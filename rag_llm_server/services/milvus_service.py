"""Milvus 2.4+ REST v2 adapter; no SDK, no implicit fallback or destructive operations."""
import asyncio
from collections import OrderedDict
import hashlib
import json
import math
import re

import httpx
from config import settings


def corpus_digest(data):
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def embedding_profile():
    return hashlib.sha256(json.dumps([
        settings.EMBEDDING_BASE_URL, settings.EMBEDDING_API_PATH,
        settings.EMBEDDING_MODEL, settings.EMBEDDING_DIMENSIONS,
    ]).encode()).hexdigest()


def validate_vector(vector):
    if not isinstance(vector, list) or len(vector) != settings.EMBEDDING_DIMENSIONS:
        raise ValueError('Embedding 维度不匹配；请核对模型与 EMBEDDING_DIMENSIONS')
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in vector):
        raise ValueError('Embedding 包含无效数值')
    norm = math.sqrt(sum(x*x for x in vector))
    if norm <= 0:
        raise ValueError('Embedding 返回零向量')
    return [x / norm for x in vector]


class EmbeddingService:
    def __init__(self):
        self.cache = OrderedDict()

    async def encode(self, text):
        settings.require('EMBEDDING_MODEL', 'EMBEDDING_API_KEY')
        if not text.strip():
            raise ValueError('向量化文本不能为空')
        key = (embedding_profile(), text)
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key][:]
        if settings.EMBEDDING_API_PATH.endswith('/multimodal'):
            body = {'model': settings.EMBEDDING_MODEL, 'input': [{'type': 'text', 'text': text}]}
        else:
            body = {'model': settings.EMBEDDING_MODEL, 'input': [text]}
        async with httpx.AsyncClient(timeout=settings.EMBEDDING_TIMEOUT, trust_env=False) as client:
            response = await client.post(settings.EMBEDDING_BASE_URL + settings.EMBEDDING_API_PATH,
                headers={'Authorization': 'Bearer ' + settings.EMBEDDING_API_KEY}, json=body)
            response.raise_for_status()
        result = response.json().get('data')
        if isinstance(result, list):
            result = result[0] if result else {}
        if not isinstance(result, dict):
            raise ValueError('Embedding 接口未返回向量')
        vector = validate_vector(result.get('embedding'))
        self.cache[key] = vector
        if len(self.cache) > 128:
            self.cache.popitem(last=False)
        return vector[:]


