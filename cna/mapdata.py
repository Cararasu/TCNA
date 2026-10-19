"""What the server sends about the map: overlays for the editor, the board for
the game, and the title screen's picture of the joined board.

All geometry is in scan pixels: a section's own for one section, the joined
map's (each section's scan placed by Joined.offsets) for the joined map.
"""
import io
import json
import math
import threading

from PIL import Image, ImageDraw

from .corrections import auto_side, hex_effective, load_corrections, norm_side
from .hexgrid import TiledGrid, parse_id
from .joined import MALTA, MAPS, SECTIONS, all_corrections, joined, unsynced
from .paths import CACHE, OFFMAP, map_corrections, map_data, map_tiles
from .scans import IMAGES

TITLE_ZOOM = 3  # the title screen's board: each scan at 1/8 scale


def r1(p):
    return [round(float(p[0]), 1), round(float(p[1]), 1)]


def _mtimes(paths):
    return tuple(p.stat().st_mtime_ns if p.exists() else 0 for p in paths)


def maps_list():
    """Every map the editor can open, and whether it has extracted data yet."""
    out = [{'id': m, 'hasData': map_data(m).exists() and map_tiles(m).exists()} for m in MAPS]
    out.append({'id': 'ALL', 'hasData': all(m['hasData'] for m in out)})
    return out


def overlay(map_id):
    """One map's automatic data, hex geometry in map pixels, and its corrections.

    Hex corners run counter-clockwise from east-south-east, so side E is
    corners 0-1, NE 1-2, NW 2-3, W 3-4, SW 4-5, SE 5-0. Sides are keyed by
    the hex that owns them (its E, NE or NW side), as in the extracted data.
    """
    grid = TiledGrid.load(map_tiles(map_id))
    with open(map_data(map_id), encoding='utf-8') as f:
        data = json.load(f)
    hexes, sides = [], {}
    for hid, e in data.items():
        r, c = parse_id(hid)
        hexes.append({'id': hid, 'c': r1(grid.center(r, c)), 'p': [r1(p) for p in grid.corners(r, c)],
                      't': e['terrain'], 'u': bool(e.get('uncertain')), 'coastal': bool(e.get('coastal')),
                      'mix': e.get('mix', {})})
        for d, s in e['sides'].items():
            sides[f'{hid}|{d}'] = auto_side(s)
    image = IMAGES[map_id]
    w, h = image.size()
    # Tiles are cached by the browser, so their URLs carry the scan's version.
    out = {'id': map_id, 'image': image.id, 'width': w, 'height': h, 'zmax': image.zmax(), 'v': image.version(),
           'hexes': hexes, 'sides': sides, 'corrections': load_corrections(map_id)}
    if map_id == MALTA:  # open on the inset, not the whole sheet
        pts = [p for hx in hexes for p in hx['p']]
        out['focus'] = [min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)]
    return out


def joined_overlay():
    """The five sections joined into one map, as overlay() gives one of them.

    Hexes and sides carry joined ids (see joined.py), each drawn from its
    first copy; each hex is labelled with the section numbers of its copies.
    The client draws each section's own tiles at its place on the joined map.
    """
    j = joined()
    off, grids = j.offsets()
    top = min(o[1] for o in off.values())
    off = {m: (o[0], o[1] - top) for m, o in off.items()}
    hexes = []
    for g, inst in j.hexes.items():
        m, hid = inst[0]
        r, c = parse_id(hid)
        ox, oy = off[m]
        move = lambda p: r1((p[0] + ox, p[1] + oy))  # noqa: E731
        e = j.data[m][hid]
        hexes.append({'id': g, 'label': f'{m}{hid}', 'also': [f'{m2}{h2}' for m2, h2 in inst[1:]],
                      'c': move(grids[m].center(r, c)), 'p': [move(p) for p in grids[m].corners(r, c)],
                      't': e['terrain'], 'u': bool(e.get('uncertain')), 'coastal': bool(e.get('coastal')),
                      'mix': e.get('mix', {})})
    sides = {}
    for gk in j.sides:
        s = j.auto_side_global(gk)
        if s:
            sides[gk] = s
    sections = []
    for k, m in enumerate(SECTIONS):
        w, h = IMAGES[m].size()
        x, y = round(off[m][0]), round(off[m][1])
        # A section's paper starts west of its first column, over hexes that
        # only the section to its west has; it is cut away along their edges
        # so the two grids meet hex to hex.
        cut = []
        if k:
            for hx in hexes:
                if hx['label'][0] == SECTIONS[k - 1] and not hx['also'] and \
                        max(p[0] for p in hx['p']) > x and min(p[0] for p in hx['p']) < x + w:
                    cut.append(hx['p'])
        sections.append({'id': m, 'x': x, 'y': y, 'width': w, 'height': h, 'v': IMAGES[m].version(),
                         'cut': cut})
    corr = all_corrections()
    return {'id': 'ALL', 'width': max(s['x'] + s['width'] for s in sections),
            'height': max(s['y'] + s['height'] for s in sections), 'zmax': IMAGES['A'].zmax(),
            'sections': sections, 'hexes': hexes, 'sides': sides,
            'corrections': j.merged(corr), 'unsynced': unsynced(j, corr)}


