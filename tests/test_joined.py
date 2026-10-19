import unittest

from cna.corrections import hex_effective, norm_side
from cna.joined import MALTA, MAPS, SECTIONS, SHIFT, Joined, all_corrections, joined, unsynced


class Ids(unittest.TestCase):
    def test_global_and_local_ids(self):
        self.assertEqual(Joined.global_id('A', '1005'), '1005')
        self.assertEqual(Joined.global_id('C', '1005'), f'10{5 + 2 * SHIFT:02d}')
        for m in MAPS:
            self.assertEqual(Joined.local_id(m, Joined.global_id(m, '1203')), '1203')
        self.assertIsNone(Joined.local_id(MALTA, '1203'))  # Africa is not on Malta
        self.assertIsNone(Joined.local_id('B', '1203'))     # west of Map B


class OnTheMapData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.j = joined()
        cls.corr = all_corrections()

    def test_shared_hexes_are_on_neighbouring_sections(self):
        for g in self.j.shared():
            sections = sorted(SECTIONS.index(m) for m, _ in self.j.hexes[g])
            self.assertEqual(len(sections), 2)
            self.assertEqual(sections[1] - sections[0], 1, g)

    def test_corrections_on_disk_are_in_sync(self):
        self.assertEqual(unsynced(self.j, self.corr), 0, 'run python -m cna.sync')

    def test_split_undoes_merged(self):
        out = self.j.split(self.j.merged(self.corr), self.corr)
        for m in MAPS:
            self.assertEqual({k: v for k, v in out[m]['hexes'].items() if v}, self.corr[m]['hexes'], m)
            self.assertEqual({k: norm_side(v) for k, v in out[m]['sides'].items()}, self.corr[m]['sides'], m)

    def test_an_edit_reaches_the_other_copy(self):
        g = next(g for g in self.j.shared())
        (east, he), (west, hw) = self.j.hexes[g]
        new = {'hexes': {**self.corr[east]['hexes'], he: {'terrain': 'swamp'}}, 'sides': dict(self.corr[east]['sides'])}
        out = self.j.propagate(east, new, self.corr)
        self.assertEqual(hex_effective(self.j.data[west][hw], out[west]['hexes'].get(hw))['terrain'], 'swamp')

    def test_sections_lie_west_to_east(self):
        off, _ = self.j.offsets()
        xs = [off[m][0] for m in SECTIONS]
        self.assertEqual(xs, sorted(xs))


if __name__ == '__main__':
    unittest.main()
