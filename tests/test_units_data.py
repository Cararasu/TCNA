"""data/units/, the Organization at Arrival Charts (4.45), hold together and say what the charts say."""
import json
import subprocess
import sys
import unittest

from cna.paths import DATA, RULEBOOK, ROOT

CHARTS = ('cw', 'it', 'gm')
NATIONS = {'uk', 'au', 'nz', 'sa', 'in', 'fr', 'pl', 'cz', 'gr', 'it', 'de'}


def load(name):
    with open(DATA / name, encoding='utf-8') as f:
        return json.load(f)


class Units(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sheets = {c: load(f'units/oa-{c}.json')['sheets'] for c in CHARTS}
        cls.codes = {c: load(f'tables/units-{c}.json')['codes'] for c in CHARTS}
        cls.weapons = {c: load(f'tables/weapons-{c}.json')['weapons'] for c in CHARTS}
        cls.units = {u['id']: u for c in CHARTS for s in cls.sheets[c] for u in s['units']}

    def test_counts(self):
        self.assertEqual([len(self.sheets[c]) for c in CHARTS], [38, 37, 11])
        self.assertEqual([sum(len(s['units']) for s in self.sheets[c]) for c in CHARTS], [436, 436, 148])

    def test_ids_name_their_chart_and_sheet(self):
        seen = set()
        for c in CHARTS:
            for s in self.sheets[c]:
                self.assertTrue(s['id'].startswith(f'{c}/'), s['id'])
                self.assertIn(s['nat'], NATIONS, s['id'])
                for u in s['units']:
                    self.assertTrue(u['id'].startswith(s['id'] + '/'), u['id'])
                    self.assertNotIn(u['id'], seen)
                    seen.add(u['id'])
                    self.assertIn(u.get('nat', s['nat']), NATIONS, u['id'])

    def test_references_resolve(self):
        for uid, u in self.units.items():
            for key in ('parent', 'replaces'):
                if key in u:
                    self.assertIn(u[key], self.units, f'{uid} {key}')
                    self.assertEqual(u[key].split('/')[0], uid.split('/')[0], f'{uid} {key}')
            # no unit is its own ancestor
            seen, up = {uid}, u.get('parent')
            while up:
                self.assertNotIn(up, seen, uid)
                seen.add(up)
                up = self.units[up].get('parent')
        for c in CHARTS:
            for s in self.sheets[c]:
                for r in s['refs']:
                    self.assertIn(r['unit'], self.units, s['id'])
                    self.assertFalse(r['unit'].startswith(s['id'] + '/'), s['id'])
                    if r['parent']:
                        self.assertIn(r['parent'], self.units, s['id'])

    def test_codes_and_weapons_resolve(self):
        for uid, u in self.units.items():
            chart = uid.split('/')[0]
            self.assertIn(u['code'], self.codes[chart], uid)
            for t in u['toe']:
                self.assertGreater(t['n'], 0, uid)
                if 'w' in t:
                    nat, w = t['w'].split('/')
                    self.assertIn(w, self.weapons[nat], uid)
                if 'code' in t:
                    self.assertIn(t['code'], self.codes[chart], uid)
                if 'land' in t:
                    self.assertLessEqual(t['land'], t['n'], uid)

    def test_arrivals(self):
        for uid, u in self.units.items():
            a = u['arrives']
            if a is None:
                self.assertTrue(u.get('formed') or u.get('replaces') or u.get('standin'), uid)
            elif a != 'D':
                self.assertEqual(set(a), {'turn', 'stage'}, uid)
                self.assertIn(a['stage'], (1, 2, 3), uid)
                self.assertTrue(1 <= a['turn'] <= 111, uid)

    def test_what_the_charts_say(self):
        u = self.units
        self.assertEqual(u['cw/7-armd/1-rtr']['toe'], [{'w': 'cw/a9-cruiser', 'n': 7}])
        self.assertEqual(u['cw/7-armd/1-rtr']['parent'], 'cw/7-armd/7th-armored-bde-hq')
        self.assertEqual((u['cw/7-armd/11-hus']['toe'], u['cw/7-armd/11-hus']['strength']), ([{'n': 6}], 'under'))
        self.assertTrue(u['cw/7-armd/7th-armored-div-hq']['eng'])
        # The 7th Motor Bde replaces the Support Group, whose units stay assigned to it
        self.assertEqual(u['cw/7-armd/7-mtr']['replaces'], 'cw/7-armd/7-spt')
        self.assertEqual(u['cw/7-armd/1-krrc']['parent'], 'cw/7-armd/7-spt')
        self.assertEqual(u['gm/5-le/21']['replaces'], 'gm/5-le/5-le')
        self.assertEqual(u['gm/5-le/i-5']['parent'], 'gm/5-le/5')
        self.assertEqual(u['gm/5-le/5']['parent'], 'gm/5-le/5-le')
        # Seven infantry points and an artillery point (N+1×7.5cm Lt Gun)
        self.assertEqual(u['gm/ramcke/i-kroh']['toe'], [{'n': 7}, {'w': 'gm/7-5-cm-ig18-light-infantry-gun', 'n': 1}])
        self.assertEqual(u['it/tobruk/2-tbrkcd']['toe'][0], {'w': 'it/100-17-howitzer', 'n': 6, 'land': 4})
        self.assertEqual(u['it/recam/recam-hq']['toe'], [{'code': 'vv', 'n': 1}])
        self.assertEqual(u['cw/9-aus/20-aus']['morale'], {'basic': 1, 'untrained': 0})
        self.assertEqual(u['it/it-guns/1-1ar']['morale'], {'basic': -1})  # from its group's row
        self.assertEqual(u['it/it-guns/1-1ar']['group'], '1st Artillery Ragruppamento')
        self.assertNotIn('parent', u['it/it-guns/1-1ar'])
        self.assertEqual(u['it/minor-garrisons/soluch-garrison-arty-regt']['garrison'], 'A4130')
        self.assertEqual(u['cw/allied-other/11-czech']['nat'], 'cz')
        self.assertTrue(u['it/trieste/i-65']['motorized'])
        ltc = next(s for s in self.sheets['it'] if s['id'] == 'it/2-libyan')
        self.assertEqual(ltc['refs'], [{'unit': 'it/ltc/ix-l', 'parent': 'it/2-libyan/2nd-libyan-infantry-hq',
                                        'arrives': 'D', 'note': 'a'}])
        tobruk = next(s for s in self.sheets['it'] if s['id'] == 'it/tobruk')
        self.assertEqual((tobruk['garrison'], tobruk['morale']), ('C4807', {'basic': -3}))

    def test_what_the_addenda_say(self):
        u = self.units
        # The three Italian divisions the rulebook left out ([4.44b] 1)
        sheets = {s['id']: s for s in self.sheets['it']}
        self.assertEqual([sid for sid in sheets][-3:], ['it/sirte', 'it/marmarica', 'it/cirene'])
        self.assertEqual([len(sheets[s]['units']) for s in ('it/sirte', 'it/marmarica', 'it/cirene')], [14, 13, 14])
        self.assertEqual(sheets['it/cirene']['morale'], {'basic': -1})
        self.assertEqual(u['it/cirene/45']['toe'], [{'w': 'it/75-18-gun-howitzer', 'n': 6},
                                                    {'w': 'it/100-17-howitzer', 'n': 3},
                                                    {'w': 'it/light-20mm-m-35-breda', 'n': 3}])
        self.assertEqual(u['it/sirte/61-srt']['arrives'], {'turn': 10, 'stage': 3})
        self.assertEqual(sheets['it/marmarica']['refs'], [{'unit': 'it/ltc/lxii-l', 'parent': 'it/marmarica/62-mrm',
                                                           'arrives': 'D', 'note': 'a'}])
        self.assertEqual(u['cw/allied-other/1']['arrives'], 'D')  # [4.44b] 3
        # Corrections for the set-ups: the XXVI Corps Artillery is the XVI, and the
        # XXIV a stand-in with the XXV's ratings
        self.assertEqual(u['it/it-guns/xvi-cp']['name'], 'XVI Corps Artillery Regt')
        self.assertNotIn('it/it-guns/xxvi-cp', u)
        self.assertEqual(u['it/it-guns/xxiv-cp']['toe'], u['it/it-guns/xxv-cp']['toe'])
        self.assertEqual((u['it/it-guns/xxiv-cp']['arrives'], u['it/it-guns/xxiv-cp']['standin']), (None, True))
        self.assertEqual([uid for uid, x in u.items() if x.get('standin')], ['it/it-guns/xxiv-cp'])

    @unittest.skipUnless(RULEBOOK.exists(), 'the rulebook transcription is not in the project folder')
    def test_matches_the_transcription(self):
        out = DATA / 'units'
        before = {p.name: p.read_bytes() for p in out.glob('*.json')}
        subprocess.run([sys.executable, '-I', str(ROOT / 'tools' / 'units' / 'oa.py')], check=True,
                       capture_output=True)
        after = {p.name: p.read_bytes() for p in out.glob('*.json')}
        self.assertEqual(after, before, 'run python -I tools/units/oa.py and commit the result')


if __name__ == '__main__':
    unittest.main()
