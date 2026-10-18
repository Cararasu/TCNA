"""Draw extracted map data over the scan, for checking by eye.

Usage:
  python -I overlay.py MAP.png GRID.json DATA.json OUT.png --rows R0 R1 --cols C0 C1
                       [--scale 1.0]

Terrain is a letter per hex (C clear, G gravel, R rough, M mountain, D desert,
Dl delta, Sm salt marsh, S sea; a trailing c marks a coastal hex, ? an
uncertain one).
Hexside features are thick lines (magenta ridge, orange slope, red
escarpment) with a tick pointing to the "down" hex; rivers are cyan (wide
major, thin minor). Line crossings are circles on the side (green track, pink
road, blue railroad).
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract import load_grid  # noqa: E402
from hexgrid import DIRECTIONS, OPPOSITE, hex_id, neighbour, parse_id  # noqa: E402

Image.MAX_IMAGE_PIXELS = None

FEATURE = {'ridge': (200, 0, 200), 'slope': (230, 110, 0), 'escarpment': (220, 0, 0)}
CROSSING = {'railroad': (0, 120, 255), 'track': (0, 170, 0), 'road': (230, 0, 160)}
RIVER = (0, 230, 255)
ABBREV = {'clear': 'C', 'gravel': 'G', 'rough': 'R', 'mountain': 'M', 'desert': 'D',
          'delta': 'Dl', 'saltmarsh': 'Sm', 'sea': 'S'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('map')
    ap.add_argument('grid')
    ap.add_argument('data')
    ap.add_argument('out')
    ap.add_argument('--rows', type=int, nargs=2, required=True)
    ap.add_argument('--cols', type=int, nargs=2, required=True)
    ap.add_argument('--scale', type=float, default=1.0)
    a = ap.parse_args()

    grid = load_grid(a.grid)
    with open(a.data, encoding='utf-8') as f:
        data = json.load(f)
    hexes = [parse_id(h) for h in data
             if a.rows[0] <= parse_id(h)[0] <= a.rows[1] and a.cols[0] <= parse_id(h)[1] <= a.cols[1]]
    if not hexes:
        sys.exit('no extracted hexes in that range')
    img = Image.open(a.map).convert('RGB')
    pts = np.array([p for h in hexes for p in grid.corners(*h)])
    x0, y0 = (np.floor(pts.min(axis=0)) - 40).astype(int).clip(0)
    x1, y1 = (np.ceil(pts.max(axis=0)) + 40).astype(int)
    box = (int(x0), int(y0), int(min(x1, img.width)), int(min(y1, img.height)))
    base = img.crop(box)
    del img
    over = base.copy()
    draw = ImageDraw.Draw(over)
    font = ImageFont.truetype('arialbd.ttf', 30)
    small = ImageFont.truetype('arial.ttf', 20)

    def P(p):
        return np.array((p[0] - box[0], p[1] - box[1]))

    # Every side of every hex in view, each drawn from the hex that owns it
    # (the data keeps each shared side once, under its E, NE or NW owner).
    owned = set()
    for r, c in hexes:
        for d in DIRECTIONS:
            if d in ('E', 'NE', 'NW'):
                owned.add((hex_id(r, c), d))
            else:
                nb = hex_id(*neighbour(r, c, d))
                if nb in data:
                    owned.add((nb, OPPOSITE[d]))

    for r, c in hexes:
        e = data[hex_id(r, c)]
        cx, cy = P(grid.center(r, c))
        label = (ABBREV.get(e['terrain'], '?') + ('c' if e['coastal'] else '')
                 + ('?' if e.get('uncertain') else ''))
        draw.text((cx, cy - 18), label, fill=(0, 0, 160), font=font, anchor='mm')
        draw.text((cx, cy + 16), hex_id(r, c), fill=(0, 0, 160), font=small, anchor='mm')

    for hid, d in sorted(owned):
        s = data[hid]['sides'].get(d)
        if not s:
            continue
        r, c = parse_id(hid)
        p0, p1 = (P(p) for p in grid.side(r, c, d))
        if s.get('river'):
            draw.line([tuple(p0), tuple(p1)], fill=RIVER,
                      width=14 if s['river'] == 'major' else 6)
        feat = s['feature']
        if feat:
            draw.line([tuple(p0), tuple(p1)], fill=FEATURE[feat['type']], width=9)
            if 'down' in feat:
                m = (p0 + p1) / 2
                dc = P(grid.center(*parse_id(feat['down'])))
                tip = m + (dc - m) / np.linalg.norm(dc - m) * 30
                draw.line([tuple(m), tuple(tip)], fill=FEATURE[feat['type']], width=6)
        for x in s['crossings']:
            m = p0 + (p1 - p0) * x['t']
            draw.ellipse([m[0] - 13, m[1] - 13, m[0] + 13, m[1] + 13],
                         outline=CROSSING[x['kind']], width=6)
    out = Image.blend(base, over, 0.85)
    if a.scale != 1.0:
        out = out.resize((int(out.width * a.scale), int(out.height * a.scale)), Image.LANCZOS)
    out.save(a.out)
    print(a.out)


if __name__ == '__main__':
    main()
