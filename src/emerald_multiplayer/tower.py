"""Battle Tower: Legends' durable book (docs/battle-tower-legends.md section 9): the host's Tower ledger, in the world's
shared SQLite file (``<world>.shared-world.sqlite3``, beside the co-op Battle Frontier's tables). The host is the authority
for every player's progress; a save's Tower record is its mirror (flash.TowerRecord). Every mutation commits before
returning, and a battle's settlement, its player rows, its Duo session and every wallet word it pays change together in
one transaction, so a result is settled once and its prizes exist exactly once.

Tables (CREATE TABLE IF NOT EXISTS):

  tower_players     one row per player who ever used the Tower in this world: progress floor P (1..101), highest cleared
                    floor H (0..100), claims (reward kind 6 op 1's bits), the save record's revision last seen (from an
                    import, or from a Tower word's receipt: the record's revision after applying it), the highest floor ever
                    cleared here (``best``: a floor at or below it is never a first clear again, whatever an import did to
                    H), the records (best solo floor, best Duo floor, wins, losses (draws and forfeits included), battles,
                    completions (floor 100 won)) and the trainer's name at their last Tower action (the records page).
  tower_tickets     one row per Tower battle issued: its ticket number (the u32 the game sees: random, low byte nonzero,
                    unique in the world), solo or Duo (the Duo session and its native battle), the floor, whether it is the
                    player's progression, its state (issued -> started -> won / lost / drew, or void: never started (refused,
                    expired, a Duo battle abandoned) or forfeit: started and never settled, a loss), its times, and the
                    settlement (P and H before and after, what was earned). A Duo battle has one ticket per player.
  tower_words       every wallet word the Tower sends, in order: written as ``planned`` in the transaction that decides it,
                    ``queued`` once it is on the player's wallet stream (wagers.py, once per (player, reference)), with the
                    game's receipt (``applied``). A settled battle plans its Tower state (PROGRESS) first, then money, items,
                    Battle Points, the claims and the milestone Pokemon. Kind 0 is money (payload = the amount).
  tower_duos        a Duo session of a host-formed team: invited -> forming (both agreed; each marks ready, the floor may
                    change) -> battle (its co-op battle issued) -> forming again after the battle (on to the next floor), or
                    ended (declined, cancelled, left, the team changed).
  tower_milestones  a milestone Pokemon (floors 25, 50, 75, 100) owed to a player: waiting (no species is legal at their
                    level yet) or chosen (species and level recorded before anything is sent), then sent, delivered, or owed
                    again (the game had no room: the player sends it again).
  tower_purchases   the Tower Shop: debit -> granting -> done (or refused / refunded), one open purchase per player.

Import rule: a player's first Tower action in the world creates their row from their save's Tower record (no record: floor
1, nothing claimed); after that, a save record whose revision is newer than the ledger's last seen (beyond the Tower words
still travelling to the game) is imported again: P and H as the save has them, the claims OR-ed. Never while the player has
a Tower battle open.
"""
from __future__ import annotations

import json
import secrets
import time
from typing import Callable

from . import rewards, tower_rewards
from .tower_rules import CLIMBED, FLOORS, after, can_fight, default_duo_floor, is_progression, win_reward

