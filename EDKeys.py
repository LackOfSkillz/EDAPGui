from __future__ import annotations

import json
from os import environ, listdir
import os
from os.path import getmtime, isfile, join
import time
from time import sleep
from typing import Any, final
from xml.etree.ElementTree import parse

import win32gui
import xmltodict

from Screen import set_focus_elite_window, is_elite_foreground, get_elite_window_handle
from directinput import *
from EDlogger import logger

"""
Description:  Pulls the keybindings for specific controls from the ED Key Bindings file, this class also
  has method for sending a key to the display that has focus (so must have ED with focus)

Constraints:  This file will use the latest modified *.binds file
"""

# Fork RP2: focus guard settings (see EDKeys.ensure_focus).
FOCUS_RETRY_SEC = 1.0  # How long to keep trying to bring Elite back in front before sending anyway.
FOCUS_LOG_INTERVAL_SEC = 10.0  # Minimum time between repeats of the same focus message, to avoid log spam.
# After a failed attempt to take focus back (e.g. an elevated window that Windows won't let us cover), later keys
# make one quick attempt each instead of retrying for FOCUS_RETRY_SEC, so each key isn't delayed by a second.
FOCUS_BACKOFF_SEC = 10.0


@final
class EDKeys:

    def __init__(self, cb):
        self.ap_ckb = cb
        self.key_mod_delay = 0.01  # Delay for key modifiers to ensure modifier is detected before/after the key
        self.key_def_hold_time = 0.2  # Default hold time for a key press
        self.key_repeat_delay = 0.1  # Delay between key press repeats
        # Fork RP2: no longer used by send()/send_key(). The focus guard (ensure_focus) now always runs and only
        # acts when Elite has lost focus. Kept so the existing 'ActivateEliteEachKey' setting and tests still work.
        self.activate_window = False
        self._focus_msg_times: dict[str, float] = {}  # Fork RP2: rate limiting for focus messages
        self._focus_failed_at = float('-inf')  # Fork RP2: when focus last couldn't be taken back (FOCUS_BACKOFF_SEC)

        self.keys_to_obtain = [
            'YawLeftButton',
            'YawRightButton',
            'RollLeftButton',
            'RollRightButton',
            'PitchUpButton',
            'PitchDownButton',
            'SetSpeedZero',
            'SetSpeed50',
            'SetSpeed100',
            'HyperSuperCombination',
            'SelectTarget',
            'DeployHeatSink',
            'UIFocus',
            'UI_Up',
            'UI_Down',
            'UI_Left',
            'UI_Right',
            'UI_Select',
            'UI_Back',
            'CycleNextPanel',
            'HeadLookReset',
            'PrimaryFire',
            'SecondaryFire',
            'ExplorationFSSEnter',
            'ExplorationFSSQuit',
            'MouseReset',
            'DeployHardpointToggle',
            'IncreaseEnginesPower',
            'IncreaseWeaponsPower',
            'IncreaseSystemsPower',
            'ResetPowerDistribution',
            'GalaxyMapOpen',
            'CamZoomIn',  # Gal map zoom in
            'SystemMapOpen',
            'UseBoostJuice',
            'Supercruise',
            'UpThrustButton',
            'LandingGearToggle',
            'TargetNextRouteSystem',  # Target next system in route
            'CamTranslateForward',
            'CamTranslateRight',
            'OrderAggressiveBehaviour',
        ]
        self.keys = self.get_bindings()
        self.bindings = self.get_bindings_dict()

        self.missing_keys = []
        # We want to log the keyboard name instead of just the key number so we build a reverse dictionary
        # so we can look up the name also
        self.reversed_dict = {value: key for key, value in SCANCODE.items()}

        # dump config to log
        for key in self.keys_to_obtain:
            try:
                # lookup the keyname in the SCANCODE reverse dictionary and output that key name
                keyname = self.reversed_dict.get(self.keys[key]['key'], "Key not found")
                keymod = " "
                # if key modifier, then look up that modifier name also
                if len(self.keys[key]['mods']) != 0:
                    keymod = self.reversed_dict.get(self.keys[key]['mods'][0], " ")

                logger.info('\tget_bindings_<{}>={} Key: <{}> Mod: <{}>'.format(key, self.keys[key], keyname, keymod))
                if key not in self.keys:
                    self.ap_ckb('log',
                                f"WARNING: \tget_bindings_<{key}>= does not have a valid keyboard keybind {keyname}.")
                    logger.warning(
                        "\tget_bindings_<{}>= does not have a valid keyboard keybind {}".format(key, keyname).upper())
                    self.missing_keys.append(key)
            except Exception as e:
                self.ap_ckb('log', f"WARNING: \tget_bindings_<{key}>= does not have a valid keyboard keybind.")
                logger.warning("\tget_bindings_<{}>= does not have a valid keyboard keybind.".format(key).upper())
                self.missing_keys.append(key)

        # Check if the hotkeys are used in ED
        binding_name = self.check_hotkey_in_bindings('Key_End')
        if binding_name != "":
            warn_text = (f"Hotkey 'Key_End' is used in the ED keybindings for '{binding_name}'. Recommend changing in"
                         f" ED to another key to avoid EDAP accidentally being triggered.")
            self.ap_ckb('log', f"WARNING: {warn_text}")
            logger.warning(f"{warn_text}")

        binding_name = self.check_hotkey_in_bindings('Key_Insert')
        if binding_name != "":
            warn_text = (f"Hotkey 'Key_Insert' is used in the ED keybindings for '{binding_name}'. Recommend changing in"
                         f" ED to another key to avoid EDAP accidentally being triggered.")
            self.ap_ckb('log', f"WARNING: {warn_text}")
            logger.warning(f"{warn_text}")

        binding_name = self.check_hotkey_in_bindings('Key_PageUp')
        if binding_name != "":
            warn_text = (f"Hotkey 'Key_PageUp' is used in the ED keybindings for '{binding_name}'. Recommend changing in"
                         f" ED to another key to avoid EDAP accidentally being triggered.")
            self.ap_ckb('log', f"WARNING: {warn_text}")
            logger.warning(f"{warn_text}")

        binding_name = self.check_hotkey_in_bindings('Key_Home')
        if binding_name != "":
            warn_text = (f"Hotkey 'Key_Home' is used in the ED keybindings for '{binding_name}'. Recommend changing in"
                         f" ED to another key to avoid EDAP accidentally being triggered.")
            self.ap_ckb('log', f"WARNING: {warn_text}")
            logger.warning(f"{warn_text}")

    def get_bindings(self) -> dict[str, Any]:
        """Returns a dict struct with the direct input equivalent of the necessary elite keybindings"""
        direct_input_keys = {}
        latest_bindings = self.get_latest_keybinds()
        if not latest_bindings:
            return {}
        bindings_tree = parse(latest_bindings)
        bindings_root = bindings_tree.getroot()

        for item in bindings_root:
            if item.tag in self.keys_to_obtain:
                key = None
                mods = []
                hold = None
                # Check primary
                if item[0].attrib['Device'].strip() == "Keyboard":
                    key = item[0].attrib['Key']
                    for modifier in item[0]:
                        if modifier.tag == "Modifier":
                            mods.append(modifier.attrib['Key'])
                        elif modifier.tag == "Hold":
                            hold = True
                # Check secondary (and prefer secondary)
                if item[1].attrib['Device'].strip() == "Keyboard":
                    key = item[1].attrib['Key']
                    mods = []
                    hold = None
                    for modifier in item[1]:
                        if modifier.tag == "Modifier":
                            mods.append(modifier.attrib['Key'])
                        elif modifier.tag == "Hold":
                            hold = True
                # Prepare final binding
                binding: None | dict[str, Any] = None
                try:
                    if key is not None:
                        binding = {}
                        binding['key'] = SCANCODE[key]
                        binding['mods'] = []
                        for mod in mods:
                            binding['mods'].append(SCANCODE[mod])
                        if hold is not None:
                            binding['hold'] = True
                except KeyError:
                    print("Unrecognised key '" + (
                        json.dumps(binding) if binding else '?') + "' for bind '" + item.tag + "'")
                if binding is not None:
                    direct_input_keys[item.tag] = binding

        if len(list(direct_input_keys.keys())) < 1:
            return {}
        else:
            return direct_input_keys

    def get_bindings_dict(self) -> dict[str, Any]:
        """Returns a dict of all the elite keybindings.
        @return: A dictionary of the keybinds file.
        Example:
        {
        'Root': {
            'YawLeftButton': {
                'Primary': {
                    '@Device': 'Keyboard',
                    '@Key': 'Key_A'
                },
                'Secondary': {
                    '@Device': '{NoDevice}',
                    '@Key': ''
                }
            }
        }
        }
        """
        latest_bindings = self.get_latest_keybinds()
        if not latest_bindings:
            return {}

        try:
            with open(latest_bindings, 'r') as file:
                my_xml = file.read()
                my_dict = xmltodict.parse(my_xml)
                return my_dict

        except OSError as e:
            logger.error(f"OS Error reading Elite Dangerous bindings file: {latest_bindings}.")
            raise Exception(f"OS Error reading Elite Dangerous bindings file: {latest_bindings}.")

    def check_hotkey_in_bindings(self, key_name: str) -> str:
        """ Check for the action keys. """
        ret = []
        for key, value in self.bindings['Root'].items():
            if type(value) is dict:
                primary = value.get('Primary', None)
                if primary is not None:
                    if primary['@Key'] == key_name:
                        ret.append(f"{key} (Primary)")
                secondary = value.get('Secondary', None)
                if secondary is not None:
                    if secondary['@Key'] == key_name:
                        ret.append(f"{key} (Secondary)")
        return " and ".join(ret)

    # Note:  this routine will grab the *.binds file which is the latest modified
    def get_latest_keybinds(self):
        # Fork RP2: built with join(). The original concatenated "\Frontier Developments\...", whose "\F" is
        # an invalid escape sequence (a SyntaxWarning since Python 3.12).
        path_bindings = join(environ['LOCALAPPDATA'], "Frontier Developments", "Elite Dangerous", "Options",
                             "Bindings")
        try:
            list_of_bindings = [join(path_bindings, f) for f in listdir(path_bindings) if
                                isfile(join(path_bindings, f)) and f.endswith('.binds')]
        except FileNotFoundError as e:
            return None

        if not list_of_bindings:
            return None
        latest_bindings = max(list_of_bindings, key=getmtime)
        logger.info(f'Latest keybindings file:{latest_bindings}')
        return latest_bindings

    def _focus_message(self, kind: str, msg: str, to_gui: bool):
        """ Logs a focus message, at most once per FOCUS_LOG_INTERVAL_SEC for each kind. Fork RP2: added.
        Uses time.monotonic(): wall-clock time can jump back (a clock sync), which would mute messages. """
        now = time.monotonic()
        if now - self._focus_msg_times.get(kind, float('-inf')) < FOCUS_LOG_INTERVAL_SEC:
            return
        self._focus_msg_times[kind] = now
        logger.warning(msg)
        if to_gui and self.ap_ckb:  # no callback when EDKeys is used on its own (e.g. EDWayPoint's test main)
            self.ap_ckb('log', msg)

    def ensure_focus(self, retry: bool = True) -> bool:
        """ Makes sure Elite is the focused window before a key is sent, taking focus back if another window
        (a notification, a dialog, an alt-tab) has taken it. Never pauses or stops the autopilot.
        Fork RP2: added. Windows delivers simulated keys only to the focused window, so when something else
        took focus, EDAP's keys went into that window and Elite missed them, breaking the maneuver in
        progress. The old 'Activate Elite each key' option refocused before every key, even when Elite already
        had focus, and was off by default. This check costs almost nothing when Elite has focus, and acts
        only when it doesn't.
        @param retry: keep trying for up to FOCUS_RETRY_SEC. False makes one attempt only; used before releasing
        a held key, so the key isn't held longer than intended while retrying.
        @return: True if Elite has focus. False if it couldn't be focused; the key is then sent anyway, as
        before, so the autopilot keeps going.
        """
        if is_elite_foreground():
            return True

        if get_elite_window_handle() == 0:
            # Game window not found (not running, or a test without the game): nothing to focus.
            self._focus_message('no_window', "Elite Dangerous window not found. Keys go to whichever window "
                                             "has focus.", to_gui=False)
            return False

        try:
            thief = win32gui.GetWindowText(win32gui.GetForegroundWindow()) or 'another window'
        except Exception:
            thief = 'another window'

        # One attempt only if asked, or if focus couldn't be taken back recently (see FOCUS_BACKOFF_SEC).
        # time.monotonic(), not time.time(): a clock that jumps back would otherwise stretch the retry loop.
        now = time.monotonic()
        keep_trying = retry and now - self._focus_failed_at >= FOCUS_BACKOFF_SEC
        deadline = now + FOCUS_RETRY_SEC if keep_trying else now
        while True:
            if set_focus_elite_window():
                self._focus_failed_at = float('-inf')
                # Give the game a moment to start taking input again before the key arrives.
                sleep(0.05)
                self._focus_message('regained', f"Elite lost focus to '{thief}'. Took focus back so the "
                                                f"autopilot's keys go to Elite.", to_gui=True)
                return True
            if time.monotonic() >= deadline:
                break
            sleep(0.1)

        self._focus_failed_at = time.monotonic()
        self._focus_message('failed', f"Could not bring Elite back in front of '{thief}'. Keys may go to "
                                      f"that window until Elite has focus again.", to_gui=True)
        return False

    def send_key(self, type, key):
        # Fork RP2: always make sure Elite has focus (see ensure_focus). Was only done when the
        # 'Activate Elite each key' option was on, which it is not by default. A release makes one attempt only,
        # so the key isn't held longer than intended (see ensure_focus).
        self.ensure_focus(retry=(type != 'Up'))

        if type == 'Up':
            ReleaseKey(key)
        else:
            PressKey(key)

    def send(self, key_binding, hold=None, repeat=1, repeat_delay=None, state=None):
        """ Send a key based on the defined keybind
        @param key_binding: The key bind name (i.e. UseBoostJuice).
        @param hold: The time to hold the key down in seconds.
        @param repeat: Number of times to repeat the key.
        @param repeat_delay: Time delay in seconds between repeats. If None, uses the default repeat delay.
        @param state: Key state:
            None - press and release (default).
            1 - press (but don't release).
            0 - release (a previous press state).
        """
        key = self.keys.get(key_binding)
        if key is None:
            logger.warning('SEND=NONE !!!!!!!!')
            self.ap_ckb('log', f"WARNING: Unable to retrieve keybinding for {key_binding}.")
            raise Exception(
                f"Unable to retrieve keybinding for {key_binding}. Advise user to check game settings for keyboard bindings.")

        key_name = self.reversed_dict.get(key['key'], "Key not found")
        logger.debug('\tsend=' + key_binding + ',key:' + str(key) + ',key_name:' + key_name + ',hold:' + str(
            hold) + ',repeat:' + str(
            repeat) + ',repeat_delay:' + str(repeat_delay) + ',state:' + str(state))

        for i in range(repeat):
            # Fork RP2: always make sure Elite has focus (see ensure_focus). Was only done when the
            # 'Activate Elite each key' option was on, which it is not by default. Releasing a held key
            # (state 0) makes one attempt only, so the key isn't held longer than intended.
            self.ensure_focus(retry=(state != 0))

            if state is None or state == 1:
                for mod in key['mods']:
                    PressKey(mod)
                    sleep(self.key_mod_delay)

                PressKey(key['key'])

            if state is None:
                if hold:
                    if hold > 0.0:
                        sleep(hold)
                else:
                    if self.key_def_hold_time > 0.0:
                        sleep(self.key_def_hold_time)

            if 'hold' in key:
                sleep(0.1)

            if state is None:
                # Fork RP2: focus can be taken while the key is held down. Check again so the release
                # reaches Elite; otherwise Elite could be left thinking the key is still held. One attempt
                # only: retrying here would keep the key held down (and the ship turning) for up to a second.
                self.ensure_focus(retry=False)

            if state is None or state == 0:
                ReleaseKey(key['key'])

                for mod in key['mods']:
                    sleep(self.key_mod_delay)
                    ReleaseKey(mod)

            if repeat_delay:
                sleep(repeat_delay)
            else:
                sleep(self.key_repeat_delay)

    def release_all_keys(self):
        """Release all modifier keys and any currently tracked key presses to prevent stuck keys.
        Called on stop/interrupt to ensure no keys remain held down."""
        modifier_scancodes = [
            SCANCODE.get("Key_LeftShift"),
            SCANCODE.get("Key_RightShift"),
            SCANCODE.get("Key_LeftControl"),
            SCANCODE.get("Key_RightControl"),
            SCANCODE.get("Key_LeftAlt"),
            SCANCODE.get("Key_RightAlt"),
        ]
        for sc in modifier_scancodes:
            if sc is not None:
                ReleaseKey(sc)

        for binding in self.keys.values():
            ReleaseKey(binding['key'])
            for mod in binding['mods']:
                ReleaseKey(mod)

    def get_collisions(self, key_name: str) -> list[str]:
        """ Get key name collisions (keys used for more than one binding).
        @param key_name: The key name (i.e. UI_Up, UI_Down).
        """
        key = self.keys.get(key_name)
        collisions = []
        for k, v in self.keys.items():
            if key == v:
                collisions.append(k)
        return collisions
