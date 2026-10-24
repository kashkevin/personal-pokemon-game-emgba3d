"""Optional per-world World Event settings: `<world>.events.json` next to the world file.

Handy for a quick test (an event after a minute, always dormant) and for tuning a world; absent means the
defaults in `balance.py`. Like the outbreak settings, an unknown key or a bad value is an error, so a typo never
passes silently. Times are seconds of the world's active time (nobody online: nothing counts).

  {"first_delay": [60, 60], "interval": [300, 300], "duration": 600, "condition_chance": 1.0,
   "shiny_chance": 1.0, "category_weights": {"legendary": 100}}

A shiny event has no timer: it stays until somebody catches it or knocks it out (`duration` does not apply to it).
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
import json
from pathlib import Path

from .balance import BALANCE

CATEGORIES = ("rare", "legendary", "mega", "mythical", "mega_legendary")


@dataclass(frozen=True)
class EventSettings:
    first_delay: tuple = BALANCE.event_first_delay
    interval: tuple = BALANCE.event_interval
    duration: int = BALANCE.event_duration_seconds
    condition_chance: float = BALANCE.event_condition_chance
    shiny_chance: float = BALANCE.event_shiny_chance
    category_weights: dict = field(default_factory=lambda: dict(BALANCE.event_category_weights))

    def __post_init__(self):
        for name in ("first_delay", "interval"):
            pair = getattr(self, name)
            if (not isinstance(pair, (list, tuple)) or len(pair) != 2
                    or any(type(v) not in (int, float) or v < 1 for v in pair) or pair[0] > pair[1]):
                raise ValueError(f"{name} must be [low, high] in seconds, at least 1, low <= high")
            object.__setattr__(self, name, tuple(pair))
        if type(self.duration) is not int or not 30 <= self.duration <= 86_400:
            raise ValueError("duration must be 30 to 86400 seconds")
        if type(self.condition_chance) not in (int, float) or not 0 <= self.condition_chance <= 1:
            raise ValueError("condition_chance must be between 0 and 1")
        if type(self.shiny_chance) not in (int, float) or not 0 <= self.shiny_chance <= 1:
            raise ValueError("shiny_chance must be between 0 and 1")
        weights = self.category_weights
        if (not isinstance(weights, dict) or not weights or set(weights) - set(CATEGORIES)
                or any(type(v) not in (int, float) or v < 0 for v in weights.values()) or not sum(weights.values())):
            raise ValueError(f"category_weights needs weights of {CATEGORIES}, at least one above zero")


DEFAULT_EVENT_SETTINGS = EventSettings()


def load_event_settings(path: Path | str | None) -> EventSettings:
    if path is None or not Path(path).is_file():
        return DEFAULT_EVENT_SETTINGS
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: event settings must be a JSON object")
    unknown = sorted(set(data) - {f.name for f in fields(EventSettings)})
    if unknown:
        raise ValueError(f"{path}: unknown event settings {unknown}")
    try:
        return EventSettings(**data)
    except (ValueError, TypeError) as error:
        raise ValueError(f"{path}: {error}") from None