MONEY = 0                       # tower_words.kind of a money word (payload = the amount)
SOLO, DUO = "solo", "duo"
OPEN = ("issued", "started")
SETTLED = ("won", "lost", "drew", "forfeit")

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS tower_players (
        player_id TEXT PRIMARY KEY, name TEXT NOT NULL, progress INTEGER NOT NULL, highest INTEGER NOT NULL,
        claims INTEGER NOT NULL, revision INTEGER NOT NULL, best INTEGER NOT NULL, best_solo INTEGER NOT NULL,
        best_duo INTEGER NOT NULL, wins INTEGER NOT NULL, losses INTEGER NOT NULL, battles INTEGER NOT NULL,
        completions INTEGER NOT NULL, imported REAL, updated REAL NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS tower_tickets (
        ticket_id TEXT PRIMARY KEY, number INTEGER NOT NULL UNIQUE, player_id TEXT NOT NULL, mode TEXT NOT NULL,
        duo_id TEXT, battle_id TEXT, floor INTEGER NOT NULL, progression INTEGER NOT NULL, state TEXT NOT NULL,
        reason TEXT, created REAL NOT NULL, started REAL, settled REAL, result TEXT)""",
    "CREATE INDEX IF NOT EXISTS tower_tickets_player ON tower_tickets (player_id, state)",
    """CREATE TABLE IF NOT EXISTS tower_words (
        player_id TEXT NOT NULL, ref TEXT NOT NULL, ticket_id TEXT, position INTEGER NOT NULL, kind INTEGER NOT NULL,
        payload INTEGER NOT NULL, state TEXT NOT NULL, applied INTEGER, created REAL NOT NULL,
        PRIMARY KEY (player_id, ref))""",
    """CREATE TABLE IF NOT EXISTS tower_duos (
        duo_id TEXT PRIMARY KEY, players TEXT NOT NULL, floor INTEGER NOT NULL, state TEXT NOT NULL,
        consent TEXT NOT NULL, ready TEXT NOT NULL, battle_id TEXT, reason TEXT, created REAL NOT NULL,
        updated REAL NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS tower_milestones (
        player_id TEXT NOT NULL, milestone INTEGER NOT NULL, floor INTEGER NOT NULL, species INTEGER, name TEXT,
        level INTEGER, state TEXT NOT NULL, attempts INTEGER NOT NULL, ticket_id TEXT, chosen REAL, delivered REAL,
        PRIMARY KEY (player_id, milestone))""",
    """CREATE TABLE IF NOT EXISTS tower_purchases (
        purchase_id TEXT PRIMARY KEY, player_id TEXT NOT NULL, item INTEGER NOT NULL, quantity INTEGER NOT NULL,
        price INTEGER NOT NULL, state TEXT NOT NULL, created REAL NOT NULL)""",
)


class TowerError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


class TowerBook:
    """Event-loop owned; every mutation commits before returning."""

    def __init__(self, db, transaction, clock: Callable[[], float] = time.time):
        self._db, self._transaction, self._now = db, transaction, clock

    # ------------------------------------------------------------------ players
    _PLAYER = ("SELECT player_id, name, progress, highest, claims, revision, best, best_solo, best_duo, wins, losses, "
               "battles, completions, imported, updated FROM tower_players")

    @staticmethod
    def _player(row) -> dict:
        keys = ("player_id", "name", "progress", "highest", "claims", "revision", "best", "best_solo", "best_duo", "wins",
                "losses", "battles", "completions", "imported", "updated")
        return dict(zip(keys, row))

    def player(self, player: str) -> dict | None:
        row = self._db.execute(self._PLAYER + " WHERE player_id=?", (player,)).fetchone()
        return None if row is None else self._player(row)

    def ranking(self, limit: int = 5) -> list[dict]:
        """The world's Tower records, best first: highest floor cleared solo, then completions, wins and the best Duo."""
        rows = self._db.execute(self._PLAYER + " WHERE battles > 0 ORDER BY best_solo DESC, completions DESC, wins DESC, "
                                "best_duo DESC, player_id LIMIT ?", (limit,)).fetchall()
        return [self._player(row) for row in rows]

    def sync(self, player: str, name: str, record, *, outstanding: int) -> tuple[dict, bool]:
        """Bring the player's row up to date with their save's Tower record (flash.TowerRecord, None: no record). Returns
        (row, imported). ``outstanding``: Tower words already on the player's wallet stream whose receipt is not in yet
        (each may have raised the save's revision by one)."""
        progress, highest, claims, revision = ((record.progress, record.highest, record.claims, record.revision)
                                               if record is not None else (1, 0, 0, 0))
        current = self.player(player)
        now = self._now()
        if current is None:
            with self._transaction():
                self._db.execute("INSERT INTO tower_players VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, 0, 0, ?, ?)",
                                 (player, name, progress, highest, claims, revision, highest, now, now))
            return self.player(player), True
        if self.open_ticket(player) is None and revision > current["revision"] + outstanding:
            merged = current["claims"] | claims
            with self._transaction():
                self._db.execute("UPDATE tower_players SET progress=?, highest=?, claims=?, revision=?, best=?, name=?, "
                                 "imported=?, updated=? WHERE player_id=?",
                                 (progress, highest, merged, revision, max(current["best"], highest), name, now, now, player))
                for milestone in range(len(tower_rewards.MILESTONE_FLOORS)):
                    if merged & tower_rewards.delivered_bit(milestone):   # the save says it made that Pokemon
                        self._db.execute("UPDATE tower_milestones SET state='delivered', delivered=? WHERE player_id=? "
                                         "AND milestone=? AND state IN ('sent', 'owed')", (now, player, milestone))
            return self.player(player), True
        if name != current["name"]:
            with self._transaction():
                self._db.execute("UPDATE tower_players SET name=? WHERE player_id=?", (name, player))
            current = self.player(player)
        return current, False

    # ------------------------------------------------------------------ tickets
    _TICKET = ("SELECT ticket_id, number, player_id, mode, duo_id, battle_id, floor, progression, state, reason, created, "
               "started, settled, result FROM tower_tickets")

    @staticmethod
    def _ticket(row) -> dict:
        keys = ("ticket_id", "number", "player_id", "mode", "duo_id", "battle_id", "floor", "progression", "state", "reason",
                "created", "started", "settled", "result")
        ticket = dict(zip(keys, row))
        ticket["progression"] = bool(ticket["progression"])
        ticket["result"] = json.loads(ticket["result"]) if ticket["result"] else None
        return ticket

    def ticket(self, ticket_id: str) -> dict | None:
        row = self._db.execute(self._TICKET + " WHERE ticket_id=?", (ticket_id,)).fetchone()
        return None if row is None else self._ticket(row)

    def ticket_by_number(self, number: int) -> dict | None:
        row = self._db.execute(self._TICKET + " WHERE number=?", (number,)).fetchone()
        return None if row is None else self._ticket(row)

    def open_ticket(self, player: str) -> dict | None:
        """The player's Tower battle that is issued or running (at most one)."""
        row = self._db.execute(self._TICKET + " WHERE player_id=? AND state IN ('issued', 'started') ORDER BY created",
                               (player,)).fetchone()
        return None if row is None else self._ticket(row)

    def open_tickets(self, mode: str | None = None) -> list[dict]:
        query = self._TICKET + " WHERE state IN ('issued', 'started')" + (" AND mode=?" if mode else "") + " ORDER BY created"
        return [self._ticket(row) for row in self._db.execute(query, (mode,) if mode else ()).fetchall()]

    def tickets_of_battle(self, battle_id: str) -> list[dict]:
        rows = self._db.execute(self._TICKET + " WHERE battle_id=? ORDER BY player_id", (battle_id,)).fetchall()
        return [self._ticket(row) for row in rows]

    def last_ticket(self, player: str) -> dict | None:
        row = self._db.execute(self._TICKET + " WHERE player_id=? ORDER BY created DESC LIMIT 1", (player,)).fetchone()
        return None if row is None else self._ticket(row)

    def _number(self) -> int:
        """A fresh ticket number: random (a host database restored or replaced never reuses one a save still holds),
        never with a zero low byte (the game's PROGRESS word names a ticket by its low byte)."""
        while True:
            number = secrets.randbits(32)
            if number & 0xFF and self.ticket_by_number(number) is None:
                return number

    def issue_solo(self, player: str, floor: int) -> dict:
        """Record a solo battle *before* its command is sent: the player's progression floor or a replay."""
        current = self.player(player)
        if current is None:
            raise TowerError("no_record", "Open the Tower page first")
        if self.open_ticket(player) is not None:
            raise TowerError("tower_busy", "Finish your Tower battle first")
        if not can_fight(current["progress"], current["highest"], floor):
            raise TowerError("tower_floor_locked", f"Floor {floor} is not open yet")
        ticket_id, number, now = secrets.token_hex(16), self._number(), self._now()
        with self._transaction():
            self._db.execute("INSERT INTO tower_tickets VALUES (?, ?, ?, 'solo', NULL, NULL, ?, ?, 'issued', NULL, ?, "
                             "NULL, NULL, NULL)",
                             (ticket_id, number, player, floor, int(is_progression(current["progress"], floor)), now))
        return self.ticket(ticket_id)

    def start(self, ticket_id: str) -> dict | None:
        """The game began the battle: issued -> started (anything else changes nothing)."""
        with self._transaction():
            self._db.execute("UPDATE tower_tickets SET state='started', started=? WHERE ticket_id=? AND state='issued'",
                             (self._now(), ticket_id))
        return self.ticket(ticket_id)

    def void(self, ticket_id: str, reason: str) -> dict | None:
        """The battle never started (refused, expired, a Duo battle abandoned): nothing changes, nothing is paid. A
        voided ticket can never be settled later."""
        ticket = self.ticket(ticket_id)
        if ticket is None or ticket["state"] not in OPEN:
            return ticket
        with self._transaction():
            self._void(ticket, reason)
        return self.ticket(ticket_id)

    def _void(self, ticket: dict, reason: str) -> None:
        self._db.execute("UPDATE tower_tickets SET state='void', reason=?, settled=? WHERE ticket_id=? AND state IN "
                         "('issued', 'started')", (reason, self._now(), ticket["ticket_id"]))
        if ticket["duo_id"] is not None:
            self._duo_back_to_forming(ticket["duo_id"], None)

    def settle(self, ticket_id: str, outcome: str, *, choose=None, forfeit: bool = False) -> dict | None:
        """Apply a battle's result once: "won", "lost" or "drew" (``forfeit``: a started battle that never reported, a
        loss). Returns the settled ticket, or None when it was unknown or no longer open (a repeated or contradicting
        result changes nothing). ``choose(player, milestone, floor)`` picks a milestone Pokemon's (species, name, level),
        or None while none can be made; it is recorded here, before anything is sent."""
        ticket = self.ticket(ticket_id)
        if ticket is None or ticket["state"] not in OPEN or outcome not in ("won", "lost", "drew"):
            return None
        with self._transaction():
            self._settle(ticket, outcome, choose, forfeit)
            if ticket["duo_id"] is not None:
                self._settle_partners(ticket, outcome, choose)
        return self.ticket(ticket_id)

    def _settle_partners(self, ticket: dict, outcome: str, choose) -> None:
        """A Duo battle settles every player's ticket on the agreed result, then the session goes on to the next floor."""
        for other in self.tickets_of_battle(ticket["battle_id"]):
            if other["ticket_id"] != ticket["ticket_id"] and other["state"] in OPEN:
                self._settle(other, outcome, choose, False)
        duo = self.duo(ticket["duo_id"])
        if duo is not None:
            rows = [self.player(p) for p in duo["players"]]
            self._duo_back_to_forming(duo["duo_id"], default_duo_floor(*(row["progress"] for row in rows)))

    def _settle(self, ticket: dict, outcome: str, choose, forfeit: bool) -> None:
        row = self.player(ticket["player_id"])
        floor, now = ticket["floor"], self._now()
        before = (row["progress"], row["highest"])
        consistent = can_fight(*before, floor)
        progress, highest = after(*before, floor, outcome) if consistent else before
        won = outcome == "won" and consistent
        reward = win_reward(floor, row["highest"], row["best"], row["claims"]) if won else None
        claims = row["claims"] | (reward.claim if reward else 0)
        solo = ticket["mode"] == SOLO
        self._db.execute(
            "UPDATE tower_players SET progress=?, highest=?, claims=?, best=?, best_solo=?, best_duo=?, wins=wins+?, "
            "losses=losses+?, battles=battles+1, completions=completions+?, updated=? WHERE player_id=?",
            (progress, highest, claims, max(row["best"], floor if won else 0),
             max(row["best_solo"], floor if won and solo else 0), max(row["best_duo"], floor if won and not solo else 0),
             int(won), int(not won), int(won and floor == FLOORS), now, row["player_id"]))
        result = {"before": list(before), "after": [progress, highest], "progression": consistent and before[0] == floor,
                  "reward": None if reward is None else reward._asdict(), "consistent": consistent}
        self._db.execute("UPDATE tower_tickets SET state=?, settled=?, result=? WHERE ticket_id=?",
                         ("forfeit" if forfeit else outcome, now, json.dumps(result), ticket["ticket_id"]))
        # The words, in the contract's order: the Tower state first (always: it settles the save's result), then
        # money, items, Battle Points, the claims and the milestone Pokemon.
        player, base = row["player_id"], f"tower:{ticket['ticket_id']}"
        words = [("state", rewards.KIND_TOWER_STATE,
                  rewards.tower_progress(highest, progress, ticket["number"] & 0xFF if solo else 0))]
        if reward is not None:
            if reward.money:
                words.append(("money", MONEY, reward.money))
            words.extend(("item", rewards.KIND_ITEM, rewards.item_payload(item, quantity))
                         for item, quantity in reward.items)
            words.append(("bp", rewards.KIND_BP, reward.bp))
            if claims != row["claims"]:
                words.append(("claims", rewards.KIND_TOWER_STATE, rewards.tower_claims(claims)))
        for position, (name, kind, payload) in enumerate(words):
            self._plan(player, f"{base}:{position}:{name}", ticket["ticket_id"], position, kind, payload)
        if reward is not None and reward.milestone is not None:
            self._owe_milestone(player, reward.milestone, floor, ticket["ticket_id"], choose, len(words))

    # -------------------------------------------------------------- milestones
    _MILESTONE = ("SELECT player_id, milestone, floor, species, name, level, state, attempts, ticket_id, chosen, delivered "
                  "FROM tower_milestones")

    @staticmethod
    def _milestone(row) -> dict:
        keys = ("player_id", "milestone", "floor", "species", "name", "level", "state", "attempts", "ticket_id", "chosen",
                "delivered")
        return dict(zip(keys, row))

    def milestone(self, player: str, milestone: int) -> dict | None:
        row = self._db.execute(self._MILESTONE + " WHERE player_id=? AND milestone=?", (player, milestone)).fetchone()
        return None if row is None else self._milestone(row)

    def milestones_of(self, player: str) -> list[dict]:
        rows = self._db.execute(self._MILESTONE + " WHERE player_id=? ORDER BY milestone", (player,)).fetchall()
        return [self._milestone(row) for row in rows]

    def waiting_milestones(self) -> list[dict]:
        return [self._milestone(row) for row in self._db.execute(self._MILESTONE + " WHERE state='waiting'").fetchall()]

    def _owe_milestone(self, player, milestone, floor, ticket_id, choose, position) -> None:
        """Inside a settlement: the milestone Pokemon becomes owed; its species and level are chosen now when they can be."""
        self._db.execute("INSERT OR IGNORE INTO tower_milestones VALUES (?, ?, ?, NULL, NULL, NULL, 'waiting', 0, ?, NULL, "
                         "NULL)", (player, milestone, floor, ticket_id))
        choice = choose(player, milestone, floor) if choose is not None else None
        if choice is not None:
            self._choose(player, milestone, choice, f"tower:{ticket_id}:{position}:mon", ticket_id, position)

    def choose_milestone(self, player: str, milestone: int, choice) -> dict | None:
        """A waiting milestone gets its species and level (now that one is legal at the player's level): recorded, and
        its word planned, in one transaction."""
        current = self.milestone(player, milestone)
        if current is None or current["state"] != "waiting" or choice is None:
            return current
        with self._transaction():
            self._choose(player, milestone, choice, f"tower:mon:{milestone}:1", current["ticket_id"], 0)
        return self.milestone(player, milestone)

    def _choose(self, player, milestone, choice, ref, ticket_id, position) -> None:
        species, name, level = choice
        self._db.execute("UPDATE tower_milestones SET species=?, name=?, level=?, state='sent', attempts=1, chosen=? "
                         "WHERE player_id=? AND milestone=? AND state='waiting'",
                         (species, name, level, self._now(), player, milestone))
        self._plan(player, ref, ticket_id, position, rewards.KIND_TOWER_MON, rewards.tower_mon(milestone, species, level))

    def resend_milestone(self, player: str, milestone: int) -> dict:
        """'Send it now': an owed milestone Pokemon (the game had no room) is sent again, the same species and level."""
        current = self.milestone(player, milestone)
        if current is None or current["state"] != "owed":
            raise TowerError("nothing_owed", "Nothing is waiting to be sent")
        if self.player(player)["claims"] & tower_rewards.delivered_bit(milestone):
            raise TowerError("nothing_owed", "It is already in your game")
        attempt = current["attempts"] + 1
        with self._transaction():
            self._db.execute("UPDATE tower_milestones SET state='sent', attempts=? WHERE player_id=? AND milestone=? "
                             "AND state='owed'", (attempt, player, milestone))
            self._plan(player, f"tower:mon:{milestone}:{attempt}", current["ticket_id"], 0, rewards.KIND_TOWER_MON,
                       rewards.tower_mon(milestone, current["species"], current["level"]))
        return self.milestone(player, milestone)

    # ------------------------------------------------------------------- words
    _WORD = "SELECT player_id, ref, ticket_id, position, kind, payload, state, applied, created FROM tower_words"

    @staticmethod
    def _word(row) -> dict:
        return dict(zip(("player_id", "ref", "ticket_id", "position", "kind", "payload", "state", "applied", "created"),
                        row))

    def _plan(self, player, ref, ticket_id, position, kind, payload) -> None:
        self._db.execute("INSERT OR IGNORE INTO tower_words VALUES (?, ?, ?, ?, ?, ?, 'planned', NULL, ?)",
                         (player, ref, ticket_id, position, kind, payload, self._now()))

    def planned_words(self) -> list[dict]:
        """Words decided but not yet on a wallet stream, in the order they were decided."""
        return [self._word(row) for row in self._db.execute(self._WORD + " WHERE state='planned' ORDER BY rowid").fetchall()]

    def words_of(self, player: str, ticket_id: str | None = None) -> list[dict]:
        query = self._WORD + " WHERE player_id=?" + (" AND ticket_id=?" if ticket_id else "") + " ORDER BY rowid"
        return [self._word(row) for row in self._db.execute(query, (player, ticket_id) if ticket_id else (player,))]

    def unapplied_state_words(self, player: str) -> list[dict]:
        """The player's Tower state words (kind 6) whose receipt has not been recorded, planned or queued."""
        rows = self._db.execute(self._WORD + " WHERE player_id=? AND kind=? AND applied IS NULL ORDER BY rowid",
                                (player, rewards.KIND_TOWER_STATE)).fetchall()
        return [self._word(row) for row in rows]

    def words_in_flight(self) -> list[dict]:
        """Words on a wallet stream whose receipt has not been recorded."""
        rows = self._db.execute(self._WORD + " WHERE state='queued' AND applied IS NULL ORDER BY rowid").fetchall()
        return [self._word(row) for row in rows]

    def word_queued(self, player: str, ref: str) -> None:
        with self._transaction():
            self._db.execute("UPDATE tower_words SET state='queued' WHERE player_id=? AND ref=? AND state='planned'",
                             (player, ref))

    def word_receipt(self, player: str, ref: str, applied: int) -> dict | None:
        """Record what the game reported for a word, once: a Tower state word's receipt is the save record's revision
        after it; a milestone Pokemon's is 1 (made) or 2 (the save already had it: nothing made), both delivered, or 0
        (no room: owed again; the player sends it again later)."""
        row = self._db.execute(self._WORD + " WHERE player_id=? AND ref=?", (player, ref)).fetchone()
        if row is None or row[6] != "queued" or row[7] is not None:
            return None
        word = self._word(row)
        with self._transaction():
            self._db.execute("UPDATE tower_words SET applied=? WHERE player_id=? AND ref=?", (applied, player, ref))
            if word["kind"] == rewards.KIND_TOWER_STATE:
                self._db.execute("UPDATE tower_players SET revision=MAX(revision, ?) WHERE player_id=?", (applied, player))
            elif word["kind"] == rewards.KIND_TOWER_MON:
                milestone = word["payload"] >> 22
                if applied:
                    claims = self.player(player)["claims"] | tower_rewards.delivered_bit(milestone)
                    self._db.execute("UPDATE tower_milestones SET state='delivered', delivered=? WHERE player_id=? AND "
                                     "milestone=?", (self._now(), player, milestone))
                    self._db.execute("UPDATE tower_players SET claims=? WHERE player_id=?", (claims, player))
                    self._plan(player, f"{ref}:claims", word["ticket_id"], word["position"] + 1, rewards.KIND_TOWER_STATE,
                               rewards.tower_claims(claims))
                else:
                    self._db.execute("UPDATE tower_milestones SET state='owed' WHERE player_id=? AND milestone=? AND "
                                     "state='sent'", (player, milestone))
        return word

    def plan_clear(self, player: str, ref: str, number: int) -> bool:
        """A Tower state word that only settles the save's result for ``number`` (a ticket this host voided, or never
        issued: another world's, an older database's), carrying the ledger's P and H. Planned once per reference;
        nothing in the ledger changes. Returns whether it was planned now."""
        current = self.player(player)
        if current is None:
            return False
        with self._transaction():
            cursor = self._db.execute(
                "INSERT OR IGNORE INTO tower_words VALUES (?, ?, NULL, 0, ?, ?, 'planned', NULL, ?)",
                (player, ref, rewards.KIND_TOWER_STATE,
                 rewards.tower_progress(current["highest"], current["progress"], number & 0xFF), self._now()))
        return cursor.rowcount == 1

    # -------------------------------------------------------------------- Duo
    _DUO = "SELECT duo_id, players, floor, state, consent, ready, battle_id, reason, created, updated FROM tower_duos"

    @staticmethod
    def _duo(row) -> dict:
        return {"duo_id": row[0], "players": json.loads(row[1]), "floor": row[2], "state": row[3],
                "consent": json.loads(row[4]), "ready": json.loads(row[5]), "battle_id": row[6], "reason": row[7],
                "created": row[8], "updated": row[9]}

    def duo(self, duo_id: str) -> dict | None:
        row = self._db.execute(self._DUO + " WHERE duo_id=?", (duo_id,)).fetchone()
        return None if row is None else self._duo(row)

    def duo_of(self, player: str) -> dict | None:
        """The player's Duo session that has not ended, else their latest one."""
        latest = None
        for row in self._db.execute(self._DUO + " ORDER BY created DESC").fetchall():
            duo = self._duo(row)
            if player in duo["players"]:
                if duo["state"] != "ended":
                    return duo
                latest = latest or duo
        return latest

    def invite_duo(self, duo_id: str, proposer: str, partner: str, floor: int) -> dict:
        if proposer == partner:
            raise TowerError("no_teammate", "A Duo is two players")
        for player in (proposer, partner):
            current = self.duo_of(player)
            if current is not None and current["state"] != "ended":
                raise TowerError("duo_busy", "Leave your current Duo first")
        now = self._now()
        with self._transaction():
            self._db.execute("INSERT INTO tower_duos VALUES (?, ?, ?, 'invited', ?, '[]', NULL, NULL, ?, ?)",
                             (duo_id, json.dumps([proposer, partner]), floor, json.dumps([proposer]), now, now))
        return self.duo(duo_id)

    def accept_duo(self, duo_id: str, player: str) -> dict:
        duo = self.duo(duo_id)
        if duo is None or player not in duo["players"] or duo["state"] != "invited":
            raise TowerError("no_duo", "No Duo invitation to accept")
        with self._transaction():
            self._db.execute("UPDATE tower_duos SET state='forming', consent=?, updated=? WHERE duo_id=?",
                             (json.dumps(duo["players"]), self._now(), duo_id))
        return self.duo(duo_id)

    def end_duo(self, duo_id: str, reason: str) -> dict:
        duo = self.duo(duo_id)
        if duo is None:
            raise TowerError("no_duo", "There is no such Duo")
        if duo["state"] == "battle":
            raise TowerError("tower_busy", "Finish the Duo battle first")
        if duo["state"] != "ended":
            with self._transaction():
                self._db.execute("UPDATE tower_duos SET state='ended', reason=?, ready='[]', updated=? WHERE duo_id=?",
                                 (reason, self._now(), duo_id))
        return self.duo(duo_id)

    def set_duo_floor(self, duo_id: str, floor: int) -> dict:
        duo = self.duo(duo_id)
        if duo is None or duo["state"] not in ("invited", "forming"):
            raise TowerError("no_duo", "The floor is set: battle first")
        with self._transaction():   # a new floor needs both players' readiness again
            self._db.execute("UPDATE tower_duos SET floor=?, ready='[]', updated=? WHERE duo_id=?",
                             (floor, self._now(), duo_id))
        return self.duo(duo_id)

    def set_ready(self, duo_id: str, player: str, ready: bool) -> dict:
        duo = self.duo(duo_id)
        if duo is None or duo["state"] != "forming" or player not in duo["players"]:
            raise TowerError("no_duo", "Accept the Duo first")
        marked = sorted(set(duo["ready"]) | {player} if ready else set(duo["ready"]) - {player})
        with self._transaction():
            self._db.execute("UPDATE tower_duos SET ready=?, updated=? WHERE duo_id=?", (json.dumps(marked), self._now(),
                                                                                       duo_id))
        return self.duo(duo_id)

    def issue_duo(self, duo_id: str, battle_id: str) -> list[dict]:
        """Record the Duo battle *before* the host invites anybody: one ticket per player (progression where the floor is
        their P), the session in battle."""
        duo = self.duo(duo_id)
        if duo is None or duo["state"] != "forming":
            raise TowerError("no_duo", "The Duo is not ready")
        rows = [self.player(p) for p in duo["players"]]
        if any(row is None or not can_fight(row["progress"], row["highest"], duo["floor"]) for row in rows):
            raise TowerError("tower_floor_locked", f"Floor {duo['floor']}: not open to both")
        if any(self.open_ticket(p) is not None for p in duo["players"]):
            raise TowerError("tower_busy", "A Tower battle is still open")
        now = self._now()
        with self._transaction():
            for row in rows:
                self._db.execute("INSERT INTO tower_tickets VALUES (?, ?, ?, 'duo', ?, ?, ?, ?, 'issued', NULL, ?, NULL, "
                                 "NULL, NULL)",
                                 (secrets.token_hex(16), self._number(), row["player_id"], duo_id, battle_id, duo["floor"],
                                  int(is_progression(row["progress"], duo["floor"])), now))
            self._db.execute("UPDATE tower_duos SET state='battle', battle_id=?, updated=? WHERE duo_id=?",
                             (battle_id, now, duo_id))
        return self.tickets_of_battle(battle_id)

    def _duo_back_to_forming(self, duo_id: str, floor: int | None) -> None:
        """Inside a transaction: the Duo battle ended (or never started); both choose readiness again."""
        self._db.execute("UPDATE tower_duos SET state='forming', battle_id=NULL, ready='[]', floor=COALESCE(?, floor), "
                         "updated=? WHERE duo_id=? AND state='battle'", (floor, self._now(), duo_id))

    def void_battle(self, battle_id: str, reason: str) -> list[dict]:
        """A Duo battle that never started or was abandoned without a result: void for both, nothing changes."""
        tickets = [t for t in self.tickets_of_battle(battle_id) if t["state"] in OPEN]
        if tickets:
            with self._transaction():
                for ticket in tickets:
                    self._void(ticket, reason)
        return self.tickets_of_battle(battle_id)

    # ---------------------------------------------------------------- the shop
    _PURCHASE = "SELECT purchase_id, player_id, item, quantity, price, state, created FROM tower_purchases"

    @staticmethod
    def _purchase(row) -> dict:
        return dict(zip(("purchase_id", "player_id", "item", "quantity", "price", "state", "created"), row))

    def purchase(self, purchase_id: str) -> dict | None:
        row = self._db.execute(self._PURCHASE + " WHERE purchase_id=?", (purchase_id,)).fetchone()
        return None if row is None else self._purchase(row)

    def open_purchase(self, player: str) -> dict | None:
        row = self._db.execute(self._PURCHASE + " WHERE player_id=? AND state IN ('debit', 'granting') ORDER BY created "
                               "LIMIT 1", (player,)).fetchone()
        return None if row is None else self._purchase(row)

    def open_purchases(self) -> list[dict]:
        rows = self._db.execute(self._PURCHASE + " WHERE state IN ('debit', 'granting') ORDER BY created").fetchall()
        return [self._purchase(row) for row in rows]

    def last_purchase(self, player: str) -> dict | None:
        row = self._db.execute(self._PURCHASE + " WHERE player_id=? ORDER BY created DESC LIMIT 1", (player,)).fetchone()
        return None if row is None else self._purchase(row)

    def start_purchase(self, purchase_id: str, player: str, item: int, quantity: int, price: int) -> dict:
        if self.open_purchase(player) is not None:
            raise TowerError("purchase_open", "Your last order is not done")
        with self._transaction():
            self._db.execute("INSERT INTO tower_purchases VALUES (?, ?, ?, ?, ?, 'debit', ?)",
                             (purchase_id, player, item, quantity, price, self._now()))
        return self.purchase(purchase_id)

    def set_purchase(self, purchase_id: str, state: str) -> None:
        with self._transaction():
            self._db.execute("UPDATE tower_purchases SET state=? WHERE purchase_id=?", (state, purchase_id))


__all__ = ["CLIMBED", "DUO", "MONEY", "OPEN", "SCHEMA", "SETTLED", "SOLO", "TowerBook", "TowerError"]
