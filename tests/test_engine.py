"""The engine's core: commands, events, dice and the sequence of play (5.2)."""
import copy
import unittest

from cna.engine import events, play, sequence, state
from cna.engine.commands import COMMANDS, Broken, Refused, run
from cna.engine.dice import die
from cna.engine.events import applies, event

# One Operations Stage of 5.2: the steps before the player turns, then the
# steps of each player turn (III.F-L).
STAGE = ['initiative-declaration', 'weather', 'organization', 'convoy-arrival', 'fleet-assignment',
         'fleet-repair']
PLAYER_TURN = ['reserve-designation', 'movement', 'breakdown', 'position', 'barrage', 'retreat-before-assault',
               'force-assignment', 'anti-armor', 'close-assault', 'reserve-release', 'truck-convoy', 'rail',
               'towing', 'maintenance', 'patrol']
TURN = ['initiative', 'convoy-schedule', 'tactical-shipping', *(STAGE + PLAYER_TURN * 2) * 3, 'end-of-turn']

# Commands for testing only.
TEST = COMMANDS.extended()


@TEST.command('test-poke', steps={'movement'}, available=lambda s: s['sandbox'])
def poke(ctx):
    yield event('test-poked')


@TEST.command('test-roll', anyone=True)
def roll(ctx, n=2):
    yield event('test-rolled', dice=ctx.roll(n))


@TEST.command('test-forget-dice', anyone=True)
def forget_dice(ctx):
    ctx.roll()
    yield event('test-poked')


@TEST.command('test-refuse-late', anyone=True)
def refuse_late(ctx):
    yield event('test-poked')
    raise Refused('too late')


@TEST.command('test-break-first', anyone=True)
def break_first(ctx):
    yield event('test-half-applied')


@applies('test-poked')
@applies('test-rolled')
def _nothing(s, ev):
    pass


@applies('test-half-applied')
def _half(s, ev):
    s['units']['half'] = {}
    raise KeyError('a bug')


def new_game(start=(1, 1), end=(6, 3), sandbox=False, initiative='axis'):
    start = {'turn': start[0], 'stage': start[1]}
    s = state.new(id='test', scenario='test', games={'land': True, 'air': False, 'logistics': False},
                  sandbox=sandbox, start=start, end={'turn': end[0], 'stage': end[1]},
                  initiative={'side': initiative, 'through': start['turn']},
                  clock=sequence.setup_clock(start, initiative), units={}, seed='test-seed')
    log = [events.created(s)]
    return events.replay(log), log


def give(g, log, side, type_, registry=TEST, **args):
    evs = run(g, {'id': f'c{len(log)}', 'type': type_, 'args': args}, side, registry)
    log.extend(copy.deepcopy(evs))
    return evs


def finish_setup(g, log):
    give(g, log, 'axis', 'end-step')
    give(g, log, 'cw', 'end-step')


def play_on(g, log, until, limit=1000):
    """Ends steps until the clock reaches `until`; returns the steps passed or stopped at."""
    seen = []
    for _ in range(limit):
        if g['clock']['step'] == until:
            return seen
        side = sorted(sequence.waiting(g))[0]
        if g['clock']['step'] == 'initiative-declaration':
            evs = give(g, log, side, 'set-order', player='A')
        else:
            evs = give(g, log, side, 'end-step')
        for ev in evs:
            if ev['type'] == 'clock-advanced':
                seen += [p['step'] for p in ev['passed']] + [ev['clock']['step']]
    raise AssertionError(f'{until} not reached')


class Dice(unittest.TestCase):
    def test_same_seed_same_rolls(self):
        a = [die('s', n) for n in range(200)]
        self.assertEqual(a, [die('s', n) for n in range(200)])
        self.assertNotEqual(a, [die('t', n) for n in range(200)])

    def test_every_face_comes_up_evenly(self):
        counts = [0] * 7
        for n in range(6000):
            counts[die('s', n)] += 1
        self.assertEqual(counts[0], 0)
        for face in range(1, 7):
            self.assertTrue(880 < counts[face] < 1120, counts)

    def test_rolls_are_recorded_and_counted(self):
        g, log = new_game()
        first = give(g, log, None, 'test-roll')[0]['dice']
        second = give(g, log, None, 'test-roll', n=3)[0]['dice']
        self.assertEqual(first + second, [die('test-seed', n) for n in range(5)])
        self.assertEqual(g['dice']['rolls'], 5)
        self.assertEqual(events.replay(log), g)

    def test_a_roll_no_event_records_is_an_error(self):
        g, log = new_game()
        with self.assertRaises(Broken):
            give(g, log, None, 'test-forget-dice')


