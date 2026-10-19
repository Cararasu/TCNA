import json
import unittest

from cna.corrections import auto_side, check_corrections, norm_side, normalize
from cna.joined import MAPS
from cna.paths import map_corrections


def corrections(**kw):
    return {'hexes': kw.get('hexes', {}), 'sides': kw.get('sides', {})}


class Checks(unittest.TestCase):
    def test_accepts_editor_output(self):
        check_corrections(corrections(
            hexes={'0101': {'terrain': 'swamp', 'landmarks': [{'type': 'village', 'name': 'Bir Hakeim'}], 'reviewed': True}},
            sides={'0101|E': norm_side({'river': 'minor', 'cross': [{'k': 'road'}]}),
                   '0101|NE': norm_side({'feature': {'type': 'slope', 'down': '0201'}}),
                   '0101|NW': norm_side({'feature': {'type': 'ridge'}})}))

    def test_refuses_bad_values(self):
        bad = [
            corrections(hexes={'0101': {'terrain': 'lava'}}),
            corrections(hexes={'0101': {'landmarks': [{'type': 'castle'}]}}),
            corrections(hexes={'0101': {'reviewed': 'yes'}}),
            corrections(hexes={'0101': {'colour': 'red'}}),
            corrections(hexes={'0101': 'swamp'}),
            corrections(hexes={'101': {}}),
            corrections(sides={'0101|W': norm_side({})}),
            corrections(sides={'0101|E': {**norm_side({}), 'river': 'huge'}}),
            corrections(sides={'0101|E': {**norm_side({}), 'cross': [{'k': 'canal'}]}}),
            corrections(sides={'0101|E': {**norm_side({}), 'feature': {'type': 'slope'}}}),
            corrections(sides={'0101|E': {**norm_side({}), 'feature': {'type': 'ridge', 'down': '0201'}}}),
            corrections(sides={'0101|E': {**norm_side({}), 'along': []}}),
            {'hexes': []},
        ]
        for obj in bad:
            with self.assertRaises(ValueError, msg=obj):
                check_corrections(obj)

    def test_joined_ids_have_five_digits(self):
        check_corrections(corrections(hexes={'12140': {'terrain': 'sea'}}), '4,5')
        with self.assertRaises(ValueError):
            check_corrections(corrections(hexes={'12140': {'terrain': 'sea'}}))


class Forms(unittest.TestCase):
    def test_norm_side_is_idempotent(self):
        s = {'river': 'major', 'cross': [{'k': 'track', 't': 0.4}, {'k': 'road'}], 'along': [], 'wadi': 0}
        n = norm_side(s)
        self.assertEqual(norm_side(n), n)
        self.assertEqual(n['cross'], [{'k': 'road'}, {'k': 'track'}])  # vocabulary order
        self.assertNotIn('along', n)

    def test_auto_side_prefers_river_to_wadi(self):
        s = auto_side({'river': 'minor', 'wadi': True, 'crossings': [{'kind': 'road', 't': 0.5}]})
        self.assertEqual(s['river'], 'minor')
        self.assertFalse(s['wadi'])
        self.assertEqual(s['cross'], [{'k': 'road'}])

    def test_normalize_drops_empty_hexes(self):
        out = normalize(corrections(hexes={'0101': {'reviewed': False}, '0102': {'reviewed': True}}))
        self.assertEqual(out['hexes'], {'0102': {'reviewed': True}})


class FilesOnDisk(unittest.TestCase):
    def test_every_corrections_file_is_valid_and_in_stored_form(self):
        for m in MAPS:
            with self.subTest(map=m):
                with open(map_corrections(m), encoding='utf-8') as f:
                    raw = json.load(f)
                check_corrections(raw)
                self.assertEqual(raw, normalize(raw), 'not in stored form: run python -m cna.sync')


if __name__ == '__main__':
    unittest.main()
