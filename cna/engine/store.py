"""Saving games. Each game is a folder saves/<id>/ holding:

  events.jsonl   the event log: one line per command, a JSON list of its events,
                 appended and flushed to disk before the command is answered.
                 The first line holds game-created.
  snapshot.json  the state after some event, and where the next line starts;
                 rewritten every SNAPSHOT_EVERY events
  meta.json      what the game list shows, so it needn't load the game

Loading starts from the snapshot and applies the lines after it. A last line
cut short, because the server stopped while writing it, is dropped with its
whole command; anything else wrong in the log is an error.

A command is saved once its line is in the log. The snapshot and meta.json
only save time, so a failure to write them is reported, not raised, and
they are written again later. Loading needs neither: a snapshot that can't be
read is passed over, and a game is there if its log is.

Saves are not yet promised to load across versions: a save from another
EVENT_VERSION, as its game-created event says, is refused with OldSave.
"""
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

from . import events, sequence
from .state import EVENT_VERSION

SNAPSHOT_EVERY = 200
ID = re.compile(r'[a-z0-9][a-z0-9-]{0,63}')
REPLACE_TRIES = 6  # Windows refuses to replace a file someone is reading; it is free again soon


class OldSave(ValueError):
    """A game saved by a version of the program whose events this one doesn't read."""


def write_json(path, obj):
    """Writes a JSON file whole or not at all."""
    tmp = path.with_name(path.name + '.tmp')
    try:
        with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(REPLACE_TRIES):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == REPLACE_TRIES - 1:
                    raise
                time.sleep(0.005 * 2 ** attempt)
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def reported(what, fn, *args, **kwargs):
    """Calls fn; an OSError is printed rather than raised. Returns whether fn succeeded."""
    try:
        fn(*args, **kwargs)
        return True
    except OSError as e:
        print(f'could not write {what}: {e}', file=sys.stderr, flush=True)
        return False


def read_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def _events(raw):
    """One log line's events; ValueError if it isn't a list of events."""
    evs = json.loads(raw)
    if not (isinstance(evs, list) and evs and all(isinstance(ev, dict) and isinstance(ev.get('seq'), int)
                                                  and isinstance(ev.get('type'), str) for ev in evs)):
        raise ValueError('not a list of events')
    return evs


