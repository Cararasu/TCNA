"""data/tables/, the characteristics charts (4.46-4.49), hold together and say what the charts say."""
import json
import subprocess
import sys
import unittest

from cna.paths import DATA, RULEBOOK, ROOT

TABLES = DATA / 'tables'
NATIONS = ('cw', 'it', 'gm')
RATINGS = {'cpa', 'aa', 'barrage', 'anti_armor', 'vulnerability', 'armor', 'assault_off', 'assault_def', 'max_toe'}
CLASSES = {'tank', 'artillery', 'anti-tank', 'light-aa', 'heavy-aa'}
ASSIGNABLE = CLASSES | {'recce'}


def load(name):
    with open(TABLES / f'{name}.json', encoding='utf-8') as f:
        return json.load(f)


class Tables(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.units = {n: load(f'units-{n}')['codes'] for n in NATIONS}
        cls.weapons = {n: load(f'weapons-{n}')['weapons'] for n in NATIONS}

    def test_id_codes_run_in_sequence(self):
        letters = [c for c in 'abcdefghijklmnopqrstuvwxyz' if c not in 'io']
        seq = letters + [c * 2 for c in letters] + [c * 3 for c in letters]
        for nat, codes in self.units.items():
            self.assertEqual(list(codes), seq[:len(codes)], nat)
        self.assertEqual([len(self.units[n]) for n in NATIONS], [43, 50, 31])

    def test_unit_entries(self):
        for nat, codes in self.units.items():
            for code, e in codes.items():
                where = f'{nat} {code}'
                self.assertIsInstance(e.get('cpa'), int, where)
                for col in e.get('paren', []):
                    self.assertIn(col, RATINGS, where)
                    self.assertIn(col, e, where)
                assigned = 0
                for a in e.get('may_assign', []):
                    self.assertLessEqual(set(a['class']), ASSIGNABLE, where)
                    assigned += a['n']
                self.assertLessEqual(assigned, e.get('max_toe', 0), where)

    def test_weapon_entries(self):
        for nat, weapons in self.weapons.items():
            for w, e in weapons.items():
                where = f'{nat} {w}'
                self.assertIn(e['class'], CLASSES, where)
                self.assertTrue('cpa' in e or 'cpa' in e.get('open', []), where)
                for col in e.get('paren', []):
                    self.assertIn(col, e, where)
                for c in e.get('changes', []):
                    self.assertEqual(set(c['from']), {'turn', 'stage'}, where)
                    self.assertTrue(set(c) - {'from'} <= set(e), where)
        self.assertEqual([len(self.weapons[n]) for n in NATIONS], [32, 21, 28])

    def test_what_the_charts_say(self):
        cw, it, gm = (self.units[n] for n in NATIONS)
        # A tank battalion: ten tank TOE, nine if all US-built (4.46a †)
        self.assertEqual(cw['g'], {'type': 'Tank Bn-Eq', 'cpa': 25, 'may_assign': [{'class': ['tank'], 'n': 10}],
                                   'max_toe': 10, 'max_toe_us': 9})
        # An HQ that keeps its CPA, with one parenthesized tank TOE (4.46)
        self.assertTrue(cw['b']['cpa_fixed'])
        self.assertEqual(cw['b']['paren'], ['max_toe'])
        self.assertEqual(cw['z']['may_assign'], [{'class': ['anti-tank'], 'n': 8}, {'class': ['artillery'], 'n': 3}])
        self.assertTrue(cw['l']['motorized'])
        # Nine artillery and three AA of either kind; "9 +3"
        self.assertEqual(it['kk']['may_assign'], [{'class': ['artillery'], 'n': 9},
                                                  {'class': ['heavy-aa', 'light-aa'], 'n': 3}])
        self.assertEqual(it['kk']['max_toe'], 12)
        self.assertEqual((it['pp']['cpa'], it['pp']['emplaced']), (0, True))
        self.assertEqual(it['c']['paren'], ['anti_armor', 'armor', 'assault_off', 'assault_def', 'max_toe'])
        self.assertEqual(it['ww']['bar'], -1)
        self.assertTrue(gm['j']['halftrack'] and gm['j']['motorized'])
        self.assertEqual(gm['h']['may_assign'], [{'class': ['artillery'], 'n': 1, 'airdrop': True}])
        self.assertEqual(gm['e']['augment'], '19.8')

    def test_weapons_as_the_charts_give_them(self):
        cw, it, gm = (self.weapons[n] for n in NATIONS)
        self.assertEqual(cw['a9-cruiser']['armor'], 1)  # Copy 2 prints "–"
        self.assertTrue(cw['stuart-m3']['us'])
        self.assertEqual(cw['scorpion']['bar'], -1)
        self.assertEqual(cw['18-pounder-gun']['paren'], ['anti_armor'])
        # Zero anti-armor until January 1942 (4.48 **, 4.49 **)
        self.assertEqual(it['75-27-gun']['anti_armor'], 0)
        self.assertEqual(it['75-27-gun']['changes'], [{'anti_armor': 2, 'from': {'turn': 63, 'stage': 1}}])
        self.assertEqual(gm['7-5-cm-ig18-light-infantry-gun']['changes'][0]['anti_armor'], 3)
        self.assertEqual((it['i-light']['cpa'], it['i-light']['no_transport']), (0, True))
        self.assertEqual(it['heavy-75-46-mod-34']['class'], 'heavy-aa')
        # German tanks: BAR 1R until 1/31 (4.49 *)
        for w in gm.values():
            if w['class'] == 'tank':
                self.assertEqual((w['bar'], w['changes']), (1, [{'bar': 0, 'from': {'turn': 31, 'stage': 1}}]))
        # Printed shifted against the columns
        self.assertEqual({k: gm['pz-iii-e'][k] for k in ('anti_armor', 'armor', 'assault_off', 'fuel')},
                         {'anti_armor': 4, 'armor': 3, 'assault_off': 4, 'fuel': 3})
        self.assertEqual((gm['marder-iii-sp']['cpa'], gm['7-62cm-pak-r']['cpa']), (25, 15))  # the addenda, [4.49]
        self.assertNotIn('open', gm['marder-iii-sp'])
        self.assertEqual(gm['7-62cm-pak-r']['anti_armor'], 9)

    @unittest.skipUnless(RULEBOOK.exists(), 'the rulebook transcription is not in the project folder')
    def test_matches_the_transcription(self):
        before = {p.name: p.read_bytes() for p in TABLES.glob('*.json')}
        subprocess.run([sys.executable, '-I', str(ROOT / 'tools' / 'units' / 'tables.py')], check=True,
                       capture_output=True)
        after = {p.name: p.read_bytes() for p in TABLES.glob('*.json')}
        self.assertEqual(after, before, 'run python -I tools/units/tables.py and commit the result')


if __name__ == '__main__':
    unittest.main()
