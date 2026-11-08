"""
Fork RP2: offline tests for Screen.set_focus_elite_window, the code that brings Elite back in front.
The other offline tests replace Screen with a stand-in; these load the real Screen.py with the Windows calls
simulated, so the fallback logic is checked without Windows. See FORK_CHANGELOG.md.
Run: python -m unittest discover -s test/offline -v
"""
import offline_stubs  # noqa: F401  (must be first: installs stand-ins for Windows-only modules)

import importlib.util
import os
import sys
import types
import unittest
from unittest import mock

# Screen.py's real dependencies, imported here first: patch.dict below removes modules first imported inside it,
# and OpenCV can't be imported a second time.
import cv2  # noqa: F401
import numpy  # noqa: F401
import JsonFile  # noqa: F401
import Screen_Regions  # noqa: F401

ELITE = 1234
OTHER = 99


def load_real_screen():
    """ Loads Screen.py under another name, with pywin32 and mss replaced, without disturbing the stand-in
    'Screen' module the other tests use. """
    fakes = {
        'win32gui': types.ModuleType('win32gui'),
        'win32api': types.ModuleType('win32api'),
        'win32process': types.ModuleType('win32process'),
        'win32con': types.SimpleNamespace(SW_RESTORE=9),
        'mss': types.SimpleNamespace(mss=lambda: None),
    }
    with mock.patch.dict(sys.modules, fakes):
        spec = importlib.util.spec_from_file_location(
            'Screen_under_test', os.path.join(offline_stubs.REPO_ROOT, 'Screen.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


screen = load_real_screen()


class FakeWindows:
    """ Simulates the pywin32 calls set_focus_elite_window uses. Like Windows' foreground lock, a plain
    SetForegroundWindow is refused unless allowed, but works once our thread is attached to the focused one.
    Like pywin32, failed calls raise. """

    def __init__(self, plain_attempt_works=False, bring_to_top_raises=False, minimised=False, game_running=True):
        self.foreground = OTHER
        self.attached = False
        self.calls = []
        self.plain_attempt_works = plain_attempt_works
        self.bring_to_top_raises = bring_to_top_raises
        self.minimised = minimised
        self.game_running = game_running

    # win32gui
    def FindWindow(self, cls, title):
        return ELITE if self.game_running else 0

    def GetForegroundWindow(self):
        return self.foreground

    def IsIconic(self, handle):
        return self.minimised

    def ShowWindow(self, handle, cmd):
        self.calls.append('ShowWindow')

    def SetForegroundWindow(self, handle):
        self.calls.append('SetForegroundWindow')
        if not (self.plain_attempt_works or self.attached):
            raise OSError('SetForegroundWindow refused')
        self.foreground = handle

    def BringWindowToTop(self, handle):
        self.calls.append('BringWindowToTop')
        if self.bring_to_top_raises:
            raise OSError('BringWindowToTop failed')

    # win32api
    def GetCurrentThreadId(self):
        return 1

    # win32process
    def GetWindowThreadProcessId(self, handle):
        return 2, 200  # (thread id, process id)

    def AttachThreadInput(self, our_thread, other_thread, attach):
        self.calls.append('attach' if attach else 'detach')
        self.attached = attach


class SetFocusTests(unittest.TestCase):

    def use(self, fake, hung=False):
        for name in ('win32gui', 'win32api', 'win32process'):
            p = mock.patch.object(screen, name, fake)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(screen, '_is_hung_window', lambda window: hung)
        p.start()
        self.addCleanup(p.stop)
        return fake

    def test_already_focused_does_nothing(self):
        win = self.use(FakeWindows())
        win.foreground = ELITE
        self.assertTrue(screen.set_focus_elite_window())
        self.assertEqual(win.calls, [])

    def test_game_not_running(self):
        win = self.use(FakeWindows(game_running=False))
        self.assertFalse(screen.set_focus_elite_window())
        self.assertEqual(win.calls, [])

    def test_plain_attempt_is_enough_when_allowed(self):
        win = self.use(FakeWindows(plain_attempt_works=True))
        self.assertTrue(screen.set_focus_elite_window())
        self.assertEqual(win.calls, ['SetForegroundWindow'])

    def test_fallback_attaches_and_always_detaches(self):
        win = self.use(FakeWindows())
        self.assertTrue(screen.set_focus_elite_window())
        self.assertEqual(win.calls, ['SetForegroundWindow', 'attach', 'BringWindowToTop', 'SetForegroundWindow',
                                     'detach'])

    def test_bring_to_top_failure_does_not_skip_set_foreground(self):
        """ Review fix: a raising BringWindowToTop skipped the SetForegroundWindow after it. """
        win = self.use(FakeWindows(bring_to_top_raises=True))
        self.assertTrue(screen.set_focus_elite_window())
        self.assertEqual(win.calls.count('SetForegroundWindow'), 2)
        self.assertEqual(win.calls[-1], 'detach')

    def test_does_not_attach_to_a_hung_window(self):
        """ Review fix: attaching to the input of a 'Not Responding' window can stall the autopilot thread. """
        win = self.use(FakeWindows(), hung=True)
        self.assertFalse(screen.set_focus_elite_window())  # must not raise
        self.assertNotIn('attach', win.calls)
        self.assertEqual(win.calls.count('SetForegroundWindow'), 2, "should still try")

    def test_only_restores_a_minimised_window(self):
        """ The original called ShowWindow every time, which can resize the game window. """
        win = self.use(FakeWindows(plain_attempt_works=True))
        screen.set_focus_elite_window()
        self.assertNotIn('ShowWindow', win.calls)
        win = self.use(FakeWindows(plain_attempt_works=True, minimised=True))
        screen.set_focus_elite_window()
        self.assertEqual(win.calls[0], 'ShowWindow')

    def test_hung_check_never_raises(self):
        self.assertFalse(screen._is_hung_window(0))  # no window; also no ctypes.windll off Windows


if __name__ == '__main__':
    unittest.main()
