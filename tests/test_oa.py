"""Units as the charts give them (cna/engine/oa.py), checked against the charts by hand."""
import unittest

from cna.engine import oa


def entry(ch, key, value):
    return next(x for x in ch['toe'] if x.get(key) == value)


class Unit(unittest.TestCase):
    def test_an_oa_entry_has_its_sheet_and_id_code(self):
        u = oa.unit('cw/7-armd/1-rtr')
        self.assertEqual((u['name'], u['code'], u['chart']), ('1st Royal Tank Regt', 'g', 'cw'))
        self.assertEqual(u['sheet']['id'], 'cw/7-armd')
        self.assertNotIn('units', u['sheet'])
        self.assertEqual(u['row']['type'], 'Tank Bn-Eq')
        self.assertEqual((u['nat'], u['morale']), ('uk', {'basic': 2}))  # the sheet's

    def test_a_unit_s_own_morale_stands_in_for_the_sheet_s(self):
        own = [u for u in oa.charts().units.values() if u['morale'] != u['sheet'].get('morale')]
        self.assertTrue(own)
        for u in own:
            self.assertIsNotNone(u['morale'], u['id'])

    def test_an_unknown_unit(self):
        with self.assertRaises(KeyError):
            oa.unit('cw/7-armd/no-such-unit')


