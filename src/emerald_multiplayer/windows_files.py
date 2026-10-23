"""Replacing and removing private files on a player's Windows PC.

An antivirus scanner (or the search indexer) opens a file it has just seen written, briefly and without letting anyone
replace or delete it: os.replace and unlink then fail with a sharing violation (PermissionError, WinError 5 or 32) for a
few milliseconds. A trade rewrites its journal several times a second and removes it at the end, so one such moment
ended the trade (the owner's report of 2026-10-23: both players confirmed, the trade window closed and nothing was
traded). These wait the moment out, up to WAIT_SECONDS, then raise the original error; elsewhere they are the plain calls.
"""
from __future__ import annotations

import os
import time

WAIT_SECONDS = 2.0
RETRY_SECONDS = .02


def _patiently(operation, *arguments):
    if os.name != "nt":
        return operation(*arguments)
    deadline = time.monotonic() + WAIT_SECONDS
    while True:
        try:
            return operation(*arguments)
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(RETRY_SECONDS)


def replace_file(source, target):
    """os.replace(source, target), waiting out a scanner's brief hold on Windows."""
    return _patiently(os.replace, source, target)


def unlink_file(path):
    """os.unlink(path), waiting out a scanner's brief hold on Windows."""
    return _patiently(os.unlink, path)
