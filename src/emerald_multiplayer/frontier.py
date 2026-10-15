"""The cooperative Battle Frontier (expansion Phase 8): a survival ladder for a team of two.

A team of two (host-formed) takes on rounds of real native co-op battles against pairs of in-game trainers (the engine's
co-op battle, `multiplayer_ladder.c`): the same battle, synchronisation and recovery as a co-op Gym. The host owns everything
that must not be doubled or lost:

* the **run** (forming -> active -> ended), its round and streak, persisted in the world's SQLite file;
* each **attempt** (one native battle per round) and its settlement, exactly once, from the released battle result;
* the **record** of every player (best streak, runs, rounds won, money earned);
* the **prize**, paid through the wallet adjustments (wagers.py), keyed by the battle so a reconnect, a restart or a repeated
  result can never pay twice.

Rules (defaults; Gen 6 battle rules are untouched, only the opposing parties' level and size are set):

* each trainer brings the Pokemon in their saved party (at most `party_limit`, default 3; eggs do not count): put the
  Pokemon you want to bring in your party and save;
* the opposing pair of every round is drawn from a pool that strengthens every 7 rounds, a Frontier Brain pair closes each
  set; the opposing level is the weaker player's average level plus the round (and 2 more per finished set);
* a win clears the round; the team may battle the next one at once or retire (the streak is kept); a loss or a draw ends the
  run; a battle that never started changes nothing;
* no experience (as in the Battle Frontier); a prize in money to each player for each cleared round, in full the first time a
  player reaches that round, a tenth after.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import random
import time
from typing import Callable

from . import coop_code

SET_LENGTH = 7
MAX_PRIZE = 999_999
REPEAT_PRIZE_DIVISOR = 10
DEFAULT_PARTY_LIMIT = 3

TRAINER_NAMES = {
    265: "Roxanne", 266: "Brawly", 267: "Wattson", 268: "Flannery", 269: "Norman", 270: "Winona", 272: "Juan",
    261: "Sidney", 262: "Phoebe", 263: "Glacia", 264: "Drake", 34: "Archie", 602: "Maxie", 335: "Wallace",
    804: "Steven", 805: "Anabel", 806: "Tucker", 807: "Spenser", 808: "Greta", 809: "Noland", 810: "Lucy",
    811: "Brandon",
}
POOLS = (
    (265, 266, 267, 268, 269, 270),                 # set 1: Gym Leaders
    (272, 261, 262, 263, 264, 34),                  # set 2: Juan, the Elite Four, Archie
    (335, 804, 602, 261, 262, 263, 264),            # set 3 and on: the Champions and the Elite Four
)
BRAINS = ((806, 807), (808, 809), (810, 811), (805, 335))   # the closing pair of each set


class FrontierError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass(frozen=True)
class Plan:
    round: int
    code: int
    level: int
    trainers: tuple
    brain: bool

    @property
    def label(self) -> str:
        return " & ".join(TRAINER_NAMES[t] for t in self.trainers)


def set_of(round_no: int) -> int:
    return (round_no - 1) // SET_LENGTH


def level_for(base_level: int, round_no: int) -> int:
    base = max(5, min(100, base_level))
    return min(100, base + (round_no - 1) + 2 * set_of(round_no))


def _pair(seed: int, round_no: int) -> tuple:
    if round_no % SET_LENGTH == 0:
        return BRAINS[set_of(round_no) % len(BRAINS)]
    pool = POOLS[min(set_of(round_no), len(POOLS) - 1)]
    rng = random.Random(f"{seed}:{round_no}")
    pair = tuple(rng.sample(pool, 2))
    if round_no > 1 and (round_no - 1) % SET_LENGTH != 0 and pair == _pair(seed, round_no - 1):
        pair = tuple(rng.sample(pool, 2))
    return pair


def plan(seed: int, round_no: int, base_level: int, *, exp: bool = False) -> Plan:
    """The round's opposing pair and level: pure, so host and tests agree and a restart redraws the same round."""
    if type(round_no) is not int or round_no < 1:
        raise FrontierError("invalid_round", "rounds start at 1")
    level = level_for(base_level, round_no)
    a, b = _pair(seed, round_no)
    return Plan(round_no, coop_code.encode(a, b, level, exp), level, (a, b), round_no % SET_LENGTH == 0)


