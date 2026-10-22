"""A counter's TOE Log Sheet (4.52): what its owner keeps on paper.

The sheet is the counter's, its units' and their ratings', so only the side
that owns the counter sees it (and the referee): views.py gives the other side
the counter's face alone. Its sections, as the paper sheet has them:

  identity     A. Counter Identity: name, Basic and current morale, the parent
               it is assigned to, garrison location, engineering capability
  maneuver     B. Maneuver Elements: the units of its formation under it,
               a box each, and those assigned to it but detached elsewhere
  assets       C. Divisional Assets: for a division, the units attached directly
               to it and not under one of its brigade-level HQs
  augmentation D. Augmentation: units attached to it but assigned elsewhere
               (19.0), with the units they carry

Logistics (E), Combat Information (F) and Notes (G) come with the rules that
fill them (M3, M5, M7). Each box is a unit: {id, name, abbr, under, toe,
characteristics} with characteristics as oa.characteristics gives them, at
the game's date; a detached unit's box says where it is instead.
"""
from ..rules import implements
from . import oa
from .commands import Refused


def _at(state):
    c = state['clock']
    return {'turn': c['turn'], 'stage': c.get('stage') or 1}


def _box(state, uid, under=None):
    u = state['units'][uid]
    f = oa.face(u)
    box = {'id': uid, 'name': f['name'], 'abbr': f['abbr'], 'under': under, 'toe': u['toe']}
    if u['oa']:
        box['characteristics'] = oa.characteristics(u, _at(state))
    return box


@implements('4.52', partial=True)  # the TOE Log Sheet's sections A to D; logistics and combat information come later
def log_sheet(state, seat, uid):
    """The log sheet of counter uid, for the seat, which must own it (or be the
    referee). Raises Refused otherwise, the same way for a unit the seat may
    not see as for none."""
    units = state['units']
    u = units.get(uid) if isinstance(uid, str) else None
    if u is None or (seat != 'referee' and u['side'] != seat):
        raise Refused(f'You have no unit {uid!r}.')
    f = oa.face(u)
    entry = oa.unit(u['oa']) if u['oa'] else {}
    division = f['size'] == 'XX'
    out = {'maneuver': [], 'assets': [], 'augmentation': []}
    inside = set()

    def assigned(k):
        # Of the counter's formation: assigned to it, or to one of its units, and so on
        seen = set()
        while k in units and k not in seen:
            seen.add(k)
            if units[k]['parent'] == uid:
                return True
            k = units[k]['parent']
        return False

    def walk(carrier, tree, section):
        # A unit goes where its carrier went, unless it is attached but assigned
        # outside the formation (Augmentation) or is one of a division's own assets
        for node in tree:
            k = node['id']
            inside.add(k)
            ku = units[k]
            if section == 'augmentation' or not assigned(k):
                where = 'augmentation'
            elif carrier == uid and division and oa.face(ku)['type'] != 'HQ':
                where = 'assets'
            else:
                where = section or 'maneuver'
            out[where].append(_box(state, k, None if carrier == uid else carrier))
            walk(k, node['carried'], where)

    walk(uid, oa.carried(state, uid), None)
    # Units of its formation attached elsewhere or on counters of their own:
    # their boxes say "detached" (4.52 B)
    for x in units.values():
        if x['id'] not in inside and x['id'] != uid and assigned(x['id']):
            box = _box(state, x['id'], None if x['parent'] == uid else x['parent'])
            box['detached'] = oa.place(state, x['id'])
            out['maneuver'].append(box)
    garrison = entry.get('garrison') or (entry.get('sheet') or {}).get('garrison')
    # The formation it is assigned to, in play or not
    parent = u['parent'] and (oa.face(units[u['parent']])['name'] if u['parent'] in units
                              else oa.unit(u['parent'])['name'])
    identity = {'id': uid, **f, 'morale': u['morale'], 'nat': u['nat'],
                'parent': parent, 'parent_in_play': u['parent'] in units,
                'garrison': garrison, 'eng': bool(entry.get('eng')),
                'division': division, 'loc': oa.place(state, uid), 'toe': u['toe']}
    if u['oa']:
        identity['characteristics'] = oa.characteristics(u, _at(state))
    return {'identity': identity, **out}
