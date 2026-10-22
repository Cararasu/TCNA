"""What one seat may see of a game.

view(state, seat) is a copy of the state with what the seat may not see left
out, so the rules can run on it, for previews, as they run on the state:

  - the dice's seed, for no one: it would tell every roll to come
  - the seats' keys
  - the other side's log sheets: of its units, only its counters are seen, as
    their faces show them (4.21): what unit, whose, where. Their TOE, morale
    and assignment, and the units attached to them, are left out. Patrols and
    reconnaissance reveal more in M3 (16.0).
  - in the Set-up Stage, the other side's counters that it places itself, its
    placements in the log, and the event numbers, which would tell how many
    placements it has made (seq is then the seat's own count: games.py).
    Its fixed counters are no secret: the scenario prints them.

The referee, a seat only sandbox games have (seats.py), sees everything else.

A view also carries what the browser shows: the seat, the current step, who
it waits for, the commands the seat can give, how many units it leaves out
(unseen: the other side's counters it places in secret), and the log of the
events the seat may see. Each unit carries what its counter shows (oa.face: name, abbr, type, size), and a listing's own unit
the listing's printed text (detail): data of the charts and the scenario, not
of the game, so not in its state.
"""
import copy

from . import sequence
from .commands import COMMANDS
from .oa import face
from .state import SIDES, other

MOVES = {'unit-placed', 'units-moved', 'move-undone'}
# What the other side sees of a counter; units with no OA entry show their own name, type and size.
FACE = ('id', 'oa', 'kind', 'name', 'type', 'size', 'side', 'nat', 'loc', 'flex', 'attached', 'deployment', 'listing')


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
    v['unseen'] = 0
    if seat in SIDES:
        v['undo'][other(seat)] = []
        v['units'], v['unseen'] = seen_units(v['units'], seat, secret_setup(state))
    for u in v['units'].values():
        u.update(face(u))
        listing = state['deployments'][u['deployment']]['listings'][u['listing']]
        if listing.get('text') and listing.get('oa') == u['oa'] and u['attached'] is None:
            u['detail'] = listing['text']
    here = sequence.current(state)
    v['seat'] = seat
    v['now'] = {'step': here['id'], 'title': here['title'], 'case': here['case'],
                'waiting': sorted(sequence.waiting(state)),
                'allowed': registry.allowed(state, seat) if seat in SIDES else []}
    v['log'] = [e for e in (visible(ev, seat, state) for ev in log) if e is not None]
    return v


def seen_units(units, seat, setup):
    """The units seat sees, and how many of the other side's counters it doesn't:
    those placed in secret in the Set-up Stage (no secret how many: the scenario
    lists them)."""
    out, unseen = {}, 0
    for uid, u in units.items():
        if u['side'] == seat:
            out[uid] = u
        elif u['attached'] is None:
            if setup and u['flex']:
                unseen += 1
            else:
                out[uid] = {k: u[k] for k in FACE if k in u}
    return out, unseen


def visible(ev, seat, state):
    """The event as the seat may see it, or None."""
    hiding = seat in SIDES and secret_setup(state)
    if hiding and secret(ev) and ev['by'] != seat:
        return None
    drop = {'game-created': {'state'}, 'seat-taken': {'key'}}.get(ev['type'], set())
    if hiding:
        drop = drop | {'seq'}  # the gaps between the numbers would count the other side's placements
    return {k: x for k, x in ev.items() if k not in drop} if drop else ev
