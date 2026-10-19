"""Hex grid geometry for the CNA map sections, fitted to the scanned map image.

Hexes are pointy-topped. A hex id is XXYY: XX is the row, counting north; YY
is the column, counting east. Even rows sit half a column east of odd rows.

A Grid maps (row, col) to pixel coordinates in one map image with an affine
lattice: centre = origin + col * col_vec + row * row_vec (+ col_vec / 2 on even
rows). Fit it to the printed gridlines with fit_grid().
"""
import json
import math
from dataclasses import asdict, dataclass

import numpy as np

# Neighbour offsets (d_row, d_col) by direction, for odd and even rows.
NEIGHBOURS = {
    1: {'E': (0, 1), 'NE': (1, 0), 'NW': (1, -1), 'W': (0, -1), 'SW': (-1, -1), 'SE': (-1, 0)},
    0: {'E': (0, 1), 'NE': (1, 1), 'NW': (1, 0), 'W': (0, -1), 'SW': (-1, 0), 'SE': (-1, 1)},
}
DIRECTIONS = ('E', 'NE', 'NW', 'W', 'SW', 'SE')
OPPOSITE = {'E': 'W', 'NE': 'SW', 'NW': 'SE', 'W': 'E', 'SW': 'NE', 'SE': 'NW'}
# Corner index pairs bounding each side; corners run counter-clockwise from
# the one at angle -30 degrees (east-south-east), in map-north-up terms.
SIDE_CORNERS = {'E': (0, 1), 'NE': (1, 2), 'NW': (2, 3), 'W': (3, 4), 'SW': (4, 5), 'SE': (5, 0)}


def hex_id(row, col):
    return f'{row:02d}{col:02d}'


def parse_id(hid):
    return int(hid[:2]), int(hid[2:])


def neighbour(row, col, direction):
    dr, dc = NEIGHBOURS[row % 2][direction]
    return row + dr, col + dc


@dataclass
class Grid:
    ox: float
    oy: float
    col_dx: float
    col_dy: float
    row_dx: float
    row_dy: float

    def center(self, row, col):
        c = col + (0.5 if row % 2 == 0 else 0.0)
        return (self.ox + c * self.col_dx + row * self.row_dx,
                self.oy + c * self.col_dy + row * self.row_dy)

    def axes(self):
        """Unit vectors for map east and map north in image space."""
        e = np.array([self.col_dx, self.col_dy])
        e /= np.linalg.norm(e)
        n = np.array([e[1], -e[0]])  # east rotated 90 degrees counter-clockwise on screen
        if np.dot(n, [self.row_dx, self.row_dy]) < 0:
            n = -n
        return e, n

    def radius(self):
        return math.hypot(self.col_dx, self.col_dy) / math.sqrt(3)

    def corners(self, row, col):
        cx, cy = self.center(row, col)
        e, n = self.axes()
        r = self.radius()
        pts = []
        for k in range(6):
            a = math.radians(-30 + 60 * k)
            v = r * (math.cos(a) * e + math.sin(a) * n)
            pts.append((cx + v[0], cy + v[1]))
        return pts

    def side(self, row, col, direction):
        a, b = SIDE_CORNERS[direction]
        c = self.corners(row, col)
        return c[a], c[b]

    def save(self, path, **extra):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({**asdict(self), **extra}, f, indent=2)

    @classmethod
    def load(cls, path):
        with open(path, encoding='utf-8') as f:
            d = json.load(f)
        return cls(**{k: d[k] for k in cls.__dataclass_fields__})


