"""What the main menu remembers: the last session, recent invitations, when each world was last played.

Only convenience lives here. It never holds a credential, a certificate or a save: a path to a host world record or to a friend
invitation file (both stay where the player put them), the address the host last typed, and times. A missing, damaged or
oversized file is ignored (the menu then has nothing to continue) and is never overwritten by a failed read, like the display
preferences. Nothing here starts a game, creates a world or changes an enrollment; those stay in the session and setup code.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import time

from .live_checkpoint import _atomic, _json_bytes

FORMAT = "emerald-launcher-recent-v1"
FILE_NAME = "launcher-recent.json"
MAX_BYTES = 16384
MAX_INVITATIONS = 5
MAX_WORLDS = 64
MODES = ("host", "join")


@dataclass(frozen=True)
class LastSession:
    mode: str
    selection: Path
    address: str
    internet: bool
    played: float

    @property
    def world_name(self):
        """The world's folder name (a random identifier) for a host session, '' for a join."""
        return self.selection.parent.name if self.mode == "host" else ""


def _text(value, limit):
    return type(value) is str and 0 < len(value) <= limit and "\x00" not in value


def _path(value):
    return _text(value, 1024) and Path(value).is_absolute()


def _time(value):
    return type(value) in (int, float) and 0 <= value < 4102444800  # before 2100


def _validate(record):
    if type(record) is not dict or set(record) != {"format", "last", "invitations", "worlds"} or record["format"] != FORMAT:
        raise ValueError("unknown recent-sessions file")
    last = record["last"]
    if last is not None:
        if (type(last) is not dict or set(last) != {"mode", "selection", "address", "internet", "played"}
                or last["mode"] not in MODES or not _path(last["selection"]) or not _text(last["address"], 64)
                or type(last["internet"]) is not bool or not _time(last["played"])):
            raise ValueError("invalid last session")
    invitations = record["invitations"]
    if (type(invitations) is not list or len(invitations) > MAX_INVITATIONS
            or any(not _path(item) for item in invitations) or len(set(invitations)) != len(invitations)):
        raise ValueError("invalid recent invitations")
    worlds = record["worlds"]
    if (type(worlds) is not dict or len(worlds) > MAX_WORLDS
            or any(not _text(key, 128) or not _time(value) for key, value in worlds.items())):
        raise ValueError("invalid world times")
    return record


def _empty():
    return {"format": FORMAT, "last": None, "invitations": [], "worlds": {}}


class RecentStore:
    def __init__(self, directory=None, *, clock=time.time):
        self.path = Path(directory) / FILE_NAME if directory is not None else None
        self.clock = clock
        self.record = _empty()
        self.available = True
        if self.path is not None:
            try:
                with self.path.open("rb") as source:
                    raw = source.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise ValueError("recent-sessions file too large")
                self.record = _validate(json.loads(raw))
            except FileNotFoundError:
                pass
            except (OSError, ValueError, UnicodeError):
                self.available = False   # kept as it is: not overwritten, not trusted

    @property
    def last(self):
        last = self.record["last"]
        if last is None:
            return None
        return LastSession(last["mode"], Path(last["selection"]), last["address"], last["internet"], float(last["played"]))

    @property
    def invitations(self):
        return tuple(Path(item) for item in self.record["invitations"])

    def world_played(self, world_directory):
        value = self.record["worlds"].get(Path(world_directory).name)
        return None if value is None else float(value)

    def _save(self, candidate):
        _validate(candidate)
        self.record = candidate
        if not self.available or self.path is None:
            return False
        try:
            _atomic(self.path, _json_bytes(candidate))
        except OSError:
            return False
        return True

    def record_session(self, mode, selection, address, internet):
        """A session was started with these choices: remember them for Continue Adventure."""
        if mode not in MODES:
            raise ValueError("invalid mode")
        selection = Path(selection)
        now = float(self.clock())
        candidate = json.loads(json.dumps(self.record))
        candidate["last"] = {"mode": mode, "selection": str(selection), "address": str(address)[:64] or "127.0.0.1",
                             "internet": bool(internet), "played": now}
        if mode == "join":
            items = [str(selection)] + [item for item in candidate["invitations"] if item != str(selection)]
            candidate["invitations"] = items[:MAX_INVITATIONS]
        else:
            worlds = candidate["worlds"]
            worlds[selection.parent.name] = now
            while len(worlds) > MAX_WORLDS:
                del worlds[min(worlds, key=worlds.get)]
        return self._save(candidate)

    def forget_last(self):
        candidate = json.loads(json.dumps(self.record))
        candidate["last"] = None
        return self._save(candidate)


def continue_target(store):
    """(LastSession, '') when Continue Adventure can start it, else (None, reason): 'none' (nothing played yet) or 'missing'
    (the world record or invitation was moved or deleted)."""
    last = store.last
    if last is None:
        return None, "none"
    try:
        present = last.selection.is_file()
    except OSError:
        present = False
    return (last, "") if present else (None, "missing")


def describe_age(then, now):
    """'today', 'yesterday', '3 days ago', ... for the menu's 'last played' line."""
    days = int((now - then) // 86400)
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 60:
        return f"{days} days ago"
    return f"{days // 30} months ago"
