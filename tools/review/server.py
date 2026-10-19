"""Local review server for the extracted CNA map data.

Usage:
  python tools/review/server.py [--port 8765]

then open http://127.0.0.1:8765/ in a browser.

Serves the scanned map sections as image tiles (extracted from the rulebook
scan on first use and cached under .cache/review/) and the extracted map data
(data/map/<MAP>.json with its fitted grid data/map/tiles<MAP>.json) as an
overlay with all geometry in map pixels. Edits made in the browser are saved
to data/map/corrections/<MAP>.json, which holds only the hexes and hexsides
changed by hand, so the automatic data can be regenerated without losing
them. Map ALL is the five sections joined (see joined.py); a hex or hexside
on two sections is kept the same on both, whichever map it is edited on.
Only listens on localhost.
"""
import argparse
import io
import json
import math
import os
import re
import subprocess
import sys
import threading
import urllib.request
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'map'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from hexgrid import TiledGrid, parse_id  # noqa: E402
from joined import (MALTA, MAPS, SECTIONS, all_corrections, auto_side, joined,  # noqa: E402
                    load_corrections, save_joined, save_section, unsynced)

Image.MAX_IMAGE_PIXELS = None

# The scans come from the Internet Archive's original upload of the rulebook,
# which holds each map section as a full 300 dpi JPEG stored landscape. The
# text PDF next to it recompresses them (Map A's colour layer to ~100 dpi).
# The grids were fitted on renders of the text PDF, which line up with the
# originals to within a pixel once rotated, but are up to a pixel larger; the
# originals' last row and column are repeated to make up the difference.
ORIGINAL_PDF = ('https://archive.org/download/campaign-for-north-africa/'
                'The%20Campaign%20for%20North%20Africa.pdf')
SCANS = {  # map -> (PDF page, rotation to upright, size the grid was fitted on)
    'A': (188, Image.ROTATE_90, (6669, 10595)),
    'B': (189, Image.ROTATE_270, (6682, 10596)),
    'C': (190, Image.ROTATE_90, (6687, 10586)),
    'D': (191, Image.ROTATE_90, (6689, 10586)),
    'E': (192, Image.ROTATE_270, (6693, 10586)),
}
FETCH_LOCK = threading.Lock()
# A full scan takes ~200 MB decoded and seconds to decode, so one is decoded
# at a time, the reduced levels are cached as files, and only the most
# recently used scans keep their two largest levels loaded.
MAX_LOADED = 2
LOADED = []  # MapImages holding their large levels, least recently used first
LOADED_LOCK = threading.Lock()
DECODE_LOCK = threading.Lock()
DATA = ROOT / 'data' / 'map'
CACHE = ROOT / '.cache' / 'review'
STATIC = Path(__file__).resolve().parent / 'static'
TILE = 256


def fetch_scans():
    """Download the original PDF once and extract every scan not yet cached."""
    with FETCH_LOCK:
        missing = [m for m in SCANS if not IMAGES[m].path.exists()]
        if not missing:
            return
        maps = CACHE / 'maps'
        maps.mkdir(parents=True, exist_ok=True)
        print('downloading the map scans from the Internet Archive (134 MB, once)...', flush=True)
        tmp = maps / 'original.pdf.download'
        urllib.request.urlretrieve(ORIGINAL_PDF, tmp)
        for m in missing:
            page, rotation, size = SCANS[m]
            prefix = maps / f'page{m}'
            subprocess.run(['pdfimages', '-j', '-f', str(page), '-l', str(page), str(tmp), str(prefix)],
                           check=True)
            src = Path(f'{prefix}-000.jpg')
            im = Image.open(src).convert('RGB').transpose(rotation)
            full = Image.new('RGB', size)
            full.paste(im, (0, 0))
            for x in range(im.width, size[0]):
                full.paste(full.crop((im.width - 1, 0, im.width, size[1])), (x, 0))
            for y in range(im.height, size[1]):
                full.paste(full.crop((0, im.height - 1, size[0], im.height)), (0, y))
            full.save(IMAGES[m].path)
            src.unlink()
        tmp.unlink()


