"""Protocol, corpus isolation, embedding compatibility and semantic routing tests."""
import json
import unittest
from unittest.mock import AsyncMock, patch
import httpx
from config import settings
from services.milvus_service import (EmbeddingService, MilvusService, corpus_digest,
                                     embedding_profile, validate_vector)
from services.rag_service import rag_service, corpus


class MilvusTests(unittest.IsolatedAsyncioTestCase):
    async def test_incompatible_existing_collection_is_not_modified(self):
        service = MilvusService()
        description = {'fields': [{'name': 'id'}, {'name': 'vector',
            'params': [{'key': 'dim', 'value': '1024'}]}], 'indexes': []}
        with patch.object(settings, 'EMBEDDING_DIMENSIONS', 2048), \
                patch.object(service, 'request', AsyncMock(side_effect=[{'has': True}, description])) as request:
            with self.assertRaises(ValueError):
                await service.ensure_collection()
            self.assertEqual([x.args[0] for x in request.call_args_list], ['collections/has', 'collections/describe'])

    async def test_health_reports_missing_or_offline_milvus(self):
        from main import app
        with patch.multiple(settings, KB_MODE='milvus', RTC_APP_ID='test', RTC_APP_KEY='test',
                VOLC_AK='test', VOLC_SK='test', ARK_API_KEY='test', ARK_ENDPOINT_ID='test',
                SERVER_URL='https://example.test', CALLBACK_API_KEY='test',
                EMBEDDING_MODEL='test', EMBEDDING_API_KEY='test'), \
                patch('main.milvus_service.count', AsyncMock(side_effect=RuntimeError('offline'))):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                response = await client.get('/health')
                self.assertFalse(response.json()['ready'])
                self.assertFalse(response.json()['knowledge_ready'])

    async def test_embedding_formats_cache_dimension_and_key_rotation(self):
        for path, data in [('/embeddings', [{'embedding': [3, 4]}]),
                           ('/embeddings/multimodal', {'embedding': [3, 4]})]:
            service = EmbeddingService()
            calls = []

            def respond(request):
                calls.append(json.loads(request.content))
                self.assertEqual(request.headers['Authorization'], 'Bearer test-key')
                return httpx.Response(200, json={'data': data})

            client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
            with patch.multiple(settings, EMBEDDING_MODEL='test', EMBEDDING_DIMENSIONS=2,
                                EMBEDDING_API_KEY='test-key', EMBEDDING_API_PATH=path), \
                    patch('services.milvus_service.httpx.AsyncClient', return_value=client):
                self.assertEqual(await service.encode('退货条件'), [0.6, 0.8])
                cached = await service.encode('退货条件')
                cached[0] = 0
                self.assertEqual(await service.encode('退货条件'), [0.6, 0.8])
                self.assertEqual(len(calls), 1)
                expected = [{'type': 'text', 'text': '退货条件'}] if path.endswith('multimodal') else ['退货条件']
                self.assertEqual(calls[0]['input'], expected)

    def test_invalid_vectors_rejected(self):
        with patch.object(settings, 'EMBEDDING_DIMENSIONS', 2):
            for vector in (None, [1], [0, 0], [float('nan'), 1], [True, 1], ['1', 1]):
                with self.assertRaises(ValueError):
                    validate_vector(vector)

    async def test_semantic_routing_bypasses_lexical_gate_and_preserves_exact_sku(self):
        hit = next(x for x in corpus()['chunks'] if x['kind'] == 'rule')
        with patch.object(settings, 'KB_MODE', 'milvus'), \
                patch('services.rag_service.relevance', return_value=0), \
                patch('services.rag_service.milvus_service.search', AsyncMock(return_value=[hit])) as search:
            result = await rag_service.search('买了之后又反悔了咋整')
            self.assertEqual(result['retrieval_mode'], 'milvus')
            self.assertTrue(result['context'])
            search.reset_mock()
            self.assertEqual((await rag_service.search('SC-PB27多重'))['retrieval_mode'], 'catalog_exact')
            self.assertEqual((await rag_service.search('SC-PB999多重'))['retrieval_mode'], 'unknown_sku')
            search.assert_not_awaited()

    async def test_scope_threshold_and_returned_evidence_validation(self):
        data = corpus()
        chunk = data['chunks'][0]
        base = {'chunk_id': chunk['id'], 'doc_id': chunk['doc_id'], 'content': chunk['content'],
                'corpus_hash': corpus_digest(data), 'embedding_profile': embedding_profile(), 'distance': 0.8}
        rows = [base, {**base, 'distance': 0.1}, {**base, 'corpus_hash': 'old'},
                {**base, 'embedding_profile': 'other-model'}, {**base, 'doc_id': 'other-course'},
                {**base, 'content': 'injected'}, {**base, 'distance': float('nan')}]
        service = MilvusService()
        with patch('services.milvus_service.embedding_service.encode', AsyncMock(return_value=[1, 0])), \
                patch.object(service, 'request', AsyncMock(return_value=rows)) as request:
            hits = await service.search('退货', data)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]['content'], chunk['content'])
        self.assertIn(corpus_digest(data), request.call_args.args[1]['filter'])
        self.assertIn(embedding_profile(), request.call_args.args[1]['filter'])

    async def test_milvus_application_error_does_not_silently_fallback(self):
        client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={'code': 100, 'message': 'missing collection'})))
        with patch('services.milvus_service.httpx.AsyncClient', return_value=client):
            with self.assertRaises(RuntimeError):
                await MilvusService().request('collections/describe')

    async def test_no_semantic_evidence_and_backend_failure(self):
        with patch.object(settings, 'KB_MODE', 'milvus'), \
                patch('services.rag_service.milvus_service.search', AsyncMock(return_value=[])):
            self.assertEqual((await rag_service.search('售后政策'))['retrieval_mode'], 'no_results')
        with patch.object(settings, 'KB_MODE', 'milvus'), \
                patch('services.rag_service.milvus_service.search', AsyncMock(side_effect=RuntimeError('offline'))):
            with self.assertRaises(RuntimeError):
                await rag_service.search('售后政策')

    async def test_import_ids_stable_and_no_destructive_operations(self):
        service = MilvusService()
        sample = {'documents': [], 'chunks': [{'id': 'one', 'heading': '规则', 'content': '示例规则'}]}
        with patch.multiple(settings, EMBEDDING_MODEL='test', EMBEDDING_API_KEY='test'), \
                patch('services.milvus_service.embedding_service.encode', AsyncMock(return_value=[1, 0])), \
                patch.object(service, 'ensure_collection', AsyncMock()), \
                patch.object(service, 'count', AsyncMock(side_effect=[0, 1, 0, 1])), \
                patch.object(service, 'request', AsyncMock(return_value={'upsertCount': 1})) as request:
            await service.sync(sample)
            first_id = request.call_args.args[1]['data'][0]['id']
            await service.sync(sample)
            self.assertEqual(first_id, request.call_args.args[1]['data'][0]['id'])
            self.assertTrue(all(x.args[0] == 'entities/upsert' for x in request.call_args_list))


if __name__ == '__main__':
    unittest.main()
