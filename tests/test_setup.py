"""A new game from each scenario, and the Set-up Stage (59.2)."""
import copy
import json
import unittest

from cna.engine import events, oa, sequence
from cna.engine.board import board
from cna.engine.commands import Refused, run
from cna.engine.setup import counts, new_game, placement, units
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
    return [u for u in g['units'].values() if u['side'] == side and u['attached'] is None
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
            # Every listing brings its unit, or its units
            for i, e in enumerate(setup['deploy']):
                for k, u in enumerate(e['units']):
                    self.assertTrue([x for x in g['units'].values() if (x['deployment'], x['listing']) == (i, k)],
                                    (s['id'], u['name']))
            for u in g['units'].values():
                if u['attached'] is None:
                    self.assertTrue(b.is_place(u['loc']), u)
                else:
                    self.assertIsNone(u['loc'], u)
                    self.assertIn(u['attached'], g['units'], u)
            # The game keeps its deployments, so later changes to scenarios.json don't change it.
            self.assertEqual([{k: x for k, x in d.items() if k != 'listings'} for d in g['deployments']],
                             [{k: x for k, x in e.items() if k != 'units'} for e in setup['deploy']])
            self.assertEqual([[x['name'] for x in d['listings']] for d in g['deployments']],
                             [[x['name'] for x in e['units']] for e in setup['deploy']])

    def test_units_start_as_the_scenario_screen_shows(self):
        """Units of an area with no hex named go to the pool, as the scenario screen counts them (counts)."""
        for s in self.data['scenarios']:
            g, _ = start(s['id'])
            shown = counts(self.data['setups'][s['setup']], board(), s['start'])
            for side in ('axis', 'cw'):
                self.assertEqual({'map': len(of(g, side, pool=False)), 'pool': len(of(g, side, pool=True))},
                                 shown[side], (s['id'], side))
        g, _ = start('graziani')
        # 31 listings on the map; the garrisons and the 3rd CCNN, with no HQ, are several counters each
        self.assertEqual((len(of(g, 'axis', pool=False)), len(of(g, 'axis', pool=True))), (65, 17))

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


class Expansion(unittest.TestCase):
    """Each listing brings its units of the OA Charts (59.2, 4.25, 4.42)."""

    @classmethod
    def setUpClass(cls):
        cls.games = {s: start(s)[0] for s in ('graziani', 'race-for-tobruk', 'crusader', 'last-chance')}

    def units(self, scenario):
        return self.games[scenario]['units']

    def carried(self, scenario, uid):
        return [x['id'] for x in oa.carried(self.games[scenario], uid)]

    def test_a_unit_is_its_oa_unit(self):
        for s, g in self.games.items():
            for uid, u in g['units'].items():
                if u['oa']:
                    self.assertEqual(uid, u['oa'], s)
                    self.assertEqual(u['side'], 'cw' if uid.startswith('cw/') else 'axis', uid)
                else:
                    self.assertIn(u['kind'], ('raider', 'replacements', 'recovery'), uid)

    def test_attached_units_are_where_their_carrier_is(self):
        """The 1st Greek Brigade of 4.25: its HQ carries its four units, and here
        is itself assigned and attached to the 50th Division (63.31)."""
        u = self.units('last-chance')
        greek = 'cw/1-greek/1st-greek-bde-hq'
        self.assertEqual(self.carried('last-chance', greek), ['cw/1-greek/1st-greek-infantry-bn', 'cw/1-greek/2-greek',
                                                              'cw/1-greek/3-greek', 'cw/1-greek/1-grkfld'])
        self.assertEqual((u[greek]['attached'], u[greek]['parent']), ('cw/50-inf/50th-infantry-div-hq',) * 2)
        here = oa.place(self.games['last-chance'], 'cw/50-inf/50th-infantry-div-hq')
        self.assertEqual(here, hex_loc('E2501'))
        self.assertEqual(oa.place(self.games['last-chance'], 'cw/1-greek/2-greek'), here)
        self.assertIsNone(u['cw/1-greek/2-greek']['loc'])

    def test_less_assg_and_att(self):
        """Crusader's 7th Armoured Bde (62.31): Assg 7 Hus, 6 RTR, 2 RTR; Less its own
        1 RTR and 8 Hus; Att 4 RHA, which stays assigned to the 7th Support Group."""
        u = self.units('crusader')
        bde = 'cw/7-armd/7th-armored-bde-hq'
        self.assertEqual(self.carried('crusader', bde),
                         ['cw/7-armd/7-hus', 'cw/7-armd/6-rtr', 'cw/uk-armor/2-rtr', 'cw/7-armd/4-rha'])
        self.assertEqual(u['cw/uk-armor/2-rtr']['parent'], bde)
        self.assertEqual(u['cw/7-armd/4-rha']['parent'], 'cw/7-armd/7-spt')
        # The 1 RTR and 8 Hussars are assigned elsewhere: to the 32nd Army Tank Bde and the 4th Armoured
        self.assertEqual(u['cw/7-armd/1-rtr']['attached'], 'cw/2-armd/32-army')
        self.assertEqual(u['cw/7-armd/8-hus']['attached'], 'cw/7-armd/4')
        # Its parent is the one 62.31 names, or none: "no longer assigned to the 7th Armoured Div"
        self.assertEqual(u['cw/22-armd/22']['parent'], 'cw/7-armd/7th-armored-div-hq')
        self.assertIsNone(u['cw/7-armd/4']['parent'])

    def test_consists_of(self):
        """Crusader's 21st Panzer (62.41): its roster, a regiment of three units from
        three formations among it."""
        self.assertEqual(self.carried('crusader', 'gm/5-le/21'),
                         ['gm/5-le/5', 'gm/15-pz/104', 'gm/5-le/39', 'gm/gm-arty/155', 'gm/5-le/200'])
        self.assertEqual(self.carried('crusader', 'gm/15-pz/104'), ['gm/15-pz/ii-104', 'gm/5-le/8', 'gm/gm-inf/708'])
        self.assertEqual(self.units('crusader')['gm/5-le/8']['parent'], 'gm/15-pz/104')
        # The 90th Light's counter is "the HQ and the 613th Flak Bn"
        self.assertEqual(self.carried('crusader', 'gm/90-le/90-le'), ['gm/90-le/613'])

    def test_a_subordinate_arriving_after_the_start_is_left_out(self):
        u = self.units('graziani')
        self.assertIn('cw/4-in/5-in', u)
        self.assertNotIn('cw/4-in/7-in', u)  # Game-Turn 5
        self.assertNotIn('cw/4-in/1-fld', u)  # Game-Turn 3
        # but one a listing names comes: the 708th Coy arrives in Game-Turn 76
        self.assertIn('gm/gm-inf/708', self.units('crusader'))

    def test_a_counter_that_replaces_another(self):
        """The 21st Panzer HQ takes the 5th Light's place in February 1942 (Game-Turn 58),
        with its subordinates."""
        self.assertIn('gm/5-le/5-le', self.units('race-for-tobruk'))
        self.assertNotIn('gm/5-le/21', self.units('race-for-tobruk'))
        u = self.units('last-chance')
        self.assertNotIn('gm/5-le/5-le', u)
        self.assertEqual(self.carried('last-chance', 'gm/5-le/21')[:2], ['gm/5-le/5', 'gm/5-le/8'])  # less the 2nd MG Bn
        self.assertEqual(u['gm/5-le/5']['parent'], 'gm/5-le/21')
        # The 200th Rifle Regt is assigned to it but "begins the scenario detached"
        self.assertEqual((u['gm/15-pz/200']['parent'], u['gm/15-pz/200']['attached']), ('gm/5-le/21', None))
        self.assertEqual(u['gm/15-pz/200']['loc'], u['gm/5-le/21']['loc'])
        # The II/155 Artillery Bn takes over the TOE of the I/75 (OA note e)
        self.assertEqual(self.units('crusader')['gm/gm-arty/ii']['toe'], [{'w': 'gm/10-5cm-k18-medium-gun', 'n': 3}])

    def test_units_the_sheet_attaches(self):
        """Ariete's I(L) and II(L) are listed on its sheet but belong to no formation."""
        u = self.units('crusader')
        for t in ('it/it-armor/i-l', 'it/it-armor/ii-l'):
            self.assertEqual((u[t]['attached'], u[t]['parent']), ('it/ariete/ariete', None))

    def test_a_unit_one_sheet_attaches_to_another_formation(self):
        """The IX(L) belongs to the Trivoli Regt but begins attached to the 2nd
        Libyan Division (its sheet's note b): in a set-up with both and no listing
        naming it, it comes once, attached to the division, in either order."""
        for first, second in (('it/2-libyan/2nd-libyan-infantry-hq', 'it/ltc/ltc'),
                              ('it/ltc/ltc', 'it/2-libyan/2nd-libyan-infantry-hq')):
            both = {'deploy': [{'side': 'axis', 'nat': 'it', 'rule': '60.31', 'at': {'area': 'Libya'},
                                'units': [{'name': 'a', 'type': 'I', 'oa': first}, {'name': 'b', 'type': 'I', 'oa': second}]}]}
            both['deploy'][0]['units'][[first, second].index('it/ltc/ltc')]['training'] = True
            u = units('test', both, board(), {'turn': 2, 'stage': 1})['it/ltc/ix-l']
            self.assertEqual((u['attached'], u['parent']), ('it/2-libyan/2nd-libyan-infantry-hq', 'it/ltc/trvli'))
            # It comes with its own formation's listing, whichever is first
            self.assertEqual(u['listing'], [first, second].index('it/ltc/ltc'))

    def test_listing_fields_at_any_depth(self):
        def made(*listings, side='cw'):
            return units('test', {'deploy': [{'side': side, 'nat': 'uk', 'rule': 'x', 'at': {'area': 'x'},
                                              'units': [{'name': 'x', 'type': 'I', **x} for x in listings]}]},
                         board(), {'turn': 2, 'stage': 1})
        # A sheet with no HQ brings its counters, less one another listing names
        u = made({'oa': 'it/tobruk'}, {'oa': 'it/tobruk/tbrklt'}, side='axis')
        self.assertEqual((u['it/tobruk/tbrklt']['listing'], u['it/tobruk/31-gaf']['listing']), (1, 0))
        # An empty TOE is a TOE
        self.assertEqual(made({'oa': 'cw/7-armd/1-rtr', 'toe': []})['cw/7-armd/1-rtr']['toe'], [])
        # parts within parts; parent and training in a roster entry
        u = made({'oa': 'cw/7-armd/7th-armored-div-hq',
                  'parts': [{'oa': 'cw/7-armd/4', 'parts': [{'oa': 'cw/7-armd/6-rtr', 'toe': [{'w': 'cw/a13-cruiser', 'n': 2}]}]}],
                  'att': [{'oa': 'cw/6-aus/2-1-aus', 'parent': None, 'training': True}]})
        self.assertEqual(u['cw/7-armd/6-rtr']['toe'], [{'w': 'cw/a13-cruiser', 'n': 2}])
        self.assertEqual((u['cw/6-aus/2-1-aus']['parent'], u['cw/6-aus/2-1-aus']['morale']['current']), (None, -3))

    def test_strength_and_morale(self):
        u = self.units('crusader')
        # The tank tables (62.32), and a listing's own TOE (62.31)
        self.assertEqual(u['cw/7-armd/7-hus']['toe'], [{'w': 'cw/crusader-mk-i', 'n': 4},
                                                       {'w': 'cw/a13-cruiser', 'n': 3}, {'w': 'cw/a10-cruiser', 'n': 4}])
        self.assertEqual(u['cw/4-in/1-cih']['toe'], [{'n': 3}])
        self.assertEqual(u['gm/15-pz/33rd-artillery-regt']['toe'], [{'w': 'gm/15cm-sig33-medium-infantry-gun', 'n': 6}])
        u = self.units('graziani')
        self.assertEqual(u['cw/7-armd/1-rtr']['morale'], {'basic': 2, 'current': 2})
        # The 6th Australian Division is In Training: its units start untrained (60.41, 17.31)
        self.assertEqual(u['cw/6-aus/2-1-aus']['morale'], {'basic': 1, 'current': -3})

    def test_listings_with_no_hq(self):
        u = self.games['graziani']['units']
        tobruk = [x for x in u.values() if x['oa'] and x['oa'].startswith('it/tobruk/') and x['attached'] is None]
        self.assertEqual(len(tobruk), 13)
        self.assertEqual({x['loc']['id'] for x in tobruk}, {hex_loc('C4807')['id']})
        oasis = [x for x in self.units('last-chance') if x.startswith('gm/300-oasis/')]
        self.assertEqual(len(oasis), 4)  # "any four"
        lrdg = [x for x in self.units('race-for-tobruk').values() if x.get('kind') == 'raider']
        self.assertEqual(len(lrdg), 1)

    def test_an_attached_unit_moves_with_its_carrier(self):
        g, log = start('graziani')
        bn = 'cw/6-aus/2-1-aus'  # attached to its brigade, at Cairo or Helwan with its division
        with self.assertRaises(Refused) as r:
            give(g, log, 'cw', 'place-unit', unit=bn, loc=hex_loc('E1730'))
        self.assertEqual(r.exception.case, '4.25')
        give(g, log, 'cw', 'place-unit', unit='cw/6-aus/6-aus', loc=hex_loc('E1730'))
        self.assertEqual(oa.place(g, bn), hex_loc('E1730'))
        self.assertIsNone(g['units'][bn]['loc'])
        self.assertEqual(events.replay(log), g)


if __name__ == '__main__':
    unittest.main()
