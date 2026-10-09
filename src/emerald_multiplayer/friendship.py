"""Host-authoritative player friendship (owner amendment "PLAYER FRIENDSHIP +
LUCKY TRADING").

Every pair of players has one relationship, stored by the host in
``<world.sqlite3>.friendships.sqlite3`` (bound to the world id, not to a ROM
build). No client save can change it. Points come only from meaningful shared
play the host itself observes: trades, battles together or against each other,
Championships, World Events and time spent online together. Daily caps stop AFK
or repeated-action farming, and every activity reference counts once.

Levels: New, Good, Great, Ultra and Best Friends. Higher levels raise the
chance that a trade between the two becomes a Lucky Trade. Best Friends may
rarely become Lucky Friends: their next successful trade together is
guaranteed Lucky, and only that committed trade consumes the state.

Balance values are the approved recommended defaults in ``balance.py``.
Friendship never gates trading, teams or battles and never changes after PvP
losses.
"""
from __future__ import annotations

from contextlib import contextmanager
import random
import sqlite3
import time
from pathlib import Path
from typing import Callable, Iterable

from .balance import BALANCE

SCOPE = "player-friendship-v1"
KINDS = frozenset(BALANCE.friendship_points)
LUCKY_TRIGGER_KINDS = frozenset({"trade", "battle_together", "gym_together", "event_together", "championship"})
_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS pairs (
        a TEXT NOT NULL, b TEXT NOT NULL, points INTEGER NOT NULL, lucky_friends INTEGER NOT NULL,
        lucky_since REAL, last_lucky_roll REAL, together_seconds REAL NOT NULL, updated REAL NOT NULL,
        PRIMARY KEY (a, b), CHECK (a < b))""",
    """CREATE TABLE IF NOT EXISTS daily (
        a TEXT NOT NULL, b TEXT NOT NULL, day TEXT NOT NULL, kind TEXT NOT NULL, points INTEGER NOT NULL,
        PRIMARY KEY (a, b, day, kind))""",
    """CREATE TABLE IF NOT EXISTS activity (
        a TEXT NOT NULL, b TEXT NOT NULL, kind TEXT NOT NULL, reference TEXT NOT NULL, at REAL NOT NULL,
        PRIMARY KEY (a, b, kind, reference))""",
    """CREATE TABLE IF NOT EXISTS lucky_trades (
        transaction_id TEXT PRIMARY KEY, a TEXT NOT NULL, b TEXT NOT NULL, guaranteed INTEGER NOT NULL, at REAL NOT NULL)""",
)
SESSION_KIND = "session_together"
SESSION_DAILY_CAP = 8  # online-together points per pair per day (AFK is never optimal)


class FriendshipError(ValueError):
    pass


def pair_key(x: str, y: str) -> tuple[str, str]:
    if x == y:
        raise FriendshipError("a player has no friendship with themselves")
    return (x, y) if x < y else (y, x)


def level_for(points: int) -> int:
    level = 0
    for index, threshold in enumerate(BALANCE.friendship_thresholds):
        if points >= threshold:
            level = index
    return level


class FriendshipStore:
    """Event-loop-owned; every mutation commits before returning."""

    def __init__(self, path: Path | str, world_id: str, *, clock: Callable[[], float] = time.time,
                 rng: random.Random | None = None):
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
                raise FriendshipError("friendship data belongs to another world")

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

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None

    # --------------------------------------------------------------- reads
    def _row(self, a: str, b: str):
        return self._db.execute("SELECT points, lucky_friends, lucky_since, last_lucky_roll, together_seconds "
                                "FROM pairs WHERE a=? AND b=?", (a, b)).fetchone()

    def pair(self, x: str, y: str) -> dict:
        a, b = pair_key(x, y)
        row = self._row(a, b)
        points, lucky = (row[0], bool(row[1])) if row else (0, False)
        level = level_for(points)
        thresholds = BALANCE.friendship_thresholds
        next_threshold = thresholds[level + 1] if level + 1 < len(thresholds) else None
        return {"level": level, "name": BALANCE.friendship_levels[level], "points": points,
                "next": next_threshold, "lucky_friends": lucky,
                "lucky_chance": 1.0 if lucky else BALANCE.lucky_trade_chance[level]}

    def view_for(self, player: str, others: Iterable[str]) -> dict:
        return {other: self.pair(player, other) for other in others if other != player}

    def lucky_trade_decision(self, x: str, y: str) -> tuple[bool, bool]:
        """(lucky, guaranteed) for a trade about to be prepared. Not persisted:
        the trade's own durable plan records the outcome."""
        view = self.pair(x, y)
        if view["lucky_friends"]:
            return True, True
        return self._rng.random() < view["lucky_chance"], False

    # ------------------------------------------------------------ mutations
    def _day(self) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime(self._now()))

    def _ensure(self, a: str, b: str) -> None:
        self._db.execute("INSERT OR IGNORE INTO pairs VALUES (?, ?, 0, 0, NULL, NULL, 0, ?)", (a, b, self._now()))

    def _award(self, a: str, b: str, kind: str, points: int) -> int:
        day = self._day()
        used = self._db.execute("SELECT COALESCE(SUM(points), 0) FROM daily WHERE a=? AND b=? AND day=?",
                                (a, b, day)).fetchone()[0]
        room = max(0, BALANCE.friendship_daily_cap - used)
        if kind == SESSION_KIND:
            used_kind = self._db.execute("SELECT COALESCE(SUM(points), 0) FROM daily WHERE a=? AND b=? AND day=? AND kind=?",
                                         (a, b, day, kind)).fetchone()[0]
            room = min(room, max(0, SESSION_DAILY_CAP - used_kind))
        granted = min(points, room)
        if granted:
            self._db.execute("""INSERT INTO daily VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(a, b, day, kind) DO UPDATE SET points = points + excluded.points""",
                (a, b, day, kind, granted))
            self._db.execute("UPDATE pairs SET points = points + ?, updated = ? WHERE a=? AND b=?",
                             (granted, self._now(), a, b))
        return granted

    def record_pair(self, kind: str, x: str, y: str, reference: str) -> dict:
        """Count one meaningful shared activity once; returns what changed."""
        if kind not in KINDS:
            raise FriendshipError(f"unknown friendship activity {kind!r}")
        a, b = pair_key(x, y)
        reference = str(reference)[:128]
        with self._transaction():
            self._ensure(a, b)
            before = self.pair(a, b)
            if self._db.execute("SELECT 1 FROM activity WHERE a=? AND b=? AND kind=? AND reference=?",
                                (a, b, kind, reference)).fetchone():
                return {"pair": (a, b), "granted": 0, "level_up": False, "lucky_friends": False}
            self._db.execute("INSERT INTO activity VALUES (?, ?, ?, ?, ?)", (a, b, kind, reference, self._now()))
            granted = self._award(a, b, kind, BALANCE.friendship_points[kind])
            after = self.pair(a, b)
            lucky = False
            if kind in LUCKY_TRIGGER_KINDS:
                lucky = self._roll_lucky_friends(a, b, after)
        return {"pair": (a, b), "granted": granted, "level_up": after["level"] > before["level"],
                "level": after["name"], "lucky_friends": lucky}

    def record_shared(self, kind: str, actor: str, others: Iterable[str], reference) -> list[dict]:
        return [self.record_pair(kind, actor, other, reference) for other in others if other != actor]

    def _roll_lucky_friends(self, a: str, b: str, view: dict) -> bool:
        if view["level"] != len(BALANCE.friendship_levels) - 1 or view["lucky_friends"]:
            return False
        row = self._row(a, b)
        now = self._now()
        if row[3] is not None and now - row[3] < BALANCE.lucky_friends_cooldown_seconds:
            return False  # one roll per cooldown: spamming an activity never helps
        self._db.execute("UPDATE pairs SET last_lucky_roll=? WHERE a=? AND b=?", (now, a, b))
        if self._rng.random() >= BALANCE.lucky_friends_chance:
            return False
        self._db.execute("UPDATE pairs SET lucky_friends=1, lucky_since=? WHERE a=? AND b=?", (now, a, b))
        return True

    def add_time_together(self, players: list[str], seconds: float) -> list[dict]:
        """Online-together time: small, capped points (never the best way)."""
        changes = []
        unique = sorted(set(players))
        block = BALANCE.friendship_session_minutes * 60
        for i, x in enumerate(unique):
            for y in unique[i + 1:]:
                a, b = pair_key(x, y)
                with self._transaction():
                    self._ensure(a, b)
                    total = self._db.execute("SELECT together_seconds FROM pairs WHERE a=? AND b=?", (a, b)).fetchone()[0]
                    total += seconds
                    blocks, rest = divmod(total, block)
                    self._db.execute("UPDATE pairs SET together_seconds=? WHERE a=? AND b=?", (rest, a, b))
                    for _ in range(int(blocks)):
                        before = self.pair(a, b)
                        granted = self._award(a, b, SESSION_KIND, BALANCE.friendship_points[SESSION_KIND])
                        after = self.pair(a, b)
                        if granted:
                            changes.append({"pair": (a, b), "granted": granted,
                                            "level_up": after["level"] > before["level"], "level": after["name"],
                                            "lucky_friends": False})
        return changes

    def commit_trade(self, transaction_id: str, x: str, y: str, lucky: bool, guaranteed: bool) -> dict:
        """After a committed trade: count it and consume Lucky Friends."""
        a, b = pair_key(x, y)
        if lucky:
            with self._transaction():
                if self._db.execute("SELECT 1 FROM lucky_trades WHERE transaction_id=?", (transaction_id,)).fetchone() is None:
                    self._db.execute("INSERT INTO lucky_trades VALUES (?, ?, ?, ?, ?)",
                                     (transaction_id, a, b, int(guaranteed), self._now()))
                    self._ensure(a, b)
                    self._db.execute("UPDATE pairs SET lucky_friends=0, lucky_since=NULL WHERE a=? AND b=?", (a, b))
        return self.record_pair("trade", a, b, transaction_id)

    def lucky_trade_count(self, x: str, y: str | None = None) -> int:
        if y is None:
            return self._db.execute("SELECT COUNT(*) FROM lucky_trades WHERE a=? OR b=?", (x, x)).fetchone()[0]
        a, b = pair_key(x, y)
        return self._db.execute("SELECT COUNT(*) FROM lucky_trades WHERE a=? AND b=?", (a, b)).fetchone()[0]
