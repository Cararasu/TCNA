"""Find candidate landmark symbols on a map section and compare with tags.

Usage:
  python find_symbols.py MAP.png TILES.json DATA.json CORRECTIONS.json

Looks for the Terrain Key's Village/Bir symbol (a small solid blue dot) and
the Training Area symbol (dark soldier figures, as printed beside cities),
assigns each find to the hex containing it, and lists finds in hexes that
carry no landmark tag yet. Finds are candidates for review, not facts.
"""
import json
import math
import os
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))  # the project, for cna
from cna.hexgrid import TiledGrid, hex_id  # noqa: E402

Image.MAX_IMAGE_PIXELS = None


def blobs(mask, min_size, max_size, min_fill):
    """Compact connected components: (cx, cy, w, h, fill) in mask pixels."""
    lab, n = ndimage.label(mask)
    out = []
    for i, sl in enumerate(ndimage.find_objects(lab), start=1):
        h = sl[0].stop - sl[0].start
        w = sl[1].stop - sl[1].start
        if not (min_size <= w <= max_size and min_size <= h <= max_size):
            continue
        if max(w, h) > 1.6 * min(w, h):
            continue
        area = int((lab[sl] == i).sum())
        fill = area / (w * h)
        if fill >= min_fill:
            out.append((sl[1].start + w / 2, sl[0].start + h / 2, w, h, fill))
    return out


def nearest_hex(grid, hexes, x, y):
    best, bd = None, 1e18
    for hid, (cx, cy) in hexes.items():
        d = (cx - x) ** 2 + (cy - y) ** 2
        if d < bd:
            best, bd = hid, d
    return best if math.sqrt(bd) <= grid.radius() else None


def main():
    map_png, tiles, data_path, corr_path = sys.argv[1:5]
    grid = TiledGrid.load(tiles)
    data = json.load(open(data_path, encoding='utf-8'))
    try:
        corr = json.load(open(corr_path, encoding='utf-8'))
    except FileNotFoundError:
        corr = {'hexes': {}}
    tagged = {h: [l['type'] for l in v.get('landmarks', [])] for h, v in corr['hexes'].items()}
    hexes = {h: grid.center(int(h[:2]), int(h[2:])) for h in data}

    img = Image.open(map_png).convert('RGB')
    W, H = img.size
    step, pad = 2048, 64
    dots, figures = [], []
    for y0 in range(0, H, step):
        for x0 in range(0, W, step):
            box = (max(0, x0 - pad), max(0, y0 - pad), min(W, x0 + step + pad), min(H, y0 + step + pad))
            a = np.asarray(img.crop(box), dtype=np.int16)
            r, g, b = a[..., 0], a[..., 1], a[..., 2]
            lum = (r + g + b) / 3
            # Village dot: saturated mid blue, darker than sea or river fill.
            dot = (b - r > 60) & (b > 130) & (lum < 165)
            # The same blue printed over yellow/brown terrain mixes to a dark
            # olive-green, about (70, 90, 45): darker than any terrain fill
            # and greener than the grey tracks and escarpments.
            dot |= (lum < 100) & (g - r > 8) & (g >= b)
            # Roads, tracks and the railroad often run through a dot; an
            # opening keeps the solid ~22 px disc and drops 5-10 px lines.
            dot = ndimage.binary_opening(dot, np.ones((11, 11)))
            for cx, cy, w, h, fill in blobs(dot, 11, 40, 0.55):
                X, Y = cx + box[0], cy + box[1]
                if x0 <= X < x0 + step and y0 <= Y < y0 + step:
                    dots.append((X, Y))
            # Training area figures: near-black, neutral, upright blobs.
            fig = (lum < 80) & ((a.max(-1) - a.min(-1)) < 50)
            fig = ndimage.binary_closing(fig, np.ones((3, 3)))
            lab, n = ndimage.label(fig)
            for i, sl in enumerate(ndimage.find_objects(lab), start=1):
                h = sl[0].stop - sl[0].start
                w = sl[1].stop - sl[1].start
                if 30 <= h <= 80 and 12 <= w <= 55 and h > 1.1 * w:
                    X = sl[1].start + w / 2 + box[0]
                    Y = sl[0].start + h / 2 + box[1]
                    if x0 <= X < x0 + step and y0 <= Y < y0 + step:
                        figures.append((X, Y))

    def by_hex(points):
        out = {}
        for x, y in points:
            hid = nearest_hex(grid, hexes, x, y)
            if hid:
                out[hid] = out.get(hid, 0) + 1
        return out

    dot_hexes = by_hex(dots)
    fig_hexes = {h: n for h, n in by_hex(figures).items() if n >= 3}  # a group of figures
    print(f'blue dots found in {len(dot_hexes)} hexes')
    for h in sorted(dot_hexes):
        t = tagged.get(h, [])
        mark = 'tagged ' + ','.join(t) if t else 'NOT TAGGED'
        print(f'  dot  {h}  {mark}')
    print(f'training-area figure groups in {len(fig_hexes)} hexes')
    for h in sorted(fig_hexes):
        t = tagged.get(h, [])
        mark = 'tagged ' + ','.join(t) if t else 'NOT TAGGED'
        print(f'  figs {h} ({fig_hexes[h]} figures)  {mark}')
    print('tagged villages without a detected dot:',
          ' '.join(sorted(h for h, t in tagged.items() if 'village' in t and h not in dot_hexes)) or '-')


if __name__ == '__main__':
    main()
