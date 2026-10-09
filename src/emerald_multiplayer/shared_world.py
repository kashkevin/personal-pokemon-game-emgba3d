"""Host-owned shared-world state: the persistent accelerated world clock,
customized trainer appearances, overworld notices and World Events.

Stored in ``<world.sqlite3>.shared-world.sqlite3`` beside the canonical world
database. It is bound to the world id only (not to a ROM build), so a game
update keeps the same clock, looks and event history. It never edits a save:
World Event Pokemon are caught through the ordinary native capture code.

Owner decisions (Oct 9, 2026):
  * one shared world clock, running 12x real time (a world day every two real
    hours) only while at least one player is connected;
  * World Events: the first player to catch the Pokemon wins it; running away,
    losing or defeating it leaves it for everyone until the timer ends;
  * balance values use the recommended defaults in ``balance.py``.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import random
import re
import sqlite3
import time
from typing import Any, Callable

from .balance import BALANCE

SCOPE = "shared-world-v1"
APPEARANCE_RE = re.compile(r"[0-9a-f]{16}\Z")
DEFAULT_APPEARANCE = "0000000000000000"
NOTICE_CHARS = 48
_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS clock (id INTEGER PRIMARY KEY CHECK (id = 1), seconds INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS appearances (player_id TEXT PRIMARY KEY, appearance TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS events (
        event_id INTEGER PRIMARY KEY, record TEXT NOT NULL, state TEXT NOT NULL,
        winner TEXT, created REAL NOT NULL)""",
    "CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
)


class SharedWorldError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _ascii(text: str) -> str:
    return "".join(c if 32 <= ord(c) < 127 else " " for c in text)[:NOTICE_CHARS]


@dataclass
class _Clock:
    seconds: float
    running_since: float | None


