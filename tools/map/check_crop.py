"""Draw grid outlines and hex ids over part of a map, at full resolution.

Usage:
  python -I check_crop.py MAP.png TILES.json OUT.png --rows R0 R1 --cols C0 C1

For checking a fitted grid by eye: outlines should sit on the printed
gridlines and each red id should match the number printed in its hex.
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hexgrid import TiledGrid, hex_id  # noqa: E402

Image.MAX_IMAGE_PIXELS = None

ap = argparse.ArgumentParser()
ap.add_argument('map')
ap.add_argument('tiles')
ap.add_argument('out')
ap.add_argument('--rows', type=int, nargs=2, required=True)
ap.add_argument('--cols', type=int, nargs=2, required=True)
a = ap.parse_args()

grid = TiledGrid.load(a.tiles)
hexes = [(r, c) for r in range(a.rows[0], a.rows[1] + 1) for c in range(a.cols[0], a.cols[1] + 1)
         if grid.has(r, c)]
img = Image.open(a.map).convert('RGB')
pts = np.array([p for h in hexes for p in grid.corners(*h)])
x0, y0 = (np.floor(pts.min(axis=0)) - 40).astype(int).clip(0)
x1, y1 = (np.ceil(pts.max(axis=0)) + 40).astype(int)
crop = img.crop((int(x0), int(y0), int(min(x1, img.width)), int(min(y1, img.height))))
draw = ImageDraw.Draw(crop)
font = ImageFont.truetype('arial.ttf', 26)
for r, c in hexes:
    draw.polygon([(x - x0, y - y0) for x, y in grid.corners(r, c)], outline=(230, 0, 0), width=3)
    cx, cy = grid.center(r, c)
    draw.text((cx - x0, cy - y0 + 20), hex_id(r, c), fill=(230, 0, 0), font=font, anchor='mm')
crop.save(a.out)
print(a.out)
