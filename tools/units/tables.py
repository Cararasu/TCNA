"""The characteristics charts (4.46-4.49) as data, for the rules and the log sheets.

Usage (from the project folder, with the rulebook transcription present):
  python -I tools/units/tables.py [--check]

Reads "The Campaign for North Africa.md" and writes data/tables/:

  units-cw.json, units-it.json, units-gm.json
      the Unit Characteristics Charts (4.46a-c): each ID code's CPA, ratings,
      maximum TOE, and the weapons systems it may be assigned
  weapons-cw.json, weapons-it.json, weapons-gm.json
      the Tank and Gun Characteristics Charts (4.47-4.49): each weapons
      system's CPA, ratings, fuel rate and Breakdown Adjustment Rating

A rating is a number, left out where the chart prints "-". A parenthesized
rating (3.4, 4.46) is also named in 'paren'. The marks each chart explains in
its key become fields (MARKS), as do the chart's notes (NOTES).

The Charts & Tables booklet is printed once for each player, so every chart is
in the transcription twice. Both copies are read, and they must agree once
FIXES are applied: --check lists where they don't. FIXES correct the
printed charts where they are wrong (each checked against the scans, in the
PDF's pages 136-140 and 167-179), each with its reason. Weapons systems the printed chart leaves a
rating out for are listed under 'open', to be settled before the rules need them.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RULEBOOK = ROOT / 'The Campaign for North Africa.md'
OUT = ROOT / 'data' / 'tables'

CHARTS = {'4.46a': ('units', 'cw'), '4.46b': ('units', 'it'), '4.46c': ('units', 'gm'),
          '4.47': ('weapons', 'cw'), '4.48': ('weapons', 'it'), '4.49': ('weapons', 'gm')}
NATIONS = {'cw': 'Commonwealth', 'it': 'Italian', 'gm': 'German'}
COLUMNS = {
    'units': ['type', 'code', 'cpa', 'aa', 'barrage', 'anti_armor', 'vulnerability', 'armor', 'assault', 'max_toe'],
    'weapons': ['name', 'cpa', 'aa', 'barrage', 'anti_armor', 'vulnerability', 'armor', 'assault', 'fuel', 'bar'],
}

# (chart, copy or None for both, ID code or weapon name) -> {column: value as it should read}
FIXES = {
    # Copy 2 prints "–" for the A9's armor, where Copy 1 (and every other
    # cruiser) has a rating; the A9 was the most thinly armored of them.
    ('4.47', 2, 'A9 Cruiser'): {'armor': '1'},
    # Copy 2 marks c and d with a dagger its key doesn't explain; Copy 1 prints
    # ** there: the unit keeps its CPA whatever TOE is assigned.
    ('4.46c', 2, 'c'): {'cpa': '30**'},
    ('4.46c', 2, 'd'): {'cpa': '30**'},
    ('4.46c', 2, 'v'): {'assault': '–'},  # Copy 2 prints a lone "*"; Copy 1 prints "–"
    ('4.46a', 1, 'z'): {'type': 'Anti-tank Battalion-Eq'},  # "Anti-tank Battalion-Eq Equivalents"
    # Rows the chart itself prints shifted against its columns (in both copies):
    # Pz III E reads "4 3 4/4 3 4/4 3" from Anti-armor on, the anti-armor,
    # armor, assault and fuel of a Pz III with the last two repeated; its BAR
    # is that of every other German tank.
    ('4.49', None, 'Pz III E'): {'vulnerability': '–', 'armor': '3', 'assault': '4/4', 'fuel': '3', 'bar': '0'},
    # 7.62cm Pak(R) and Marder III (SP) are printed one column to the left, so
    # that their CPA is missing. The addenda (September 1979, [4.49]) give it:
    # "The CPA for the 7.62cm Pak(R) is 15; for the Marder, 25."
    ('4.49', None, '7.62cm Pak(R)'): {'cpa': '15', 'aa': '–', 'barrage': '–', 'anti_armor': '9',
                                      'vulnerability': '2', 'armor': '–', 'assault': '1/1', 'fuel': '1', 'bar': '–'},
    ('4.49', None, 'Marder III (SP)'): {'cpa': '25', 'aa': '–', 'barrage': '–', 'anti_armor': '9',
                                        'vulnerability': '2', 'armor': '2', 'assault': '3/2', 'fuel': '2', 'bar': '0'},
    ('4.49', None, '5cm Pak 38'): {'assault': '1/1'},  # printed "1½1"
}

# What each chart's marks mean, by its key: (column, mark) -> field.
MARKS = {
    '4.46a': {('cpa', '*'): 'cpa_fixed', ('cpa', '+'): 'motorized',
              ('max_toe', '†'): 'max_toe_us', ('max_toe', '**'): 'max_toe_us'},
    '4.46b': {('cpa', '*'): 'cpa_fixed', ('cpa', '+'): 'motorized'},
    '4.46c': {('code', '*'): 'augment', ('cpa', '**'): 'cpa_fixed', ('cpa', '+'): 'motorized',
              ('cpa', '‡'): 'halftrack'},
    '4.47': {('name', '*'): 'us', ('name', '†'): 'engineer', ('name', '‡'): 'sp'},
    '4.48': {('name', '*'): 'sp', ('name', '***'): 'airdrop', ('name', '****'): None,
             ('anti_armor', '**'): 'from_63', ('cpa', '+'): 'no_transport'},
    '4.49': {('name', '***'): None, ('name', '****'): None, ('anti_armor', '**'): 'from_63'},
}
JAN_1942 = {'turn': 63, 'stage': 1}  # "the first Operations Stage in Jan of 1942 (Game-Turn 63)"

# The charts' notes, as fields: what each note gives, by ID code or weapon.
NOTES = {
    '4.46a': {'later': [
        {'case': '20.5', 'from': {'turn': 39, 'stage': 1}, 'codes': None},  # "certain Reconnaissance units"
        {'case': '19.9', 'from': {'turn': 75, 'stage': 1}, 'codes': list('klmnpqrst')},
        {'case': '20.77', 'from': {'turn': 87, 'stage': 1}, 'codes': list('nprs')}]},
    '4.46b': {'later': [
        {'case': '20.5', 'from': {'turn': 39, 'stage': 1}, 'codes': ['ww']},
        {'case': '19.8', 'from': {'turn': 75, 'stage': 1}, 'codes': None}],  # battle groups, certain HQs
              'codes': {'vv': {'bar': -1}, 'ww': {'bar': -1},  # note 3
                        't': {'halftrack': True}}},  # note 5
    '4.46c': {'later': [
        {'case': '20.5', 'from': {'turn': 39, 'stage': 1}, 'codes': ['ff']},
        {'case': '19.8', 'from': {'turn': 75, 'stage': 1}, 'codes': None}],
              'codes': {'ee': {'bar': -1}, 'ff': {'bar': -1}}},  # note 3
    # Note 1: air transportable and airdroppable.
    '4.49': {'weapons': {'7.5 cm(IG18) Light Infantry Gun': {'airdrop': True},
                         '2.8cm s.Pz.B.41 or 28/20 Pak': {'airdrop': True}}},
}
GERMAN_TANK_BAR = {'bar': 1, 'until': {'turn': 31, 'stage': 1}}  # 4.49's BAR*: "1R until ... the 1/31 Game-Turn"

# Section headings within the Tank and Gun charts -> the class of the weapons
# under them. The German chart lists its guns under "Tank Weapon Systems", from
# the row in FIRST_GUN on.
CLASSES = [('tank weapon', 'tank'), ('artillery', 'artillery'), ('gun weapon', 'artillery'),
           ('anti-tank', 'anti-tank'), ('antitank', 'anti-tank'), ('anti-air', 'aa')]
FIRST_GUN = {'4.49': '7.5 cm(IG18) Light Infantry Gun'}

NUMBERS = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8, 'nine': 9,
           'ten': 10, 'twelve': 12, 'fifteen': 15}
# The first that the words contain; "anti-tank" before "tank", "light"/"heavy" before "anti-air".
ASSIGNABLE = [('reconnais', ['recce']), ('anti-tank', ['anti-tank']), ('tank', ['tank']),
              ('artillery', ['artillery']), ('light', ['light-aa']), ('heavy', ['heavy-aa']),
              ('anti-air', ['light-aa', 'heavy-aa'])]
ASSIGN = re.compile(r'(?:up to )?(' + '|'.join(NUMBERS) + r') (paradropable )?'
                    r'(reconnaiss?ance|tank|artillery|anti-tank|light anti-air|light aa|light anti-aircraft|'
                    r'heavy aa|heavy anti-air|anti-air)', re.I)

HEADING = re.compile(r'^#{3,4} \[(4\.4[6-9][abc]?)\] (.*)')
ANY_HEADING = re.compile(r'^#{1,4} ')
MARK = r'[*†‡+]*'
NUM = re.compile(r'^(\()?(\d+)(\))?\s*(' + MARK + ')$')
DASH = {'', '–', '-', '—'}


class Bad(ValueError):
    pass


def clean(cell):
    return re.sub(r'</?sub>', '', cell.replace('\\*', '*')).strip()


def name_and_marks(s):
    m = re.match(r'^(.*?)\s*(' + MARK + ')$', s)
    return m.group(1), m.group(2)


def copies(lines):
    """chart -> its copies in the transcription; each a list of ('row', cells) and ('class', name)."""
    out, current = {}, None
    for line in lines:
        m = HEADING.match(line)
        if m and m.group(1) in CHARTS:
            if not ('continued' in m.group(2).lower() and current == m.group(1)):
                out.setdefault(m.group(1), []).append([])
            current = m.group(1)
            continue
        if ANY_HEADING.match(line):
            current = None
        if current is None:
            continue
        s = line.strip()
        if s.startswith('|'):
            if not s.startswith('|---'):
                out[current][-1].append(('row', [clean(c) for c in s.strip('|').split('|')]))
        elif re.fullmatch(r'\*+[^*]{1,40}\*+', s):
            out[current][-1].append(('class', s.strip('*')))
    return out


def number(raw, where):
    """A rating: (value or None, parenthesized, marks)."""
    if raw in DASH:
        return None, False, ''
    m = NUM.match(raw)
    if not m or bool(m.group(1)) != bool(m.group(3)):
        raise Bad(f'{where}: cannot read {raw!r}')
    return int(m.group(2)), bool(m.group(1)), m.group(4)


def assault(raw, where):
    if raw in DASH:
        return (None, False), (None, False)
    m = re.match(r'^(\(?\d+\)?)/(\(?\d+\)?)$', raw)
    if not m:
        raise Bad(f'{where}: cannot read the close assault ratings {raw!r}')
    return tuple(number(x, where)[:2] for x in m.groups())


def bar(raw, where):
    if raw in DASH:
        return None
    m = re.match(r'^(\d)([RL]?)$', raw)
    if not m or (m.group(1) != '0' and not m.group(2)):
        raise Bad(f'{where}: cannot read the BAR {raw!r}')
    return int(m.group(1)) * (-1 if m.group(2) == 'L' else 1)


def max_toe(raw, where):
    """The Maximum TOE column: (value or None, parenthesized, marks). '9 +3' is 12; '8AA' is 8."""
    if raw in DASH:
        return None, False, ''
    m = re.match(r'^(\()?(\d+)(\))?\s*(?:\+\s*(\d+))?\s*(?:AA)?\s*(' + MARK + ')$', raw)
    if not m:
        raise Bad(f'{where}: cannot read the maximum TOE {raw!r}')
    return int(m.group(2)) + int(m.group(4) or 0), bool(m.group(1)), m.group(5)


def may_assign(text, where):
    """'may assign up to eight anti-tank TOE Strength Points and three artillery ...'
    -> [{'class': [...], 'n': 8}, {'class': ['artillery'], 'n': 3}]. Alternatives joined
    by 'or' are one entry whose class lists them all."""
    text = text.replace('*', '')
    out, last = [], None
    for m in ASSIGN.finditer(text):
        kind = m.group(3).lower()
        cls = next(c for key, c in ASSIGNABLE if key in kind)
        if last is not None and re.search(r'\bor\b', text[last.end():m.start()]):
            prev = out[-1]
            if prev['n'] != NUMBERS[m.group(1).lower()]:
                raise Bad(f'{where}: alternatives of different sizes in {text!r}')
            prev['class'] = prev['class'] + [c for c in cls if c not in prev['class']]
        else:
            out.append({'class': list(cls), 'n': NUMBERS[m.group(1).lower()],
                        **({'airdrop': True} if m.group(2) else {})})
        last = m
    if not out:
        raise Bad(f'{where}: cannot read {text!r}')
    return out


def apply_fixes(chart, copy, key, cells, kind):
    row = dict(zip(COLUMNS[kind], cells))
    for k in ((chart, copy, key), (chart, None, key)):
        row.update(FIXES.get(k, {}))
    return row


def marked(chart, column, marks, where):
    """The fields the marks after a value stand for ('+‡': two marks)."""
    out = []
    for mark in re.findall(r'\*+|[†‡+]', marks):
        if (column, mark) not in MARKS[chart]:
            raise Bad(f'{where}: the mark {mark!r} in {column} is not in the chart\'s key')
        out.append(MARKS[chart][(column, mark)])
    return out


def ratings(entry, row, chart, where, columns):
    """Reads the rating columns of a row into entry; returns the marks' fields."""
    flags = []
    for col in columns:
        value, paren, marks = number(row[col], f'{where} {col}') if row[col] != '?' else (None, False, '')
        if value is not None:
            entry[col] = value
        if paren:
            entry.setdefault('paren', []).append(col)
        flags += marked(chart, col, marks, where)
    (off, poff), (dfn, pdef) = assault(row['assault'], where)
    for col, value, paren in (('assault_off', off, poff), ('assault_def', dfn, pdef)):
        if value is not None:
            entry[col] = value
        if paren:
            entry.setdefault('paren', []).append(col)
    return flags


