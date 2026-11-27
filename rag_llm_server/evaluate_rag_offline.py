"""Score the local RAG flow against corpus-scoped annotations."""

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import re
import subprocess
import sys
import time


K = 5
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'reproduction/rag_offline'
SCENARIOS = ('catalog', 'policy', 'followup', 'negative')
MOCK_PREFIX = '[模拟服务，非真实模型] '
CONTEXT_HEADER = '[演示资料；来源：'
REFUSAL = re.compile(r'无法确认|不能确认|不能核实|无法查询|无法转接|无法办理|没有接入|没有.{0,16}(?:资料|信息)')
ESCALATION = re.compile(r'联系.{0,16}人工|订单页|查询铁路12306')
SEVERE = re.compile(
    r'(?:^|[。；\n])\s*(?:我(?:已经|已)|已)(?:帮你)?(?:退款|转接|修改地址|查到|登记)|'
    r'(?:保证|承诺)(?:一定|肯定)?(?:能登机|全额退款|通过退货)|'
    r'(?:手机号|银行卡号|收货地址)[：:]\s*(?:TEST|FAKE|DEMO)[-_A-Z0-9]+'
)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def validate_cases(cases, snapshot, chunks):
    seen = set()
    semantic = set()
    for case in cases:
        groups = case['evidence_groups']
        evidence = {chunk_id for group in groups for chunk_id in group}
        valid_refs = all(set(fact['chunk_ids']) <= evidence for fact in case['key_facts'])
        if (case['id'] in seen or case['semantic_key'] in semantic or
                case['knowledge_snapshot'] != snapshot or case['annotation_status'] != 'reviewable' or
                case['scenario'] not in SCENARIOS or
                case['expected_disposition'] not in ('answer', 'decline', 'clarify', 'channel') or
                (case['expected_disposition'] == 'answer' and not (groups and case['key_facts'])) or
                any(not group for group in groups) or evidence - set(chunks) or not valid_refs):
            raise ValueError(f"Invalid evidence annotation: {case['id']}")
        for pattern in case['expect'] + case['reject'] + case['forbidden_claims']:
            re.compile(pattern)
        for fact in case['key_facts']:
            for pattern in fact['patterns']:
                re.compile(pattern)
        seen.add(case['id'])
        semantic.add(case['semantic_key'])


def answer_evidence(answer, source_ids):
    if not answer.startswith(MOCK_PREFIX):
        return {}
    blocks = answer[len(MOCK_PREFIX):].split(CONTEXT_HEADER)[1:]
    return {chunk_id: block.partition('\n')[2].strip()
            for chunk_id, block in zip(source_ids, blocks)}


def score(case, answer, sources, route):
    source_ids = [source['id'] for source in sources[:K]]
    retrieved = set(source_ids)
    expected_ids = {chunk for group in case['evidence_groups'] for chunk in group}
    correct = retrieved & expected_ids
    groups_complete = bool(expected_ids) and all(retrieved.intersection(group) for group in case['evidence_groups'])
    supports = answer_evidence(answer, source_ids)
    patterns = [pattern for pattern in case['forbidden_claims'] if re.search(pattern, answer, flags=re.I)]
    # Unrelated verbatim excerpts are measured as retrieval noise and wrong
    # disposal, separately from generated unsupported claims.
    severe = bool(SEVERE.search(answer)) or bool(patterns and case['severity'] == 'high')
    if supports:
        disposition = 'context_dump'
    elif REFUSAL.search(answer):
        disposition = 'channel' if ESCALATION.search(answer) else 'decline'
    elif re.search(r'请.{0,8}(?:补充|提供|确认).{0,12}(?:型号|版本)', answer):
        disposition = 'clarify'
    elif answer:
        disposition = 'direct_text'
    else:
        disposition = 'empty'
    expected = case['expected_disposition']
    route_ok = route in case['expected_routes']
    declined = disposition in ('channel', 'decline', 'clarify')
    if expected == 'answer':
        missing = [
            fact['statement'] for fact in case['key_facts']
            if not any(all(re.search(pattern, supports.get(chunk, '').replace('**', ''), re.I)
                           for pattern in fact['patterns'])
                       for chunk in fact['chunk_ids'])
        ]
        passed = groups_complete and not missing and not patterns and not severe
    else:
        missing = [fact['statement'] for fact in case['key_facts']
                   if not all(re.search(pattern, answer, re.I) for pattern in fact['patterns'])]
        accepted = {'decline': {'decline', 'channel'}, 'clarify': {'clarify'},
                    'channel': {'channel'}}[expected]
        passed = disposition in accepted and not missing and not patterns and not severe
    return {
        'expected_evidence': sorted(expected_ids),
        'retrieved_ids': source_ids,
        'relevant_ranks': [rank for rank, chunk in enumerate(source_ids, 1) if chunk in correct],
        'noise_ids': list(dict.fromkeys(chunk for chunk in source_ids if chunk not in correct)),
        'hit_at_5': bool(correct) if expected_ids else None,
        'recall_at_5': len(correct) / len(expected_ids) if expected_ids else None,
        'relevant_retrieved': len(correct),
        'evidence_complete': groups_complete if expected_ids else None,
        'answer_disposition': disposition,
        'answers_expected_goal': passed,
        'missing_facts': missing,
        'route_ok': route_ok,
        'semantic_pass': passed and route_ok,
        'forbidden_matches': patterns,
        'unsupported_claim_detected': severe or bool(patterns),
        'unanswerable_direct': expected != 'answer' and not declined,
        'false_refusal': expected == 'answer' and declined,
        'severe_detected': severe,
    }


