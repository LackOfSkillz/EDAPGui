# Fork Change Log

Changes made in this fork ([LackOfSkillz/EDAPGui](https://github.com/LackOfSkillz/EDAPGui)) relative to upstream ([SumZer0-git/EDAPGui](https://github.com/SumZer0-git/EDAPGui)). Upstream's own history stays in [ChangeLog.md](ChangeLog.md).

**Forked from:** upstream `main` at `8e15ca6` (v1.9.3 plus merged PRs through #149, 2026-09-22).

Entries are labelled by date and branch rather than version number, so they don't collide with upstream releases.

**Code comments.** Every changed spot in the code carries a tag comment saying what the original did and why it was changed. Each pass has its own tag: `Fork RP1:` for reliability pass 1, `Fork RP2:` for the next, and so on. `git grep "Fork RP1"` lists every change from a pass.

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
- **Replay testing.** Record Status.json, journal and screen frames during a run and replay them offline. Add the offline harness to the repo as proper tests, and re-enable CI.
- **Assist framework.** An `Assist` base class and registry to replace the seven copy-pasted blocks in `engine_loop`.
- **Housekeeping.**
  - Remove dead code (the old `refuel()`).
  - Split `requirements.txt` into core and ML extras; it's currently a UTF-16 pip freeze that includes torch.
  - Check licensing: `ultralytics` is AGPL-3.0, inside an MIT repo.

---

## Keeping up with upstream

```sh
git remote add upstream https://github.com/SumZer0-git/EDAPGui.git   # once
git fetch upstream
git merge upstream/main
```

Upstream support is through their Discord (see [readme.md](readme.md)); their GitHub Issues page isn't monitored.
