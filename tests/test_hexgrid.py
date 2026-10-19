import unittest

from cna.hexgrid import DIRECTIONS, OPPOSITE, SIDE_CORNERS, Grid, hex_id, neighbour, parse_id


class HexIds(unittest.TestCase):
    def test_round_trip(self):
        for r, c in [(1, 1), (9, 35), (45, 1), (12, 168), (81, 3)]:
            self.assertEqual(parse_id(hex_id(r, c)), (r, c))
        self.assertEqual(hex_id(3, 7), '0307')
        self.assertEqual(hex_id(12, 140), '12140')  # joined-map columns run past 99

    def test_neighbours_are_mutual(self):
        for r in (10, 11):
            for d in DIRECTIONS:
                self.assertEqual(neighbour(*neighbour(r, 20, d), OPPOSITE[d]), (r, 20), (r, d))

    def test_six_distinct_neighbours(self):
        for r in (10, 11):
            self.assertEqual(len({neighbour(r, 20, d) for d in DIRECTIONS}), 6)


class Geometry(unittest.TestCase):
    # Roughly Map A's fit: columns 188 px apart, rows 162 px up the image.
    grid = Grid(ox=33.0, oy=10333.0, col_dx=188.1, col_dy=0.2, row_dx=-0.7, row_dy=-162.5)

    def test_shared_sides_meet(self):
        """A hexside drawn from either hex is the same segment, reversed."""
        for r in (10, 11):
            for d in DIRECTIONS:
                a0, a1 = self.grid.side(r, 20, d)
                b0, b1 = self.grid.side(*neighbour(r, 20, d), OPPOSITE[d])
                for p, q in ((a0, b1), (a1, b0)):
                    self.assertAlmostEqual(p[0], q[0], delta=1.0)
                    self.assertAlmostEqual(p[1], q[1], delta=1.0)

    def test_corner_order(self):
        """Side E is on the east of the hex, NE above it (north is up the image)."""
        cx, cy = self.grid.center(10, 20)
        (ex0, _), (ex1, _) = self.grid.side(10, 20, 'E')
        self.assertGreater(min(ex0, ex1), cx)
        (_, ny0), (_, ny1) = self.grid.side(10, 20, 'NE')
        self.assertLess(max(ny0, ny1), cy + 1)
        self.assertEqual(SIDE_CORNERS['E'], (0, 1))


if __name__ == '__main__':
    unittest.main()
