import json
import re
import unicodedata
import logging
import time
from functools import lru_cache
import httpx
from config import settings, ROOT
from services.utils import Signer
from services.commerce import normalize
from services.milvus_service import milvus_service
logger = logging.getLogger('uvicorn.error')


@lru_cache(maxsize=1)
def corpus():
    return json.loads((ROOT / 'knowledge/corpus.json').read_text(encoding='utf-8'))


def terms(text):
    text = normalize(text)
    return {text[i:i + 2] for i in range(len(text) - 1)}


def relevance(query, text):
    return len(terms(query) & terms(text))


async def knowledge_request(path, body):
    settings.require('VOLC_AK', 'VOLC_SK', 'VOLC_ACCOUNT_ID', 'KB_COLLECTION_NAME')
    host = 'api-knowledgebase.mlp.cn-beijing.volces.com'
    request = {'method': 'POST', 'path': path, 'body': body, 'params': {},
               'headers': {'Host': host, 'Content-Type': 'application/json',
                           'V-Account-Id': settings.VOLC_ACCOUNT_ID}}
    Signer(request, 'air').add_authorization({'accessKeyId': settings.VOLC_AK, 'secretKey': settings.VOLC_SK})
    async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
        response = await client.post('https://' + host + path, headers=request['headers'],
                                     content=json.dumps(body).encode('utf-8'))
        response.raise_for_status()
    data = response.json()
    if data.get('code') not in (None, 0, '0', 200, 'Success') or data.get('ResponseMetadata', {}).get('Error'):
        raise RuntimeError('知识库服务返回错误，请核对账户、集合及权限')
    return data.get('data', {})


class RagService:
    async def search(self, query):
        if settings.KB_MODE not in ('sample', 'cloud', 'milvus'):
            raise ValueError('KB_MODE 必须为 sample、cloud 或 milvus')
        data = corpus()
        normalized = normalize(query)
        products = [x for x in data['chunks'] if x['kind'] == 'product']
        aliases = {normalize(alias) for x in products for alias in x['aliases']}
        # Preserve token boundaries so capacity (SSD1 1TB / U1 128G) is not part of the SKU.
        explicit = [normalize(x) for x in re.findall(
            r'(?:sc|ew)[\s-]*[a-z]+[\s-]*\d+[a-z]*',
            unicodedata.normalize('NFKC', query).lower())]
        if any(x not in aliases for x in explicit):
            return self.result(query, [], 'unknown_sku')
        matched = [x for x in products if any(normalize(a) in normalized for a in x['aliases'] if len(a) >= 3)]
        policy_question = any(x in query.rsplit('；追问：', 1)[-1] for x in ('退货', '退款', '售后', '运费', '发票', '纠纷'))
        if matched:
            longest = max(max(len(normalize(a)) for a in x['aliases'] if normalize(a) in normalized) for x in matched)
            matched = [x for x in matched if any(len(normalize(a)) == longest and normalize(a) in normalized
                                                for a in x['aliases']) or normalize(x['sku']) in explicit]
            families = {'Watch': '手表', 'Buds': 'TWS', 'Phone': '手机', 'Pad': '平板',
                        'PB': '充电宝', 'CG': '充电器', 'KB': '键盘', 'Dock': '扩展坞', 'SSD': '存储'}
            related = []
            for product in matched:
                family = next((name for key, name in families.items() if '-' + key in product['sku']), '')
                related += [x for x in data['chunks'] if family and x['kind'] == 'rule'
                            and x['source'] == product['source'] and family in x['heading']
                            and relevance(query, x['content']) >= 2]
            matched += related[:2]
            if any(x in query for x in ('飞机', '登机', '托运', '航班')):
                matched += [x for x in data['chunks'] if x['id'] == 'aviation_review']
            if not policy_question:
                return self.result(query, matched[:5], 'catalog_exact')
        if settings.KB_MODE == 'milvus':
            # Semantic queries must not be rejected by a lexical-overlap prefilter.
            hits = await milvus_service.search(query.rsplit('；追问：', 1)[-1], data)
            combined = {x['id']: x for x in matched + hits}
            return self.result(query, list(combined.values())[:5] if hits else [],
                               'milvus' if hits else 'no_results')
        ranked = sorted(data['chunks'], key=lambda x: relevance(query, x['heading'] + x['content']), reverse=True)
        ranked = [x for x in ranked if relevance(query, x['heading'] + x['content']) >= 2]
        if not ranked:
            return self.result(query, [], 'no_results')
        if settings.KB_MODE == 'sample':
            return self.result(query, (matched + ranked)[:5], 'sample_lexical')
        response = await knowledge_request('/api/knowledge/collection/search_knowledge', {
            'project': settings.KB_PROJECT_NAME, 'name': settings.KB_COLLECTION_NAME,
            'query': query.rsplit('；追问：', 1)[-1], 'limit': 8, 'post_processing': {'chunk_group': True}})
        active = {x['doc_id']: x for x in data['documents']}
        hits = []
        for item in response.get('result_list', []):
            info = item.get('doc_info') or {}
            doc_id = info.get('doc_id') or item.get('doc_id')
            # Old course/unknown documents cannot leak into the new scenario.
            if doc_id not in active or not item.get('content') or relevance(query, item['content']) < 2:
                continue
            hits.append({'id': item.get('id', doc_id), 'doc_id': doc_id,
                         'source': active[doc_id]['source'], 'heading': info.get('doc_name', ''),
                         'content': item['content'], 'score': item.get('score'), 'demo': True})
        return self.result(query, (matched + hits)[:5] if hits else [], 'cloud' if hits else 'no_results')

    def result(self, query, hits, mode):
        return {'query': query, 'retrieval_mode': mode, 'version': corpus()['version'],
                'sources': [{k: v for k, v in x.items() if k != 'content'} for x in hits],
                'context': '\n\n'.join('[演示资料；来源：' + x['source'] + '；章节：' + x['heading'] + ']\n'
                                        + x['content'] for x in hits)[:6500]}

    async def retrieve(self, query):
        started = time.monotonic()
        result = await self.search(query)
        logger.info('Commerce retrieval mode=%s source_ids=%s elapsed_ms=%d',
                    result['retrieval_mode'], ','.join(x['id'] for x in result['sources']),
                    (time.monotonic() - started) * 1000)
        return result['context']


rag_service = RagService()
