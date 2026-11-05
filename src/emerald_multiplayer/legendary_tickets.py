"""Legendary Tickets: the game's four event tickets, earned in play (docs/legendary-tickets.md).

The owner's decision of 2026-11-05 (docs/owner-decisions.md #11 and #40): the tickets of the personal static legendary
encounters come from postgame achievements, challenging quests and Battle Frontier milestones; Game Corner purchases are
never the only way. Of the Local Soft Reset catalogue's 25 encounters (reset_protocol.SOURCES) six need a ticket: the Eon
Ticket (Southern Island: Latios or Latias), the Mystic Ticket (Navel Rock: Lugia and Ho-Oh), the Aurora Ticket (Birth
Island: Deoxys) and the Old Sea Map (Faraway Island: Mew). In Emerald only Mystery Gift and record mixing gave them, and
neither exists on the PC. A ticket is the key item in the Bag *and* its island's ship flag: Lilycove's ferry and the
reset adapter (engine multiplayer_static_reset.c, TicketReady and the descriptor's prerequisite) check both.

This module is the host's half that needs no engine change:

* ``TICKETS``: which ticket opens which island and which reset descriptors; ``GAME_PROGRESSION``: how the game itself
  opens the other nineteen (no ticket, unchanged);
* the conditions, each read from the player's last host save (flags, the game's statistics, the Pokedex, variables, the
  Tower record: ``save_facts``) or from the host's own records (``with_host_records``);
* ``DEFAULT_SOURCES``: the owner's setting, one per ticket (any of its sources earns it); a world may override it with
  ``<world>.tickets.json`` (``load_sources``);
* ``TicketBook`` and ``reconcile``: the durable ledger that turns a met condition into exactly one grant per character.

Delivering a ticket needs the game's reward word kind 8 (docs/legendary-tickets.md section 6: the ticket into the Bag,
else the PC, and its island's ship flag, atomically, never a second copy; receipt 1 given, 2 already owned, 0 no room).
Until a game advertises it (manifest ticket_abi_version 1) nothing here is wired into the server and nothing is sent.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
import re
import struct
from typing import Callable, NamedTuple

# ---------------------------------------------------------------------------------------------------------------- save
# Pinned native layout (engine include/global.h; the offsets marked STATIC_ASSERT are asserted by the engine's
# src/multiplayer_trade_effects.c, so a moved field fails the build; the others are checked by the engine self-test the
# design adds, docs/legendary-tickets.md section 6.4).
SAVE_BLOCK_1_SIZE = 15568
SAVE_BLOCK_2_SIZE = 3884
FLAGS_OFFSET = 0x1270            # SaveBlock1.flags (STATIC_ASSERT)
VARS_OFFSET = 0x139C             # SaveBlock1.vars (right after the 300 flag bytes)
GAME_STATS_OFFSET = 0x159C       # SaveBlock1.gameStats (STATIC_ASSERT): u32 each, XOR SaveBlock2.encryptionKey
DEX_CAUGHT_OFFSET = 0x3619       # SaveBlock1.dexCaught (STATIC_ASSERT): bit n is National Dex number n + 1
DEX_BYTES = 129
ENCRYPTION_KEY_OFFSET = 0xAC     # SaveBlock2.encryptionKey (STATIC_ASSERT)
CARD_BATTLE_POINTS_OFFSET = 0xEBA   # SaveBlock2.frontier.cardBattlePoints: every BP the island's facilities ever paid
FLAG_BYTES = VARS_OFFSET - FLAGS_OFFSET

SYSTEM_FLAGS = 0x860
FLAG_SYS_GAME_CLEAR = SYSTEM_FLAGS + 0x04          # the Hall of Fame entered
FLAG_SYS_TOWER_SILVER = SYSTEM_FLAGS + 0x64        # each facility's Silver Symbol, its Gold right after it
FRONTIER_FACILITIES = ("Tower", "Dome", "Palace", "Arena", "Factory", "Pike", "Pyramid")
FLAG_DEFEATED_REGIROCK, FLAG_DEFEATED_REGICE, FLAG_DEFEATED_REGISTEEL = 0x1BB, 0x1BC, 0x1BD
FLAG_DEFEATED_KYOGRE, FLAG_DEFEATED_GROUDON, FLAG_DEFEATED_RAYQUAZA = 0x1BE, 0x1BF, 0x1C0
REGI_FLAGS = (FLAG_DEFEATED_REGIROCK, FLAG_DEFEATED_REGICE, FLAG_DEFEATED_REGISTEEL)
WEATHER_FLAGS = (FLAG_DEFEATED_KYOGRE, FLAG_DEFEATED_GROUDON, FLAG_DEFEATED_RAYQUAZA)
VAR_TRICK_HOUSE_LEVEL = 0x4044   # puzzles solved, 0-8
TRICK_HOUSE_PUZZLES = 8
GAME_STAT_ENTERED_HOF = 10       # include/constants/game_stat.h; the game counts up to 999
MAX_SPECIES_HERE = 721           # Generations 1-6: the species a player can own in this game

# ------------------------------------------------------------------------------------------------------------- tickets


class Ticket(NamedTuple):
    key: str
    index: int                   # the reward word's payload (docs/legendary-tickets.md 6.1)
    item: int                    # engine include/constants/items.h
    name: str
    ship_flag: int               # FLAG_ENABLE_SHIP_*: Lilycove's ferry sails there only with it
    received_flag: int | None    # FLAG_RECEIVED_* that Mystery Gift set beside the ticket (the Eon Ticket has none)
    island: str
    descriptors: tuple[int, ...]  # the Local Soft Reset descriptors it opens (reset_protocol.SOURCES)
    encounters: str


TICKETS = (
    Ticket("eon", 1, 728, "Eon Ticket", SYSTEM_FLAGS + 0x53, None, "Southern Island", (0x1018, 0x1019),
           "Latios or Latias, level 50 (the one that is not roaming)"),
    Ticket("mystic", 2, 729, "Mystic Ticket", SYSTEM_FLAGS + 0x80, 0x13B, "Navel Rock", (0x1014, 0x1015),
           "Lugia and Ho-Oh, level 70"),
    Ticket("aurora", 3, 730, "Aurora Ticket", SYSTEM_FLAGS + 0x75, 0x13A, "Birth Island", (0x1017,),
           "Deoxys, level 30 (the triangle puzzle)"),
    Ticket("old_sea_map", 4, 731, "Old Sea Map", SYSTEM_FLAGS + 0x76, 0x13C, "Faraway Island", (0x1016,),
           "Mew, level 30 (the chase in the grass)"),
)
TICKET_BY_KEY = {ticket.key: ticket for ticket in TICKETS}
TICKET_BY_INDEX = {ticket.index: ticket for ticket in TICKETS}

# The nineteen other reset descriptors need no ticket: the game's own progression opens them, unchanged.
GAME_PROGRESSION = {
    **dict.fromkeys((0x1001, 0x1002, 0x1003), "New Mauville, opened with Wattson's Basement Key (story)"),
    **dict.fromkeys((0x1004, 0x1005), "Team Aqua's Hideout (story)"),
    0x1006: "Ancient Tomb, after the Sealed Chamber's braille riddle and the tomb's own",
    0x1007: "Desert Ruins, after the Sealed Chamber's braille riddle and the ruins' own",
    0x1008: "Island Cave, after the Sealed Chamber's braille riddle and the cave's own",
    0x1009: "Sky Pillar's top, once Rayquaza has calmed Sootopolis (story)",
    0x100A: "Battle Frontier (the S.S. Ticket after the Hall of Fame), watered with the Wailmer Pail",
    0x100B: "Marine Cave, found through the Weather Institute's abnormal weather after the Hall of Fame",
    0x100C: "Terra Cave, found through the Weather Institute's abnormal weather after the Hall of Fame",
    **dict.fromkeys(range(0x100D, 0x1014), "Routes 119 and 120 with Steven's Devon Scope (story)"),
}


def ticket_for_descriptor(descriptor: int) -> Ticket | None:
    """The ticket a reset descriptor needs (None: the game's own progression opens it)."""
    return next((ticket for ticket in TICKETS if descriptor in ticket.descriptors), None)


class TicketError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


# --------------------------------------------------------------------------------------------------------------- facts
@dataclass(frozen=True)
class TicketFacts:
    """What the conditions read: the player's last host save, then the host's own records (``with_host_records``)."""
    hall_of_fame: int = 0          # Hall of Fame entries (the game's statistic; at least 1 once the game is clear)
    dex_caught: int = 0            # species caught (National Pokedex)
    regis: int = 0                 # Regirock, Regice and Registeel caught or defeated (each sets its FLAG_DEFEATED_*)
    weather: int = 0               # Kyogre, Groudon and Rayquaza caught or defeated
    rayquaza: int = 0
    trick_house: int = 0           # Trick House puzzles solved
    silver_symbols: int = 0        # the island Battle Frontier's facilities with their Silver Symbol (a Gold implies it)
    gold_symbols: int = 0
    frontier_bp: int = 0           # Battle Points the island's facilities ever paid (the Trainer Card's)
    tower_floor: int = 0           # Battle Tower: Legends' highest floor cleared (the save's record or the host's)
    coop_frontier_streak: int = 0  # the co-op Battle Frontier's best streak (host); 7 = the first Frontier Brain pair
    coop_league: int = 0           # co-op Pokemon League clears (host)
    championship_wins: int = 0     # Championships won, four or eight places (host)
    islands: frozenset = frozenset()   # tickets whose island the save already opens (its ship flag is set)


def _flag(block1: bytes, flag: int) -> bool:
    return bool(block1[FLAGS_OFFSET + flag // 8] >> (flag % 8) & 1)


def _var(block1: bytes, var: int) -> int:
    return struct.unpack_from("<H", block1, VARS_OFFSET + 2 * (var - 0x4000))[0]


def _game_stat(block1: bytes, block2: bytes, stat: int) -> int:
    key = struct.unpack_from("<I", block2, ENCRYPTION_KEY_OFFSET)[0]
    return struct.unpack_from("<I", block1, GAME_STATS_OFFSET + 4 * stat)[0] ^ key


def save_facts(save_block1: bytes, save_block2: bytes, tower=None) -> TicketFacts:
    """The facts of a saved game (flash.inspect_flash's blocks; ``tower``: its flash.TowerRecord or None)."""
    if len(save_block1) != SAVE_BLOCK_1_SIZE or len(save_block2) != SAVE_BLOCK_2_SIZE:
        raise TicketError("bad_save", "the save's blocks have another layout")
    hall_of_fame = min(_game_stat(save_block1, save_block2, GAME_STAT_ENTERED_HOF), 999)
    if _flag(save_block1, FLAG_SYS_GAME_CLEAR):
        hall_of_fame = max(hall_of_fame, 1)
    silver = sum(_flag(save_block1, FLAG_SYS_TOWER_SILVER + 2 * i) for i in range(len(FRONTIER_FACILITIES)))
    gold = sum(_flag(save_block1, FLAG_SYS_TOWER_SILVER + 2 * i + 1) for i in range(len(FRONTIER_FACILITIES)))
    dex = save_block1[DEX_CAUGHT_OFFSET:DEX_CAUGHT_OFFSET + DEX_BYTES]
    return TicketFacts(
        hall_of_fame=hall_of_fame,
        dex_caught=sum(bin(byte).count("1") for byte in dex),
        regis=sum(_flag(save_block1, flag) for flag in REGI_FLAGS),
        weather=sum(_flag(save_block1, flag) for flag in WEATHER_FLAGS),
        rayquaza=int(_flag(save_block1, FLAG_DEFEATED_RAYQUAZA)),
        trick_house=min(_var(save_block1, VAR_TRICK_HOUSE_LEVEL), TRICK_HOUSE_PUZZLES),
        silver_symbols=silver,
        gold_symbols=gold,
        frontier_bp=struct.unpack_from("<H", save_block2, CARD_BATTLE_POINTS_OFFSET)[0],
        tower_floor=0 if tower is None else tower.highest,
        islands=frozenset(ticket.key for ticket in TICKETS if _flag(save_block1, ticket.ship_flag)),
    )


def with_host_records(facts: TicketFacts, *, tower_best: int = 0, coop_frontier_streak: int = 0, coop_league: int = 0,
                      championship_wins: int = 0) -> TicketFacts:
    """The save's facts with the host's records of this world (the Tower's best floor never lowers the save's)."""
    return replace(facts, tower_floor=max(facts.tower_floor, tower_best), coop_frontier_streak=coop_frontier_streak,
                   coop_league=coop_league, championship_wins=championship_wins)


# ---------------------------------------------------------------------------------------------------------- conditions
POSTGAME, QUEST, FRONTIER = "postgame achievement", "challenging quest", "Battle Frontier milestone"


class Condition(NamedTuple):
    kind: str
    category: str
    where: str                   # "save": the player's last host save; "host": the host's records; "save+host": either
    solo: bool                   # one player can meet it alone
    bounds: tuple[int, int] | None   # the amount N of "kind:N"; None: the condition takes no amount
    label: str                   # what the player is told ({n}: the amount)
    have: Callable[[TicketFacts], int]
    need: int | None = None      # what ``have`` must reach when the condition takes no amount


CONDITIONS = {condition.kind: condition for condition in (
    Condition("hall_of_fame", POSTGAME, "save", True, (1, 999),
              "Enter the Hall of Fame {n} time(s)", lambda f: f.hall_of_fame),
    Condition("pokedex", POSTGAME, "save", True, (1, MAX_SPECIES_HERE),
              "Catch {n} kinds of Pokemon (National Pokedex)", lambda f: f.dex_caught),
    Condition("coop_league", POSTGAME, "host", False, (1, 999),
              "Clear the co-op Pokemon League {n} time(s)", lambda f: f.coop_league),
    Condition("regi_trio", QUEST, "save", True, None,
              "Solve the Sealed Chamber: catch or defeat Regirock, Regice and Registeel", lambda f: f.regis, 3),
    Condition("weather_trio", QUEST, "save", True, None,
              "Catch or defeat Kyogre, Groudon and Rayquaza", lambda f: f.weather, 3),
    Condition("rayquaza", QUEST, "save", True, None,
              "Catch or defeat Rayquaza at the top of Sky Pillar", lambda f: f.rayquaza, 1),
    Condition("trick_house", QUEST, "save", True, None,
              "Solve all eight Trick House puzzles", lambda f: f.trick_house, TRICK_HOUSE_PUZZLES),
    Condition("championship_wins", QUEST, "host", False, (1, 999),
              "Win {n} Championship(s)", lambda f: f.championship_wins),
    Condition("silver_symbols", FRONTIER, "save", True, (1, len(FRONTIER_FACILITIES)),
              "Earn {n} of the Battle Frontier's Silver Symbols", lambda f: f.silver_symbols),
    Condition("gold_symbols", FRONTIER, "save", True, (1, len(FRONTIER_FACILITIES)),
              "Earn {n} of the Battle Frontier's Gold Symbols", lambda f: f.gold_symbols),
    Condition("frontier_bp", FRONTIER, "save", True, (1, 0xFFFF),
              "Earn {n} Battle Points in the Battle Frontier's facilities", lambda f: f.frontier_bp),
    Condition("tower_floor", FRONTIER, "save+host", True, (1, 100),
              "Clear floor {n} of Battle Tower: Legends", lambda f: f.tower_floor),
    Condition("coop_frontier_streak", FRONTIER, "host", False, (1, 999),
              "Win {n} rounds in a row in the co-op Battle Frontier", lambda f: f.coop_frontier_streak),
)}


class Source(NamedTuple):
    """One way to earn a ticket: a condition and its amount (None for a condition that takes none)."""
    kind: str
    amount: int | None

    @property
    def condition(self) -> Condition:
        return CONDITIONS[self.kind]

    @property
    def text(self) -> str:
        return self.kind if self.amount is None else f"{self.kind}:{self.amount}"

    @property
    def label(self) -> str:
        return self.condition.label.format(n=self.amount)

    def progress(self, facts: TicketFacts) -> tuple[int, int]:
        """(have, need): the condition is met once have reaches need."""
        condition = self.condition
        need = condition.need if self.amount is None else self.amount
        return min(condition.have(facts), need), need

    def met(self, facts: TicketFacts) -> bool:
        have, need = self.progress(facts)
        return have >= need


def parse_source(text) -> Source:
    """``kind`` or ``kind:N`` of CONDITIONS; TicketError for anything else."""
    if type(text) is not str or not 1 <= len(text) <= 64:
        raise TicketError("invalid_source", "a ticket source is a condition name")
    kind, colon, amount = text.partition(":")
    condition = CONDITIONS.get(kind)
    if condition is None:
        raise TicketError("invalid_source", f"unknown ticket condition {kind!r}")
    if condition.bounds is None:
        if colon:
            raise TicketError("invalid_source", f"{kind} takes no amount")
        return Source(kind, None)
    low, high = condition.bounds
    if not colon or re.fullmatch(r"[1-9][0-9]{0,5}", amount) is None or not low <= int(amount) <= high:
        raise TicketError("invalid_source", f"{kind} needs an amount from {low} to {high} ({kind}:N)")
    return Source(kind, int(amount))


# ----------------------------------------------------------------------------------------------------------- settings
# THE OWNER'S SETTING: one line per ticket; any of a ticket's sources earns it (docs/legendary-tickets.md section 3).
DEFAULT_SOURCES = {
    "eon": ("hall_of_fame:2",),                          # postgame: the Elite Four and the Champion beaten again
    "old_sea_map": ("regi_trio",),                       # quest: the Sealed Chamber's riddle and its three legends
    "aurora": ("weather_trio",),                         # quest: Kyogre, Groudon and Rayquaza
    "mystic": ("silver_symbols:7", "tower_floor:75"),    # Frontier: the island's seven Brains, or the world's Tower
}
MAX_SOURCES = 4
# No ticket is sold at the Game Corner (none ever was: tools/mp/gen_rare_goods.py keeps tickets out). A casino price would
# be a second way at most, and its price is the owner's to set (docs/legendary-tickets.md, decision D3).
CASINO_PRICES: dict[str, int] = {}


def validate_sources(mapping) -> dict[str, tuple[Source, ...]]:
    """Every ticket's sources, checked: each ticket at least one source and at most MAX_SOURCES, all of them known."""
    if not isinstance(mapping, dict) or set(mapping) != set(TICKET_BY_KEY):
        raise TicketError("invalid_settings", "the ticket sources name exactly: " + ", ".join(TICKET_BY_KEY))
    checked = {}
    for key, texts in mapping.items():
        if not isinstance(texts, (list, tuple)) or not 1 <= len(texts) <= MAX_SOURCES:
            raise TicketError("invalid_settings", f"the {key} ticket needs 1 to {MAX_SOURCES} sources")
        sources = tuple(parse_source(text) for text in texts)
        if len(set(sources)) != len(sources):
            raise TicketError("invalid_settings", f"the {key} ticket names a source twice")
        checked[key] = sources
    return checked


def load_sources(path) -> dict[str, tuple[Source, ...]]:
    """The world's ticket sources: DEFAULT_SOURCES, with a ticket's line replaced by ``<world>.tickets.json``
    ({"sources": {"eon": ["hall_of_fame:1"]}}) when that file exists. A file that cannot be used refuses (TicketError):
    the host does not start with half a setting."""
    mapping = {key: list(texts) for key, texts in DEFAULT_SOURCES.items()}
    path = Path(path)
    if path.exists():
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as error:
            raise TicketError("invalid_settings", f"{path.name} cannot be read") from error
        if not isinstance(value, dict) or set(value) != {"sources"} or not isinstance(value["sources"], dict):
            raise TicketError("invalid_settings", f'{path.name} holds one object: {{"sources": {{...}}}}')
        unknown = set(value["sources"]) - set(TICKET_BY_KEY)
        if unknown:
            raise TicketError("invalid_settings", f"{path.name} names unknown tickets: {', '.join(sorted(unknown))}")
        mapping.update(value["sources"])
    return validate_sources(mapping)


def earned_by(sources: dict[str, tuple[Source, ...]], facts: TicketFacts) -> dict[str, Source]:
    """For every ticket one of whose sources the facts meet: the first such source, in the setting's order."""
    earned = {}
    for key, choices in sources.items():
        met = next((source for source in choices if source.met(facts)), None)
        if met is not None:
            earned[key] = met
    return earned


# -------------------------------------------------------------------------------------------------------------- ledger
SCHEMA = (
    # One row per (player, ticket) from the moment a source is met: earned -> sent (a reward word with ``ref`` is on the
    # player's wallet stream) -> delivered (receipt 1 given, 2 already owned; or the save shows the island open), or
    # owed (receipt 0: neither the Bag nor the PC had room; offered again with the next attempt once the player has
    # saved since, owed_revision). A delivered ticket is never sent again, whatever later saves or settings say.
    """CREATE TABLE IF NOT EXISTS legendary_tickets (
        player_id TEXT NOT NULL, ticket TEXT NOT NULL, state TEXT NOT NULL, source TEXT NOT NULL,
        attempt INTEGER NOT NULL, ref TEXT, receipt INTEGER, owed_revision INTEGER, earned REAL NOT NULL,
        updated REAL NOT NULL, PRIMARY KEY (player_id, ticket))""",
)
STATES = ("earned", "sent", "delivered", "owed")
RECEIPT_GIVEN, RECEIPT_OWNED, RECEIPT_NO_ROOM = 1, 2, 0


def ticket_ref(key: str, attempt: int) -> str:
    """The wallet reference of a ticket's attempt: the wallet queues one word per (player, reference)."""
    return f"ticket:{key}:{attempt}"


class TicketBook:
    """Event-loop owned; every mutation commits before returning (the FrontierBook / TowerBook pattern)."""

    _COLUMNS = ("player_id", "ticket", "state", "source", "attempt", "ref", "receipt", "owed_revision", "earned",
                "updated")

    def __init__(self, db, transaction, clock: Callable[[], float]):
        self._db, self._transaction, self._now = db, transaction, clock

    def row(self, player: str, ticket: str) -> dict | None:
        found = self._db.execute(f"SELECT {', '.join(self._COLUMNS)} FROM legendary_tickets WHERE player_id=? "
                                 "AND ticket=?", (player, ticket)).fetchone()
        return None if found is None else dict(zip(self._COLUMNS, found))

    def rows(self, player: str) -> list[dict]:
        found = self._db.execute(f"SELECT {', '.join(self._COLUMNS)} FROM legendary_tickets WHERE player_id=? "
                                 "ORDER BY ticket", (player,)).fetchall()
        return [dict(zip(self._COLUMNS, row)) for row in found]

    def earn(self, player: str, ticket: str, source: str) -> bool:
        """Record that the player met ``source`` for the ticket (the first record stands). True when new."""
        if ticket not in TICKET_BY_KEY:
            raise TicketError("unknown_ticket", f"no ticket {ticket!r}")
        now = self._now()
        with self._transaction():
            cursor = self._db.execute("INSERT OR IGNORE INTO legendary_tickets VALUES (?, ?, 'earned', ?, 0, NULL, NULL, "
                                      "NULL, ?, ?)", (player, ticket, source, now, now))
        return cursor.rowcount == 1

    def send(self, player: str, ticket: str) -> str:
        """The next attempt of an earned or owed ticket: its reference, recorded before the word is queued (queueing is
        idempotent per reference, so a crash in between only queues it on the next pass)."""
        current = self.row(player, ticket)
        if current is None or current["state"] not in ("earned", "owed"):
            raise TicketError("not_owed", "only an earned or owed ticket is sent")
        attempt = current["attempt"] + 1
        ref = ticket_ref(ticket, attempt)
        with self._transaction():
            self._db.execute("UPDATE legendary_tickets SET state='sent', attempt=?, ref=?, receipt=NULL, updated=? "
                             "WHERE player_id=? AND ticket=? AND state IN ('earned', 'owed')",
                             (attempt, ref, self._now(), player, ticket))
        return ref

    def settle(self, player: str, ticket: str, ref: str, receipt: int, revision: int | None) -> str | None:
        """The game's receipt for the word ``ref``: 1 given / 2 already owned -> delivered, 0 -> owed (offered again after
        a save newer than ``revision``). A receipt for another attempt, or for a settled one, changes nothing.
        Returns the new state, or None when nothing changed."""
        current = self.row(player, ticket)
        if current is None or current["state"] != "sent" or current["ref"] != ref:
            return None
        if receipt in (RECEIPT_GIVEN, RECEIPT_OWNED):
            state = "delivered"
        elif receipt == RECEIPT_NO_ROOM:
            state = "owed"
        else:
            raise TicketError("invalid_receipt", "a ticket receipt is 0, 1 or 2")
        with self._transaction():
            self._db.execute("UPDATE legendary_tickets SET state=?, receipt=?, owed_revision=?, updated=? "
                             "WHERE player_id=? AND ticket=? AND state='sent' AND ref=?",
                             (state, receipt, revision if state == "owed" else None, self._now(), player, ticket, ref))
        return state

    def seen(self, player: str, ticket: str) -> bool:
        """The player's save shows the ticket's island open (from this world's word, another world's, or Mystery Gift):
        an earned or owed ticket is delivered without another word. True when it changed."""
        with self._transaction():
            cursor = self._db.execute("UPDATE legendary_tickets SET state='delivered', updated=? WHERE player_id=? "
                                      "AND ticket=? AND state IN ('earned', 'owed')", (self._now(), player, ticket))
        return cursor.rowcount == 1


def reconcile(book: TicketBook, player: str, *, sources: dict[str, tuple[Source, ...]], facts: TicketFacts | None,
              revision: int | None, grant: Callable[[str, Ticket, str], object],
              receipt: Callable[[str, str], int | None]) -> list[Ticket]:
    """One player's tickets, safe to run at any time and any number of times (after a restart or a reconnect too).

    ``facts``: the player's last host save and the host's records (None while no save can be read: receipts are still
    settled, nothing new is earned). ``revision``: that save's checkpoint revision. ``grant(player, ticket, ref)`` queues
    the ticket's reward word once per (player, ref) (Wagers.grant_reward is idempotent per reference). ``receipt(player,
    ref)`` is what the game reported moving for that word (None until it reports). Returns the tickets given just now
    (receipt 1), for the in-game notice."""
    given = []
    for row in book.rows(player):
        if row["state"] == "sent":
            reported = receipt(player, row["ref"])
            if reported is not None and book.settle(player, row["ticket"], row["ref"], reported, revision) == "delivered" \
                    and reported == RECEIPT_GIVEN:
                given.append(TICKET_BY_KEY[row["ticket"]])
    if facts is not None:
        for key, source in earned_by(sources, facts).items():
            if key not in facts.islands:
                book.earn(player, key, source.text)
        for key in facts.islands:
            book.seen(player, key)
    for row in book.rows(player):
        ticket = TICKET_BY_KEY[row["ticket"]]
        # An owed ticket goes again once the player has saved since it was refused (a refusal settled while no save
        # could be read waits for the next one that can, so it is never stuck).
        if row["state"] == "earned" or (row["state"] == "owed" and revision is not None
                                        and (row["owed_revision"] is None or revision > row["owed_revision"])):
            grant(player, ticket, book.send(player, row["ticket"]))
        elif row["state"] == "sent":
            grant(player, ticket, row["ref"])     # idempotent: completes a queueing a crash interrupted
    return given


def notice(ticket: Ticket) -> tuple[str, str]:
    """The in-game banner's two lines (at most 32 characters each) for a ticket just given."""
    return f"{ticket.name.upper()}!", "Show it at LILYCOVE's port."
