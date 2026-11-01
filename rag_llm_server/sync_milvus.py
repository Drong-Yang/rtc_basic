"""Import reviewed corpus into an isolated Milvus collection. Never deletes data."""
import argparse
import asyncio
import json
from services.rag_service import corpus
from services.milvus_service import milvus_service


async def run(check):
    data = corpus()
    if check:
        await milvus_service.request('collections/load', timeout=30)
        result = {'active_records': await milvus_service.count(data), 'expected': len(data['chunks'])}
        print(json.dumps(result, ensure_ascii=False))
        if result['active_records'] != result['expected']:
            raise RuntimeError('请先执行 sync_milvus.py 导入当前知识版本')
    else:
        print(json.dumps(await milvus_service.sync(data), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Only check imported active record count')
    asyncio.run(run(parser.parse_args().check))
