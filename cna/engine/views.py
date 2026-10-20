"""What one seat may see of a game.

view(state, seat) is a copy of the state with what the seat may not see left
out, so the rules can run on it, for previews, as they run on the state:

  - the dice's seed, for no one: it would tell every roll to come
  - the seats' keys
  - in the Set-up Stage, the other side's units that it places itself, its
    placements in the log, and the event numbers, which would tell how many
    placements it has made (seq is then the seat's own count: games.py).
    Its fixed units are no secret: the scenario prints them.

The referee, a seat only sandbox games have (seats.py), sees everything else.
Fog of war comes with patrols in M3.

A view also carries what the browser shows: the seat, the current step, who
it waits for, the commands the seat can give, how many units it leaves out
(unseen), and the log of the events the seat may see.
"""
import copy

from . import sequence
from .commands import COMMANDS
from .state import SIDES, other

MOVES = {'unit-placed', 'units-moved', 'move-undone'}


def secret_setup(state):
    return state['clock']['step'] == 'setup'


def secret(ev):
    """Whether, in the Set-up Stage, only the side that caused the event (and
    the referee) may see it."""
    return ev['type'] in MOVES


def view(state, seat, log=(), registry=COMMANDS, seq=None):
    """seq: the number of events the seat may know of (games.Game.seq_for);
    by default the state's."""
    v = copy.deepcopy(state)
    if seq is not None:
        v['seq'] = seq
    v['dice'] = {'rolls': state['dice']['rolls']}
    v['seats'] = {s: x and {'name': x['name']} for s, x in state['seats'].items()}
    if seat in SIDES:
        foe = other(seat)
        v['undo'][foe] = []
        if secret_setup(state):
            v['units'] = {uid: u for uid, u in v['units'].items() if u['side'] == seat or not u['flex']}
    # How many of the other side's units are left out: no secret, the scenario lists them.
    v['unseen'] = len(state['units']) - len(v['units'])
    here = sequence.current(state)
    v['seat'] = seat
    v['now'] = {'step': here['id'], 'title': here['title'], 'case': here['case'],
                'waiting': sorted(sequence.waiting(state)),
                'allowed': registry.allowed(state, seat) if seat in SIDES else []}
    v['log'] = [e for e in (visible(ev, seat, state) for ev in log) if e is not None]
    return v


def visible(ev, seat, state):
    """The event as the seat may see it, or None."""
    hiding = seat in SIDES and secret_setup(state)
    if hiding and secret(ev) and ev['by'] != seat:
        return None
    drop = {'game-created': {'state'}, 'seat-taken': {'key'}}.get(ev['type'], set())
    if hiding:
        drop = drop | {'seq'}  # the gaps between the numbers would count the other side's placements
    return {k: x for k, x in ev.items() if k not in drop} if drop else ev
