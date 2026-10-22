"""A counter's TOE Log Sheet (4.52), for its owner only (cna/engine/logsheets.py)."""
import copy
import unittest

from cna.engine.commands import Refused
from cna.engine.logsheets import log_sheet
from tests.test_setup import hex_loc, start


def boxes(sheet, section):
    return [b['id'] for b in sheet[section]]


class LogSheet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.crusader = start('crusader')[0]
        cls.alamein = start('last-chance')[0]

    def test_counter_identity(self):
        s = log_sheet(self.alamein, 'cw', 'cw/7-armd/7th-armored-div-hq')['identity']
        self.assertEqual((s['name'], s['abbr'], s['morale'], s['eng'], s['division']),
                         ('7th Armored Div HQ', '7', {'basic': 2, 'current': 2}, True, True))
        self.assertEqual(s['loc'], hex_loc('E2302'))
        self.assertEqual(log_sheet(self.alamein, 'axis', 'gm/90-le/90-le')['identity']['parent'], None)
        s = log_sheet(start('graziani')[0], 'axis', 'it/tobruk/31-gaf')['identity']
        self.assertEqual(s['garrison'], 'C4807')

    def test_sections(self):
        """Crusader's 21st Panzer: its regiments and their units are Maneuver
        Elements, its other units Divisional Assets; the 3rd Aufklarungs Bn and
        the I/104, on counters of their own, are detached."""
        s = log_sheet(self.crusader, 'axis', 'gm/5-le/21')
        self.assertEqual(boxes(s, 'assets'), ['gm/5-le/39', 'gm/5-le/200'])
        self.assertEqual(boxes(s, 'maneuver')[:3], ['gm/5-le/5', 'gm/5-le/i-5', 'gm/5-le/ii-5'])
        detached = {b['id']: b['detached'] for b in s['maneuver'] if 'detached' in b}
        self.assertEqual(set(detached), {'gm/5-le/3', 'gm/15-pz/i-104'})
        self.assertEqual(detached['gm/5-le/3'], hex_loc('C4015'))
        self.assertEqual(s['augmentation'], [])
        tank = next(b for b in s['maneuver'] if b['id'] == 'gm/5-le/i-5')
        self.assertEqual((tank['under'], tank['characteristics']['points']), ('gm/5-le/5', 11))

    def test_augmentation(self):
        """Crusader's 7th Armoured Bde has the 4 RHA attached, assigned to the 7th
        Support Group (62.31)."""
        s = log_sheet(self.crusader, 'cw', 'cw/7-armd/7th-armored-bde-hq')
        self.assertEqual(boxes(s, 'augmentation'), ['cw/7-armd/4-rha'])
        self.assertEqual(boxes(s, 'maneuver'), ['cw/7-armd/7-hus', 'cw/7-armd/6-rtr', 'cw/uk-armor/2-rtr'])
        self.assertEqual(s['assets'], [])  # a brigade has no Divisional Assets
        # and the 7th Support Group's sheet has it detached
        s = log_sheet(self.crusader, 'cw', 'cw/7-armd/7-spt')
        self.assertIn('cw/7-armd/4-rha', [b['id'] for b in s['maneuver'] if 'detached' in b])

    def test_units_under_an_asset_are_assets(self):
        """A unit carried by one of a division's assets, and assigned to it, is in
        Divisional Assets with it, not in Maneuver Elements."""
        g = copy.deepcopy(self.crusader)
        g['units']['gm/gm-inf/708'].update(attached='gm/5-le/39', parent='gm/5-le/39')
        s = log_sheet(g, 'axis', 'gm/5-le/21')
        self.assertEqual(boxes(s, 'assets'), ['gm/5-le/39', 'gm/gm-inf/708', 'gm/5-le/200'])
        self.assertNotIn('gm/gm-inf/708', boxes(s, 'maneuver'))

    def test_the_formation_is_by_assignment(self):
        """A division's own unit carried by one of its regiments is a Maneuver
        Element, not Augmentation; an attached unit's own detached units are not
        the formation's."""
        g = copy.deepcopy(self.crusader)
        g['units']['gm/5-le/39'].update(attached='gm/5-le/5')  # still assigned to the 21st Panzer
        s = log_sheet(g, 'axis', 'gm/5-le/21')
        self.assertIn('gm/5-le/39', boxes(s, 'maneuver'))
        self.assertEqual(s['augmentation'], [])
        g = copy.deepcopy(self.crusader)
        g['units']['cw/7-armd/11-hus'].update(parent='cw/7-armd/4-rha')  # on its own counter
        s = log_sheet(g, 'cw', 'cw/7-armd/7th-armored-bde-hq')
        self.assertNotIn('cw/7-armd/11-hus', boxes(s, 'maneuver'))

    def test_a_parent_not_in_play(self):
        s = log_sheet(self.crusader, 'cw', 'cw/2-armd/32-army')['identity']
        self.assertEqual((s['parent'], s['parent_in_play']), ('2nd Armored Div HQ', False))

    def test_only_for_its_owner(self):
        for seat, uid in (('cw', 'gm/5-le/21'), ('axis', 'cw/7-armd/7-spt'), ('axis', 'gm/5-le/nothing'),
                          ('axis', ['gm/5-le/21'])):
            with self.assertRaises(Refused):
                log_sheet(self.crusader, seat, uid)
        self.assertTrue(log_sheet(self.crusader, 'referee', 'cw/7-armd/7-spt')['maneuver'])


if __name__ == '__main__':
    unittest.main()