def read_units(chart, copy, items):
    codes, kind_of = {}, ''
    for _, cells in (i for i in items if i[0] == 'row'):
        if cells[0] in ('Unit Type',) or len(cells) != 10:
            if len(cells) != 10:
                raise Bad(f'{chart} copy {copy}: a row with {len(cells)} cells: {cells}')
            continue
        if cells[1]:
            code, code_marks = name_and_marks(cells[1])
            where = f'{chart} copy {copy} {code}'
            row = apply_fixes(chart, copy, code, cells, 'units')
            kind_of = row['type'] or kind_of
            entry = {'type': kind_of}
            flags = ratings(entry, row, chart, where, ['cpa', 'aa', 'barrage', 'anti_armor', 'vulnerability', 'armor'])
            flags += marked(chart, 'code', code_marks, where)
            value, paren, marks = max_toe(row['max_toe'], where)
            if value is not None:
                entry['max_toe'] = value
            if paren:
                entry.setdefault('paren', []).append('max_toe')
            flags += marked(chart, 'max_toe', marks, where)
            set_flags(entry, flags)
            codes[code] = entry
        else:
            # "may assign ..." under the code it belongs to, with that code's maximum TOE
            text = next((c for c in cells if 'assign' in c or 'emplaced' in c), None)
            if text is None or not codes:
                raise Bad(f'{chart} copy {copy}: cannot read the row {cells}')
            code = list(codes)[-1]
            entry, where = codes[code], f'{chart} copy {copy} {code}'
            entry['may_assign'] = may_assign(text, where)
            if 'emplaced' in text:
                entry['emplaced'] = True
            value, paren, marks = max_toe(cells[-1], where)
            if value is not None:
                entry['max_toe'] = value
                if paren:
                    entry.setdefault('paren', []).append('max_toe')
            set_flags(entry, marked(chart, 'max_toe', marks, where))
    for code, extra in NOTES.get(chart, {}).get('codes', {}).items():
        codes[code].update(extra)
    return {code: paren_last(e) for code, e in codes.items()}


