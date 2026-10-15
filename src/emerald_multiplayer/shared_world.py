"""Host-owned shared-world state: the persistent accelerated world clock,
customized trainer appearances, overworld notices, World Events and the shared
visible wild Pokemon (Phase 3: spawn_director.py, shared_spawns.py).

Stored in ``<world.sqlite3>.shared-world.sqlite3`` beside the canonical world
database. It is bound to the world id only (not to a ROM build), so a game
update keeps the same clock, looks and event history. It never edits a save:
World Event Pokemon are caught through the ordinary native capture code.

Mass outbreaks (Phase 4: outbreaks.py) run on the same shared spawns.

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
# The game's own times of day (engine include/constants/rtc.h, OW_TIMES_OF_DAY =
# GEN_6): while connected the game's clock is this world clock, and its wild
# Pokemon use the night weights in the evening and at night, so the host's
# shared spawns must use the same hours (scripts/multiplayer/
# check_engine_spawn_weights.py compares them with the game).
MORNING_HOURS, DAY_HOURS, EVENING_HOURS = range(4, 11), range(11, 18), range(18, 21)


def time_of_day_for_hour(hour: int) -> str:
    if hour in MORNING_HOURS:
        return "morning"
    if hour in DAY_HOURS:
        return "day"
    if hour in EVENING_HOURS:
        return "evening"
    return "night"
from . import event_conditions
from .frontier import SCHEMA as _FRONTIER_SCHEMA, FrontierBook
from .secret_bases import SCHEMA as _BASE_SCHEMA, SecretBaseBook

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS clock (id INTEGER PRIMARY KEY CHECK (id = 1), seconds INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS appearances (player_id TEXT PRIMARY KEY, appearance TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS events (
        event_id INTEGER PRIMARY KEY, record TEXT NOT NULL, state TEXT NOT NULL,
        winner TEXT, created REAL NOT NULL)""",
    "CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    # The owner of every World Event Pokemon, decided once by the host (the first valid reported catch wins).
    """CREATE TABLE IF NOT EXISTS event_resolutions (
        event_id INTEGER PRIMARY KEY, winner TEXT NOT NULL, seq INTEGER NOT NULL, resolved REAL NOT NULL,
        species INTEGER NOT NULL, level INTEGER NOT NULL, shiny INTEGER NOT NULL, mega INTEGER NOT NULL,
        held_item INTEGER NOT NULL, category TEXT, claimants TEXT NOT NULL)""",
    # Every "caught" report the host received for an event, accepted or not (the audit trail).
    """CREATE TABLE IF NOT EXISTS event_reports (
        report_id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER NOT NULL, player_id TEXT NOT NULL,
        verdict TEXT NOT NULL, at REAL NOT NULL)""",
    *_BASE_SCHEMA,
    *_FRONTIER_SCHEMA,
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
                 locations: list | None = None, spawn_catalogue: dict | None = None,
                 spawn_rng: random.Random | None = None, spawn_tuning=None, outbreak_settings=None,
                 event_condition_chance: float | None = None, event_settings=None):
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
        self.bases = SecretBaseBook(self._db, self._transaction)
        self.frontier = FrontierBook(self._db, self._transaction, clock=time.time)
        from .event_settings import DEFAULT_EVENT_SETTINGS
        self._events = event_settings if event_settings is not None else DEFAULT_EVENT_SETTINGS
        self._condition_chance = self._events.condition_chance if event_condition_chance is None else event_condition_chance
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
        # The player who held the event Pokemon last, and since when the
        # connected claimant has been away from the event's map (active time).
        self._last_claimant: str | None = None
        self._claimant_away_since: float | None = None
        saved_wait = self._kv("next_event_remaining", "")
        try:
            wait = max(0.0, float(saved_wait)) if saved_wait else None
        except ValueError:
            wait = None
        if wait is None:
            wait = self._rng.uniform(*self._events.first_delay)
        self._next_event_at = self._active_now() + wait
        self._restore_event()
        self._init_spawns(spawn_catalogue, spawn_rng, spawn_tuning, outbreak_settings)

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
            self._save_spawns_locked()
        if self._event is not None:
            self._save_event("active")

    # ------------------------------------------------------------ shared spawns
    def _init_spawns(self, catalogue: dict | None, rng: random.Random | None, tuning, outbreak_settings) -> None:
        from .outbreaks import DEFAULT_SETTINGS, Outbreaks
        from .shared_spawns import SpawnBoards
        from .spawn_director import DEFAULT_TUNING, SpawnDirector
        if catalogue is None:
            catalogue = load_spawn_catalogue()
        self.spawns_enabled = bool(catalogue)
        boards = None
        saved = self._kv("spawns", "")
        if saved and self.spawns_enabled:
            try:
                boards = SpawnBoards.from_state(json.loads(saved), self._active_now)
            except (ValueError, KeyError, TypeError):
                boards = None  # an unreadable record never blocks the world: start empty
        if boards is None:
            boards = SpawnBoards(self._active_now, int(self._kv("spawn_next_id", "1") or 1))
        self.spawn_boards = boards
        self.spawn_director = None
        self.outbreaks = None
        if not self.spawns_enabled:
            return
        rng = spawn_rng_or(rng)
        self.spawn_director = SpawnDirector(catalogue, boards, rng=rng, clock=self._active_now,
                                            tuning=tuning or DEFAULT_TUNING)
        state = None
        saved = self._kv("outbreaks", "")
        if saved:
            try:
                state = json.loads(saved)
            except ValueError:
                state = None  # an unreadable record never blocks the world: schedule afresh
        try:
            self.outbreaks = Outbreaks(self.spawn_director, settings=outbreak_settings or DEFAULT_SETTINGS, rng=rng,
                                       clock=self._active_now, notice=self.post_notice,
                                       state=state if isinstance(state, dict) else None)
        except (ValueError, KeyError, TypeError):
            self.outbreaks = Outbreaks(self.spawn_director, settings=outbreak_settings or DEFAULT_SETTINGS, rng=rng,
                                       clock=self._active_now, notice=self.post_notice)

    def _save_spawns_locked(self) -> None:
        """Inside a transaction: the boards and the outbreak scheduler, with
        remaining durations only."""
        if not getattr(self, "spawns_enabled", False):
            return
        self._set_kv("spawns", json.dumps(self.spawn_boards.to_state(), sort_keys=True, separators=(",", ":")))
        self._set_kv("spawn_next_id", str(self.spawn_boards.next_id))
        if self.outbreaks is not None:
            self._set_kv("outbreaks", json.dumps(self.outbreaks.to_state(), sort_keys=True, separators=(",", ":")))

    def save_spawns(self) -> None:
        if self._db is None or not self.spawns_enabled:
            return
        with self._transaction():
            self._save_spawns_locked()

    def _night(self) -> bool:
        return self.time_of_day() in ("evening", "night")

    def spawn_outbreaks(self) -> dict[str, dict]:
        """Map key -> the active mass outbreak (Phase 4, outbreaks.py)."""
        return self.outbreaks.active() if self.outbreaks is not None else {}

    def outbreak_view(self) -> dict | None:
        return self.outbreaks.view() if self.outbreaks is not None else None

    def tick_spawns(self, presences: dict[str, dict | None], progression: Callable[[], int] | None = None) -> bool:
        """The outbreak scheduler, then one director step for every map with
        players on it. Time only passes while somebody is online, so nothing
        ages, starts or ends while the world is empty."""
        if not self.spawns_enabled or self._active == 0:
            return False
        changed = False
        live = {player: presence for player, presence in presences.items() if presence is not None}
        if self.outbreaks is not None and self.outbreaks.tick(progression, night=self._night(), presences=live):
            changed = True
            self.save_spawns()  # an outbreak's start and end are durable at once
        if self.spawn_director.update(presences, night=self._night(), outbreaks=self.spawn_outbreaks()):
            changed = True
        return changed

    def spawn_view(self, player_id: str, presence: dict | None) -> dict | None:
        if not self.spawns_enabled:
            return None
        return self.spawn_director.view(player_id, presence)

    def spawn_action(self, player_id: str, action: str, spawn_id: int, result: str | None) -> str:
        """A game claims, reports or releases a shared wild Pokemon."""
        from .shared_spawns import CONSUMED, GONE, GRANTED
        if not self.spawns_enabled:
            return GONE
        found = self.spawn_boards.find(spawn_id)
        if found is None:
            return GONE
        board, _slot = found
        if action == "claim":
            outcome = board.claim(player_id, spawn_id)
        elif action == "result":
            outcome = board.result(player_id, spawn_id, result or "cancelled")
        elif action == "release":
            outcome = board.release(player_id, spawn_id)
        else:
            raise SharedWorldError("invalid_spawn_action", "unsupported shared spawn action")
        if outcome in (GRANTED, CONSUMED):
            # Ownership changes are durable at once: a host crash can neither
            # resurrect a caught Pokemon nor forget who is battling one.
            self.save_spawns()
        return outcome

    def player_connected(self, player_id: str) -> None:
        if self._claim is not None and self._claim["player_id"] == player_id:
            # The claimant is back within its grace period: it keeps the event
            # Pokemon until it reports or walks away (the spawns do the same).
            self._claim["released_at"] = None
            self._claimant_away_since = None
        if getattr(self, "spawns_enabled", False):
            for board in self.spawn_boards.boards():
                board.player_reconnected(player_id)

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
        return time_of_day_for_hour((self.world_seconds() // 3600) % 24)

    # ------------------------------------------------------- PokeNav world view
    _WEATHER_LABELS = {"WEATHER_SUNNY": "Clear", "WEATHER_SUNNY_CLOUDS": "Clouds", "WEATHER_RAIN": "Rain",
                       "WEATHER_DOWNPOUR": "Downpour", "WEATHER_RAIN_THUNDERSTORM": "Thunderstorm",
                       "WEATHER_SNOW": "Snow", "WEATHER_DROUGHT": "Sun", "WEATHER_SANDSTORM": "Sandstorm",
                       "WEATHER_FOG": "Fog", "WEATHER_FOG_HORIZONTAL": "Fog", "WEATHER_FOG_DIAGONAL": "Fog",
                       "WEATHER_VOLCANIC_ASH": "Ash", "WEATHER_SHADE": "Overcast", "WEATHER_ABNORMAL": "Strange"}

    def _place_name(self, group: int, number: int) -> str:
        director = getattr(self, "spawn_director", None)
        entry = director.map_entry(f"{group}.{number}") if director is not None else None
        name = entry.get("name") if entry else None
        return name[:40] if isinstance(name, str) and name else f"Area {group}-{number}"

    def nav_view(self, presences: dict[str, dict | None]) -> dict:
        """What the PokeNav-style World pages show (Phase 7): where each online
        player is and the weather there, the running outbreak and World Event."""
        director = getattr(self, "spawn_director", None)
        players = []
        for player_id, presence in sorted(presences.items()):
            if presence is None:
                continue
            code = presence.get("weather")
            name = director._weather_names.get(code) if director is not None and type(code) is int else None
            label = None if name is None else self._WEATHER_LABELS.get(name, name.removeprefix("WEATHER_").title())
            players.append({"player_id": player_id,
                            "place": self._place_name(presence["map_group"], presence["map_number"]),
                            "weather": label})
        outbreak = self.outbreak_view()
        if outbreak is not None:
            outbreak = {"name": outbreak["name"][:40], "place": outbreak["place"][:40],
                        "seconds_left": outbreak["seconds_left"]}
        status = self.event_status()
        event = None if status is None else {key: value for key, value in status.items()
                                             if key != "waiting" or value is not None}
        seconds = self.world_seconds()
        return {"players": players[:4], "outbreak": outbreak, "event": event,
                "time": f"{seconds // 3600 % 24:02d}:{seconds // 60 % 60:02d}", "tod": self.time_of_day()}

    def habitat_view(self, presence: dict | None) -> dict:
        """The PokeNav "this area" page (Phase 7): what the host's own encounter tables say about the map a player stands on
        (the same tables the shared wild Pokemon use, which scripts/multiplayer/check_engine_spawn_weights.py compares with
        the game). Nothing here is invented: an area without wild-Pokemon data says so."""
        director = getattr(self, "spawn_director", None)
        if presence is None or director is None:
            return {"known": False, "place": "Unknown area"}
        group, number = presence["map_group"], presence["map_number"]
        key = f"{group}.{number}"
        entry = director.map_entry(key)
        place = self._place_name(group, number)
        if not entry or not getattr(self, "spawns_enabled", False):
            return {"known": False, "place": place}
        levels = [value for pair in entry["levels"] for value in pair if value]
        low, high = (min(levels), max(levels)) if levels else (0, 0)
        code = presence.get("weather")
        weather = director._weather_names.get(code) if type(code) is int else None
        if weather is None:
            weather = entry.get("weather")
        weights = director.species_weights(key, high or 1, self._night(), weather)
        top = sorted(weights, key=lambda item: (-item[1], item[0]))[:3]
        common = [director.species_name(director.stage_at(index, high or 1)).title()[:20] for index, _ in top]
        favors = [name.removeprefix("TYPE_").title() for name in entry.get("boost", ())][:3]
        label = self._WEATHER_LABELS.get(weather, (weather or "").removeprefix("WEATHER_").title()) if weather else None
        return {"known": True, "place": place, "levels": [low, high], "common": common, "favors": favors,
                "time": self.time_of_day(), "weather": label or None}

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
        last = record.pop("last_claimant", None)
        self._last_claimant = last if isinstance(last, str) else None
        record["expires"] = self._active_now() + remaining
        if self._resolution(record["event_id"]) is not None:
            # The host stopped between deciding who caught it and closing the event: it is closed now.
            winner = self._resolution(record["event_id"])["winner"]
            self._event = record
            self._save_event("caught", winner)
            self._event = None
            return
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
            self._last_claimant = claim["player_id"]

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
        if state == "active" and self._last_claimant is not None:
            stored["last_claimant"] = self._last_claimant
        with self._transaction():
            self._db.execute("""INSERT INTO events VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET record=excluded.record, state=excluded.state, winner=excluded.winner""",
                (event["event_id"], json.dumps(stored, sort_keys=True), state, winner, time.time()))

    def _dormant(self, event: dict | None = None) -> bool:
        event = self._event if event is None else event
        return event is not None and event.get("awake") is False

    def event_view(self) -> dict | None:
        """The event the games draw: none while a dormant event waits for its condition."""
        event = self._event
        if event is None or self._dormant(event):
            return None
        return self._full_event_view()

    def _full_event_view(self) -> dict:
        event = self._event
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

    def _announce_dormant(self, event: dict) -> None:
        self.post_notice(_banner("Something stirs near", event["place"]))
        self.post_notice(_banner("It wakes " + event_conditions.label(event["condition"]), "See PokeNav: World"))

    def event_status(self) -> dict | None:
        """What the PokeNav World page may say: a dormant event hides its species."""
        event = self._event
        if event is None:
            return None
        left = max(0, int(event["expires"] - self._active_now()))
        if self._dormant(event):
            return {"name": "Something stirs", "place": event["place"][:40], "seconds_left": left,
                    "waiting": "Wakes " + event_conditions.label(event["condition"])}
        return {"name": self._event_label(event)[:40], "place": str(event.get("place", "SOMEWHERE"))[:40],
                "seconds_left": left, "waiting": None}

    def tick_event_conditions(self, presences: dict[str, dict | None]) -> bool:
        """Wake a dormant event when its condition is met by the connected players."""
        event = self._event
        if event is None or not self._dormant(event):
            return False
        from .spawn_director import PRESENT_ACTIVITIES
        director = getattr(self, "spawn_director", None)
        names = set()
        on_map = 0
        for presence in presences.values():
            if presence is None or presence.get("activity") not in PRESENT_ACTIVITIES:
                continue
            code = presence.get("weather")
            if director is not None and type(code) is int and code in director._weather_names:
                names.add(director._weather_names[code])
            if (presence.get("map_group"), presence.get("map_number")) == (event["map_group"], event["map_number"]):
                on_map += 1
        if not event_conditions.is_met(event["condition"], time_of_day=self.time_of_day(),
                                       weather_names=names, players_on_map=on_map):
            return False
        now = self._active_now()
        event["awake"] = True
        event["expires"] = max(event["expires"], now + event_conditions.WAKE_GRACE_SECONDS)
        self._save_event("active")
        self._announce(event, event["expires"] - now)
        return True

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
        weights = self._events.category_weights
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
            "expires": self._active_now() + self._events.duration,
            "reminded": [],
        }
        self._claim = None
        self._last_claimant = None
        self._claimant_away_since = None
        self._participants = set()
        if legendary and self._condition_chance > 0 and self._rng.random() < self._condition_chance:
            self._event["condition"] = event_conditions.condition_for_types(entry.get("types", ()))
            self._event["awake"] = False
        self._save_event("active")
        if self._dormant():
            self._announce_dormant(self._event)
        else:
            self._announce(self._event, self._events.duration)
        return self._full_event_view()

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
            slept = self._dormant()
            self._save_event("expired")
            self._finish_participation(self._event["event_id"])
            self._event, self._claim = None, None
            self.post_notice(_banner("The legend slipped away", "before it woke...") if slept
                             else _banner(f"The {label}", "has disappeared..."))
            self._next_event_at = now + self._rng.uniform(*self._events.interval)
            changed = True
        if self._event is not None and not self._dormant():
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
            self._next_event_at = now + self._rng.uniform(*self._events.interval)
        if wall - self._last_persist >= 30:
            self.persist_clock()
            self.persist_timers()
        return changed

    # ------------------------------------------------------- catch resolution
    def _resolution(self, event_id: int) -> dict | None:
        row = self._db.execute("SELECT event_id, winner, seq, resolved, species, level, shiny, mega, held_item, category, "
                               "claimants FROM event_resolutions WHERE event_id=?", (event_id,)).fetchone()
        if row is None:
            return None
        return {"event_id": row[0], "winner": row[1], "seq": row[2], "resolved": row[3], "species": row[4],
                "level": row[5], "shiny": bool(row[6]), "mega": bool(row[7]), "held_item": row[8], "category": row[9],
                "claimants": json.loads(row[10])}

    def resolutions(self, limit: int = 20) -> list[dict]:
        """The resolved catches, newest first (the ledger of who owns what)."""
        rows = self._db.execute("SELECT event_id FROM event_resolutions ORDER BY seq DESC LIMIT ?", (limit,)).fetchall()
        return [self._resolution(row[0]) for row in rows]

    def _log_report(self, event_id: int, player_id: str, verdict: str) -> None:
        with self._transaction():
            self._db.execute("INSERT INTO event_reports (event_id, player_id, verdict, at) VALUES (?, ?, ?, ?)",
                             (event_id, player_id, verdict, time.time()))

    def reports(self, event_id: int) -> list[tuple[str, str]]:
        return [(r[0], r[1]) for r in self._db.execute(
            "SELECT player_id, verdict FROM event_reports WHERE event_id=? ORDER BY report_id", (event_id,))]

    def _resolve(self, event: dict, winner: str) -> None:
        """Record the owner of the Pokemon, durably, once."""
        seq = self._db.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM event_resolutions").fetchone()[0]
        with self._transaction():
            self._db.execute("INSERT INTO event_resolutions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                             (event["event_id"], winner, seq, time.time(), event["species"], event["level"],
                              int(bool(event["shiny"])), int(bool(event["mega"])), event["held_item"],
                              event.get("category"), json.dumps(event.get("claimants", []))))

    def claim_event(self, player_id: str, event_id: int) -> str:
        event = self._event
        if event is None or event["event_id"] != event_id or self._dormant(event) or self._resolution(event_id):
            return "gone"
        if self._claim is not None and self._claim["player_id"] != player_id:
            return "busy"
        changed = self._claim is None or self._claim.get("released_at") is not None
        self._claim = {"player_id": player_id, "event_id": event_id, "released_at": None}
        self._last_claimant = player_id
        self._claimant_away_since = None
        self._participants.add(player_id)
        claimants = event.setdefault("claimants", [])
        if player_id not in claimants:
            claimants.append(player_id)
            changed = True
        if changed:
            # Durable at once, like a shared spawn's claim: a host restart in
            # the middle of the battle keeps it for this player.
            self._save_event("active")
        return "granted"

    def _finish_participation(self, event_id: int) -> None:
        participants, self._participants = sorted(self._participants), set()
        if len(participants) > 1 and callable(self.on_event_finished):
            try:
                self.on_event_finished(participants, event_id)
            except Exception:  # noqa: BLE001 - friendship bookkeeping never blocks the event
                pass

    def event_result(self, player_id: str, event_id: int, result: str, display_name: str) -> str:
        """A game reports how its battle with the event Pokemon ended.

        Catch ownership (expansion Phase 11): the **first valid reported catch wins**, decided here, in the order reports
        arrive, whoever holds the claim at that moment. A report is valid when its sender claimed this event (so a game that
        lost its claim to a disconnect, and caught the Pokemon anyway, still counts if it reports first). The winner is
        recorded durably before anything else changes; a replay of the winner's report is answered the same ("consumed");
        every other report finds it "gone". Nothing here can give one event two owners.
        """
        prior = self._resolution(event_id)
        if prior is not None:
            if result == "caught":
                self._log_report(event_id, player_id, "replay" if prior["winner"] == player_id else "late")
            return "consumed" if result == "caught" and prior["winner"] == player_id else "gone"
        event = self._event
        if event is None or event["event_id"] != event_id:
            if result == "caught":
                self._log_report(event_id, player_id, "expired")   # the game has it; nobody else can, no duplicate
            return "gone"
        holder = self._claim["player_id"] if self._claim is not None else None
        if result == "caught":
            if player_id != holder and player_id not in event.get("claimants", ()):
                self._log_report(event_id, player_id, "never_claimed")
                return "not_claimant"
            self._resolve(event, player_id)
            self._log_report(event_id, player_id, "winner")
            self._save_event("caught", player_id)
            name = _ascii(display_name).upper()[:16] or "A TRAINER"
            self.post_notice(_banner(f"{name} caught the", self._event_label(event) + "!"))
            if holder is not None and holder != player_id:
                self.post_notice(_banner(f"{name} caught it first!", "Your battle ends here."), to=[holder])
            self._finish_participation(event_id)
            self._event, self._claim = None, None
            self._next_event_at = self._active_now() + self._rng.uniform(*self._events.interval)
            return "consumed"
        if holder != player_id:
            return "not_claimant"
        self._claim = None
        return "released"

    def player_disconnected(self, player_id: str) -> None:
        if self._claim is not None and self._claim["player_id"] == player_id:
            self._claim["released_at"] = self._active_now() + BALANCE.event_claim_grace_seconds

    def tick_event_claim(self, presences: dict[str, dict | None]) -> bool:
        """Let go of an event claim whose connected claimant left the event's map.

        The game claims the event Pokemon when its player talks to it and
        reports the battle's result; it never sends a release. A game that was
        reset, crashed or restarted between the two (while its companion stayed
        connected) left the claim held for the rest of the event, and everybody
        else was told it was busy. The claim now ends after the claimant has
        been on another map for ``event_claim_away_seconds`` of active time; a
        result that comes later is still accepted (``event_result``).
        Returns True when the shared view changed.
        """
        claim, event = self._claim, self._event
        if claim is None or event is None or claim.get("released_at") is not None:
            self._claimant_away_since = None
            return False
        presence = presences.get(claim["player_id"])
        if presence is None:
            return False  # disconnected: the grace period applies instead
        if (presence.get("map_group"), presence.get("map_number")) == (event["map_group"], event["map_number"]):
            self._claimant_away_since = None
            return False
        now = self._active_now()
        if self._claimant_away_since is None:
            self._claimant_away_since = now
            return False
        if now - self._claimant_away_since < BALANCE.event_claim_away_seconds:
            return False
        self._claim, self._claimant_away_since = None, None
        self._save_event("active")
        return True
        if getattr(self, "spawns_enabled", False):
            for board in self.spawn_boards.boards():
                board.player_disconnected(player_id)


def spawn_rng_or(rng: random.Random | None) -> random.Random:
    return rng if rng is not None else random.Random()


def load_spawn_catalogue() -> dict:
    """Shared spawn data generated from the pinned engine (empty without it)."""
    try:
        from .shared_spawn_catalogue import CATALOGUE
    except ImportError:  # a development checkout without the generated module
        return {}
    return CATALOGUE


def load_event_catalogue() -> dict:
    """Event species and locations generated from the pinned engine data."""
    try:
        from .world_event_catalogue import CATALOGUE
    except ImportError:  # a development checkout without the generated module
        return {}
    return CATALOGUE
