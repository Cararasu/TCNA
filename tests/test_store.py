"""Saving and loading games, and open games (store.py, games.py)."""
import contextlib
import copy
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from cna.engine import events
from cna.engine import games as games_module
from cna.engine.commands import COMMANDS, Broken, Refused
from cna.engine.events import event
from cna.engine.games import Games, NoGame
from cna.engine.store import OldSave, Save, read_json, write_json

TEST = COMMANDS.extended()


@TEST.command('test-break', anyone=True)
def breaks(ctx):
    yield event('test-broke')
    raise RuntimeError('a bug')


@TEST.command('test-fail-early', anyone=True)
def fails_early(ctx):
    raise RuntimeError('a bug before any event')
    yield  # a handler: a generator


@events.applies('test-broke')
def _broke(state, ev):
    state['units'].clear()


class Saving(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.games = Games(self.root, TEST, snapshot_every=7)
        self.game = self.games.create('graziani', seed='test-seed')
        self.n = 0

    def tearDown(self):
        self.tmp.cleanup()

    def give(self, side, type_, game=None, **args):
        self.n += 1
        return (game or self.game).submit({'id': f'c{self.n}', 'type': type_, 'args': args}, side)

    def shuffle(self, times):
        """Places a pooled Axis unit and takes it back, `times` times: two commands each."""
        unit = next(u['id'] for u in self.game.state['units'].values()
                    if u['side'] == 'axis' and u['loc']['kind'] == 'pool')
        some_hex = next(u['loc'] for u in self.game.state['units'].values() if u['loc']['kind'] == 'hex')
        for _ in range(times):
            self.give('axis', 'place-unit', unit=unit, loc=some_hex)
            self.give('axis', 'undo')

    def log(self):
        return [ev for line in self.game.save.log.read_text(encoding='utf-8').splitlines()
                for ev in json.loads(line)]

    def reopened(self):
        return Games(self.root, TEST, snapshot_every=7).get(self.game.id)

    def test_snapshot_plus_events_is_a_full_replay(self):
        self.shuffle(20)
        snap = read_json(self.game.save.snapshot_path)
        self.assertGreater(snap['state']['seq'], 1)
        self.assertLess(snap['state']['seq'], self.game.state['seq'])
        self.assertEqual(events.replay(self.log()), self.game.state)
        self.assertEqual(self.reopened().state, self.game.state)

    def test_a_restart_continues_the_game(self):
        self.shuffle(3)
        again = self.reopened()
        self.assertEqual(again.state, self.game.state)
        self.give('cw', 'place-unit', game=again, unit=self.pooled('cw', again), loc=self.some_hex(again))
        self.assertEqual(self.reopened().state, again.state)

    def test_a_last_line_cut_short_is_dropped(self):
        self.shuffle(2)
        before = self.game.state
        with open(self.game.save.log, 'ab') as f:
            f.write(b'[{"type":"unit-placed","se')
        again = self.reopened()
        self.assertEqual(again.state, before)
        self.give('cw', 'place-unit', game=again, unit=self.pooled('cw', again), loc=self.some_hex(again))
        self.assertEqual(events.replay(self.log()), again.state)
        self.assertEqual(self.reopened().state, again.state)

    def pooled(self, side, game):
        return next(u['id'] for u in game.state['units'].values() if u['side'] == side and u['loc']['kind'] == 'pool')

    def some_hex(self, game):
        return next(u['loc'] for u in game.state['units'].values() if u['loc']['kind'] == 'hex')

    def test_a_damaged_line_inside_the_log_is_an_error(self):
        self.shuffle(1)
        lines = self.game.save.log.read_bytes().split(b'\n')
        lines[1] = lines[1][:-5]
        self.game.save.log.write_bytes(b'\n'.join(lines))
        self.game.save.snapshot_path.unlink(missing_ok=True)
        with self.assertRaises(ValueError):
            self.reopened()

    def test_a_line_that_is_not_a_list_of_events_is_an_error(self):
        self.shuffle(1)
        self.game.save.snapshot_path.unlink(missing_ok=True)
        for bad in (b'{}', b'[]', b'[1]', b'[{"type": "x"}]'):
            with self.subTest(bad=bad):
                lines = self.game.save.log.read_bytes().split(b'\n')
                self.game.save.log.write_bytes(b'\n'.join([*lines[:2], bad, *lines[3:]]))
                with self.assertRaisesRegex(ValueError, 'damaged'):
                    self.reopened()

    def test_a_snapshot_that_does_not_fit_the_log_is_ignored(self):
        self.shuffle(5)
        snap = read_json(self.game.save.snapshot_path)
        write_json(self.game.save.snapshot_path, {**snap, 'offset': snap['offset'] - 3})
        self.assertEqual(self.reopened().state, self.game.state)

    def test_a_save_from_another_version_is_refused(self):
        save = self.game.save
        lines = save.log.read_bytes().split(b'\n')
        first = json.loads(lines[0])
        first[0]['state']['version'] += 1  # the version the game-created event says
        save.log.write_bytes(b'\n'.join([json.dumps(first).encode(), *lines[1:]]))
        meta = read_json(save.meta_path)
        write_json(save.meta_path, {**meta, 'version': meta['version'] + 1})
        with self.assertRaises(OldSave):
            self.reopened()
        listed = Games(self.root).list()
        self.assertEqual([(m['id'], m['old']) for m in listed], [(self.game.id, True)])

    def test_the_game_list(self):
        self.game.join('axis', 'Thomas')
        meta = Games(self.root).list()[0]
        self.assertEqual((meta['id'], meta['scenario'], meta['old'], meta['seq']),
                         (self.game.id, 'graziani', False, self.game.state['seq']))
        self.assertEqual(meta['where']['step'], 'setup')
        self.assertEqual(meta['seats']['axis'], {'name': 'Thomas'})
        self.assertIs(meta['sandbox'], False)  # only sandbox games have a referee seat to offer

    def test_a_snapshot_that_cannot_be_read_is_passed_over(self):
        self.shuffle(5)
        self.game.save.snapshot_path.write_text('{"offset": 12, "sta', encoding='utf-8')
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(self.reopened().state, self.game.state)
        self.assertIn('the whole log is read', err.getvalue())

    def test_a_game_whose_meta_json_is_lost_still_loads(self):
        self.shuffle(1)
        self.game.save.meta_path.unlink()
        self.assertEqual(self.reopened().state, self.game.state)
        self.assertEqual([m['id'] for m in Games(self.root).list()], [self.game.id])  # written again

    def test_a_failed_create_leaves_the_id_free(self):
        with mock.patch('cna.engine.store._line', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.games.create('graziani', game_id='lost-game')
        self.assertFalse((self.root / 'lost-game').exists())
        self.assertEqual(self.games.create('graziani', game_id='lost-game').id, 'lost-game')

    def test_any_failure_once_events_are_applied_reloads_the_game(self):
        before = copy.deepcopy(self.game.state)
        with mock.patch.object(self.game.save, 'append', side_effect=TypeError('not JSON')):
            with self.assertRaises(TypeError):
                self.give('axis', 'place-unit', unit=self.pooled('axis', self.game), loc=self.some_hex(self.game))
        self.assertEqual(self.game.state, before)

    def test_a_load_that_fails_lets_the_next_one_load(self):
        again = Games(self.root, TEST, snapshot_every=7)
        real, started, go, made = games_module.Game, threading.Event(), threading.Event(), []

        def flaky(save, registry):
            made.append(save.id)
            if len(made) == 1:
                started.set()
                go.wait(5)
                raise OSError('the log is busy')
            return real(save, registry)

        failed, got = [], []

        def first():
            try:
                again.get(self.game.id)
            except OSError:
                failed.append(True)

        def later():
            got.append(again.get(self.game.id))
        with mock.patch.object(games_module, 'Game', flaky):
            threads = [threading.Thread(target=first)]
            threads[0].start()
            started.wait(5)
            threads.append(threading.Thread(target=later))  # waits for the first load
            threads[1].start()
            go.set()
            threads.append(threading.Thread(target=later))  # comes while the first fails
            threads[2].start()
            for t in threads:
                t.join(10)
        self.assertEqual(failed, [True])
        self.assertEqual(len(got), 2)
        self.assertIs(got[0], got[1])
        self.assertEqual(len(made), 2)  # the failed load, then one more
        self.assertEqual(again.loading, {})

    def test_the_game_list_does_not_tell_of_set_up_placements(self):
        before = Games(self.root).list()[0]
        self.shuffle(2)
        self.assertEqual(Games(self.root).list()[0], before)

    def test_a_command_is_done_once_its_line_is_written(self):
        """meta.json and the snapshot only save time: if they can't be written
        (Windows refuses to replace a file someone is reading), the command
        still counts, and they are written later."""
        def refuse(*args, **kwargs):
            raise PermissionError('in use')
        save = self.game.save
        save.write_meta, save.snapshot = refuse, refuse
        woken = []
        t = threading.Thread(target=lambda: woken.append(self.game.wait(self.game.state['seq'], 5, 'referee')))
        t.start()
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.game.join('cw', 'Ann')  # a change anyone may know of, so meta.json is due
            t.join()
            self.assertEqual(woken, [self.game.state['seq']])
            self.shuffle(4)  # past snapshot_every
        self.assertIn('could not write', err.getvalue())
        self.assertFalse(save.snapshot_path.exists())
        self.assertEqual(self.reopened().state, self.game.state)
        del save.write_meta, save.snapshot  # the class's own again
        self.game.join('axis', 'Thomas')
        self.assertEqual(Games(self.root).list()[0]['seats'], {'axis': {'name': 'Thomas'}, 'cw': {'name': 'Ann'},
                                                               'referee': None})
        self.shuffle(4)
        self.assertTrue(save.snapshot_path.exists())

    def test_a_file_being_read_is_replaced_once_it_is_free(self):
        path = self.root / 'busy.json'
        write_json(path, {'n': 1})
        f = open(path, encoding='utf-8')
        threading.Timer(0.05, f.close).start()
        write_json(path, {'n': 2})
        self.assertEqual(read_json(path), {'n': 2})
        self.assertEqual([p.name for p in self.root.glob('busy*')], ['busy.json'])

    def test_games_load_once_each(self):
        again = Games(self.root, TEST, snapshot_every=7)
        got = []
        threads = [threading.Thread(target=lambda: got.append(again.get(self.game.id))) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len({id(g) for g in got}), 1)
        self.assertEqual(again.loading, {})

    def test_a_command_sent_again_runs_once(self):
        unit, loc = self.pooled('axis', self.game), self.some_hex(self.game)
        cmd = {'id': 'once', 'type': 'place-unit', 'args': {'unit': unit, 'loc': loc}}
        first = self.game.submit(cmd, 'axis')
        seq = self.game.state['seq']
        self.assertEqual(self.game.submit(cmd, 'axis'), first)
        self.assertEqual(self.game.state['seq'], seq)
        self.assertEqual(self.reopened().submit(cmd, 'axis'), first)  # remembered across a restart

    def test_a_command_the_snapshot_covers_is_still_remembered(self):
        games = Games(self.root, TEST, snapshot_every=1)  # every command writes a snapshot
        game = games.create('graziani', seed='test-seed')
        cmd = {'id': 'once', 'type': 'place-unit', 'args': {'unit': self.pooled('axis', game), 'loc': self.some_hex(game)}}
        first = game.submit(cmd, 'axis')
        self.assertEqual(read_json(game.save.snapshot_path)['state']['seq'], game.state['seq'])
        again = Games(self.root, TEST, snapshot_every=1).get(game.id)
        self.assertEqual(again.submit(cmd, 'axis'), first)
        self.assertEqual(again.state['seq'], game.state['seq'])

    def test_the_log_is_read_from_the_end_of_the_file(self):
        self.shuffle(20)
        self.assertEqual(list(self.reopened().log), self.log()[-len(self.game.log):])

    def test_a_refused_command_saves_nothing(self):
        size = self.game.save.log.stat().st_size
        with self.assertRaises(Refused):
            self.give('cw', 'set-order', player='A')
        self.assertEqual(self.game.save.log.stat().st_size, size)

    def test_a_broken_command_is_undone_by_reloading(self):
        before = copy.deepcopy(self.game.state)
        with self.assertRaises(Broken):
            self.give(None, 'test-break')
        self.assertEqual(self.game.state, before)
        self.assertTrue(self.game.state['units'])

    def test_an_error_before_the_first_event_reads_nothing_again(self):
        with mock.patch.object(self.game, '_load') as load:
            with self.assertRaisesRegex(RuntimeError, 'before any event'):
                self.give(None, 'test-fail-early')
        load.assert_not_called()
        self.assertFalse(self.game.broken)

    def test_a_game_that_cannot_be_read_again_is_read_before_its_next_use(self):
        """If the reload after a broken command fails too, the command's own
        error is raised, and the game is read again before anything else."""
        before = copy.deepcopy(self.game.state)
        with mock.patch.object(self.game.save, 'load', side_effect=OSError('the disk is busy')),                 contextlib.redirect_stderr(io.StringIO()) as err:
            with self.assertRaises(Broken):
                self.give(None, 'test-break')
            self.assertTrue(self.game.broken)
            with self.assertRaises(OSError):
                self.game.view('axis')  # still unreadable: refused, not shown half-loaded
        self.assertIn('could not read game', err.getvalue())
        self.assertEqual(self.game.view('referee')['units'], before['units'])
        self.assertFalse(self.game.broken)
        self.assertEqual(self.game.state, before)

    def test_waiting_for_a_change(self):
        seq = self.game.state['seq']
        self.assertEqual(self.game.wait(seq, timeout=0.01), seq)
        got = []
        t = threading.Thread(target=lambda: got.append(self.game.wait(seq, timeout=5, seat='axis')))
        t.start()
        self.shuffle(1)  # Axis placements: only the Axis seat is told of them
        t.join()
        self.assertGreater(got[0], seq)

    def test_unknown_and_bad_ids(self):
        for bad in ('no-such-game', '../graziani', 'Graziani', ''):
            with self.assertRaises(NoGame):
                self.games.get(bad)
        with self.assertRaises(ValueError):
            Save(self.root, '../x')


if __name__ == '__main__':
    unittest.main()
