"""Putting units in places: set-up placement, sandbox moves, and undo.

  place-unit  in the Set-up Stage: puts one of the side's flexible units, or
              several together, on a hex or in a box, or back in the pool (59.2)
  move-unit   in sandbox games, in the side's Movement Segment: moves units
              anywhere, for trying things out until the movement rules come
  undo        takes back the side's last placement or move in the current step

The units moved are counters: a unit attached to another (4.25) has no place
of its own and goes where its carrier goes, so it can't be moved alone.

A change of place is a list of moves {unit, from, to}. Each event that moves
units adds its moves to the undo list of the side that gave the command; the
clock's moving on empties the lists (play.py).
"""
from .board import board
from .oa import face
from .commands import Refused, command
from .events import applies, event
from .play import ready


def _own(ctx, uid):
    # The same refusal for another side's unit as for none at all, so that it
    # doesn't tell of a unit the player may not see.
    u = ctx.state['units'].get(uid) if isinstance(uid, str) else None
    if u is None or u['side'] != ctx.side:
        raise Refused(f'You have no unit {uid!r}.')
    if u['attached']:
        carrier = ctx.state['units'][u['attached']]
        raise Refused(f'{name(u)} is attached to {name(carrier)} and goes where it goes.', '4.25')
    return u


def name(u):
    return face(u)['name']


def _check_place(loc, pool=False):
    if not board().is_place(loc) or (loc['kind'] == 'pool' and not pool):
        raise Refused(f'{loc!r} is not a place on the board.')


@command('place-unit', steps={'setup'})
def place_unit(ctx, loc, unit=None, units=None):
    # unit: one unit; units: a list, placed together, so that one undo takes them back
    if (unit is None) == (units is None):
        raise Refused('Name the unit to place, or a list of units.')
    ids = [unit] if units is None else units
    if not isinstance(ids, list) or not ids or len(set(map(str, ids))) != len(ids):
        raise Refused('Name the units to place, each once.')
    us = [_own(ctx, uid) for uid in ids]
    for u in us:
        if not u['flex']:
            raise Refused(f'{name(u)} sets up where the scenario puts it.', '59.2')
    _check_place(loc, pool=True)
    moves = [{'unit': u['id'], 'from': dict(u['loc']), 'to': dict(loc)} for u in us if u['loc'] != loc]
    if not moves:
        raise Refused(f'{name(us[0])} is already there.' if len(us) == 1 else 'The units are already there.')
    yield event('unit-placed', moves=moves)


@command('move-unit', steps={'movement'}, available=lambda s: s['sandbox'])
def move_unit(ctx, units, to):
    if not isinstance(units, list) or not units or len(set(map(str, units))) != len(units):
        raise Refused('Name the units to move, each once.')
    us = [_own(ctx, uid) for uid in units]
    _check_place(to)
    for u in us:
        if u['loc']['kind'] == 'pool':
            raise Refused(f'{name(u)} is not on the map.')
    moves = [{'unit': u['id'], 'from': dict(u['loc']), 'to': dict(to)} for u in us if u['loc'] != to]
    if not moves:
        raise Refused('The units are already there.')
    yield event('units-moved', moves=moves)


@command('undo')
def undo(ctx):
    done = ctx.state['undo'][ctx.side]
    if not done:
        raise Refused('There is nothing to take back in this step.')
    yield event('move-undone', moves=[{'unit': m['unit'], 'from': m['to'], 'to': m['from']} for m in reversed(done[-1])])


@ready('setup')
def _all_placed(state, side):
    left = sum(1 for u in state['units'].values() if u['side'] == side and u['loc'] and u['loc']['kind'] == 'pool')
    if left:
        raise Refused(f'{left} unit{"s are" if left > 1 else " is"} still to be placed.', '59.2')


def _move(state, moves):
    for m in moves:
        state['units'][m['unit']]['loc'] = dict(m['to'])


@applies('unit-placed')
@applies('units-moved')
def _moved(state, ev):
    _move(state, ev['moves'])
    state['undo'][ev['by']].append([{**m, 'from': dict(m['from']), 'to': dict(m['to'])} for m in ev['moves']])


@applies('move-undone')
def _undone(state, ev):
    _move(state, ev['moves'])
    state['undo'][ev['by']].pop()