def paren_last(entry):
    if 'paren' in entry:
        entry['paren'] = entry.pop('paren')
    return entry


def set_flags(entry, flags):
    for f in flags:
        if f == 'max_toe_us':
            entry['max_toe_us'] = 9  # "its maximum TOE Strength is nine points"
        elif f == 'augment':
            entry['augment'] = '19.8'
        elif f is not None:
            entry[f] = True


def read_weapons(chart, copy, items):
    weapons, cls = {}, None
    for item in items:
        if item[0] == 'class' or (item[0] == 'row' and item[1][0] and not any(item[1][1:])):
            text = (item[1] if item[0] == 'class' else item[1][0]).strip('*').lower()
            cls = next((c for key, c in CLASSES if key in text), cls)
            continue
        cells = item[1]
        if cells[0] == 'Type':
            continue
        if len(cells) != 10:
            raise Bad(f'{chart} copy {copy}: a row with {len(cells)} cells: {cells}')
        name, name_marks = name_and_marks(cells[0])
        if FIRST_GUN.get(chart) == name:
            cls = 'artillery'
        where = f'{chart} copy {copy} {name}'
        if cls is None:
            raise Bad(f'{where}: no class heading above it')
        row = apply_fixes(chart, copy, name, cells, 'weapons')
        entry = {'name': name, 'class': cls}
        if cls == 'aa':
            entry['class'] = 'heavy-aa' if 'heavy' in name.lower() else 'light-aa'
        flags = ratings(entry, row, chart, where, ['cpa', 'aa', 'barrage', 'anti_armor', 'vulnerability', 'armor'])
        flags += marked(chart, 'name', name_marks, where)
        fuel, _, _ = number(row['fuel'], f'{where} fuel')
        if fuel is not None:
            entry['fuel'] = fuel
        b = bar(row['bar'], where)
        if b is not None:
            entry['bar'] = b
        if row['cpa'] == '?':
            entry['open'] = ['cpa']
        for f in flags:
            if f == 'from_63':
                # The printed rating holds from January 1942; before it, zero.
                entry['changes'] = [{'anti_armor': entry['anti_armor'], 'from': dict(JAN_1942)}]
                entry['anti_armor'] = 0
            elif f is not None:
                entry[f] = True
        if re.search(r'\bSP\b', name):
            entry['sp'] = True
        if chart == '4.49' and cls == 'tank':
            entry['changes'] = [{'bar': entry.get('bar', 0), 'from': dict(GERMAN_TANK_BAR['until'])}]
            entry['bar'] = GERMAN_TANK_BAR['bar']
        entry.update(NOTES.get(chart, {}).get('weapons', {}).get(name, {}))
        weapons[slug(name)] = paren_last(entry)
    return weapons