def prize_for(level: int, round_no: int, *, first_time: bool) -> int:
    """Money for clearing a round: scales with the level and the set, tripled for a Brain, a tenth when repeated."""
    amount = level * 25 * (2 + set_of(round_no)) // 2
    if round_no % SET_LENGTH == 0:
        amount *= 3
    if not first_time:
        amount //= REPEAT_PRIZE_DIVISOR
    return max(1, min(MAX_PRIZE, amount))


SCHEMA = (
    """CREATE TABLE IF NOT EXISTS frontier_runs (
        run_id TEXT PRIMARY KEY, players TEXT NOT NULL, state TEXT NOT NULL, consent TEXT NOT NULL,
        round INTEGER NOT NULL, streak INTEGER NOT NULL, seed INTEGER NOT NULL, created REAL NOT NULL,
        updated REAL NOT NULL, ended_reason TEXT)""",
    """CREATE TABLE IF NOT EXISTS frontier_attempts (
        battle_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, round INTEGER NOT NULL, code INTEGER NOT NULL,
        level INTEGER NOT NULL, state TEXT NOT NULL, prizes TEXT, paid INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS frontier_attempts_run ON frontier_attempts (run_id, round)",
    # Every closed co-op battle's outcome (1 won, 2 lost, 3 drawn), written before the battle is closed.
    "CREATE TABLE IF NOT EXISTS coop_results (battle_id TEXT PRIMARY KEY, outcome INTEGER NOT NULL, players TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS frontier_records (
        player_id TEXT PRIMARY KEY, best_streak INTEGER NOT NULL, runs INTEGER NOT NULL, rounds INTEGER NOT NULL,
        earned INTEGER NOT NULL)""",
)


