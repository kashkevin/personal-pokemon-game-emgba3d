"""Owner-approved balance defaults (Oct 9, 2026: "use your recommended values").

Every tunable number for the newer shared-world systems lives here so it can
be changed in one place. Values that the ROM must know (Shiny Charm coin
price, Mega Stone price, Lucky IV floor) live in the engine's
include/constants/multiplayer_balance.h and are mirrored in docs/balance-defaults.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Balance:
    # Shared world clock: one world day per two real hours, paused when empty.
    clock_rate: int = 12
    clock_start_seconds: int = 8 * 3600  # world day 0 begins at 08:00

    # Overworld notices stay available this long for players returning to the field.
    notice_seconds: int = 8

    # World Events (first catch wins; owner decision).
    event_first_delay: tuple = (10 * 60, 20 * 60)
    event_interval: tuple = (25 * 60, 45 * 60)
    event_duration_seconds: int = 15 * 60
    event_category_weights: dict = field(default_factory=lambda: {
        "rare": 50, "legendary": 28, "mega": 15, "mythical": 5, "mega_legendary": 2,
    })
    event_shiny_chance: float = 1 / 64
    event_level_offset_rare: int = 3
    event_level_offset_legendary: int = 8
    event_level_min: int = 5
    event_level_max: int = 70
    event_claim_grace_seconds: int = 120

    # Player friendship (pairs). Points per meaningful shared activity.
    friendship_levels: tuple = ("New Friends", "Good Friends", "Great Friends", "Ultra Friends", "Best Friends")
    friendship_thresholds: tuple = (0, 30, 120, 300, 600)
    friendship_points: dict = field(default_factory=lambda: {
        "trade": 15, "battle_together": 12, "battle_against": 6, "championship": 10,
        "event_together": 10, "gym_together": 20, "session_together": 2,
    })
    friendship_daily_cap: int = 60          # points per pair per real day
    friendship_session_minutes: int = 30    # "played together" credit interval

    # Lucky trades: chance per friendship level (index matches friendship_levels).
    lucky_trade_chance: tuple = (0.05, 0.08, 0.12, 0.20, 0.30)
    lucky_iv_floor: int = 12                 # Lucky Pokemon IVs are raised to at least this (max 31)
    lucky_friends_chance: float = 0.10       # per eligible Best-Friends interaction
    lucky_friends_cooldown_hours: int = 12

    @property
    def lucky_friends_cooldown_seconds(self) -> int:
        return self.lucky_friends_cooldown_hours * 3600

    # PvP wagers (fictional in-game money only).
    wager_max: int = 100_000
    wager_min: int = 100


BALANCE = Balance()
