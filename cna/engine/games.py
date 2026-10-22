"""Open games: commands run one at a time, are saved, and wake those waiting.

Games opens a saved game the first time it is asked for and keeps it open.
Each Game has one lock: a command runs under it (commands.run), its events
are saved before it is answered, and everyone waiting for a change is woken.
A command sent again with the same id, after a network error, is not run
again; the events it led to are returned instead.

Players are known by their seats; a seat is found from the player's token
(seats.py). A Game also keeps the last LOG_SIZE events, for the views' logs.

In the Set-up Stage each side places its units in secret, and even the number
of events would tell the other side how busy it has been. So a Game counts
each side's events the other may not see (hidden), and the event numbers a
seat is told (seq_for: its view, its stream, and meta.json for anyone) leave
those out.
"""
import sys
import threading
import traceback
from collections import OrderedDict, deque

from ..paths import SAVES
from . import events, logsheets, seats, setup, views
from .commands import COMMANDS, Broken, Refused, run
from .state import SIDES
from .store import SNAPSHOT_EVERY, Save, reported, saved_games

REMEMBERED = 1000  # command ids kept for recognising a command sent again
LOG_SIZE = 500


class NoGame(LookupError):
    """There is no saved game with this id. Not a KeyError, so that a save
    that fails to load with one is not taken for a game that isn't there."""


class Game:
    def __init__(self, save, registry=COMMANDS):
        self.save = save
        self.registry = registry
        self.changed = threading.Condition()
        self.broken = False  # a failed command's state couldn't be read again (submit)
        self._load()

    @property
    def id(self):
        return self.save.id

    def _load(self):
        self.state, read = self.save.load()
        # With no snapshot the whole log was read, and its lines are at hand.
        whole = read[0][0]['seq'] == 1 if read else False
        # From the log's last lines, not those after the snapshot: a command
        # whose line the snapshot covers may still be sent again. Each line
        # holds at least one event, so these lines hold the last LOG_SIZE events.
        n = max(REMEMBERED, LOG_SIZE)
        recent = read[-n:] if whole else self.save.last_batches(n)
        self.answered = OrderedDict()  # (side, command id) -> its events
        for evs in recent:
            self._remember(evs)
        self.log = deque((ev for evs in recent for ev in evs), maxlen=LOG_SIZE)
        # The Set-up Stage comes first, so while it lasts the whole log is set-up.
        self.hidden = dict.fromkeys(SIDES, 0)  # side -> its events the other side may not know of
        self.public_at = None  # the time of the last event anyone may know of
        if views.secret_setup(self.state):
            every = read if whole else self.save.batches()
        else:
            every = recent
        for evs in every:
            self._count(evs)
        self.meta_written = None
        self._write_meta()
        self.broken = False

    def _check(self):
        """Reads the save again if a failed command left the game unread;
        raises if it still can't be read. Call it holding the lock."""
        if self.broken:
            self._load()

    def _remember(self, evs):
        if evs[0].get('cmd') is None:
            return
        self.answered[(evs[0]['by'], evs[0]['cmd'])] = evs
        while len(self.answered) > REMEMBERED:
            self.answered.popitem(last=False)

    def _count(self, evs):
        """Counts one command's events among the hidden ones or not; the
        state is the one after them."""
        if not views.secret_setup(self.state):
            self.hidden = dict.fromkeys(SIDES, 0)
        else:
            secret = [ev for ev in evs if views.secret(ev)]
            for ev in secret:
                self.hidden[ev['by']] += 1
            if len(secret) == len(evs):
                return
        self.public_at = evs[-1]['at']

    def _write_meta(self):
        """Rewrites meta.json if what anyone may know has changed. A failure
        is reported, and it is tried again with the next command."""
        m = (self.seq_for(None), self.public_at)
        if m != self.meta_written and reported(self.save.meta_path, self.save.write_meta, self.state,
                                               updated=m[1], seq=m[0]):
            self.meta_written = m

    def submit(self, cmd, side, internal=False):
        """Runs a command given by `side` and saves its events. Returns the
        events, or raises Refused and changes nothing."""
        with self.changed:
            self._check()
            key = (side, cmd.get('id'))
            if cmd.get('id') is not None and key in self.answered:
                return self.answered[key]
            try:
                evs = run(self.state, cmd, side, self.registry, internal=internal)
            except Broken:
                self._reload()
                raise
            # Any other error, Refused or not, came before the first event (run
            # raises Broken after it), so nothing changed and nothing is read again.
            if evs:
                try:
                    self.save.append(self.state, evs)
                except Exception:  # the line wasn't written: the state is ahead of the log
                    self._reload()
                    raise
                self._count(evs)
                self._write_meta()
                self._remember(evs)
                self.log.extend(evs)
                self.changed.notify_all()
            return evs

    def _reload(self):
        """After a command failed once its events were applied: the state may
        be ahead of the log, so it is read again, and the command was not done.
        If that fails too, the caller raises the command's own error, and the
        game is read again before it is next used (_check)."""
        self.broken = True
        try:
            self._load()
        except Exception:
            print(f'could not read game {self.id} again after a failed command:', file=sys.stderr)
            traceback.print_exc()

    def join(self, seat, name):
        """Takes a free seat. Returns the player's token, or raises Refused."""
        token = seats.new_token()
        self.submit({'id': None, 'type': 'join', 'args': {'seat': seat, 'name': name, 'key': seats.key(token)}},
                    None, internal=True)
        return token

    def seat_of(self, token):
        with self.changed:
            self._check()
            return seats.seat_of(self.state, token)

    def seq_for(self, seat):
        """How many events the seat may know of: in the Set-up Stage, the other
        side's placements are left out. None: anyone, as the game list shows.
        The number never goes down."""
        with self.changed:
            if seat == 'referee':
                return self.state['seq']
            return self.state['seq'] - sum(n for side, n in self.hidden.items() if side != seat)

    def view(self, seat):
        with self.changed:
            self._check()
            return views.view(self.state, seat, self.log, self.registry, seq=self.seq_for(seat))

    def log_sheet(self, seat, uid):
        """The TOE Log Sheet of one of the seat's counters (logsheets.py); raises Refused."""
        with self.changed:
            self._check()
            return logsheets.log_sheet(self.state, seat, uid)

    def visible(self, evs, seat):
        """The events as the seat may see them."""
        with self.changed:
            return [e for e in (views.visible(ev, seat, self.state) for ev in evs) if e is not None]

    def preview(self, cmd, seat):
        """The events the command would lead to, worked out on the seat's view;
        raises Refused or DiceNeeded. Nothing is saved."""
        with self.changed:
            self._check()
            v = views.view(self.state, seat, (), self.registry, seq=self.seq_for(seat))
        return run(v, cmd, seat, self.registry, preview=True)  # the view is a copy already

    def wait(self, after, timeout=None, seat=None):
        """Waits until the seat (seq_for) may know of an event after number
        `after`, or for `timeout` seconds. Returns the seat's number."""
        with self.changed:
            self.changed.wait_for(lambda: self.seq_for(seat) > after, timeout)
            return self.seq_for(seat)


