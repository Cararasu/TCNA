"""Seats: who plays which side.

There are no accounts. Taking a seat gives the player a token, which the
browser keeps and sends with every request. The state holds only the token's
hash (the seat's key), so neither a saved game nor a view gives a token away.
The tokens keep players in their own seats; they are not security.

join is internal: the server gives it (games.py), with the key of a token it
has just made, and a player cannot send it as a command.
"""
import hashlib
import hmac
import secrets

from .commands import Refused, command
from .events import applies, event
from .state import SEATS

NAME_LENGTH = 40


def new_token():
    return secrets.token_urlsafe(24)


def key(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def seat_of(state, token):
    """The seat the token sits in, or None."""
    if not isinstance(token, str) or not token:
        return None
    k = key(token)
    for seat, x in state['seats'].items():
        if x and hmac.compare_digest(x['key'], k):
            return seat
    return None


def check_free(state, seat):
    """Refuses unless the seat can be taken. The referee sees both sides'
    set-up, so only sandbox games, which are for trying things out, have one."""
    if seat not in SEATS:
        raise Refused(f'There is no seat {seat!r}.')
    if seat == 'referee' and not state['sandbox']:
        raise Refused('Only sandbox games have a referee seat: the referee sees both sides\' set-up.')
    if state['seats'][seat]:
        raise Refused(f'The {seat} seat is taken.')


@command('join', anyone=True, internal=True)
def join(ctx, seat, name, key):
    check_free(ctx.state, seat)
    name = ' '.join(str(name or '').split())[:NAME_LENGTH] or seat
    yield event('seat-taken', seat=seat, name=name, key=key)


@applies('seat-taken')
def _taken(state, ev):
    state['seats'][ev['seat']] = {'name': ev['name'], 'key': ev['key']}
