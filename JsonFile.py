from __future__ import annotations

import json
import os
import tempfile
import time
from time import sleep

from EDlogger import logger

"""
File: JsonFile.py

Description:
  Fork RP1: added in this fork (reliability pass 1, see FORK_CHANGELOG.md).
  Shared, bounded reader for the JSON files the game rewrites in place (Status.json, NavRoute.json,
  Cargo.json, Market.json, FleetCarrier.json). The game can be part way through a write when we read,
  so a failed read is retried with a short backoff. Unlike the previous per-parser loops, the number of
  attempts and the backoff are capped, so a file that stays unreadable can no longer hang the caller.

  Fork RP2: also safe writing for EDAP's own files (AP.json, ship_configs.json, waypoints, calibration).
  write_json_atomic() means a file is always either the old version or the new one, never half-written.
  backup_unreadable_file() moves a file that can't be read aside, so it is kept for recovery instead of
  being silently overwritten with defaults.
"""


def write_json_atomic(data, file_path: str, indent: int = 4) -> None:
    """ Writes data as JSON so the file on disk is always complete: it is written to a temporary file in the
    same folder, flushed to disk, then swapped in with a single rename.
    Fork RP2: added. EDAP wrote its config files in place, so a crash, kill or power cut mid-save left a
    truncated file. On the next start, AP.json and ship_configs.json were then silently replaced with
    defaults, losing settings and ship RPY tuning.
    @param data: The data to write.
    @param file_path: Destination file.
    @param indent: JSON indent, same as the files used before.
    @raise OSError: If the file could not be written. Callers keep their existing error handling.
    """
    directory = os.path.dirname(os.path.abspath(file_path))
    fd, tmp_path = tempfile.mkstemp(prefix=os.path.basename(file_path) + '.', suffix='.tmp', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fp:
            json.dump(data, fp, indent=indent)
            fp.flush()
            os.fsync(fp.fileno())

        # On Windows, antivirus or file indexing can hold the destination open for a moment, which makes the
        # rename fail with PermissionError. Retry briefly before giving up.
        for attempt in range(5):
            try:
                os.replace(tmp_path, file_path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                sleep(0.1)
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def backup_unreadable_file(file_path: str) -> str | None:
    """ Moves a file that exists but could not be read to '<name>.unreadable-<date-time>' in the same folder.
    Fork RP2: added, so an unreadable config is kept for recovery instead of being overwritten with defaults.
    @param file_path: The file to move.
    @return: The backup path, or None if there was nothing to move or it could not be moved.
    """
    if not os.path.exists(file_path):
        return None
    backup_path = f"{file_path}.unreadable-{time.strftime('%Y%m%d-%H%M%S')}"
    try:
        os.replace(file_path, backup_path)
        logger.error(f"'{file_path}' could not be read. It has been kept as '{backup_path}'.")
        return backup_path
    except OSError as e:
        logger.error(f"'{file_path}' could not be read, and could not be backed up: {e}")
        return None


def read_game_json(file_path: str, name: str, max_attempts: int = 10,
                   initial_backoff: float = 0.1, max_backoff: float = 1.0) -> dict | None:
    """ Reads and parses a JSON file, retrying on failure.
    With the defaults this waits roughly 6.5 seconds in total before giving up.
    @param file_path: Path to the file.
    @param name: Short name for log messages (i.e. 'Status.json').
    @param max_attempts: Number of read attempts before giving up.
    @param initial_backoff: Delay in seconds after the first failure. Doubles after each failure.
    @param max_backoff: Upper limit for the delay between attempts.
    @return: The parsed data, or None if the file could not be read.
    """
    backoff = initial_backoff
    for attempt in range(1, max_attempts + 1):
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                data = json.load(file)
            if attempt > 2:
                logger.debug(f'{name} read succeeded on attempt {attempt}.')
            return data
        except (OSError, ValueError) as e:
            # ValueError covers an empty or half-written file (JSONDecodeError) and bad encoding.
            if attempt >= 2:
                logger.debug(f'Error reading {name} (attempt {attempt}), file may be open: {e}')
            if attempt < max_attempts:
                sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    logger.warning(f'Unable to read {name} after {max_attempts} attempts.')
    return None
