"""Local server for the CNA game and its map editor.

Usage (from the project folder):
  python -m cna.server [--port 8765] [--host 127.0.0.1] [--saves FOLDER] [--allow-host NAME]

then open http://127.0.0.1:8765/ for the game (title screen, scenarios, the
board) or http://127.0.0.1:8765/editor.html for the map editor. The browser
side is in web/; this file only routes requests. It listens on localhost
unless --host says otherwise (0.0.0.0: the local network). The map editor
saves only for a browser on this machine: others may look but not change.

  GET  /tiles/<MAP>/<z>/<x>/<y>.jpg   a scan tile (scans.py)
  GET  /api/vocab                     the map's vocabulary (data/vocab.json)
  GET  /api/maps                      the maps the editor can open
  GET  /api/map/<MAP>                 a section's data and corrections; ALL is the joined map
  PUT  /api/corrections/<MAP>         save a map's corrections (copies go to shared hexes); from this machine only
  GET  /api/game/map                  the joined board with corrections applied
  GET  /api/scenarios                 data/scenarios.json, with each setup's units on the map and to place
  GET  /api/rules/<case>              rule text from the local rulebook transcription
  GET  /api/units                     the OA and characteristics charts, by chart (data/units/, data/tables/)
  GET  /title.jpg                    the title screen's board

Games (cna/engine), saved under saves/. A player is known by the token joining
a seat gave them, sent as "Authorization: Bearer <token>":

  GET  /api/sequence                  the steps of the sequence of play: titles and cases
  GET  /api/games                     the saved games
  POST /api/games                     create one: {scenario, games?, sandbox?, initiative?, seat?, name?}
                                      -> {id}, and {seat, token} when a seat is taken too
  POST /api/games/<id>/join           {seat, name} -> {seat, token}
  GET  /api/games/<id>/view           what the token's seat sees
  GET  /api/games/<id>/logsheet/<unit> the TOE Log Sheet of one of the seat's counters (4.52)
  POST /api/games/<id>/commands       {id, type, args} -> {events, seq}, or 422 with the refusal
  POST /api/games/<id>/preview        {type, args} -> {events}, or {dice} if it needs dice, or 422
  GET  /api/games/<id>/stream?token=  server-sent events: 'changed' with the token's seat's event number;
                                      without a token, the number of events anyone may know of

The token goes in the query for the stream only, since EventSource can't send
headers; the request log leaves it out. A POST or PUT with a body must say it
is JSON (Content-Type: application/json), so that another web site can't send
one from the player's browser without the browser asking first. Nor can a web
site that points its own name at this machine (DNS rebinding): the routes
answer only requests whose Host is an IP address, localhost, this machine's
name, or a name given with --allow-host. Errors under /api/ come back as JSON:
{error, case?}.
"""
import argparse
import inspect
import ipaddress
import json
import re
import socket
import threading
import traceback
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import mapdata, rulebook, scans
from .engine import oa, sequence, setup
from .engine.board import board
from .engine.commands import Refused
from .engine.dice import DiceNeeded
from .engine.games import Games, NoGame
from .engine.store import ID, OldSave
from .joined import save_joined, save_section, sync_all
from .paths import SCENARIOS, VOCAB, WEB, map_data

MAX_BODY = 20_000_000
HEARTBEAT = 15  # seconds between the stream's heartbeats, which also find closed connections
MAX_STREAMS = 100  # streams open at once; each holds a thread while it is open
STREAMS = threading.BoundedSemaphore(MAX_STREAMS)
TIMEOUT = 60  # seconds a connection may keep the server waiting for what it sends
GAME_ID = f'({ID.pattern})'
TOKEN_IN_QUERY = re.compile(r'([?&]token=)[^&\s"]*')
GAMES = None  # the open games (engine.games.Games), set by serve()
HOST_NAMES = {'localhost'}  # the names besides IP addresses a request's Host may give; serve() adds more


class HTTPError(Exception):
    def __init__(self, status, message=None, case=None):
        super().__init__(message)
        self.status, self.message, self.case = status, message, case


class Raw:
    """A response body that is not JSON."""

    def __init__(self, body, ctype, cache=False):
        self.body, self.ctype, self.cache = body, ctype, cache


class Stream:
    """A response of server-sent events: an iterator of byte chunks, sent as they come."""

    def __init__(self, chunks):
        self.chunks = chunks


class Request:
    """What a route may need besides the path: the JSON body, the headers, the query, the token."""

    def __init__(self, handler, body):
        self.body = body
        self.headers = handler.headers
        self.query = parse_qs(urlsplit(handler.path).query)
        self.client = handler.client_address[0]

    def arg(self, name, default=None):
        return self.query.get(name, [default])[0]

    @property
    def local(self):
        """Whether the request comes from this machine."""
        try:
            return ipaddress.ip_address(self.client).is_loopback
        except ValueError:
            return False

    @property
    def token(self):
        auth = self.headers.get('Authorization', '')
        return auth[len('Bearer '):].strip() if auth.startswith('Bearer ') else None


