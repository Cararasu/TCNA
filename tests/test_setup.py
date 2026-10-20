"""A new game from each scenario, and the Set-up Stage (59.2)."""
import copy
import json
import unittest

from cna.engine import events, sequence
from cna.engine.board import board
from cna.engine.commands import Refused, run
from cna.engine.setup import counts, new_game, placement
from cna.paths import SCENARIOS


def load():
    with open(SCENARIOS, encoding='utf-8') as f:
        return json.load(f)


def start(scenario='graziani', **kw):
    log = [events.created(new_game(scenario, seed='test-seed', **kw))]
    return events.replay(log), log


def give(g, log, side, type_, **args):
    evs = run(g, {'id': f'c{len(log)}', 'type': type_, 'args': args}, side)
    log.extend(copy.deepcopy(evs))
    return evs


def hex_loc(label):
    return {'kind': 'hex', 'id': board().hex_of_label(label)}


def of(g, side, pool=None, flex=None):
    return [u for u in g['units'].values() if u['side'] == side
            and (pool is None or (u['loc']['kind'] == 'pool') == pool) and (flex is None or u['flex'] == flex)]


def place_all(g, log, side, label):
    for u in of(g, side, pool=True):
        give(g, log, side, 'place-unit', unit=u['id'], loc=hex_loc(label))


