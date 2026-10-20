"""The commands that move a game along the sequence of play, and their events.

  end-step     a side is done with the current step. A step that waits for
               both sides goes on once both are done.
  resume-step  takes that back, while the other side is still at it
  set-order    the side with the Initiative chooses to be Player A or B for
               this OpStage (5.2 III.A, 7.11)
  repeat-loop  Player A goes round the Movement and Combat Phase again
               instead of ending it (5.2 III.G); given in its last segment.
               Only sandbox games have it so far: until the movement rules
               come there is nothing to go round for, and offering it would
               stop the clock in every player turn.

A step can refuse to be ended too soon: @ready registers the check, for
example that a side has placed all its units before ending the Set-up Stage.
The Initiative Declaration Phase is never ended with end-step: set-order ends it.
"""
import copy

from ..rules import implements
from . import sequence
from .commands import Refused, command
from .events import applies, event
from .state import SIDES, other

READY = {}  # step id -> check(state, side) that refuses ending the step too soon


def ready(step_id):
    """Registers the check that a side may end this step."""
    def register(fn):
        if step_id in READY:
            raise ValueError(f'{step_id} already has a check that it may be ended')
        READY[step_id] = fn
        return fn
    return register


def advanced(ctx, repeat=False):
    """The event moving the clock past the current step."""
    c, passed = sequence.advance(ctx.state, ctx.registry.has_work, repeat)
    return event('clock-advanced', clock=c, passed=passed)


@command('end-step', not_steps={
    'initiative-declaration': ('Declare the order first: choose to be Player A or Player B.', '7.11')})
def end_step(ctx):
    check = READY.get(ctx.state['clock']['step'])
    if check:
        check(ctx.state, ctx.side)
    if sequence.waiting(ctx.state) - {ctx.side}:
        yield event('side-done', side=ctx.side)
    else:
        yield advanced(ctx)


@command('resume-step', ended=True)
def resume_step(ctx):
    yield event('side-resumed', side=ctx.side)


@command('set-order', steps={'initiative-declaration'})
@implements('7.11')
@implements('7.12', partial=True)  # the Initiative holds through the Game-Turn; determining it comes in M2
def set_order(ctx, player):
    if player not in ('A', 'B'):
        raise Refused('Choose to be Player A or Player B.', '7.11')
    first = ctx.side if player == 'A' else other(ctx.side)
    yield event('order-set', order={'A': first, 'B': other(first)})
    yield advanced(ctx)


@command('repeat-loop', steps={'reserve-release'},
         available=lambda s: s['sandbox'] and s['clock']['player'] == 'A')
def repeat_loop(ctx):
    yield advanced(ctx, repeat=True)


@applies('clock-advanced')
def _advanced(state, ev):
    state['clock'] = copy.deepcopy(ev['clock'])
    state['undo'] = {side: [] for side in SIDES}


@applies('side-done')
def _done(state, ev):
    state['clock']['done'][ev['side']] = True


@applies('side-resumed')
def _resumed(state, ev):
    state['clock']['done'][ev['side']] = False


@applies('order-set')
def _order(state, ev):
    state['clock']['order'] = dict(ev['order'])
