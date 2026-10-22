"""The units as the charts give them: the Organization at Arrival Charts (4.45)
and the Characteristics Charts (4.46–4.49), from data/units/ and data/tables/.

A unit is named by its OA id, <chart>/<sheet>/<counter> (cw/7-armd/1-rtr), and
a weapons system by <chart>/<slug> (cw/a9-cruiser). The charts are cw, it and
gm. Nothing here is copied into a game's state: the state keeps the OA id and
what changes in play (TOE, morale, attachment), and looks the rest up here, so
a fix in the data reaches games already started.

  unit(oa_id)                the OA entry, with its sheet and ID code row
  face(u)                    what a unit's counter shows: name, abbreviation, type, size
  characteristics(u, at)     the unit's ratings, from its TOE and ID code
  carried(state, uid)        the units attached to a counter, as a tree
  place(state, uid)          where a unit is, following what it is attached to

roster.py prints a scenario's units, for checking against the rulebook.
"""
import json
import re
import threading

from ..paths import TABLES, UNIT_DATA
from ..rules import implements

CHARTS = ('cw', 'it', 'gm')
# The ratings each TOE Strength Point has; the rest of an ID code row is the unit's.
POINT_RATINGS = ('aa', 'barrage', 'anti_armor', 'vulnerability', 'armor', 'assault_off', 'assault_def')
# The ratings a weapons system assigned to an HQ with a parenthesized maximum
# fights with in parentheses (4.46): those it attacks or defends with.
COMBAT_RATINGS = ('aa', 'barrage', 'anti_armor', 'assault_off', 'assault_def')

# "Early 1942" (4.46), when a Commonwealth tank battalion of US tanks only has a
# maximum of 9: read as January, the first Game-Turn of 1942, as the charts'
# other changes of that winter are dated.
US_ONLY_FROM = {'turn': 63, 'stage': 1}

_LOCK = threading.Lock()
_DATA = None