class Commands(unittest.TestCase):
    def test_unknown_command(self):
        g, log = new_game()
        with self.assertRaises(Refused):
            give(g, log, 'axis', 'teleport')

    def test_refused_out_of_its_step(self):
        g, log = new_game()
        with self.assertRaises(Refused):
            give(g, log, 'axis', 'set-order', player='A')

    def test_refused_for_the_wrong_side(self):
        g, log = new_game()
        finish_setup(g, log)
        self.assertEqual(g['clock']['step'], 'initiative-declaration')
        with self.assertRaises(Refused):
            give(g, log, 'cw', 'set-order', player='A')
        with self.assertRaises(Refused):
            give(g, log, 'cw', 'end-step')
        with self.assertRaises(Refused):
            give(g, log, 'referee', 'end-step')

    def test_refused_for_bad_arguments(self):
        g, log = new_game()
        finish_setup(g, log)
        for args in ({}, {'player': 'C'}, {'player': 'A', 'colour': 'red'}):
            with self.assertRaises(Refused):
                give(g, log, 'axis', 'set-order', **args)

    def test_a_refusal_changes_nothing(self):
        g, log = new_game()
        before = copy.deepcopy(g)
        with self.assertRaises(Refused):
            give(g, log, 'cw', 'set-order', player='A')
        self.assertEqual(g, before)

    def test_a_late_refusal_breaks_the_state(self):
        g, log = new_game()
        with self.assertRaises(Broken):
            give(g, log, None, 'test-refuse-late')

    def test_a_first_event_failing_partway_breaks_the_state(self):
        g, _ = new_game()
        with self.assertRaises(Broken):
            run(g, {'id': 'c', 'type': 'test-break-first'}, None, TEST)

    def test_a_step_has_one_ready_check(self):
        with self.assertRaises(ValueError):
            play.ready('setup')(lambda state, side: None)

    def test_events_are_stamped(self):
        g, log = new_game()
        ev = give(g, log, 'axis', 'end-step')[0]
        self.assertEqual((ev['seq'], ev['cmd'], ev['by']), (2, 'c1', 'axis'))
        self.assertEqual(g['seq'], 2)

    def test_both_sides_end_a_shared_step(self):
        g, log = new_game()
        self.assertEqual(give(g, log, 'axis', 'end-step')[0]['type'], 'side-done')
        with self.assertRaises(Refused):
            give(g, log, 'axis', 'end-step')
        give(g, log, 'axis', 'resume-step')
        with self.assertRaises(Refused):
            give(g, log, 'axis', 'resume-step')
        give(g, log, 'cw', 'end-step')
        self.assertEqual(g['clock']['step'], 'setup')
        self.assertEqual(give(g, log, 'axis', 'end-step')[0]['type'], 'clock-advanced')
        self.assertEqual(g['clock']['done'], {'axis': False, 'cw': False})

    def test_replay_gives_the_same_state(self):
        g, log = new_game(sandbox=True)
        finish_setup(g, log)
        play_on(g, log, 'end-of-turn')
        self.assertEqual(events.replay(log), g)

    def test_allowed(self):
        g, log = new_game()
        finish_setup(g, log)
        # end-step is never offered where it would always be refused: set-order ends this step (7.11)
        self.assertEqual(set(COMMANDS.allowed(g, 'axis')), {'set-order', 'undo'})
        self.assertEqual(COMMANDS.allowed(g, 'cw'), [])


