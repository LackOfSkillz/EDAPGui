# Fork Change Log

Changes made in this fork ([LackOfSkillz/EDAPGui](https://github.com/LackOfSkillz/EDAPGui)) relative to upstream ([SumZer0-git/EDAPGui](https://github.com/SumZer0-git/EDAPGui)). Upstream's own history stays in [ChangeLog.md](ChangeLog.md).

**Forked from:** upstream `main` at `8e15ca6` (v1.9.3 plus merged PRs through #149, 2026-09-22).

Entries are labelled by date and branch rather than version number, so they don't collide with upstream releases. Newest first.

**Code comments.** Every changed spot in the code carries a tag comment saying what the original did and why it was changed. Each pass has its own tag: `Fork RP1:` for reliability pass 1, `Fork RP2:` for the next, and so on. `git grep "Fork RP1"` lists every change from a pass.

**Tests.** `python -m unittest discover -s test/offline -v` runs the offline tests (no game needed; just `numpy` and `opencv-python-headless`). They also run automatically on GitHub for every push, once Actions are enabled on the fork (Actions tab, then "I understand my workflows, go ahead and enable them").

---

## 2026-11-08: Reliability pass 2

Branch `reliability-pass-2`, stacked on pass 1, [PR #2](https://github.com/LackOfSkillz/EDAPGui/pull/2). Code comments are tagged `Fork RP2:`.

Bug fixes plus one deliberate behaviour change: the autopilot now keeps its keys going to Elite when another window takes focus.

### Supercruise disengage detection (`OCR.py`, `ED_AP.py`)

- **Fixed: one OCR failure could stop SC Assist from ever dropping out at its destination.**
  - When OCR failed, the error handler saved the image to `./ocr_output/<name>`, with no file extension, in a folder nothing created. OpenCV raises on a name without an extension (tested), so the handler meant to recover from the failure crashed itself.
  - For the "disengage" check, that crash killed the supercruise-overcharge monitor thread, which had no error handling.
  - That thread is the only thing that detects the disengage prompt, so SC Assist kept flying past its destination.
  - Now the image is saved as a timestamped `.png`, the folder is created, and saving can't raise.
- **Fixed:** the monitor thread now logs any error and carries on with its next check, instead of dying silently.

### Config files can no longer be wiped (`JsonFile.py` and every file that saves settings)

- **Fixed: a crash mid-save could wipe your settings and ship tuning.** Config files were written in place, so a crash, kill or power cut mid-save left a truncated file. On the next start, `AP.json` and `ship_configs.json` (every ship's RPY calibration) were then silently replaced with defaults.
  - All of EDAP's own files are now written to a temporary file and swapped in with one rename, so a file is always either the old version or the new one: `AP.json`, `ship_configs.json`, waypoint files, `resolution.json`, `ocr_calibration.json`, `construction.json`.
  - If `AP.json` or `ship_configs.json` still can't be read, it is kept as `<name>.unreadable-<date-time>` and a warning appears in the GUI log, instead of it being overwritten.
- **Fixed:** a corrupt `ocr_calibration.json` crashed startup. It is now kept as a backup and the built-in regions are used.

### Keys always go to Elite (`EDKeys.py`, `Screen.py`, `EDGalaxyMap.py`, `EDAPGui.py`)

- **Changed: Elite is brought back to the front before every autopilot keystroke.** Windows only delivers simulated keys to the focused window. When a notification, dialog or alt-tab took focus, the autopilot's keys went into that window and Elite missed them mid-maneuver.
  - Before every key press and release, EDAP checks that Elite has focus. This costs almost nothing when it does.
  - If it doesn't, EDAP takes focus back. A GUI log line names the window that took it, at most once every 10 seconds.
  - The autopilot never pauses or stops for this. If Elite can't be brought forward within 1 second, the key is sent anyway and a warning is logged.
  - After such a failure (say, an admin window Windows won't let EDAP cover), later keys make one quick attempt each instead of waiting a second each, until Elite has focus again.
  - The release of a held key is checked too, so a window popping up mid-hold can't leave Elite thinking the key is still down. That check makes one quick attempt only, so a held key (and the turn it drives) isn't stretched by up to a second while retrying.
- **Fixed:** bringing Elite forward was unreliable. Windows often refuses a background program's request to change focus, and the original hid that failure. There's now a standard fallback for that case. The fallback skips a window that is "Not Responding", since attaching to it can stall the autopilot. It also no longer calls `ShowWindow(SW_NORMAL)` every time, which could resize the game window; it only restores a minimised window.
- Galaxy map system names are now typed one character at a time with the focus check, so a pop-up can't receive half a system name. Same 0.25 s between characters as before.
- The "Activate Elite for each key" option is now redundant. It is shown greyed out as "Keep Elite focused (now automatic)" and kept in config files so they still load.

### Install and launch (`start_ed_ap.bat`, `install_requirements.bat`, `readme.md`, `requirements.txt`, `.gitattributes`)

- **Fixed: the launcher's checks never worked.** Nearly all of `start_ed_ap.bat` ran inside one `if ( ... )` block, where cmd.exe reads `%errorlevel%` once, at the start of the block. So:
  - The Python version checks never saw real results; it always tried `py -3.11`.
  - A failed requirements install still reported success and launched.
  - The script is now flat, so every check sees the real result.
  - Exit codes are checked with `if %errorlevel% neq 0`, not `if errorlevel 1`. The latter means "1 or more" and misses negative codes: the newer `py.exe` launcher returns one when the requested Python version isn't installed, and so does a crash.
  - A failed `venv` creation (for example, EDAP still running and holding files open) now stops with a message instead of carrying on.
- **Fixed: a failed install stuck forever.** Setup counted as done once the `venv` folder existed, so every launch after a failed install skipped setup and started a broken environment. Setup now only counts as done once the requirements install successfully.
  - An existing venv on a supported Python is reused: pip is simply run again, which takes seconds when everything is installed.
  - A venv on an unsupported Python, or one whose pip doesn't work, is rebuilt.
- **Fixed: unsupported Python versions.** The launcher, installer and readme offered Python 3.9 and 3.10, but the pinned requirements can't install on them. Resolving the requirements for Windows per version showed:
  - 3.9 and 3.10 fail: pandas 3.0.3, scipy 1.17.1, contourpy 1.3.3 and networkx 3.6.1 are 3.11+ only.
  - 3.14 fails: PaddlePaddle 3.2.2 has no 3.14 build.
  - 3.11, 3.12 and 3.13 all resolve. Both scripts now accept only those, preferring 3.11, and the readme is corrected.
- **Fixed:** `install_requirements.bat` also reported success when pip failed.
- **Fixed:** batch files were stored with Unix line endings, and "Download ZIP" (the readme's recommended install) delivered them that way. cmd.exe can fail to find `goto` labels in such files. `.gitattributes` now gives them Windows line endings on checkout and in ZIP downloads.
- `requirements.txt` re-saved as UTF-8; same packages and versions. As UTF-16, git treated it as binary, so changes to it never showed in diffs.
- **Fixed:** the same invalid `"\F"` escape fixed in pass 1, in the key bindings folder path in `EDKeys.py`.

### Tests and CI (`test/offline/`, `.github/workflows/offline-tests.yml`)

- **Added:** 39 offline tests covering pass 1 and pass 2. They need neither the game nor Windows: Windows-only modules are replaced with stand-ins. The focus guard and the real `Screen.py` focus code are tested against simulated Windows calls, including Windows refusing the focus change.
- **Added:** a GitHub Actions workflow that runs on every push and pull request, on Windows, with Python 3.11, 3.12 and 3.13:
  - compiles every file with warnings treated as errors,
  - lints for real bugs (syntax errors, undefined names),
  - runs the offline tests.
  - The existing workflow was disabled (`if: false`) and targeted Python 3.9.
- `.gitignore` now ignores Python caches in every folder.

### Behaviour changes you might notice

| Situation | Before | Now |
|---|---|---|
| A pop-up or alt-tab takes focus during a run | Autopilot keys go into that window and Elite misses them | Elite is brought back before the next key; GUI log names the window |
| Elite can't be brought back (e.g. an admin window has focus) | Keys go into that window | Same, plus a GUI warning every 10 s; no extra delay per key after the first second |
| You're typing in another window during a run | The autopilot types into your window | Elite takes focus back at its next keypress, so your typing may then go to Elite |
| OCR fails while approaching a station | Disengage detection could die, so SC Assist overshoots | Logged; detection carries on |
| A config file is unreadable at startup | Silently replaced with defaults | Kept as `<name>.unreadable-<date-time>`, defaults used, warning in GUI log |
| `start_ed_ap.bat` with only Python 3.9 or 3.10 | Install fails part-way, then launches broken | Clear message to install 3.11 |
| `start_ed_ap.bat` after a failed install | Skips setup and launches broken | Runs setup again |
| First launch after updating, with a working venv | n/a | Runs pip once (seconds), then starts |
| "Activate Elite for each key" option | Off by default | Always on, option greyed out |

### Testing

- 39 offline tests pass, with no unclosed-file warnings.
- The whole repo compiles with warnings as errors and passes the bug lint.
- Checked against the real tools: OpenCV's behaviour for the error-path file name, pip's resolution of the pinned requirements on Windows for Python 3.9 through 3.14, and pyautogui 0.9.54's source for the typing pause.
- The batch files and the Windows focus code were also desk-reviewed independently, since they can't run here. The review found, and this entry includes fixes for:
  - `if errorlevel 1` missing negative exit codes (a missing Python version could pass the version check, and a crashed pip could count as a successful install),
  - an unchecked `venv` creation, and a venv with broken pip being reused forever,
  - `BringWindowToTop` raising and skipping the `SetForegroundWindow` after it,
  - galaxy map typing being 0.35 s per character instead of 0.25 s (pyautogui adds its own pause),
  - a second of delay per key while focus couldn't be regained, and up to a second of extra hold before a key release,
  - wall-clock timing in the focus retry, and a crash when EDKeys has no GUI callback.
  - The new `Screen.py` tests fail on the code from before these fixes.
- **Not yet tested on Windows or in game.** Before merging:
  - [ ] Fresh "Download ZIP" install with Python 3.11 via `start_ed_ap.bat`
  - [ ] Launch with your existing `venv`: pip runs briefly, then EDAP starts
  - [ ] During an FSD route, alt-tab to another window: Elite comes back at the next key, and the GUI log names the window
  - [ ] Supercruise Assist to a station: drops at the disengage prompt
  - [ ] A route that types a system name into the galaxy map: the name is typed correctly
  - [ ] Settings tab: "Keep Elite focused (now automatic)" is greyed out
  - [ ] Enable Actions on the fork and check the "Offline tests" workflow passes

---

## 2026-11-08: Reliability pass 1

Branch `reliability-pass-1`, [PR #1](https://github.com/LackOfSkillz/EDAPGui/pull/1). Commits `4ced982` and `869a5ba`.

Bug fixes only: no new features, and no changes to tuning, calibration or settings. Code comments are tagged `Fork RP1:` (55 comments across 10 files).

### Journal reading (`EDJournal.py`)

- **Fixed: journal replayed after a game restart.** `current_log` was only set at startup. Once the game started a new journal, every `ship_state()` call reopened it and re-parsed it from line 1. One-shot events re-fired, and the `mission_completed` / `mission_redirected` counters that Robigo relies on kept growing.
- **Fixed: half-written lines stopped the assist.** If the game was mid-write, a partial line raised a JSON error. A write split inside a multi-byte character (non-English names) raised `UnicodeDecodeError`. The journal is now read in binary, and lines are decoded only once complete.
- **Fixed: missed updates.** The "has the file changed?" check read the modification time *after* reading the file. Lines written during the read, or within the same timestamp tick (about 15 ms on Windows), were skipped until the game wrote again. The check now uses modification time plus size, captured before reading.
- **Fixed: journal folder scanned on every call.** Finding the newest journal listed the whole folder and checked every file's timestamp on each `ship_state()` call. There are 100+ call sites, and the SC loop calls it every 50 ms. The result is now cached for 2 seconds, with an immediate rescan after a `Continued` or `Shutdown` event.
- **Fixed: unlocked shared file handle.** The autopilot thread and the SCO monitor thread read the same journal handle with no locking. Reads are now serialised. GUI messages raised during a read are held until the lock is released, so they can't deadlock against the GUI thread.
- **Fixed:** a corrupt journal line is now skipped with a warning instead of raising.
- **Fixed:** invalid `"\F"` escape in the journal folder path (a SyntaxWarning on Python 3.12+).
- When two journal files have the same timestamp, the later part (`.02` over `.01`) is now picked.

### Game JSON files (`StatusParser.py`, `NavRouteParser.py`, `CargoParser.py`, `MarketParser.py`, `FleetCarrierMonitorDataParser.py`)

- **Added:** `JsonFile.py` with `read_game_json()`, one shared reader with bounded retries and capped backoff.
- **Fixed: reads could retry forever.** Status.json retried with no limit. NavRoute, Cargo, Market and FleetCarrier retried with no limit and a backoff that doubled each time (1s, 2s, 4s, 8s...). All now give up after about 6.5 seconds, keep the last good data, and retry on the next call.
- **Fixed:** an unreadable Status.json at startup now raises a clear error instead of hanging.
- **Fixed:** the same check-after-read race as the journal. The change key is now captured before reading.

### Autopilot (`ED_AP.py`, `EDGalaxyMap.py`, `EDShipControl.py`)

- **Fixed: hot loops.** AFK Combat Assist's main loop, the wait-for-scooping loop in `refuel_new`, and the Odyssey galaxy map route wait had no sleep, so each kept a CPU core at 100% while it ran.
- **Fixed: errors were invisible.** When an assist hit an error it was logged at DEBUG only, so at the default log level it just stopped. Errors are now written to `autopilot.log` with a traceback, shown in the GUI log, and announced by voice.
- **Fixed: keys could stay held after an error.** Only a manual stop released keys. An error mid-maneuver now releases them too.
- **Fixed:** entering supercruise also accepts already being in supercruise. The FSD jump flag can be missed with 1-second polling, which left the autopilot boosting forever.
- **Fixed:** waits that could hang forever are now bounded (see the table below).

### Behaviour changes you might notice

| Situation | Before | Now |
|---|---|---|
| Still mass locked when trying to enter supercruise | Boosts forever | Assist stops after 180 s with a reason |
| FSD never engages supercruise | Waits forever | Assist stops after 45 s with a reason |
| Interdiction submit never drops you out | Holds zero throttle forever | Resumes after 60 s |
| Galaxy map route never plots | Waits forever | Gives up after 60 s, closes the map, assist reports it couldn't target the system |
| Searched system not in the first results | Tries forever | Gives up after 10 results |
| Panel won't close when returning to cockpit | Presses UI_Back forever | Stops after 10 presses (0.2 s apart) and logs a warning |
| Game JSON file unreadable | Retries forever | Gives up after about 6.5 s and keeps last good data |
| Assist hits an error | Stops silently | Reason in GUI log and voice ("FSD Assist stopped with an error") |
| AFK Combat reaction time | Instant (busy loop) | Within 0.5 s |

### Testing

- All changed files compile with warnings treated as errors.
- An offline harness (Windows-only modules stubbed) ran 26 checks, passing on every repeat run. It is not in the repo yet; see Planned.
  - Game restart: new journal read once, not replayed.
  - Folder scan throttled: 280,000+ `ship_state()` calls in 0.5 s caused no extra scans.
  - `Continued` event switches to the next journal part immediately.
  - Partial line, corrupt line, and a write split mid-character are all handled.
  - 4 reader threads against a live writer: 400 of 400 events counted exactly once, no errors.
  - GUI callbacks run only after the journal lock is released.
  - JSON reads give up when bounded, recover mid-retry, and keep the last good Status.json data.
- The same scenarios run against the original code confirmed the bugs:
  - Mission count went from 1 to 7 over 6 reads.
  - A half-written line raised an error.
  - A mid-character split raised `UnicodeDecodeError`.
- **Not yet tested in game.** `ED_AP.py`, `EDGalaxyMap.py` and `EDShipControl.py` were reviewed but need Windows and Elite Dangerous to run. Before merging:
  - [ ] FSD Route Assist across several jumps, including a refuel
  - [ ] Supercruise Assist to a station with docking
  - [ ] Waypoint Assist run (galaxy map targeting)
  - [ ] Robigo or AFK Combat, if you use them
  - [ ] Check `autopilot.log` and the GUI log for any new warnings

---

## Planned

Remaining items from the initial analysis, not started yet:

- **One state poller.** A single thread owns the Status.json and journal reads and publishes snapshots. GUI updates go through `root.after` instead of touching Tk from worker threads.
- **Cooperative stop.** A `threading.Event` plus an interruptible sleep, replacing the injected-exception stop (`PyThreadState_SetAsyncExc`). The current method lags behind long sleeps and can interrupt a read mid-way.
- **Route-aware fuel planning.** Use NavRoute.json star classes to decide whether the next scoopable star is in reach, instead of a flat refuel threshold.
- **Safety supervisor.** Watch hull, under-attack, heat and fuel across every mode, with an escalation ladder: log, evade, abort, logout.
- **Condition-based docking and positioning.** Replace fixed timers with signals the game reports, such as the journal's docking "Distance" denial.
- **Status events and notifications.** Publish jump, docked, refuelled and aborted (with reason) events over EDMesg, then add Discord or phone alerts on abort.
- **Replay testing.** Record Status.json, journal and screen frames during a run and replay them offline. (Offline unit tests and CI were added in pass 2.)
- **Assist framework.** An `Assist` base class and registry to replace the seven copy-pasted blocks in `engine_loop`.
- **Housekeeping.**
  - Remove dead code: the old `refuel()`, and about 20 unused variables flagged by lint.
  - Route the ~70 `print()` calls through the logger so they reach `autopilot.log`.
  - Split `requirements.txt` into core and ML extras; it's a full pip freeze that includes torch.
  - Check licensing: `ultralytics` is AGPL-3.0, inside an MIT repo.

---

## Keeping up with upstream

```sh
git remote add upstream https://github.com/SumZer0-git/EDAPGui.git   # once
git fetch upstream
git merge upstream/main
```

Upstream support is through their Discord (see [readme.md](readme.md)); their GitHub Issues page isn't monitored.
