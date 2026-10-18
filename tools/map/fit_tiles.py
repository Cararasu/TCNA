"""Fit a tiled hex grid over a whole map section, growing out from a seed fit.

Usage:
  python -I fit_tiles.py MAP.png SEED_GRID.json OUT_TILES.json
                         [--tile 6] [--rows 1 45] [--cols 1 36] [--min-score 35]
                         [--overlay OUT.png]

The seed grid must already fit some part of the map (see fit_grid.py). Each
tile is fitted starting from an already-fitted neighbour, so the hex
numbering carries over without slipping. A tile whose best gridline contrast
stays below --min-score (mostly sea or off the map) borrows the fit of the
neighbour it was reached from.
"""
import argparse
import json
import os
import sys
from collections import deque

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hexgrid import Grid, TiledGrid, _gridline_score, fit_grid  # noqa: E402

Image.MAX_IMAGE_PIXELS = None

ap = argparse.ArgumentParser()
ap.add_argument('map')
ap.add_argument('seed')
ap.add_argument('out')
ap.add_argument('--tile', type=int, default=6)
ap.add_argument('--rows', type=int, nargs=2, default=(1, 45))
ap.add_argument('--cols', type=int, nargs=2, default=(1, 36))
ap.add_argument('--min-score', type=float, default=35.0)
ap.add_argument('--overlay')
a = ap.parse_args()

img = Image.open(a.map)
lum = np.asarray(img.convert('L'))
seed = Grid.load(a.seed)
T = a.tile


def tile_hexes(tr, tc):
    return [(r, c) for r in range(tr * T, tr * T + T) for c in range(tc * T, tc * T + T)
            if a.rows[0] <= r <= a.rows[1] and a.cols[0] <= c <= a.cols[1]]


def inside(grid, hexes):
    """Keep hexes whose centres fall on the image."""
    h, w = lum.shape
    out = []
    for r, c in hexes:
        x, y = grid.center(r, c)
        if 60 <= x < w - 60 and 60 <= y < h - 60:
            out.append((r, c))
    return out


# Seed tile: the one holding the middle of the seed fit.
with open(a.seed, encoding='utf-8') as f:
    meta = json.load(f)
sr = (meta['fitted_rows'][0] + meta['fitted_rows'][1]) // 2
sc = (meta['fitted_cols'][0] + meta['fitted_cols'][1]) // 2
start = (sr // T, sc // T)

tiles, scores, empty, borrowed = {}, {}, set(), set()
queue = deque([(start, seed)])
seen = {start}
while queue:
    key, init = queue.popleft()
    hexes = inside(init, tile_hexes(*key))
    if len(hexes) < 4:
        empty.add(key)
        continue
    grid, score = fit_grid(init, lum, hexes)
    if score < a.min_score:
        # Too little printed grid to fit on its own (mostly sea, or mostly
        # off the map). Borrow the neighbour's fit, which is good to a few
        # pixels one tile away; extract.py's outline test then keeps only the
        # hexes that are really printed. Don't grow further from it.
        tiles[key] = init
        borrowed.add(key)
        print(f'tile {key}: contrast {score:.1f}, borrowing neighbour fit', flush=True)
        continue
    tiles[key], scores[key] = grid, score
    for d in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        nk = (key[0] + d[0], key[1] + d[1])
        lo_r, hi_r = a.rows[0] // T, a.rows[1] // T
        lo_c, hi_c = a.cols[0] // T, a.cols[1] // T
        if nk not in seen and lo_r <= nk[0] <= hi_r and lo_c <= nk[1] <= hi_c:
            seen.add(nk)
            queue.append((nk, grid))
    print(f'tile {key}: {len(hexes)} hexes, contrast {score:.1f}', flush=True)

tg = TiledGrid(T, tiles)
tg.save(a.out, scores={f'{k[0]},{k[1]}': round(v, 1) for k, v in scores.items()},
        borrowed=sorted(f'{k[0]},{k[1]}' for k in borrowed),
        empty=sorted(f'{k[0]},{k[1]}' for k in empty))
print(f'{len(tiles) - len(borrowed)} tiles fitted, {len(borrowed)} borrowed, {len(empty)} empty -> {a.out}')

if a.overlay:
    small = img.convert('RGB').resize((img.width // 4, img.height // 4))
    draw = ImageDraw.Draw(small)
    for key, grid in tiles.items():
        for r, c in tile_hexes(*key):
            draw.polygon([(x / 4, y / 4) for x, y in grid.corners(r, c)], outline=(230, 0, 0))
    small.save(a.overlay)
    print(a.overlay)
