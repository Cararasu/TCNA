"""What each seat sees, seats and tokens, and previews (views.py, seats.py)."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from cna.engine.commands import COMMANDS, Refused
from cna.engine.dice import DiceNeeded
from cna.engine.events import applies, event
from cna.engine.games import Games
from cna.engine.oa import face

TEST = COMMANDS.extended()


@TEST.command('test-views-roll', steps={'setup'})
def roll(ctx):
    yield event('test-views-rolled', dice=ctx.roll(2))


@applies('test-views-rolled')
def _rolled(state, ev):
    pass


class Seen(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.games = Games(Path(self.tmp.name), TEST)
        self.game = self.games.create('graziani', seed='test-seed')
        self.n = 0

    def tearDown(self):
        self.tmp.cleanup()

    def give(self, seat, type_, **args):
        self.n += 1
        return self.game.submit({'id': f'c{self.n}', 'type': type_, 'args': args}, seat)

    def units(self, side, **match):
        """The side's counters: its units not attached to another."""
        return [u for u in self.game.state['units'].values()
                if u['side'] == side and u['attached'] is None
                and all(u[k] == x if k != 'pool' else (u['loc']['kind'] == 'pool') == x
                                             for k, x in match.items())]

    def every(self, side, **match):
        """The side's units, attached or not."""
        return [u for u in self.game.state['units'].values()
                if u['side'] == side and all(u[k] == x for k, x in match.items())]

    def a_hex(self, side):
        return next(u['loc'] for u in self.units(side, flex=False) if u['loc']['kind'] == 'hex')

    def place_all(self, side):
        for u in self.units(side, pool=True):
            self.give(side, 'place-unit', unit=u['id'], loc=self.a_hex(side))

    def test_neither_side_sees_the_other_s_set_up(self):
        mine = self.units('axis', pool=True)[0]
        self.give('axis', 'place-unit', unit=mine['id'], loc=self.a_hex('axis'))
        cw = self.game.view('cw')
        axis_seen = {uid for uid, u in cw['units'].items() if u['side'] == 'axis'}
        self.assertEqual(axis_seen, {u['id'] for u in self.units('axis', flex=False)})
        self.assertNotIn(mine['id'], cw['units'])
        self.assertEqual(cw['undo']['axis'], [])
        self.assertFalse([ev for ev in cw['log'] if ev['type'] == 'unit-placed'])
        self.assertEqual(len(self.game.view('axis')['units']),
                         len(self.every('axis')) + len(self.units('cw', flex=False)))
        self.assertEqual(len(self.game.view('referee')['units']), len(self.game.state['units']))
        self.assertEqual(cw['unseen'], len(self.units('axis', flex=True)))
        self.assertEqual(self.game.view('referee')['unseen'], 0)

        self.place_all('axis')
        self.place_all('cw')
        self.give('axis', 'end-step')
        self.assertNotIn(mine['id'], self.game.view('cw')['units'])  # until both are done
        self.give('cw', 'end-step')
        cw = self.game.view('cw')
        self.assertEqual(cw['units'][mine['id']]['loc'], self.a_hex('axis'))
        self.assertTrue([ev for ev in cw['log'] if ev['type'] == 'unit-placed' and ev['by'] == 'axis'])

    def test_no_view_holds_a_secret(self):
        token = self.game.join('axis', 'Thomas')
        for seat in ('axis', 'cw', 'referee'):
            text = json.dumps(self.game.view(seat))
            self.assertNotIn('test-seed', text, seat)
            self.assertNotIn(token, text, seat)
            self.assertNotIn(self.game.state['seats']['axis']['key'], text, seat)
        self.assertNotIn(self.game.state['seats']['axis']['key'], self.game.save.meta_path.read_text())

    def test_the_other_side_sees_counter_faces_only(self):
        """Its counters as their faces show them; their log sheets (TOE, morale,
        assignment, the units they carry) stay with their owner, before and after
        the Set-up Stage."""
        def check():
            for seat, foe in (('axis', 'cw'), ('cw', 'axis')):
                v = self.game.view(seat)
                theirs = {uid: u for uid, u in v['units'].items() if u['side'] == foe}
                self.assertTrue(theirs)
                for u in theirs.values():
                    self.assertFalse({'toe', 'morale', 'parent'} & set(u), u)
                    self.assertIsNone(u['attached'], u)
                    self.assertTrue(u['name'] and u['type'], u)  # the face
                self.assertFalse([u for u in self.every(foe) if u['attached'] and u['id'] in v['units']])
                # Its own units, all of them, as they are
                mine = {uid: u for uid, u in v['units'].items() if u['side'] == seat}
                self.assertEqual(set(mine), {u['id'] for u in self.every(seat)})
                self.assertTrue(all('toe' in u and 'morale' in u for u in mine.values()))
                # Nor does the log tell: game-created, which holds the state, is shown without it
                self.assertFalse([ev for ev in v['log'] if 'state' in ev])
            self.assertEqual(len(self.game.view('referee')['units']), len(self.game.state['units']))

        check()
        self.place_all('axis')
        self.place_all('cw')
        self.give('axis', 'end-step')
        self.give('cw', 'end-step')
        self.assertNotEqual(self.game.state['clock']['step'], 'setup')
        check()
        self.assertEqual(self.game.view('cw')['unseen'], 0)

    def test_what_the_view_says_about_now(self):
        now = self.game.view('axis')['now']
        self.assertEqual((now['step'], now['case'], now['waiting']), ('setup', '59.2', ['axis', 'cw']))
        self.assertIn('place-unit', now['allowed'])
        self.assertNotIn('join', now['allowed'])
        self.assertEqual(self.game.view('referee')['now']['allowed'], [])

    def test_the_event_numbers_do_not_count_the_other_side_s_placements(self):
        start = self.game.view('cw')['seq']
        for u in self.units('axis', pool=True)[:2]:
            self.give('axis', 'place-unit', unit=u['id'], loc=self.a_hex('axis'))
        cw = self.game.view('cw')
        self.assertEqual(cw['seq'], start)
        self.assertEqual(self.game.view('axis')['seq'], start + 2)
        self.assertEqual(self.game.wait(start, 0.01, 'cw'), start)  # the stream stays quiet
        self.assertFalse([ev for ev in cw['log'] if 'seq' in ev])
        mine = self.units('cw', pool=True)[0]['id']
        done = self.give('cw', 'place-unit', unit=mine, loc=self.a_hex('cw'))
        self.assertNotIn('seq', self.game.visible(done, 'cw')[0])
        self.assertEqual(self.game.seq_for('cw'), start + 1)
        again = Games(Path(self.tmp.name), TEST).get(self.game.id)  # counted again on loading
        self.assertEqual((again.seq_for('cw'), again.seq_for('axis')), (start + 1, start + 2))

        self.place_all('axis')
        self.place_all('cw')
        self.give('axis', 'end-step')
        self.give('cw', 'end-step')
        cw = self.game.view('cw')
        self.assertEqual(cw['seq'], self.game.state['seq'])  # set-up is over: nothing is hidden
        self.assertTrue(all('seq' in ev for ev in cw['log']))