class MilvusService:
    async def request(self, operation, body=None, timeout=None):
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', settings.MILVUS_COLLECTION):
            raise ValueError('MILVUS_COLLECTION 名称无效')
        headers = {'Request-Timeout': str(max(1, math.ceil(timeout or settings.MILVUS_TIMEOUT)))}
        if settings.MILVUS_TOKEN:
            headers['Authorization'] = 'Bearer ' + settings.MILVUS_TOKEN
        payload = {'dbName': settings.MILVUS_DATABASE, 'collectionName': settings.MILVUS_COLLECTION, **(body or {})}
        async with httpx.AsyncClient(timeout=timeout or settings.MILVUS_TIMEOUT, trust_env=False) as client:
            response = await client.post(settings.MILVUS_URI + '/v2/vectordb/' + operation,
                                         headers=headers, json=payload)
            response.raise_for_status()
        result = response.json()
        if result.get('code') != 0:
            raise RuntimeError(f"Milvus {operation} 失败（code={result.get('code')}）；检查服务、集合及导入状态")
        return result.get('data')

    def scope(self, data):
        return f'corpus_hash == "{corpus_digest(data)}" and embedding_profile == "{embedding_profile()}"'

    async def count(self, data):
        # Milvus 2.4.4 REST injects pagination into count(*), which it then rejects.
        # Fetch IDs only, bounded at expected+1 so missing/extra records are detected.
        rows = await self.request('entities/query', {'filter': self.scope(data),
            'outputFields': ['id'], 'limit': len(data['chunks']) + 1})
        return len(rows)

    async def ensure_collection(self):
        exists = await self.request('collections/has')
        if not exists.get('has'):
            await self.request('collections/create', {
                'schema': {'autoID': False, 'enableDynamicField': True, 'fields': [
                    {'fieldName': 'id', 'dataType': 'VarChar', 'isPrimary': True,
                     'elementTypeParams': {'max_length': '64'}},
                    {'fieldName': 'vector', 'dataType': 'FloatVector',
                     'elementTypeParams': {'dim': str(settings.EMBEDDING_DIMENSIONS)}},
                ]},
                'indexParams': [{'fieldName': 'vector', 'indexName': 'vector_index',
                                 'metricType': 'COSINE', 'params': {'index_type': 'FLAT'}}],
                'params': {'consistencyLevel': 'Strong'},
            }, timeout=30)
        description = await self.request('collections/describe', timeout=10)
        fields = {x['name']: x for x in description['fields']}
        if 'id' not in fields or 'vector' not in fields:
            raise ValueError('已有集合字段不兼容，请使用新的 MILVUS_COLLECTION；不会覆盖旧集合')
        dimension = dict((x['key'], x['value']) for x in fields['vector'].get('params', []))
        if int(dimension.get('dim', 0)) != settings.EMBEDDING_DIMENSIONS:
            raise ValueError('已有集合维度不同，请使用新的 MILVUS_COLLECTION；不会覆盖旧集合')
        indexes = description.get('indexes', [])
        if not any(x.get('metricType') == 'COSINE' for x in indexes):
            raise ValueError('已有集合不是 COSINE 索引，请使用新集合')
        await self.request('collections/load', timeout=30)

    async def sync(self, data):
        settings.require('EMBEDDING_MODEL', 'EMBEDDING_API_KEY')
        await self.ensure_collection()
        if await self.count(data) == len(data['chunks']):
            return {'collection': settings.MILVUS_COLLECTION, 'count': len(data['chunks']),
                    'status': 'already_current', 'embedding_model': settings.EMBEDDING_MODEL}
        # Generate everything before writing; retries never drop collections or old versions.
        fingerprint, digest = embedding_profile(), corpus_digest(data)
        semaphore = asyncio.Semaphore(3)

        async def row(chunk):
            async with semaphore:
                vector = await embedding_service.encode(chunk['heading'] + '\n' + chunk['content'])
                return {**chunk, 'chunk_id': chunk['id'], 'vector': vector,
                    'id': hashlib.sha256((fingerprint + digest + chunk['id']).encode()).hexdigest(),
                    'corpus_hash': digest, 'embedding_profile': fingerprint}

        rows = await asyncio.gather(*(row(chunk) for chunk in data['chunks']))
        result = await self.request('entities/upsert', {'data': rows}, timeout=30)
        count = await self.count(data)
        if count != len(rows):
            raise RuntimeError(f'导入可见记录数 {count} 与预期 {len(rows)} 不一致')
        return {'collection': settings.MILVUS_COLLECTION, 'count': count,
                'dimensions': settings.EMBEDDING_DIMENSIONS, 'corpus_hash': digest,
                'embedding_model': settings.EMBEDDING_MODEL, 'write_result': result}

    async def search(self, query, data):
        vector = await embedding_service.encode(query)
        rows = await self.request('entities/search', {
            'data': [vector], 'annsField': 'vector', 'filter': self.scope(data), 'limit': 8,
            'outputFields': ['chunk_id', 'doc_id', 'content', 'heading', 'corpus_hash', 'embedding_profile'],
            'searchParams': {'metricType': 'COSINE', 'params': {}},
        })
        active = {x['id']: x for x in data['chunks']}
        hits = []
        for row in rows:
            chunk = active.get(row.get('chunk_id'))
            score = row.get('distance')
            if (chunk is None or row.get('doc_id') != chunk['doc_id'] or row.get('content') != chunk['content']
                    or row.get('corpus_hash') != corpus_digest(data)
                    or row.get('embedding_profile') != embedding_profile()
                    or not isinstance(score, (float, int)) or not math.isfinite(score)
                    or score < settings.MILVUS_MIN_SCORE):
                continue
            hits.append({**chunk, 'score': score})
        return hits


embedding_service = EmbeddingService()
milvus_service = MilvusService()
