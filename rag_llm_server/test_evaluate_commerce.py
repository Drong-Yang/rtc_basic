import json
import re
from unittest.mock import patch
import unittest
from pathlib import Path
from evaluate_commerce import check_answer, load_cases
from evaluate_rag_offline import score


class EvaluationTests(unittest.TestCase):
    def test_evidence_scoring_preserves_rank_and_checks_facts_in_correct_chunk(self):
        from evaluate_rag_offline import CONTEXT_HEADER, MOCK_PREFIX

        case = {'evidence_groups': [['sku-a'], ['sku-b', 'sku-b-alt']],
                'key_facts': [{'statement': 'A is 100W', 'patterns': ['100W'], 'chunk_ids': ['sku-a']},
                              {'statement': 'B is 50W', 'patterns': ['50W'], 'chunk_ids': ['sku-b', 'sku-b-alt']}],
                'forbidden_claims': [], 'expected_disposition': 'answer',
                'expected_routes': ['catalog_exact'], 'severity': 'standard'}
        sources = [{'id': x} for x in ('noise', 'sku-b-alt', 'sku-a', 'sku-a', 'noise-2', 'sku-b')]
        answer = MOCK_PREFIX + ''.join(f'{CONTEXT_HEADER}d；章节：h]\n{body}\n'
                                       for body in ('100W', '50W', '90W', '90W'))
        result = score(case, answer, sources, 'catalog_exact')
        self.assertEqual(result['relevant_ranks'], [2, 3, 4])
        self.assertEqual(result['recall_at_5'], 2 / 3)
        self.assertTrue(result['evidence_complete'])
        self.assertEqual(result['missing_facts'], ['A is 100W'])
        self.assertFalse(result['semantic_pass'])

    def test_refusal_and_unsafe_claim_are_distinct(self):
        case = {'evidence_groups': [], 'key_facts': [], 'forbidden_claims': ['TEST-CUST-123'],
                'expected_disposition': 'decline', 'expected_routes': ['service_boundary'], 'severity': 'high'}
        normal = score(case, '我没有接入订单系统，无法查询。', [], 'service_boundary')
        self.assertTrue(normal['semantic_pass'])
        self.assertFalse(normal['unanswerable_direct'])
        violation = score(case, '我已修改地址。TEST-CUST-123', [], 'service_boundary')
        self.assertTrue(violation['unanswerable_direct'])
        self.assertTrue(violation['severe_detected'])

    def test_positive_negative_and_case_insensitive_checks(self):
        case = {'expect': ['189', 'IP68'], 'reject': ['212']}
        self.assertTrue(check_answer(case, '189g ip68')['checks_passed'])
        result = check_answer(case, '189g IP68; 212g')
        self.assertFalse(result['checks_passed'])
        self.assertEqual(result['violated_checks'], ['212'])
        self.assertEqual(check_answer(case, '189g')['missing_checks'], ['IP68'])
        self.assertTrue(check_answer({'expect': ['189']}, '189g')['checks_passed'])

    def test_custom_file_subset_and_invalid_ids(self):
        raw = json.dumps([
            {'id': 1, 'question': 'a', 'expect': ['a']},
            {'id': 2, 'question': 'b', 'expect': ['b'], 'reject': ['c']}
        ]).encode('utf-8-sig')
        path = Path(__file__).resolve().parent / 'test-cases.json'
        with patch.object(Path, 'read_bytes', return_value=raw):
            resolved, digest, cases = load_cases(path, [2])
            self.assertEqual(resolved, path.resolve())
            self.assertEqual(len(digest), 64)
            self.assertEqual([x['id'] for x in cases], [2])
            with self.assertRaises(ValueError):
                load_cases(path, [999])
        with patch.object(Path, 'read_bytes', return_value=b'[{"id":1,"expect":["["]}]'):
            with self.assertRaises(re.error):
                load_cases(path)


if __name__ == '__main__':
    unittest.main()
