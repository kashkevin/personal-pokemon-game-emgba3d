"""The cooperative Battle Frontier (expansion Phase 8) and Pokemon League (Phase 10): ladders for a team of two.

The League is the same machinery with a fixed ladder: the Elite Four and the Champion as three co-op rounds (see LEAGUE).

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

from . import coop_code, frontier_rewards

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
        return " & ".join(TRAINER_NAMES.get(t, "Trainer") for t in self.trainers)


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


def league_plan(round_no: int, *, exp: bool = False) -> Plan:
    """A League round: the Elite Four or the Champion at their own levels (battle-code level 0)."""
    if type(round_no) is not int or not 1 <= round_no <= len(LEAGUE):
        raise FrontierError("invalid_round", "the League has three rounds")
    a, b, _ = LEAGUE[round_no - 1]
    return Plan(round_no, coop_code.encode(a, b, 0, exp), 0, (a, b), round_no == len(LEAGUE))


def league_prize(round_no: int, *, first_time: bool) -> int:
    amount = LEAGUE_PRIZES[round_no - 1]
    return amount if first_time else max(1, amount // REPEAT_PRIZE_DIVISOR)


def prize_for(level: int, round_no: int, *, first_time: bool) -> int:
    """Money for clearing a round: scales with the level and the set, tripled for a Brain, a tenth when repeated."""
    amount = level * 25 * (2 + set_of(round_no)) // 2
    if round_no % SET_LENGTH == 0:
        amount *= 3
    if not first_time:
        amount //= REPEAT_PRIZE_DIVISOR
    return max(1, min(MAX_PRIZE, amount))


# The Pokemon League as co-op rounds (Elite Four, then the Champion): each entry is (first trainer, second trainer, name).
# The trainers keep their own levels (level 0 in the battle code); each brings three Pokemon, like Emerald's Multi battles.
LEAGUE = (
    (261, 262, "Elite 4 Sidney & Phoebe"),
    (263, 264, "Elite 4 Glacia & Drake"),
    (335, 804, "Champion Wallace & Steven"),
)
LEAGUE_PRIZES = (4000, 6000, 12000)       # money to each player per round
LEAGUE_FIRST_CLEAR_BONUS = 20000          # to each player the first time they clear the League
MODES = ("frontier", "league")

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS frontier_runs (
        run_id TEXT PRIMARY KEY, players TEXT NOT NULL, state TEXT NOT NULL, consent TEXT NOT NULL,
        round INTEGER NOT NULL, streak INTEGER NOT NULL, seed INTEGER NOT NULL, created REAL NOT NULL,
        updated REAL NOT NULL, ended_reason TEXT, mode TEXT NOT NULL DEFAULT 'frontier')""",
    """CREATE TABLE IF NOT EXISTS league_records (
        player_id TEXT PRIMARY KEY, clears INTEGER NOT NULL, best_round INTEGER NOT NULL, first_clear REAL,
        last_clear REAL)""",
    """CREATE TABLE IF NOT EXISTS hall_of_fame (
        entry_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL UNIQUE, players TEXT NOT NULL,
        names TEXT NOT NULL, party TEXT NOT NULL, cleared REAL NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS frontier_attempts (
        battle_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, round INTEGER NOT NULL, code INTEGER NOT NULL,
        level INTEGER NOT NULL, state TEXT NOT NULL, prizes TEXT, paid INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS frontier_attempts_run ON frontier_attempts (run_id, round)",
    # Every closed co-op battle's outcome (1 won, 2 lost, 3 drawn), written before the battle is closed.
    "CREATE TABLE IF NOT EXISTS coop_results (battle_id TEXT PRIMARY KEY, outcome INTEGER NOT NULL, players TEXT NOT NULL)",
    # Battle Points and item prizes of a cleared round, written in the same transaction that settles the round (so they exist
    # exactly once). state: queued (not yet in the wallet) -> sent (in the player's wallet stream) -> delivered / undelivered.
    """CREATE TABLE IF NOT EXISTS frontier_rewards (
        battle_id TEXT NOT NULL, player_id TEXT NOT NULL, kind TEXT NOT NULL, payload INTEGER NOT NULL,
        state TEXT NOT NULL, applied INTEGER, PRIMARY KEY (battle_id, player_id, kind))""",
    # What the host paid and what the shop took, per player (the balance itself is in the save).
    "CREATE TABLE IF NOT EXISTS frontier_bp (player_id TEXT PRIMARY KEY, earned INTEGER NOT NULL, spent INTEGER NOT NULL)",
    # A Battle Points shop purchase: debit -> granting -> done (or refused / refunded). Each step is a wallet adjustment.
    """CREATE TABLE IF NOT EXISTS frontier_purchases (
        purchase_id TEXT PRIMARY KEY, player_id TEXT NOT NULL, item INTEGER NOT NULL, quantity INTEGER NOT NULL,
        price INTEGER NOT NULL, state TEXT NOT NULL, created REAL NOT NULL)""",
    # Each player's team selection for co-op ladder battles: bit n = saved party slot n (validated against the live save when used).
    "CREATE TABLE IF NOT EXISTS frontier_bring (player_id TEXT PRIMARY KEY, mask INTEGER NOT NULL, updated REAL NOT NULL)",
    """CREATE TABLE IF NOT EXISTS frontier_records (
        player_id TEXT PRIMARY KEY, best_streak INTEGER NOT NULL, runs INTEGER NOT NULL, rounds INTEGER NOT NULL,
        earned INTEGER NOT NULL)""",
)


class FrontierBook:
    """Event-loop owned; every mutation commits before returning."""

    def __init__(self, db, transaction, clock: Callable[[], float] = time.time):
        self._db, self._transaction, self._now = db, transaction, clock
        columns = {row[1] for row in self._db.execute("PRAGMA table_info(frontier_runs)")}
        if "mode" not in columns:   # a world file from before the League
            with self._transaction():
                self._db.execute("ALTER TABLE frontier_runs ADD COLUMN mode TEXT NOT NULL DEFAULT 'frontier'")

    # ------------------------------------------------------------------ reads
    @staticmethod
    def _run(row) -> dict:
        return {"run_id": row[0], "players": json.loads(row[1]), "state": row[2], "consent": json.loads(row[3]),
                "round": row[4], "streak": row[5], "seed": row[6], "ended_reason": row[9], "mode": row[10]}

    _RUN = ("SELECT run_id, players, state, consent, round, streak, seed, created, updated, ended_reason, mode "
            "FROM frontier_runs")

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

    def league_record(self, player: str) -> dict:
        row = self._db.execute("SELECT clears, best_round, first_clear, last_clear FROM league_records WHERE player_id=?",
                               (player,)).fetchone()
        return {"clears": row[0], "best_round": row[1], "first_clear": row[2], "last_clear": row[3]} if row else \
            {"clears": 0, "best_round": 0, "first_clear": None, "last_clear": None}

    def hall_of_fame(self, limit: int = 5) -> list[dict]:
        rows = self._db.execute("SELECT entry_id, run_id, players, names, party, cleared FROM hall_of_fame "
                                "ORDER BY entry_id DESC LIMIT ?", (limit,)).fetchall()
        return [{"entry": r[0], "run_id": r[1], "players": json.loads(r[2]), "names": json.loads(r[3]),
                 "party": json.loads(r[4]), "cleared": r[5]} for r in rows]

    def cleared_without_hall(self) -> list[dict]:
        rows = self._db.execute(self._RUN + " WHERE mode='league' AND ended_reason='cleared' AND run_id NOT IN "
                                "(SELECT run_id FROM hall_of_fame)").fetchall()
        return [self._run(row) for row in rows]

    def add_hall_of_fame(self, run_id: str, names: list[str], party: list) -> bool:
        """Enter a cleared League run once (a repeated call changes nothing). `party`: the team's species and levels."""
        run = self.run(run_id)
        if run is None or run["mode"] != "league" or run["ended_reason"] != "cleared":
            raise FrontierError("not_cleared", "only a cleared League run enters the Hall of Fame")
        with self._transaction():
            cursor = self._db.execute("INSERT OR IGNORE INTO hall_of_fame (run_id, players, names, party, cleared) "
                                      "VALUES (?, ?, ?, ?, ?)",
                                      (run_id, json.dumps(run["players"]), json.dumps(names), json.dumps(party), self._now()))
        return cursor.rowcount == 1

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
    def propose(self, run_id: str, proposer: str, partner: str, seed: int, mode: str = "frontier") -> dict:
        if mode not in MODES:
            raise FrontierError("invalid_mode", "unknown ladder")
        if proposer == partner:
            raise FrontierError("no_teammate", "the Frontier is for a team of two")
        existing = self.run(run_id)
        if existing is not None:
            if existing["players"] != [proposer, partner] or existing["mode"] != mode:
                raise FrontierError("run_conflict", "that run belongs to another team")
            return existing
        for player in (proposer, partner):
            current = self.run_of(player)
            if current is not None and current["state"] != "ended":
                raise FrontierError("run_busy", "finish or retire the current Frontier run first")
        now = self._now()
        with self._transaction():
            self._db.execute("INSERT INTO frontier_runs VALUES (?, ?, 'forming', ?, 1, 0, ?, ?, ?, NULL, ?)",
                             (run_id, json.dumps([proposer, partner]), json.dumps([proposer]), seed, now, now, mode))
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
        league = run["mode"] == "league"
        final = league and attempt["round"] >= len(LEAGUE)
        with self._transaction():
            if outcome == 1:
                prizes = {}
                for player in run["players"]:
                    if league:
                        first = attempt["round"] > self.league_record(player)["best_round"]
                        amount = league_prize(attempt["round"], first_time=first)
                        if final and self.league_record(player)["clears"] == 0:
                            amount += LEAGUE_FIRST_CLEAR_BONUS
                        prizes[player] = min(MAX_PRIZE, amount)
                    else:
                        first = attempt["round"] > self.record(player)["best_streak"]
                        prizes[player] = prize_for(attempt["level"], attempt["round"], first_time=first)
                        self._queue_rewards(battle_id, player, attempt["round"], first)
                    if league:
                        self._league_progress(player, attempt["round"], cleared=final)
                    else:
                        self._bump(player, best=attempt["round"], rounds=1)
                self._db.execute("UPDATE frontier_attempts SET state='won', prizes=? WHERE battle_id=?",
                                 (json.dumps(prizes), battle_id))
                self._db.execute("UPDATE frontier_runs SET streak=?, round=?, updated=? WHERE run_id=?",
                                 (attempt["round"], attempt["round"] + 1, self._now(), run["run_id"]))
                if final:
                    self._db.execute("UPDATE frontier_runs SET state='ended', ended_reason='cleared' WHERE run_id=?",
                                     (run["run_id"],))
                    for player in run["players"]:
                        self._bump(player, runs=1)
            else:
                self._db.execute("UPDATE frontier_attempts SET state='lost' WHERE battle_id=?", (battle_id,))
                self._db.execute("UPDATE frontier_runs SET state='ended', ended_reason=?, updated=? WHERE run_id=?",
                                 ("defeated" if outcome == 2 else "draw", self._now(), run["run_id"]))
                for player in run["players"]:
                    self._bump(player, runs=1)
        return self.attempt(battle_id)

    # ---------------------------------------------------------- BP and items
    def _queue_rewards(self, battle_id: str, player: str, round_no: int, first: bool) -> None:
        """Inside settle()'s transaction: this round's Battle Points and (a Brain round, first time) item prize."""
        bp = frontier_rewards.bp_for(round_no, first_time=first)
        self._db.execute("INSERT OR IGNORE INTO frontier_rewards VALUES (?, ?, 'bp', ?, 'queued', NULL)",
                         (battle_id, player, bp))
        item = frontier_rewards.item_for(round_no, first_time=first)
        if item is not None:
            self._db.execute("INSERT OR IGNORE INTO frontier_rewards VALUES (?, ?, 'item', ?, 'queued', NULL)",
                             (battle_id, player, (item[0] << 8) | item[1]))

    def rewards_of(self, battle_id: str) -> list[dict]:
        rows = self._db.execute("SELECT battle_id, player_id, kind, payload, state, applied FROM frontier_rewards "
                                "WHERE battle_id=? ORDER BY player_id, kind", (battle_id,)).fetchall()
        return [self._reward(r) for r in rows]

    @staticmethod
    def _reward(r) -> dict:
        return {"battle_id": r[0], "player_id": r[1], "kind": r[2], "payload": r[3], "state": r[4], "applied": r[5]}

    def rewards_in_flight(self) -> list[dict]:
        """Rewards sent to a wallet whose delivery receipt is still awaited."""
        rows = self._db.execute("SELECT battle_id, player_id, kind, payload, state, applied FROM frontier_rewards "
                                "WHERE state='sent'").fetchall()
        return [self._reward(r) for r in rows]

    def reward_sent(self, battle_id: str, player: str, kind: str) -> None:
        with self._transaction():
            self._db.execute("UPDATE frontier_rewards SET state='sent' WHERE battle_id=? AND player_id=? AND kind=? "
                             "AND state='queued'", (battle_id, player, kind))

    def reward_result(self, battle_id: str, player: str, kind: str, applied: int) -> bool:
        """Record what the game reported for a sent reward, once. Battle Points that landed enter the ledger."""
        with self._transaction():
            row = self._db.execute("SELECT state FROM frontier_rewards WHERE battle_id=? AND player_id=? AND kind=?",
                                   (battle_id, player, kind)).fetchone()
            if row is None or row[0] != "sent":
                return False
            self._db.execute("UPDATE frontier_rewards SET state=?, applied=? WHERE battle_id=? AND player_id=? AND kind=?",
                             ("delivered" if applied else "undelivered", applied, battle_id, player, kind))
            if kind == "bp" and applied:
                self._bp_bump(player, earned=applied)
        return True

    def bp_ledger(self, player: str) -> dict:
        row = self._db.execute("SELECT earned, spent FROM frontier_bp WHERE player_id=?", (player,)).fetchone()
        return {"earned": row[0], "spent": row[1]} if row else {"earned": 0, "spent": 0}

    def _bp_bump(self, player: str, *, earned: int = 0, spent: int = 0) -> None:
        current = self.bp_ledger(player)
        self._db.execute("""INSERT INTO frontier_bp VALUES (?, ?, ?) ON CONFLICT(player_id) DO UPDATE SET
            earned=excluded.earned, spent=excluded.spent""", (player, current["earned"] + earned, current["spent"] + spent))

    def bring(self, player: str) -> int:
        row = self._db.execute("SELECT mask FROM frontier_bring WHERE player_id=?", (player,)).fetchone()
        return row[0] if row else 0

    def set_bring(self, player: str, mask: int) -> None:
        """Keep the player's team selection (0 forgets it: the host then picks the default)."""
        if type(mask) is not int or isinstance(mask, bool) or not 0 <= mask <= 0x3F:
            raise FrontierError("invalid_team", "a team is slots 1 to 6")
        with self._transaction():
            if mask == 0:
                self._db.execute("DELETE FROM frontier_bring WHERE player_id=?", (player,))
            else:
                self._db.execute("""INSERT INTO frontier_bring VALUES (?, ?, ?) ON CONFLICT(player_id) DO UPDATE SET
                    mask=excluded.mask, updated=excluded.updated""", (player, mask, self._now()))

    # -- the Battle Points shop: one open purchase per player; every step is a wallet adjustment keyed by the purchase
    def open_purchase(self, player: str) -> dict | None:
        row = self._db.execute("SELECT purchase_id, player_id, item, quantity, price, state, created FROM frontier_purchases "
                               "WHERE player_id=? AND state IN ('debit', 'granting', 'refunding') ORDER BY created LIMIT 1",
                               (player,)).fetchone()
        return None if row is None else self._purchase(row)

    @staticmethod
    def _purchase(r) -> dict:
        return {"purchase_id": r[0], "player_id": r[1], "item": r[2], "quantity": r[3], "price": r[4], "state": r[5],
                "created": r[6]}

    def purchase(self, purchase_id: str) -> dict | None:
        row = self._db.execute("SELECT purchase_id, player_id, item, quantity, price, state, created FROM frontier_purchases "
                               "WHERE purchase_id=?", (purchase_id,)).fetchone()
        return None if row is None else self._purchase(row)

    def last_purchase(self, player: str) -> dict | None:
        row = self._db.execute("SELECT purchase_id, player_id, item, quantity, price, state, created FROM frontier_purchases "
                               "WHERE player_id=? ORDER BY created DESC LIMIT 1", (player,)).fetchone()
        return None if row is None else self._purchase(row)

    def open_purchases(self) -> list[dict]:
        rows = self._db.execute("SELECT purchase_id, player_id, item, quantity, price, state, created FROM frontier_purchases "
                                "WHERE state IN ('debit', 'granting', 'refunding')").fetchall()
        return [self._purchase(r) for r in rows]

    def start_purchase(self, purchase_id: str, player: str, item: int, quantity: int, price: int) -> dict:
        if self.open_purchase(player) is not None:
            raise FrontierError("purchase_open", "finish the open purchase first")
        with self._transaction():
            self._db.execute("INSERT INTO frontier_purchases VALUES (?, ?, ?, ?, ?, 'debit', ?)",
                             (purchase_id, player, item, quantity, price, self._now()))
        return self.purchase(purchase_id)

    def set_purchase(self, purchase_id: str, state: str, *, spent: int = 0) -> None:
        with self._transaction():
            self._db.execute("UPDATE frontier_purchases SET state=? WHERE purchase_id=?", (state, purchase_id))
            if spent:
                row = self._db.execute("SELECT player_id FROM frontier_purchases WHERE purchase_id=?", (purchase_id,)).fetchone()
                if row is not None:
                    self._bp_bump(row[0], spent=spent)

    def _league_progress(self, player: str, round_no: int, *, cleared: bool) -> None:
        current, now = self.league_record(player), self._now()
        self._db.execute("""INSERT INTO league_records VALUES (?, ?, ?, ?, ?) ON CONFLICT(player_id) DO UPDATE SET
            clears=excluded.clears, best_round=excluded.best_round, first_clear=excluded.first_clear,
            last_clear=excluded.last_clear""",
                         (player, current["clears"] + (1 if cleared else 0), max(current["best_round"], round_no),
                          current["first_clear"] if current["first_clear"] is not None or not cleared else now,
                          now if cleared else current["last_clear"]))

    def mark_paid(self, battle_id: str) -> None:
        attempt = self.attempt(battle_id)
        if attempt is None or attempt["state"] != "won" or attempt["paid"]:
            return
        with self._transaction():
            self._db.execute("UPDATE frontier_attempts SET paid=1 WHERE battle_id=?", (battle_id,))
            for player, amount in attempt["prizes"].items():
                self._bump(player, earned=amount)
