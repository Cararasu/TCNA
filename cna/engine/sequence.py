"""The sequence of play as data, and the clock that walks it.

LAND is one Game-Turn of the Land Game (5.2), a tree of groups and steps.
Each step has an id, the case it comes from, its title, and who acts in it:

  both         both players, at the same time
  phasing      Player A or B, whichever's player turn it is (5.2 III.F-L)
  nonphasing   the other player
  initiative   the player with the Initiative
  axis, cw     that side

`sides` narrows who acts: the Commonwealth Rail Movement Phase belongs to
Player A only when Player A is the Commonwealth. A group can be done once for
each OpStage or each player (`each`), or repeated as a loop (`loop`): Player A
may go round the Movement and Combat Phase again (5.2 III.G).

The clock is a game's place in this tree:

  {turn, stage, player, step, round, order, done}

stage is 1-3 inside an OpStage and None before it; player is 'A' or 'B' inside
a player turn; round counts the times round a loop; order says which side is
Player A and which is B; done marks the sides that have ended a step that
waits for both. Before the first Game-Turn the clock is at the Set-up Stage;
after the scenario's last OpStage, at the end of the game.

A step stops the clock when someone acts in it and it has something to do:
it says so itself (stop), or a command can be given in it (has_work, from the
command registry). Every other step is passed by itself.
"""
from ..rules import implements
from .state import SIDES, other


def step(id, case, title, who, *, sides=None, stop=False):
    return {'id': id, 'case': case, 'title': title, 'who': who, 'sides': sides, 'stop': stop}


def group(id, case, title, children, *, each=None, loop=False):
    return {'id': id, 'case': case, 'title': title, 'children': children, 'each': each, 'loop': loop}


LAND = [
    step('initiative', '5.2 I', 'Initiative Determination Stage', 'both'),
    group('naval-convoy', '5.2 II', 'Naval Convoy Stage', [
        step('convoy-schedule', '5.2 II.A', 'Naval Convoy Schedule Phase', 'both'),
        step('tactical-shipping', '5.2 II.B', 'Tactical Shipping Phase', 'both'),
    ]),
    group('opstage', '5.2 III', 'Operations Stage', each='stage', children=[
        step('initiative-declaration', '5.2 III.A', 'Initiative Declaration Phase', 'initiative'),
        step('weather', '5.2 III.B', 'Weather Determination Phase', 'initiative'),
        step('organization', '5.2 III.C', 'Organization Phase', 'both'),
        step('convoy-arrival', '5.2 III.D', 'Naval Convoy Arrival Phase', 'both'),
        group('fleet', '5.2 III.E', 'Commonwealth Fleet Phase', [
            step('fleet-assignment', '5.2 III.E.1', 'Fleet Assignment Segment', 'cw'),
            step('fleet-repair', '5.2 III.E.2', 'Fleet Repair Segment', 'cw'),
        ]),
        group('player-turn', '5.2 III.F-L', 'Player Turn', each='player', children=[
            step('reserve-designation', '5.2 III.F', 'Reserve Designation Phase', 'phasing'),
            group('movement-combat', '5.2 III.G', 'Movement and Combat Phase', loop=True, children=[
                step('movement', '5.2 III.G.1', 'Movement Segment', 'phasing'),
                step('breakdown', '5.2 III.G.2', 'Breakdown Determination Segment', 'both'),
                group('combat', '5.2 III.G.3', 'Combat Segment', [
                    step('position', '5.2 III.G.3.a', 'Position Determination Step', 'both'),
                    step('barrage', '5.2 III.G.3.b', 'Barrage Step', 'both'),
                    step('retreat-before-assault', '5.2 III.G.3.c', 'Retreat Before Assault Step', 'nonphasing'),
                    step('force-assignment', '5.2 III.G.3.d', 'Force Assignment Step', 'both'),
                    step('anti-armor', '5.2 III.G.3.e', 'Anti-Armor Step', 'both'),
                    step('close-assault', '5.2 III.G.3.f', 'Close Assault Step', 'phasing'),
                ]),
                step('reserve-release', '5.2 III.G.4', 'Reserve Release Segment', 'phasing'),
            ]),
            step('truck-convoy', '5.2 III.H', 'Truck Convoy Movement Phase', 'phasing'),
            step('rail', '5.2 III.J', 'Commonwealth Rail Movement Phase', 'phasing', sides={'cw'}),
            group('repair', '5.2 III.K', 'Repair Phase', [
                step('towing', '5.2 III.K.1', 'Towing Segment', 'phasing'),
                step('maintenance', '5.2 III.K.2', 'Maintenance Segment', 'phasing'),
            ]),
            step('patrol', '5.2 III.L', 'Patrol Phase', 'phasing'),
        ]),
    ]),
    step('end-of-turn', '5.2 VI', 'End of Game-Turn', 'both', stop=True),
]
SETUP = step('setup', '59.2', 'Set-up Stage', 'both', stop=True)
GAME_OVER = step('game-over', None, 'End of the Game', 'none', stop=True)