def slug(name):
    s = re.sub(r'[^a-z0-9]+', '-', name.lower().replace('"', '').replace('″', '')).strip('-')
    return s


def code_order(codes):
    """The ID codes as the charts letter them: a..z without i and o, then aa.., then aaa.."""
    letters = [c for c in 'abcdefghijklmnopqrstuvwxyz' if c not in 'io']
    seq = letters + [c * 2 for c in letters] + [c * 3 for c in letters]
    return seq[:len(codes)]


def differences(a, b, path=''):
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b), key=str):
            if k == 'type':
                continue  # how the type column is worded differs between the copies; it isn't a rating
            out += differences(a.get(k), b.get(k), f'{path} {k}'.strip())
        return out
    return [] if a == b else [f'{path}: {a!r} / {b!r}']


def read(lines):
    """chart -> data, and the problems found."""
    found, problems, out = copies(lines), [], {}
    for chart, (kind, _) in CHARTS.items():
        cs = found.get(chart, [])
        if len(cs) != 2:
            problems.append(f'{chart}: {len(cs)} copies in the transcription, not 2')
            if not cs:
                continue
        parsed = []
        for i, items in enumerate(cs, 1):
            try:
                parsed.append((read_units if kind == 'units' else read_weapons)(chart, i, items))
            except Bad as e:
                problems.append(str(e))
        if not parsed:
            continue
        for other in parsed[1:]:
            problems += [f'{chart} copies 1/2 differ in {d}' for d in differences(parsed[0], other)]
        data = parsed[0]
        if kind == 'units':
            if list(data) != code_order(data):
                problems.append(f'{chart}: the ID codes are not in sequence: {" ".join(data)}')
            for code, e in data.items():
                assigned = sum(x['n'] for x in e.get('may_assign', []))
                if assigned and assigned > e.get('max_toe', 0):
                    problems.append(f'{chart} {code}: may be assigned {assigned} TOE, above its maximum {e.get("max_toe")}')
                if 'cpa' not in e:
                    problems.append(f'{chart} {code}: no CPA')
        else:
            for w, e in data.items():
                if 'cpa' not in e and 'cpa' not in e.get('open', []):
                    problems.append(f'{chart} {w}: no CPA')
        out[chart] = data
    return out, problems