def _load(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


class Charts:
    def __init__(self):
        self.oa = {c: _load(UNIT_DATA / f'oa-{c}.json') for c in CHARTS}
        self.tables = {c: _load(TABLES / f'units-{c}.json') for c in CHARTS}
        self.arms = {c: _load(TABLES / f'weapons-{c}.json') for c in CHARTS}
        self.codes = {c: self.tables[c]['codes'] for c in CHARTS}
        self.weapons = {f'{c}/{slug}': w for c in CHARTS for slug, w in self.arms[c]['weapons'].items()}
        self.units, self.sheets, self.children, self.refs, self.replaced_by = {}, {}, {}, {}, {}
        for c in CHARTS:
            for s in self.oa[c]['sheets']:
                sheet = {k: v for k, v in s.items() if k != 'units'}
                self.sheets[s['id']] = {**sheet, 'units': [u['id'] for u in s['units']]}
                for u in s['units']:
                    # A unit's own morale and nationality, where it has them, stand
                    # in for the sheet's.
                    self.units[u['id']] = {**u, 'chart': c, 'sheet': sheet, 'row': self.codes[c][u['code']],
                                           'nat': u.get('nat', s['nat']), 'morale': u.get('morale', s.get('morale'))}
                    if u.get('parent'):
                        self.children.setdefault(u['parent'], []).append(u['id'])
                    if u.get('replaces'):
                        self.replaced_by[u['replaces']] = u['id']
                for r in s['refs']:
                    if r['parent']:
                        self.refs.setdefault(r['parent'], []).append(r['unit'])

    def payload(self):
        """The charts as the browser looks them up: by chart, the OA sheets,
        the ID codes and the weapons systems."""
        return {c: {'sheets': self.oa[c]['sheets'], 'codes': self.codes[c], 'later': self.tables[c]['later'],
                    'weapons': self.arms[c]['weapons']} for c in CHARTS}


def charts():
    """The charts, read once."""
    global _DATA
    with _LOCK:
        if _DATA is None:
            _DATA = Charts()
        return _DATA


@implements('4.41', '4.42', partial=True)  # arrival by the Reinforcement Schedules comes in M4
def unit(oa_id):
    """The OA entry of a unit: its row on the sheet, with chart, sheet (less its
    units), row (its ID code's row), nat and morale. Raises KeyError for an id
    the charts don't have."""
    try:
        return charts().units[oa_id]
    except KeyError:
        raise KeyError(f'There is no unit {oa_id!r} in the Organization at Arrival Charts.') from None


# The unit types of data/vocab.json, from the words of an ID code's type, in this order.
TYPE_WORDS = (('anti-tank', 'AT'), ('anti-air', 'AA'), ('headquarters', 'HQ'), ('tank', 'T'),
              ('artillery', 'Ar'), ('rec', 'R'), ('engineer', 'E'), ('construction', 'E'), ('infantry', 'I'))
SIZE_WORDS = ((r'\b(korps|corps)\b', 'XXX'), (r'\bdiv', 'XX'), (r'\b(bde|brigade|group|command|force)\b', 'X'),
              (r'\b(regt|regiment|regimental|legion)\b', 'III'), (r'\b(bn|battalion|bat)\b', 'II'),
              (r'\b(coy|co|company|bty|battery)\b', 'I'))


def _size(words):
    return next((s for w, s in SIZE_WORDS if re.search(w, words.lower())), '')


def face(u):
    """What a unit's counter shows (4.21), for a unit of the state: {name, abbr,
    type, size}, type and size as in data/vocab.json. Units with no OA entry
    carry their own."""
    if not u.get('oa'):
        return {'name': u['name'], 'abbr': u['name'], 'type': u['type'], 'size': u.get('size', '')}
    e = unit(u['oa'])
    kind = e['row']['type'].lower()
    type_ = next((t for w, t in TYPE_WORDS if w in kind), 'I')
    # An HQ's size is its formation's: from its name, or for the HQ heading a
    # sheet ("1st Libyan Infantry HQ") the sheet's title. Other units' is their
    # ID code's, or their name's where the code gives none (construction units).
    if type_ == 'HQ':
        size = _size(e['name']) or ('' if e.get('parent') else _size(e['sheet']['title']))
    else:
        size = _size(kind.replace('-eq', '')) or _size(e['name'])
    return {'name': e['name'], 'abbr': e['abbr'] or e['name'], 'type': type_, 'size': size}


def _holds(change, at):
    return at is not None and (at['turn'], at['stage']) >= (change['from']['turn'], change['from']['stage'])


def _weapon(w_id, at):
    w = charts().weapons[w_id]
    out = {k: v for k, v in w.items() if k != 'changes'}
    for ch in w.get('changes', ()):
        if _holds(ch, at):
            out.update({k: v for k, v in ch.items() if k != 'from'})
    return out


@implements('4.46', '4.47', '4.48', '4.49')
def characteristics(u, at=None):
    """The characteristics of a unit: an OA id, or a unit of the state ({oa,
    toe}) whose TOE may differ from the OA one. at ({turn, stage}) is when, for
    ratings that change during the campaign; None gives them as at the start.

    The unit's own fields (code, type, cpa, max_toe, may_assign and the chart's
    flags) are given with its TOE, one entry per kind of TOE Strength Point:
    {w, n, name, class, ratings…} for a weapons system, {code, n, type,
    ratings…} for points of another ID code, {n, ratings…} for its own kind.
    Each point fights with the ratings of its entry (4.46). paren names the
    ratings in parentheses, on the unit for its own fields and on each entry
    for that entry's."""
    oa_id, toe = (u, None) if isinstance(u, str) else (u['oa'], u.get('toe'))
    e = unit(oa_id)
    if toe is None:  # its OA TOE, or that of the counter it takes over
        toe = unit(e['replaces'])['toe'] if e.get('takes_toe') else e['toe']
    row, c = e['row'], e['chart']
    own_paren = [r for r in row.get('paren', ()) if r in POINT_RATINGS]
    out = {k: v for k, v in row.items() if k not in POINT_RATINGS and k != 'paren'}
    out['oa'], out['code'] = oa_id, e['code']
    if 'motorized' in e:
        out['motorized'] = e['motorized']
    paren = [r for r in row.get('paren', ()) if r not in POINT_RATINGS]
    # Weapons systems assigned to an HQ whose maximum is in parentheses fight
    # with parenthesized values (4.46).
    assigned_paren = 'max_toe' in paren

    entries = []
    for t in toe:
        if 'w' in t:
            x = {**_weapon(t['w'], at), **t}
        elif 'code' in t:
            r = charts().codes[c][t['code']]
            x = {'type': r['type'], 'cpa': r.get('cpa'), **{k: r[k] for k in (*POINT_RATINGS, 'bar') if k in r},
                 **({'paren': r['paren']} if r.get('paren') else {}), **t}
        else:
            x = {'cpa': row.get('cpa'), **{k: row[k] for k in POINT_RATINGS if k in row},
                 **({'paren': own_paren} if own_paren else {}), **t}
        if assigned_paren and ('w' in t or 'code' in t):
            x['paren'] = [r for r in POINT_RATINGS
                          if r in x.get('paren', ()) or (r in COMBAT_RATINGS and r in x)]
        entries.append(x)
    out['toe'] = entries
    out['points'] = sum(t['n'] for t in toe)

    # The CPA of the slowest TOE Strength Point, unless the chart fixes it (4.46).
    if entries and not row.get('cpa_fixed'):
        if any(x.get('cpa') is None for x in entries):
            out['cpa'] = None
            out['open'] = ['cpa']
        else:
            out['cpa'] = min(x['cpa'] for x in entries)
    # A tank battalion of US tanks only, from "early 1942" (4.46)
    if 'max_toe_us' in row and entries and all(x.get('us') for x in entries) and _holds({'from': US_ONLY_FROM}, at):
        out['max_toe'] = row['max_toe_us']
    if paren:
        out['paren'] = paren
    return out


def carried(state, uid):
    """The units attached to the unit uid, each with those attached to it:
    [{id, carried: [...]}], in the order of the state's units."""
    under = {}
    for u in state['units'].values():
        if u.get('attached'):
            under.setdefault(u['attached'], []).append(u['id'])

    def tree(i, seen):
        return [{'id': k, 'carried': tree(k, seen | {k})} for k in under.get(i, ()) if k not in seen]
    return tree(uid, {uid})


def place(state, uid):
    """Where the unit uid is: its own loc, or its carrier's if it is attached."""
    units, seen = state['units'], set()
    u = units[uid]
    while u.get('attached') and u['id'] not in seen:
        seen.add(u['id'])
        u = units[u['attached']]
    return u['loc']

