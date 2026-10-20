"""The durable record of free-for-all battles: four players (1v1v1v1) and, since Update 32, three (1v1v1).

A free-for-all is not a PvP-archive battle (that archive is built around two sides), not a co-op ladder battle and carries no
wager and no experience. The host keeps what happened here, keyed by the battle ID so a restart, a reconnect or a repeated
RELEASE can never record (or count) the same battle twice.

The outcome is the native result code of a free-for-all: 1..4 (a 1v1v1: 1..3) name the winning trainer's slot (slot + 1;
slot 0 is the challenger), 5 is a draw (the last trainers fell together). It is the same for every participant. A
trainer's standing counts both sizes together.
"""
from __future__ import annotations

import json
from typing import Callable

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS ffa_results (battle_id TEXT PRIMARY KEY, outcome INTEGER NOT NULL, players TEXT NOT NULL, "
    "winner TEXT, recorded REAL NOT NULL)",
)
DRAW = 5


class FfaResultError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


class FfaBook:
    def __init__(self, db, transaction: Callable, *, clock: Callable[[], float]):
        self._db, self._transaction, self._now = db, transaction, clock

    def record(self, battle_id: str, outcome: int, players) -> str | None:
        """Keep a closed free-for-all's outcome (idempotent: the first write stands). Returns the winner, None for a draw."""
        players = list(players)
        if len(players) not in (3, 4) or len(set(players)) != len(players):
            raise FfaResultError("invalid_players", "a free-for-all has three or four distinct trainers")
        if type(outcome) is not int or not (1 <= outcome <= len(players) or outcome == DRAW):
            raise FfaResultError("invalid_outcome",
                                 f"a free-for-all ends with a winner's slot (1-{len(players)}) or a draw ({DRAW})")
        winner = None if outcome == DRAW else players[outcome - 1]
        with self._transaction():
            self._db.execute("INSERT OR IGNORE INTO ffa_results VALUES (?, ?, ?, ?, ?)",
                             (battle_id, outcome, json.dumps(players), winner, self._now()))
        return self.winner_of(battle_id)

    def result(self, battle_id: str) -> dict | None:
        row = self._db.execute("SELECT outcome, players, winner FROM ffa_results WHERE battle_id=?", (battle_id,)).fetchone()
        if row is None:
            return None
        return dict(battle_id=battle_id, outcome=row[0], players=json.loads(row[1]), winner=row[2])

    def winner_of(self, battle_id: str) -> str | None:
        found = self.result(battle_id)
        return None if found is None else found["winner"]

    def record_of(self, player: str) -> dict:
        """A trainer's free-for-all standing: battles fought, won, drawn."""
        played = won = drawn = 0
        for outcome, players, winner in self._db.execute("SELECT outcome, players, winner FROM ffa_results"):
            if player not in json.loads(players):
                continue
            played += 1
            won += winner == player
            drawn += outcome == DRAW
        return dict(played=played, won=won, drawn=drawn, lost=played - won - drawn)
