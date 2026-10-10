"""RTC control plane and OpenAI-compatible RAG streaming callback."""
import asyncio
import base64
import hashlib
import copy
import json
import logging
import re
import secrets
import time
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from config import settings
from services.llm_service import llm_service
from services.rag_service import rag_service
from services.token_build import AccessToken, PRIVILEGES
from services.utils import Signer
from services.commerce import direct_answer, retrieval_query

# A single worker owns local demo sessions. Their IDs survive start/stop but expire with the RTC token.
sessions = {}
rtc_events = {}
logger = logging.getLogger('uvicorn.error')


@asynccontextmanager
async def lifespan(app):
    yield


app = FastAPI(title='语音客服', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:3000', 'http://127.0.0.1:3000'],
                   allow_methods=['GET', 'POST'], allow_headers=['*'])


def envelope(action, result=None, error=None):
    metadata = {'Action': action}
    if error:
        metadata['Error'] = {'Code': 'RequestFailed', 'Message': error}
    return {'ResponseMetadata': metadata, 'Result': result or {}}


@app.get('/health')
async def health():
    required = ['RTC_APP_ID', 'RTC_APP_KEY', 'VOLC_AK', 'VOLC_SK', 'ARK_API_KEY',
                'ARK_ENDPOINT_ID', 'SERVER_URL', 'CALLBACK_API_KEY']
    if settings.KB_MODE == 'cloud':
        required += ['VOLC_ACCOUNT_ID', 'KB_COLLECTION_NAME']
    missing = [name for name in required if not getattr(settings, name, '')]
    return {'status': 'running', 'ready': not missing, 'mock': settings.MOCK_MODE,
            'knowledge_mode': settings.KB_MODE, 'missing': missing}


@app.post('/getScenes')
async def get_scenes():
    try:
        settings.require('RTC_APP_ID', 'RTC_APP_KEY')
        now = time.time()
        for key in list(sessions):
            if sessions[key]['expires'] < now:
                del sessions[key]
        if len(sessions) >= 100:
            raise ValueError('会话数量已达上限，请稍后重试')
        key = uuid.uuid4().hex
        session = {'AppId': settings.RTC_APP_ID, 'RoomId': 'room_' + key,
                   'UserId': 'user_' + key[:16], 'TaskId': 'task_' + key,
                   'expires': now + 3600, 'started': False, 'lock': asyncio.Lock()}
        sessions[key] = session
        builder = AccessToken(settings.RTC_APP_ID, settings.RTC_APP_KEY, session['RoomId'], session['UserId'])
        builder.add_privilege(PRIVILEGES['PrivSubscribeStream'], 0)
        builder.add_privilege(PRIVILEGES['PrivPublishStream'], 0)
        builder.expire_time(int(session['expires']))
        rtc = {name: session[name] for name in ('AppId', 'RoomId', 'UserId')}
        rtc['Token'] = builder.serialize()
        return envelope('getScenes', {'scenes': [{
            'scene': {'id': key, 'name': '星核数码 · 3C购物助手', 'botName': 'AiAgent',
                      'icon': '', 'isInterruptMode': True, 'isVision': False,
                      'isScreenMode': False, 'isAvatarScene': False, 'avatarBgUrl': ''},
            'rtc': rtc, 'VoiceChat': {}}]})
    except ValueError as exc:
        return JSONResponse(envelope('getScenes', error=str(exc)), status_code=503)


def voice_config():
    path = settings.VOICE_CONFIG_FILE
    if not path.exists():
        raise ValueError('请从 voice_config.example.json 创建 voice_config.json')
    config = copy.deepcopy(json.loads(path.read_text(encoding='utf-8-sig')))
    asr = config.get('ASRConfig', {}).get('ProviderParams', {})
    if asr.get('Mode') == 'bigmodel' and asr.get('Credential'):
        if 'VolcanoASRParameters' not in asr:
            raise ValueError('ASR 透传配置缺少 VolcanoASRParameters，请填入字符串 "{}" 或有效 JSON 参数')
        if not isinstance(asr['VolcanoASRParameters'], str) or not isinstance(json.loads(asr['VolcanoASRParameters']), dict):
            raise ValueError('VolcanoASRParameters 必须是 JSON 对象字符串')
    settings.require('SERVER_URL', 'CALLBACK_API_KEY', 'ARK_API_KEY', 'ARK_ENDPOINT_ID')
    if not settings.SERVER_URL.startswith('https://'):
        raise ValueError('SERVER_URL 必须是云端可访问的 HTTPS 地址')
    config['LLMConfig'] = {'Mode': 'CustomLLM', 'Url': settings.SERVER_URL + '/api/chat_callback',
                           'APIKey': settings.CALLBACK_API_KEY, 'ModelName': settings.ARK_ENDPOINT_ID}
    return config


