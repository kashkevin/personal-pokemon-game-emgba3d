"""Mass outbreaks on the shared spawn system (EmeraldTogether Phase 4).

The host schedules one outbreak at a time on a Hoenn route the players can
reach: for its duration that map instance holds up to 12 visible wild Pokemon
in total instead of 8 (shared_spawns.OUTBREAK_SLOT_LIMIT), and most new ones
are the outbreak's species. Every player in the world sees the same outbreak
Pokemon, as with every shared spawn (spawn_director.py), and the existing world
notices announce it.

Owner requirements (2026-10-13): host-scheduled; exactly 12 slots during an
outbreak (not 8 + 12); configurable species, weights, duration and cooldown;
compatible with the Phase 2 weather; paused while nobody is online; kept across
host restarts; announced through the existing notices; when it ends the map
returns to 8 safely, without duplicating a Pokemon or taking away one that
somebody is battling (SpawnBoard.trim).

Time is the shared world's *active* clock (Phase 11): durations and cooldowns
count only while somebody is online, and saved state holds remaining durations
only, so a restarted host resumes the same outbreak.

Settings: ``OutbreakSettings`` (defaults below), optionally overridden by a JSON
file beside the world database (``<world.sqlite3>.outbreaks.json``, see
``load_outbreak_settings``).
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
import json
import math
from pathlib import Path
import random
from typing import Callable

STATE_VERSION = 1
TIERS = ("COMMON", "UNCOMMON", "RARE", "VERY_RARE")
LINE_CHARS = 32


def _range(value, name: str) -> tuple[float, float]:
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in value)
            or not 0 < value[0] <= value[1]):
        raise ValueError(f"outbreak setting {name} must be [low, high] seconds with 0 < low <= high")
    return (float(value[0]), float(value[1]))


@dataclass(frozen=True)
class OutbreakSettings:
    """Implementation defaults; every value can be changed in the world's
    outbreak settings file."""
    enabled: bool = True
    first_delay: tuple = (8 * 60.0, 15 * 60.0)   # active seconds before the first outbreak
    cooldown: tuple = (20 * 60.0, 35 * 60.0)     # after one ends, before the next one starts
    duration: tuple = (12 * 60.0, 18 * 60.0)     # how long one lasts
    share: float = 0.7                           # chance that a new spawn there is the outbreak species
    shiny_odds: int = 4096                       # the outbreak species' odds (the approved Gen 6 rate)
    # How likely each rarity tier is to be chosen as the outbreak species
    # (the map's own tiers weigh 30/15/6/3; outbreaks favour less common ones).
    tier_weights: dict = field(default_factory=lambda: {"COMMON": 20, "UNCOMMON": 40, "RARE": 30, "VERY_RARE": 10})
    species_weights: dict = field(default_factory=dict)  # species id -> multiplier (0 excludes it)
    species: tuple = ()                          # when not empty: only these species have outbreaks
    map_types: tuple = ("MAP_TYPE_ROUTE",)       # routes and woods, not caves or buildings
    regions: tuple = ("hoenn",)                  # never the FRLG maps the engine also carries
    exclude_maps: tuple = ()                     # map keys "group.number"
    level_margin: int = 5                        # maps whose lowest wild level <= players' level + margin
    reminder_seconds: tuple = (300.0,)           # a reminder notice this long before the end
    retry_seconds: float = 60.0                  # no outbreak could be placed: try again after this

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise ValueError("outbreak setting enabled must be true or false")
        for name in ("first_delay", "cooldown", "duration"):
            object.__setattr__(self, name, _range(getattr(self, name), name))
        if isinstance(self.share, bool) or not isinstance(self.share, (int, float)) or not 0 < self.share <= 1:
            raise ValueError("outbreak setting share must be in (0, 1]")
        if type(self.shiny_odds) is not int or not 1 <= self.shiny_odds <= 65536:
            raise ValueError("outbreak setting shiny_odds must be an integer 1..65536")
        if (not isinstance(self.tier_weights, dict) or not set(self.tier_weights) <= set(TIERS)
                or any(type(v) is not int or v < 0 for v in self.tier_weights.values())
                or not any(self.tier_weights.values())):
            raise ValueError(f"outbreak setting tier_weights must map {TIERS} to non-negative integers, not all 0")
        if not isinstance(self.species_weights, dict):
            raise ValueError("outbreak setting species_weights must map species ids to multipliers")
        weights = {}
        for key, value in self.species_weights.items():
            species = int(key) if isinstance(key, str) and key.isdigit() else key
            if (type(species) is not int or not 1 <= species <= 1700 or isinstance(value, bool)
                    or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
                raise ValueError("outbreak setting species_weights must map species ids to multipliers >= 0")
            weights[species] = float(value)
        object.__setattr__(self, "species_weights", weights)
        for name in ("species", "map_types", "regions", "exclude_maps", "reminder_seconds"):
            value = getattr(self, name)
            if not isinstance(value, (list, tuple)):
                raise ValueError(f"outbreak setting {name} must be a list")
            object.__setattr__(self, name, tuple(value))
        if any(type(s) is not int or not 1 <= s <= 1700 for s in self.species):
            raise ValueError("outbreak setting species must list species ids")
        if any(not isinstance(v, str) for v in self.map_types + self.regions + self.exclude_maps):
            raise ValueError("outbreak settings map_types, regions and exclude_maps hold strings")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not v > 0 for v in self.reminder_seconds):
            raise ValueError("outbreak setting reminder_seconds must hold positive durations")
        if type(self.level_margin) is not int or not 0 <= self.level_margin <= 100:
            raise ValueError("outbreak setting level_margin must be an integer 0..100")
        if isinstance(self.retry_seconds, bool) or not isinstance(self.retry_seconds, (int, float)) \
                or not self.retry_seconds > 0:
            raise ValueError("outbreak setting retry_seconds must be a positive duration")


DEFAULT_SETTINGS = OutbreakSettings()


def load_outbreak_settings(path: Path | str | None) -> OutbreakSettings:
    """The world's outbreak settings: the defaults, with the values of the JSON
    object in ``path`` (when that file exists) in their place. An unknown key or
    an invalid value is an error, so a typo never passes silently."""
    if path is None or not Path(path).is_file():
        return DEFAULT_SETTINGS
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: outbreak settings must be a JSON object")
    known = {f.name for f in fields(OutbreakSettings)}
    unknown = sorted(set(data) - known)
    if unknown:
        raise ValueError(f"{path}: unknown outbreak settings {unknown}")
    try:
        return OutbreakSettings(**data)
    except ValueError as error:
        raise ValueError(f"{path}: {error}") from None


def _ascii(text: str) -> str:
    return "".join(c if 32 <= ord(c) < 127 else " " for c in text)


def _banner(first: str, second: str = "") -> str:
    first = _ascii(first).replace("|", " ")[:LINE_CHARS].rstrip()
    second = _ascii(second).replace("|", " ")[:LINE_CHARS - 1].rstrip()
    return first if not second else f"{first}|{second}"


def _clock_text(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


class Outbreaks:
    """The outbreak scheduler. Pure logic over the spawn director's catalogue,
    a random source and the active clock; the shared world owns and saves it."""

    def __init__(self, director, *, settings: OutbreakSettings = DEFAULT_SETTINGS,
                 rng: random.Random | None = None, clock: Callable[[], float],
                 notice: Callable[[str], None] = lambda text: None, state: dict | None = None):
        self.director = director
        self.settings = settings
        self.rng = rng or random.Random()
        self.clock = clock
        self.notice = notice
        self.current: dict | None = None
        self.next_id = 1
        self.last_map = ""
        self._next_at = self.clock() + self.rng.uniform(*settings.first_delay)
        if state:
            self._restore(state)

    # ------------------------------------------------------------ state
    def to_state(self) -> dict:
        now = self.clock()
        current = None
        if self.current is not None:
            current = {k: v for k, v in self.current.items() if k != "expires"}
            current["remaining"] = max(0.0, self.current["expires"] - now)
        return {"version": STATE_VERSION, "current": current, "next_remaining": max(0.0, self._next_at - now),
                "next_id": self.next_id, "last_map": self.last_map}

    def _restore(self, state: dict) -> None:
        if state.get("version") != STATE_VERSION:
            return
        now = self.clock()
        self.next_id = max(1, int(state.get("next_id", 1)))
        self.last_map = str(state.get("last_map", ""))
        self._next_at = now + max(0.0, float(state.get("next_remaining", 0.0)))
        current = state.get("current")
        if isinstance(current, dict) and self.director.map_entry(str(current.get("map_key"))) is not None:
            current = dict(current)
            current["expires"] = now + max(0.0, float(current.pop("remaining", 0.0)))
            current["reminded"] = [float(mark) for mark in current.get("reminded", [])]
            self.current = current

    # ------------------------------------------------------------ views
    def active(self) -> dict[str, dict]:
        """Map key -> the outbreak the spawn director applies there."""
        if self.current is None:
            return {}
        c = self.current
        return {c["map_key"]: {"species": c["species"], "share": c["share"], "shiny_odds": c["shiny_odds"]}}

    def view(self) -> dict | None:
        if self.current is None:
            return None
        c = self.current
        group, number = (int(part) for part in c["map_key"].split("."))
        return {"outbreak_id": c["outbreak_id"], "species": c["species"], "name": c["name"], "place": c["place"],
                "map_group": group, "map_number": number,
                "seconds_left": max(0, int(c["expires"] - self.clock()))}

    # ------------------------------------------------------------ choice
    def candidates(self, progression_level: int, *, night: bool,
                   presences: dict[str, dict] | None = None) -> list[tuple[str, int, float]]:
        """(map key, species, weight) for every possible outbreak.

        Maps: the configured regions and map types (Hoenn routes by default),
        whose lowest wild level the players' progression reaches. Species: the
        map's own land families, weighted by the outbreak tier weights, the time
        of day, the map's area boosts and its current weather (the Phase 2
        table: the weather its first player reports, else the map's default),
        each as the most evolved member the map's lowest level allows."""
        s = self.settings
        by_map = self.director.present_players(presences or {})
        out = []
        for key, entry in sorted(self.director.catalogue["maps"].items()):
            if (entry.get("region") not in s.regions or entry.get("map_type") not in s.map_types
                    or key in s.exclude_maps):
                continue
            low = min(min(a, b) for a, b in entry["levels"])
            if low > progression_level + s.level_margin:
                continue
            weather = self.director.weather_for(key, by_map.get(key, []))
            for family, weight in self.director.species_weights(key, low, night, weather, tier_weights=s.tier_weights):
                species = self.director.stage_at(family, low)
                if s.species and species not in s.species:
                    continue
                weight = weight * s.species_weights.get(species, 1.0)
                if key == self.last_map:
                    weight *= 0.25  # rarely the same place twice in a row
                if weight > 0:
                    out.append((key, species, weight))
        return out

    # ------------------------------------------------------------ lifecycle
    def start(self, progression_level: int, *, night: bool = False, presences: dict | None = None,
              map_key: str | None = None, species: int | None = None) -> dict | None:
        """Start an outbreak now (the scheduler's step; tests may name the map
        and species). Returns its view, or None when nothing fits."""
        if self.current is not None:
            return None
        if map_key is None or species is None:
            options = [option for option in self.candidates(progression_level, night=night, presences=presences)
                       if map_key is None or option[0] == map_key]
            if not options:
                return None
            map_key, species, _ = self.rng.choices(options, [w for _, _, w in options])[0]
        entry = self.director.map_entry(map_key)
        if entry is None:
            return None
        now = self.clock()
        self.current = {
            "outbreak_id": self.next_id, "map_key": map_key, "species": int(species),
            "name": self.director.species_name(int(species)), "place": entry.get("name", "SOMEWHERE"),
            "share": float(self.settings.share), "shiny_odds": int(self.settings.shiny_odds),
            "expires": now + self.rng.uniform(*self.settings.duration), "reminded": [],
        }
        self.next_id += 1
        self.last_map = map_key
        self._announce()
        return self.view()

    def _announce(self) -> None:
        c = self.current
        left = c["expires"] - self.clock()
        self.notice(_banner(f"MASS OUTBREAK: {c['name']}!", f"{c['place']}  {_clock_text(left)} left"))

    def end(self) -> dict | None:
        """End the current outbreak: its map returns to 8 (claimed Pokemon
        stay; SpawnBoard.trim) and the cooldown starts."""
        if self.current is None:
            return None
        ended, self.current = self.current, None
        board = self.director.boards.existing(ended["map_key"])
        if board is not None:
            board.set_outbreak(False)
            board.trim()
        self._next_at = self.clock() + self.rng.uniform(*self.settings.cooldown)
        self.notice(_banner(f"The {ended['name']} outbreak", f"on {ended['place']} has ended."))
        return ended

    def tick(self, progression: Callable[[], int] | None, *, night: bool = False,
             presences: dict | None = None) -> bool:
        """One scheduler step (the shared world calls it only while somebody is
        online). True when anything players see changed."""
        if not self.settings.enabled:
            if self.current is not None:
                self.end()
                return True
            return False
        now = self.clock()
        if self.current is not None:
            left = self.current["expires"] - now
            if left <= 0:
                self.end()
                return True
            for mark in sorted(self.settings.reminder_seconds, reverse=True):
                if left <= mark and mark not in self.current["reminded"]:
                    self.current["reminded"].append(mark)
                    if left > mark - 30:  # a host that slept through it says nothing stale
                        self._announce()
                        return True
            return False
        if now < self._next_at:
            return False
        level = progression() if progression is not None else 10
        if self.start(level, night=night, presences=presences) is None:
            self._next_at = now + self.settings.retry_seconds
            return False
        return True
