"""Extract hex terrain and hexside features from a map section image.

Usage (needs scipy, see lines.py):
  python extract.py MAP.png GRID.json OUT.json --rows R0 R1 --cols C0 C1

GRID.json is a single fitted grid (fit_grid.py) or a tiled one (fit_tiles.py).
For every printed hex in the range this records the terrain type and, for its
E, NE and NW sides, any hexside feature (ridge, slope, escarpment) and any
line that crosses the side (road, track, railroad). Slopes and escarpments
carry the direction of their "down" side, which the map shows by the splash
shading. Positions with no printed hex outline are left out. Draw the result
over the map with overlay.py to check it.
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hexgrid import DIRECTIONS, Grid, TiledGrid, _gridline_score, hex_id, neighbour, parse_id  # noqa: E402
from lines import SideFrame, build_masks, line_on_side, river_on_side  # noqa: E402

Image.MAX_IMAGE_PIXELS = None

# Reference colours sampled from Map E (k-means over the whole section), plus
# salt marsh and rock/gravel from the Qattara Depression on Map D.
REFS = {
    'clear': [(253, 239, 188), (249, 232, 181), (240, 226, 178), (253, 243, 189)],
    'marsh': [(225, 216, 137)],
    'gravel': [(244, 226, 148), (227, 208, 111)],
    'sea': [(134, 186, 221)],
    'delta': [(193, 189, 106)],
    'tan': [(179, 159, 85)],
    'brown': [(164, 136, 49)],
    'desert': [(222, 175, 26)],
    'blue': [(116, 154, 175)],
    'dark': [(122, 124, 91), (95, 95, 85), (60, 60, 60)],
}
NAMES = list(REFS)
REF_RGB = np.array([c for n in NAMES for c in REFS[n]], dtype=np.float32)
REF_CLS = np.array([NAMES.index(n) for n in NAMES for _ in REFS[n]])
CLS = {n: i for i, n in enumerate(NAMES)}


def classify(rgb):
    """Index into NAMES of the nearest reference colour, per pixel."""
    flat = rgb.reshape(-1, 3).astype(np.float32)
    out = np.empty(len(flat), dtype=np.int8)
    for s in range(0, len(flat), 1 << 20):
        d = ((flat[s:s + (1 << 20), None, :] - REF_RGB[None]) ** 2).sum(-1)
        out[s:s + (1 << 20)] = REF_CLS[d.argmin(1)]
    return out.reshape(rgb.shape[:2])


class Region:
    """A crop of the map with per-pixel colour classes, addressed in map pixels."""

    def __init__(self, img, box):
        self.x0, self.y0 = box[0], box[1]
        self.rgb = np.asarray(img.crop(box))
        self.cls = classify(self.rgb)
        self.h, self.w = self.cls.shape
        a = self.rgb.astype(np.int16)
        lum = a.mean(-1)
        sat = a.max(-1) - a.min(-1)
        # Neutral grey line work: gridlines, roads, tracks, hex numbers. The
        # saturation limit leaves out the blue-grey railroad and brown splash.
        self.dark = (lum < 150) & (sat < 42)
        # Thick strokes only (track dashes, 8+ px): road lines (5-6 px) and
        # gridlines vanish under a 7x7 erosion. Track dashes printed over
        # splash shading pick up a brown tint, hence the looser limit here.
        self.thick = _dilate(_erode((lum < 150) & (sat < 70), 3), 3)
        self.thin = self.dark & ~_dilate(self.thick, 2)
        self.lines = build_masks(self.rgb)

    def _at(self, arr, pts, fill):
        x = np.round(pts[:, 0] - self.x0).astype(int)
        y = np.round(pts[:, 1] - self.y0).astype(int)
        ok = (x >= 0) & (x < self.w) & (y >= 0) & (y < self.h)
        out = np.full(len(pts), fill, dtype=arr.dtype)
        out[ok] = arr[y[ok], x[ok]]
        return out

    def classes_at(self, pts):
        return self._at(self.cls, pts, -1)

    def mask_at(self, name, pts):
        return self._at(getattr(self, name), pts, False)


def _shifted(mask, r, op):
    out = mask.copy()
    p = np.pad(mask, r, constant_values=(op is np.logical_or) is False)
    h, w = mask.shape
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            out = op(out, p[r + dy:r + dy + h, r + dx:r + dx + w])
    return out


def _erode(mask, r):
    return _shifted(mask, r, np.logical_and)


def _dilate(mask, r):
    return _shifted(mask, r, np.logical_or)


def fractions(c):
    c = c[c >= 0]
    return {n: float(np.mean(c == i)) if len(c) else 0.0 for n, i in CLS.items()}


def hex_interior(grid, row, col, scale=0.6):
    cx, cy = grid.center(row, col)
    e, n = grid.axes()
    r = grid.radius() * scale
    pts = []
    for rad in np.linspace(0.1, 1.0, 10):
        for ang in np.linspace(0, 2 * np.pi, int(12 + 36 * rad), endpoint=False):
            v = r * rad * (np.cos(ang) * e + np.sin(ang) * n)
            pts.append((cx + v[0], cy + v[1]))
    return np.array(pts)


def terrain_of(f):
    """Terrain by majority of the land part of the hex.

    The map paints terrain as patches that don't follow hex outlines and the
    rules don't say how a partly covered hex counts, so a hex whose leading
    terrain covers 30-60 % of it is marked uncertain for review.
    """
    land = 1.0 - f['sea']
    if f['sea'] > 0.85 or land <= 0:
        return 'sea', False
    g = {k: v / land for k, v in f.items() if k != 'sea'}
    shares = {'desert': g['desert'], 'delta': g['delta'], 'rough': g['tan'] + g['brown'],
              'saltmarsh': g['marsh']}
    lead, share = max(shares.items(), key=lambda kv: kv[1])
    if share >= 0.5:
        t = 'mountain' if lead == 'rough' and g['brown'] >= 0.5 else lead
        return t, share <= 0.6
    # Rock/gravel is a stipple on cream, so it never covers most of a hex. The
    # crack lines of salt marsh share its colour, so any marsh fill rules it out.
    if g['gravel'] >= 0.3 and g['marsh'] < 0.1:
        return 'gravel', g['gravel'] < 0.4
    return 'clear', share >= 0.3


SIDE_TS = np.linspace(0.12, 0.88, 40)  # sample positions along a hexside


def side_bands(grid, row, col, direction):
    """Sample points beside one hexside: (side_a, side_b, core), each (t, d) grids.

    side_a lies inside (row, col), side_b inside the neighbour; d is the
    distance from the side line in pixels.
    """
    p0, p1 = (np.array(p) for p in grid.side(row, col, direction))
    along = p1 - p0
    length = np.linalg.norm(along)
    u = along / length
    c0 = np.array(grid.center(row, col))
    normal = np.array([-u[1], u[0]])
    if np.dot(c0 - p0, normal) < 0:
        normal = -normal  # point into this hex
    base = p0 + np.outer(SIDE_TS, along)
    ts = SIDE_TS

    def band(d0, d1, sign):
        ds = np.arange(d0, d1 + 1, 2)
        return (base[:, None, :] + sign * ds[None, :, None] * normal[None, None, :]).reshape(-1, 2), len(ts), len(ds)

    return band, length


def analyse_side(reg, grid, row, col, direction, interiors):
    band, length = side_bands(grid, row, col, direction)
    nb = neighbour(row, col, direction)

    def cls_grid(d0, d1, sign):
        pts, nt, nd = band(d0, d1, sign)
        return reg.classes_at(pts).reshape(nt, nd)

    core = cls_grid(-3, 3, +1)

    def frac(c, names):
        return float(np.mean(np.isin(c, [CLS[n] for n in names])))

    def shaded(sign, names):
        """Splash shading on one side: dense near the line, fading by 50-70 px.

        Terrain patches that merely straddle the side stay dense far out.
        """
        mid = frac(cls_grid(10, 22, sign), names)
        mid2 = frac(cls_grid(24, 34, sign), names)
        far = frac(cls_grid(52, 70, sign), names)
        return (mid > 0.4 or mid2 > 0.3) and (far < 0.45 or far < mid - 0.4)

    def mask_grid(name, d0, d1, sign):
        pts, nt, nd = band(d0, d1, sign)
        return reg.mask_at(name, pts).reshape(nt, nd)

    feat = None
    brownish = ('tan', 'brown')
    core_line = frac(core, ('brown', 'dark'))
    core_dark = frac(core, ('dark',))
    # An escarpment's dark band is solid and wide; a road and railroad running
    # along the side are dark too, but only as thin lines.
    core_thick = float(np.mean(mask_grid('thick', -3, 3, +1)))
    esc_a, esc_b = frac(cls_grid(8, 22, +1), ('dark',)), frac(cls_grid(8, 22, -1), ('dark',))
    # The speckle is dense on the down side and absent on the up side; roads
    # and railroads running along the side are dark too, but never that
    # one-sided. Measured on Maps D/E: escarpments 0.68-0.96 vs <= 0.08;
    # line work along a side at most 0.63 on its darker side.
    if (core_dark > 0.55 and core_thick > 0.5 and max(esc_a, esc_b) >= 0.65
            and min(esc_a, esc_b) <= 0.1):
        feat = {'type': 'escarpment', 'down': 'a' if esc_a > esc_b else 'b'}
    elif core_line > 0.6:
        sa, sb = shaded(+1, brownish), shaded(-1, brownish)
        if sa and sb:
            feat = {'type': 'ridge'}
        elif sa or sb:
            feat = {'type': 'slope', 'down': 'a' if sa else 'b'}
    if feat and 'down' in feat:
        feat['down'] = hex_id(row, col) if feat['down'] == 'a' else hex_id(*nb)

    # Rivers and line work (roads, tracks, railroads): see lines.py. The
    # dark band of an escarpment would read as track along the side, so line
    # work on escarpment sides is left to review.
    p0, p1 = grid.side(row, col, direction)
    frame = SideFrame(p0, p1, grid.center(row, col), (reg.x0, reg.y0))
    fa, fb = interiors.get((row, col)), interiors.get(nb)
    river = river_on_side(frame.sample(reg.lines['water']),
                          fa['sea'] if fa else 0.0, fb['sea'] if fb else 0.0)
    crossings = []
    if not (feat and feat['type'] == 'escarpment'):
        for kind in ('road', 'track', 'railroad'):
            t = line_on_side(frame.sample(reg.lines[kind]), cut_core=(kind == 'road'),
                             deep=12 if kind == 'track' else 14)
            if t is not None:
                crossings.append({'kind': kind, 't': round(t, 3)})
        # Where a road and a railroad cross or merge, their ink together is
        # thick enough to pass for a track dash; a "track" at the same point
        # as a road or railroad crossing is that blob.
        others = [x['t'] for x in crossings if x['kind'] != 'track']
        crossings = [x for x in crossings
                     if x['kind'] != 'track' or all(abs(x['t'] - t) > 0.12 for t in others)]
    return feat, river, crossings


def load_grid(path):
    with open(path, encoding='utf-8') as f:
        tiled = 'tiles' in json.load(f)
    return TiledGrid.load(path) if tiled else Grid.load(path)


def groups(grid, hexes):
    """Split hexes into blocks small enough to process at full resolution."""
    if isinstance(grid, TiledGrid):
        out = {}
        for h in hexes:
            if grid.has(*h):
                out.setdefault(grid.key(*h), []).append(h)
        return list(out.values())
    return [hexes]


# A printed hex outline scores well above this; phantom positions over the
# turn track, holding boxes and margins score near zero.
MIN_OUTLINE = 30.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('map')
    ap.add_argument('grid')
    ap.add_argument('out')
    ap.add_argument('--rows', type=int, nargs=2, required=True)
    ap.add_argument('--cols', type=int, nargs=2, required=True)
    a = ap.parse_args()

    grid = load_grid(a.grid)
    img = Image.open(a.map).convert('RGB')
    hexes = [(r, c) for r in range(a.rows[0], a.rows[1] + 1) for c in range(a.cols[0], a.cols[1] + 1)]

    def block_box(block, pad):
        pts = np.array([p for h in block for p in grid.corners(*h)])
        x0, y0 = (np.floor(pts.min(axis=0)) - pad).astype(int).clip(0)
        x1, y1 = (np.ceil(pts.max(axis=0)) + pad).astype(int)
        return (int(x0), int(y0), int(min(x1, img.width)), int(min(y1, img.height)))

    # Pass 1: which positions hold a printed hex. Score each outline; then
    # also keep positions that most of their neighbours surround, since a
    # hole inside the map is a real hex whose gridlines are faint (the sheet's
    # fold line, dense artwork) rather than a phantom over the margins.
    outlines = {}
    for block in groups(grid, hexes):
        box = block_box(block, 40)
        lum = np.asarray(img.crop(box).convert('L'), dtype=np.float32)
        for h in block:
            outlines[h] = _gridline_score(grid, lum, [h], offset=(box[0], box[1]), sides=DIRECTIONS)
    keep = {h for h, v in outlines.items() if v >= MIN_OUTLINE}

    def enclosed(h):
        n = sum(neighbour(*h, d) in keep for d in DIRECTIONS)
        # Inside the map: most neighbours are hexes. On the map edge only
        # three can be, so there also require the column to carry on above
        # and below (a gap in an edge column, not the margin).
        r, c = h
        return n >= 4 or (n >= 3 and (r - 2, c) in keep and (r + 2, c) in keep)

    while True:
        add = {h for h in outlines if h not in keep and enclosed(h)}
        if not add:
            break
        keep |= add
    filled = sorted(hex_id(*h) for h in keep if outlines[h] < MIN_OUTLINE)
    if filled:
        print(f'kept {len(filled)} faint hexes surrounded by others: {" ".join(filled)}', flush=True)

    # Pass 2: extract the kept hexes.
    result, skipped = {}, [hex_id(*h) for h in outlines if h not in keep]
    for block in groups(grid, sorted(keep)):
        box = block_box(block, 300)
        reg = Region(img, box)

        interiors = {}
        ring = {neighbour(r, c, d) for r, c in block for d in DIRECTIONS} | set(block)
        for h in ring:
            if grid.has(*h) if isinstance(grid, TiledGrid) else True:
                interiors[h] = fractions(reg.classes_at(hex_interior(grid, *h)))
        for r, c in block:
            outline = outlines[(r, c)]
            f = interiors[(r, c)]
            t, uncertain = terrain_of(f)
            entry = {'terrain': t, 'uncertain': uncertain, 'coastal': 0.1 < f['sea'] <= 0.85,
                     'outline': round(outline, 1),
                     'mix': {k: round(v, 2) for k, v in f.items() if v >= 0.03}, 'sides': {}}
            for d in ('E', 'NE', 'NW'):
                feat, river, cross = analyse_side(reg, grid, r, c, d, interiors)
                if feat or river or cross:
                    entry['sides'][d] = {'feature': feat, 'river': river, 'crossings': cross}
            result[hex_id(r, c)] = entry
        print(f'block of {len(block)} hexes done ({len(result)} kept so far)', flush=True)

    # Sides that face a hex with no printed outline (off the map) don't exist.
    for hid, e in result.items():
        r, c = parse_id(hid)
        for d in list(e['sides']):
            if hex_id(*neighbour(r, c, d)) not in result:
                del e['sides'][d]

    # An escarpment's speckle reaches round its corners and looks like line
    # work on the neighbouring sides; drop crossings close to those corners.
    corners = []
    for hid, e in result.items():
        for d, s in e['sides'].items():
            if s['feature'] and s['feature']['type'] == 'escarpment':
                corners.extend(grid.side(*parse_id(hid), d))
    corners = np.array(corners) if corners else np.zeros((0, 2))
    for hid, e in result.items():
        for d, s in e['sides'].items():
            p0, p1 = (np.array(p) for p in grid.side(*parse_id(hid), d))
            keep = []
            for x in s['crossings']:
                m = p0 + (p1 - p0) * x['t']
                if not len(corners) or np.min(np.linalg.norm(corners - m, axis=1)) > 40:
                    keep.append(x)
            s['crossings'] = keep
        e['sides'] = {d: s for d, s in e['sides'].items() if s['feature'] or s['river'] or s['crossings']}

    with open(a.out, 'w', encoding='utf-8') as f:
        json.dump(dict(sorted(result.items())), f, indent=1)
    print(f'{len(result)} hexes, {len(skipped)} positions without a printed hex -> {a.out}')


if __name__ == '__main__':
    main()
