"""Local server for the CNA game and its map editor.

Usage (from the project folder):
  python -m cna.server [--port 8765]

then open http://127.0.0.1:8765/ for the game (title screen, scenarios, the
board) or http://127.0.0.1:8765/editor.html for the map editor. The browser
side is in web/; this file only routes requests. Only listens on localhost.

  GET /tiles/<MAP>/<z>/<x>/<y>.jpg   a scan tile (scans.py)
  GET /api/vocab                     the map's vocabulary (data/vocab.json)
  GET /api/maps                      the maps the editor can open
  GET /api/map/<MAP>                 a section's data and corrections; ALL is the joined map
  PUT /api/corrections/<MAP>         save a map's corrections (copies go to shared hexes)
  GET /api/game/map                  the joined board with corrections applied
  GET /api/scenarios                 data/scenarios.json
  GET /api/rules/<case>              rule text from the local rulebook transcription
  GET /title.jpg                     the title screen's board
"""
import argparse
import json
import re
import threading
import traceback
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from . import mapdata, rulebook, scans
from .joined import save_joined, save_section, sync_all
from .paths import SCENARIOS, VOCAB, WEB, map_data

MAX_BODY = 20_000_000


class HTTPError(Exception):
    def __init__(self, status, message=None):
        super().__init__(message)
        self.status, self.message = status, message


class Raw:
    """A response body that is not JSON."""

    def __init__(self, body, ctype, cache=False):
        self.body, self.ctype, self.cache = body, ctype, cache


ROUTES = []  # (method, compiled pattern, handler); handlers return JSON-able data or Raw


def route(method, pattern):
    def deco(fn):
        ROUTES.append((method, re.compile(pattern), fn))
        return fn
    return deco


def read_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


@route('GET', r'/tiles/([A-E])/(\d+)/(-?\d+)/(-?\d+)\.jpg')
def get_tile(m, z, x, y):
    body = scans.IMAGES[m].tile(int(z), int(x), int(y))
    if body is None:
        raise HTTPError(HTTPStatus.NOT_FOUND)
    return Raw(body, 'image/jpeg', cache=True)


@route('GET', r'/api/vocab')
def get_vocab():
    return read_json(VOCAB)


@route('GET', r'/api/maps')
def get_maps():
    return mapdata.maps_list()


@route('GET', r'/api/map/ALL')
def get_joined():
    return mapdata.joined_overlay()


@route('GET', r'/api/map/([A-EM])')
def get_map(m):
    if not map_data(m).exists():
        raise HTTPError(HTTPStatus.NOT_FOUND, f'no extracted data for map {m}')
    return mapdata.overlay(m)


@route('PUT', r'/api/corrections/([A-EM]|ALL)')
def put_corrections(m, body):
    if m == 'ALL':
        save_joined(body)
    else:
        save_section(m, body)
    return {'ok': True}


@route('GET', r'/api/game/map')
def get_game_map():
    return mapdata.game_map()


@route('GET', r'/api/scenarios')
def get_scenarios():
    return {**read_json(SCENARIOS), 'rulebook': rulebook.available()}


@route('GET', r'/api/rules/(\d{1,2}\.\d{1,3})')
def get_rule(case):
    text = rulebook.rule_text(case)
    if text is None:
        raise HTTPError(HTTPStatus.NOT_FOUND, f'case {case} is not in the local rulebook transcription')
    return {'case': case, 'text': text}


@route('GET', r'/title\.jpg')
def get_title():
    return Raw(mapdata.title_image(), 'image/jpeg', cache=True)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

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

    def dispatch(self, method):
        """Run the matching route; False if none matches."""
        path = self.path.split('?', 1)[0]
        for meth, pattern, fn in ROUTES:
            m = pattern.fullmatch(path)
            if not m or meth != method:
                continue
            try:
                args = list(m.groups())
                if method == 'PUT':
                    length = int(self.headers.get('Content-Length', 0))
                    if length > MAX_BODY:
                        raise HTTPError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                    try:
                        body = json.loads(self.rfile.read(length))
                    except ValueError as exc:
                        raise HTTPError(HTTPStatus.BAD_REQUEST, f'not JSON: {exc}')
                    try:
                        out = fn(*args, body)
                    except ValueError as exc:  # the data was refused (corrections.check_corrections)
                        raise HTTPError(HTTPStatus.BAD_REQUEST, str(exc))
                else:
                    out = fn(*args)
            except HTTPError as exc:
                self.send_error(exc.status, exc.message)
            except Exception as exc:  # noqa: BLE001 - report it rather than drop the connection
                traceback.print_exc()
                self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, f'{type(exc).__name__}: {exc}')
            else:
                if isinstance(out, Raw):
                    self.send_bytes(out.body, out.ctype, out.cache)
                else:
                    self.send_bytes(json.dumps(out, separators=(',', ':')).encode('utf-8'), 'application/json')
            return True
        return False

    def do_GET(self):
        if self.dispatch('GET'):
            return
        if self.path.split('?', 1)[0] == '/':
            self.path = '/index.html'
        self.static = True
        super().do_GET()

    def do_PUT(self):
        if not self.dispatch('PUT'):
            self.send_error(HTTPStatus.NOT_FOUND)

    def end_headers(self):
        # The web files change as they are worked on; have the browser check them.
        if getattr(self, 'static', False):
            self.send_header('Cache-Control', 'no-cache')
        super().end_headers()


Handler.extensions_map = {**SimpleHTTPRequestHandler.extensions_map, '.js': 'text/javascript',
                          '.mjs': 'text/javascript', '.json': 'application/json'}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--port', type=int, default=8765)
    a = ap.parse_args()
    changed, _ = sync_all()
    if changed:
        print(f'synchronized {changed} corrections of hexes and hexsides shared by two sections', flush=True)
    srv = ThreadingHTTPServer(('127.0.0.1', a.port), Handler)
    threading.Thread(target=scans.warm_all, daemon=True).start()
    print(f'CNA game: http://127.0.0.1:{a.port}/   map editor: http://127.0.0.1:{a.port}/editor.html'
          '  (Ctrl+C to stop)', flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
