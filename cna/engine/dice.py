"""Dice: each roll follows from the game's seed and the number of dice rolled
before it, so a game can be replayed and checked roll by roll.

The seed is a secret: a player who knew it could work out every roll to come,
so no view of the game includes it.
"""
import hashlib
import secrets


def new_seed():
    return secrets.token_hex(16)


def die(seed, n):
    """Die number n (counting from 0) of the game with this seed: 1 to 6."""
    h = hashlib.sha256(f'{seed}:{n}'.encode()).digest()
    return int.from_bytes(h[:8], 'big') % 6 + 1


class DiceNeeded(Exception):
    """A preview reached a roll of the dice, which only the real command makes."""


class Dice:
    """The dice of one command. Every die rolled must be recorded, in order, in
    the `dice` of the event that uses it."""

    def __init__(self, state, preview=False):
        self.state = state
        self.preview = preview
        self.pending = []  # rolled, not yet in an event

    def roll(self, n=1):
        if self.preview:
            raise DiceNeeded(f'{n} {"die" if n == 1 else "dice"} to roll')
        first = self.state['dice']['rolls'] + len(self.pending)
        rolled = [die(self.state['dice']['seed'], first + i) for i in range(n)]
        self.pending.extend(rolled)
        return rolled

    def record(self, ev):
        """Checks that the event records the next dice rolled, and marks them recorded."""
        used = list(ev.get('dice', ()))
        if used != self.pending[:len(used)]:
            raise RuntimeError(f'{ev["type"]} records dice {used}, but the next dice rolled were '
                               f'{self.pending[:len(used)]}')
        del self.pending[:len(used)]