def fraction(n, d):
    return {'numerator': n, 'denominator': d, 'value': n / d if d else None}


def duration_stats(values):
    values = sorted(values)
    if not values:
        return {'n': 0, 'p50_ms': None, 'p95_ms': None}
    return {'n': len(values), **{f'p{p}_ms': round(values[math.ceil(p * len(values) / 100) - 1], 3)
                                for p in (50, 95)}}


def summarize(rows):
    complete = [r for r in rows if r['status'] == 'complete']
    answerable = [r for r in rows if r['expected_disposition'] == 'answer']
    evidence = [r for r in answerable if r['evidence_groups']]
    multi = [r for r in evidence if len(r['evidence_groups']) > 1]
    unanswerable = [r for r in rows if r['expected_disposition'] != 'answer']
    return {
        'total': len(rows), 'completed': len(complete),
        'timeouts': sum(r['status'] == 'timeout' for r in rows),
        'errors': sum(r['status'] == 'error' for r in rows),
        'hit_at_5': fraction(sum(bool(r.get('hit_at_5')) for r in evidence), len(evidence)),
        'recall_at_5': fraction(sum(r.get('recall_at_5') or 0 for r in evidence), len(evidence)),
        'evidence_complete': fraction(sum(bool(r.get('evidence_complete')) for r in multi), len(multi)),
        'answer_fact_and_evidence': fraction(sum(bool(r.get('answers_expected_goal')) for r in answerable), len(answerable)),
        'semantic_pass': fraction(sum(bool(r.get('semantic_pass')) for r in rows), len(rows)),
        'keyword_pass': fraction(sum(bool(r.get('checks_passed')) for r in rows), len(rows)),
        'correct_unanswerable_disposition': fraction(sum(bool(r.get('answers_expected_goal')) for r in unanswerable), len(unanswerable)),
        'unanswerable_direct': fraction(sum(bool(r.get('unanswerable_direct')) for r in unanswerable), len(unanswerable)),
        'false_refusal': fraction(sum(bool(r.get('false_refusal')) for r in answerable), len(answerable)),
        'flagged_unsupported_claims': fraction(sum(r['unsupported_claim_detected'] for r in complete), len(complete)),
        'severe_detected': fraction(sum(r['severe_detected'] for r in complete), len(complete)),
        'channel_guidance': sum(r['answer_disposition'] == 'channel' for r in complete),
        'retrieval_ms': duration_stats([r['retrieval_ms'] for r in complete if r['retrieval_ms'] is not None]),
        'first_text_ms': duration_stats([r['first_text_ms'] for r in complete]),
        'elapsed_ms': duration_stats([r['elapsed_ms'] for r in complete]),
    }


