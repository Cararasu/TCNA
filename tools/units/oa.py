"""The Organization at Arrival Charts (4.45) as data: every land unit counter.

Usage (from the project folder, with the rulebook transcription present):
  python -I tools/units/oa.py [--check]

Reads "The Campaign for North Africa.md" and data/tables/ (tools/units/tables.py),
and writes data/units/oa-cw.json, oa-it.json and oa-gm.json: each chart's sheets
in printed order, each sheet's units with

  id        <chart>/<sheet>/<counter>: stable, for scenarios and saved games
  name      as the OA sheet gives it; abbr: the counter's abbreviation
  code      the ID code, in data/tables/units-<chart>.json
  parent    the unit it is assigned to, from the sheet's indentation (4.45)
  group     a heading on the sheet that has no counter of its own
  toe       TOE Strength Points on arrival: {n} for the unit's own kind, {w, n}
            for a weapons system (data/tables/weapons-*.json), {code, n} for
            points of another ID code; land: of n, how many may fire on land
  strength  'under' or 'over' (U@, O@)
  arrives   'D' (deployed at the start of the campaign), {turn, stage}, or
            None for counters that come into play otherwise
  morale    {basic, untrained}, where it differs from the sheet's
  note      the sheet's note letter(s) for the unit

and a sheet's refs: units that belong to another sheet but are listed on this
one too, because they arrive or start attached to its units.

FIXES correct the transcription and the printed chart, each with its reason.
--check lists anything that still doesn't fit.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RULEBOOK = ROOT / 'The Campaign for North Africa.md'
TABLES = ROOT / 'data' / 'tables'
OUT = ROOT / 'data' / 'units'

CHARTS = {'cw': r'\[4\.44B\] COMMONWEALTH ORGANIZATION', 'it': r'\[4\.44b\] ITALIAN ORGANIZATION',
          'gm': r'\[4\.45c\] GERMAN ORGANIZATION'}
NAMES = {'cw': 'Commonwealth', 'it': 'Italian', 'gm': 'German'}

# Sheet title (without its note letter) -> (id, nationality). The nationality
# is the counters' colour group (the CSS --n-* colours); the chart's own
# headings are out of place in the transcription for two of the sheets.
SHEETS = {
    'cw': {
        '1st Armored Division': ('1-armd', 'uk'), '2nd Armored Division': ('2-armd', 'uk'),
        '7th Armored Division': ('7-armd', 'uk'), '8th Armored Division': ('8-armd', 'uk'),
        '44th (Home Countries) Infantry Division': ('44-inf', 'uk'), '10th Armored Division': ('10-armd', 'uk'),
        '50th (Northumbrian) Infantry Division': ('50-inf', 'uk'), '1st Army Tank Brigade': ('1-army-tank', 'uk'),
        '51st (Highland) Infantry Division': ('51-inf', 'uk'), '70th Infantry Division': ('70-inf', 'uk'),
        '22nd Armored Brigade': ('22-armd', 'uk'), 'Selby Force/The Matruh Garrison': ('selby', 'uk'),
        '22nd Guards Brigade (200th Guards Brigade)': ('22-gds', 'uk'),
        'Unassigned Anti-tank Regiments': ('uk-at', 'uk'), 'Unassigned Armor-Class Units': ('uk-armor', 'uk'),
        'Unassigned British Infantry-type Units': ('uk-inf', 'uk'), 'Unassigned Artillery Units': ('uk-arty', 'uk'),
        'Unassigned Anti-aircraft Units': ('uk-aa', 'uk'),
        '6th Australian Division': ('6-aus', 'au'), '9th Australian Division': ('9-aus', 'au'),
        '18th Australian Brigade': ('18-aus', 'au'),
        '4th Indian Division': ('4-in', 'in'), '3rd Indian Motorized Brigade Group': ('3-in-mtr', 'in'),
        '5th Indian Division': ('5-in', 'in'), 'Unassigned Indian Units': ('in-other', 'in'),
        '10th Indian Division': ('10-in', 'in'), '18th Indian Brigade': ('18-in', 'in'),
        '161st Indian Motor Brigade': ('161-in-mtr', 'in'),
        '2nd New Zealand Division': ('2-nz', 'nz'), 'Unassigned New Zealand Units': ('nz-other', 'nz'),
        'Unassigned South Africa Units': ('sa-other', 'sa'), '1st South African Infantry Division': ('1-sa', 'sa'),
        '2nd South African Infantry Division': ('2-sa', 'sa'),
        '1st Free French Brigade': ('1-ff', 'fr'), '2nd Free French Brigade': ('2-ff', 'fr'),
        '1st Greek Infantry Brigade Group': ('1-greek', 'gr'), 'The Polish (Carpathian) Brigade': ('polish', 'pl'),
        'Unassigned Allied Units': ('allied-other', 'fr'),
    },
    'it': {
        '132nd "Ariete" Divisione Corazzata (Armored)': ('ariete', 'it'),
        '133rd "Littorio" Divisione Corazzata (Armored)': ('littorio', 'it'),
        '1st Libyan Infantry Division (Sibille)': ('1-libyan', 'it'),
        '2nd Libyan (Pescatori) Infantry Division': ('2-libyan', 'it'),
        'The Libyan Tank Command (Babini Gruppo Corazzato)': ('ltc', 'it'),
        '16th "Pistoia" Divison (Semi-motorized)': ('pistoia', 'it'),
        '60th "Sabratha" Division (Semi-motorized)': ('sabratha', 'it'), 'Gruppo Maletti': ('maletti', 'it'),
        '17th "Pavia" Division (Semi-motorized)': ('pavia', 'it'),
        '25th "Bologna" Division (Semi-motorized)': ('bologna', 'it'),
        '101st "Trieste" Division Fanteria Motorizzate': ('trieste', 'it'),
        '55th "Savona" Division (Semi-motorized)': ('savona', 'it'),
        '27th "Brescia" Division (Semi-motorized)': ('brescia', 'it'),
        '64th "Catanzaro" Division (Semi-motorized)': ('catanzaro', 'it'),
        '102nd "Trento" Divisione Fanteria Motorizzate': ('trento', 'it'),
        '136th "Giovani Fascisti" Divisione Fanteria': ('ggff', 'it'),
        '185th "Folgore" Division': ('folgore', 'it'),
        'Raggruppamento Esplorante del Corpo Di Manovra': ('recam', 'it'),
        'The Saharan Detachment': ('saharan', 'it'),
        'Benghazi Garrison': ('benghazi', 'it'), 'The Tobruk Garrison': ('tobruk', 'it'),
        'Bardia Garrison': ('bardia', 'it'), 'Derna Garrison': ('derna', 'it'),
        'Giariabub Oasis Complex Garrison': ('giarabub', 'it'), 'Minor Garrison Units': ('minor-garrisons', 'it'),
        'Unassigned Armored Units': ('it-armor', 'it'),
        'Assigned Units without a Parent Formation': ('it-no-parent', 'it'),
        'Unassigned Infantry and Reconnaissance Units': ('it-inf', 'it'),
        'Unassigned Gun Units': ('it-guns', 'it'),
        '2nd CCNN ("28th October") Division': ('2-ccnn', 'it'), '1st CCNN ("23rd March") Division': ('1-ccnn', 'it'),
        '3rd CCNN ("21st April") Division': ('3-ccnn', 'it'), '4th CCNN ("3 January") Division': ('4-ccnn', 'it'),
        'Unassigned Blackshirt Units': ('ccnn-other', 'it'),
        '61st "Sirte" Division (Semi-motorized)': ('sirte', 'it'),
        '62nd "Marmarica" Division (Semi-motorized)': ('marmarica', 'it'),
        '63rd "Cirene" Division (Semi-motorized)': ('cirene', 'it'),
    },
    'gm': {
        '5th Light ("Leichte") Panzer Division': ('5-le', 'de'), 'Sonderverband 288': ('288', 'de'),
        '15th Panzer Division': ('15-pz', 'de'), '300th Oasis Battalion': ('300-oasis', 'de'),
        '164th Light Afrika Division': ('164-le', 'de'), 'Fallschirmjaeger-Brigade Ramcke': ('ramcke', 'de'),
        'Unassigned Infantry Units': ('gm-inf', 'de'), "Kampfgruppen HQ's": ('kampfgruppen', 'de'),
        'Non-Divisional Artillery Units': ('gm-arty', 'de'), 'Unassigned Anti-Air Units': ('gm-aa', 'de'),
        '90th Light ("The Afrika") Division': ('90-le', 'de'),
    },
}
# Sheets with no counters: "There are no counters provided for these groups."
NO_COUNTERS = {'Italian Battle Groups'}

# Sheets printed without a table: their counters, from the sheet's text.
HAND = {
    'selby': [{'name': 'Matruh Garrison HQ (Selby Force)', 'abbr': None, 'code': 'a', 'toe': [], 'arrives': 'D'}],
    '22-gds': [{'name': '22nd Guards Bde HQ', 'abbr': '22 Gds', 'code': 'a', 'toe': [],
                'arrives': {'turn': 21, 'stage': 3}},  # "formed in February 1941 (3/21)"
               {'name': '200th Guards Bde HQ', 'abbr': '200 Gds', 'code': 'a', 'toe': [],
                'arrives': {'turn': 63, 'stage': 1}}],  # "In January 1942, it became the 200th"
    # The sheet names fourteen; the six in italics have counters. Formed in play.
    'kampfgruppen': [{'name': f'Kampfgruppe {n}', 'abbr': n, 'code': 'b', 'toe': [], 'arrives': None, 'formed': True}
                     for n in ('Bach', 'Graf', 'Knabe', 'Marcks', 'Pfeiffer', 'Schwrn')],
}

# The OA sheets the rulebook left out, printed in the addenda (September 1979,
# [4.44b] 1: "The OA sheets for three entire Italian Divisions - Sirte, Cirene
# and Marmarica - have been left out"), transcribed from the scan in the
# rulebook transcription's format. They follow the Italian chart's sheets.
ADDENDA = '''
### [4.44b] ITALIAN ORGANIZATION AT ARRIVAL CHART (addenda)

#### 61st "Sirte" Division (Semi-motorized)

Basic Morale: –1

| Notes | Unit | Counter Abbreviation | ID Code | TOE & Weapon System(s) | Arrives |
|---|---|---|---|---|---|
|  | 61st Sirte Div HQ | 61 Srt | b | N | 3/10 |
|  | › 69th Infantry Regt HQ | 69 | h | 1×65/17 Gun | 3/10 |
|  | › › I/69 Infantry Bn | I/69 | u | N | 3/10 |
|  | › › II/69 Infantry Bn | II/69 | u | N | 3/10 |
|  | › › III/69 Infantry Bn | III/69 | u | N | 3/10 |
|  | › 70th Infantry Regt HQ | 70 | h | 1×65/17 Gun | 3/10 |
|  | › › I/70 Infantry Bn | I/70 | u | N | 3/10 |
|  | › › II/70 Infantry Bn | II/70 | u | N | 3/10 |
|  | › › III/70 Infantry Bn | III/70 | u | N | 3/10 |
|  | › 61st Machinegun Bn | 61 | bb | N | 3/10 |
|  | › 61st Anti-tank Coy | 61 | rr | 2×47/32 Gun | 3/10 |
|  | › 43rd Artillery Regt | 43 | kk | 6×75/27 Gun, 3×100/17 Howitzer, 6×Light AA | 3/10 |
|  | › 61st Engineer Bn | 61 | bbb | N | 3/10 |
|  | › 61st Bersaglieri Mitrg Coy | 61 Brs | aaa | N | 3/10 |

#### 62nd "Marmarica" Division (Semi-motorized)

Basic Morale: –1

| Notes | Unit | Counter Abbreviation | ID Code | TOE & Weapon System(s) | Arrives |
|---|---|---|---|---|---|
|  | 62nd Marmarica Div HQ | 62 Mrm | b | N | D |
|  | › 115th Infantry Regt HQ | 115 | h | 1×65/17 Gun | D |
|  | › › I/115 Infantry Bn | I/115 | u | N | D |
|  | › › II/115 Infantry Bn | II/115 | u | N | D |
|  | › › III/115 Infantry Bn | III/115 | u | N | D |
|  | › 116th Infantry Regt HQ | 116 | h | 1×65/17 Gun | D |
|  | › › I/116 Infantry Bn | I/116 | u | N | D |
|  | › › II/116 Infantry Bn | II/116 | u | N | D |
|  | › › III/116 Infantry Bn | III/116 | u | N | D |
|  | › 62nd Machinegun Bn | 62 | bb | N | D |
|  | › 62nd Anti-tank Coy | 62 | rr | 2×47/32 Gun | D |
|  | › 44th Artillery Regt | 44 | kk | 6×75/27 Gun, 3×105/28 Gun, 3×Light AA | D |
|  | › 62nd Engineer Bn | 62 | bbb | N | D |
| a | › LXII(L) Tank Bn | LXII(L) |  |  | D |

#### 63rd "Cirene" Division (Semi-motorized)

Basic Morale: –1

| Notes | Unit | Counter Abbreviation | ID Code | TOE & Weapon System(s) | Arrives |
|---|---|---|---|---|---|
|  | 63rd Cirene Div HQ | 63 Cir | b | N | D |
|  | › 157th Infantry Regt HQ | 157 | h | 1×65/17 Gun | D |
|  | › › I/157 Infantry Bn | I/157 | u | N | D |
|  | › › II/157 Infantry Bn | II/157 | u | N | D |
|  | › › III/157 Infantry Bn | III/157 | u | N | D |
|  | › 158th Infantry Regt HQ | 158 | h | 1×65/17 Gun | D |
|  | › › I/158 Infantry Bn | I/158 | u | N | D |
|  | › › II/158 Infantry Bn | II/158 | u | N | D |
|  | › › III/158 Infantry Bn | III/158 | u | N | D |
|  | › 63rd Machinegun Bn | 63 | bb | N | D |
|  | › 63rd Anti-tank Coy | 63 | rr | 2×47/32 Gun | D |
|  | › 45th Artillery Regt | 45 | kk | 6×75/18 Gun-Howitzer, 3×100/17 Howitzer, 3×Light AA | D |
|  | › 63rd Engineer Bn | 63 | bbb | N | D |
|  | › 63rd Bersaglieri Mitrg Coy | 63 Brs | aaa | N | D |
| a | › LXIII(L) Tank Bn | LXIII(L) |  |  | D |
'''

# Units a set-up deploys that no OA sheet lists, as rows added to a sheet's
# table: (notes, unit, abbreviation, ID code, TOE, arrives). They are stand-ins,
# not rulebook data.
STAND_INS = {
    # Alamein (63.41) deploys an "XXIV Cp Arty", which was at el Alamein. Its
    # equipment was much like the XXV's, whose ratings it takes. It arrives by
    # no schedule: only the set-up brings it into play.
    'it-guns': [('(0)', 'XXIV Corps Artillery Regt', 'XXIV Cp', 'kk', '9×105/28 Gun, 3×Light AA', '')],
}

# (sheet, unit name as printed) -> {column: value as it should read}
FIXES = {
    ('70-inf', '1st Durham Light Inf'): {'code': 'm'},  # "M"
    ('70-inf', '1st Argyll & Sutherland'): {'arrives': 'D'},  # "d"
    ('90-le', 'II/155 Schutzen Bn'): {'code': 'k'},  # "K"
    ('bardia', '8th Gaf S di C Arty Regt'): {'code': 'll'},  # "11": ll is the artillery code that fits
    ('bardia', '9th Gaf S di C Arty Regt'): {'code': 'll'},
    ('bardia', '10th Gaf S di C Arty Regt'): {'code': 'll'},
    # Printed x, the anti-tank battalion code, for a battery of one 17cm gun;
    # the 364 Artillery Bty, the same, is w (one artillery TOE). The addenda
    # ([4.44b] 6) correct it too, to the artillery code; they name the codes
    # the other way round from the transcription's chart.
    ('gm-arty', '362 Artillery Bty'): {'code': 'w'},
    ('allied-other', '1st Company, Fr Mtr Marine'): {'arrives': 'D'},  # the addenda, [4.44b] 3; printed 3/65
    # There was no XXVI Corps in North Africa; the XVI's artillery was there,
    # with much the same equipment. The set-ups' "XXVI Cp" are this unit too.
    ('it-guns', 'XXVI Corps Artillery Regt'): {'name': 'XVI Corps Artillery Regt', 'abbr': 'XVI Cp'},
    ('1-sa', 'DEO Rifles'): {'abbr': 'DEORfl'},  # "DEORf1"
    ('1-sa', 'Natal Mounted Rifles'): {'abbr': 'NtlMRfl'},  # "Nt1MRf1"
    ('2-sa', '2nd S. African Police'): {'abbr': '2 SA Plc'},  # printed "1 SA Plc", as the 1st
    ('gm-arty', 'I/722 Artillery Bty'): {'abbr': 'I/722'},  # "I/722*": the counter misprints it 1/772
    # The sheet prints no ID codes for the unassigned tank battalions: light
    # (CV33) battalions are k and medium (M13/40) battalions l, as everywhere
    # else in the chart (the Libyan Tank Command, Ariete, Littorio).
    **{('it-armor', n): {'code': 'k'} for n in ('I(L) Tank Bn', 'II(L) Tank Bn')},
    **{('it-armor', n): {'code': 'l'} for n in ('III(M) Tank Bn', 'IV(M) Tank Bn', 'V(M)TankBn', 'XIII(M) Tank Bn',
                                                 'XXI(M) Tank Bn', 'LI(M) Tank Bn', 'LII(M) Tank Bn')},
    ('it-armor', 'V(M)TankBn'): {'code': 'l', 'name': 'V(M) Tank Bn'},
    # Counters that take over another's TOE (sheet notes): no TOE of their own
    ('5-le', '21st Panzer Div HQ'): {'toe': '–'},  # "(b)": the 5th Light HQ's
    ('gm-arty', 'II/155 Artillery Bn'): {'toe': '–'},  # note e: the I/75's, on reassignment
}

# Counters that replace another (by unit name on each sheet), from the sheets' notes.
REPLACES = {
    ('5-le', '21st Panzer Div HQ'): ('5-le', '5th Light Panzer Div HQ'),  # 2/58, note a
    ('gm-arty', 'II/155 Artillery Bn'): ('5-le', 'I/75 Artillery Bn'),  # note e; no date: on reassignment
    ('2-armd', '32nd Army Tank Bde HQ'): ('2-armd', '3rd Armored Bde HQ'),  # note c
    ('7-armd', '7th Motor Bde HQ'): ('7-armd', '7th Support Group HQ'),  # note c
    ('22-gds', '200th Guards Bde HQ'): ('22-gds', '22nd Guards Bde HQ'),
    ('uk-arty', '11th Royal Horse Arty Regt'): ('1-armd', '11th Royal Horse Arty'),  # note b: refitted with Bishops
}
NO_ARRIVAL = {('gm-arty', 'II/155 Artillery Bn')}
# Counters that take over the TOE of the counter they replace (sheet notes).
TAKES_TOE = {('5-le', '21st Panzer Div HQ'), ('gm-arty', 'II/155 Artillery Bn')}

# Rows that list a unit of another sheet, by its name there where it differs.
REFS = {('1-ccnn', 'I(M) Tank Battalion'): ('ltc', 'I(M) Tank Bn')}

MORALE = {('9-aus', '20th Australian Inf Bde HQ'): {'basic': 1, 'untrained': 0}}  # note a: "arrives with an untrained morale of zero"
NAT = {('allied-other', '11th Czech Bn'): 'cz'}
GARRISONS = {'Scfzrn': 'C3419', 'FtMad': 'C3019', 'EGUG': 'C1715', 'Benina': 'A4829', 'Mechili': 'B4921',
             'Soluch': 'A4130'}  # Minor Garrison Units: "Garrison Locations"
# Sheet notes that change a unit's characteristics: (sheet, note) -> fields
NOTE_FIELDS = {('trieste', 'b'): {'motorized': True}, ('trento', 'b'): {'motorized': True}}  # "should read 10+"

# Weapons systems as the OA sheets spell them -> the characteristics charts' entries
ALIASES = {
    'cw': {
        '105mm howitzer (spa)': 'cw/105mm-sp-howitzer', '155mm howitzer': 'cw/155mm-howitzer',
        '18-pounder': 'cw/18-pounder-gun', '18/25-pounder': 'cw/18-25-pounder-gun', '2-pounder': 'cw/2-pounder',
        '25-pounder': 'cw/25-pounder-gun', '3.7" howitzer': 'cw/3-7-howitzer', '4.5" gun': 'cw/4-5-gun',
        '4.5" howitzer': 'cw/4-5-howitzer', '5.5" gun-howitzer': 'cw/5-5-gun-howitzer', '6-pounder': 'cw/6-pounder',
        '60-pounder': 'cw/60-pounder-gun', '6o-pounder': 'cw/60-pounder-gun', '6" howitzer': 'cw/6-howitzer',
        'a10': 'cw/a10-cruiser', 'a10 cruiser': 'cw/a10-cruiser', 'a13': 'cw/a13-cruiser',
        'a13 cruiser': 'cw/a13-cruiser', 'a9': 'cw/a9-cruiser', 'a9 cruiser': 'cw/a9-cruiser',
        'a9cruiser': 'cw/a9-cruiser', 'crusader i': 'cw/crusader-mk-i', 'crusader mk i': 'cw/crusader-mk-i',
        'crusader mk ii': 'cw/crusader-mk-ii', 'grant': 'cw/grant-m3', 'heavy aa': 'cw/heavy-aa-3-7',
        'light aa': 'cw/light-aa-bofors-40mm', 'mark vi light': 'cw/mark-vi-light', 'mk vi light': 'cw/mark-vi-light',
        'matilda': 'cw/matilda-mk-ii', 'sp 25-pounder': 'cw/sp-25-pounder-gun', 'stuart': 'cw/stuart-m3',
        'valentine': 'cw/valentine-mk-ii',
        'french 149mm (see it. arty)': 'it/149mm-vichy-french',
    },
    'it': {
        "'i' heavy aa": 'it/i-heavy', "'i' light aa": 'it/i-light',
        '100/17 howitzer': 'it/100-17-howitzer', '100/17 howtizer': 'it/100-17-howitzer',
        '105/28 gun': 'it/105-28-gun', '149/13 howitzer': 'it/149-13-howitzer',
        '149mm vichy french gun': 'it/149mm-vichy-french', '47/32': 'it/47-32-mod-37', '47/32 gun': 'it/47-32-mod-37',
        '65/17': 'it/65-17-gun', '65/17 gun': 'it/65-17-gun', '75/18 gun howitzer': 'it/75-18-gun-howitzer',
        '75/18 gun-howitzer': 'it/75-18-gun-howitzer', '75/18 gun-howtizer': 'it/75-18-gun-howitzer',
        '75/18 sp gun': 'it/75-18-gun', 'semovente 75/18 sp gun': 'it/75-18-gun', '75/27 gun': 'it/75-27-gun',
        '75/46 aa gun': 'it/heavy-75-46-mod-34',
        'heavy aa': 'it/heavy-75-46-mod-34',  # 4.46b note 4
        'light aa': 'it/light-20mm-m-35-breda', 'cv33': 'it/cv-33-l3-35', 'l6/40': 'it/l-6-40',
        'm11/39': 'it/m-11-39', 'm13/40': 'it/m-13-40', 'm14/41': 'it/m14-41', 'paraart': 'it/paraart',
    },
    'gm': {
        '10.5cm lt field howitzer': 'gm/10-5cm-lefh18-light-field-howitzer', '10.5cm med gun': 'gm/10-5cm-k18-medium-gun',
        '155mm (fr. 1915 short)': 'gm/155mm-french-1915short', '15cm gun': 'gm/15cm-k18-gun',
        # "Med(ium)" is the chart's word for schwere: the 10.5cm(K18) is its "Medium Gun",
        # and the 15cm(K18) its only 15cm gun
        '15cm med gun': 'gm/15cm-k18-gun',
        '15cm med field howitzer': 'gm/15cm-sfh18-medium-field-howitzer',
        '15cm med inf gun': 'gm/15cm-sig33-medium-infantry-gun', '15cm sp gun': 'gm/15cm-sp-gun',
        '17cm gun': 'gm/17cm-k18-gun', '21cm how': 'gm/21cm-mrs18-howitzer', '21cm howitzer': 'gm/21cm-mrs18-howitzer',
        '3.7cm': 'gm/3-7cm-pak-35-36', '5cm': 'gm/5cm-pak-38',
        '7.5cm lt gun': 'gm/7-5-cm-ig18-light-infantry-gun', '7.5cm lt inf gun': 'gm/7-5-cm-ig18-light-infantry-gun',
        'heavy aa': 'gm/heavy-88mm-flak', 'light aa': 'gm/light-20mm-37mm-flak',
        'pzi': 'gm/pz-i', 'pzii': 'gm/pz-ii', 'pziiie': 'gm/pz-iii-e', 'pziiih': 'gm/pz-iii-h',
        'pzivd': 'gm/pz-iv-d', 'pzive': 'gm/pz-iv-e', 'pzjgi': 'gm/pzjg-1-sp',
    },
}
# Arrival TOE above the ID code's maximum, as printed (4.46: "may be exceeded
# only due to the unit's arrival/deployment TOE Strength").
OVER_MAX = {'it/ariete/132', 'it/trento/102nd-anti-tank-bn', 'it/saharan/saharan-artillery-battery',
            'cw/1-armd/9-lancr',  # 10 Stuarts, where a battalion of US tanks only has nine
            'it/sirte/43'}  # 6×75/27, 3×100/17 and 6×Light AA in the addenda
# Weapons systems on an ID code that may not be assigned them, as printed.
OTHER_CLASS = {('it/folgore/186', 'anti-tank'), ('it/folgore/187', 'anti-tank'),  # 1×47/32 on an artillery HQ
               ('it/saharan/saharan-artillery-battery', 'light-aa')}
# Rows that are not land units.
SKIP = {('tobruk', 'The San Giorgio')}  # a cruiser sunk in the harbor (note c); it comes with the fleet (30.0)

HEADING = re.compile(r'^(#{2,4}) (.*)')
MORALE_LINE = re.compile(r'^\**Basic Morale:\s*(.*?)\**$')
VALUE = r'([+–-]?\d)'


FIXED = set()  # the FIXES applied, to find those that name nothing


class Bad(ValueError):
    pass


def slug(s):
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')


def number(s):
    return int(s.replace('–', '-'))


def clean_title(raw):
    """'Benghazi Garrison (Hex: A4827) (a)' -> ('Benghazi Garrison', 'A4827', 'a')."""
    t = re.sub(r'\s*\*\(.*?\)\*', '', raw).strip()
    note = None
    m = re.search(r'\s*\(([a-z])\)$', t)
    if m:
        note, t = m.group(1), t[:m.start()]
    hex_ = None
    m = re.search(r'\s*\(Hex: ([A-E])\s*(\d{4})\)', t)
    if m:
        hex_, t = m.group(1) + m.group(2), t[:m.start()] + t[m.end():]
    return t.strip(), hex_, note


def sheet_morale(text):
    """'+2 (+1)' -> {'basic': 2, 'untrained': 1}; 'None ...', 'That of ...', 'As listed ...' -> None."""
    m = re.match(VALUE + r'(?:\s*\(' + VALUE + r'\))?', text)
    if not m:
        return None
    out = {'basic': number(m.group(1))}
    if m.group(2):
        out['untrained'] = number(m.group(2))
    return out


def read_charts(lines):
    """chart -> its sheets: {'title', 'line', 'morale', 'code', 'rows'}."""
    out, chart, sheet = {}, None, None
    for i, line in enumerate(lines, 1):
        m = HEADING.match(line)
        if m:
            start = next((c for c, pat in CHARTS.items() if re.search(pat, line)), None)
            if start:
                chart, sheet = start, None
                out[chart] = []
                continue
            if chart and re.search(r'\[4\.4[5-9][a-c]?\]', line):
                chart = sheet = None  # the next chart
                continue
            if chart and m.group(1) == '####':
                sheet = {'title': m.group(2).strip(), 'line': i, 'morale': None, 'morale_text': None,
                         'code': None, 'rows': []}
                out[chart].append(sheet)
            continue
        if sheet is None:
            continue
        s = line.strip()
        mm = MORALE_LINE.match(s)
        if mm and sheet['morale_text'] is None:
            sheet['morale_text'] = mm.group(1)
            c = re.search(r'ID Code: (\w+)', s)
            if c:
                sheet['code'] = c.group(1)
        elif re.match(r'^ID Code: (\w+)$', s):
            sheet['code'] = s.split(': ')[1]
        elif s.startswith('|') and not s.startswith('|---') and 'Counter Abbreviation' not in s:
            sheet['rows'].append((i, [c.strip() for c in s.strip('|').split('|')]))
    return out


def weapon(chart, name, tables):
    key = re.sub(r'\s+', ' ', name.lower().replace('″', '"')).strip()
    for k in (key, key[:-1] if key.endswith('s') else key, key.replace(' ', '')):
        w = ALIASES[chart].get(k)
        if w:
            nat, ws = w.split('/')
            if ws not in tables['weapons'][nat]:
                raise Bad(f'{name!r} -> {w}, which is not in data/tables/weapons-{nat}.json')
            return w
    raise Bad(f'no weapons system for {name!r}')


def rated(entry):
    """Whether an ID code has combat ratings of its own, besides what it may be assigned."""
    return bool(set(entry) & {'aa', 'barrage', 'anti_armor', 'vulnerability', 'armor', 'assault_off', 'assault_def'})


def parse_toe(chart, cell, code, tables):
    """The TOE column -> (toe, strength)."""
    codes = tables['units'][chart]
    if cell in ('', '–', '-'):
        return [], None
    m = re.fullmatch(r'([UO])@\s*(\d+)(?:\s*TOE)?', cell)
    if m:
        return [{'n': int(m.group(2))}], {'U': 'under', 'O': 'over'}[m.group(1)]
    own = []
    m = re.fullmatch(r'N(?:\s*\+\s*(.+))?', cell)
    if m:
        entry = codes[code]
        if rated(entry) or not entry.get('may_assign'):
            # Points of the unit's own kind; a German h battalion has seven, and may be
            # assigned an artillery point besides ("N+1×7.5cm Lt Gun")
            if 'max_toe' in entry:
                own = [{'n': entry['max_toe']}]
        elif entry['type'] != 'Headquarters':
            raise Bad(f'"N" for ID code {code}, whose TOE is weapons systems')
        # else an HQ that may be assigned weapons systems, with none
        if not m.group(1):
            return own, None
        cell = m.group(1)
    toe = []
    for piece in re.split(r'\s*(?:,|&|\band\b)\s*', cell):
        for part in re.split(r'\s+(?=\d+\s*[×xX])', piece.strip()):
            p = re.fullmatch(r'(\d+)\s*[×xX]?\s*(?:\((\d+)\)\s*)?(.+)', part.strip())
            if not p:
                raise Bad(f'cannot read the TOE {cell!r}')
            n, land, name = int(p.group(1)), p.group(2), p.group(3).strip()
            if name in codes:  # TOE points of another ID code ("1×vv")
                toe.append({'code': name, 'n': n})
                continue
            entry = {'w': weapon(chart, name, tables), 'n': n}
            if land:
                entry['land'] = int(land)
            toe.append(entry)
    return own + toe, None


def parse_arrives(cell):
    if cell.upper() == 'D':
        return 'D'
    m = re.fullmatch(r'(\d)/(\d+)', cell)
    if m:
        return {'turn': int(m.group(2)), 'stage': int(m.group(1))}
    if cell == '':
        return None
    raise Bad(f'cannot read the arrival {cell!r}')


def parse_notes(cell):
    """'b(–2)' -> ('b', {'basic': -2}); '(+1)' -> (None, {'basic': 1}); 'a' -> ('a', None)."""
    m = re.fullmatch(r'([a-z,&]*)\s*(?:\(' + VALUE + r'\))?', cell)
    if not m:
        raise Bad(f'cannot read the notes column {cell!r}')
    return m.group(1) or None, ({'basic': number(m.group(2))} if m.group(2) else None)


def read_sheet(chart, sheet, tables, problems):
    """One sheet -> (units, refs to resolve, groups)."""
    sid, nat = SHEETS[chart][sheet['clean']]
    codes = tables['units'][chart]
    rows, stack = [], {}
    if sid in HAND:
        for h in HAND[sid]:
            rows.append({**h, 'depth': 0, 'parent': None, 'group': None, 'note': None, 'morale': None, 'kind': 'unit'})
    for line, cells in sheet['rows'] + [(None, list(r)) for r in STAND_INS.get(sid, ())]:
        where = f'{chart} {sid} line {line}' if line else f'{chart} {sid} stand-in'
        if len(cells) != 6:
            problems.append(f'{where}: a row with {len(cells)} cells')
            continue
        notes, unit, abbr, code, toe, arrives = cells
        depth = unit.count('›')
        name = unit.replace('›', '').strip()
        eng = '<sup>E</sup>' in name
        name = name.replace('<sup>E</sup>', '').strip()
        if (sid, name) in SKIP:
            continue
        fix = FIXES.get((sid, name), {})
        if fix:
            FIXED.add((sid, name))
        name, abbr = fix.get('name', name), fix.get('abbr', abbr.replace('\\*', '').strip().strip('"'))
        code, toe, arrives = fix.get('code', code), fix.get('toe', toe), fix.get('arrives', arrives)
        try:
            note, morale = parse_notes(notes)
        except Bad as e:
            problems.append(f'{where}: {e}')
            continue
        parent = stack.get(depth - 1) if depth else None
        row = {'name': name, 'abbr': abbr or None, 'depth': depth, 'note': note, 'morale': morale,
               'line': line, 'up': parent}
        if not abbr and not code and not toe and not arrives:
            row['kind'] = 'group'
        elif not code and not toe:
            row['kind'] = 'ref'
            row['arrives'] = parse_arrives(arrives)
        else:
            row['kind'] = 'unit'
            if code not in codes:
                problems.append(f'{where}: {name}: ID code {code!r} is not in the {NAMES[chart]} chart')
                continue
            row['code'] = code
            try:
                row['toe'], row['strength'] = parse_toe(chart, toe, code, tables)
                row['arrives'] = parse_arrives(arrives)
            except Bad as e:
                problems.append(f'{where}: {name}: {e}')
                continue
            row['eng'] = eng
            row['standin'] = line is None
        if REPLACES.get((sid, name), (None,))[0] != sid:
            # A counter that replaces another printed above it (21st Panzer HQ after the 5th
            # Light's) is not the parent of the rows that follow: they stay under the first
            stack[depth] = row
            for d in [d for d in stack if d > depth]:
                del stack[d]
        rows.append(row)
    return sid, nat, rows


def effective(row, sheet_morale_):
    while row is not None:
        if row.get('morale'):
            return row['morale']
        row = row.get('up')
    return sheet_morale_


def build(found, tables):
    problems, out = [], {}
    names = {}  # (sheet id, name) -> unit id, for REPLACES and REFS
    for chart, sheets in found.items():
        known = SHEETS[chart]
        seen = set()
        out[chart] = []
        for sheet in sheets:
            title, hex_, note = clean_title(sheet['title'])
            sheet['clean'] = title
            if title in NO_COUNTERS:
                continue
            if title not in known:
                problems.append(f'{chart} line {sheet["line"]}: an unknown sheet {title!r}')
                continue
            seen.add(title)
            morale = sheet_morale(sheet['morale_text'] or '')
            sid, nat, rows = read_sheet(chart, sheet, tables, problems)
            units = [r for r in rows if r['kind'] == 'unit']
            # ids: the counter's abbreviation, or for counters whose abbreviation another on the
            # sheet shares, their name
            base = [slug(u['abbr'] or u['name']) for u in units]
            dup = {b for b in base if base.count(b) > 1}
            ids = [slug(u['name']) if b in dup else b for u, b in zip(units, base)]
            for k, i in enumerate(ids):
                if ids.count(i) > 1:
                    problems.append(f'{chart} {sid}: two counters would have the id {i}')
            for u, i in zip(units, ids):
                u['id'] = f'{chart}/{sid}/{i}'
                names[(sid, u['name'])] = u['id']
            out[chart].append({'id': f'{chart}/{sid}', 'title': title, 'nat': nat, 'morale': morale,
                               'garrison': hex_, 'note': note, 'rows': rows, 'sheet': sheet})
        for title in set(known) - seen:
            problems.append(f'{chart}: the sheet {title!r} is not in the transcription')
    # Second pass: parents, refs, replacements, morale; now that every id is known
    for chart, sheets in out.items():
        for s in sheets:
            sid = s['id'].split('/')[1]
            for r in s['rows']:
                if r['kind'] == 'ref':
                    r['id'] = names.get(REFS.get((sid, r['name']), (None, None))) or next(
                        (i for (sh, n), i in names.items() if n == r['name'] and sh != sid), None)
                    if r['id'] is None:
                        problems.append(f'{chart} {sid}: {r["name"]} is listed without an ID code or TOE, '
                                        f'and is on no other sheet')
            units, refs = [], []
            for r in s['rows']:
                up = r.get('up')
                group = None
                while up is not None and up['kind'] == 'group':
                    group = group or up['name']
                    up = up.get('up')
                parent = up['id'] if up is not None else None
                if r['kind'] == 'ref':
                    if r['id']:
                        refs.append({'unit': r['id'], 'parent': parent, 'arrives': r['arrives'], 'note': r['note']})
                    continue
                if r['kind'] != 'unit':
                    continue
                u = {'id': r['id'], 'name': r['name'], 'abbr': r['abbr'], 'code': r['code']}
                if parent:
                    u['parent'] = parent
                if group:
                    u['group'] = group
                u['toe'] = r['toe']
                if r.get('strength'):
                    u['strength'] = r['strength']
                u['arrives'] = r['arrives']
                m = MORALE.get((sid, r['name'])) or effective(r, s['morale'])
                if m != s['morale']:
                    u['morale'] = m
                if r.get('note'):
                    u['note'] = r['note']
                if r.get('eng'):
                    u['eng'] = True
                if (sid, r['name']) in NAT:
                    u['nat'] = NAT[(sid, r['name'])]
                if sid == 'minor-garrisons' and r['abbr'] in GARRISONS:
                    u['garrison'] = GARRISONS[r['abbr']]
                for letter in (r.get('note') or '').replace('&', ',').split(','):
                    u.update(NOTE_FIELDS.get((sid, letter), {}))
                if (sid, r['name']) in REPLACES:
                    target = names.get(REPLACES[(sid, r['name'])])
                    if target is None:
                        problems.append(f'{chart} {sid}: {r["name"]} replaces {REPLACES[(sid, r["name"])]}, '
                                        f'which is not a unit')
                    else:
                        u['replaces'] = target
                        if (sid, r['name']) in TAKES_TOE:
                            u['takes_toe'] = True
                if r.get('formed'):
                    u['formed'] = True
                if r.get('standin'):
                    u['standin'] = True
                if u['arrives'] is None and not u.get('formed') and not u.get('standin') \
                        and (sid, r['name']) not in NO_ARRIVAL:
                    problems.append(f'{chart} {u["id"]}: no arrival')
                check_toe(chart, u, tables, problems)
                units.append(u)
            s['units'], s['refs'] = units, refs
            for k in ('rows', 'sheet'):
                del s[k]
            for k in ('morale', 'garrison', 'note'):
                if s[k] is None:
                    del s[k]
    for key in REPLACES:
        if key not in names:
            problems.append(f'REPLACES names {key}, which is not a unit')
    for key in set(FIXES) - FIXED:
        problems.append(f'FIXES name {key}, which is not on the sheet')
    return out, problems


def check_toe(chart, u, tables, problems):
    """Weapons systems the ID code may be assigned, and the arrival TOE against its maximum."""
    entry = tables['units'][chart][u['code']]
    allowed = {c for a in entry.get('may_assign', []) for c in a['class']}
    if entry.get('emplaced'):
        allowed.add('artillery')  # "the emplaced guns and may assign up to eight anti-air"
    total = 0
    for t in u['toe']:
        if 'w' in t:
            nat, w = t['w'].split('/')
            cls = tables['weapons'][nat][w]['class']
            if not (entry.get('emplaced') and cls == 'artillery'):
                total += t['n']  # the emplaced guns don't count against the maximum ("8AA")
            if cls not in allowed and (u['id'], cls) not in OTHER_CLASS:
                problems.append(f'{chart} {u["id"]}: {t["w"]} ({cls}) on ID code {u["code"]}, '
                                f'which may be assigned {sorted(allowed) or "none"}')
        else:
            total += t['n']
            if 'code' in t and 'recce' not in allowed:
                problems.append(f'{chart} {u["id"]}: TOE of ID code {t["code"]} on ID code {u["code"]}')
    limit = entry.get('max_toe')
    weapons = [tables['weapons'][t['w'].split('/')[0]][t['w'].split('/')[1]] for t in u['toe'] if 'w' in t]
    if 'max_toe_us' in entry and weapons and all(w.get('us') for w in weapons):
        limit = entry['max_toe_us']  # a tank battalion of US tanks only (4.46a)
    if rated(entry):
        # A unit with ratings of its own, which may be assigned weapons systems besides
        # (German h): the maximum is that of its own points
        own = sum(t['n'] for t in u['toe'] if set(t) == {'n'})
        extra = total - own
        if extra > sum(a['n'] for a in entry.get('may_assign', [])) and u['id'] not in OVER_MAX:
            problems.append(f'{chart} {u["id"]}: arrives with {extra} assigned TOE, more than ID code {u["code"]} may have')
        total = own
    if limit is not None and total > limit and u.get('strength') != 'over' and u['id'] not in OVER_MAX:
        problems.append(f'{chart} {u["id"]}: arrives with {total} TOE, above the maximum {limit} of ID code {u["code"]}')
    if u.get('strength') == 'under' and limit is not None and total >= limit:
        problems.append(f'{chart} {u["id"]}: understrength at {total}, but the maximum is {limit}')
    if u.get('strength') == 'over' and limit is not None and total <= limit:
        problems.append(f'{chart} {u["id"]}: overstrength at {total}, but the maximum is {limit}')


def load_tables():
    out = {'units': {}, 'weapons': {}}
    for kind, key in (('units', 'codes'), ('weapons', 'weapons')):
        for nat in ('cw', 'it', 'gm'):
            with open(TABLES / f'{kind}-{nat}.json', encoding='utf-8') as f:
                out[kind][nat] = json.load(f)[key]
    return out


def about(chart):
    return (f'The {NAMES[chart]} Organization at Arrival Chart (4.45): its sheets in printed order, each with its '
            'units. id: <chart>/<sheet>/<counter>. code: the ID code in data/tables/units-' + chart + '.json. '
            'parent: the unit it is assigned to. group: a heading on the sheet with no counter. toe: TOE Strength '
            'Points on arrival, {n} of the unit\'s own kind, {w, n} of a weapons system (data/tables/weapons-*.json), '
            '{code, n} of another ID code; land: how many of them may fire on land. strength: under or over (U@, '
            'O@). arrives: D (deployed at the start of the campaign), {turn, stage}, or null. morale: {basic, '
            'untrained}, on the sheet or on a unit where it differs. eng: an HQ with engineering capability. '
            'garrison: the hex. replaces: the counter it takes the place of; takes_toe: and its TOE. formed: formed in play. standin: not '
            'in the charts; a stand-in for a unit a set-up deploys (tools/units/oa.py, STAND_INS), arriving only '
            'with it. note: the sheet\'s note letter. refs: units of another sheet listed on this one, arriving or '
            'starting attached. Generated by tools/units/oa.py from the rulebook transcription and its addenda.')


def write(chart, sheets):
    path = OUT / f'oa-{chart}.json'
    parts = []
    for s in sheets:
        head = {k: v for k, v in s.items() if k != 'units'}
        units = ',\n'.join(f'    {json.dumps(u, ensure_ascii=False)}' for u in s['units'])
        text = json.dumps(head, ensure_ascii=False)[:-1]
        parts.append(f'  {text}, "units": [\n{units}\n  ]}}')
    body = ',\n'.join(parts)
    path.write_text(f'{{\n "about": {json.dumps(about(chart), ensure_ascii=False)},\n "chart": "4.45",\n'
                    f' "sheets": [\n{body}\n ]\n}}\n', encoding='utf-8', newline='\n')
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--check', action='store_true', help='only report problems; write nothing')
    a = ap.parse_args()
    if not RULEBOOK.exists():
        sys.exit(f'{RULEBOOK.name} is not in the project folder')
    found = read_charts(RULEBOOK.read_text(encoding='utf-8').split('\n'))
    found['it'].extend(read_charts(ADDENDA.split('\n'))['it'])
    data, problems = build(found, load_tables())
    for p in problems:
        print(p)
    print(', '.join(f'{c}: {len(s)} sheets, {sum(len(x["units"]) for x in s)} units' for c, s in data.items())
          + f'; {len(problems)} problems')
    if a.check:
        sys.exit(1 if problems else 0)
    if problems:
        sys.exit('not written: fix the problems first')
    OUT.mkdir(parents=True, exist_ok=True)
    for chart, sheets in data.items():
        print(f'wrote {write(chart, sheets).relative_to(ROOT)}')


if __name__ == '__main__':
    main()
