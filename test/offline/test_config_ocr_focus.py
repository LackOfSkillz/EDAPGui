"""
Fork RP2: offline tests for the reliability pass 2 fixes: safe config writes, unreadable-file backups,
calibration loading, the OCR error path, and the keyboard focus guard. See FORK_CHANGELOG.md.
Run: python -m unittest discover -s test/offline -v
"""
import offline_stubs  # noqa: F401  (must be first: installs stand-ins for Windows-only modules)

import glob
import json
import os
import tempfile
import time
import unittest
from unittest import mock

import numpy as np

import EDKeys as edkeys_module
import JsonFile
import OCR as ocr_module
import Screen_Regions


class InTempFolder(unittest.TestCase):
    """ Runs each test in its own empty working folder, since some code uses relative paths. """

    def setUp(self):
        self._old_cwd = os.getcwd()
        self.dir = tempfile.mkdtemp(prefix='edap-test-')
        os.chdir(self.dir)

    def tearDown(self):
        os.chdir(self._old_cwd)


class AtomicWriteTests(InTempFolder):

    def test_writes_and_overwrites(self):
        JsonFile.write_json_atomic({'a': 1}, 'AP.json')
        JsonFile.write_json_atomic({'a': 2}, 'AP.json')
        with open('AP.json') as f:
            self.assertEqual(json.load(f), {'a': 2})
        self.assertEqual(glob.glob('*.tmp'), [])

    def test_failed_write_leaves_old_file_intact(self):
        """ The original wrote in place, so a failure part way left a truncated file. """
        JsonFile.write_json_atomic({'tuning': 'precious'}, 'ship_configs.json')
        with self.assertRaises(TypeError):
            JsonFile.write_json_atomic({'bad': {1, 2}}, 'ship_configs.json')  # a set can't be written as JSON
        with open('ship_configs.json') as f:
            self.assertEqual(json.load(f), {'tuning': 'precious'})
        self.assertEqual(glob.glob('*.tmp'), [], "temporary file left behind")


class BackupTests(InTempFolder):

    def test_unreadable_file_is_moved_aside(self):
        with open('AP.json', 'w') as f:
            f.write('{"truncated": ')
        backup = JsonFile.backup_unreadable_file('AP.json')
        self.assertIsNotNone(backup)
        self.assertFalse(os.path.exists('AP.json'))
        with open(backup) as f:
            self.assertEqual(f.read(), '{"truncated": ')

    def test_missing_file_returns_none(self):
        self.assertIsNone(JsonFile.backup_unreadable_file('nope.json'))


class CalibrationFileTests(InTempFolder):

    def setUp(self):
        super().setUp()
        os.makedirs('configs')

    def write_corrupt(self):
        with open('configs/ocr_calibration.json', 'w') as f:
            f.write('{"EDGalaxyMap.cartographics": {"rect": [0.1, ')

    def test_corrupt_file_is_backed_up_and_defaults_used(self):
        """ The original raised on startup if the calibration file was corrupt. """
        self.write_corrupt()
        data = Screen_Regions.load_default_calib_data()
        self.assertIsInstance(data, dict)
        self.assertTrue(len(data) > 0)
        self.assertEqual(len(glob.glob('configs/ocr_calibration.json.unreadable-*')), 1)
        with open('configs/ocr_calibration.json') as f:
            self.assertEqual(json.load(f), data, "defaults not written back")

    def test_loaders_ignore_corrupt_file(self):
        self.write_corrupt()
        reg = {'cartographics': {'rect': [0.0, 0.0, 1.0, 1.0]}}
        Screen_Regions.load_calibrated_regions('EDGalaxyMap', reg)  # must not raise
        self.assertEqual(reg['cartographics']['rect'], [0.0, 0.0, 1.0, 1.0])
        quads = {'cartographics': Screen_Regions.Quad.from_rect([0.0, 0.0, 1.0, 1.0])}
        Screen_Regions.load_calibrated_regions_quad('EDGalaxyMap', quads)  # must not raise


class OcrErrorPathTests(InTempFolder):
    """ The original error handler saved to './ocr_output/<name>' with no extension and no folder, so OpenCV
    raised and the handler itself crashed. For 'disengage' that killed supercruise disengage detection. """

    image = np.zeros((10, 10, 3), np.uint8)

    def test_saves_png_and_creates_folder(self):
        ocr_module.OCR._save_failed_image(self.image, 'disengage')
        self.assertEqual(len(glob.glob('ocr_output/failed-disengage-*.png')), 1)

    def test_empty_and_unsafe_names(self):
        ocr_module.OCR._save_failed_image(self.image, '')
        ocr_module.OCR._save_failed_image(self.image, 'a/b:c')
        self.assertEqual(len(glob.glob('ocr_output/failed-ocr-*.png')), 1)
        self.assertEqual(len(glob.glob('ocr_output/failed-a_b_c-*.png')), 1)

    def test_never_raises(self):
        ocr_module.OCR._save_failed_image(None, 'disengage')  # OpenCV raises on None; must be caught


