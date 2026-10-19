"""The data files agree with the vocabulary and with each other."""
import json
import unittest

from cna import vocab
from cna.joined import MAPS, joined
from cna.paths import OFFMAP, SCENARIOS


def load(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


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
