"""Line work on the map: roads, tracks, railroads and rivers, judged per hexside.

Pixel masks are built per line type for a block of the map, then each hexside
is examined in its own (t, d) frame: t runs along the side (0 at the first
corner, 1 at the second), d is the signed distance from it in pixels.

A line *crosses* a side when a piece of it on one side and a piece on the
other, each extended to the side, meet it at the same point. That works at any
angle, including the shallow ones common in the Nile delta. For the rules a
road, track or railroad is only ever a chain of hexes linked through the
hexsides it crosses (Case 8.33); where the art draws one hugging a hexside it
lies wholly inside one hex and crosses that hex's other sides near the
corners, hence the samples reaching close to each corner. Rivers are drawn
along hexsides but wander off the line by up to ~40 px, so water near the
side over most of it counts.

Needs scipy (connected components, sampling).
"""
import numpy as np
from scipy import ndimage

# Samples along a side (t) and across it (d, pixels).
TS = np.linspace(0.02, 0.98, 50)
DS = np.arange(-34, 35, 2)
T_STEP = TS[1] - TS[0]


def build_masks(rgb):
    """Per-pixel masks for one block of the map (rgb: H x W x 3 uint8)."""
    a = rgb.astype(np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    lum = (r + g + b) / 3
    sat = a.max(-1) - a.min(-1)
    # Light blue fill of sea, lakes and rivers: (134, 186, 221) at sea, as grey
    # as (137, 180, 191) in delta channels. The railroad over cream,
    # (110, 143, 156), is bluish too but always darker (lum <= 150 vs >= 160).
    water = (b > r + 35) & (b > 165) & (lum > 158)
    near_water = ndimage.binary_dilation(water, iterations=6)
    # Grey line work. Printed over the olive delta it takes on some of the
    # background colour, hence the loose saturation limit; hue limits keep out
    # the blue/teal railroad and river outlines.
    grey = (lum < 135) & (sat < 62) & (b - r < 25) & (g - r < 25)
    # Track dashes are 8+ px thick; road lines (5-6 px), gridlines and hex
    # numbers vanish under a 7 x 7 erosion.
    thick = ndimage.binary_dilation(ndimage.binary_erosion(grey, np.ones((7, 7))), np.ones((7, 7)))
    thin = grey & ~ndimage.binary_dilation(thick, iterations=2)
    # Hex numbers and other small print: drop small separate specks.
    lab, n = ndimage.label(thin, np.ones((3, 3)))
    if n:
        sizes = ndimage.find_objects(lab)
        small = np.zeros(n + 1, bool)
        for i, sl in enumerate(sizes, start=1):
            h = sl[0].stop - sl[0].start
            w = sl[1].stop - sl[1].start
            small[i] = max(h, w) < 30
        thin &= ~small[lab]
    # Wadi: a grey-green band ~20 px wide, e.g. (135, 162, 137). The teal
    # railroad over the delta has a similar hue but is only a 5-6 px line,
    # which the opening removes.
    wadi = (g - r > 15) & (g - b > 8) & (lum > 100) & (lum < 185)
    wadi = ndimage.binary_opening(wadi, np.ones((9, 9)))
    # Border: thick blue-grey dashes, e.g. (73, 124, 145), 10-12 px across.
    # The railroad, (91, 137, 145), is a 5 px line with ties, which a 7 x 7
    # opening removes. (Village dots survive too, but are no line.)
    # Dark river channel fill, (116, 154, 175), is as blue but redder.
    bluish = (b - r > 40) & (lum < 160) & (r < 100) & ~water
    border = ndimage.binary_opening(bluish, np.ones((7, 7)))
    # Railroad: blue over cream, teal over the delta. River outlines share the
    # colour but sit right next to river water; wadi edges and border dashes
    # are kept out as well.
    rail = (lum < 165) & (((b - r) > 28) | ((g - r) > 28)) & ~water & ~near_water
    rail &= ~ndimage.binary_dilation(wadi | border, iterations=10)
    return {'water': water, 'road': thin, 'track': thick, 'railroad': rail & ~thick,
            'wadi': wadi, 'border': border}


class SideFrame:
    """Sampling grid in a hexside's (t, d) frame. d > 0 lies in hex A."""

    def __init__(self, p0, p1, centre_a, origin):
        p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
        along = p1 - p0
        self.length = float(np.linalg.norm(along))
        u = along / self.length
        n = np.array([-u[1], u[0]])
        if np.dot(np.asarray(centre_a) - p0, n) < 0:
            n = -n
        pts = p0[None, None, :] + TS[:, None, None] * along[None, None, :] + DS[None, :, None] * n[None, None, :]
        self.x = pts[..., 0] - origin[0]
        self.y = pts[..., 1] - origin[1]

    def sample(self, mask):
        return ndimage.map_coordinates(mask.astype(np.uint8), [self.y, self.x], order=0, mode='constant') > 0


def _pieces(grid, cut_core):
    """Connected line pieces in a (t, d) grid as (t_idx, d_px) cell arrays."""
    g = grid.copy()
    if cut_core:
        g[:, np.abs(DS) <= 3] = False  # the side's own gridline
    lab, n = ndimage.label(g, np.ones((3, 3)))
    out = []
    for i in range(1, n + 1):
        ti, di = np.nonzero(lab == i)
        if len(ti) >= 3:
            out.append((ti, DS[di]))
    return out


def _t_at_side(ti, d):
    """Where the piece, extended as a straight line, meets d = 0 (t index)."""
    if np.ptp(d) < 6:
        return None
    b, a = np.polyfit(d, ti, 1)
    return a


def line_on_side(grid, cut_core, deep=14):
    """t (0..1 along the side) where this line type crosses the side, or None."""
    pieces = _pieces(grid, cut_core)
    a_side = [p for p in pieces if p[1].max() >= deep]   # reaches well into A
    b_side = [p for p in pieces if p[1].min() <= -deep]  # reaches well into B
    hits = []
    for ti, d in pieces:
        # One piece straddling the side: a track dash or railroad crossing it.
        # A slanted dash reaches only 6-10 px into each hex. (Roads have the
        # gridline cut out of the middle, so never straddle.)
        if d.min() <= -6 and d.max() >= 6:
            t0 = _t_at_side(ti, d)
            if t0 is not None and 0 <= t0 <= len(TS) - 1:
                hits.append(t0)
    for ta, da in a_side:
        for tb, db in b_side:
            if ta is tb:
                continue
            t0a, t0b = _t_at_side(ta, da), _t_at_side(tb, db)
            if t0a is None or t0b is None:
                continue
            if abs(t0a - t0b) <= 4 and -1 <= (t0a + t0b) / 2 <= len(TS):
                hits.append((t0a + t0b) / 2)
    if not hits:
        return None
    t = float(np.clip(np.median(hits), 0, len(TS) - 1))
    return float(TS[0] + t * T_STEP)


def wadi_on_side(grid):
    """True if a wadi runs along the side: the band near it over most of it."""
    return bool(grid.any(1).mean() >= 0.5)  # the band wanders up to ~35 px off the side


def border_on_side(grid):
    """True if border dashes run along the side (dashed, so 35 % is plenty)."""
    return bool(grid[:, np.abs(DS) <= 12].any(1).mean() >= 0.25)


def river_on_side(water_grid, sea_a, sea_b):
    """'major' / 'minor' / None. sea_a/sea_b: sea share of the two hex interiors."""
    if max(sea_a, sea_b) > 0.5:
        return None  # coast or open water, not a river
    near = water_grid[:, np.abs(DS) <= 32]
    covered = near.any(1)
    if covered.mean() < 0.6:
        return None
    widths = near.sum(1)[covered] * 2  # d samples are 2 px apart
    return 'major' if np.median(widths) >= 18 else 'minor'