def _gridline_score(grid, lum, hexes, offset=(0, 0), sides=('E', 'NE', 'NW')):
    """Mean contrast of the predicted gridlines against their surroundings.

    lum is a 2-D luminance array whose (0, 0) pixel sits at image position
    offset. Higher is better: gridlines are thin dark lines. The default
    sides cover each shared side once; pass DIRECTIONS for a hex's full outline.
    """
    h, w = lum.shape
    ts = np.linspace(0.2, 0.8, 9)
    total, count = 0.0, 0
    for row, col in hexes:
        corners = grid.corners(row, col)
        for d in sides:
            a, b = SIDE_CORNERS[d]
            p0, p1 = np.array(corners[a]), np.array(corners[b])
            along = p1 - p0
            normal = np.array([-along[1], along[0]]) / np.linalg.norm(along)
            pts = p0 + np.outer(ts, along) - offset
            on = _sample(lum, pts, w, h)
            off = (_sample(lum, pts + 7 * normal, w, h) + _sample(lum, pts - 7 * normal, w, h)) / 2
            ok = ~np.isnan(on) & ~np.isnan(off)
            total += float(np.sum(off[ok] - on[ok]))
            count += int(ok.sum())
    return total / count if count else -1e9


def _sample(lum, pts, w, h):
    x = np.round(pts[:, 0]).astype(int)
    y = np.round(pts[:, 1]).astype(int)
    out = np.full(len(pts), np.nan)
    ok = (x >= 0) & (x < w) & (y >= 0) & (y < h)
    out[ok] = lum[y[ok], x[ok]]
    return out


def fit_grid(grid, lum, hexes, offset=(0, 0), rounds=6, anchor=None):
    """Refine grid by coordinate search, maximising gridline contrast.

    The search moves the centre of the anchor hex (default: the middle of
    hexes) and the two lattice vectors, so that small steps stay local to the
    fitted area however far it is from row 0, column 0.
    """
    if anchor is None:
        anchor = hexes[len(hexes) // 2]
    ar, ac = anchor
    ac_eff = ac + (0.5 if ar % 2 == 0 else 0.0)

    def build(p):
        ax, ay, cdx, cdy, rdx, rdy = p
        return Grid(ax - ac_eff * cdx - ar * rdx, ay - ac_eff * cdy - ar * rdy, cdx, cdy, rdx, rdy)

    ax, ay = grid.center(ar, ac)
    p = [ax, ay, grid.col_dx, grid.col_dy, grid.row_dx, grid.row_dy]
    steps = [8.0, 8.0, 0.5, 0.5, 0.5, 0.5]
    best = _gridline_score(build(p), lum, hexes, offset)
    for _ in range(rounds):
        improved = True
        while improved:
            improved = False
            for i in range(6):
                for sign in (1, -1):
                    trial = list(p)
                    trial[i] += sign * steps[i]
                    s = _gridline_score(build(trial), lum, hexes, offset)
                    if s > best:
                        p, best, improved = trial, s, True
        steps = [v / 2 for v in steps]
    return build(p), best


class TiledGrid:
    """A grid fitted piecewise: one affine Grid per tile of tile x tile hexes.

    Absorbs the slow distortion of a scanned map sheet. Hexes in tiles that
    were never fitted (no printed grid there) have no position.
    """

    def __init__(self, tile, tiles):
        self.tile = tile
        self.tiles = tiles  # {(tile_row, tile_col): Grid}

    def key(self, row, col):
        return (row // self.tile, col // self.tile)

    def has(self, row, col):
        return self.key(row, col) in self.tiles

    def grid_for(self, row, col):
        return self.tiles[self.key(row, col)]

    def center(self, row, col):
        return self.grid_for(row, col).center(row, col)

    def corners(self, row, col):
        return self.grid_for(row, col).corners(row, col)

    def side(self, row, col, direction):
        return self.grid_for(row, col).side(row, col, direction)

    def axes(self):
        return next(iter(self.tiles.values())).axes()

    def radius(self):
        return next(iter(self.tiles.values())).radius()

    def save(self, path, **extra):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'tile': self.tile,
                       'tiles': {f'{k[0]},{k[1]}': asdict(g) for k, g in sorted(self.tiles.items())},
                       **extra}, f, indent=1)

    @classmethod
    def load(cls, path):
        with open(path, encoding='utf-8') as f:
            d = json.load(f)
        tiles = {}
        for k, g in d['tiles'].items():
            tr, tc = (int(v) for v in k.split(','))
            tiles[(tr, tc)] = Grid(**{f: g[f] for f in Grid.__dataclass_fields__})
        return cls(d['tile'], tiles)
