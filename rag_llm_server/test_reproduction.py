import asyncio
import base64
import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock
from types import SimpleNamespace
import httpx
from main import app, sessions, chat_callback, rtc_events, voice_config, safe_rtc_description
from config import settings
from services.token_build import AccessToken, PRIVILEGES


class VoiceTests(unittest.IsolatedAsyncioTestCase):
    def test_token_matches_official_reference(self):
        # Synthetic fixed vector from volcengine/rtc-aigc-embedded-demo,
        # server/src/AccessToken.py. Add privileges out of numeric order.
        token = AccessToken('0' * 24, 'synthetic-test-key', 'room_demo', 'user_demo')
        token.nonce = 1234
        token.issued_at = 1700000000
        token.expire_time(4102444800)
        token.add_privilege(PRIVILEGES['PrivSubscribeStream'], 0)
        token.add_privilege(PRIVILEGES['PrivPublishStream'], 0)
        self.assertEqual(token.serialize(),
            '001000000000000000000000000QgDSBAAAAPFTZQBXhvQJAHJvb21fZGVtbwkAdXNlcl9kZW1vBQAAAAAAAAABAAAAAAACAAAAAAADAAAAAAAEAAAAAAAgACRbdjc0qhgTUYwv++FFAoN1RRAlx4LWGXLfNq22pXv8')

    async def asyncSetUp(self):
        sessions.clear()
        rtc_events.clear()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test')
        self.patches = [patch.object(settings, name, value) for name,value in {
            'RTC_APP_ID':'testapp', 'RTC_APP_KEY':'testkey', 'MOCK_MODE':True,
            'KB_MODE':'sample', 'CALLBACK_API_KEY':'callback-test',
            'ARK_API_KEY':'synthetic-test', 'ARK_ENDPOINT_ID':'test-model'}.items()]
        for p in self.patches: p.start()

    async def asyncTearDown(self):
        await self.client.aclose()
        for p in self.patches: p.stop()

    async def test_unique_sessions_and_signed_tokens(self):
        one=(await self.client.post('/getScenes')).json()['Result']['scenes'][0]
        two=(await self.client.post('/getScenes')).json()['Result']['scenes'][0]
        self.assertNotEqual(one['rtc']['RoomId'],two['rtc']['RoomId'])
        self.assertTrue(one['rtc']['Token'].startswith('001testapp'))
        key=one['scene']['id']
        self.assertEqual((await self.client.post('/proxy?Action=StartVoiceChat',json={'SceneID':key})).status_code,503)
        outgoing=[]
        async def upstream(action, body):
            outgoing.append((action,body))
            return {'ResponseMetadata':{'Action':action},'Result':{}}
        with patch('main.rtc_request',upstream),patch('main.voice_config',return_value={}),patch.object(settings,'MOCK_MODE',False):
            for action in ['StartVoiceChat','StartVoiceChat','StopVoiceChat','StartVoiceChat']:
                r=await self.client.post('/proxy?Action='+action,json={'SceneID':key})
                self.assertEqual(r.status_code,200)
        self.assertEqual(len(outgoing),3)
        self.assertEqual(outgoing[0][1]['RoomId'],one['rtc']['RoomId'])
        self.assertEqual(outgoing[0][1]['AgentConfig']['TargetUserId'],[one['rtc']['UserId']])
        self.assertEqual(outgoing[0][1]['TaskId'],outgoing[1][1]['TaskId'])

    def test_asr_passthrough_requires_json_parameters(self):
        config = {'ASRConfig': {'ProviderParams': {'Mode': 'bigmodel',
                  'Credential': {'ApiResourceId': 'volc.seedasr.sauc.duration'}}}}
        path = Path('synthetic-voice.json')
        with patch.object(Path, 'exists', return_value=True), patch.object(settings, 'VOICE_CONFIG_FILE', path), patch.object(settings, 'SERVER_URL', 'https://example.invalid'):
            with patch.object(Path, 'read_text', return_value=json.dumps(config)):
                with self.assertRaisesRegex(ValueError, 'VolcanoASRParameters'):
                    voice_config()
            config['ASRConfig']['ProviderParams']['VolcanoASRParameters'] = '{}'
            with patch.object(Path, 'read_text', return_value=json.dumps(config)):
                self.assertEqual(voice_config()['ASRConfig']['ProviderParams']['VolcanoASRParameters'], '{}')
        self.assertNotIn('callback-test', safe_rtc_description('invalid callback-test'))

    async def test_callback_auth_and_sse(self):
        body={'messages':[{'role':'user','content':'七天无理由怎么退货'}]}
        r=await self.client.post('/api/chat_callback',json=body)
        self.assertEqual(r.status_code,401)
        r=await self.client.post('/api/chat_callback',json=body,headers={'Authorization':'Bearer callback-test'})
        self.assertEqual(r.status_code,200)
        self.assertIn('text/event-stream',r.headers['content-type'])
        chunks=[json.loads(l[6:]) for l in r.text.splitlines() if l.startswith('data: ') and l!='data: [DONE]']
        text=''.join(c['choices'][0]['delta'].get('content', '') for c in chunks)
        self.assertIn('模拟',text);self.assertIn('无理由',text)
        self.assertTrue(r.text.endswith('data: [DONE]\n\n'))

    async def test_rtc_status_auth_and_tlv_validation(self):
        from main import rtc_event_signature
        event = json.dumps({'TaskId': 'synthetic-task', 'Stage': {'Code': 0},
                            'ErrorInfo': {'Code': 1001, 'Reason': 'not retained'}}).encode()
        body = {'message': base64.b64encode(b'conv' + len(event).to_bytes(4, 'big') + event).decode()}
        self.assertEqual((await self.client.post('/api/rtc_events', json=body)).status_code, 401)
        body['signature'] = rtc_event_signature()
        self.assertEqual((await self.client.post('/api/rtc_events', content=json.dumps(body))).status_code, 200)
        saved = (await self.client.get('/debug/rtc')).json()['events'][0]
        self.assertEqual(saved['stage'], 0)
        self.assertEqual(saved['error_code'], 1001)
        self.assertNotIn('Reason', saved)
        body['message'] = base64.b64encode(b'conv' + b'\x00' * 4 + event).decode()
        self.assertEqual((await self.client.post('/api/rtc_events', json=body)).status_code, 422)

    async def test_missing_config_unknown_session_and_no_results(self):
        with patch.object(settings,'RTC_APP_KEY',''):
            self.assertEqual((await self.client.post('/getScenes')).status_code,503)
        self.assertEqual((await self.client.post('/proxy?Action=StartVoiceChat',json={'SceneID':'missing'})).status_code,404)
        r=await self.client.get('/debug/rag',params={'query':'火星天气'})
        self.assertEqual(r.json()['status'],'no_results')

    async def test_upstream_failure_is_http_error(self):
        async def failure(*args): raise httpx.ReadTimeout('test')
        with patch('main.rag_service.retrieve',failure):
            r=await self.client.post('/debug/chat',json={'question':'课程'})
            self.assertEqual(r.status_code,502)

    async def test_callback_flushes_before_slow_knowledge_lookup(self):
        retrieve = AsyncMock(return_value='demo')
        request = SimpleNamespace(headers={'Authorization': 'Bearer callback-test'},
            json=AsyncMock(return_value={'messages': [{'role': 'user', 'content': '课程'}]}))
        with patch('main.rag_service.retrieve', retrieve):
            response = await chat_callback(request)
            first = await anext(response.body_iterator)
            self.assertIn('assistant', first)
            retrieve.assert_not_awaited()
            await response.body_iterator.aclose()

    async def test_callback_normalizes_reasoning_and_reports_service_failure(self):
        async def upstream(*args):
            yield {'choices': [{'delta': {'reasoning_content': 'private reasoning'}}]}
            yield {'choices': [{'delta': {'content': '演示课程'}}]}
            yield {'choices': [], 'usage': {'total_tokens': 3}}
        body = {'messages': [{'role': 'user', 'content': '课程'}]}
        headers = {'Authorization': 'Bearer callback-test'}
        with patch('main.llm_service.chat_stream', upstream):
            r = await self.client.post('/api/chat_callback', json=body, headers=headers)
        chunks = [json.loads(line[6:]) for line in r.text.splitlines()
                  if line.startswith('data: ') and line != 'data: [DONE]']
        self.assertEqual(len({x['id'] for x in chunks}), 1)
        self.assertTrue(all(x['object'] == 'chat.completion.chunk' for x in chunks))
        self.assertNotIn('reasoning', r.text)
        self.assertIn('演示课程', r.text)
        with patch('main.rag_service.retrieve', side_effect=httpx.ReadTimeout('test')):
            r = await self.client.post('/api/chat_callback', json=body, headers=headers)
        self.assertIn('暂时不可用', r.text)
        self.assertTrue(r.text.endswith('data: [DONE]\n\n'))


if __name__=='__main__': unittest.main()