def offmap_zones(sections):
    """The printed off-map boxes, outlined in joined map pixels."""
    with open(OFFMAP, encoding='utf-8') as f:
        zones = json.load(f)['zones']
    place = {s['id']: (s['x'], s['y']) for s in sections}
    out = []
    for z in zones:
        x0, y0 = place[z['section']]
        if 'rect' in z:
            x, y, w, h = z['rect']
            poly = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
        else:
            poly = z['poly']
        zone = {k: v for k, v in z.items() if k not in ('rect', 'poly')}
        zone['p'] = [[px + x0, py + y0] for px, py in poly]
        out.append(zone)
    return out


_GAME_MAP = (None, None)
_GAME_MAP_LOCK = threading.Lock()


def game_map():
    """The joined map as the game shows it: corrections applied, off-map boxes added.

    Each hex has its terrain and landmarks; only hexsides with something on
    them are sent. Rebuilt when the map data, grids, corrections or boxes change.
    """
    global _GAME_MAP
    key = _mtimes([f(m) for f in (map_data, map_tiles, map_corrections) for m in MAPS] + [OFFMAP])
    with _GAME_MAP_LOCK:
        if _GAME_MAP[0] == key:
            return _GAME_MAP[1]
        base = joined_overlay()
        corr = base['corrections']
        hexes = []
        for h in base['hexes']:
            e = hex_effective({'terrain': h['t'], 'uncertain': h['u']}, corr['hexes'].get(h['id']))
            hexes.append({'id': h['id'], 'label': h['label'], 'also': h['also'], 'c': h['c'], 'p': h['p'],
                          't': e['terrain'], 'lm': e['landmarks'], 'coastal': h['coastal']})
        sides = {}
        for k in set(base['sides']) | set(corr['sides']):
            s = norm_side(corr['sides'].get(k) or base['sides'].get(k))
            if s['river'] or s['feature'] or s['wadi'] or s['border'] or s['cross']:
                sides[k] = s
        out = {'width': base['width'], 'height': base['height'], 'zmax': base['zmax'],
               'sections': base['sections'], 'hexes': hexes, 'sides': sides,
               'zones': offmap_zones(base['sections'])}
        _GAME_MAP = (key, out)
        return out


def title_image():
    """The joined board at 1/8 scale for the title screen, built once and cached.

    Rebuilt when a scan, or the data or grid that places it, is newer.
    """
    path = CACHE / 'title.jpg'
    newest = max([IMAGES[m].version() for m in SECTIONS]
                 + list(_mtimes([f(m) for f in (map_data, map_tiles) for m in MAPS])))
    if path.exists() and path.stat().st_mtime_ns >= newest:
        return path.read_bytes()
    data = joined_overlay()
    scale = 2 ** (TITLE_ZOOM - data['zmax'])
    board = Image.new('RGB', (math.ceil(data['width'] * scale), math.ceil(data['height'] * scale)), (58, 58, 58))
    for sec in data['sections']:
        im = IMAGES[sec['id']].level(TITLE_ZOOM)
        x, y = round(sec['x'] * scale), round(sec['y'] * scale)
        # As on the joined map: the paper over the western section's last hexes is cut away.
        mask = Image.new('L', im.size, 255)
        draw = ImageDraw.Draw(mask)
        for poly in sec['cut']:
            draw.polygon([(px * scale - x, py * scale - y) for px, py in poly], fill=0)
        board.paste(im, (x, y), mask)
    buf = io.BytesIO()
    board.save(buf, 'JPEG', quality=85)
    body = buf.getvalue()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return body