def _line(evs):
    return (json.dumps(evs, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')


class Save:
    """One game's folder."""

    def __init__(self, root, game_id, snapshot_every=SNAPSHOT_EVERY):
        if not isinstance(game_id, str) or not ID.fullmatch(game_id):
            raise ValueError(f'{game_id!r} is not a game id.')
        self.id = game_id
        self.dir = Path(root) / game_id
        self.log = self.dir / 'events.jsonl'
        self.snapshot_path = self.dir / 'snapshot.json'
        self.meta_path = self.dir / 'meta.json'
        self.snapshot_every = snapshot_every
        self.size = None  # bytes of the log, once loaded
        self.since_snapshot = 0
        self.created = None  # when the game was created, once loaded

    @classmethod
    def create(cls, root, first, snapshot_every=SNAPSHOT_EVERY):
        """A new save holding the game-created event; FileExistsError if the id
        is taken. meta.json is the caller's (write_meta), as with append."""
        save = cls(root, first['state']['id'], snapshot_every)
        save.dir.mkdir(parents=True, exist_ok=False)
        try:
            with open(save.log, 'wb') as f:
                f.write(_line([first]))
                f.flush()
                os.fsync(f.fileno())
                save.size = f.tell()
        except BaseException:
            shutil.rmtree(save.dir, ignore_errors=True)  # no game, so the id is free again
            raise
        save.created = first['at']
        return save

    def exists(self):
        return self.log.exists()

    def first(self):
        """The log's first event, game-created."""
        with open(self.log, 'rb') as f:
            line = f.readline()
        try:
            return _events(line)[0]
        except ValueError as e:
            raise ValueError(f'{self.log}: the first line is damaged: {e}') from None

    def write_meta(self, state, updated=None, seq=None):
        """meta.json, which anyone may read: seq and updated are the number and
        time of the last event everyone may know of (games.py)."""
        write_json(self.meta_path, {
            'id': state['id'], 'scenario': state['scenario'], 'version': state['version'],
            'sandbox': state['sandbox'], 'created': self.created, 'updated': updated or self.created,
            'seq': state['seq'] if seq is None else seq,
            'seats': {seat: x and {'name': x['name']} for seat, x in state['seats'].items()}, 'where': sequence.where(state['clock'])})

    def load(self):
        """The saved state, and the commands' event lists read after the snapshot."""
        first = self.first()
        version = first.get('state', {}).get('version')
        if version != EVENT_VERSION:
            raise OldSave(f'{self.id} was saved by another version of the program (event version {version}; '
                          f'this one reads version {EVENT_VERSION}).')
        self.created = first['at']
        start, offset = {}, 0
        try:
            snap = read_json(self.snapshot_path)
            start, offset = snap['state'], snap['offset']
            if not isinstance(start, dict) or not isinstance(offset, int) or offset < 0:
                raise ValueError('not a snapshot')
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError, TypeError) as e:
            print(f'could not read {self.snapshot_path}, so the whole log is read: {e}', file=sys.stderr, flush=True)
            start, offset = {}, 0
        try:
            return self._read(start, offset)
        except _Mismatch:
            return self._read({}, 0)  # the snapshot doesn't fit the log: replay it all

    def _read(self, state, offset):
        with open(self.log, 'rb') as f:
            if offset > f.seek(0, os.SEEK_END):
                raise _Mismatch()
            f.seek(offset)
            data = f.read()
        lines = data.split(b'\n')
        cut = lines.pop()  # whatever follows the last newline: empty, or a line cut short
        batches = []
        for n, raw in enumerate(lines):
            try:
                evs = _events(raw)
            except ValueError as e:
                if n == 0 and offset:
                    raise _Mismatch() from None
                raise ValueError(f'{self.log}: line {n + 1} after byte {offset} is damaged: {e}') from None
            if evs[0]['seq'] != state.get('seq', 0) + 1:
                if n == 0 and offset:
                    raise _Mismatch()
                raise ValueError(f'{self.log}: event {evs[0]["seq"]} follows event {state.get("seq", 0)}')
            for ev in evs:
                events.apply(state, ev)
            batches.append(evs)
        self.size = offset + len(data) - len(cut)
        if cut:
            with open(self.log, 'r+b') as f:
                f.truncate(self.size)
        self.since_snapshot = sum(len(b) for b in batches)
        return state, batches

    def append(self, state, evs):
        """Saves one command's events; `state` is the state after them. Raises
        OSError if their line can't be written, and then the command is not
        saved. A snapshot that can't be written is reported and tried again
        with the next command. meta.json is the caller's (write_meta)."""
        if self.size is None:
            raise RuntimeError('load the save before appending to it')
        with open(self.log, 'ab') as f:
            f.write(_line(evs))
            f.flush()
            os.fsync(f.fileno())
            self.size = f.tell()
        self.since_snapshot += len(evs)
        if self.since_snapshot >= self.snapshot_every:
            reported(self.snapshot_path, self.snapshot, state)

    def batches(self):
        """The event lists of every line of the log, oldest first."""
        if self.size is None:
            raise RuntimeError('load the save before reading it')
        with open(self.log, 'rb') as f:
            data = f.read(self.size)
        return [json.loads(line) for line in data.split(b'\n')[:-1]]

    def last_batches(self, n):
        """The event lists of the log's last n lines, oldest first, read from
        the end of the log rather than the whole of it."""
        if self.size is None:
            raise RuntimeError('load the save before reading its last lines')
        data, pos, chunk = b'', self.size, 1 << 16
        with open(self.log, 'rb') as f:
            while pos > 0 and data.count(b'\n') <= n:
                step = min(chunk, pos)
                pos -= step
                f.seek(pos)
                data = f.read(step) + data
                chunk *= 2
        lines = data.split(b'\n')[:-1]  # the log ends with a newline
        if pos > 0:
            lines = lines[1:]  # may begin partway through a line
        return [json.loads(line) for line in lines[-n:]] if n > 0 else []

    def snapshot(self, state):
        write_json(self.snapshot_path, {'offset': self.size, 'state': state})
        self.since_snapshot = 0


class _Mismatch(Exception):
    pass


def saved_games(root):
    """The meta of each saved game, newest first; `old` marks those from another version."""
    out = []
    for p in Path(root).glob('*/meta.json'):
        try:
            meta = read_json(p)
        except (OSError, ValueError):
            continue
        out.append({**meta, 'old': meta.get('version') != EVENT_VERSION})
    return sorted(out, key=lambda m: m.get('updated') or '', reverse=True)
