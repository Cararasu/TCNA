"""A new game: its starting state from a scenario (59.2).

Each unit of the scenario's setup (data/scenarios.json) becomes a unit of the
state, with the id <setup>.<deployment>.<n>. A deployment's 'at' says where
its units start:

  box                   in that off-map box, fixed
  hex                   on that hex, fixed, unless 'within' lets them set up nearby
  hexes, near, anchor   on the first hex named, flexible
  area alone            in the pool, for the player to place

Flexible units may be placed elsewhere in the Set-up Stage (units.py). In M0
they may go anywhere; the checks on where come in M2.

The deployments themselves, less their units, are kept in the state too, so
that later changes to scenarios.json don't change a game already started.
"""
import json
import secrets

from ..paths import SCENARIOS
from ..rules import implements
from . import sequence, state
from .board import board
from .dice import new_seed

DEFAULT_NATION = {'axis': 'it', 'cw': 'uk'}
GAMES = ('land', 'air', 'logistics')


def catalog():
    with open(SCENARIOS, encoding='utf-8') as f:
        return json.load(f)


@implements('59.2', partial=True)  # where units set up; 'within N hexes' is checked from M2
def placement(at, b):
    """Where a deployment's units start, and whether the player may place them elsewhere.
    Raises ValueError for a hex or box the board doesn't have: a mistake in
    scenarios.json, which mustn't quietly turn fixed units into units to place."""
    if at.get('box'):
        if at['box'] not in b.zones:
            raise ValueError(f'The scenario puts units in {at["box"]!r}, which is not an off-map box.')
        return {'kind': 'zone', 'id': at['box']}, False
    ref = at.get('hex') or (at.get('hexes') or [None])[0] or at.get('near') or at.get('anchor')
    if not ref:
        return {'kind': 'pool'}, True
    hid = b.hex_of_label(ref)
    if not hid:
        raise ValueError(f'The scenario puts units at {ref!r}, which is not a hex on the map.')
    return {'kind': 'hex', 'id': hid}, not at.get('hex') or bool(at.get('within'))


def units(setup_id, setup, b):
    out = {}
    for i, e in enumerate(setup['deploy']):
        loc, flex = placement(e['at'], b)
        for k, u in enumerate(e['units']):
            uid = f'{setup_id}.{i}.{k}'
            out[uid] = {'id': uid, 'deployment': i, 'side': e['side'],
                        'nat': u.get('nat') or e.get('nat') or DEFAULT_NATION[e['side']],
                        'name': u['name'], 'type': u['type'], 'size': u.get('size', ''),
                        **({'detail': u['detail']} if u.get('detail') else {}),
                        'loc': dict(loc), 'flex': flex}
    return out


def counts(setup, b):
    """Each side's units on the map and in the pool at the start, as the
    scenario screen shows them: {side: {'map': n, 'pool': n}}."""
    out = {side: {'map': 0, 'pool': 0} for side in state.SIDES}
    for e in setup['deploy']:
        loc, _ = placement(e['at'], b)
        out[e['side']]['pool' if loc['kind'] == 'pool' else 'map'] += len(e['units'])
    return out


def deployments(setup):
    """Each deployment as the browser shows it: its side, where it sets up, its case."""
    return [{k: x for k, x in e.items() if k != 'units'} for e in setup['deploy']]


@implements('7.15', '60.6', '61.5', '64.4')
@implements('62.7', '63.6', partial=True)  # rolling for it instead takes effect in M2
def initiative(setup, start, choice=None):
    """The Initiative at the start: the setup's (7.15), or the creator's choice of
    a side, or 'roll' where the scenario lets the players roll for it instead."""
    init = setup['initiative']
    if choice is None:
        return {'side': init['side'], 'through': init['through']}
    if choice in state.SIDES:
        return {'side': choice, 'through': init['through']}
    if choice == 'roll':
        if not init.get('may_roll'):
            raise ValueError(f'In this scenario the Initiative at the start is fixed ({init["rule"]}).')
        return {'side': init['side'], 'through': start['turn'] - 1}
    raise ValueError(f'The Initiative goes to axis or cw, or is rolled for, not {choice!r}.')


def new_game(scenario_id, *, games=None, sandbox=False, initiative_choice=None, game_id=None, seed=None):
    """A new game's state, at the Set-up Stage. Raises ValueError for a choice
    the scenario doesn't allow."""
    cat = catalog()
    scenario = next((s for s in cat['scenarios'] if s['id'] == scenario_id), None)
    if scenario is None:
        raise ValueError(f'There is no scenario {scenario_id!r}.')
    if games is not None and not isinstance(games, dict):
        raise ValueError('The games played are an object: {land, air, logistics}.')
    games = {g: bool((games or {}).get(g)) for g in GAMES}
    games['land'] = True
    if games['air'] or games['logistics']:
        raise ValueError('So far only the Land Game can be played.')
    setup = cat['setups'][scenario['setup']]
    init = initiative(setup, scenario['start'], initiative_choice)
    return state.new(id=game_id or f'{scenario_id}-{secrets.token_hex(2)}', scenario=scenario_id, games=games,
                     sandbox=sandbox, start=scenario['start'], end=scenario['end'], initiative=init,
                     clock=sequence.setup_clock(scenario['start'], init['side']),
                     units=units(scenario['setup'], setup, board()), deployments=deployments(setup),
                     seed=seed or new_seed())