def about(chart):
    kind, nat = CHARTS[chart]
    if kind == 'units':
        return (f'The {NATIONS[nat]} Unit Characteristics Chart ({chart}), by ID code. Ratings: cpa, aa, barrage, '
                'anti_armor, vulnerability, armor, assault_off, assault_def, max_toe; left out where the chart '
                'prints a dash, and named in paren where parenthesized. may_assign: the weapons systems the unit '
                'may be assigned (class: any of those listed; n: up to). cpa_fixed: keeps its CPA whatever is '
                'assigned. motorized: historically fully motorized (+). max_toe_us: the maximum of a tank '
                'battalion of US tanks only. halftrack: has armor only when trucked (14.88). augment: may be '
                'augmented by anti-tank TOE (19.8). bar: Breakdown Adjustment Rating, columns right (+) or left '
                '(-). later: what the chart notes allow from a Game-Turn on, by case. Generated by '
                'tools/units/tables.py from the rulebook transcription.')
    return (f'The {NATIONS[nat]} Tank and Gun Characteristics Chart ({chart}), by weapons system. class: tank, '
            'artillery, anti-tank, light-aa or heavy-aa. Ratings as in the unit charts, with fuel (Fuel Rate) and '
            'bar (Breakdown Adjustment Rating, columns right (+) or left (-)). changes: values that hold from an '
            'Operations Stage on, the rating before it being the one given. us: a US tank. sp: self-propelled. '
            'engineer: counts as an engineer for minefields (26.0). airdrop: may be airdropped. no_transport: '
            'has no transport of its own (CPA 0). open: ratings the chart does not print, still to be settled. '
            'Generated by tools/units/tables.py from the rulebook transcription.')