class Games:
    """The saved games in one folder, opened as they are asked for."""

    def __init__(self, root=SAVES, registry=COMMANDS, snapshot_every=SNAPSHOT_EVERY):
        self.root = root
        self.registry = registry
        self.snapshot_every = snapshot_every
        self.open = {}
        self.loading = {}  # game id -> the lock held while the game is loaded
        self.lock = threading.Lock()

    def create(self, scenario, seat=None, **choices):
        """A new game (setup.new_game takes the choices), saved and open.
        seat: the one its creator will take; a seat that can't be taken
        refuses the game (Refused) before anything is saved."""
        for _ in range(20):
            state = setup.new_game(scenario, **choices)
            if seat is not None:
                seats.check_free(state, seat)
            first = events.created(state)
            try:
                save = Save.create(self.root, first, self.snapshot_every)
            except FileExistsError:
                if choices.get('game_id'):
                    raise
                continue
            game = Game(save, self.registry)
            with self.lock:
                return self.open.setdefault(game.id, game)
        raise RuntimeError('no free game id')

    def get(self, game_id):
        """The open game; NoGame if there is none, OldSave if it can't be read.
        A game is loaded under a lock of its own, so other games needn't wait."""
        while True:
            with self.lock:
                if game_id in self.open:
                    return self.open[game_id]
                loading = self.loading.setdefault(game_id, threading.Lock())
            with loading:
                with self.lock:
                    if game_id in self.open:
                        return self.open[game_id]
                    if self.loading.get(game_id) is not loading:
                        continue  # the load this waited for failed and gave up its lock: wait on the new one
                return self._open(game_id, loading)

    def _open(self, game_id, loading):
        """Loads a game, holding its `loading` lock."""
        game = None
        try:
            try:
                save = Save(self.root, game_id, self.snapshot_every)
            except ValueError:
                raise NoGame(game_id) from None
            if not save.exists():
                raise NoGame(game_id)
            game = Game(save, self.registry)
        finally:
            with self.lock:
                if self.loading.get(game_id) is loading:
                    del self.loading[game_id]
                if game is not None:
                    game = self.open.setdefault(game_id, game)
        return game

    def list(self):
        return saved_games(self.root)
