"""Events: what happened in a game. Only events change the state.

An event is a dict holding its type, its own fields, and the stamps the
command runner adds (STAMPS):

  seq  its number in the game, from 1
  cmd  the id of the command that caused it
  by   the side that gave the command
  at   the time, in UTC

An event that used dice holds them in `dice`, in the order rolled.

Each event type has one function that applies it, registered with @applies.
That function changes the state in place, and copies what it takes from the
event, so the state never shares data with the event log. A saved game is its
list of events: applying them in order, from game-created on, rebuilds it.
"""
import copy
from datetime import datetime, timezone

STAMPS = ('seq', 'cmd', 'by', 'at')
APPLY = {}


def event(type_, **fields):
    """A new event, before the runner stamps it."""
    clash = set(fields) & {'type', *STAMPS}
    if clash:
        raise ValueError(f'{type_}: {", ".join(sorted(clash))} are set by the runner')
    return {'type': type_, **fields}


def applies(type_):
    """Registers the function that applies events of this type."""
    def register(fn):
        if type_ in APPLY:
            raise ValueError(f'{type_} already has a function that applies it')
        APPLY[type_] = fn
        return fn
    return register


def apply(state, ev):
    try:
        fn = APPLY[ev['type']]
    except KeyError:
        raise ValueError(f'unknown event type {ev["type"]}') from None
    fn(state, ev)
    state['dice']['rolls'] += len(ev.get('dice', ()))
    state['seq'] = ev['seq']


def replay(evs):
    """The state the events lead to, starting with game-created."""
    state = {}
    for ev in evs:
        apply(state, ev)
    return state


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def created(state, at=None):
    """A game's first event, which holds its whole starting state."""
    return {**event('game-created', state=copy.deepcopy(state)), 'seq': 1, 'cmd': None, 'by': None,
            'at': at or now()}


@applies('game-created')
def _created(state, ev):
    state.clear()
    state.update(copy.deepcopy(ev['state']))