def host_allowed(host):
    """Whether a request's Host header names this server: an IP address or one
    of HOST_NAMES. A web site that points its own name at this machine (DNS
    rebinding) sends its own name, and could otherwise use the server from the
    player's browser as if it were this machine. No Host: not a browser."""
    if not host:
        return True
    name = host.strip().lower()
    if name.startswith('['):  # [IPv6]:port
        name = name[1:name.find(']')] if ']' in name else name[1:]
    elif name.count(':') == 1:
        name = name.split(':')[0]
    name = name.rstrip('.')
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        return name in HOST_NAMES


def redact(text):
    """The text with any token in a query left out, for the request log."""
    return TOKEN_IN_QUERY.sub(r'\1…', text)


ROUTES = []  # (method, compiled pattern, handler, whether it takes req); handlers return JSON-able data, Raw or Stream


def route(method, pattern):
    def deco(fn):
        ROUTES.append((method, re.compile(pattern), fn, 'req' in inspect.signature(fn).parameters))
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
def put_corrections(m, req):
    if not req.local:
        raise HTTPError(HTTPStatus.FORBIDDEN, 'The map corrections can be changed only on the machine the server runs on.')
    body = _object(req.body)
    try:
        if m == 'ALL':
            save_joined(body)
        else:
            save_section(m, body)
    except ValueError as exc:  # the data was refused (corrections.check_corrections)
        raise HTTPError(HTTPStatus.BAD_REQUEST, str(exc))
    return {'ok': True}


@route('GET', r'/api/game/map')
def get_game_map():
    return mapdata.game_map()


@route('GET', r'/api/scenarios')
def get_scenarios():
    cat = read_json(SCENARIOS)
    b = board()
    for sid, su in cat['setups'].items():
        # The scenarios of a setup start together; the counts are the first's.
        # A setup no scenario uses yet has none to show.
        start = next((s['start'] for s in cat['scenarios'] if s['setup'] == sid), None)
        if start:
            su['counts'] = setup.counts(su, b, start)
    return {**cat, 'rulebook': rulebook.available()}


@route('GET', r'/api/units')
def get_units():
    return oa.charts().payload()


@route('GET', r'/api/rules/(\d{1,2}\.\d{1,3})')
def get_rule(case):
    text = rulebook.rule_text(case)
    if text is None:
        raise HTTPError(HTTPStatus.NOT_FOUND, f'case {case} is not in the local rulebook transcription')
    return {'case': case, 'text': text}


@route('GET', r'/title\.jpg')
def get_title():
    return Raw(mapdata.title_image(), 'image/jpeg', cache=True)


# ---------- games ----------

def _object(body, *required):
    if not isinstance(body, dict):
        raise HTTPError(HTTPStatus.BAD_REQUEST, 'The request body must be a JSON object.')
    missing = [k for k in required if k not in body]
    if missing:
        raise HTTPError(HTTPStatus.BAD_REQUEST, f'The request lacks {", ".join(missing)}.')
    return body


def _command(body):
    b = _object(body, 'type')
    args = {} if b.get('args') is None else b['args']  # left out or null: none
    if not isinstance(b['type'], str) or not isinstance(args, dict) or not isinstance(b.get('id'), (str, type(None))):
        raise HTTPError(HTTPStatus.BAD_REQUEST, 'A command is {id, type, args}: two strings and an object.')
    return {'id': b.get('id'), 'type': b['type'], 'args': args}


def _game(game_id):
    try:
        return GAMES.get(game_id)
    except NoGame:
        raise HTTPError(HTTPStatus.NOT_FOUND, f'There is no game {game_id}.') from None
    except OldSave as exc:
        raise HTTPError(HTTPStatus.CONFLICT, str(exc)) from None


def _seat(game, token):
    seat = game.seat_of(token)
    if seat is None:
        raise HTTPError(HTTPStatus.UNAUTHORIZED, 'You hold no seat in this game.')
    return seat


def _join(game, seat, name):
    try:
        return {'seat': seat, 'token': game.join(seat, name)}
    except Refused as exc:
        raise HTTPError(HTTPStatus.CONFLICT, exc.message, exc.case) from None


@route('GET', r'/api/sequence')
def get_sequence():
    """Every step of the sequence of play, for naming them."""
    return {'steps': {k: {'title': s['title'], 'case': s['case']} for k, s in sequence.STEPS.items()}}


@route('GET', r'/api/games')
def list_games():
    return {'games': GAMES.list()}