class Characteristics(unittest.TestCase):
    def test_1_rtr(self):
        ch = oa.characteristics('cw/7-armd/1-rtr')
        self.assertEqual((ch['code'], ch['type'], ch['cpa'], ch['max_toe'], ch['points']), ('g', 'Tank Bn-Eq', 25, 10, 7))
        a9 = entry(ch, 'w', 'cw/a9-cruiser')
        self.assertEqual((a9['n'], a9['name'], a9['class']), (7, 'A9 Cruiser', 'tank'))
        self.assertEqual((a9['anti_armor'], a9['armor'], a9['assault_off'], a9['assault_def'], a9['bar']), (3, 1, 3, 3, 1))

    def test_the_slowest_weapons_system_gives_the_cpa(self):
        # 2 Bays: 8 Crusader I (CPA 25) and 2 A13 (CPA 30).
        ch = oa.characteristics('cw/1-armd/2-bays')
        self.assertEqual((ch['cpa'], ch['points']), (25, 10))
        self.assertEqual([(x['w'], x['n'], x['cpa']) for x in ch['toe']],
                         [('cw/crusader-mk-i', 8, 25), ('cw/a13-cruiser', 2, 30)])

    def test_an_hq_keeps_its_cpa_and_fights_its_tank_in_parentheses(self):
        # ID code b: CPA 30*, may assign (1) tank. The Stuart has CPA 35.
        ch = oa.characteristics('cw/1-armd/1')
        self.assertEqual((ch['cpa'], ch['max_toe'], ch['paren']), (30, 1, ['max_toe']))
        stuart = entry(ch, 'w', 'cw/stuart-m3')
        self.assertEqual(stuart['paren'], ['aa', 'anti_armor', 'assault_off', 'assault_def'])
        self.assertEqual(stuart['armor'], 3)

    def test_a_tank_battalion_of_us_tanks_only(self):
        # 9th Lancers: 10 Stuarts, over the maximum of 9 that such a battalion has
        # from "early 1942" (4.46), January 1942 (Game-Turn 63)
        jan_1942 = {'turn': 63, 'stage': 1}
        ch = oa.characteristics('cw/1-armd/9-lancr', jan_1942)
        self.assertEqual((ch['max_toe'], ch['points'], ch['cpa']), (9, 10, 35))
        for before in (None, {'turn': 62, 'stage': 3}):  # in Crusader, ten (62.32)
            self.assertEqual(oa.characteristics('cw/1-armd/9-lancr', before)['max_toe'], 10)
        # Not so with a British tank among them.
        mixed = oa.characteristics({'oa': 'cw/1-armd/9-lancr',
                                    'toe': [{'w': 'cw/stuart-m3', 'n': 8}, {'w': 'cw/a13-cruiser', 'n': 1}]}, jan_1942)
        self.assertEqual((mixed['max_toe'], mixed['cpa']), (10, 30))

    def test_a_unit_of_its_own_kind(self):
        # 11 Hus: U@6 of ID code ll, CPA 45, Armor 1, Close Assault 2/3, max 8.
        ch = oa.characteristics('cw/7-armd/11-hus')
        self.assertEqual((ch['type'], ch['cpa'], ch['max_toe'], ch['points']), ('Reconnaissance Battalion-Eq', 45, 8, 6))
        self.assertEqual(ch['toe'], [{'cpa': 45, 'armor': 1, 'assault_off': 2, 'assault_def': 3, 'n': 6}])

    def test_coastal_guns_firing_on_land(self):
        # 2nd Tobruk CD Arty Group: 6×(4) 100/17 and 6 'I' Light AA, emplaced.
        ch = oa.characteristics('it/tobruk/2-tbrkcd')
        self.assertEqual((ch['points'], ch['cpa'], ch['emplaced']), (12, 0, True))
        guns = entry(ch, 'w', 'it/100-17-howitzer')
        self.assertEqual((guns['n'], guns['land'], guns['barrage']), (6, 4, 8))
        self.assertTrue(entry(ch, 'w', 'it/i-light')['no_transport'])

    def test_points_of_another_id_code(self):
        # RECAM HQ (a: CPA 45, may assign (1) recce) with 1 point of vv.
        ch = oa.characteristics('it/recam/recam-hq')
        vv = entry(ch, 'code', 'vv')
        self.assertEqual((vv['type'], vv['n'], vv['cpa'], vv['armor']), ('Recce Bn-Eq', 1, 45, 1))
        self.assertEqual(vv['paren'], ['anti_armor', 'assault_off', 'assault_def'])
        self.assertEqual(vv['bar'], -1)  # its own ID code's, one column left
        self.assertEqual(ch['cpa'], 45)

    def test_ratings_that_change(self):
        # The 75/27's Anti-armor goes from 0 to 2 at Game-Turn 63.
        def anti_armor(at):
            return entry(oa.characteristics('it/maletti/1-maletti', at), 'w', 'it/75-27-gun')['anti_armor']
        self.assertEqual([anti_armor(None), anti_armor({'turn': 62, 'stage': 3}), anti_armor({'turn': 63, 'stage': 1})],
                         [0, 0, 2])
        self.assertNotIn('changes', entry(oa.characteristics('it/maletti/1-maletti'), 'w', 'it/75-27-gun'))

    def test_the_state_s_toe_stands_in_for_the_oa_one(self):
        ch = oa.characteristics({'oa': 'cw/7-armd/1-rtr', 'toe': [{'w': 'cw/a9-cruiser', 'n': 3}]})
        self.assertEqual((ch['points'], ch['oa']), (3, 'cw/7-armd/1-rtr'))
        self.assertEqual(oa.characteristics({'oa': 'cw/7-armd/1-rtr', 'toe': []})['cpa'], 25)  # the chart's

    def test_every_unit(self):
        for uid in oa.charts().units:
            ch = oa.characteristics(uid)
            self.assertEqual(ch['points'], sum(x['n'] for x in ch['toe']), uid)
            self.assertTrue(isinstance(ch['cpa'], int) or ch['open'] == ['cpa'], uid)


class Attached(unittest.TestCase):
    def state(self):
        hex_ = {'kind': 'hex', 'id': 'x'}
        return {'units': {
            'hq': {'id': 'hq', 'loc': hex_},
            'bde': {'id': 'bde', 'attached': 'hq', 'loc': None},
            'bn1': {'id': 'bn1', 'attached': 'bde', 'loc': None},
            'bn2': {'id': 'bn2', 'attached': 'hq', 'loc': None},
            'alone': {'id': 'alone', 'loc': {'kind': 'pool'}},
        }}

    def test_carried(self):
        s = self.state()
        self.assertEqual(oa.carried(s, 'hq'), [{'id': 'bde', 'carried': [{'id': 'bn1', 'carried': []}]},
                                               {'id': 'bn2', 'carried': []}])
        self.assertEqual(oa.carried(s, 'alone'), [])

    def test_place_follows_the_carrier(self):
        s = self.state()
        self.assertEqual(oa.place(s, 'bn1'), {'kind': 'hex', 'id': 'x'})
        self.assertEqual(oa.place(s, 'alone'), {'kind': 'pool'})
