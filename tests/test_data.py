"""The data files agree with the vocabulary and with each other."""
import json
import unittest

from cna import vocab
from cna.joined import MAPS, joined
from cna.paths import OFFMAP, SCENARIOS, TABLES, UNIT_DATA


KINDS = ('replacements', 'raider', 'recovery')  # listings with no OA entry
ROSTER = ('less', 'assg', 'att', 'det', 'consists', 'parts')


def load(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def specs(spec):
    """A listing and every unit it describes with fields of its own (in assg, consists, parts, ...)."""
    yield spec
    for k in ROSTER:
        for x in spec.get(k, ()):
            if isinstance(x, dict):
                yield from specs(x)


def claims(spec, top=True):
    """The OA units a listing puts in play by name: itself, and those it assigns, attaches or lists."""
    out = []
    if spec.get('oa') and '/' in spec['oa'][3:]:  # a unit, not a sheet
        out.append(spec['oa'])
    for k in ('assg', 'att', 'consists'):
        for x in spec.get(k, ()):
            if isinstance(x, str):
                out.extend([x] if '/' in x[3:] else [])
            else:
                out.extend(claims(x, False))
    for x in spec.get('parts', ()):
        out.extend(claims({k: v for k, v in x.items() if k != 'oa'}, False))
    return out


class OA:
    """The OA units, sheets, ID codes and weapons systems the links may name."""

    def __init__(self):
        self.units, self.sheets, self.codes, self.weapons, self.nats = {}, set(), set(), set(), {}
        for c in ('cw', 'it', 'gm'):
            for s in load(UNIT_DATA / f'oa-{c}.json')['sheets']:
                self.sheets.add(s['id'])
                self.nats[s['id']] = s['nat']
                self.units.update((u['id'], u) for u in s['units'])
            self.codes |= {f'{c}/{k}' for k in load(TABLES / f'units-{c}.json')['codes']}
            self.weapons |= {f'{c}/{k}' for k in load(TABLES / f'weapons-{c}.json')['weapons']}
        self.replaced = {u['replaces']: uid for uid, u in self.units.items() if 'replaces' in u}

    def ancestors(self, uid):
        """The unit's parents up its sheet, each with the counters that replace it, and its sheet."""
        out = set()
        while uid:
            out.add(uid)
            if uid in self.replaced:
                out.add(self.replaced[uid])
            up = self.units[uid].get('parent')
            if not up:
                out.add(uid.rsplit('/', 1)[0])
            uid = up
        return out

    def check_toe(self, test, toe, where):
        for t in toe:
            test.assertGreater(t['n'], 0, where)
            if 'w' in t:
                test.assertIn(t['w'], self.weapons, where)
            if 'code' in t:
                test.assertTrue(any(c.endswith('/' + t['code']) for c in self.codes), where)

    def check(self, test, spec, where):
        if spec.get('oa'):
            test.assertTrue(spec['oa'] in self.units or spec['oa'] in self.sheets, f'{where}: {spec["oa"]}')
        for k in ROSTER:
            for x in spec.get(k, ()):
                if isinstance(x, dict):
                    self.check(test, x, f'{where} {k}')
                else:
                    test.assertTrue(x in self.units or (k == 'consists' and x in self.sheets), f'{where} {k}: {x}')
        if spec.get('parent'):
            test.assertIn(spec['parent'], self.units, where)
        for x in spec.get('detached', ()):
            test.assertIn(x, spec.get('assg', ()), where)
        for x in spec.get('choose', {}).get('of', ()):
            test.assertIn(x, self.units, where)
        self.check_toe(test, spec.get('toe', ()), where)


class MapData(unittest.TestCase):
    def test_extracted_data_uses_the_vocabulary(self):
        j = joined()
        for m in MAPS:
            for hid, h in j.data[m].items():
                self.assertIn(h['terrain'], vocab.TERRAIN, f'{m}{hid}')
                for d, s in h['sides'].items():
                    where = f'{m}{hid}|{d}'
                    if s.get('feature'):
                        self.assertIn(s['feature']['type'], vocab.FEATURES, where)
                    self.assertIn(s.get('river'), (None, *vocab.RIVERS), where)
                    for x in s['crossings']:
                        self.assertIn(x['kind'], vocab.LINE_ORDER, where)


class Scenarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load(SCENARIOS)
        cls.zones = {z['id']: z for z in load(OFFMAP)['zones']}
        j = joined()
        cls.labels = {f'{m}{hid}' for m, hid in j.where}

    def deployments(self):
        for name, setup in self.data['setups'].items():
            for i, e in enumerate(setup['deploy']):
                yield f'{name}[{i}]', e

    def test_scenarios_name_their_setup(self):
        for s in self.data['scenarios']:
            self.assertIn(s['setup'], self.data['setups'], s['id'])

    def test_units_use_the_vocabulary(self):
        for where, e in self.deployments():
            self.assertIn(e['side'], ('axis', 'cw'), where)
            for u in e['units']:
                self.assertIn(u['type'], vocab.UNIT_TYPES, f'{where} {u["name"]}')
                if 'size' in u:
                    self.assertIn(u['size'], vocab.UNIT_SIZES, f'{where} {u["name"]}')

    def test_every_listing_names_its_units(self):
        """Each listing is linked to the OA Charts (oa, consists or choose), or
        is of a kind that has no OA entry."""
        for where, e in self.deployments():
            for u in e['units']:
                self.assertTrue('oa' in u or 'consists' in u or 'choose' in u or u.get('kind') in KINDS,
                                f'{where} {u["name"]}')

    def test_links_name_oa_units(self):
        oa = OA()
        for name, setup in self.data['setups'].items():
            for t in setup.get('toe', ()):
                for uid, toe in t['units'].items():
                    self.assertIn(uid, oa.units, f'{name} {t["rule"]}')
                    oa.check_toe(self, toe, f'{name} {t["rule"]} {uid}')
            for i, e in enumerate(setup['deploy']):
                for u in e['units']:
                    oa.check(self, u, f'{name}[{i}] {u["name"]}')

    def test_nationalities_agree_with_the_oa_charts(self):
        """A game takes a unit's nationality (its counter's colours) from the OA
        Charts; the listing must say the same."""
        oa = OA()
        for where, e in self.deployments():
            for u in e['units']:
                if u.get('oa') in oa.units:
                    unit = oa.units[u['oa']]
                    sheet = next(s for s in oa.nats if u['oa'].startswith(s + '/'))
                    self.assertEqual(u.get('nat') or e['nat'], unit.get('nat', oa.nats[sheet]), f'{where} {u["name"]}')

    def test_no_unit_is_claimed_twice(self):
        """A unit is listed, assigned, attached or in a roster once in a setup."""
        for name, setup in self.data['setups'].items():
            seen = {}
            for i, e in enumerate(setup['deploy']):
                for u in e['units']:
                    for uid in claims(u):
                        self.assertNotIn(uid, seen, f'{name}[{i}] {u["name"]}: also {seen.get(uid)}')
                        seen[uid] = u['name']

    def test_det_names_units_claimed_elsewhere(self):
        """Det (59.2) names subordinates listed elsewhere in the setup: it adds nothing."""
        for name, setup in self.data['setups'].items():
            listings = [u for e in setup['deploy'] for u in e['units']]
            for u in listings:
                others = {uid for v in listings if v is not u for uid in claims(v)}
                for spec in specs(u):
                    for uid in spec.get('det', ()):
                        self.assertIn(uid, others, f'{name} {u["name"]}')

    def test_less_names_subordinates(self):
        """Less (59.2) names units of the formation's own OA roster."""
        oa = OA()
        for name, setup in self.data['setups'].items():
            for e in setup['deploy']:
                for u in e['units']:
                    for spec in specs(u):
                        for uid in [*spec.get('less', ()), *spec.get('det', ())]:
                            self.assertIn(spec.get('oa'), oa.ancestors(uid), f'{name} {u["name"]}: {uid}')

    def test_text_left_for_later(self):
        """What the set-ups say that M1 doesn't carry out, and the milestone that will."""
        later = {(name, u['name']): u['later'] for name, setup in self.data['setups'].items()
                 for e in setup['deploy'] for u in e['units'] if 'later' in u}
        self.assertEqual(later, {('italians', 'Autoblinda 40 (2 TOE)'): 'M4', ('desert-fox', '7th Armoured Division'): 'M4'})
        rules = {name: [x['rule'] for x in setup.get('later', ())] for name, setup in self.data['setups'].items()}
        self.assertEqual(rules, {'italians': ['60.41'], 'desert-fox': [], 'crusader': ['62.32'],
                                 'alamein': ['63.31', '63.41', '63.42', '63.48']})

    def test_places_are_on_the_map(self):
        for where, e in self.deployments():
            at = e['at']
            if 'box' in at:
                self.assertIn(at['box'], self.zones, where)
            for ref in [at.get('hex'), at.get('near'), at.get('anchor'), *at.get('hexes', [])]:
                if ref:
                    self.assertIn(ref.replace(' ', ''), self.labels, where)

    def test_holding_boxes_name_real_hexes(self):
        for z in self.zones.values():
            if 'hex' in z:
                self.assertIn(z['hex'], self.labels, z['id'])


if __name__ == '__main__':
    unittest.main()