async def rtc_request(action, body):
    settings.require('VOLC_AK', 'VOLC_SK')
    host = 'rtc.volcengineapi.com'
    params = {'Action': action, 'Version': settings.RTC_API_VERSION}
    data = {'method': 'POST', 'path': '/', 'params': params,
            'headers': {'Host': host, 'Content-Type': 'application/json'}, 'body': body}
    Signer(data, 'rtc').add_authorization(
        {'accessKeyId': settings.VOLC_AK, 'secretKey': settings.VOLC_SK})
    # Sign and send the identical serialized bytes.
    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        response = await client.post('https://' + host + '/', params=params,
                                     headers=data['headers'], content=json.dumps(body).encode('utf-8'))
        response.raise_for_status()
    return response.json()


@app.post('/proxy')
async def proxy(request: Request):
    action = request.query_params.get('Action', '')
    if action not in ('StartVoiceChat', 'StopVoiceChat'):
        return JSONResponse(envelope(action, error='不支持的 Action'), status_code=400)
    try:
        body = await request.json()
        session = sessions.get(body.get('SceneID'))
        if session is None or session['expires'] < time.time():
            return JSONResponse(envelope(action, error='会话已过期，请刷新页面重新获取'), status_code=404)
        if settings.MOCK_MODE:
            return JSONResponse(envelope(action, error='模拟模式仅验证文本和界面流程；真实 RTC 通话请使用非模拟模式启动'), status_code=503)
        async with session['lock']:
            starting = action == 'StartVoiceChat'
            if session['started'] == starting:
                return envelope(action, {'TaskId': session['TaskId']})
            outgoing = {name: session[name] for name in ('AppId', 'RoomId', 'TaskId')}
            if starting:
                outgoing.update({'AgentConfig': {'TargetUserId': [session['UserId']],
                    'EnableConversationStateCallback': True,
                    'ServerMessageURLForRTS': settings.SERVER_URL + '/api/rtc_events',
                    'ServerMessageSignatureForRTS': rtc_event_signature(),
                    'UserId': 'AiAgent', 'WelcomeMessage': '您好，我是星核数码购物助手。这里的商品是演示数据，您可以问我商品参数和购物售后规则。'},
                    'Config': voice_config()})
            result = await rtc_request(action, outgoing)
            if not result.get('ResponseMetadata', {}).get('Error'):
                session['started'] = starting
            return result
    except (ValueError, httpx.HTTPError) as exc:
        message = str(exc) if isinstance(exc, ValueError) else 'RTC 请求失败，请检查网络、账户权限和配额'
        return JSONResponse(envelope(action, error=message), status_code=502)


def rtc_event_signature():
    settings.require('CALLBACK_API_KEY')
    return hashlib.sha256(('rtc-events:' + settings.CALLBACK_API_KEY).encode()).hexdigest()


def safe_rtc_description(value):
    value = str(value)
    for name in ('CALLBACK_API_KEY', 'ARK_API_KEY', 'RTC_APP_KEY', 'VOLC_AK', 'VOLC_SK'):
        secret = getattr(settings, name, '')
        if secret:
            value = value.replace(secret, '[redacted]')
    value = re.sub(r'(?i)(bearer\s+|token[\s:=]+|key[\s:=]+)\S+', '[redacted]', value)
    return value[:800]


@app.post('/api/rtc_events')
async def receive_rtc_event(request: Request):
    # RTC sends JSON without Content-Type. Authenticate before decoding the TLV payload.
    body = await request.json()
    signature = body.get('signature', '')
    if not isinstance(signature, str) or not secrets.compare_digest(signature, rtc_event_signature()):
        raise HTTPException(401, '状态回调鉴权失败')
    try:
        raw = base64.b64decode(body.get('message', ''), validate=True)
        if len(raw) < 8 or len(raw) > 65536 or int.from_bytes(raw[4:8], 'big') != len(raw) - 8:
            raise ValueError()
        event = json.loads(raw[8:])
        if raw[:4] != b'conv':
            logger.info('RTC auxiliary event type=%s fields=%s', raw[:4].decode('ascii', errors='replace'), ','.join(event.keys()))
            return {'ok': True}
        task = str(event.get('TaskId', ''))
        code = int(event.get('Stage', {}).get('Code', -1))
        error = event.get('ErrorInfo') or {}
        # Keep status and redacted error descriptions; never signatures or transcripts.
        entry = {'task_id': task, 'stage': code, 'error_code': error.get('Code'),
                 'time': time.time(), 'description': safe_rtc_description(event.get('Stage', {}).get('Description', '')),
                 'error_reason': safe_rtc_description(error.get('Reason', '')),
                 'fields': list(event.keys()),
                 'stage_fields': list(event.get('Stage', {}).keys())}
        if len(rtc_events) >= 100:
            rtc_events.pop(next(iter(rtc_events)))
        rtc_events[uuid.uuid4().hex] = entry
        logger.info('RTC state task=%s stage=%s error_code=%s description=%s reason=%s', task, code,
                    entry['error_code'], entry['description'], entry['error_reason'])
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(422, '无效状态消息')
    return {'ok': True}


@app.get('/debug/rtc')
async def debug_rtc():
    return {'events': list(rtc_events.values())}


def validate_messages(messages):
    if not messages or messages[-1].get('role') != 'user':
        raise HTTPException(422, '最后一条消息必须为用户文本')
    if any(item.get('role') not in ('user', 'assistant', 'system') or
           not isinstance(item.get('content'), str) for item in messages):
        raise HTTPException(422, '只支持文本消息')


