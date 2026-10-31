import json
import re
from unittest.mock import patch
import unittest
from pathlib import Path
from evaluate_commerce import check_answer, load_cases


class EvaluationTests(unittest.TestCase):
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
