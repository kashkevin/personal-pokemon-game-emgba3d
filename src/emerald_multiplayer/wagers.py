"""Optional PvP wagers in fictional in-game money (project brief "OPTIONAL
BATTLE WAGERS"; master spec: both sides confirm, team wagers respect each
wallet, no accidental loss, no duplication by disconnecting).

Rules (approved recommended defaults, docs/balance-defaults.md):
  * the challenger proposes an amount for a pending challenge; every other
    trainer must accept that exact amount, otherwise the battle cannot start;
  * each trainer stakes the same amount from their own wallet;
  * a win moves each losing trainer's stake to the opposing winner in the same
    team slot (1v1: loser -> winner); a draw, cancellation or a battle that
    never starts moves nothing;
  * money moves only after the host has a verified, closed result.

Money moves through per-player *wallet adjustments* applied by each player's
own game (world mailbox): every adjustment has a per-player sequence number
stored in the save (VAR_MP_WALLET_SEQ), so an adjustment applies exactly once
per save; a reloaded older save simply applies it again together with its
money. Debits collect first; the winner is credited only what was actually
collected, so a disconnect can never create money.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import sqlite3
import time
from pathlib import Path
from typing import Callable

from . import rewards
from .balance import BALANCE

SCOPE = "pvp-wagers-v1"
MAX_MONEY = 999_999
# Pinned build layout (checked with offsetof against the engine build):
# SaveBlock1.money is XOR-encrypted with SaveBlock2.encryptionKey.
MONEY_OFFSET = 0x490
ENCRYPTION_KEY_OFFSET = 0xAC
_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS wagers (
        battle_id TEXT PRIMARY KEY, amount INTEGER NOT NULL, sender TEXT NOT NULL, players TEXT NOT NULL,
        accepted TEXT NOT NULL, state TEXT NOT NULL, outcome INTEGER, updated REAL NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS wallet (
        player_id TEXT NOT NULL, seq INTEGER NOT NULL, delta INTEGER NOT NULL, battle_id TEXT NOT NULL,
        credit_to TEXT, applied INTEGER, created REAL NOT NULL,
        PRIMARY KEY (player_id, seq))""",
    # The highest sequence a player's save reported applying. Keeps new
    # adjustments ahead of the save even if this database was ever restored
    # from an older backup.
    "CREATE TABLE IF NOT EXISTS wallet_base (player_id TEXT PRIMARY KEY, seq INTEGER NOT NULL)",
)


def money_from_snapshot(snapshot) -> int:
    """A verified checkpoint's money (0-999,999)."""
    raw = int.from_bytes(snapshot.save_block1[MONEY_OFFSET:MONEY_OFFSET + 4], "little")
    key = int.from_bytes(snapshot.save_block2[ENCRYPTION_KEY_OFFSET:ENCRYPTION_KEY_OFFSET + 4], "little")
    return min(raw ^ key, MAX_MONEY)


def format_money(amount: int) -> str:
    return f"${amount:,}"