async def replay(case, backend):
    commerce, rag, llm, keyword = backend
    row = {**case, 'status': 'complete'}
    messages = case['history'] + [{'role': 'user', 'content': case['question']}]
    query = commerce.retrieval_query(messages)
    result = {'sources': [], 'context': '', 'retrieval_mode': 'service_boundary'}
    retrieval_ms = None
    start = time.perf_counter()
    stage = 'retrieval'
    try:
        if not commerce.direct_answer(case['question']):
            async with asyncio.timeout(5):
                result = await rag.rag_service.search(query)
            retrieval_ms = (time.perf_counter() - start) * 1000
        stage = 'answer'
        first = None
        output = []
        async with asyncio.timeout(10):
            async for frame in llm.llm_service.chat_stream(messages, result['context']):
                for choice in frame.get('choices', []):
                    content = choice.get('delta', {}).get('content')
                    if content:
                        if first is None:
                            first = (time.perf_counter() - start) * 1000
                        output.append(content)
        if first is None:
            raise RuntimeError('Empty answer stream')
        answer = ''.join(output)
        row.update(score(case, answer, result['sources'], result['retrieval_mode']))
        row.update(keyword.check_answer(case, answer))
        row.update(answer=answer, first_text_ms=first, retrieval_ms=retrieval_ms)
    except Exception as exc:
        row.update(status='timeout' if isinstance(exc, TimeoutError) else 'error',
                   error_type=type(exc).__name__, stage=stage)
    return {**row, 'retrieval_query': query, 'retrieval_mode': result['retrieval_mode'],
            'canonical_query': result.get('query'), 'sources': result['sources'],
            'elapsed_ms': (time.perf_counter() - start) * 1000}


async def run(args):
    # The evaluator and data stay fixed when switching service source trees.
    server = (args.server or ROOT / 'rag_llm_server').resolve()
    sys.path.insert(0, str(server))
    from config import settings
    from services import commerce, llm_service, rag_service
    import evaluate_commerce

    settings.KB_MODE = 'sample'
    settings.MOCK_MODE = True
    corpus_file = server / 'knowledge/corpus.json'
    snapshot = {'version': rag_service.corpus()['version'], 'sha256': sha256(corpus_file)}
    case_path = args.cases.resolve()
    _, case_hash, cases = evaluate_commerce.load_cases(case_path, args.ids)
    manifest_file = case_path.with_name('manifest.json')
    if case_path.name == 'holdout.json' and not manifest_file.is_file():
        raise ValueError('Missing holdout manifest')
    if manifest_file.is_file():
        manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
        if case_hash != manifest['files'][case_path.name]['sha256'] or snapshot != manifest['knowledge_snapshot']:
            raise ValueError('Dataset or corpus differs from the frozen manifest')
    validate_cases(cases, snapshot, {chunk['id'] for chunk in rag_service.corpus()['chunks']})

    started_at = datetime.now(timezone.utc).isoformat()
    rows = []
    for case in cases:
        rows.append(await replay(case, (commerce, rag_service, llm_service, evaluate_commerce)))
    files = [server / name for name in ('config.py', 'evaluate_commerce.py')]
    files += sorted((server / 'services').glob('*.py'))
    report = {
        'label': args.label, 'started_at': started_at, 'completed_at': datetime.now(timezone.utc).isoformat(),
        'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'runtime': platform.python_version(), 'mode': 'sample_retrieval_mock_llm',
        'settings': {'kb_mode': 'sample', 'mock_mode': True, 'k': K, 'retrieval_timeout_s': 5, 'answer_timeout_s': 10},
        'knowledge_snapshot': snapshot, 'cases_file': str(case_path), 'cases_sha256': case_hash,
        'source_sha256': {str(path.relative_to(server)): sha256(path) for path in files},
        'evaluator_sha256': sha256(Path(__file__)), 'selected_ids': args.ids,
        'summary': summarize(rows),
        'by_scenario': {name: summarize([r for r in rows if r['scenario'] == name]) for name in SCENARIOS},
        'by_route': {name: summarize([r for r in rows if r['retrieval_mode'] == name])
                     for name in sorted({r['retrieval_mode'] for r in rows})},
        'by_expected_route': {name: summarize([r for r in rows if r['expected_routes'][0] == name])
                              for name in sorted({r['expected_routes'][0] for r in rows})},
        'source_types': dict(Counter(r['source_type'] for r in rows)), 'cases': rows,
    }
    if args.out.exists():
        raise FileExistsError(f'Report already exists: {args.out}')
    write_json(args.out, report)
    print(json.dumps({'report': str(args.out), 'summary': report['summary']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=Path, required=True)
    parser.add_argument('--ids', type=int, nargs='+')
    parser.add_argument('--server', type=Path, help='Backend source directory for baseline replay')
    parser.add_argument('--label', required=True)
    parser.add_argument('--out', type=Path, required=True)
    asyncio.run(run(parser.parse_args()))
