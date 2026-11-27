"""Verify paired inputs and retain traces and an offline routing simulation."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from random import Random

from evaluate_rag_offline import write_json


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def pair(before, after):
    fixed_inputs = ('cases_sha256', 'evaluator_sha256', 'knowledge_snapshot', 'mode', 'settings', 'runtime')
    if any(before[key] != after[key] for key in fixed_inputs):
        raise ValueError('Reports differ in evaluation inputs')
    hashes = before['source_sha256'], after['source_sha256']
    if set(hashes[0]) != set(hashes[1]):
        raise ValueError('Service source lists differ')
    changes = [name for name, digest in hashes[0].items() if digest != hashes[1][name]]
    both = list(zip(before['cases'], after['cases'], strict=True))
    if any(a['id'] != b['id'] for a, b in both):
        raise ValueError('Case IDs or replay order differ')
    return both, changes


def trace(row):
    return {key: row.get(key) for key in (
        'id', 'scenario', 'family', 'severity', 'question', 'history', 'retrieval_query', 'canonical_query',
        'expected_evidence', 'retrieved_ids', 'missing_facts', 'retrieval_mode', 'expected_disposition',
        'answer_disposition', 'answers_expected_goal', 'semantic_pass', 'checks_passed', 'status',
        'error_type', 'forbidden_matches', 'severe_detected', 'answer',
    )}


def comparison(before, after):
    both, changes = pair(before, after)
    fields = ('retrieval_mode', 'retrieved_ids', 'answer', 'semantic_pass', 'status')
    changed = [{'before': trace(a), 'after': trace(b)} for a, b in both
               if any(a.get(key) != b.get(key) for key in fields)]
    return {'same_cases_sha256': after['cases_sha256'], 'changed_service_files': changes,
            'before': before['summary'], 'after': after['summary'],
            'after_by_scenario': after['by_scenario'], 'after_by_expected_route': after['by_expected_route'],
            'changed_traces': changed}


def holdout_review(report):
    rows = report['cases']
    queue = []
    for row in rows:
        if row['severity'] == 'high' or not row.get('semantic_pass') or not row.get('checks_passed') or row['status'] != 'complete':
            queue.append(trace(row))
    normal = [row for row in rows if row['id'] not in {entry['id'] for entry in queue}]
    sampled = Random(20261124).sample(normal, min(8, len(normal)))
    return {'high_risk': sum(row['severity'] == 'high' for row in rows),
            'automated_anomalies': sum(not row.get('semantic_pass') or not row.get('checks_passed') for row in rows),
            'review_queue_count': len(queue), 'review_queue': queue,
            'normal_random_seed': 20261124, 'sampled_normal': [trace(row) for row in sampled]}


def route(session_id, candidate_enabled):
    bucket = int.from_bytes(hashlib.sha256(session_id.encode()).digest()[:8], 'big') % 100
    return 'candidate' if candidate_enabled and bucket < 5 else 'control'


def simulate(before, after):
    both, _ = pair(before, after)
    assignments = []
    for a, b in both:
        session = f'offline-demo-{a["id"]}'
        group = route(session, True)
        assert all(route(session, True) == group for _ in range(3))
        assert route(session, False) == 'control'
        row = b if group == 'candidate' else a
        assignments.append({'session': session, 'id': row['id'], 'group': group,
                            'status': row['status'], 'semantic_pass': row['semantic_pass'],
                            'severe_detected': row['severe_detected']})
    return {'mode': 'offline replay only', 'candidate_threshold_percent': 5,
            'groups': dict(Counter(item['group'] for item in assignments)),
            'sessions': len(assignments), 'sticky_rechecks': len(assignments) * 3,
            'rollback_control': len(assignments), 'assignments': assignments}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    args = parser.parse_args()
    paired = {}
    for split in ('pilot', 'dev', 'holdout', 'dev_variants'):
        before = read(args.run_dir / f'{split}-before.json')
        after = read(args.run_dir / f'{split}-after.json')
        paired[split] = comparison(before, after)
        if split == 'holdout':
            write_json(args.run_dir / 'holdout-review-queue.json', holdout_review(after))
            write_json(args.run_dir / 'offline-routing-simulation.json', simulate(before, after))
    write_json(args.run_dir / 'comparison.json', paired)
