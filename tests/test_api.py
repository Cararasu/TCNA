"""The game API on a real server (cna/server.py): routes, tokens and the stream."""
import contextlib
import copy
import http.client
import io
import json
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from cna import server
from cna.engine.games import Games


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        server.HEARTBEAT = 0.2
        cls.log_message = server.Handler.log_message
        server.Handler.log_message = lambda *args: None
        cls.srv = server.serve('127.0.0.1', 0, Games(Path(cls.tmp.name)))
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        server.Handler.log_message = cls.log_message
        cls.tmp.cleanup()

    def call(self, method, path, body=None, token=None, content_type='application/json', host=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        headers = {'Content-Type': content_type, **({'Host': host} if host else {})}
        if token:
            headers['Authorization'] = f'Bearer {token}'
        conn.request(method, path, json.dumps(body) if body is not None else None, headers)
        res = conn.getresponse()
        data = json.loads(res.read() or 'null')
        conn.close()
        return res.status, data

    def new_game(self):
        status, made = self.call('POST', '/api/games', {'scenario': 'graziani', 'seat': 'axis', 'name': 'Thomas'})
        self.assertEqual(status, 200, made)
        status, joined = self.call('POST', f'/api/games/{made["id"]}/join', {'seat': 'cw', 'name': 'Ann'})
        self.assertEqual(status, 200, joined)
        return made['id'], made['token'], joined['token']

    def pooled(self, view, side):
        return next(u for u in view['units'].values() if u['side'] == side and u['loc'] and u['loc']['kind'] == 'pool')

    def a_hex(self, view):
        return next(u['loc'] for u in view['units'].values() if u['loc'] and u['loc']['kind'] == 'hex')

    def stream(self, gid, query=''):
        """Opens the game's stream; returns the connection and a function
        giving the next event number it tells of."""
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        conn.request('GET', f'/api/games/{gid}/stream{query}')
        res = conn.getresponse()
        self.assertEqual(res.getheader('Content-Type'), 'text/event-stream')
        got = queue.Queue()

        def read():
            try:
                for line in res:
                    got.put(line.decode().rstrip('\n'))
            except OSError:
                pass
        threading.Thread(target=read, daemon=True).start()

        def next_changed():
            while True:
                line = got.get(timeout=5)
                if line.startswith('data: '):
                    return int(line[len('data: '):])
        return conn, next_changed

    def test_create_join_view_and_command(self):
        gid, axis, cw = self.new_game()
        status, v = self.call('GET', f'/api/games/{gid}/view', token=axis)
        self.assertEqual((status, v['seat'], v['now']['step']), (200, 'axis', 'setup'))
        unit = self.pooled(v, 'axis')
        cmd = {'id': 'c1', 'type': 'place-unit', 'args': {'unit': unit['id'], 'loc': self.a_hex(v)}}
        status, preview = self.call('POST', f'/api/games/{gid}/preview', cmd, axis)
        self.assertEqual((status, preview['events'][0]['type']), (200, 'unit-placed'))
        status, done = self.call('POST', f'/api/games/{gid}/commands', cmd, axis)
        self.assertEqual((status, done['events'][0]['type']), (200, 'unit-placed'))
        status, again = self.call('POST', f'/api/games/{gid}/commands', cmd, axis)
        self.assertEqual(again, done)  # sent twice, run once
        status, listed = self.call('GET', '/api/games')
        meta = next(m for m in listed['games'] if m['id'] == gid)
        self.assertEqual(meta['seats']['cw'], {'name': 'Ann'})

    def test_refusals_and_errors(self):
        gid, axis, cw = self.new_game()
        _, v = self.call('GET', f'/api/games/{gid}/view', token=axis)
        cmd = {'type': 'place-unit', 'args': {'unit': self.pooled(v, 'axis')['id'], 'loc': self.a_hex(v)}}
        status, err = self.call('POST', f'/api/games/{gid}/commands', cmd, cw)
        self.assertEqual(status, 422)
        self.assertIn('error', err)
        status, err = self.call('POST', f'/api/games/{gid}/commands', {'type': 'end-step'}, 'not-a-token')
        self.assertEqual(status, 401)
        self.assertEqual(self.call('GET', f'/api/games/{gid}/view')[0], 401)
        self.assertEqual(self.call('GET', '/api/games/no-such-game/view', token=axis)[0], 404)
        self.assertEqual(self.call('POST', f'/api/games/{gid}/join', {'seat': 'cw'})[0], 409)
        self.assertEqual(self.call('POST', '/api/games', {'scenario': 'atlantis'})[0], 400)
        self.assertEqual(self.call('POST', f'/api/games/{gid}/commands', {'args': {}}, axis)[0], 400)
        self.assertEqual(self.call('POST', f'/api/games/{gid}/commands', [1, 2], axis)[0], 400)
        status, err = self.call('POST', f'/api/games/{gid}/commands',
                                {'type': 'join', 'args': {'seat': 'referee', 'name': 'x', 'key': 'k'}}, axis)
        self.assertEqual(status, 422)
        self.assertEqual(self.call('POST', f'/api/games/{gid}/join', {'seat': 'referee'})[0], 409)
        bad_loc = {'type': 'place-unit', 'args': {'unit': self.pooled(v, 'axis')['id'], 'loc': {'kind': 'hex', 'id': [1]}}}
        self.assertEqual(self.call('POST', f'/api/games/{gid}/commands', bad_loc, axis)[0], 422)
        self.assertEqual(self.call('POST', '/api/games', {'scenario': 'graziani', 'games': ['air']})[0], 400)
        status, err = self.call('POST', f'/api/games/{gid}/preview', {'type': 'undo', 'args': None}, axis)
        self.assertEqual((status, err['error']), (422, 'There is nothing to take back in this step.'))

    def test_a_bad_content_length(self):
        for length in ('ten', '-1'):
            conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
            conn.putrequest('POST', '/api/games')
            conn.putheader('Content-Length', length)
            conn.endheaders()
            res = conn.getresponse()
            self.assertEqual(res.status, 400, length)
            conn.close()

    def test_a_seat_that_cannot_be_taken_saves_no_game(self):
        before = self.call('GET', '/api/games')[1]['games']
        status, err = self.call('POST', '/api/games', {'scenario': 'graziani', 'seat': 'axsi'})
        self.assertEqual(status, 409, err)
        self.assertEqual(self.call('GET', '/api/games')[1]['games'], before)

    def test_a_command_shows_up_in_the_other_player_s_stream(self):
        gid, axis, cw = self.new_game()
        self.assertEqual(self.call('GET', f'/api/games/{gid}/stream?token=not-a-token')[0], 401)
        conn, next_changed = self.stream(gid, f'?token={cw}')
        first = next_changed()  # where the game is now, as the Commonwealth may know it
        _, v = self.call('GET', f'/api/games/{gid}/view', token=axis)
        pooled = [u['id'] for u in v['units'].values() if u['side'] == 'axis' and u['loc'] and u['loc']['kind'] == 'pool']
        place = {'id': 's1', 'type': 'place-unit', 'args': {'units': pooled, 'loc': self.a_hex(v)}}
        self.assertEqual(self.call('POST', f'/api/games/{gid}/commands', place, axis)[0], 200)
        # The placement is secret, so the stream stays quiet; ending the set-up is not.
        _, done = self.call('POST', f'/api/games/{gid}/commands', {'id': 's2', 'type': 'end-step'}, axis)
        self.assertEqual(next_changed(), first + 1)
        self.assertEqual(self.call('GET', f'/api/games/{gid}/view', token=cw)[1]['seq'], first + 1)
        self.assertEqual(done['seq'], first + 2)  # the Axis player's own count holds the placement
        conn.close()

    def test_the_stream_does_not_tell_of_the_other_side_s_set_up(self):
        """The seat comes from the token: naming a seat in the query, as the
        stream once took it, only gets the number anyone may know of."""
        gid, axis, cw = self.new_game()
        _, v = self.call('GET', f'/api/games/{gid}/view', token=axis)
        pooled = [u['id'] for u in v['units'].values() if u['side'] == 'axis' and u['loc'] and u['loc']['kind'] == 'pool']
        for i, unit in enumerate(pooled[:3]):
            cmd = {'id': f'p{i}', 'type': 'place-unit', 'args': {'unit': unit, 'loc': self.a_hex(v)}}
            self.assertEqual(self.call('POST', f'/api/games/{gid}/commands', cmd, axis)[0], 200)
        public = self.call('GET', f'/api/games/{gid}/view', token=cw)[1]['seq']
        own = self.call('GET', f'/api/games/{gid}/view', token=axis)[1]['seq']
        self.assertEqual(own, public + 3)
        for query, want in (('', public), ('?seat=axis', public), ('?seat=referee', public),
                            (f'?token={cw}', public), (f'?token={axis}', own)):
            conn, next_changed = self.stream(gid, query)
            self.assertEqual(next_changed(), want, query)
            conn.close()

    def test_a_body_must_be_sent_as_json(self):
        """Another web site can make the player's browser send a text/plain
        POST without asking first; it is refused before anything is done."""
        before = self.call('GET', '/api/games')[1]['games']
        status, err = self.call('POST', '/api/games', {'scenario': 'graziani', 'seat': 'axis'},
                                content_type='text/plain')
        self.assertEqual(status, 415, err)
        self.assertEqual(self.call('GET', '/api/games')[1]['games'], before)
        status, _ = self.call('POST', '/api/games', {'scenario': 'graziani'},
                              content_type='application/json; charset=utf-8')
        self.assertEqual(status, 200)

    def test_the_request_log_leaves_tokens_out(self):
        line = 'GET /api/games/g-1/stream?token=s3cret&after=4 HTTP/1.1'
        self.assertEqual(server.redact(line), 'GET /api/games/g-1/stream?token=…&after=4 HTTP/1.1')

    def test_the_rest_of_the_server_still_works(self):
        self.assertEqual(self.call('GET', '/api/vocab')[0], 200)
        # A body refused before anything is written: the real corrections stay as they are.
        status, err = self.call('PUT', '/api/corrections/A', {'hexes': [], 'sides': {}})
        self.assertEqual(status, 400, err)
        self.assertEqual(self.call('PUT', '/api/corrections/A')[0], 400)  # no body
        self.assertEqual(self.call('POST', '/api/no-such-route', {})[0], 404)
        status, err = self.call('GET', '/api/games/Bad_Id/view')
        self.assertEqual(status, 404)
        self.assertIn('error', err)  # JSON, as everywhere under /api/
        status, cat = self.call('GET', '/api/scenarios')
        self.assertEqual(status, 200)
        self.assertEqual(set(cat['setups']['italians']['counts']['axis']), {'map', 'pool'})
        gid, axis, cw = self.new_game()
        status, sheet = self.call('GET', f'/api/games/{gid}/logsheet/it/ltc/ltc', token=axis)
        self.assertEqual((status, sheet['identity']['name']), (200, 'Libyan Tank Command HQ'))
        self.assertEqual(self.call('GET', f'/api/games/{gid}/logsheet/it/ltc/ltc', token=cw)[0], 404)
        self.assertEqual(self.call('GET', f'/api/games/{gid}/logsheet/it/ltc/ltc')[0], 401)
        status, charts = self.call('GET', '/api/units')
        self.assertEqual(status, 200)
        self.assertEqual(set(charts), {'cw', 'it', 'gm'})
        self.assertEqual(charts['cw']['codes']['g']['type'], 'Tank Bn-Eq')
        self.assertEqual(charts['cw']['sheets'][0]['id'], 'cw/1-armd')
        self.assertIn('a9-cruiser', charts['cw']['weapons'])

    def test_a_setup_no_scenario_uses_yet(self):
        cat = server.read_json(server.SCENARIOS)
        cat['setups']['spare'] = copy.deepcopy(cat['setups']['crusader'])
        with mock.patch.object(server, 'read_json', return_value=cat):
            status, got = self.call('GET', '/api/scenarios')
        self.assertEqual(status, 200)
        self.assertNotIn('counts', got['setups']['spare'])
        self.assertIn('counts', got['setups']['crusader'])

    def test_a_damaged_save_is_not_taken_for_a_missing_game(self):
        gid, _, _ = self.new_game()
        server.GAMES.open.pop(gid)  # as after a restart
        with open(Path(self.tmp.name) / gid / 'events.jsonl', 'ab') as f:
            f.write(b'{}\n')
        with contextlib.redirect_stderr(io.StringIO()):  # the server prints the error
            status, err = self.call('GET', f'/api/games/{gid}/view')
        self.assertEqual(status, 500, err)
        self.assertIn('damaged', err['error'])

    def test_only_names_of_this_machine_are_answered(self):
        """A web site pointing its own name at this machine (DNS rebinding)
        sends that name as the Host, and is refused."""
        port = self.port
        for host in (f'127.0.0.1:{port}', f'localhost:{port}', f'[::1]:{port}', f'192.168.1.20:{port}', 'LOCALHOST.'):
            self.assertTrue(server.host_allowed(host), host)
        for host in (f'evil.example:{port}', 'evil.example', '[evil'):
            self.assertFalse(server.host_allowed(host), host)
        status, err = self.call('POST', '/api/games', {'scenario': 'graziani'}, host=f'evil.example:{port}')
        self.assertEqual(status, 403, err)
        status, _ = self.call('PUT', '/api/corrections/A', {'hexes': [], 'sides': {}}, host=f'evil.example:{port}')
        self.assertEqual(status, 403)
        self.assertEqual(self.call('GET', '/api/games', host=f'localhost:{port}')[0], 200)

    def test_streams_are_limited(self):
        gid, _, _ = self.new_game()
        with mock.patch.object(server, 'STREAMS', server.threading.BoundedSemaphore(1)):
            conn, next_changed = self.stream(gid)
            next_changed()
            status, err = self.call('GET', f'/api/games/{gid}/stream')
            self.assertEqual(status, 503, err)
            conn.close()

    def test_the_map_corrections_change_only_from_this_machine(self):
        handler = mock.Mock(path='/api/corrections/A', headers={}, client_address=('192.168.1.20', 50000))
        req = server.Request(handler, {'hexes': [], 'sides': {}})
        self.assertFalse(req.local)
        with mock.patch.object(server, 'save_section') as saved:
            with self.assertRaises(server.HTTPError) as caught:
                server.put_corrections('A', req)
        self.assertEqual(caught.exception.status, 403)
        saved.assert_not_called()
        for here in ('127.0.0.1', '::1'):
            self.assertTrue(server.Request(mock.Mock(path='/', headers={}, client_address=(here, 1)), None).local)


if __name__ == '__main__':
    unittest.main()