def write(chart, data):
    kind, nat = CHARTS[chart]
    path = OUT / f'{kind}-{nat}.json'
    key = 'codes' if kind == 'units' else 'weapons'
    head = [f' "about": {json.dumps(about(chart), ensure_ascii=False)}', f' "chart": "{chart}"']
    if NOTES.get(chart, {}).get('later'):
        head.append(f' "later": {json.dumps(NOTES[chart]["later"], ensure_ascii=False)}')
    body = ',\n'.join(f'  {json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False)}'
                      for k, v in data.items())
    text = '{\n' + ',\n'.join(head) + f',\n "{key}": {{\n{body}\n }}\n}}\n'
    path.write_text(text, encoding='utf-8', newline='\n')
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--check', action='store_true', help='only report problems; write nothing')
    a = ap.parse_args()
    if not RULEBOOK.exists():
        sys.exit(f'{RULEBOOK.name} is not in the project folder')
    data, problems = read(RULEBOOK.read_text(encoding='utf-8').split('\n'))
    for p in problems:
        print(p)
    print(', '.join(f'{c}: {len(d)}' for c, d in data.items()) + f'; {len(problems)} problems')
    if a.check:
        sys.exit(1 if problems else 0)
    if problems:
        sys.exit('not written: fix the problems first')
    OUT.mkdir(parents=True, exist_ok=True)
    for chart, d in data.items():
        print(f'wrote {write(chart, d).relative_to(ROOT)}')


if __name__ == '__main__':
    main()