class SharedWorld:
    """Event-loop-owned; every mutation commits before returning."""

    def __init__(self, path: Path | str, world_id: str, *, clock: Callable[[], float] = time.monotonic,
                 rng: random.Random | None = None, event_catalogue: dict | None = None,
                 locations: list | None = None):
        self.path = Path(path)
        self.world_id = world_id
        self._now = clock
        self._rng = rng or random.Random()
        self._db = sqlite3.connect(str(self.path), isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        with self._transaction():
            for statement in _SCHEMA:
                self._db.execute(statement)
            row = self._db.execute("SELECT value FROM metadata WHERE key='world_id'").fetchone()
            if row is None:
                self._db.execute("INSERT INTO metadata VALUES ('world_id', ?)", (world_id,))
                self._db.execute("INSERT INTO metadata VALUES ('scope', ?)", (SCOPE,))
            elif row[0] != world_id:
                raise SharedWorldError("world_mismatch", "shared-world data belongs to another world")
            if self._db.execute("SELECT seconds FROM clock WHERE id=1").fetchone() is None:
                self._db.execute("INSERT INTO clock VALUES (1, ?)", (BALANCE.clock_start_seconds,))
        seconds = self._db.execute("SELECT seconds FROM clock WHERE id=1").fetchone()[0]
        self._clock = _Clock(float(seconds), None)
        self._last_persist = self._now()
        self._active = 0
        self._notice_id = int(self._kv("notice_id", "0"))
        self._notice: dict | None = None
        self._notice_expires = 0.0
        self.catalogue = event_catalogue if event_catalogue is not None else load_event_catalogue()
        self.locations = locations if locations is not None else self.catalogue.get("locations", [])
        self._event: dict | None = None
        self._claim: dict | None = None
        self._next_event_at = self._now() + self._rng.uniform(*BALANCE.event_first_delay)
        self._restore_event()

    # ------------------------------------------------------------------ storage
    @contextmanager
    def _transaction(self):
        self._db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self._db.execute("ROLLBACK")
            raise
        else:
            self._db.execute("COMMIT")

    def _kv(self, key: str, default: str) -> str:
        row = self._db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return default if row is None else row[0]

    def _set_kv(self, key: str, value: str) -> None:
        self._db.execute("INSERT INTO kv VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def close(self) -> None:
        if self._db is None:
            return
        self.persist_clock()
        self._db.close()
        self._db = None

    # ------------------------------------------------------------------ clock
    def _seconds(self) -> float:
        value = self._clock.seconds
        if self._clock.running_since is not None:
            value += (self._now() - self._clock.running_since) * BALANCE.clock_rate
        return value

    def world_seconds(self) -> int:
        return int(self._seconds()) & 0xFFFFFFFF

    def clock_view(self) -> dict:
        return {"seconds": self.world_seconds(), "running": self._clock.running_since is not None}

    def persist_clock(self) -> None:
        with self._transaction():
            self._db.execute("UPDATE clock SET seconds=? WHERE id=1", (int(self._seconds()),))
        self._last_persist = self._now()

    def set_active_players(self, count: int) -> None:
        """Run the clock only while somebody plays (owner choice)."""
        if count > 0 and self._clock.running_since is None:
            self._clock.running_since = self._now()
        elif count == 0 and self._clock.running_since is not None:
            self._clock.seconds = self._seconds()
            self._clock.running_since = None
            self.persist_clock()
        self._active = count

    def time_of_day(self) -> str:
        hour = (self.world_seconds() // 3600) % 24
        if 4 <= hour < 10:
            return "morning"
        if 10 <= hour < 17:
            return "day"
        if 17 <= hour < 20:
            return "evening"
        return "night"

    # ------------------------------------------------------------- appearance
    def appearance(self, player_id: str) -> str | None:
        row = self._db.execute("SELECT appearance FROM appearances WHERE player_id=?", (player_id,)).fetchone()
        return None if row is None else row[0]

    def set_appearance(self, player_id: str, appearance: str) -> str:
        if not isinstance(appearance, str) or APPEARANCE_RE.fullmatch(appearance) is None:
            raise SharedWorldError("invalid_appearance", "appearance must be 16 lower-case hex digits")
        from .appearance import validate_appearance
        validate_appearance(bytes.fromhex(appearance))
        with self._transaction():
            self._db.execute("INSERT INTO appearances VALUES (?, ?) ON CONFLICT(player_id) DO UPDATE SET appearance=excluded.appearance",
                             (player_id, appearance))
        return appearance

    # --------------------------------------------------------------- notices
    def post_notice(self, text: str, to: list[str] | None = None) -> None:
        self._notice_id = self._notice_id % 0x7FFFFFFF + 1
        with self._transaction():
            self._set_kv("notice_id", str(self._notice_id))
        self._notice = {"id": self._notice_id, "text": _ascii(text), "to": sorted(to) if to else None}
        self._notice_expires = self._now() + BALANCE.notice_seconds

    def notice_view(self) -> dict | None:
        if self._notice is not None and self._now() > self._notice_expires:
            self._notice = None
        return None if self._notice is None else dict(self._notice)

    # ---------------------------------------------------------------- events
    def _restore_event(self) -> None:
        row = self._db.execute("SELECT event_id, record FROM events WHERE state='active' ORDER BY event_id DESC LIMIT 1").fetchone()
        if row is None:
            return
        record = json.loads(row[1])
        # Timers count real time only while the host runs; a restarted host
        # resumes the remaining time instead of losing the event.
        record["expires"] = self._now() + max(0.0, float(record.get("remaining", 0)))
        self._event = record

    def _save_event(self, state: str, winner: str | None = None) -> None:
        event = self._event
        stored = {key: value for key, value in event.items() if key != "expires"}
        stored["remaining"] = max(0.0, event["expires"] - self._now())
        with self._transaction():
            self._db.execute("""INSERT INTO events VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET record=excluded.record, state=excluded.state, winner=excluded.winner""",
                (event["event_id"], json.dumps(stored, sort_keys=True), state, winner, time.time()))

    def event_view(self) -> dict | None:
        event = self._event
        if event is None:
            return None
        return {
            "event_id": event["event_id"], "species": event["species"], "level": event["level"],
            "shiny": event["shiny"], "mega": event["mega"], "map_group": event["map_group"],
            "map_number": event["map_number"], "x": event["x"], "y": event["y"],
            "held_item": event["held_item"], "perfect_ivs": event["perfect_ivs"],
            "seconds_left": max(0, int(event["expires"] - self._now())),
            "claimant": None if self._claim is None else self._claim["player_id"],
        }

    def _event_name(self, event: dict) -> str:
        return event.get("name", "A rare Pokemon")

    def spawn_event(self, *, progression_level: int, category: str | None = None) -> dict | None:
        """Create one World Event (used by the scheduler and by tests)."""
        catalogue = self.catalogue
        if not self.locations or not catalogue.get("rare"):
            return None
        weights = BALANCE.event_category_weights
        if category is None:
            choices = [name for name, weight in weights.items() if catalogue.get(name)]
            if not choices:
                return None
            category = self._rng.choices(choices, [weights[name] for name in choices])[0]
        pool = catalogue.get(category) or []
        if not pool:
            return None
        entry = self._rng.choice(pool)
        location = self._rng.choice(self.locations)
        legendary = category in ("legendary", "mythical", "mega_legendary")
        offset = BALANCE.event_level_offset_legendary if legendary else BALANCE.event_level_offset_rare
        level = max(BALANCE.event_level_min, min(BALANCE.event_level_max, progression_level + offset))
        shiny = self._rng.random() < BALANCE.event_shiny_chance
        event_id = int(self._kv("event_id", "0")) + 1
        with self._transaction():
            self._set_kv("event_id", str(event_id))
        self._event = {
            "event_id": event_id, "category": category, "species": entry["species"],
            "name": entry["name"], "level": level, "shiny": shiny, "mega": bool(entry.get("mega")),
            "held_item": entry.get("held_item", 0), "perfect_ivs": 3 if legendary else 1,
            "map_group": location["map_group"], "map_number": location["map_number"],
            "x": location["x"], "y": location["y"], "place": location["name"],
            "expires": self._now() + BALANCE.event_duration_seconds,
        }
        self._claim = None
        self._save_event("active")
        minutes = BALANCE.event_duration_seconds // 60
        label = ("SHINY " if shiny else "") + entry["name"].upper()
        self.post_notice(f"EVENT! {label} near {location['name'].upper()} {minutes}:00")
        return self.event_view()

    def tick_events(self, connected: int, progression: Callable[[], int]) -> bool:
        """Advance timers; returns True when the shared view changed."""
        now = self._now()
        changed = False
        if self._event is not None and now >= self._event["expires"]:
            name = self._event_name(self._event)
            self._save_event("expired")
            self._event, self._claim = None, None
            self.post_notice(f"The {name} has disappeared...")
            self._next_event_at = now + self._rng.uniform(*BALANCE.event_interval)
            changed = True
        if self._claim is not None and self._claim.get("released_at") is not None and now >= self._claim["released_at"]:
            self._claim = None
            changed = True
        if self._event is None and connected > 0 and now >= self._next_event_at:
            if self.spawn_event(progression_level=progression()) is not None:
                changed = True
            self._next_event_at = now + self._rng.uniform(*BALANCE.event_interval)
        if now - self._last_persist >= 30:
            self.persist_clock()
        return changed

    def claim_event(self, player_id: str, event_id: int) -> str:
        event = self._event
        if event is None or event["event_id"] != event_id:
            return "gone"
        if self._claim is not None and self._claim["player_id"] != player_id:
            return "busy"
        self._claim = {"player_id": player_id, "event_id": event_id, "released_at": None}
        return "granted"

    def event_result(self, player_id: str, event_id: int, result: str, display_name: str) -> str:
        event = self._event
        if event is None or event["event_id"] != event_id:
            return "gone"
        if self._claim is None or self._claim["player_id"] != player_id:
            return "not_claimant"
        if result == "caught":
            self._save_event("caught", player_id)
            self.post_notice(f"{display_name.upper()} caught the {event['name'].upper()}!")
            self._event, self._claim = None, None
            self._next_event_at = self._now() + self._rng.uniform(*BALANCE.event_interval)
            return "consumed"
        self._claim = None
        return "released"

    def player_disconnected(self, player_id: str) -> None:
        if self._claim is not None and self._claim["player_id"] == player_id:
            self._claim["released_at"] = self._now() + BALANCE.event_claim_grace_seconds


def load_event_catalogue() -> dict:
    """Event species and locations generated from the pinned engine data."""
    path = Path(__file__).with_name("data") / "world_events.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
