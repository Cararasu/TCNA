"""Local review server for the extracted CNA map data.

Usage:
  python tools/review/server.py [--port 8765]

then open http://127.0.0.1:8765/ in a browser.

Serves the scanned map sections as image tiles (rendered from the rulebook
PDF on first use and cached under .cache/review/) and the extracted map data
(data/map/<MAP>.json with its fitted grid data/map/tiles<MAP>.json) as an
overlay with all geometry in map pixels. Edits made in the browser are saved
to data/map/corrections/<MAP>.json, which holds only the hexes and hexsides
changed by hand, so the automatic data can be regenerated without losing
them. Only listens on localhost.
"""
import argparse
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
from hexgrid import TiledGrid, parse_id  # noqa: E402

Image.MAX_IMAGE_PIXELS = None

PDF = ROOT / 'The Campaign for North Africa_text.pdf'
PAGES = {'A': 188, 'B': 189, 'C': 190, 'D': 191, 'E': 192}  # PDF page per map section
# The text PDF stores Map A's colour layer at only ~100 dpi; the Internet
# Archive's single-page images of the same scan are full 300 dpi, so Map A is
# taken from there instead (page images are numbered from 0).
ARCHIVE_PAGE = ('https://archive.org/download/campaign-for-north-africa/'
                'The%20Campaign%20for%20North%20Africa_jp2.zip/'
                'The%20Campaign%20for%20North%20Africa_jp2%2FThe%20Campaign%20for%20North%20Africa_{n:04d}.jp2'
                '?ext=jpg')
FROM_ARCHIVE = {'A'}
DATA = ROOT / 'data' / 'map'
CACHE = ROOT / '.cache' / 'review'
STATIC = Path(__file__).resolve().parent / 'static'
TILE = 256


class MapImage:
    """One map section's scan: lazily rendered, loaded and tiled."""

    def __init__(self, map_id):
        self.id = map_id
        self.path = CACHE / 'maps' / f'map{map_id}.png'
        self.lock = threading.Lock()
        self.levels = {}  # zoom -> PIL image at that zoom's scale
        self._size = None

    def ensure_rendered(self):
        if self.path.exists():
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.id in FROM_ARCHIVE:
            url = ARCHIVE_PAGE.format(n=PAGES[self.id] - 1)
            print(f'downloading map {self.id} from the Internet Archive (once)...', flush=True)
            tmp = self.path.with_suffix('.download')
            urllib.request.urlretrieve(url, tmp)
            Image.open(tmp).convert('RGB').save(self.path)
            tmp.unlink()
            return
        print(f'rendering map {self.id} from the PDF (takes a few minutes, once)...', flush=True)
        subprocess.run(['pdftoppm', '-r', '300', '-f', str(PAGES[self.id]), '-l', str(PAGES[self.id]),
                        '-png', '-singlefile', str(PDF), str(self.path.with_suffix(''))], check=True)

    def size(self):
        if self._size is None:
            self.ensure_rendered()
            with Image.open(self.path) as im:
                self._size = im.size
        return self._size

    def zmax(self):
        w, h = self.size()
        return math.ceil(math.log2(max(w, h) / TILE))

    def level(self, z):
        """The scan at zoom z: full resolution at zmax, halved per level below."""
        with self.lock:
            return self._level(z)

    def _level(self, z):
        if z not in self.levels:
            if z == self.zmax():
                im = Image.open(self.path).convert('RGB')
                im.load()
            else:
                im = self._level(z + 1).reduce(2)
            self.levels[z] = im
        return self.levels[z]

    def tile(self, z, x, y):
        out = CACHE / 'tiles' / self.id / str(z) / f'{x}_{y}.jpg'
        if out.exists():
            return out.read_bytes()
        im = self.level(z)
        x0, y0 = x * TILE, y * TILE
        if x0 >= im.width or y0 >= im.height or x < 0 or y < 0:
            return None
        crop = im.crop((x0, y0, min(x0 + TILE, im.width), min(y0 + TILE, im.height)))
        canvas = Image.new('RGB', (TILE, TILE), (230, 230, 230))
        canvas.paste(crop, (0, 0))
        out.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(out, 'JPEG', quality=88)
        return out.read_bytes()


IMAGES = {m: MapImage(m) for m in PAGES}


def r1(p):
    return [round(float(p[0]), 1), round(float(p[1]), 1)]


CORRECTIONS = DATA / 'corrections'
SAVE_LOCK = threading.Lock()


def load_corrections(map_id):
    path = CORRECTIONS / f'{map_id}.json'
    if not path.exists():
        return {'hexes': {}, 'sides': {}}
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def save_corrections(map_id, obj):
    """Write a map's corrections atomically (temp file, then rename)."""
    if not (isinstance(obj, dict) and isinstance(obj.get('hexes'), dict) and isinstance(obj.get('sides'), dict)):
        raise ValueError('corrections must be {"hexes": {...}, "sides": {...}}')
    for key in obj['hexes']:
        if not re.fullmatch(r'\d{4}', key):
            raise ValueError(f'bad hex id {key!r}')
    for key in obj['sides']:
        if not re.fullmatch(r'\d{4}\|(E|NE|NW)', key):
            raise ValueError(f'bad side key {key!r}')
    CORRECTIONS.mkdir(parents=True, exist_ok=True)
    path = CORRECTIONS / f'{map_id}.json'
    tmp = path.with_suffix('.json.tmp')
    out = {'hexes': dict(sorted(obj['hexes'].items())), 'sides': dict(sorted(obj['sides'].items()))}
    with SAVE_LOCK:
        with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(out, f, indent=1, ensure_ascii=False)
            f.write('\n')
        os.replace(tmp, path)


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
            # A side is a river or a wadi, not both; blue water decides for the river.
            side = {'river': s.get('river'), 'wadi': bool(s.get('wadi')) and not s.get('river'),
                    'border': bool(s.get('border')),
                    'cross': [{'k': x['kind'], 't': x['t']} for x in s['crossings']]}
            if s.get('feature'):
                side['feature'] = s['feature']
            sides[f'{hid}|{d}'] = side
    w, h = IMAGES[map_id].size()
    return {'id': map_id, 'width': w, 'height': h, 'zmax': IMAGES[map_id].zmax(),
            'hexes': hexes, 'sides': sides, 'corrections': load_corrections(map_id)}


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
            for mid in PAGES:
                has_data = (DATA / f'{mid}.json').exists() and (DATA / f'tiles{mid}.json').exists()
                maps.append({'id': mid, 'hasData': has_data})
            self.send_json(maps)
            return
        m = re.fullmatch(r'/api/map/([A-E])', path)
        if m:
            mid = m.group(1)
            if not (DATA / f'{mid}.json').exists():
                self.send_error(HTTPStatus.NOT_FOUND, f'no extracted data for map {mid}')
                return
            self.send_json(overlay(mid))
            return
        if path == '/':
            self.path = '/index.html'
        super().do_GET()

    def do_PUT(self):
        m = re.fullmatch(r'/api/corrections/([A-E])', self.path.split('?', 1)[0])
        if not m:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        length = int(self.headers.get('Content-Length', 0))
        if length > 20_000_000:
            self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        try:
            save_corrections(m.group(1), json.loads(self.rfile.read(length)))
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        self.send_json({'ok': True})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8765)
    a = ap.parse_args()
    srv = ThreadingHTTPServer(('127.0.0.1', a.port), Handler)
    print(f'CNA map review: http://127.0.0.1:{a.port}/  (Ctrl+C to stop)', flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
