"""The map as the rules see it: the joined map's hexes, the section labels the
rulebook uses for them (A4827), and the off-map boxes.

A place is a loc: {kind: 'hex', id} on the joined map, {kind: 'zone', id} for
an off-map box, or {kind: 'pool'} for a unit its player has yet to place.
"""
import json
import threading

from ..joined import joined
from ..paths import OFFMAP

_LOCK = threading.Lock()
_BOARD = (None, None)


class Board:
    def __init__(self, j):
        self.labels = {f'{m}{hid}': g for g, inst in j.hexes.items() for m, hid in inst}
        self.hexes = set(j.hexes)
        with open(OFFMAP, encoding='utf-8') as f:
            self.zones = {z['id'] for z in json.load(f)['zones']}

    def hex_of_label(self, label):
        """The joined hex id of a section label, or None."""
        return self.labels.get(label.replace(' ', ''))

    def is_place(self, loc):
        """Whether loc is a hex, an off-map box or the pool."""
        if not isinstance(loc, dict):
            return False
        kind, id_ = loc.get('kind'), loc.get('id')
        if kind == 'pool':
            return set(loc) == {'kind'}
        return (set(loc) == {'kind', 'id'} and isinstance(kind, str) and isinstance(id_, str)
                and id_ in {'hex': self.hexes, 'zone': self.zones}.get(kind, ()))


def board():
    """The board, rebuilt when the joined map is."""
    global _BOARD
    j = joined()
    with _LOCK:
        if _BOARD[0] is not j:
            _BOARD = (j, Board(j))
        return _BOARD[1]
