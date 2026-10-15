"""Wake-up conditions for legendary World Events (expansion Phase 10).

A legendary, mythical or mega-legendary event can be *dormant* when it spawns:
the host announces that something stirs near a place and shows nobody the
Pokemon until its condition is met, once, by the connected players:

  night / day / evening   the world clock's time of day
  rain / sand             any connected player's game reports that weather
                          (the games report the overworld weather in presence)
  together                at least two players standing on the event's map at once

The condition follows the species' type (see CONDITION_BY_TYPE) and, once met,
stays met (latched) for the rest of the event; waking also guarantees a
minimum of WAKE_GRACE_SECONDS to reach the place. Nothing here changes a
battle, a catch or the first-catch rule; a dormant event simply is not offered.
"""
from __future__ import annotations

WAKE_GRACE_SECONDS = 5 * 60
TOGETHER_PLAYERS = 2
WEATHER_CLASSES = {
    "rain": frozenset({"WEATHER_RAIN", "WEATHER_DOWNPOUR", "WEATHER_RAIN_THUNDERSTORM"}),
    "sand": frozenset({"WEATHER_SANDSTORM"}),
}
# First matching type decides; anything else is cooperative.
CONDITION_BY_TYPE = (
    ("water", "rain"), ("electric", "rain"), ("ground", "sand"), ("rock", "sand"),
    ("ghost", "night"), ("dark", "night"), ("psychic", "night"), ("fairy", "night"),
    ("fire", "day"), ("ice", "evening"),
)
LABELS = {"night": "at night", "day": "by day", "evening": "at dusk", "rain": "in the rain",
          "sand": "in a sandstorm", "together": "when trainers gather"}
KINDS = frozenset(LABELS)


def condition_for_types(types) -> str:
    wanted = set(types or ())
    for type_name, kind in CONDITION_BY_TYPE:
        if type_name in wanted:
            return kind
    return "together"


def label(kind: str) -> str:
    return LABELS[kind]


def is_met(kind: str, *, time_of_day: str, weather_names, players_on_map: int) -> bool:
    """`weather_names`: the WEATHER_* names connected players report; `time_of_day`:
    "day", "evening" or "night" from the world clock."""
    if kind in ("night", "day", "evening"):
        return time_of_day == kind
    if kind in WEATHER_CLASSES:
        return bool(WEATHER_CLASSES[kind].intersection(weather_names))
    if kind == "together":
        return players_on_map >= TOGETHER_PLAYERS
    raise ValueError(f"unknown event condition {kind!r}")
