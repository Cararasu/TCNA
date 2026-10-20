"""Commands: what a player asks for. The rules check a command, then either
refuse it or turn it into events.

A command is {id, type, args}. The id is chosen by the browser, so a command
sent twice runs only once (games.py). The type names a handler registered
with @command, and args are its keyword arguments.

A handler gets a Context and the args, and yields events. The runner applies
each event as soon as it is yielded, so the handler goes on with the state
after it. A handler refuses a command by raising Refused, and must do that
before it yields its first event: a later error leaves the state half changed,
and the runner raises Broken so that the game is loaded again from its log.

A preview runs a command on a copy of the player's view (views.py) and returns
the events it would lead to, without saving anything. No dice are rolled: a
command that needs them raises DiceNeeded instead.
"""
import copy
import inspect

from . import events, sequence
from .dice import Dice, DiceNeeded
from .state import SIDE_NAMES, SIDES


class Refused(Exception):
    """A command the rules do not allow, with the reason and the case behind it."""

    def __init__(self, message, case=None):
        super().__init__(message)
        self.message = message
        self.case = case


class Broken(RuntimeError):
    """A command failed after changing the state: the state must be loaded again."""


class Context:
    """What a handler works with: the state, the side giving the command, and the dice."""

    def __init__(self, state, side, registry, preview=False):
        self.state = state
        self.side = side
        self.registry = registry
        self.preview = preview
        self.dice = Dice(state, preview)

    def roll(self, n=1):
        return self.dice.roll(n)


class Command:
    def __init__(self, name, handler, *, steps, not_steps, anyone, ended, available, internal):
        self.name = name
        self.handler = handler
        self.steps = set(steps) if steps is not None else None  # None: any step
        self.not_steps = dict(not_steps or {})  # step id -> (why the command can't be given there, case)
        self.anyone = anyone  # given by anyone, not only by the sides acting in the step
        self.ended = ended  # given only by a side that has ended the step, instead of only by one that hasn't
        self.available = available  # state -> whether the command can be given at all, in this game and place
        self.internal = internal  # given by the server itself, never sent by a player

    def check(self, state, side):
        """Refuses the command if it cannot be given now by this side."""
        here = sequence.current(state)
        if self.steps is not None and here['id'] not in self.steps:
            raise Refused(f'{self.name} cannot be given in the {here["title"]}.', here['case'])
        if here['id'] in self.not_steps:
            raise Refused(*self.not_steps[here['id']])
        if self.available is not None and not self.available(state):
            raise Refused(f'{self.name} cannot be given here in this game.', here['case'])
        if self.anyone:
            return
        if side not in SIDES:
            raise Refused(f'{side} is not a side.')
        if side not in sequence.actors(state):
            raise Refused(f'The {SIDE_NAMES[side]} player does not act in the {here["title"]}.', here['case'])
        if state['clock']['done'][side] != self.ended:
            raise Refused(f'The {SIDE_NAMES[side]} player has {"not" if self.ended else "already"} ended '
                          f'the {here["title"]}.')


class Registry:
    """The commands of a game, by name."""

    def __init__(self, commands=()):
        self.commands = {c.name: c for c in commands}

    def command(self, name, *, steps=None, not_steps=None, anyone=False, ended=False, available=None,
                internal=False):
        """Registers a handler as the command `name`. not_steps: {step id: (message, case)},
        the steps the command is never given in, though steps=None."""
        def register(fn):
            if name in self.commands:
                raise ValueError(f'two commands are called {name}')
            self.commands[name] = Command(name, fn, steps=steps, not_steps=not_steps, anyone=anyone, ended=ended,
                                          available=available, internal=internal)
            return fn
        return register

    def extended(self):
        """A new registry holding these commands, for adding more."""
        return Registry(self.commands.values())

    def get(self, name):
        try:
            return self.commands[name]
        except KeyError:
            raise Refused(f'There is no command {name}.') from None

    def has_work(self, state):
        """Whether a command belonging to the current step can be given in it.
        Commands for any step (steps=None) don't count."""
        here = state['clock']['step']
        return any(c.steps is not None and here in c.steps and (c.available is None or c.available(state))
                   for c in self.commands.values())

    def allowed(self, state, side):
        """The names of the commands this side can give now."""
        out = []
        for c in self.commands.values():
            if c.internal:
                continue
            try:
                c.check(state, side)
            except Refused:
                continue
            out.append(c.name)
        return out


COMMANDS = Registry()
command = COMMANDS.command


def run(state, cmd, side, registry=COMMANDS, at=None, internal=False, preview=False):
    """Runs a command given by `side`: checks it, then applies the events it
    leads to. Returns those events, or raises Refused and changes nothing.
    internal: the server gives the command, so internal commands are allowed."""
    c = registry.get(cmd['type'])
    if c.internal and not internal:
        raise Refused(f'There is no command {c.name}.')
    c.check(state, side)
    args = cmd.get('args') or {}
    try:
        inspect.signature(c.handler).bind(None, **args)
    except TypeError as e:
        raise Refused(f'{c.name}: {e}') from None
    ctx = Context(state, side, registry, preview)
    at = at or events.now()
    done = []
    changed = False  # an event's apply has begun, so the state may be half changed
    try:
        for ev in c.handler(ctx, **args) or ():
            ctx.dice.record(ev)
            ev.update(seq=state['seq'] + 1, cmd=cmd.get('id'), by=side, at=at)
            changed = True
            events.apply(state, ev)
            done.append(ev)
        if ctx.dice.pending:
            raise RuntimeError(f'{c.name} rolled dice {ctx.dice.pending} that no event records')
    except Exception as e:
        if changed and not (preview and isinstance(e, DiceNeeded)):
            raise Broken(f'{c.name} failed after {len(done)} events: {e}') from e
        raise
    return done


def preview(view, cmd, side, registry=COMMANDS):
    """The events a command would lead to, worked out on a copy of the
    player's view. Raises Refused, or DiceNeeded; saves and changes nothing."""
    return run(copy.deepcopy(view), cmd, side, registry, preview=True)
