"""Reproducible keyword regression, not an automatic factual-quality guarantee."""
import argparse
import asyncio
import json
import re
import time
from pathlib import Path
from config import ROOT, settings
from services.rag_service import rag_service
from services.llm_service import llm_service
from services.commerce import direct_answer, retrieval_query

WORKSPACE = ROOT.parent


async def run(live, ids=None):
    if not live:
        settings.KB_MODE = 'sample'
        settings.MOCK_MODE = True
    elif settings.MOCK_MODE or settings.KB_MODE != 'cloud':
        raise ValueError('真实评测必须使用非模拟模型与cloud知识库')
    cases = json.loads((WORKSPACE / 'reproduction/ecommerce_cases.json').read_text(encoding='utf-8'))
    if ids:
        cases = [case for case in cases if case['id'] in ids]
    # Small acceptance run, not a load test; avoid burst quotas obscuring quality.
    semaphore = asyncio.Semaphore(1)

    async def evaluate(case):
        async with semaphore:
            started = time.monotonic()
            messages = case.get('history', []) + [{'role': 'user', 'content': case['question']}]
            first = None
            stage = 'knowledge'
            try:
                result = {'context': '', 'sources': [], 'retrieval_mode': 'service_boundary'}
                if not direct_answer(case['question']):
                    async with asyncio.timeout(5):
                        result = await rag_service.search(retrieval_query(messages))
                answer = ''
                stage = 'model'
                async for chunk in llm_service.chat_stream(messages, result['context']):
                    for choice in chunk.get('choices', []):
                        text = choice.get('delta', {}).get('content') or ''
                        if text and first is None:
                            first = round(time.monotonic() - started, 3)
                        answer += text
                missing = [x for x in case['expect'] if not re.search(x, answer, flags=re.I)]
                row = {**case, 'answer': answer, 'first_text_s': first,
                       'elapsed_s': round(time.monotonic() - started, 3),
                       'retrieval_mode': result['retrieval_mode'], 'sources': result['sources'],
                       'missing_checks': missing, 'checks_passed': not missing}
            except Exception as exc:
                row = {**case, 'checks_passed': False, 'error_type': type(exc).__name__, 'stage': stage,
                       'http_status': getattr(getattr(exc, 'response', None), 'status_code', None)}
            print(json.dumps({'case': case['id'], 'checks_passed': row['checks_passed'],
                              'first_text_s': first}, ensure_ascii=False), flush=True)
            return row

    rows = await asyncio.gather(*(evaluate(case) for case in cases))
    summary = {'mode': 'real_cloud_and_ark' if live else 'sample_retrieval_only',
               'method': '关键词回归检查，不能等同完整事实准确率；真实音频仍需浏览器验收',
               'total': len(rows), 'checks_passed': sum(x['checks_passed'] for x in rows), 'cases': rows}
    filename = 'ecommerce-eval-real' if live else 'ecommerce-eval-sample'
    if ids:
        filename += '-subset'
    output = WORKSPACE / '.runtime'
    output.mkdir(parents=True, exist_ok=True)
    path = output / (filename + '.json')
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k != 'cases'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true', help='Call real KB and Ark; incurs normal service charges')
    parser.add_argument('--ids', nargs='+', type=int, help='Rerun affected case IDs only')
    args = parser.parse_args()
    asyncio.run(run(args.live, args.ids))