class Sequence(unittest.TestCase):
    def test_a_game_turn_follows_5_2(self):
        g, log = new_game()
        finish_setup(g, log)
        seen = play_on(g, log, 'end-of-turn')
        self.assertEqual(['initiative', 'convoy-schedule', 'tactical-shipping', 'initiative-declaration'] + seen,
                         TURN)
        end_turn = g['clock']
        play_on(g, log, 'initiative-declaration')
        self.assertEqual(g['clock']['turn'], end_turn['turn'] + 1)

    def test_steps_with_nothing_to_do_are_passed(self):
        g, log = new_game()
        finish_setup(g, log)
        give(g, log, 'axis', 'set-order', player='A')
        self.assertEqual((g['clock']['stage'], g['clock']['step']), (2, 'initiative-declaration'))

    def test_the_order_is_declared_each_opstage(self):
        g, log = new_game()
        finish_setup(g, log)
        with self.assertRaises(Refused) as r:
            give(g, log, 'axis', 'end-step')
        self.assertEqual(r.exception.case, '7.11')
        self.assertEqual(g['clock']['step'], 'initiative-declaration')

    def test_sandbox_stops_at_each_movement_segment(self):
        g, log = new_game(sandbox=True)
        finish_setup(g, log)
        give(g, log, 'axis', 'set-order', player='B')
        self.assertEqual((g['clock']['player'], g['clock']['step']), ('A', 'movement'))
        self.assertEqual(sequence.waiting(g), {'cw'})
        give(g, log, 'cw', 'test-poke')
        with self.assertRaises(Refused):
            give(g, log, 'axis', 'test-poke')
        give(g, log, 'cw', 'end-step')
        # Player A may go round the Movement and Combat Phase again (5.2 III.G)
        self.assertEqual((g['clock']['player'], g['clock']['step']), ('A', 'reserve-release'))
        give(g, log, 'cw', 'end-step')
        self.assertEqual((g['clock']['player'], g['clock']['step']), ('B', 'movement'))
        self.assertEqual(sequence.waiting(g), {'axis'})
        give(g, log, 'axis', 'end-step')  # Player B's phase is not repeated: on to Player B's truck convoys
        self.assertEqual((g['clock']['stage'], g['clock']['step']), (2, 'initiative-declaration'))

    def test_player_a_goes_round_the_movement_and_combat_phase_again(self):
        g, log = new_game(sandbox=True)
        finish_setup(g, log)
        give(g, log, 'axis', 'set-order', player='A')
        give(g, log, 'axis', 'end-step')
        self.assertEqual(g['clock']['step'], 'reserve-release')
        self.assertIn('repeat-loop', COMMANDS.allowed(g, 'axis'))
        give(g, log, 'axis', 'repeat-loop', registry=COMMANDS)
        self.assertEqual((g['clock']['player'], g['clock']['step'], g['clock']['round']), ('A', 'movement', 2))
        with self.assertRaises(Refused):
            give(g, log, 'axis', 'repeat-loop', registry=COMMANDS)  # only at the end of the phase
        self.assertEqual(events.replay(log), g)

    def test_without_sandbox_the_phase_is_not_repeated(self):
        g, log = new_game()
        finish_setup(g, log)
        g['clock'] = sequence.clock(1, 1, 'A', 'reserve-release', {'A': 'axis', 'B': 'cw'})
        with self.assertRaises(Refused):
            give(g, log, 'axis', 'repeat-loop', registry=COMMANDS)

    def test_a_scenario_starting_mid_turn(self):
        g, log = new_game(start=(26, 3), end=(38, 3))
        finish_setup(g, log)
        self.assertEqual(sequence.where(g['clock']),
                         {'turn': 26, 'stage': 3, 'player': None, 'step': 'initiative-declaration'})
        play_on(g, log, 'end-of-turn')
        self.assertEqual(g['clock']['turn'], 26)

    def test_the_game_ends_after_its_last_opstage(self):
        g, log = new_game(end=(1, 2))
        finish_setup(g, log)
        give(g, log, 'axis', 'set-order', player='A')
        give(g, log, 'axis', 'set-order', player='A')
        self.assertEqual(sequence.where(g['clock']), {'turn': 1, 'stage': 2, 'player': None, 'step': 'game-over'})
        for side in state.SIDES:
            self.assertEqual(COMMANDS.allowed(g, side), [])

    def test_going_round_the_movement_and_combat_phase(self):
        g, _ = new_game()
        order = {'A': 'axis', 'B': 'cw'}
        g['clock'] = sequence.clock(1, 2, 'A', 'reserve-release', order)
        always = lambda s: True  # noqa: E731
        c, _ = sequence.advance(g, always, repeat=True)
        self.assertEqual((c['step'], c['round']), ('movement', 2))
        c, _ = sequence.advance({**g, 'clock': c}, always)
        self.assertEqual((c['step'], c['round']), ('breakdown', 2))
        c, _ = sequence.advance(g, always)
        self.assertEqual((c['step'], c['round']), ('truck-convoy', 1))
        g['clock'] = sequence.clock(1, 2, 'A', 'movement', order)
        with self.assertRaises(ValueError):
            sequence.advance(g, always, repeat=True)

    def test_rail_movement_is_the_commonwealth_s(self):
        g, _ = new_game()
        g['clock'] = sequence.clock(1, 1, 'A', 'rail', {'A': 'axis', 'B': 'cw'})
        self.assertEqual(sequence.actors(g), set())
        g['clock'] = sequence.clock(1, 1, 'B', 'rail', {'A': 'axis', 'B': 'cw'})
        self.assertEqual(sequence.actors(g), {'cw'})


if __name__ == '__main__':
    unittest.main()
