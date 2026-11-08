from __future__ import annotations

import json
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
"""


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
