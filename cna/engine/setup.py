"""A new game: its starting state from a scenario (59.2).

Each listing of the scenario's setup (data/scenarios.json) brings its units of
the Organization at Arrival Charts (cna/engine/oa.py), and each such unit
becomes a unit of the state, with its OA id as its id (Expansion). A
deployment's 'at' says where its counters start:

  box                   in that off-map box, fixed
  hex                   on that hex, fixed, unless 'within' lets them set up nearby
  hexes, near, anchor   on the first hex named, flexible
  area alone            in the pool, for the player to place

Flexible counters may be placed elsewhere in the Set-up Stage (units.py). In M0
they may go anywhere; the checks on where come in M2. A unit that starts
attached to another (4.25) has no place of its own: it is where its carrier is.

The deployments themselves, with their listings' names and texts but not their
units, are kept in the state too, so that later changes to scenarios.json don't
change a game already started.
"""
import json
import secrets

from ..paths import SCENARIOS
from ..rules import implements
from . import oa, sequence, state
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


ROSTER = ('assg', 'att', 'consists')


def _id(x):
    return x if isinstance(x, str) else x['oa']


def _spec(x):
    return {} if isinstance(x, str) else x


def claims(spec):
    """The OA units a listing names, so that it brings them and no other listing does:
    itself, and those it assigns, attaches, lists in its roster or chooses."""
    out = [spec['oa']] if spec.get('oa') in oa.charts().units else []  # a sheet is no unit
    for k in ROSTER:
        for x in spec.get(k, ()):
            out.extend(claims(x if isinstance(x, dict) else {'oa': x}))
    for x in spec.get('parts', ()):
        out.extend(claims({k: v for k, v in x.items() if k != 'oa'}))
    if 'choose' in spec:
        out.extend(spec['choose']['of'][:spec['choose']['n']])
    return out


