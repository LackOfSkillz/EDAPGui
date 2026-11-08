"""
Fork RP2: shared setup for the offline tests.

These tests run without Elite Dangerous, without Windows and without the heavy requirements (torch, paddle).
Windows-only and heavy modules are replaced with small stand-ins before any EDAP module is imported.
Every offline test file must `import offline_stubs` before importing EDAP modules.

Run from the repository root:
    python -m unittest discover -s test/offline -v
Needs only: numpy and opencv-python-headless (for the calibration and OCR error-path tests).
"""
import logging
import os
import sys
import tempfile
import types

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def _stub(name, **attrs):
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    sys.modules[name] = module
    return module


class _Dummy:
    def __init__(self, *args, **kwargs):
        pass


# EDlogger: the real one renames or creates autopilot.log in the current folder and needs colorlog.
logger = logging.getLogger('edap-offline-tests')
logger.addHandler(logging.NullHandler())
logger.propagate = False
_stub('EDlogger', logger=logger, logging=logging)

# WindowsKnownPaths uses ctypes.windll. Point 'Saved Games' at a temporary folder instead.
SAVED_GAMES = tempfile.mkdtemp(prefix='edap-test-saved-')
JOURNAL_DIR = os.path.join(SAVED_GAMES, 'Frontier Developments', 'Elite Dangerous')
os.makedirs(JOURNAL_DIR, exist_ok=True)


class FOLDERID:
    SavedGames = 'SavedGames'


class UserHandle:
    current = 'current'


_stub('WindowsKnownPaths', FOLDERID=FOLDERID, UserHandle=UserHandle, get_path=lambda folder, handle: SAVED_GAMES)

# Voice needs pyttsx3.
_stub('Voice', Voice=_Dummy)

# EDKeys needs pywin32, xmltodict, directinput (ctypes.windll) and Screen (mss, pywin32).
# Tests patch these functions to simulate focus changes.
_stub('win32gui', GetForegroundWindow=lambda: 0, GetWindowText=lambda handle: '')
_stub('xmltodict', parse=lambda *args, **kwargs: {})
_stub('directinput', PressKey=lambda key: None, ReleaseKey=lambda key: None, SCANCODE={})
_stub('Screen', set_focus_elite_window=lambda: False, is_elite_foreground=lambda: False,
      get_elite_window_handle=lambda: 0)

# OCR needs paddleocr and strsimpy.
_stub('paddleocr', PaddleOCR=_Dummy)
_stub('strsimpy', SorensenDice=_Dummy)
_stub('strsimpy.jaro_winkler', JaroWinkler=_Dummy)
_stub('strsimpy.normalized_levenshtein', NormalizedLevenshtein=_Dummy)