class Seats(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.game = Games(self.root).create('graziani', seed='test-seed')

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_token_acts_only_for_its_own_seat(self):
        axis = self.game.join('axis', 'Thomas')
        cw = self.game.join('cw', '  Ann   Smith ')
        self.assertEqual((self.game.seat_of(axis), self.game.seat_of(cw)), ('axis', 'cw'))
        self.assertEqual(self.game.view('axis')['seats']['cw'], {'name': 'Ann Smith'})
        self.assertIsNone(self.game.seat_of('not-a-token'))
        self.assertIsNone(self.game.seat_of(None))
        unit = next(u for u in self.game.state['units'].values() if u['side'] == 'axis' and u['flex'] and u['attached'] is None)
        loc = {'kind': 'pool'} if unit['loc']['kind'] != 'pool' else next(
            u['loc'] for u in self.game.state['units'].values() if u['loc'] and u['loc']['kind'] == 'hex')
        with self.assertRaises(Refused):
            self.game.submit({'id': 'x', 'type': 'place-unit', 'args': {'unit': unit['id'], 'loc': loc}},
                             self.game.seat_of(cw))

    def test_a_seat_is_taken_once(self):
        self.game.join('axis', 'Thomas')
        with self.assertRaises(Refused):
            self.game.join('axis', 'Someone else')
        with self.assertRaises(Refused):
            self.game.join('italy', 'Benito')

    def test_only_sandbox_games_have_a_referee(self):
        with self.assertRaises(Refused):
            self.game.join('referee', 'Ref')  # it would show the Axis player the Commonwealth set-up
        sandbox = Games(self.root).create('graziani', sandbox=True, seed='test-seed')
        self.assertEqual(sandbox.seat_of(sandbox.join('referee', 'Ref')), 'referee')
        with self.assertRaises(Refused):
            Games(self.root).create('graziani', seat='referee')

    def test_join_is_not_a_command_a_player_can_send(self):
        with self.assertRaises(Refused):
            self.game.submit({'id': 'x', 'type': 'join', 'args': {'seat': 'cw', 'name': 'me', 'key': 'k'}}, 'axis')

    def test_seats_are_kept_across_a_restart(self):
        token = self.game.join('cw', 'Ann')
        again = Games(self.root).get(self.game.id)
        self.assertEqual(again.seat_of(token), 'cw')


class Previews(Seen):
    def test_a_preview_gives_the_command_s_events_and_changes_nothing(self):
        unit = self.units('axis', pool=True)[0]['id']
        cmd = {'id': 'p1', 'type': 'place-unit', 'args': {'unit': unit, 'loc': self.a_hex('axis')}}
        before = copy.deepcopy(self.game.state)
        size = self.game.save.log.stat().st_size
        seen = self.game.preview(cmd, 'axis')
        self.assertEqual(self.game.state, before)
        self.assertEqual(self.game.save.log.stat().st_size, size)
        done = self.game.submit(cmd, 'axis')
        strip = lambda evs: [{k: x for k, x in ev.items() if k != 'at'} for ev in evs]  # noqa: E731
        self.assertEqual(strip(seen), strip(done))

    def test_a_preview_is_refused_as_the_command_would_be(self):
        unit = self.units('cw', pool=True)[0]['id']
        with self.assertRaises(Refused):
            self.game.preview({'type': 'place-unit', 'args': {'unit': unit, 'loc': self.a_hex('cw')}}, 'axis')

    def test_a_preview_rolls_no_dice(self):
        with self.assertRaises(DiceNeeded):
            self.game.preview({'type': 'test-views-roll'}, 'axis')
        self.assertEqual(self.game.state['dice']['rolls'], 0)

    def test_a_preview_works_from_the_seat_s_view(self):
        """The Commonwealth's preview can't see the Axis units placed in secret,
        and neither it nor the command itself tells of them."""
        unit = self.units('axis', pool=True)[0]
        self.give('axis', 'place-unit', unit=unit['id'], loc=self.a_hex('axis'))
        self.assertNotIn(unit['id'], self.game.view('cw')['units'])
        cmd = {'type': 'place-unit', 'args': {'unit': unit['id'], 'loc': self.a_hex('cw')}}
        refusals = []
        for attempt in (self.game.preview, self.game.submit):
            with self.assertRaises(Refused) as r:
                attempt(cmd, 'cw')
            refusals.append(r.exception.message)
        self.assertEqual(refusals[0], refusals[1])
        self.assertNotIn(face(unit)['name'], refusals[0])


if __name__ == '__main__':
    unittest.main()
