"""data/rules/cases.json, the list of every rule for the coverage report, is consistent."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

from cna.paths import DATA, RULEBOOK, ROOT

CASES = DATA / 'rules' / 'cases.json'


def load():
    with open(CASES, encoding='utf-8') as f:
        return json.load(f)


class RulesList(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load()

    def test_every_number_is_in_its_place(self):
        seen = set()
        for sec in self.data['sections']:
            for sub in sec['subsections']:
                self.assertTrue(sub['id'].startswith(sec['id'] + '.'), sub['id'])
                self.assertTrue(sub['title'], f'{sub["id"]} has no title')
                for case in sub['cases']:
                    self.assertTrue(case.startswith(sub['id']) and len(case) > len(sub['id']), case)
                    self.assertNotIn(case, seen, f'{case} is listed twice')
                    seen.add(case)
        self.assertEqual([int(s['id']) for s in self.data['sections']], list(range(1, 66)))

    def test_cases_are_in_order(self):
        for sec in self.data['sections']:
            for sub in sec['subsections']:
                digits = [[int(d) for d in c.split('.')[1]] for c in sub['cases']]
                self.assertEqual(digits, sorted(digits), sub['id'])

    def test_gaps_are_not_listed_as_cases(self):
        cases = {c for s in self.data['sections'] for u in s['subsections'] for c in u['cases']}
        for g in self.data['gaps']:
            self.assertNotIn(g, cases)

    @unittest.skipUnless(RULEBOOK.exists(), 'the rulebook transcription is not in the project folder')
    def test_matches_the_transcription(self):
        before = CASES.read_bytes()
        subprocess.run([sys.executable, '-I', str(ROOT / 'tools' / 'rules' / 'cases.py')], check=True,
                       capture_output=True)
        self.assertEqual(CASES.read_bytes(), before, 'run python -I tools/rules/cases.py and commit the result')


if __name__ == '__main__':
    unittest.main()
