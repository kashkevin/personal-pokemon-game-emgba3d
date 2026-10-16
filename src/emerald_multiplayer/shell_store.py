"""Small private JSON records of the in-game main menu (saved servers, world names, character links).

Only convenience and bookkeeping live in these files: names, addresses, stable world and player identifiers and times. Never a
credential, a certificate or a save (credentials stay in the invitation copy inside the character's own private folder).

Every write is atomic (a temporary file in the same folder, flushed, then renamed over the old one) and the file it replaces is
first kept as ``<name>.bak``. A file that cannot be read or fails validation is not trusted and not overwritten: the store falls
back to its backup when that one is valid and says so (``recovered``); when neither is usable the store is ``unavailable`` and
refuses to write, so a damaged record is never silently replaced by an empty one.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import time

from .live_checkpoint import _atomic, _json_bytes

MAX_BYTES = 262144
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def is_uuid(value):
    return type(value) is str and UUID.fullmatch(value) is not None and value != "00000000-0000-0000-0000-000000000000"


def text_ok(value, limit, *, empty=False):
    return (type(value) is str and (empty or value != "") and len(value) <= limit
            and value.isprintable() and (empty or value.strip() != ""))


def time_ok(value):
    return type(value) in (int, float) and 0 <= value < 4102444800


class StoreUnavailable(RuntimeError):
    """The record on disk is damaged and has no valid backup; nothing is written until a person resolves it."""


class JsonStore:
    """One validated JSON record with atomic writes and a backup of the previous version."""

    def __init__(self, path, fmt, empty, validate, *, clock=time.time):
        self.path = None if path is None else Path(path)
        self.format = fmt
        self._empty = empty
        self._validate = validate
        self.clock = clock
        self.record = empty()
        self.available = True
        self.recovered = False
        if self.path is not None:
            self._load()

    def _read(self, path):
        with Path(path).open("rb") as source:
            raw = source.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("record too large")
        record = json.loads(raw)
        if type(record) is not dict or record.get("format") != self.format:
            raise ValueError("unknown record")
        return self._validate(record)

    def _load(self):
        backup = self.path.with_name(self.path.name + ".bak")
        try:
            self.record = self._read(self.path)
            return
        except FileNotFoundError:
            if not backup.exists():
                return
        except (OSError, ValueError, UnicodeError):
            pass
        try:
            self.record = self._read(backup)
            self.recovered = True
        except (OSError, ValueError, UnicodeError):
            self.available = False

    def save(self, candidate):
        """Validate, then replace the record on disk and in memory. Raises StoreUnavailable if the file is damaged."""
        self._validate(candidate)
        if self.path is None:
            self.record = candidate
            return
        if not self.available:
            raise StoreUnavailable(str(self.path))
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.path.exists():
            try:
                shutil.copyfile(self.path, self.path.with_name(self.path.name + ".bak"))
            except OSError:
                pass
        _atomic(self.path, _json_bytes(candidate))
        self.record = candidate
        self.recovered = False
