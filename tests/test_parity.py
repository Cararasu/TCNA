"""The browser's hex rules (web/shared/hex.js) agree with the Python ones.

Needs Node.js on PATH; skipped without it.
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

from cna import vocab
from cna.corrections import OWNED, hex_effective, norm_side
from cna.hexgrid import DIRECTIONS, NEIGHBOURS, OPPOSITE, SIDE_CORNERS, hex_id, neighbour, parse_id

SIDES = [
    None, {},
    {'river': 'major', 'wadi': True, 'border': 1},
    {'feature': {'type': 'slope', 'down': '0405'}, 'cross': [{'k': 'railroad'}, {'k': 'road', 't': 0.3}]},
    {'feature': {'type': 'ridge'}, 'cross': [{'k': k} for k in reversed(vocab.LINE_ORDER)], 'along': []},
]
HEXES = [
    ({'terrain': 'clear', 'uncertain': True}, None),
    ({'terrain': 'clear', 'uncertain': True}, {'terrain': 'rough'}),
    ({'terrain': 'sea', 'uncertain': False}, {'landmarks': [{'type': 'port', 'name': 'Tobruk'}], 'reviewed': True}),
]
IDS = ['0101', '1020', '1121', '45140', '8203']


def py_side_key(hid, d):
    if d in OWNED:
        return f'{hid}|{d}'
    return f'{hex_id(*neighbour(*parse_id(hid), d))}|{OPPOSITE[d]}'


@unittest.skipUnless(shutil.which('node'), 'Node.js is not on PATH')
class Parity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        script = Path(__file__).with_name('parity.mjs')
        cases = {'vocab': vocab.RAW, 'sides': SIDES, 'hexes': HEXES, 'ids': IDS}
        run = subprocess.run(['node', str(script)], input=json.dumps(cases), capture_output=True, text=True,
                             encoding='utf-8', check=True)
        cls.js = json.loads(run.stdout)

    def test_constants(self):
        c = self.js['constants']
        self.assertEqual(c['DIRS'], list(DIRECTIONS))
        self.assertEqual(c['OPPOSITE'], OPPOSITE)
        self.assertEqual(c['SIDE_CORNERS'], {k: list(v) for k, v in SIDE_CORNERS.items()})
        self.assertEqual(c['NEIGHBOURS'], {str(p): {d: list(v) for d, v in n.items()} for p, n in NEIGHBOURS.items()})

    def test_norm_side(self):
        self.assertEqual(self.js['normSide'], [norm_side(s) for s in SIDES])

    def test_hex_of(self):
        self.assertEqual(self.js['hexOf'], [hex_effective(a, c) for a, c in HEXES])

    def test_neighbours_and_side_keys(self):
        self.assertEqual(self.js['neighbours'], [[hex_id(*neighbour(*parse_id(i), d)) for d in DIRECTIONS] for i in IDS])
        self.assertEqual(self.js['sideKeys'], [[py_side_key(i, d) for d in DIRECTIONS] for i in IDS])


if __name__ == '__main__':
    unittest.main()