class FocusGuardTests(unittest.TestCase):
    """ EDKeys.ensure_focus: keys must go to Elite, taking focus back from whatever window took it, and the
    autopilot must never pause. Windows calls are simulated. """

    def make_keys(self):
        keys = edkeys_module.EDKeys.__new__(edkeys_module.EDKeys)  # skip __init__, which reads key bindings
        keys.gui_messages = []
        keys.ap_ckb = lambda msg, body=None: keys.gui_messages.append(body)
        keys._focus_msg_times = {}
        keys.key_mod_delay = 0
        keys.key_def_hold_time = 0
        keys.key_repeat_delay = 0
        keys.keys = {'TestKey': {'key': 0x11, 'mods': []}}
        keys.reversed_dict = {0x11: 'Key_W'}
        return keys

    def patch_windows(self, foreground, focus_results, window_exists=True):
        """ foreground: is Elite focused. focus_results: what each set_focus_elite_window() call returns. """
        calls = {'set_focus': 0}

        def set_focus():
            calls['set_focus'] += 1
            return focus_results.pop(0) if focus_results else False

        patches = [
            mock.patch.object(edkeys_module, 'is_elite_foreground', lambda: foreground),
            mock.patch.object(edkeys_module, 'get_elite_window_handle', lambda: 1234 if window_exists else 0),
            mock.patch.object(edkeys_module, 'set_focus_elite_window', set_focus),
            mock.patch.object(edkeys_module.win32gui, 'GetWindowText', lambda handle: 'Windows Update', create=True),
            mock.patch.object(edkeys_module, 'FOCUS_RETRY_SEC', 0.3),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return calls

    def test_already_focused_does_nothing(self):
        keys = self.make_keys()
        calls = self.patch_windows(foreground=True, focus_results=[])
        self.assertTrue(keys.ensure_focus())
        self.assertEqual(calls['set_focus'], 0)
        self.assertEqual(keys.gui_messages, [])

    def test_takes_focus_back_and_says_from_what(self):
        keys = self.make_keys()
        calls = self.patch_windows(foreground=False, focus_results=[False, True])
        self.assertTrue(keys.ensure_focus())
        self.assertEqual(calls['set_focus'], 2, "should retry until focus is back")
        self.assertEqual(len(keys.gui_messages), 1)
        self.assertIn('Windows Update', keys.gui_messages[0])

    def test_repeat_messages_are_rate_limited(self):
        keys = self.make_keys()
        self.patch_windows(foreground=False, focus_results=[True, True, True])
        keys.ensure_focus()
        keys.ensure_focus()
        keys.ensure_focus()
        self.assertEqual(len(keys.gui_messages), 1)

    def test_gives_up_but_never_blocks_the_autopilot(self):
        keys = self.make_keys()
        self.patch_windows(foreground=False, focus_results=[])
        start = time.time()
        self.assertFalse(keys.ensure_focus())
        self.assertLess(time.time() - start, 1.0)
        self.assertEqual(len(keys.gui_messages), 1)
        self.assertIn('Could not bring Elite back', keys.gui_messages[0])

    def test_game_not_running_returns_immediately(self):
        keys = self.make_keys()
        calls = self.patch_windows(foreground=False, focus_results=[], window_exists=False)
        start = time.time()
        self.assertFalse(keys.ensure_focus())
        self.assertLess(time.time() - start, 0.1)
        self.assertEqual(calls['set_focus'], 0)
        self.assertEqual(keys.gui_messages, [], "should only go to the log file, not the GUI")

    def test_send_checks_focus_before_press_and_before_release(self):
        """ A window can take focus while a key is held; the release must reach Elite too. """
        keys = self.make_keys()
        events = []
        keys.ensure_focus = lambda: events.append('focus') or True
        with mock.patch.object(edkeys_module, 'PressKey', lambda k: events.append('press')), \
                mock.patch.object(edkeys_module, 'ReleaseKey', lambda k: events.append('release')):
            keys.send('TestKey')
            self.assertEqual(events, ['focus', 'press', 'focus', 'release'])
            events.clear()
            keys.send('TestKey', state=1)
            self.assertEqual(events, ['focus', 'press'])
            events.clear()
            keys.send('TestKey', state=0)
            self.assertEqual(events, ['focus', 'release'])


if __name__ == '__main__':
    unittest.main()
