"""Exercise the FastAPI application without opening a port or using credentials."""

import argparse
import asyncio
import json
from pathlib import Path
import time
from unittest.mock import patch

import httpx

from config import settings
from evaluate_rag_offline import write_json
from main import app


def summarize_events(events):
    first = {}
    for kind, elapsed_ms in events:
        first.setdefault(kind, round(elapsed_ms, 3))
    return {'frame_count': len(events), 'first_frame_ms_by_kind': first}


async def simulate_disconnect(payload):
    role_sent = asyncio.Event()
    retrieval_started = asyncio.Event()
    retrieval_cancelled = asyncio.Event()
    body = json.dumps(payload, ensure_ascii=False).encode()
    request_delivered = False

    async def receive():
        nonlocal request_delivered
        if not request_delivered:
            request_delivered = True
            return {'type': 'http.request', 'body': body, 'more_body': False}
        await role_sent.wait()
        await retrieval_started.wait()
        return {'type': 'http.disconnect'}

    async def send(message):
        if (message['type'] == 'http.response.body' and
                b'"role": "assistant"' in message.get('body', b'')):
            role_sent.set()

    async def blocked_retrieval(query):
        retrieval_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            retrieval_cancelled.set()

    host = ('127.0.0.1', 1)
    scope = {'type': 'http', 'asgi': {'version': '3.0', 'spec_version': '2.3'},
             'http_version': '1.1', 'method': 'POST', 'scheme': 'http', 'path': '/api/chat_callback',
             'raw_path': b'/api/chat_callback', 'root_path': '', 'query_string': b'',
             'headers': [(b'authorization', b'Bearer offline-test'), (b'content-type', b'application/json')],
             'client': host, 'server': host}
    with patch('main.rag_service.retrieve', side_effect=blocked_retrieval):
        async with asyncio.timeout(2):
            await app(scope, receive, send)
    assert role_sent.is_set() and retrieval_cancelled.is_set()
    return {'role_sent': True, 'retrieval_cancelled': True}


async def smoke():
    callback_events = []
    callback_started = None

    async def observe(scope, receive, send):
        async def observe_send(message):
            if scope['path'] == '/api/chat_callback' and message['type'] == 'http.response.body':
                for line in message.get('body', b'').decode().splitlines():
                    if line.startswith('data: '):
                        raw = line[6:]
                        if raw == '[DONE]':
                            kind = 'done'
                        else:
                            choice = json.loads(raw)['choices'][0]
                            kind = ('role' if choice['delta'].get('role') else
                                    'content' if choice['delta'].get('content') else choice['finish_reason'])
                        callback_events.append((kind, 1000 * (time.perf_counter() - callback_started)))
            await send(message)
        await app(scope, receive, observe_send)

    stub_settings = dict(KB_MODE='sample', MOCK_MODE=True, CALLBACK_API_KEY='offline-test',
                         ARK_API_KEY='offline-test', ARK_ENDPOINT_ID='offline-test',
                         RTC_APP_ID='', RTC_APP_KEY='', VOLC_AK='', VOLC_SK='', SERVER_URL='')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=observe), base_url='http://test') as client:
        with patch.multiple(settings, **stub_settings):
            health = await client.get('/health')
            health.raise_for_status()
            assert health.json()['mock'] and health.json()['knowledge_mode'] == 'sample'
            knowledge = await client.get('/debug/knowledge')
            knowledge.raise_for_status()
            assert knowledge.json()['knowledge_units'] == 89
            retrieval = []
            for query, mode, expected in (
                ('SC-PB27多重？', 'catalog_exact', 'ecommerce_demo_v1_1_3'),
                ('表能带着洗澡吗', 'catalog_category', 'ecommerce_demo_v1_2_12'),
                ('SC-PB999多重？', 'unknown_sku', None),
                ('退款多久能到账？', 'sample_lexical', 'ecommerce_demo_v1_0_13'),
            ):
                response = await client.get('/debug/rag', params={'query': query})
                response.raise_for_status()
                result = response.json()
                assert result['retrieval_mode'] == mode
                ids = [source['id'] for source in result['sources']]
                assert (expected in ids) if expected else not ids
                retrieval.append({'question': query, 'mode': mode, 'ids': ids, 'version': result['version']})
            reply = await client.post('/debug/chat', json={'question': '我买的那单到底能不能退？'})
            reply.raise_for_status()
            assert '没有接入订单' in reply.text and '订单页' in reply.text

            payload = {'messages': [{'role': 'user', 'content': '我买的那单到底能不能退？'}]}
            unauthorized = await client.post('/api/chat_callback', json=payload)
            assert unauthorized.status_code == 401
            callback_started = time.perf_counter()
            authorized = await client.post('/api/chat_callback', json=payload,
                                           headers={'Authorization': 'Bearer offline-test'})
            authorized.raise_for_status()
            assert '没有接入订单' in authorized.text
            assert [kind for kind, _ in callback_events] == ['role', 'content', 'stop', 'done']
            events = {'normal': summarize_events(callback_events)}
            callback_events.clear()
            callback_started = time.perf_counter()
            with patch('main.rag_service.retrieve', side_effect=TimeoutError):
                payload['messages'][0]['content'] = '退款多久能到账？'
                fail = await client.post('/api/chat_callback', json=payload,
                                         headers={'Authorization': 'Bearer offline-test'})
            fail.raise_for_status()
            assert '暂时不可用' in fail.text
            assert [kind for kind, _ in callback_events] == ['role', 'content', 'stop', 'done']
            events['injected_timeout'] = summarize_events(callback_events)
            disconnected = await simulate_disconnect(payload)
            callback_events.clear()
            callback_started = time.perf_counter()
            retried = await client.post('/api/chat_callback', json=payload,
                                        headers={'Authorization': 'Bearer offline-test'})
            retried.raise_for_status()
            assert '暂时不可用' not in retried.text
            assert callback_events[0][0] == 'role' and callback_events[-1][0] == 'done'
            events['client_retry'] = summarize_events(callback_events)
    return {'mode': 'ASGI in-process / sample / mock', 'port': None, 'external_database': None,
            'health': health.json(), 'knowledge_units': knowledge.json()['knowledge_units'],
            'retrieval': retrieval, 'chat': reply.text, 'callback_without_auth': 401,
            'callback_app_send_elapsed_ms': events, 'simulated_disconnect': disconnected,
            'audible_audio_ms': None}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    write_json(args.out, asyncio.run(smoke()))