@route('POST', r'/api/games')
def create_game(req):
    b = _object(req.body, 'scenario')
    try:
        game = GAMES.create(b['scenario'], seat=b.get('seat') or None, games=b.get('games'),
                            sandbox=bool(b.get('sandbox')), initiative_choice=b.get('initiative'))
    except ValueError as exc:
        raise HTTPError(HTTPStatus.BAD_REQUEST, str(exc)) from None
    except Refused as exc:  # the seat asked for; no game was saved
        raise HTTPError(HTTPStatus.CONFLICT, exc.message, exc.case) from None
    out = {'id': game.id}
    if b.get('seat'):
        out.update(_join(game, b['seat'], b.get('name')))
    return out


@route('POST', rf'/api/games/{GAME_ID}/join')
def join_game(game_id, req):
    b = _object(req.body, 'seat')
    return _join(_game(game_id), b['seat'], b.get('name'))


@route('GET', rf'/api/games/{GAME_ID}/view')
def get_view(game_id, req):
    game = _game(game_id)
    return game.view(_seat(game, req.token))


@route('GET', rf'/api/games/{GAME_ID}/logsheet/([a-z0-9./-]{{1,80}})')
def get_log_sheet(game_id, uid, req):
    game = _game(game_id)
    try:
        return game.log_sheet(_seat(game, req.token), uid)
    except Refused as exc:
        raise HTTPError(HTTPStatus.NOT_FOUND, exc.message, exc.case) from None


@route('POST', rf'/api/games/{GAME_ID}/commands')
def post_command(game_id, req):
    game = _game(game_id)
    seat = _seat(game, req.token)
    try:
        evs = game.submit(_command(req.body), seat)
    except Refused as exc:
        raise HTTPError(HTTPStatus.UNPROCESSABLE_ENTITY, exc.message, exc.case) from None
    return {'events': game.visible(evs, seat), 'seq': game.seq_for(seat) if evs else None}


@route('POST', rf'/api/games/{GAME_ID}/preview')
def post_preview(game_id, req):
    game = _game(game_id)
    seat = _seat(game, req.token)
    try:
        return {'events': game.preview(_command(req.body), seat)}
    except Refused as exc:
        raise HTTPError(HTTPStatus.UNPROCESSABLE_ENTITY, exc.message, exc.case) from None
    except DiceNeeded as exc:
        return {'events': None, 'dice': str(exc)}


@route('GET', rf'/api/games/{GAME_ID}/stream')
def get_stream(game_id, req):
    """'changed' each time the game has new events that the seat of `?token=`
    may know of, with the seat's event number (Game.seq_for) as its id, so a
    reconnecting EventSource says where it got to. Without a token: the events
    anyone may know of. The seat comes from the token, never from the query
    itself: in the Set-up Stage a side's number counts its secret placements."""
    game = _game(game_id)
    token = req.arg('token')
    seat = None if token is None else _seat(game, token)
    try:
        last = int(req.headers.get('Last-Event-ID') or req.arg('after', '-1'))
    except ValueError:
        last = -1

    def chunks(last):
        yield b'retry: 2000\n\n'
        while True:
            seq = game.wait(last, HEARTBEAT, seat)
            if seq > last:
                last = seq
                yield f'id: {seq}\nevent: changed\ndata: {seq}\n\n'.encode()
            else:
                yield b': heartbeat\n\n'
    return Stream(chunks(last))


# ---------- the handler ----------

