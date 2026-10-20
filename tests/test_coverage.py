"""The rule coverage report (cna/coverage.py) and the marks it reads (cna/rules)."""
import io
import unittest

from cna import coverage


class Coverage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = coverage.load_cases()
        cls.status, cls.by, cls.errors = coverage.statuses(cls.cases, coverage.load_marks())

    def test_every_mark_names_a_case_of_the_rulebook(self):
        self.assertEqual(self.errors, [])

    def test_a_section_or_subsection_stands_for_its_cases(self):
        _, under, _ = coverage.index(self.cases)
        self.assertEqual(under['7.1'], ['7.11', '7.12', '7.13', '7.14', '7.15', '7.16'])
        self.assertEqual(under['7'], [*under['7.1'], '7.2'])  # 7.2 has no cases: it is an item itself
        self.assertEqual(under['1'], ['1'])
        self.assertEqual(under['3.6'], ['3.61', '3.62'])  # added by the addenda

    def test_what_m0_carries_out(self):
        for case in ('5.1', '5.2', '7.11', '7.15', '4.1'):
            self.assertEqual(self.status[case], 'done', case)
        for case in ('7.12', '59.2'):
            self.assertEqual(self.status[case], 'partly', case)
        self.assertEqual(self.status['1'], 'not needed')
        self.assertEqual(self.status['8.11'], 'missing')

    def test_the_report_adds_up(self):
        items, _, _ = coverage.index(self.cases)
        out = io.StringIO()
        coverage.report(self.cases, self.status, out)
        total = coverage.counts(self.status, items)
        self.assertEqual(sum(total.values()), len(items))
        self.assertIn(f'Rule coverage: {len(items)} items, {total["done"]} done', out.getvalue())

    def test_listing_a_section(self):
        out = io.StringIO()
        coverage.detail(self.cases, self.status, self.by, 7, only='missing', out=out)
        text = out.getvalue()
        self.assertIn('7.13', text)
        self.assertNotIn('7.11', text)

    def test_an_unknown_number_is_an_error(self):
        _, _, errors = coverage.statuses(self.cases, [{'cases': ('99.9',), 'kind': 'done', 'where': 'test'}])
        self.assertEqual(len(errors), 1)


if __name__ == '__main__':
    unittest.main()
