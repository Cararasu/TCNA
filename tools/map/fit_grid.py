"""Fit a hex grid to a rendered map section and draw a check overlay.

Usage:
  python -I fit_grid.py MAP.png GRID.json --rows 25 30 --cols 1 12
                        [--init ox oy col_dx col_dy row_dx row_dy] [--overlay OUT.png]

Without --init, GRID.json is read as the starting grid. The fitted grid is
written back to GRID.json. The overlay shows the fitted hex outlines and ids
over the region so the fit can be checked by eye.
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hexgrid import Grid, fit_grid, hex_id  # noqa: E402

Image.MAX_IMAGE_PIXELS = None

ap = argparse.ArgumentParser()
ap.add_argument('map')
ap.add_argument('grid')
ap.add_argument('--rows', type=int, nargs=2, required=True)
ap.add_argument('--cols', type=int, nargs=2, required=True)
ap.add_argument('--init', type=float, nargs=6)
ap.add_argument('--overlay')
a = ap.parse_args()

grid = Grid(*a.init) if a.init else Grid.load(a.grid)
hexes = [(r, c) for r in range(a.rows[0], a.rows[1] + 1) for c in range(a.cols[0], a.cols[1] + 1)]

img = Image.open(a.map)
pts = np.array([p for h in hexes for p in grid.corners(*h)])
pad = 60
x0, y0 = (np.floor(pts.min(axis=0)) - pad).astype(int).clip(0)
x1, y1 = (np.ceil(pts.max(axis=0)) + pad).astype(int)
x1, y1 = min(x1, img.width), min(y1, img.height)
crop = img.crop((x0, y0, x1, y1))
lum = np.asarray(crop.convert('L'), dtype=np.float32)

before = fit_grid(grid, lum, hexes, offset=(x0, y0), rounds=0)[1]
grid, score = fit_grid(grid, lum, hexes, offset=(x0, y0))
print(f'gridline contrast: {before:.1f} -> {score:.1f}')
print(grid)
grid.save(a.grid, fitted_rows=a.rows, fitted_cols=a.cols, score=score)

if a.overlay:
    draw = ImageDraw.Draw(crop)
    try:
        font = ImageFont.truetype('arial.ttf', 26)
    except OSError:
        font = ImageFont.load_default()
    for r, c in hexes:
        poly = [(x - x0, y - y0) for x, y in grid.corners(r, c)]
        draw.polygon(poly, outline=(230, 0, 0), width=3)
        cx, cy = grid.center(r, c)
        draw.text((cx - x0, cy - y0 + 20), hex_id(r, c), fill=(230, 0, 0), font=font, anchor='mm')
    crop.save(a.overlay)
    print(a.overlay)
