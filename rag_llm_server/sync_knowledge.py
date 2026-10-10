"""Idempotently import only this demo's reviewed documents; never delete other data."""
import argparse
import asyncio
import json
from config import settings
from services.rag_service import corpus, knowledge_request


async def run(upload):
    for doc in corpus()['documents']:
        body = {'collection_name': settings.KB_COLLECTION_NAME, 'project': settings.KB_PROJECT_NAME,
                'doc_id': doc['doc_id']}
        if upload:
            result = await knowledge_request('/api/knowledge/doc/add', {
                **body, 'add_type': 'url', 'url': settings.SERVER_URL + '/knowledge/' + doc['file'],
                'doc_name': doc['doc_id'], 'doc_type': 'markdown'})
            print(json.dumps({'doc_id': doc['doc_id'], 'action': 'upload', 'accepted': True}, ensure_ascii=False), flush=True)
        else:
            result = await knowledge_request('/api/knowledge/doc/info', body)
            print(json.dumps({'doc_id': doc['doc_id'], 'status': result.get('status'),
                              'point_num': result.get('point_num')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--upload', action='store_true', help='Replace the four managed demo IDs only')
    args = parser.parse_args()
    asyncio.run(run(args.upload))