class Handler(SimpleHTTPRequestHandler):
    timeout = TIMEOUT

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def log_message(self, fmt, *args):
        if '/tiles/' not in self.path:
            super().log_message(fmt, *(redact(a) if isinstance(a, str) else a for a in args))

    def send_bytes(self, body, ctype, cache=False, status=HTTPStatus.OK):
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'max-age=86400' if cache else 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, obj, status=HTTPStatus.OK):
        self.send_bytes(json.dumps(obj, separators=(',', ':')).encode('utf-8'), 'application/json', status=status)

    def send_stream(self, chunks):
        streams = STREAMS  # released to the one it was taken from
        if not streams.acquire(blocking=False):
            chunks.close()
            self.fail(HTTPStatus.SERVICE_UNAVAILABLE, 'Too many streams are open on this server.')
            return
        try:
            self.send_response(HTTPStatus.OK)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.close_connection = True
            for chunk in chunks:
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError):
            pass  # the browser went away, or stopped reading
        finally:
            chunks.close()
            streams.release()

    def fail(self, status, message=None, case=None):
        if self.path.startswith('/api/'):
            self.send_json({'error': message or HTTPStatus(status).phrase, **({'case': case} if case else {})},
                           status)
        else:
            self.send_error(status, message)

    def read_body(self):
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            raise HTTPError(HTTPStatus.BAD_REQUEST, 'Content-Length is not a number.') from None
        if length < 0:
            raise HTTPError(HTTPStatus.BAD_REQUEST, 'Content-Length is negative.')
        if length > MAX_BODY:
            raise HTTPError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        try:
            raw = self.rfile.read(length)
        except TimeoutError:
            self.close_connection = True
            raise HTTPError(HTTPStatus.REQUEST_TIMEOUT, 'The request body did not come in time.') from None
        if not raw:
            return None
        if self.headers.get_content_type() != 'application/json':
            raise HTTPError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, 'The request body must be sent as application/json.')
        try:
            return json.loads(raw)
        except ValueError as exc:
            raise HTTPError(HTTPStatus.BAD_REQUEST, f'not JSON: {exc}')

    def dispatch(self, method):
        """Run the matching route; False if none matches."""
        path = self.path.split('?', 1)[0]
        for meth, pattern, fn, wants_req in ROUTES:
            m = pattern.fullmatch(path)
            if not m or meth != method:
                continue
            try:
                if not host_allowed(self.headers.get('Host')):
                    raise HTTPError(HTTPStatus.FORBIDDEN, f'This server does not answer to the name in the request '
                                    f'({self.headers.get("Host")}); start it with --allow-host to add one.')
                body = self.read_body() if method in ('PUT', 'POST') else None
                out = fn(*m.groups(), **({'req': Request(self, body)} if wants_req else {}))
            except HTTPError as exc:
                self.fail(exc.status, exc.message, exc.case)
            except Exception as exc:  # noqa: BLE001 - report it rather than drop the connection
                traceback.print_exc()
                self.fail(HTTPStatus.INTERNAL_SERVER_ERROR, f'{type(exc).__name__}: {exc}')
            else:
                if isinstance(out, Raw):
                    self.send_bytes(out.body, out.ctype, out.cache)
                elif isinstance(out, Stream):
                    self.send_stream(out.chunks)
                else:
                    self.send_json(out)
            return True
        return False

    def do_GET(self):
        if self.dispatch('GET'):
            return
        if self.path.startswith('/api/'):
            self.fail(HTTPStatus.NOT_FOUND)
            return
        if self.path.split('?', 1)[0] == '/':
            self.path = '/index.html'
        self.static = True
        super().do_GET()

    def do_PUT(self):
        if not self.dispatch('PUT'):
            self.fail(HTTPStatus.NOT_FOUND)

    def do_POST(self):
        if not self.dispatch('POST'):
            self.fail(HTTPStatus.NOT_FOUND)

    def end_headers(self):
        # The web files change as they are worked on; have the browser check them.
        if getattr(self, 'static', False):
            self.send_header('Cache-Control', 'no-cache')
        super().end_headers()


Handler.extensions_map = {**SimpleHTTPRequestHandler.extensions_map, '.js': 'text/javascript',
                          '.mjs': 'text/javascript', '.json': 'application/json'}


def serve(host='127.0.0.1', port=8765, games=None, allow_hosts=()):
    """The server, ready to serve_forever(); games: where the games are kept (default saves/).
    allow_hosts: names of this machine requests may give besides those it knows (HOST_NAMES)."""
    global GAMES
    GAMES = games or Games()
    me = socket.gethostname().lower()
    HOST_NAMES.update({me, f'{me}.local', *(n.lower().rstrip('.') for n in (host, *allow_hosts) if n)})
    return ThreadingHTTPServer((host, port), Handler)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--port', type=int, default=8765)
    ap.add_argument('--host', default='127.0.0.1',
                    help='the address to listen on; 0.0.0.0 opens the server to the local network')
    ap.add_argument('--saves', help='the folder of saved games (default: saves/ in the project folder)')
    ap.add_argument('--allow-host', action='append', default=[], metavar='NAME',
                    help='another name this machine is reached by (besides IP addresses, localhost and its '
                         'own name); may be given more than once')
    a = ap.parse_args()
    changed, _ = sync_all()
    if changed:
        print(f'synchronized {changed} corrections of hexes and hexsides shared by two sections', flush=True)
    srv = serve(a.host, a.port, Games(Path(a.saves)) if a.saves else None, a.allow_host)
    threading.Thread(target=scans.warm_all, daemon=True).start()
    if a.host not in ('127.0.0.1', 'localhost', '::1'):
        print(f'Listening on {a.host}: other machines can reach this server. Player tokens keep players in '
              'their own seats, but they are not security. The map editor saves only from this machine.', flush=True)
    print(f'CNA game: http://127.0.0.1:{a.port}/   map editor: http://127.0.0.1:{a.port}/editor.html'
          '  (Ctrl+C to stop)', flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
