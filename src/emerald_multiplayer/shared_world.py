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
NOTICE_CHARS = 64  # two banner lines of at most 32 characters, joined by "|"
LINE_CHARS = 32
REMINDER_SECONDS = (600, 300, 60)
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


def _banner(first: str, second: str = "") -> str:
    """Two short lines for the in-game banner (the ROM breaks lines at "|")."""
    first = _ascii(first).replace("|", " ")[:LINE_CHARS].rstrip()
    second = _ascii(second).replace("|", " ")[:LINE_CHARS - 1].rstrip()
    return first if not second else f"{first}|{second}"


def _clock_text(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


@dataclass
class _Clock:
    seconds: float
    running_since: float | None


@dataclass
class _ActiveTime:
    """Seconds during which at least one player was connected (Phase 11).

    Measured with the injected monotonic clock inside this process only. Every
    timer deadline (World Events, claim grace, the event scheduler, shared
    spawns) is kept in these units, so it stops exactly when the last player
    leaves and resumes exactly when one returns. Absolute values are never
    stored: saved records hold the remaining active duration instead, which
    survives a host restart (a new process starts its own monotonic clock).
    """
    seconds: float = 0.0
    running_since: float | None = None


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
        self._notice_queue: list[dict] = []  # later notices wait their turn on the banner
        self._participants: set[str] = set()  # players who challenged the current event
        self.on_event_finished = None         # callback(participants, event_id) for friendship
        self.catalogue = event_catalogue if event_catalogue is not None else load_event_catalogue()
        self.locations = locations if locations is not None else self.catalogue.get("locations", [])
        self._active_time = _ActiveTime()
        self._event: dict | None = None
        self._claim: dict | None = None
        saved_wait = self._kv("next_event_remaining", "")
        try:
            wait = max(0.0, float(saved_wait)) if saved_wait else None
        except ValueError:
            wait = None
        if wait is None:
            wait = self._rng.uniform(*BALANCE.event_first_delay)
        self._next_event_at = self._active_now() + wait
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
        self.persist_timers()
        self._db.close()
        self._db = None

    # ------------------------------------------------------------ active time
    def _active_now(self) -> float:
        value = self._active_time.seconds
        if self._active_time.running_since is not None:
            value += self._now() - self._active_time.running_since
        return value

    def active_seconds(self) -> float:
        """Active (somebody online) seconds measured by this process."""
        return self._active_now()

    def persist_timers(self) -> None:
        """Save every running deadline as a remaining active duration."""
        if self._db is None:
            return
        with self._transaction():
            self._set_kv("next_event_remaining", repr(max(0.0, self._next_event_at - self._active_now())))
        if self._event is not None:
            self._save_event("active")

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
        """Run the clock only while somebody plays (owner choice).

        Called by the server at the moment a session joins or leaves, so the
        world clock and every timer pause and resume at the actual transition.
        """
        now = self._now()
        if count > 0 and self._clock.running_since is None:
            self._clock.running_since = now
            self._active_time.running_since = now
        elif count == 0 and self._clock.running_since is not None:
            self._clock.seconds = self._seconds()
            self._clock.running_since = None
            if self._active_time.running_since is not None:
                self._active_time.seconds += now - self._active_time.running_since
                self._active_time.running_since = None
            self.persist_clock()
            self.persist_timers()
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
        notice = {"id": self._notice_id, "text": _ascii(text), "to": sorted(to) if to else None}
        if len(self._notice_queue) < 16:
            self._notice_queue.append(notice)
        self._advance_notice()

    def _advance_notice(self) -> None:
        if self._notice is not None and self._now() <= self._notice_expires:
            return
        self._notice = self._notice_queue.pop(0) if self._notice_queue else None
        if self._notice is not None:
            self._notice_expires = self._now() + BALANCE.notice_seconds

    def notice_view(self) -> dict | None:
        self._advance_notice()
        return None if self._notice is None else dict(self._notice)

    # ---------------------------------------------------------------- events
    def _restore_event(self) -> None:
        row = self._db.execute("SELECT event_id, record FROM events WHERE state='active' ORDER BY event_id DESC LIMIT 1").fetchone()
        if row is None:
            return
        record = json.loads(row[1])
        # Timers count only while somebody is online; a restarted host resumes
        # the remaining active time instead of losing the event. Older records
        # carry only "remaining"; an absolute deadline from any earlier format
        # is meaningless in a new process and is dropped.
        record.pop("expires", None)
        try:
            remaining = max(0.0, float(record.pop("remaining", 0) or 0))
        except (TypeError, ValueError):
            remaining = 0.0
        claim = record.pop("claim", None)
        record["expires"] = self._active_now() + remaining
        self._event = record
        if isinstance(claim, dict) and isinstance(claim.get("player_id"), str):
            # Everyone was disconnected by the restart: the claimant keeps the
            # Pokemon for a grace period (or what was left of it) so a battle in
            # progress can still report its result and nothing is caught twice.
            grace = claim.get("grace_remaining")
            try:
                grace = BALANCE.event_claim_grace_seconds if grace is None else max(0.0, float(grace))
            except (TypeError, ValueError):
                grace = BALANCE.event_claim_grace_seconds
            self._claim = {"player_id": claim["player_id"], "event_id": record["event_id"],
                           "released_at": self._active_now() + grace}

    def _save_event(self, state: str, winner: str | None = None) -> None:
        event = self._event
        active_now = self._active_now()
        stored = {key: value for key, value in event.items() if key != "expires"}
        stored["remaining"] = max(0.0, event["expires"] - active_now)
        claim = self._claim
        if state == "active" and claim is not None and claim.get("event_id") == event["event_id"]:
            released_at = claim.get("released_at")
            stored["claim"] = {"player_id": claim["player_id"],
                               "grace_remaining": None if released_at is None else max(0.0, released_at - active_now)}
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
            "seconds_left": max(0, int(event["expires"] - self._active_now())),
            "claimant": None if self._claim is None else self._claim["player_id"],
        }

    def _event_name(self, event: dict) -> str:
        return event.get("name", "RARE POKEMON")

    def _event_label(self, event: dict) -> str:
        return ("SHINY " if event.get("shiny") else "") + self._event_name(event)

    def _announce(self, event: dict, seconds_left: float) -> None:
        label = self._event_label(event)
        first = f"WORLD EVENT! {label}" if len(label) <= LINE_CHARS - 13 else f"{label} appeared!"
        self.post_notice(_banner(first, f"near {event['place']}  {_clock_text(seconds_left)} left"))

    def _choose_location(self, progression_level: int, types: list[str]) -> dict | None:
        reachable = [loc for loc in self.locations if int(loc.get("min_level", 0)) <= progression_level]
        if not reachable:
            reachable = [loc for loc in self.locations if int(loc.get("min_level", 0)) == 0] or list(self.locations)
        if not reachable:
            return None
        last = self._kv("last_place", "")
        weights = []
        for loc in reachable:
            weight = 4.0 if set(types) & set(loc.get("themes", ())) else 1.0
            if loc.get("name") == last and len({l.get("name") for l in reachable}) > 1:
                weight *= 0.25  # rarely the same place twice in a row
            weights.append(weight)
        return self._rng.choices(reachable, weights)[0]

    def _choose_stage(self, entry: dict, level: int) -> dict:
        stages = entry.get("stages")
        if not stages:
            return entry
        eligible = [stage for stage in stages if int(stage.get("min_level", 0)) <= level] or stages[:1]
        best = max(int(stage.get("min_level", 0)) for stage in eligible)
        return self._rng.choice([stage for stage in eligible if int(stage.get("min_level", 0)) == best])

    def spawn_event(self, *, progression_level: int, category: str | None = None) -> dict | None:
        """Create one World Event (used by the scheduler and by tests)."""
        catalogue = self.catalogue
        if not self.locations:
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
        legendary = category in ("legendary", "mythical", "mega_legendary")
        offset = BALANCE.event_level_offset_legendary if legendary else BALANCE.event_level_offset_rare
        level = max(BALANCE.event_level_min, min(BALANCE.event_level_max, progression_level + offset))
        entry = self._rng.choice(pool)
        stage = self._choose_stage(entry, level)
        location = self._choose_location(progression_level, list(entry.get("types", ())))
        if location is None:
            return None
        shiny = self._rng.random() < BALANCE.event_shiny_chance
        event_id = int(self._kv("event_id", "0")) + 1
        with self._transaction():
            self._set_kv("event_id", str(event_id))
            self._set_kv("last_place", location["name"])
        self._event = {
            "event_id": event_id, "category": category, "species": stage["species"],
            "name": stage["name"], "level": level, "shiny": shiny, "mega": bool(entry.get("mega")),
            "held_item": int(entry.get("held_item", 0) or 0), "perfect_ivs": 3 if legendary else 1,
            "map_group": location["map_group"], "map_number": location["map_number"],
            "x": location["x"], "y": location["y"], "place": location["name"],
            "expires": self._active_now() + BALANCE.event_duration_seconds,
            "reminded": [],
        }
        self._claim = None
        self._participants = set()
        self._save_event("active")
        self._announce(self._event, BALANCE.event_duration_seconds)
        return self.event_view()

    def tick_events(self, connected: int, progression: Callable[[], int]) -> bool:
        """Advance timers; returns True when the shared view changed."""
        if (connected > 0) != (self._active > 0):
            # Safety net for callers that report presence only here; the server
            # also calls set_active_players at the exact join/leave moment.
            self.set_active_players(connected)
        wall = self._now()
        now = self._active_now()  # Phase 11: deadlines count only while someone is online
        changed = False
        if self._event is not None and now >= self._event["expires"]:
            label = self._event_label(self._event)
            self._save_event("expired")
            self._finish_participation(self._event["event_id"])
            self._event, self._claim = None, None
            self.post_notice(_banner(f"The {label}", "has disappeared..."))
            self._next_event_at = now + self._rng.uniform(*BALANCE.event_interval)
            changed = True
        if self._event is not None:
            left = self._event["expires"] - now
            reminded = self._event.setdefault("reminded", [])
            for mark in REMINDER_SECONDS:
                if left <= mark and mark not in reminded:
                    reminded.append(mark)
                    if left > mark - 30 and (self._claim is None or self._claim.get("released_at") is not None):
                        self._announce(self._event, left)
                        changed = True
        if self._claim is not None and self._claim.get("released_at") is not None and now >= self._claim["released_at"]:
            self._claim = None
            changed = True
        if self._event is None and connected > 0 and now >= self._next_event_at:
            if self.spawn_event(progression_level=progression()) is not None:
                changed = True
            self._next_event_at = now + self._rng.uniform(*BALANCE.event_interval)
        if wall - self._last_persist >= 30:
            self.persist_clock()
            self.persist_timers()
        return changed

    def claim_event(self, player_id: str, event_id: int) -> str:
        event = self._event
        if event is None or event["event_id"] != event_id:
            return "gone"
        if self._claim is not None and self._claim["player_id"] != player_id:
            return "busy"
        self._claim = {"player_id": player_id, "event_id": event_id, "released_at": None}
        self._participants.add(player_id)
        return "granted"

    def _finish_participation(self, event_id: int) -> None:
        participants, self._participants = sorted(self._participants), set()
        if len(participants) > 1 and callable(self.on_event_finished):
            try:
                self.on_event_finished(participants, event_id)
            except Exception:  # noqa: BLE001 - friendship bookkeeping never blocks the event
                pass

    def event_result(self, player_id: str, event_id: int, result: str, display_name: str) -> str:
        event = self._event
        if event is None or event["event_id"] != event_id:
            return "gone"
        if self._claim is None or self._claim["player_id"] != player_id:
            return "not_claimant"
        if result == "caught":
            self._save_event("caught", player_id)
            name = _ascii(display_name).upper()[:16] or "A TRAINER"
            self.post_notice(_banner(f"{name} caught the", self._event_label(event) + "!"))
            self._finish_participation(event_id)
            self._event, self._claim = None, None
            self._next_event_at = self._active_now() + self._rng.uniform(*BALANCE.event_interval)
            return "consumed"
        self._claim = None
        return "released"

    def player_disconnected(self, player_id: str) -> None:
        if self._claim is not None and self._claim["player_id"] == player_id:
            self._claim["released_at"] = self._active_now() + BALANCE.event_claim_grace_seconds


def load_event_catalogue() -> dict:
    """Event species and locations generated from the pinned engine data."""
    try:
        from .world_event_catalogue import CATALOGUE
    except ImportError:  # a development checkout without the generated module
        return {}
    return CATALOGUE