class Expansion:
    """A setup's listings as units of the state, one per counter (59.2, 4.25, 4.42).

    A listing brings its unit and, recursively, the unit's OA subordinates,
    each attached to its parent and so without a counter of its own on the map,
    except for those:
      - in its 'less', or 'det' (listed elsewhere): left out, with theirs;
      - another listing names (claims): that listing brings them;
      - arriving after the scenario's start (4.42), unless a listing names them.
    A counter that replaces another (oa.py, 'replaces') stands in for it, with
    the other's subordinates, from its arrival or wherever a listing names it.
    The units a sheet lists as starting attached to a unit (its 'refs') come
    attached to it; a unit both such and of a formation in play comes with its
    formation, and is attached once all listings are brought, so that the order
    of the listings doesn't matter. 'consists' is the whole roster instead;
    'assg' units come assigned and attached, 'att' units attached only, and
    'parts' change the subordinate formations they name, with the same fields
    as a listing, at any depth. TOE is the OA sheet's, then the setup's tank
    tables', then the listing's.

    Units are {id, oa, side, nat, toe, morale, parent, attached, loc, flex,
    deployment, listing}: see state.py.
    """

    def __init__(self, setup_id, setup, start):
        self.setup_id = setup_id
        self.c = oa.charts()
        self.start = (start['turn'], start['stage'])
        self.tanks = {uid: toe for t in setup.get('toe', ()) for uid, toe in t['units'].items()}
        self.claimed = {uid for e in setup['deploy'] for u in e['units'] for uid in claims(u)}
        self.units = {}
        self.refs = []  # (unit, carrier, how it would come): attached by another sheet, done last

    def arrived(self, uid):
        a = self.c.units[uid]['arrives']
        return a == 'D' or (a is not None and (a['turn'], a['stage']) < self.start)

    def current(self, uid):
        """The counter that stands for uid: the one replacing it, once that is in play."""
        r = self.c.replaced_by.get(uid)
        return r if r and (r in self.claimed or self.arrived(r)) else uid

    def parent_of(self, uid):
        p = self.c.units[uid].get('parent')
        return self.current(p) if p else None

    def roster(self, uid):
        """uid's subordinates by the OA Charts, and the units its sheet attaches to
        it: [(id, assigned)], those other listings bring and those yet to arrive left out."""
        kids = list(self.c.children.get(uid, ()))
        orig = self.c.units[uid].get('replaces')
        if orig and self.current(orig) == uid:
            kids = self.c.children.get(orig, []) + kids
        out, seen = [], set()
        for k, assigned in [(k, True) for k in kids] + [(k, False) for k in self.c.refs.get(uid, ())]:
            k = self.current(k)
            if k not in seen and k not in self.claimed and self.arrived(k):
                seen.add(k)
                out.append((k, assigned))
        return out

    @implements('4.25')
    @implements('59.2', '4.42', partial=True)  # set-up placement checks come in M2, arrival by schedule in M4
    def listing(self, where, e, u, loc, flex):
        """Brings a listing's units. where: (deployment, listing) indexes."""
        common = {'side': e['side'], 'flex': flex, 'deployment': where[0], 'listing': where[1],
                  'training': bool(u.get('training'))}
        nat = u.get('nat') or e.get('nat') or DEFAULT_NATION[e['side']]
        if u.get('kind'):
            uid = f'{self.setup_id}.{where[0]}.{where[1]}'
            self.units[uid] = {'id': uid, 'oa': None, 'kind': u['kind'], 'name': u['name'], 'type': u['type'],
                               'size': u.get('size', ''), 'side': e['side'], 'nat': nat,
                               'toe': [dict(t) for t in u.get('toe', ())], 'morale': None, 'parent': None,
                               'attached': None, 'loc': dict(loc), 'flex': flex,
                               'deployment': where[0], 'listing': where[1]}
            return
        top = u.get('oa')
        if top in self.c.units:
            parent = u['parent'] if 'parent' in u else self.parent_of(top)
            self.bring(top, u, parent, None, loc, common)
            return
        # A sheet with no HQ, a roster with no HQ, or a choice: each unit its own counter
        if top in self.c.sheets:
            items = [top]
        elif 'choose' in u:
            items = u['choose']['of'][:u['choose']['n']]
        else:
            items = u['consists']
        for x in self.items(items):
            self.bring(_id(x), _spec(x), self.parent_of(_id(x)), None, loc, common)

    def attach_refs(self):
        """The units sheets attach to units of other formations (60.31's tank
        battalions): attached there, staying assigned to their own formation.
        One whose formation is not in play comes as the carrier's would."""
        done = set()
        for k, carrier, (loc, common, down) in self.refs:
            if k in done:
                continue
            done.add(k)
            if k in self.units:
                self.units[k].update(attached=carrier, loc=None)
            else:
                self.bring(k, {}, self.parent_of(k), carrier, loc, common, **down)

    def items(self, xs):
        """The units of a roster, whole sheets spelled out: those others claim or that
        have yet to arrive left out of a sheet."""
        for x in xs:
            if isinstance(x, str) and x in self.c.sheets:
                for uid in self.c.sheets[x]['units']:
                    if not self.c.units[uid].get('parent') and uid not in self.claimed and self.arrived(uid):
                        yield uid
            else:
                yield x

    # Morale from the OA sheet, untrained for units In Training; a battalion
    # taking its formation's in an assault comes in M3, Training itself in M4
    @implements('17.1', '17.31', partial=True)
    def bring(self, uid, spec, parent, attached, loc, common, less=frozenset(), parts=None):
        if uid in self.units:
            raise ValueError(f'The setup brings {uid} twice.')
        e = self.c.units[uid]
        parts = parts or {}
        spec = {**parts.get(uid, {}), **spec}
        parts = {**parts, **{p['oa']: p for p in spec.get('parts', ())}}
        less = less | set(spec.get('less', ())) | set(spec.get('det', ()))
        if 'parent' in spec:
            parent = spec['parent']
        if spec.get('training'):
            common = {**common, 'training': True}
        oa_toe = self.c.units[e['replaces']]['toe'] if e.get('takes_toe') else e['toe']
        toe = spec['toe'] if 'toe' in spec else self.tanks[uid] if uid in self.tanks else oa_toe
        m = e['morale']
        if m:
            m = {'basic': m['basic'], 'current': m['untrained'] if common['training'] and 'untrained' in m
                 else m['basic']}
        self.units[uid] = {'id': uid, 'oa': uid, 'side': common['side'], 'nat': e['nat'],
                           'toe': [dict(t) for t in toe], 'morale': m, 'parent': parent, 'attached': attached,
                           'loc': None if attached else dict(loc), 'flex': common['flex'],
                           'deployment': common['deployment'], 'listing': common['listing']}
        down = {'less': less, 'parts': parts}
        if 'consists' in spec:
            for x in self.items(spec['consists']):
                self.bring(_id(x), _spec(x), uid, uid, loc, common, **down)
        else:
            for k, assigned in self.roster(uid):
                if k in less:
                    continue
                if assigned:
                    self.bring(k, {}, uid, uid, loc, common, **down)
                else:
                    self.refs.append((k, uid, (loc, common, down)))
        for x in spec.get('assg', ()):
            alone = _id(x) in spec.get('detached', ())
            self.bring(_id(x), _spec(x), uid, None if alone else uid, loc, common, **down)
        for x in spec.get('att', ()):
            self.bring(_id(x), _spec(x), self.parent_of(_id(x)), uid, loc, common, **down)


def units(setup_id, setup, b, start):
    """The setup's units at the scenario's start: {id: unit}."""
    x = Expansion(setup_id, setup, start)
    for i, e in enumerate(setup['deploy']):
        loc, flex = placement(e['at'], b)
        for k, u in enumerate(e['units']):
            x.listing((i, k), e, u, loc, flex)
    x.attach_refs()
    return x.units


def counts(setup, b, start):
    """Each side's counters on the map and in the pool at the start, as the
    scenario screen shows them: {side: {'map': n, 'pool': n}}."""
    out = {side: {'map': 0, 'pool': 0} for side in state.SIDES}
    for u in units('', setup, b, start).values():
        if u['attached'] is None:
            out[u['side']]['pool' if u['loc']['kind'] == 'pool' else 'map'] += 1
    return out


def deployments(setup):
    """Each deployment as the browser shows it: its side, where it sets up, its
    case, and its listings' names and printed texts."""
    return [{**{k: x for k, x in e.items() if k != 'units'},
             'listings': [{k: u[k] for k in ('name', 'oa', 'text') if u.get(k)} for u in e['units']]}
            for e in setup['deploy']]


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
                     units=units(scenario['setup'], setup, board(), scenario['start']),
                     deployments=deployments(setup),
                     seed=seed or new_seed())