class NewGame(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load()

    def test_every_scenario_creates_a_game(self):
        b = board()
        for s in self.data['scenarios']:
            setup = self.data['setups'][s['setup']]
            g, _ = start(s['id'])
            self.assertEqual(g['clock']['step'], 'setup', s['id'])
            self.assertEqual(g['initiative'], {k: setup['initiative'][k] for k in ('side', 'through')}, s['id'])
            self.assertEqual(g['clock']['order']['A'], setup['initiative']['side'], s['id'])
            self.assertEqual(len(g['units']), sum(len(e['units']) for e in setup['deploy']), s['id'])
            for u in g['units'].values():
                self.assertTrue(b.is_place(u['loc']), u)
            # The game keeps its deployments, so later changes to scenarios.json don't change it.
            self.assertEqual(g['deployments'], [{k: x for k, x in e.items() if k != 'units'} for e in setup['deploy']])

    def test_units_start_as_the_scenario_screen_shows(self):
        """Units of an area with no hex named go to the pool, as the scenario screen counts them (counts)."""
        for s in self.data['scenarios']:
            g, _ = start(s['id'])
            shown = counts(self.data['setups'][s['setup']], board())
            for side in ('axis', 'cw'):
                self.assertEqual({'map': len(of(g, side, pool=False)), 'pool': len(of(g, side, pool=True))},
                                 shown[side], (s['id'], side))
        g, _ = start('graziani')
        self.assertEqual((len(of(g, 'axis', pool=False)), len(of(g, 'axis', pool=True))), (31, 17))

    def test_a_scenario_place_not_on_the_board_is_an_error(self):
        """A mistake in scenarios.json mustn't turn fixed units into units to place."""
        b = board()
        for at in ({'hex': 'C9999'}, {'hexes': ['Z0101']}, {'near': 'C99 99', 'within': 2},
                   {'area': 'Somewhere', 'anchor': 'Q1'}, {'box': 'no-such-box'}):
            with self.assertRaises(ValueError, msg=at):
                placement(at, b)
        self.assertEqual(placement({'area': 'Anywhere in Libya'}, b), ({'kind': 'pool'}, True))
        self.assertEqual(placement({'hex': 'C4218'}, b), (hex_loc('C4218'), False))

    def test_the_creator_may_give_the_initiative_away(self):
        g, _ = start('graziani', initiative_choice='cw')
        self.assertEqual(g['initiative'], {'side': 'cw', 'through': 1})
        self.assertEqual(g['clock']['order'], {'A': 'cw', 'B': 'axis'})

    def test_rolling_for_the_first_initiative(self):
        g, _ = start('crusader', initiative_choice='roll')
        self.assertEqual(g['initiative'], {'side': 'cw', 'through': 56})
        with self.assertRaises(ValueError):
            start('graziani', initiative_choice='roll')
        with self.assertRaises(ValueError):
            start('graziani', initiative_choice='italy')

    def test_choices_not_offered_yet(self):
        with self.assertRaises(ValueError):
            start('graziani', games={'air': True})
        with self.assertRaises(ValueError):
            start('graziani', games=['air'])
        with self.assertRaises(ValueError):
            start('tobruk')


class SetupStage(unittest.TestCase):
    def test_placing_a_unit_from_the_pool(self):
        g, log = start()
        u = of(g, 'axis', pool=True)[0]
        give(g, log, 'axis', 'place-unit', unit=u['id'], loc=hex_loc('C4218'))
        self.assertEqual(g['units'][u['id']]['loc'], hex_loc('C4218'))
        give(g, log, 'axis', 'place-unit', unit=u['id'], loc={'kind': 'pool'})
        self.assertEqual(g['units'][u['id']]['loc'], {'kind': 'pool'})
        self.assertEqual(events.replay(log), g)

    def test_what_cannot_be_placed(self):
        g, log = start()
        fixed = of(g, 'axis', flex=False)[0]
        pooled = of(g, 'axis', pool=True)[0]
        enemy = of(g, 'cw')[0]
        bad = [('axis', fixed['id'], hex_loc('C4218')),            # set up where the scenario says
               ('axis', enemy['id'], hex_loc('C4218')),            # not the side's own
               ('axis', 'no-such-unit', hex_loc('C4218')),
               ('axis', pooled['id'], {'kind': 'hex', 'id': '9999'}),  # not on the map
               ('axis', pooled['id'], {'kind': 'zone', 'id': 'atlantis'}),
               ('axis', pooled['id'], {'kind': 'hex', 'id': ['C4218']}),  # not JSON the board reads
               ('axis', pooled['id'], {'kind': ['hex'], 'id': 'C4218'}),
               ('axis', pooled['id'], {'kind': 'pool'})]           # already there
        before = copy.deepcopy(g)
        for side, unit, loc in bad:
            with self.assertRaises(Refused, msg=(unit, loc)):
                give(g, log, side, 'place-unit', unit=unit, loc=loc)
        self.assertEqual(g, before)

    def test_undo_takes_back_the_last_placement(self):
        g, log = start()
        a, b = of(g, 'axis', pool=True)[:2]
        give(g, log, 'axis', 'place-unit', unit=a['id'], loc=hex_loc('C4218'))
        give(g, log, 'axis', 'place-unit', unit=b['id'], loc=hex_loc('C4120'))
        with self.assertRaises(Refused):
            give(g, log, 'cw', 'undo')
        give(g, log, 'axis', 'undo')
        self.assertEqual(g['units'][b['id']]['loc'], {'kind': 'pool'})
        self.assertEqual(g['units'][a['id']]['loc'], hex_loc('C4218'))
        give(g, log, 'axis', 'undo')
        self.assertEqual(g['units'][a['id']]['loc'], {'kind': 'pool'})
        with self.assertRaises(Refused):
            give(g, log, 'axis', 'undo')
        self.assertEqual(events.replay(log), g)

    def test_placing_units_together(self):
        g, log = start()
        a, b, c = (u['id'] for u in of(g, 'axis', pool=True)[:3])
        evs = give(g, log, 'axis', 'place-unit', units=[a, b, c], loc=hex_loc('C4218'))
        self.assertEqual(len(evs), 1)
        self.assertEqual({g['units'][x]['loc']['id'] for x in (a, b, c)}, {hex_loc('C4218')['id']})
        before = copy.deepcopy(g)
        fixed = of(g, 'axis', flex=False)[0]['id']
        for args in ({'units': [a, fixed]}, {'units': [a, a]}, {'units': []}, {'unit': a, 'units': [b]}, {}):
            with self.assertRaises(Refused, msg=args):
                give(g, log, 'axis', 'place-unit', loc={'kind': 'pool'}, **args)
        self.assertEqual(g, before)  # each refused whole
        give(g, log, 'axis', 'undo')  # one undo takes them all back
        self.assertEqual({g['units'][x]['loc']['kind'] for x in (a, b, c)}, {'pool'})
        self.assertEqual(events.replay(log), g)

    def test_play_begins_once_both_sides_have_set_up(self):
        g, log = start()
        with self.assertRaises(Refused):
            give(g, log, 'axis', 'end-step')  # units still in the pool
        place_all(g, log, 'axis', 'C4218')
        give(g, log, 'axis', 'end-step')
        with self.assertRaises(Refused):
            give(g, log, 'axis', 'place-unit', unit=of(g, 'axis', flex=True)[0]['id'], loc=hex_loc('C4120'))
        place_all(g, log, 'cw', 'D3714')
        give(g, log, 'cw', 'end-step')
        self.assertEqual(sequence.where(g['clock']),
                         {'turn': 1, 'stage': 1, 'player': None, 'step': 'initiative-declaration'})
        with self.assertRaises(Refused):
            give(g, log, 'axis', 'undo')  # nothing left to undo in the new step
        self.assertEqual(events.replay(log), g)


class Sandbox(unittest.TestCase):
    def to_movement(self, sandbox):
        g, log = start(sandbox=sandbox)
        place_all(g, log, 'axis', 'C4218')
        place_all(g, log, 'cw', 'D3714')
        give(g, log, 'axis', 'end-step')
        give(g, log, 'cw', 'end-step')
        give(g, log, 'axis', 'set-order', player='A')
        return g, log

    def test_moving_a_stack(self):
        g, log = self.to_movement(sandbox=True)
        self.assertEqual((g['clock']['player'], g['clock']['step']), ('A', 'movement'))
        stack = [u['id'] for u in of(g, 'axis') if u['loc'] == hex_loc('C4218')]
        give(g, log, 'axis', 'move-unit', units=stack, to=hex_loc('C4120'))
        self.assertTrue(all(g['units'][uid]['loc'] == hex_loc('C4120') for uid in stack))
        with self.assertRaises(Refused):
            give(g, log, 'cw', 'move-unit', units=[of(g, 'cw')[0]['id']], to=hex_loc('C4120'))
        give(g, log, 'axis', 'undo')
        self.assertTrue(all(g['units'][uid]['loc'] == hex_loc('C4218') for uid in stack))
        self.assertEqual(events.replay(log), g)

    def test_no_moves_outside_the_sandbox(self):
        g, log = self.to_movement(sandbox=False)
        self.assertEqual(g['clock']['step'], 'initiative-declaration')
        with self.assertRaises(Refused):
            give(g, log, 'axis', 'move-unit', units=[of(g, 'axis')[0]['id']], to=hex_loc('C4120'))


if __name__ == '__main__':
    unittest.main()