async def open_stream(messages):
    context = '' if direct_answer(messages[-1]['content']) else await rag_service.retrieve(retrieval_query(messages))
    stream = llm_service.chat_stream(messages, context)
    # Prime before HTTP 200, so configuration/authentication/timeout errors are proper HTTP errors.
    try:
        first = await anext(stream)
    except StopAsyncIteration:
        raise HTTPException(502, '模型返回空流')
    except ValueError as exc:
        raise HTTPException(503, str(exc))
    except httpx.HTTPError:
        raise HTTPException(502, '豆包模型调用失败，请检查 API Key、模型权限、配额及网络')
    return first, stream


@app.post('/api/chat_callback')
async def chat_callback(request: Request):
    settings.require('CALLBACK_API_KEY')
    if not secrets.compare_digest(request.headers.get('Authorization', ''),
                                  'Bearer ' + settings.CALLBACK_API_KEY):
        raise HTTPException(401, '回调鉴权失败')
    body = await request.json()
    messages = body.get('messages', [])
    validate_messages(messages)
    settings.require('ARK_API_KEY', 'ARK_ENDPOINT_ID')
    response_id = uuid.uuid4().hex
    created = int(time.time())

    def frame(delta, finish=None):
        return 'data: ' + json.dumps({
            'id': response_id, 'object': 'chat.completion.chunk', 'created': created,
            'model': settings.ARK_ENDPOINT_ID,
            'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}],
            'stream_options': {'include_usage': True}}, ensure_ascii=False) + '\n\n'

    async def generate():
        started = time.monotonic()
        chars = 0
        stream = None
        status = 'cancelled'
        stage = 'knowledge'
        try:
            # RTC gives CustomLLM only 10s to respond. Flush a valid role frame
            # before any knowledge/model I/O, including on cold connections.
            yield frame({'role': 'assistant'})
            async with asyncio.timeout(5):
                context = '' if direct_answer(messages[-1]['content']) else await rag_service.retrieve(retrieval_query(messages))
            stage = 'model'
            stream = llm_service.chat_stream(messages, context)
            async for chunk in stream:
                for choice in chunk.get('choices', []):
                    text = choice.get('delta', {}).get('content') or ''
                    if text:
                        if not chars:
                            logger.info('RTC callback id=%s first_content_ms=%d',
                                        response_id, (time.monotonic() - started) * 1000)
                        chars += len(text)
                        yield frame({'content': text})
            if not chars:
                raise RuntimeError('模型未返回可朗读文本')
            status = 'completed'
            yield frame({}, 'stop')
            yield 'data: [DONE]\n\n'
        except (httpx.HTTPError, RuntimeError, ValueError, TimeoutError) as exc:
            status = 'failed'
            logger.warning('RTC callback id=%s stage=%s error_type=%s',
                           response_id, stage, type(exc).__name__)
            yield frame({'content': '抱歉，知识库或模型服务暂时不可用，请稍后重试。'})
            yield frame({}, 'stop')
            yield 'data: [DONE]\n\n'
        finally:
            if stream is not None:
                await stream.aclose()
            logger.info('RTC callback id=%s status=%s answer_chars=%d elapsed_ms=%d',
                        response_id, status, chars, (time.monotonic() - started) * 1000)

    return StreamingResponse(generate(), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


class ChatMessage(BaseModel):
    role: str
    content: str


class DebugRequest(BaseModel):
    history: list[ChatMessage] = Field(default_factory=list)
    question: str = Field(min_length=1, max_length=4000)


@app.post('/debug/chat')
async def debug_chat(request: DebugRequest):
    messages = [item.model_dump() for item in request.history] + [{'role': 'user', 'content': request.question}]
    validate_messages(messages)
    first, stream = await open_stream(messages)

    async def generate():
        try:
            yield first.get('choices', [{}])[0].get('delta', {}).get('content', '') if first.get('choices') else ''
            async for chunk in stream:
                if chunk.get('choices'):
                    yield chunk['choices'][0].get('delta', {}).get('content', '')
        except (httpx.HTTPError, RuntimeError, ValueError):
            yield '\n[模型流中断，请重试]'
        finally:
            await stream.aclose()
    return StreamingResponse(generate(), media_type='text/plain')


@app.get('/debug/rag')
async def debug_rag(query: str):
    result = await rag_service.search(query)
    return {**result, 'retrieved_context': result['context'], 'knowledge_mode': settings.KB_MODE,
            'status': 'success' if result['context'] else 'no_results'}


@app.exception_handler(ValueError)
async def configuration_error(request, exc):
    return JSONResponse({'detail': str(exc)}, status_code=503)


@app.exception_handler(httpx.HTTPError)
async def upstream_error(request, exc):
    return JSONResponse({'detail': '外部服务请求失败，请核对配置、权限、配额及网络'}, status_code=502)


if __name__ == '__main__':
    import uvicorn
    uvicorn.run('main:app', host='127.0.0.1', port=3001)