def _expand(nodes, stage=None, player=None, loop=None):
    for n in nodes:
        if 'children' not in n:
            yield {'step': n['id'], 'stage': stage, 'player': player, 'loop': loop}
        elif n['each'] == 'stage':
            for k in (1, 2, 3):
                yield from _expand(n['children'], k, player, loop)
        elif n['each'] == 'player':
            for p in ('A', 'B'):
                yield from _expand(n['children'], stage, p, loop)
        else:
            yield from _expand(n['children'], stage, player, (n['id'], stage, player) if n['loop'] else loop)


def _steps(nodes):
    for n in nodes:
        if 'children' in n:
            yield from _steps(n['children'])
        else:
            yield n


SLOTS = list(_expand(LAND))  # one Game-Turn, step by step
INDEX = {(s['stage'], s['player'], s['step']): i for i, s in enumerate(SLOTS)}
STEPS = {s['id']: s for s in [*_steps(LAND), SETUP, GAME_OVER]}
assert len(STEPS) == len(list(_steps(LAND))) + 2, 'step ids must be unique'
LOOP_START = {}
for _i, _s in enumerate(SLOTS):
    if _s['loop']:
        LOOP_START[_i] = LOOP_START[_i - 1] if SLOTS[_i - 1]['loop'] == _s['loop'] else _i
LOOP_ENDS = {i for i in LOOP_START if i + 1 not in LOOP_START or LOOP_START[i + 1] != LOOP_START[i]}
LAST_OF_STAGE = {s['stage']: i for i, s in enumerate(SLOTS) if s['stage']}


# ---------- the clock ----------

def clock(turn, stage, player, step_id, order, round=1):
    return {'turn': turn, 'stage': stage, 'player': player, 'step': step_id, 'round': round,
            'order': dict(order), 'done': {side: False for side in SIDES}}


def setup_clock(start, initiative):
    """The clock of a new game: at the Set-up Stage, the side with the Initiative as Player A."""
    return clock(start['turn'], start['stage'], None, 'setup', {'A': initiative, 'B': other(initiative)})


def current(state):
    """The current step."""
    return STEPS[state['clock']['step']]


def actors(state):
    """The sides that act in the current step."""
    c = state['clock']
    s = current(state)
    who = s['who']
    if who == 'both':
        sides = set(SIDES)
    elif who in ('phasing', 'nonphasing'):
        player = c['player'] if who == 'phasing' else {'A': 'B', 'B': 'A'}[c['player']]
        sides = {c['order'][player]}
    elif who == 'initiative':
        sides = {state['initiative']['side']}
    elif who in SIDES:
        sides = {who}
    else:
        sides = set()
    return sides & s['sides'] if s['sides'] else sides


def waiting(state):
    """The sides the current step still waits for."""
    return {side for side in actors(state) if not state['clock']['done'][side]}


def where(c):
    """A clock's place, without its order and done marks."""
    return {k: c[k] for k in ('turn', 'stage', 'player', 'step')}


def _next(state, c, repeat=False):
    """The clock one step on."""
    order = c['order']
    if c['step'] == 'game-over':
        raise ValueError('the game is over')
    if c['step'] == 'setup':
        start = state['start']
        i = 0 if start['stage'] == 1 else INDEX[(start['stage'], None, 'initiative-declaration')]
        s = SLOTS[i]
        return clock(c['turn'], s['stage'], s['player'], s['step'], order)
    i = INDEX[(c['stage'], c['player'], c['step'])]
    if repeat:
        if i not in LOOP_ENDS:
            raise ValueError(f'{c["step"]} does not end a loop')
        s = SLOTS[LOOP_START[i]]
        return clock(c['turn'], s['stage'], s['player'], s['step'], order, c['round'] + 1)
    end = state['end']
    if c['turn'] == end['turn'] and i == LAST_OF_STAGE[end['stage']]:
        return clock(c['turn'], c['stage'], None, 'game-over', order)
    turn = c['turn']
    if i + 1 == len(SLOTS):
        i, turn = 0, turn + 1
    else:
        i += 1
    s = SLOTS[i]
    same_loop = i in LOOP_START and i - 1 in LOOP_START and LOOP_START[i] == LOOP_START[i - 1]
    return clock(turn, s['stage'], s['player'], s['step'], order, c['round'] if same_loop else 1)


def stops(state, has_work):
    """Whether the clock stops at the current step."""
    s = current(state)
    if s['id'] == 'game-over':
        return True
    if not actors(state):
        return False
    return s['stop'] or has_work(state)


@implements('5.1', '5.2')
def advance(state, has_work, repeat=False):
    """Moves the clock past the current step, and on past every step with
    nothing to do. repeat goes round the loop the current step ends instead.
    Returns the new clock and the places passed on the way."""
    c = _next(state, state['clock'], repeat)
    passed = []
    while not stops({**state, 'clock': c}, has_work):
        passed.append(where(c))
        c = _next(state, c)
    return c, passed
