"""
Fork RP2: offline tests for the reliability pass 1 fixes (journal reading and game JSON files).
See FORK_CHANGELOG.md. Run: python -m unittest discover -s test/offline -v
"""
import offline_stubs  # noqa: F401  (must be first: installs stand-ins for Windows-only modules)

import functools
import json
import os
import tempfile
import threading
import time
import unittest
from unittest import mock

import EDJournal
import JsonFile
import StatusParser as status_module

JOURNAL_DIR = offline_stubs.JOURNAL_DIR
OLD = time.time() - 1000  # A modification time safely in the past.


def event(name, **fields):
    return json.dumps({'timestamp': '2026-11-08T12:00:00Z', 'event': name, **fields}) + '\n'


def write_journal(name, lines, mtime=None):
    path = os.path.join(JOURNAL_DIR, name)
    with open(path, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def append(path, text):
    with open(path, 'a', encoding='utf-8') as f:
        f.write(text)


def append_bytes(path, data):
    with open(path, 'ab') as f:
        f.write(data)


def no_callback(msg, body=None):
    pass


class JournalTests(unittest.TestCase):

    def setUp(self):
        for name in os.listdir(JOURNAL_DIR):
            os.remove(os.path.join(JOURNAL_DIR, name))

    def journal(self, cb=no_callback):
        """ Creates an EDJournal and closes its file afterwards (Windows can't delete open files). """
        jn = EDJournal.EDJournal(cb=cb)
        self.addCleanup(lambda: jn.log_file.close() if jn.log_file else None)
        return jn

    def force_rescan(self, jn):
        jn._latest_log_checked_at = 0.0

    def test_new_journal_after_restart_is_read_once(self):
        """ RP1: the original replayed a new journal from line 1 on every call, inflating counters. """
        write_journal('Journal.A.01.log', [event('Fileheader', part=1), event('MissionCompleted')], mtime=OLD)
        jn = self.journal()
        self.assertEqual(jn.ship_state()['mission_completed'], 1)

        write_journal('Journal.B.01.log', [event('Fileheader', part=1), event('MissionCompleted')], mtime=OLD + 100)
        self.force_rescan(jn)
        for _ in range(5):
            jn.ship_state()
        self.assertEqual(jn.ship_state()['mission_completed'], 2)
        self.assertTrue(jn.current_log.endswith('Journal.B.01.log'))

    def test_folder_scan_is_cached(self):
        """ RP1: the original listed the journal folder on every ship_state() call. """
        write_journal('Journal.A.01.log', [event('Fileheader', part=1)], mtime=OLD)
        jn = self.journal()
        scans = []
        real_scan = EDJournal.EDJournal._scan_for_latest_log
        jn._scan_for_latest_log = lambda path: scans.append(path) or real_scan(path)
        for _ in range(2000):
            jn.ship_state()
        self.assertLessEqual(len(scans), 1)

        write_journal('Journal.B.01.log', [event('Fileheader', part=1)], mtime=OLD + 50)
        jn.ship_state()
        self.assertTrue(jn.current_log.endswith('Journal.A.01.log'), "picked up before the rescan interval")
        jn._latest_log_checked_at -= EDJournal.JOURNAL_RESCAN_INTERVAL_SEC
        jn.ship_state()
        self.assertTrue(jn.current_log.endswith('Journal.B.01.log'), "not picked up after the rescan interval")

    def test_continued_event_switches_journal_immediately(self):
        part1 = write_journal('Journal.C.01.log', [event('Fileheader', part=1)], mtime=OLD)
        jn = self.journal()
        # Same order as the game: 'Continued' goes to part 1, then part 2 is created.
        append(part1, event('Continued', Part=2))
        time.sleep(0.02)
        write_journal('Journal.C.02.log', [event('Fileheader', part=2), event('MissionRedirected')])
        jn.ship_state()
        self.assertTrue(jn.current_log.endswith('Journal.C.01.log'))
        jn.ship_state()
        self.assertTrue(jn.current_log.endswith('Journal.C.02.log'))
        self.assertEqual(jn.ship['mission_redirected'], 1)

    def test_same_timestamp_picks_later_part(self):
        write_journal('Journal.T.01.log', [event('Fileheader', part=1)], mtime=OLD)
        write_journal('Journal.T.02.log', [event('Fileheader', part=2)], mtime=OLD)
        self.assertTrue(EDJournal.EDJournal._scan_for_latest_log(JOURNAL_DIR).endswith('Journal.T.02.log'))

    def test_half_written_line_waits_for_the_rest(self):
        """ RP1: the original raised on a partial line, stopping the assist. """
        path = write_journal('Journal.D.01.log', [event('Fileheader', part=1)], mtime=OLD)
        jn = self.journal()
        line = event('MissionCompleted')
        append(path, line[:20])
        jn.ship_state()  # must not raise
        self.assertEqual(jn.ship['mission_completed'], 0)
        time.sleep(0.01)
        append(path, line[20:])
        jn.ship_state()
        self.assertEqual(jn.ship['mission_completed'], 1)

    def test_write_split_inside_multibyte_character(self):
        """ RP1: the original raised UnicodeDecodeError, stopping the assist. """
        path = write_journal('Journal.U.01.log', [event('Fileheader', part=1)], mtime=OLD)
        jn = self.journal()
        raw = (json.dumps({'timestamp': '2026-11-08T12:00:00Z', 'event': 'MissionCompleted',
                           'Name_Localised': 'Gärtnerei Überführung'}, ensure_ascii=False) + '\n').encode('utf-8')
        split_at = raw.index('ä'.encode('utf-8')) + 1
        append_bytes(path, raw[:split_at])
        jn.ship_state()  # must not raise
        time.sleep(0.01)
        append_bytes(path, raw[split_at:])
        jn.ship_state()
        self.assertEqual(jn.ship['mission_completed'], 1)

    def test_corrupt_line_is_skipped(self):
        path = write_journal('Journal.E.01.log', [event('Fileheader', part=1)], mtime=OLD)
        jn = self.journal()
        append(path, '{"event": "Broken", \n' + event('MissionCompleted'))
        jn.ship_state()
        self.assertEqual(jn.ship['mission_completed'], 1)

    def test_concurrent_readers_count_every_event_once(self):
        """ RP1: the AP and SCO threads shared one file handle with no lock. """
        path = write_journal('Journal.F.01.log', [event('Fileheader', part=1)], mtime=OLD)
        jn = self.journal()
        errors = []
        stop = threading.Event()

        def reader():
            while not stop.is_set():
                try:
                    jn.ship_state()
                except Exception as e:
                    errors.append(repr(e))

        readers = [threading.Thread(target=reader) for _ in range(4)]
        for t in readers:
            t.start()
        total = 300
        for i in range(total):
            text = event('MissionCompleted')
            if i % 3 == 0:  # some lines arrive in two writes
                append(path, text[:15])
                append(path, text[15:])
            else:
                append(path, text)
        time.sleep(0.2)
        stop.set()
        for t in readers:
            t.join()
        jn.ship_state()
        self.assertEqual(errors, [])
        self.assertEqual(jn.ship['mission_completed'], total)

    def test_gui_callback_runs_after_lock_is_released(self):
        """ RP1: callbacks made while holding the lock could deadlock against the GUI thread. """
        path = write_journal('Journal.G.01.log', [event('Fileheader', part=1)], mtime=OLD)
        seen = []
        holder = {}
        jn = self.journal(cb=lambda msg, body=None: seen.append((msg, body, holder['jn']._lock._is_owned())))
        holder['jn'] = jn
        real_parse = jn.parse_line

        def parse_and_log(log):
            real_parse(log)
            if log.get('event') == 'MissionCompleted':
                jn.ap_ckb('log', 'mission done')

        jn.parse_line = parse_and_log
        time.sleep(0.01)
        append(path, event('MissionCompleted'))
        jn.ship_state()
        self.assertEqual(seen, [('log', 'mission done', False)])


class GameJsonTests(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='edap-test-json-')
        self.path = os.path.join(self.dir, 'Status.json')

    def write(self, text):
        with open(self.path, 'w') as f:
            f.write(text)

    def test_unreadable_file_gives_up(self):
        """ RP1: the original retried forever. """
        self.write('{"half": ')
        self.assertIsNone(JsonFile.read_game_json(self.path, 'Status.json', max_attempts=3, initial_backoff=0.01))

    def test_file_fixed_during_retries_is_read(self):
        self.write('{"half": ')

        def fix_later():
            time.sleep(0.15)
            self.write('{"ok": true}')

        threading.Thread(target=fix_later).start()
        self.assertEqual(JsonFile.read_game_json(self.path, 'Status.json'), {'ok': True})

    def test_status_parser_keeps_last_good_data_and_recovers(self):
        fast_read = functools.partial(JsonFile.read_game_json, max_attempts=3, initial_backoff=0.01)
        good = {'timestamp': '2026-11-08T12:00:00Z', 'event': 'Status', 'Flags': 16, 'GuiFocus': 0}
        with mock.patch.object(status_module, 'read_game_json', fast_read):
            self.write(json.dumps(good))
            parser = status_module.StatusParser(file_path=self.path)
            self.assertTrue(parser.get_flag(16))
            time.sleep(0.01)
            self.write('{"broken"')
            self.assertTrue(parser.get_flag(16), "lost the last good data")
            time.sleep(0.01)
            self.write(json.dumps({**good, 'Flags': 32}))
            self.assertTrue(parser.get_flag(32))
            self.assertFalse(parser.get_flag(16))

    def test_status_parser_unreadable_at_startup_raises_clear_error(self):
        """ RP1: the original hung forever at startup. """
        fast_read = functools.partial(JsonFile.read_game_json, max_attempts=3, initial_backoff=0.01)
        with mock.patch.object(status_module, 'read_game_json', fast_read):
            self.write('')
            with self.assertRaises(RuntimeError):
                status_module.StatusParser(file_path=self.path)


if __name__ == '__main__':
    unittest.main()