class WagerError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class Wagers:
    """Host-owned; every mutation commits before returning."""

    def __init__(self, path: Path | str, world_id: str, *, clock: Callable[[], float] = time.time):
        self.path = Path(path)
        self._now = clock
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
                raise WagerError("world_mismatch", "wager data belongs to another world")

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

    # ----------------------------------------------------------------- wagers
    def _wager(self, battle_id: str) -> dict | None:
        row = self._db.execute("SELECT amount, sender, players, accepted, state, outcome FROM wagers WHERE battle_id=?",
                               (battle_id,)).fetchone()
        if row is None:
            return None
        return {"battle_id": battle_id, "amount": row[0], "sender": row[1], "players": json.loads(row[2]),
                "accepted": json.loads(row[3]), "state": row[4], "outcome": row[5]}

    def view(self, battle_id: str) -> dict | None:
        return self._wager(battle_id)

    def pending_for(self, player: str) -> list[dict]:
        """Unsettled wallet adjustments for a player (newest last)."""
        rows = self._db.execute("SELECT seq, delta, battle_id, applied FROM wallet WHERE player_id=? ORDER BY seq",
                                (player,)).fetchall()
        return [{"seq": r[0], "delta": r[1], "battle_id": r[2], "applied": r[3]} for r in rows]

    def propose(self, battle_id: str, sender: str, players: list[str], amount: int, funds: dict[str, int]) -> dict:
        if type(amount) is not int or not (amount == 0 or BALANCE.wager_min <= amount <= BALANCE.wager_max):
            raise WagerError("invalid_wager", f"wagers range from {BALANCE.wager_min} to {BALANCE.wager_max}")
        if sender not in players:
            raise WagerError("not_participant", "only a trainer in this battle may set its wager")
        current = self._wager(battle_id)
        if current is not None and current["state"] != "proposed":
            raise WagerError("wager_locked", "this battle's wager can no longer change")
        if amount and any(funds.get(player, 0) < amount for player in players):
            raise WagerError("insufficient_funds", "every trainer needs enough money for the wager")
        with self._transaction():
            if amount == 0:
                self._db.execute("DELETE FROM wagers WHERE battle_id=?", (battle_id,))
                return None
            self._db.execute("""INSERT INTO wagers VALUES (?, ?, ?, ?, ?, 'proposed', NULL, ?)
                ON CONFLICT(battle_id) DO UPDATE SET amount=excluded.amount, sender=excluded.sender,
                players=excluded.players, accepted=excluded.accepted, state='proposed', updated=excluded.updated""",
                (battle_id, amount, sender, json.dumps(sorted(players)), json.dumps([sender]), self._now()))
        return self._wager(battle_id)

    def accept(self, battle_id: str, player: str, amount: int, funds: int) -> dict:
        current = self._wager(battle_id)
        if current is None or current["state"] != "proposed":
            raise WagerError("no_wager", "there is no open wager on this battle")
        if player not in current["players"] or current["amount"] != amount:
            raise WagerError("wager_changed", "accept the exact wager shown")
        if funds < amount:
            raise WagerError("insufficient_funds", "you need enough money for the wager")
        accepted = sorted(set(current["accepted"]) | {player})
        with self._transaction():
            self._db.execute("UPDATE wagers SET accepted=?, updated=? WHERE battle_id=?",
                             (json.dumps(accepted), self._now(), battle_id))
        return self._wager(battle_id)

    def decline(self, battle_id: str, player: str) -> None:
        current = self._wager(battle_id)
        if current is None or current["state"] != "proposed" or player not in current["players"]:
            return
        with self._transaction():
            self._db.execute("DELETE FROM wagers WHERE battle_id=?", (battle_id,))

    def ready(self, battle_id: str) -> bool:
        """A battle may start: no wager, or every trainer accepted it."""
        current = self._wager(battle_id)
        return current is None or set(current["accepted"]) == set(current["players"])

    def lock(self, battle_id: str, funds: dict[str, int]) -> None:
        current = self._wager(battle_id)
        if current is None or current["state"] != "proposed":
            return
        if set(current["accepted"]) != set(current["players"]):
            raise WagerError("wager_pending", "every trainer must accept the wager first")
        if any(funds.get(player, 0) < current["amount"] for player in current["players"]):
            raise WagerError("insufficient_funds", "a trainer no longer has enough money for the wager")
        with self._transaction():
            self._db.execute("UPDATE wagers SET state='locked', updated=? WHERE battle_id=?", (self._now(), battle_id))

    def cancel(self, battle_id: str) -> None:
        current = self._wager(battle_id)
        if current is not None and current["state"] in ("proposed", "locked"):
            with self._transaction():
                self._db.execute("UPDATE wagers SET state='void', updated=? WHERE battle_id=?", (self._now(), battle_id))

    def settle(self, battle_id: str, players: list[str], mode: int, outcome: int) -> list[tuple[str, int]]:
        """Queue the stake transfers of a closed battle; returns debits queued.

        ``players`` is the battle's fixed order (2v2: teams are players[::2]
        and players[1::2]); ``outcome`` 1/2 names the winning team, 3 a draw.
        """
        current = self._wager(battle_id)
        if current is None or current["state"] not in ("locked", "proposed"):
            return []
        if current["state"] == "proposed" or outcome not in (1, 2):
            with self._transaction():
                self._db.execute("UPDATE wagers SET state='settled', outcome=?, updated=? WHERE battle_id=?",
                                 (outcome, self._now(), battle_id))
            return []
        teams = (players[::2], players[1::2]) if mode == 3 else ([players[0]], [players[1]])
        winners, losers = (teams[0], teams[1]) if outcome == 1 else (teams[1], teams[0])
        debits = []
        with self._transaction():
            self._db.execute("UPDATE wagers SET state='settled', outcome=?, updated=? WHERE battle_id=?",
                             (outcome, self._now(), battle_id))
            for loser, winner in zip(losers, winners):
                self._queue(loser, -current["amount"], battle_id, credit_to=winner)
                debits.append((loser, current["amount"]))
        return debits

    # --------------------------------------------------------------- wallet
    def _last_seq(self, player: str) -> int:
        issued = self._db.execute("SELECT COALESCE(MAX(seq), 0) FROM wallet WHERE player_id=?", (player,)).fetchone()[0]
        base = self._db.execute("SELECT seq FROM wallet_base WHERE player_id=?", (player,)).fetchone()
        return max(issued, base[0] if base else 0)

    def _queue(self, player: str, delta: int, battle_id: str, *, credit_to: str | None = None) -> int:
        seq = self._last_seq(player) + 1
        if seq > 0xFFFF:
            raise WagerError("wallet_exhausted", "this player's wallet sequence is exhausted")
        self._db.execute("INSERT INTO wallet VALUES (?, ?, ?, ?, ?, NULL, ?)",
                         (player, seq, delta, battle_id, credit_to, self._now()))
        return seq

    def grant(self, player: str, amount: int, ref: str) -> int | None:
        """Queue a prize of ``amount`` for ``player``, once per (player, ref): a repeated call (a retried settlement, a
        restart between paying and recording it) returns None and queues nothing. Returns the wallet sequence."""
        if type(amount) is not int or not 1 <= amount <= MAX_MONEY or not isinstance(ref, str) or not ref:
            raise WagerError("invalid_prize", "a prize is 1 to 999,999")
        with self._transaction():
            if self._db.execute("SELECT 1 FROM wallet WHERE player_id=? AND battle_id=? AND delta>0",
                                (player, ref)).fetchone() is not None:
                return None
            return self._queue(player, amount, ref)

    def grant_reward(self, player: str, kind: int, payload: int, ref: str, *, tower: bool = False) -> int | None:
        """Queue a Battle Frontier reward (rewards.py: Battle Points, an item, or a shop's Battle Points debit) for ``player``
        once per (player, ref): a repeat returns None and queues nothing. Returns the wallet sequence. A Battle Tower word
        (kinds 6 and 7) is accepted only from a caller that knows the game has the Tower (``tower``: tower_service.py)."""
        if not isinstance(ref, str) or not ref:
            raise WagerError("invalid_reward", "a reward needs a reference")
        try:
            word = rewards.encode(kind, payload, tower=tower)
        except rewards.RewardError as error:
            raise WagerError("invalid_reward", str(error)) from error
        with self._transaction():
            if self._db.execute("SELECT 1 FROM wallet WHERE player_id=? AND battle_id=?", (player, ref)).fetchone() is not None:
                return None
            return self._queue(player, word, ref)

    def entry(self, player: str, ref: str) -> dict | None:
        """The wallet adjustment queued for (player, ref): its sequence, delta and what the game reported moving (None
        until it reports)."""
        row = self._db.execute("SELECT seq, delta, applied FROM wallet WHERE player_id=? AND battle_id=? ORDER BY seq LIMIT 1",
                               (player, ref)).fetchone()
        return None if row is None else {"seq": row[0], "delta": row[1], "applied": row[2]}

    def _full_seq(self, player: str, low: int) -> int:
        """The save's sequence from its low byte (the host knows every issued seq)."""
        last = self._last_seq(player)
        candidate = last - ((last - low) & 0xFF)
        return max(0, candidate)

    def battle_points_moved(self, player: str, saved_seq: int, live_seq_low) -> int:
        """The Battle Points the player's game moved after its save: points added minus points taken by the adjustments
        after ``saved_seq`` (the save's VAR_MP_WALLET_SEQ) up to the one the game reports having applied now
        (``live_seq_low``: its world presence's low byte), each as much as its receipt says (one applied whose receipt is
        still on its way: in full). Nothing without a reported sequence; a game back on an older save holds none of
        them (it applies them again)."""
        if type(live_seq_low) is not int or not 0 <= live_seq_low <= 0xFF or type(saved_seq) is not int:
            return 0
        moved = 0
        for delta, applied in self._db.execute("SELECT delta, applied FROM wallet WHERE player_id=? AND seq>? AND seq<=?",
                                               (player, saved_seq, self._full_seq(player, live_seq_low))):
            decoded = rewards.decode(delta)
            if decoded is not None and decoded[0] in (rewards.KIND_BP, rewards.KIND_BP_DEBIT):
                amount = decoded[1] if applied is None else applied
                moved += amount if decoded[0] == rewards.KIND_BP else -amount
        return moved

    def applied_seq(self, player: str) -> int:
        """The highest wallet sequence this player's save reported applying here (0: none). A character entering this world
        with a save from elsewhere starts from it, so queued adjustments after it are delivered once (character_transfer)."""
        row = self._db.execute("SELECT seq FROM wallet_base WHERE player_id=?", (player,)).fetchone()
        return row[0] if row else 0

    def next_adjustment(self, player: str, save_seq_low: int | None) -> dict | None:
        """The adjustment this player's game should apply next (or None)."""
        if save_seq_low is None:
            return None
        applied = self._full_seq(player, save_seq_low)
        row = self._db.execute("SELECT seq, delta FROM wallet WHERE player_id=? AND seq=?",
                               (player, applied + 1)).fetchone()
        return None if row is None else {"seq": row[0], "delta": row[1]}

    def applied(self, player: str, seq: int, amount: int) -> list[tuple[str, int, str]]:
        """A game applied adjustment ``seq`` moving ``amount``; returns credits queued."""
        if type(seq) is not int or not 1 <= seq <= 0xFFFF or type(amount) is not int or not 0 <= amount <= MAX_MONEY:
            return []
        row = self._db.execute("SELECT delta, battle_id, credit_to, applied FROM wallet WHERE player_id=? AND seq=?",
                               (player, seq)).fetchone()
        credits = []
        with self._transaction():
            self._db.execute("""INSERT INTO wallet_base VALUES (?, ?)
                ON CONFLICT(player_id) DO UPDATE SET seq=MAX(seq, excluded.seq)""", (player, seq))
            if row is None:
                return []  # a receipt this host never issued (restored backup): baseline only
            delta, battle_id, credit_to, previous = row
            self._db.execute("UPDATE wallet SET applied=? WHERE player_id=? AND seq=?", (amount, player, seq))
            if delta < 0 and credit_to is not None:
                # Credit exactly what the debit collected; a re-application of
                # a reloaded save that collected again only tops up the
                # difference, so a winner is never paid twice.
                already = self._db.execute(
                    "SELECT COALESCE(SUM(delta), 0) FROM wallet WHERE player_id=? AND battle_id=? AND delta > 0",
                    (credit_to, battle_id)).fetchone()[0]
                owed = min(amount, -delta) - already
                if owed > 0:
                    self._queue(credit_to, owed, battle_id)
                    credits.append((credit_to, owed, battle_id))
        return credits