class FrontierBook:
    """Event-loop owned; every mutation commits before returning."""

    def __init__(self, db, transaction, clock: Callable[[], float] = time.time):
        self._db, self._transaction, self._now = db, transaction, clock

    # ------------------------------------------------------------------ reads
    @staticmethod
    def _run(row) -> dict:
        return {"run_id": row[0], "players": json.loads(row[1]), "state": row[2], "consent": json.loads(row[3]),
                "round": row[4], "streak": row[5], "seed": row[6], "ended_reason": row[9]}

    _RUN = "SELECT run_id, players, state, consent, round, streak, seed, created, updated, ended_reason FROM frontier_runs"

    def run(self, run_id: str) -> dict | None:
        row = self._db.execute(self._RUN + " WHERE run_id=?", (run_id,)).fetchone()
        return None if row is None else self._run(row)

    def run_of(self, player: str) -> dict | None:
        """The player's unfinished run, else their latest finished one."""
        best = None
        for row in self._db.execute(self._RUN + " ORDER BY created DESC").fetchall():
            run = self._run(row)
            if player in run["players"]:
                if run["state"] != "ended":
                    return run
                best = best or run
        return best

    def attempt(self, battle_id: str) -> dict | None:
        row = self._db.execute("SELECT battle_id, run_id, round, code, level, state, prizes, paid FROM frontier_attempts "
                               "WHERE battle_id=?", (battle_id,)).fetchone()
        return None if row is None else self._attempt(row)

    @staticmethod
    def _attempt(row) -> dict:
        return {"battle_id": row[0], "run_id": row[1], "round": row[2], "code": row[3], "level": row[4], "state": row[5],
                "prizes": json.loads(row[6]) if row[6] else {}, "paid": bool(row[7])}

    def open_attempt(self, run_id: str) -> dict | None:
        row = self._db.execute("SELECT battle_id, run_id, round, code, level, state, prizes, paid FROM frontier_attempts "
                               "WHERE run_id=? AND state='issued'", (run_id,)).fetchone()
        return None if row is None else self._attempt(row)

    def unpaid(self) -> list[dict]:
        rows = self._db.execute("SELECT battle_id, run_id, round, code, level, state, prizes, paid FROM frontier_attempts "
                                "WHERE state='won' AND paid=0").fetchall()
        return [self._attempt(row) for row in rows]

    def issued(self) -> list[dict]:
        rows = self._db.execute("SELECT battle_id, run_id, round, code, level, state, prizes, paid FROM frontier_attempts "
                                "WHERE state='issued'").fetchall()
        return [self._attempt(row) for row in rows]

    def record(self, player: str) -> dict:
        row = self._db.execute("SELECT best_streak, runs, rounds, earned FROM frontier_records WHERE player_id=?",
                               (player,)).fetchone()
        return {"best_streak": row[0], "runs": row[1], "rounds": row[2], "earned": row[3]} if row else \
            {"best_streak": 0, "runs": 0, "rounds": 0, "earned": 0}

    def _bump(self, player: str, *, best: int = 0, runs: int = 0, rounds: int = 0, earned: int = 0) -> None:
        current = self.record(player)
        self._db.execute("""INSERT INTO frontier_records VALUES (?, ?, ?, ?, ?) ON CONFLICT(player_id) DO UPDATE SET
            best_streak=excluded.best_streak, runs=excluded.runs, rounds=excluded.rounds, earned=excluded.earned""",
                         (player, max(current["best_streak"], best), current["runs"] + runs,
                          current["rounds"] + rounds, current["earned"] + earned))

    # ---------------------------------------------------------------- results
    def record_result(self, battle_id: str, outcome: int, players) -> None:
        """Keep a closed co-op battle's outcome. Idempotent: the first write stands."""
        if outcome not in (1, 2, 3):
            raise FrontierError("invalid_outcome", "a battle ends won, lost or drawn")
        with self._transaction():
            self._db.execute("INSERT OR IGNORE INTO coop_results VALUES (?, ?, ?)",
                             (battle_id, outcome, json.dumps(list(players))))

    def coop_result(self, battle_id: str) -> int | None:
        row = self._db.execute("SELECT outcome FROM coop_results WHERE battle_id=?", (battle_id,)).fetchone()
        return None if row is None else row[0]

    # ------------------------------------------------------------------ runs
    def propose(self, run_id: str, proposer: str, partner: str, seed: int) -> dict:
        if proposer == partner:
            raise FrontierError("no_teammate", "the Frontier is for a team of two")
        existing = self.run(run_id)
        if existing is not None:
            if existing["players"] != [proposer, partner]:
                raise FrontierError("run_conflict", "that run belongs to another team")
            return existing
        for player in (proposer, partner):
            current = self.run_of(player)
            if current is not None and current["state"] != "ended":
                raise FrontierError("run_busy", "finish or retire the current Frontier run first")
        now = self._now()
        with self._transaction():
            self._db.execute("INSERT INTO frontier_runs VALUES (?, ?, 'forming', ?, 1, 0, ?, ?, ?, NULL)",
                             (run_id, json.dumps([proposer, partner]), json.dumps([proposer]), seed, now, now))
        return self.run(run_id)

    def accept(self, run_id: str, player: str) -> dict:
        run = self.run(run_id)
        if run is None or player not in run["players"]:
            raise FrontierError("no_run", "there is no such Frontier run")
        if run["state"] == "ended":
            raise FrontierError("run_ended", "that run has ended")
        if run["state"] == "active" or player in run["consent"]:
            return run
        consent = sorted(set(run["consent"]) | {player})
        state = "active" if set(consent) == set(run["players"]) else "forming"
        with self._transaction():
            self._db.execute("UPDATE frontier_runs SET consent=?, state=?, updated=? WHERE run_id=?",
                             (json.dumps(consent), state, self._now(), run_id))
        return self.run(run_id)

    def end(self, run_id: str, reason: str) -> dict:
        """Close a run once: counts it for its players when it ever started (a forming run that is declined is not a run)."""
        run = self.run(run_id)
        if run is None:
            raise FrontierError("no_run", "there is no such Frontier run")
        if run["state"] == "ended":
            return run
        if self.open_attempt(run_id) is not None:
            raise FrontierError("battle_open", "a Frontier battle is in progress")
        with self._transaction():
            self._db.execute("UPDATE frontier_runs SET state='ended', ended_reason=?, updated=? WHERE run_id=?",
                             (reason, self._now(), run_id))
            if run["state"] == "active":
                for player in run["players"]:
                    self._bump(player, runs=1)
        return self.run(run_id)

    # --------------------------------------------------------------- attempts
    def issue(self, run_id: str, battle_id: str, plan_: Plan) -> dict:
        """Record the intent to start a round's battle *before* the host invites anybody."""
        run = self.run(run_id)
        if run is None or run["state"] != "active":
            raise FrontierError("not_active", "the run is not active")
        if plan_.round != run["round"]:
            raise FrontierError("wrong_round", "that is not the run's next round")
        if self.open_attempt(run_id) is not None:
            raise FrontierError("battle_open", "a Frontier battle is already waiting")
        with self._transaction():
            self._db.execute("INSERT INTO frontier_attempts VALUES (?, ?, ?, ?, ?, 'issued', NULL, 0, ?)",
                             (battle_id, run_id, plan_.round, plan_.code, plan_.level, self._now()))
        return self.attempt(battle_id)

    def void(self, battle_id: str) -> dict | None:
        """The battle never started (declined, expired, refused): the round is offered again."""
        attempt = self.attempt(battle_id)
        if attempt is None or attempt["state"] != "issued":
            return attempt
        with self._transaction():
            self._db.execute("UPDATE frontier_attempts SET state='void' WHERE battle_id=? AND state='issued'", (battle_id,))
        return self.attempt(battle_id)

    def settle(self, battle_id: str, outcome: int) -> dict | None:
        """Apply a released battle result once. outcome: 1 won, 2 lost, 3 drawn. Returns the settled attempt, or None if
        it was unknown or already settled (a repeated result changes nothing)."""
        attempt = self.attempt(battle_id)
        if attempt is None or attempt["state"] != "issued":
            return None
        run = self.run(attempt["run_id"])
        with self._transaction():
            if outcome == 1:
                prizes = {}
                for player in run["players"]:
                    first = attempt["round"] > self.record(player)["best_streak"]
                    prizes[player] = prize_for(attempt["level"], attempt["round"], first_time=first)
                    self._bump(player, best=attempt["round"], rounds=1)
                self._db.execute("UPDATE frontier_attempts SET state='won', prizes=? WHERE battle_id=?",
                                 (json.dumps(prizes), battle_id))
                self._db.execute("UPDATE frontier_runs SET streak=?, round=?, updated=? WHERE run_id=?",
                                 (attempt["round"], attempt["round"] + 1, self._now(), run["run_id"]))
            else:
                self._db.execute("UPDATE frontier_attempts SET state='lost' WHERE battle_id=?", (battle_id,))
                self._db.execute("UPDATE frontier_runs SET state='ended', ended_reason=?, updated=? WHERE run_id=?",
                                 ("defeated" if outcome == 2 else "draw", self._now(), run["run_id"]))
                for player in run["players"]:
                    self._bump(player, runs=1)
        return self.attempt(battle_id)

    def mark_paid(self, battle_id: str) -> None:
        attempt = self.attempt(battle_id)
        if attempt is None or attempt["state"] != "won" or attempt["paid"]:
            return
        with self._transaction():
            self._db.execute("UPDATE frontier_attempts SET paid=1 WHERE battle_id=?", (battle_id,))
            for player, amount in attempt["prizes"].items():
                self._bump(player, earned=amount)