class MapImage:
    """One map section's scan: lazily extracted, loaded and tiled."""

    def __init__(self, map_id):
        self.id = map_id
        self.path = CACHE / 'maps' / f'map{map_id}.png'
        self.lock = threading.Lock()
        self.levels = {}  # zoom -> PIL image at that zoom's scale
        self._size = None

    def size(self):
        if self._size is None:
            if not self.path.exists():
                fetch_scans()
            with Image.open(self.path) as im:
                self._size = im.size
            self._version = self.path.stat().st_mtime_ns
        return self._size

    def zmax(self):
        w, h = self.size()
        return math.ceil(math.log2(max(w, h) / TILE))

    def level(self, z):
        """The scan at zoom z: full resolution at zmax, halved per level below."""
        with self.lock:
            im = self._level(z)
        if z >= self.zmax() - 1:
            with LOADED_LOCK:
                if self in LOADED:
                    LOADED.remove(self)
                LOADED.append(self)
                while len(LOADED) > MAX_LOADED:
                    old = LOADED.pop(0)
                    old.levels = {k: v for k, v in old.levels.items() if k < old.zmax() - 1}
        return im

    def version(self):
        """Changes whenever the cached scan is replaced; keys the tile cache."""
        self.size()
        return self._version

    def level_path(self, z):
        return self.path.with_name(f'{self.path.stem}.z{z}.png')

    def _level(self, z):
        if z not in self.levels:
            path = self.level_path(z)
            if z == self.zmax():
                with DECODE_LOCK:
                    im = Image.open(self.path).convert('RGB')
                    im.load()
            elif path.exists() and path.stat().st_mtime_ns >= self.version():
                im = Image.open(path).convert('RGB')
                im.load()
            else:
                im = self._level(z + 1).reduce(2)
                im.save(path, compress_level=1)
            self.levels[z] = im
        return self.levels[z]

    def warm(self):
        """Cache every reduced level as a file, so no zoom needs the full scan."""
        if not self.level_path(0).exists() or self.level_path(0).stat().st_mtime_ns < self.version():
            print(f'building zoom levels for map {self.id} (once)...', flush=True)
            for z in range(self.zmax() - 1, -1, -1):
                self.level(z)
            self.levels = {k: v for k, v in self.levels.items() if k < self.zmax() - 1}

    def tile(self, z, x, y):
        out = CACHE / 'tiles' / self.id / str(self.version()) / str(z) / f'{x}_{y}.jpg'
        if out.exists():
            return out.read_bytes()
        im = self.level(z)
        x0, y0 = x * TILE, y * TILE
        if x0 >= im.width or y0 >= im.height or x < 0 or y < 0:
            return None
        crop = im.crop((x0, y0, min(x0 + TILE, im.width), min(y0 + TILE, im.height)))
        canvas = Image.new('RGB', (TILE, TILE), (230, 230, 230))
        canvas.paste(crop, (0, 0))
        buf = io.BytesIO()
        canvas.save(buf, 'JPEG', quality=88)
        body = buf.getvalue()
        # Neighbouring tiles of the joined map ask for the same tile at once.
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(f'{out.stem}.{threading.get_ident()}.tmp')
        try:
            tmp.write_bytes(body)
            os.replace(tmp, out)
        except OSError:
            tmp.unlink(missing_ok=True)
        return body


IMAGES = {m: MapImage(m) for m in SCANS}
IMAGES[MALTA] = IMAGES['A']  # the Malta inset is printed on Map A's sheet


def r1(p):
    return [round(float(p[0]), 1), round(float(p[1]), 1)]


def overlay(map_id):
    """One map's automatic data, hex geometry in map pixels, and its corrections.

    Hex corners run counter-clockwise from east-south-east, so side E is
    corners 0-1, NE 1-2, NW 2-3, W 3-4, SW 4-5, SE 5-0. Sides are keyed by
    the hex that owns them (its E, NE or NW side), as in the extracted data.
    """
    grid = TiledGrid.load(DATA / f'tiles{map_id}.json')
    with open(DATA / f'{map_id}.json', encoding='utf-8') as f:
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


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, fmt, *args):
        if '/tiles/' not in self.path:
            super().log_message(fmt, *args)

    def send_bytes(self, body, ctype, cache=False):
        self.send_response(HTTPStatus.OK)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'max-age=86400' if cache else 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, obj):
        self.send_bytes(json.dumps(obj, separators=(',', ':')).encode('utf-8'), 'application/json')

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        m = re.fullmatch(r'/tiles/([A-E])/(\d+)/(-?\d+)/(-?\d+)\.jpg', path)
        if m:
            body = IMAGES[m.group(1)].tile(int(m.group(2)), int(m.group(3)), int(m.group(4)))
            if body is None:
                self.send_error(HTTPStatus.NOT_FOUND)
            else:
                self.send_bytes(body, 'image/jpeg', cache=True)
            return
        if path == '/api/maps':
            maps = []
            for mid in MAPS:
                has_data = (DATA / f'{mid}.json').exists() and (DATA / f'tiles{mid}.json').exists()
                maps.append({'id': mid, 'hasData': has_data})
            maps.append({'id': 'ALL', 'hasData': all(m['hasData'] for m in maps)})
            self.send_json(maps)
            return
        if path == '/api/map/ALL':
            self.send_json(joined_overlay())
            return
        m = re.fullmatch(r'/api/map/([A-EM])', path)
        if m:
            mid = m.group(1)
            if not (DATA / f'{mid}.json').exists():
                self.send_error(HTTPStatus.NOT_FOUND, f'no extracted data for map {mid}')
                return
            self.send_json(overlay(mid))
            return
        if path == '/':
            self.path = '/index.html'
        self.static = True
        super().do_GET()

    def end_headers(self):
        # The editor's own files change with it; have the browser check them.
        if getattr(self, 'static', False):
            self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

    def do_PUT(self):
        m = re.fullmatch(r'/api/corrections/([A-EM]|ALL)', self.path.split('?', 1)[0])
        if not m:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        length = int(self.headers.get('Content-Length', 0))
        if length > 20_000_000:
            self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        try:
            obj = json.loads(self.rfile.read(length))
            if m.group(1) == 'ALL':
                save_joined(obj)
            else:
                save_section(m.group(1), obj)
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        self.send_json({'ok': True})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8765)
    a = ap.parse_args()
    srv = ThreadingHTTPServer(('127.0.0.1', a.port), Handler)
    threading.Thread(target=lambda: [IMAGES[m].warm() for m in SCANS], daemon=True).start()
    print(f'CNA map review: http://127.0.0.1:{a.port}/  (Ctrl+C to stop)', flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
