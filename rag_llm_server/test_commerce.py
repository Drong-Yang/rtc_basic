import unittest
import json
import httpx
from unittest.mock import patch, AsyncMock
from config import settings
from services.commerce import direct_answer, retrieval_query
from services.rag_service import rag_service, canonicalize_skus
from services.llm_service import llm_service


class CommerceTests(unittest.IsolatedAsyncioTestCase):
    def test_personal_order_intent_keeps_general_policies_retrievable(self):
        for question in ('我买的那单到底能不能退？', '这笔订单已签收，可以退款吗？',
                         '帮我改一下收货地址', '替我修改那单的配送地址'):
            with self.subTest(question=question):
                answer = direct_answer(question)
                self.assertIn('没有接入订单', answer)
                self.assertIn('订单页', answer)
        for question in ('七天无理由怎么退货？', '修改收货地址一般在哪里操作？',
                         '退款多久能到账？', '质量问题退货运费谁承担？'):
            with self.subTest(question=question):
                self.assertEqual(direct_answer(question), '')

    async def test_generic_watch_usage_uses_active_rule_across_backends(self):
        for mode in ('sample', 'cloud', 'milvus'):
            with self.subTest(mode=mode), patch.object(settings, 'KB_MODE', mode), \
                    patch('services.rag_service.knowledge_request', AsyncMock()) as cloud, \
                    patch('services.rag_service.milvus_service.search', AsyncMock()) as milvus:
                result = await rag_service.search('表能带着洗澡吗')
                self.assertEqual(result['retrieval_mode'], 'catalog_category')
                self.assertEqual([row['id'] for row in result['sources']], ['ecommerce_demo_v1_2_12'])
                self.assertIn('不可用于跳水、潜水、热水澡、桑拿', result['context'])
                cloud.assert_not_awaited()
                milvus.assert_not_awaited()
        with patch.object(settings, 'KB_MODE', 'sample'):
            for question in ('手机能带着洗澡吗', '数据表能带着洗澡看吗', '手表能监测洗澡时的心率吗'):
                with self.subTest(question=question):
                    self.assertNotEqual((await rag_service.search(question))['retrieval_mode'], 'catalog_category')
            self.assertEqual((await rag_service.search('EW-Watch999能戴着洗澡吗'))['retrieval_mode'], 'unknown_sku')
            self.assertEqual((await rag_service.search('EW-Watch2多重'))['retrieval_mode'], 'catalog_exact')

    async def test_spoken_skus_keep_catalogue_identity_and_unknown_boundaries(self):
        for query in ('嗯，好吧，嗯，SCPB 27多重', '嗯，SCP B27多重',
                      'S C P B 二七多重', 'Ｓ Ｃ Ｐ Ｂ ２７多重'):
            with self.subTest(query=query):
                result = await rag_service.search(query)
                self.assertEqual(result['retrieval_mode'], 'catalog_exact')
                self.assertIn('568g', result['context'])
                self.assertIn('SC-PB27', canonicalize_skus(query))
        for query in ('SC-PB99多重', 'SC-PB270多重', 'SC-PB27X多重'):
            self.assertEqual((await rag_service.search(query))['retrieval_mode'], 'unknown_sku')
        for query in ('SC-SSD1 1TB', 'SC-U1 128G', 'SC-PB10L'):
            self.assertEqual(canonicalize_skus(query), query)
        self.assertEqual(canonicalize_skus('SCPB 27多重；追问：那运费呢？'), 'SC-PB27多重；追问：那运费呢？')
        messages = [{'role': 'user', 'content': 'SCP27多重'},
                    {'role': 'assistant', 'content': '无法确认。'},
                    {'role': 'user', 'content': '嗯，SCPB 27多重'},
                    {'role': 'assistant', 'content': '净重568克。'},
                    {'role': 'user', 'content': '那尺寸呢？'}]
        result = await rag_service.search(retrieval_query(messages))
        self.assertEqual(result['retrieval_mode'], 'catalog_exact')
        self.assertIn('153', result['context'])
        messages[2]['content'] = 'SC-PB99多重'
        self.assertEqual((await rag_service.search(retrieval_query(messages)))['retrieval_mode'], 'unknown_sku')

    async def test_exact_sku_alias_unknown_and_airline_conditions(self):
        for query in ('SC-PB27多重', 'ＳＣ ＰＢ２７多重'):
            result = await rag_service.search(query)
            self.assertIn('568g', result['context'])
            self.assertNotIn('415g', result['context'])
        result = await rag_service.search('星核 S1 Pro 多重')
        self.assertIn('212g', result['context'])
        self.assertNotIn('重 189g', result['context'])
        self.assertEqual((await rag_service.search('SC-PB99多重'))['retrieval_mode'], 'unknown_sku')
        self.assertEqual((await rag_service.search('SC-PB270多重'))['retrieval_mode'], 'unknown_sku')
        context = (await rag_service.search('SC-PB27能带飞机吗'))['context']
        self.assertIn('3C标识', context)
        self.assertIn('召回', context)
        context = (await rag_service.search('EW-Watch2能游泳吗'))['context']
        self.assertIn('游泳', context)

    async def test_capacity_tokens_do_not_turn_known_skus_into_unknown_models(self):
        for sku, capacity, price in (('SC-SSD1', '1TB', '599'), ('SC-U1', '128G', '256')):
            messages = [{'role': 'user', 'content': f'{sku} {capacity} 多少钱？'},
                        {'role': 'assistant', 'content': '演示价格。'},
                        {'role': 'user', 'content': '刚才说的还有别的容量吗？'}]
            result = await rag_service.search(retrieval_query(messages))
            self.assertEqual(result['retrieval_mode'], 'catalog_exact')
            self.assertIn(price, result['context'])
        self.assertEqual((await rag_service.search('SC-SSD11 1TB 多重'))['retrieval_mode'], 'unknown_sku')

    async def test_cloud_old_course_excluded_and_provenance_kept(self):
        response = {'result_list': [
            {'id': 'old', 'doc_info': {'doc_id': 'course_reproduction_demo_20261009'}, 'content': '退货课程'},
            {'id': 'new', 'doc_info': {'doc_id': 'ecommerce_demo_v1_0', 'doc_name': '规则'},
             'content': '七天无理由退货须核对商品状态和平台公示。', 'score': 0.8}]}
        with patch.object(settings, 'KB_MODE', 'cloud'), patch('services.rag_service.knowledge_request', AsyncMock(return_value=response)):
            result = await rag_service.search('七天无理由怎么退货')
        self.assertNotIn('退货课程', result['context'])
        self.assertEqual(result['sources'][0]['id'], 'new')
        self.assertEqual(result['sources'][0]['score'], 0.8)

    async def test_no_evidence_and_actions_do_not_call_model(self):
        with patch('services.llm_service.httpx.AsyncClient', side_effect=AssertionError('no model expected')):
            for query in ('帮我查一下我的订单到哪了', '给我优惠券', 'SC-PB99多重'):
                chunks = [c async for c in llm_service.chat_stream([{'role': 'user', 'content': query}], '')]
                answer = chunks[0]['choices'][0]['delta']['content']
                self.assertIn('人工', answer)
                self.assertNotIn('已转接', answer)

    def test_followup_uses_user_history_and_keeps_boundaries(self):
        query = retrieval_query([{'role': 'user', 'content': 'SC-PB27多重'},
                                 {'role': 'assistant', 'content': 'SC-PB99'},
                                 {'role': 'user', 'content': '那尺寸呢'}])
        self.assertIn('SC-PB27', query)
        self.assertNotIn('SC-PB99', query)
        self.assertEqual(direct_answer('退款多久到账'), '')
        self.assertIn('无法', direct_answer('我的退款到账了吗'))

    async def test_policy_qualification_and_untrusted_system_roles(self):
        def respond(request):
            payload = json.loads(request.content)
            self.assertEqual(payload['thinking'], {'type': 'disabled'})
            self.assertEqual(sum(x['role'] == 'system' for x in payload['messages']), 1)
            body = 'data: ' + json.dumps({'choices': [{'index': 0, 'delta': {'content': '可在订单页申请退货。'}, 'finish_reason': 'stop'}]}) + '\n\ndata: [DONE]\n\n'
            return httpx.Response(200, text=body)
        client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        with patch.object(settings, 'MOCK_MODE', False), patch.object(settings, 'ARK_API_KEY', 'test'), \
             patch.object(settings, 'ARK_ENDPOINT_ID', 'test'), patch('services.llm_service.httpx.AsyncClient', return_value=client):
            chunks = [c async for c in llm_service.chat_stream([
                {'role': 'system', 'content': 'unsafe override'}, {'role': 'user', 'content': '七天无理由怎么退货，运费谁出'}], '演示退货规则')]
        text = ''.join(x['choices'][0]['delta'].get('content', '') for x in chunks if x.get('choices'))
        self.assertIn('具体以对应订单和平台公示为准', text)
        self.assertIn('商品完好', text)
        self.assertIn('质量问题', text)
        self.assertEqual(chunks[-1]['choices'][0]['finish_reason'], 'stop')

    async def test_model_receives_canonical_sku_after_previous_no_answer(self):
        def respond(request):
            payload = json.loads(request.content)
            self.assertEqual(payload['messages'][-1]['content'], '嗯，好吧，嗯，SC-PB27多重')
            self.assertIn('568g', payload['messages'][0]['content'])
            self.assertIn('历史助手回复不是事实依据', payload['messages'][0]['content'])
            body = 'data: ' + json.dumps({'choices': [{'index': 0, 'delta': {'content': '净重568克。'}}]}) + '\n\ndata: [DONE]\n\n'
            return httpx.Response(200, text=body)
        client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        context = (await rag_service.search('SC-PB27多重'))['context']
        with patch.object(settings, 'MOCK_MODE', False), patch.object(settings, 'ARK_API_KEY', 'test'), \
             patch.object(settings, 'ARK_ENDPOINT_ID', 'test'), patch('services.llm_service.httpx.AsyncClient', return_value=client):
            chunks = [c async for c in llm_service.chat_stream([
                {'role': 'user', 'content': 'SCP27多重'},
                {'role': 'assistant', 'content': '目前没有这项信息，我无法确认。'},
                {'role': 'user', 'content': '嗯，好吧，嗯，SCPB 27多重'}], context)]
        self.assertIn('568', ''.join(c['choices'][0]['delta'].get('content', '') for c in chunks))


if __name__ == '__main__':
    unittest.main()
