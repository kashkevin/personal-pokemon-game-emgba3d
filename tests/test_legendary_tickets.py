"""Legendary Tickets (docs/legendary-tickets.md): the catalogue against the 25 reset descriptors, the conditions read from
synthetic saves at the engine's pinned offsets, the owner's one-line-per-ticket setting, and the ledger that grants each
ticket once per character across receipts, full bags, restarts and saves from other worlds. No game, ROM or real save is
used; delivery itself (reward word kind 8) is the engine's half and is not exercised here."""
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import struct
import tempfile
from types import SimpleNamespace
import unittest

from emerald_multiplayer import legendary_tickets as lt
from emerald_multiplayer.flash import SAVE_BLOCK_1_SIZE, SAVE_BLOCK_2_SIZE, TOWER_RECORD_OFFSET, inspect_flash
from emerald_multiplayer.reset_protocol import SOURCES
import test_flash
import test_tower_contract

PLAYER, OTHER = "player-a", "player-b"


def blocks():
    return bytearray(SAVE_BLOCK_1_SIZE), bytearray(SAVE_BLOCK_2_SIZE)


def set_flag(block1, flag):
    block1[lt.FLAGS_OFFSET + flag // 8] |= 1 << (flag % 8)


def set_var(block1, var, value):
    struct.pack_into("<H", block1, lt.VARS_OFFSET + 2 * (var - 0x4000), value)


def set_hall_of_fame(block1, block2, entries, key=0x5A5AC3C3):
    struct.pack_into("<I", block2, lt.ENCRYPTION_KEY_OFFSET, key)
    struct.pack_into("<I", block1, lt.GAME_STATS_OFFSET + 4 * lt.GAME_STAT_ENTERED_HOF, entries ^ key)


def catch(block1, *species):
    for number in species:
        block1[lt.DEX_CAUGHT_OFFSET + (number - 1) // 8] |= 1 << ((number - 1) % 8)


@contextmanager
def _transaction_of(db):
    db.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        db.execute("ROLLBACK")
        raise
    else:
        db.execute("COMMIT")


def open_book(path, clock):
    db = sqlite3.connect(str(path), isolation_level=None)
    with _transaction_of(db):
        for statement in lt.SCHEMA:
            db.execute(statement)
    return db, lt.TicketBook(db, lambda: _transaction_of(db), clock)


class Wallet:
    """Wagers.grant_reward's contract: one word per (player, reference); the game's receipt arrives later."""

    def __init__(self):
        self.words, self.calls = {}, []

    def grant(self, player, ticket, ref):
        self.calls.append((player, ticket.key, ref))
        if (player, ref) in self.words:
            return None
        self.words[(player, ref)] = {"index": ticket.index, "applied": None}
        return len(self.words)

    def receipt(self, player, ref):
        word = self.words.get((player, ref))
        return None if word is None else word["applied"]

    def report(self, player, ref, amount):
        self.words[(player, ref)]["applied"] = amount

    def queued(self, player):
        return [ref for (owner, ref) in self.words if owner == player]


class CatalogueTests(unittest.TestCase):
    def test_every_reset_descriptor_is_either_a_ticket_encounter_or_the_games_own(self):
        tickets = {descriptor for ticket in lt.TICKETS for descriptor in ticket.descriptors}
        self.assertEqual(tickets, {0x1014, 0x1015, 0x1016, 0x1017, 0x1018, 0x1019})
        self.assertEqual(tickets | set(lt.GAME_PROGRESSION), set(SOURCES))
        self.assertFalse(tickets & set(lt.GAME_PROGRESSION))
        self.assertEqual(len(lt.GAME_PROGRESSION), 19)
        for descriptor in SOURCES:
            ticket = lt.ticket_for_descriptor(descriptor)
            if ticket is None:
                self.assertIn(descriptor, lt.GAME_PROGRESSION)
            else:
                self.assertTrue(SOURCES[descriptor].startswith(ticket.island), SOURCES[descriptor])

    def test_tickets_are_the_games_four_event_items_with_their_islands_flags(self):
        from emerald_multiplayer.trade_labels import ITEM_NAMES
        self.assertEqual([t.key for t in lt.TICKETS], ["eon", "mystic", "aurora", "old_sea_map"])
        self.assertEqual(sorted(t.index for t in lt.TICKETS), [1, 2, 3, 4])
        for ticket in lt.TICKETS:
            self.assertEqual(ITEM_NAMES[ticket.item], ticket.name)
        # engine include/constants/flags.h: SYSTEM_FLAGS 0x860; ENABLE_SHIP_* +0x53, +0x80, +0x75, +0x76; RECEIVED_*
        self.assertEqual([t.ship_flag for t in lt.TICKETS], [0x8B3, 0x8E0, 0x8D5, 0x8D6])
        self.assertEqual([t.received_flag for t in lt.TICKETS], [None, 0x13B, 0x13A, 0x13C])
        for flag in [t.ship_flag for t in lt.TICKETS] + [0x13A, 0x13B, 0x13C, lt.FLAG_SYS_TOWER_SILVER + 13]:
            self.assertLess(flag // 8, lt.FLAG_BYTES)

    def test_pinned_offsets_agree_with_the_hosts_other_readers(self):
        from emerald_multiplayer import character_transfer, frontier_service, tower_rules, trade_effect_flash
        self.assertEqual(lt.FLAGS_OFFSET, frontier_service.FLAGS_OFFSET)
        self.assertEqual(lt.FLAGS_OFFSET, trade_effect_flash.FLAGS)
        self.assertEqual(lt.VARS_OFFSET, character_transfer.VARS_OFFSET)
        self.assertEqual(lt.GAME_STATS_OFFSET, trade_effect_flash.GAME_STATS)
        self.assertEqual(lt.DEX_CAUGHT_OFFSET, trade_effect_flash.DEX_CAUGHT)
        self.assertEqual(lt.DEX_BYTES, trade_effect_flash.DEX_BYTES)
        self.assertEqual(lt.ENCRYPTION_KEY_OFFSET, trade_effect_flash.ENCRYPTION_KEY)
        self.assertEqual(lt.CARD_BATTLE_POINTS_OFFSET, frontier_service.BATTLE_POINTS_OFFSET + 2)
        self.assertEqual(lt.FLAG_SYS_GAME_CLEAR, tower_rules.FLAG_SYS_GAME_CLEAR)
        self.assertEqual((lt.SAVE_BLOCK_1_SIZE, lt.SAVE_BLOCK_2_SIZE), (SAVE_BLOCK_1_SIZE, SAVE_BLOCK_2_SIZE))


class SaveFactsTests(unittest.TestCase):
    def test_a_new_save_has_nothing(self):
        facts = lt.save_facts(*blocks())
        self.assertEqual(facts, lt.TicketFacts())

    def test_each_fact_is_read_where_the_game_keeps_it(self):
        block1, block2 = blocks()
        set_hall_of_fame(block1, block2, 2)
        for flag in (lt.FLAG_DEFEATED_REGIROCK, lt.FLAG_DEFEATED_REGISTEEL, lt.FLAG_DEFEATED_KYOGRE,
                     lt.FLAG_DEFEATED_RAYQUAZA):
            set_flag(block1, flag)
        for facility in range(7):
            set_flag(block1, lt.FLAG_SYS_TOWER_SILVER + 2 * facility)
        set_flag(block1, lt.FLAG_SYS_TOWER_SILVER + 2 * 3 + 1)          # the Arena's Gold Symbol
        set_var(block1, lt.VAR_TRICK_HOUSE_LEVEL, 8)
        catch(block1, 1, 25, 150, 384, 721)
        struct.pack_into("<H", block2, lt.CARD_BATTLE_POINTS_OFFSET, 1234)
        set_flag(block1, lt.TICKET_BY_KEY["aurora"].ship_flag)
        facts = lt.save_facts(bytes(block1), bytes(block2), SimpleNamespace(highest=63))
        self.assertEqual(facts, lt.TicketFacts(hall_of_fame=2, dex_caught=5, regis=2, weather=2, rayquaza=1,
                                               trick_house=8, silver_symbols=7, gold_symbols=1, frontier_bp=1234,
                                               tower_floor=63, islands=frozenset({"aurora"})))

    def test_the_hall_of_fame_counts_once_the_game_is_clear_even_before_its_statistic(self):
        block1, block2 = blocks()
        set_flag(block1, lt.FLAG_SYS_GAME_CLEAR)
        self.assertEqual(lt.save_facts(block1, block2).hall_of_fame, 1)
        set_hall_of_fame(block1, block2, 3)
        self.assertEqual(lt.save_facts(block1, block2).hall_of_fame, 3)
        set_hall_of_fame(block1, block2, 0xFFFFFF)                       # the game stops counting at 999
        self.assertEqual(lt.save_facts(block1, block2).hall_of_fame, 999)

    def test_a_save_of_another_layout_is_refused(self):
        block1, block2 = blocks()
        with self.assertRaises(lt.TicketError):
            lt.save_facts(bytes(block1[:-1]), bytes(block2))
        with self.assertRaises(lt.TicketError):
            lt.save_facts(bytes(block1), bytes(block2) + b"\0")

    def test_host_records_join_the_saves_facts(self):
        facts = lt.save_facts(*blocks(), SimpleNamespace(highest=40))
        joined = lt.with_host_records(facts, tower_best=55, coop_frontier_streak=7, coop_league=1, championship_wins=2)
        self.assertEqual((joined.tower_floor, joined.coop_frontier_streak, joined.coop_league, joined.championship_wins),
                         (55, 7, 1, 2))
        self.assertEqual(lt.with_host_records(facts, tower_best=12).tower_floor, 40)   # the save's record is kept

    def test_the_facts_come_out_of_a_real_flash_container(self):
        """The same offsets through flash.inspect_flash (newest bank, sector checksums recomputed): block 2 is section 0,
        block 1 sections 1-4."""
        def put1(data, offset, payload):
            return test_flash._rewrite(data, 0, 1 + offset // 3968, offset % 3968, payload)

        data = test_flash.make_flash()
        key = 0x01020304
        data = test_flash._rewrite(data, 0, 0, lt.ENCRYPTION_KEY_OFFSET, struct.pack("<I", key))
        data = test_flash._rewrite(data, 0, 0, lt.CARD_BATTLE_POINTS_OFFSET, struct.pack("<H", 77))
        data = put1(data, lt.GAME_STATS_OFFSET + 4 * lt.GAME_STAT_ENTERED_HOF, struct.pack("<I", 2 ^ key))
        flags = bytearray(lt.FLAG_BYTES)
        for flag in lt.REGI_FLAGS + (lt.FLAG_SYS_TOWER_SILVER, lt.TICKET_BY_KEY["eon"].ship_flag):
            flags[flag // 8] |= 1 << (flag % 8)
        data = put1(data, lt.FLAGS_OFFSET, bytes(flags))
        data = put1(data, lt.VARS_OFFSET + 2 * (lt.VAR_TRICK_HOUSE_LEVEL - 0x4000), struct.pack("<H", 5))
        data = put1(data, lt.DEX_CAUGHT_OFFSET, b"\xff\x01")
        data = test_flash.FlashTests._put_block3(data, TOWER_RECORD_OFFSET,
                                                 test_tower_contract.tower_record(highest=30, progress=31))
        snapshot = inspect_flash(data)
        facts = lt.save_facts(snapshot.save_block1, snapshot.save_block2, snapshot.tower)
        self.assertEqual(facts, lt.TicketFacts(hall_of_fame=2, dex_caught=9, regis=3, trick_house=5, silver_symbols=1,
                                               frontier_bp=77, tower_floor=30, islands=frozenset({"eon"})))


class SourceTests(unittest.TestCase):
    def test_sources_parse_and_refuse(self):
        self.assertEqual(lt.parse_source("tower_floor:75"), lt.Source("tower_floor", 75))
        self.assertEqual(lt.parse_source("regi_trio"), lt.Source("regi_trio", None))
        for text in ("tower_floor", "tower_floor:0", "tower_floor:101", "tower_floor:075", "tower_floor:7.5",
                     "tower_floor:²", "regi_trio:1", "casino", "", "x" * 65, None, 7,
                     "silver_symbols:8", "pokedex:722", "hall_of_fame:1000"):
            with self.subTest(text=text), self.assertRaises(lt.TicketError):
                lt.parse_source(text)

    def test_progress_and_labels(self):
        facts = lt.TicketFacts(regis=2, silver_symbols=7, tower_floor=80)
        self.assertEqual(lt.parse_source("regi_trio").progress(facts), (2, 3))
        self.assertFalse(lt.parse_source("regi_trio").met(facts))
        self.assertEqual(lt.parse_source("tower_floor:75").progress(facts), (75, 75))
        self.assertTrue(lt.parse_source("silver_symbols:7").met(facts))
        self.assertEqual(lt.parse_source("tower_floor:75").label, "Clear floor 75 of Battle Tower: Legends")
        self.assertEqual(lt.parse_source("hall_of_fame:2").label, "Enter the Hall of Fame 2 time(s)")

    def test_the_defaults_follow_the_owners_three_kinds_and_need_nobody_else(self):
        sources = lt.validate_sources(lt.DEFAULT_SOURCES)
        self.assertEqual(set(sources), set(lt.TICKET_BY_KEY))
        categories = {source.condition.category for choices in sources.values() for source in choices}
        self.assertEqual(categories, {lt.POSTGAME, lt.QUEST, lt.FRONTIER})
        for key, choices in sources.items():
            self.assertTrue(any(source.condition.solo for source in choices), key)
        self.assertEqual(sources["eon"], (lt.Source("hall_of_fame", 2),))
        self.assertEqual(sources["mystic"], (lt.Source("silver_symbols", 7), lt.Source("tower_floor", 75)))
        self.assertEqual(lt.CASINO_PRICES, {})       # no Game Corner ticket unless the owner sets a price

    def test_any_source_earns_the_ticket_and_the_settings_order_names_it(self):
        sources = lt.validate_sources(lt.DEFAULT_SOURCES)
        self.assertEqual(lt.earned_by(sources, lt.TicketFacts()), {})
        earned = lt.earned_by(sources, lt.TicketFacts(tower_floor=75, hall_of_fame=1, regis=3))
        self.assertEqual(earned, {"mystic": lt.Source("tower_floor", 75), "old_sea_map": lt.Source("regi_trio", None)})
        earned = lt.earned_by(sources, lt.TicketFacts(tower_floor=100, silver_symbols=7, weather=3, hall_of_fame=2))
        self.assertEqual(earned["mystic"], lt.Source("silver_symbols", 7))
        self.assertEqual(set(earned), {"eon", "aurora", "mystic"})

    def test_settings_are_refused_rather_than_half_used(self):
        good = {key: list(value) for key, value in lt.DEFAULT_SOURCES.items()}
        for name, mapping in (("missing ticket", {k: v for k, v in good.items() if k != "eon"}),
                              ("extra ticket", {**good, "gs_ball": ["regi_trio"]}),
                              ("no source", {**good, "eon": []}),
                              ("five sources", {**good, "eon": ["regi_trio", "rayquaza", "trick_house", "weather_trio",
                                                               "hall_of_fame:1"]}),
                              ("twice", {**good, "eon": ["regi_trio", "regi_trio"]}),
                              ("not a list", {**good, "eon": "regi_trio"}),
                              ("bad source", {**good, "eon": ["hall_of_fame"]})):
            with self.subTest(name), self.assertRaises(lt.TicketError):
                lt.validate_sources(mapping)

    def test_a_world_file_replaces_whole_ticket_lines(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "w.sqlite3.tickets.json"
            self.assertEqual(lt.load_sources(path), lt.validate_sources(lt.DEFAULT_SOURCES))
            path.write_text(json.dumps({"sources": {"eon": ["hall_of_fame:1", "coop_league:1"]}}), encoding="utf-8")
            sources = lt.load_sources(path)
            self.assertEqual(sources["eon"], (lt.Source("hall_of_fame", 1), lt.Source("coop_league", 1)))
            self.assertEqual(sources["aurora"], (lt.Source("weather_trio", None),))
            for text in ("{", "[]", json.dumps({"sources": {"gs_ball": ["regi_trio"]}}),
                         json.dumps({"sources": {"eon": ["casino"]}}), json.dumps({"tickets": {}}),
                         json.dumps({"sources": {}, "casino": {}})):
                path.write_text(text, encoding="utf-8")
                with self.subTest(text=text), self.assertRaises(lt.TicketError):
                    lt.load_sources(path)

    def test_the_banner_fits_the_games_two_lines(self):
        for ticket in lt.TICKETS:
            first, second = lt.notice(ticket)
            self.assertLessEqual(max(len(first), len(second)), 32)
            self.assertTrue(first.startswith(ticket.name.upper()))


class LedgerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "world.sqlite3"
        self.now = 1000.0
        self.db, self.book = open_book(self.path, lambda: self.now)
        self.addCleanup(lambda: self.db.close())
        self.wallet = Wallet()
        self.sources = lt.validate_sources(lt.DEFAULT_SOURCES)

    def run_once(self, facts, revision=1, player=PLAYER, book=None):
        return lt.reconcile(book or self.book, player, sources=self.sources, facts=facts, revision=revision,
                            grant=self.wallet.grant, receipt=self.wallet.receipt)

    def state(self, ticket, player=PLAYER):
        row = self.book.row(player, ticket)
        return None if row is None else row["state"]

    def test_nothing_is_earned_or_sent_before_a_source_is_met(self):
        self.assertEqual(self.run_once(lt.TicketFacts(hall_of_fame=1, regis=2, silver_symbols=6, tower_floor=74)), [])
        self.assertEqual(self.book.rows(PLAYER), [])
        self.assertEqual(self.wallet.words, {})

    def test_a_met_source_queues_one_word_and_its_receipt_delivers_it_once(self):
        facts = lt.TicketFacts(regis=3)
        self.assertEqual(self.run_once(facts), [])
        row = self.book.row(PLAYER, "old_sea_map")
        self.assertEqual((row["state"], row["source"], row["attempt"], row["ref"]), ("sent", "regi_trio", 1,
                                                                                     "ticket:old_sea_map:1"))
        self.assertEqual(self.wallet.words, {(PLAYER, "ticket:old_sea_map:1"): {"index": 4, "applied": None}})
        for _ in range(3):                                   # passes before the game reports: nothing new is queued
            self.assertEqual(self.run_once(facts), [])
        self.assertEqual(self.wallet.queued(PLAYER), ["ticket:old_sea_map:1"])
        self.wallet.report(PLAYER, "ticket:old_sea_map:1", lt.RECEIPT_GIVEN)
        self.assertEqual(self.run_once(facts), [lt.TICKET_BY_KEY["old_sea_map"]])     # the notice, once
        self.assertEqual(self.state("old_sea_map"), "delivered")
        self.assertEqual(self.run_once(facts), [])
        self.assertEqual(self.wallet.queued(PLAYER), ["ticket:old_sea_map:1"])

    def test_already_owned_is_delivered_without_a_notice(self):
        self.run_once(lt.TicketFacts(hall_of_fame=2))
        self.wallet.report(PLAYER, "ticket:eon:1", lt.RECEIPT_OWNED)
        self.assertEqual(self.run_once(lt.TicketFacts(hall_of_fame=2)), [])
        self.assertEqual(self.book.row(PLAYER, "eon")["receipt"], lt.RECEIPT_OWNED)
        self.assertEqual(self.state("eon"), "delivered")

    def test_no_room_is_owed_and_offered_again_after_the_next_save_only(self):
        facts = lt.TicketFacts(weather=3)
        self.run_once(facts, revision=5)
        self.wallet.report(PLAYER, "ticket:aurora:1", lt.RECEIPT_NO_ROOM)
        self.run_once(facts, revision=5)
        self.assertEqual((self.state("aurora"), self.book.row(PLAYER, "aurora")["owed_revision"]), ("owed", 5))
        for _ in range(3):
            self.run_once(facts, revision=5)                 # no newer save: no new word
        self.run_once(facts, revision=None)                  # save unknown: no new word either
        self.assertEqual(self.wallet.queued(PLAYER), ["ticket:aurora:1"])
        self.run_once(facts, revision=6)
        self.assertEqual(self.wallet.queued(PLAYER), ["ticket:aurora:1", "ticket:aurora:2"])
        self.assertEqual(self.book.row(PLAYER, "aurora")["attempt"], 2)
        self.wallet.report(PLAYER, "ticket:aurora:1", lt.RECEIPT_GIVEN)   # a stale receipt of the first attempt
        self.assertEqual(self.run_once(facts, revision=6), [])
        self.assertEqual(self.state("aurora"), "sent")
        self.wallet.report(PLAYER, "ticket:aurora:2", lt.RECEIPT_GIVEN)
        self.assertEqual(self.run_once(facts, revision=6), [lt.TICKET_BY_KEY["aurora"]])
        self.assertEqual(self.state("aurora"), "delivered")

    def test_a_refusal_settled_without_a_readable_save_is_not_stuck(self):
        self.run_once(lt.TicketFacts(regis=3), revision=4)
        self.wallet.report(PLAYER, "ticket:old_sea_map:1", lt.RECEIPT_NO_ROOM)
        self.run_once(None, revision=None)                    # the save cannot be read just now
        row = self.book.row(PLAYER, "old_sea_map")
        self.assertEqual((row["state"], row["owed_revision"]), ("owed", None))
        self.run_once(None, revision=None)
        self.assertEqual(self.wallet.queued(PLAYER), ["ticket:old_sea_map:1"])
        self.run_once(lt.TicketFacts(regis=3), revision=4)    # readable again: offered again, once
        self.run_once(lt.TicketFacts(regis=3), revision=4)
        self.assertEqual(self.wallet.queued(PLAYER), ["ticket:old_sea_map:1", "ticket:old_sea_map:2"])

    def test_a_save_that_already_opens_the_island_is_never_sent_the_ticket(self):
        owned = lt.TicketFacts(silver_symbols=7, islands=frozenset({"mystic"}))
        self.run_once(owned)
        self.assertIsNone(self.book.row(PLAYER, "mystic"))
        self.assertEqual(self.wallet.words, {})

    def test_an_owed_ticket_the_save_shows_open_is_delivered_without_another_word(self):
        self.run_once(lt.TicketFacts(regis=3), revision=2)
        self.wallet.report(PLAYER, "ticket:old_sea_map:1", lt.RECEIPT_NO_ROOM)
        self.run_once(lt.TicketFacts(regis=3), revision=2)
        self.assertEqual(self.state("old_sea_map"), "owed")
        self.run_once(lt.TicketFacts(regis=3, islands=frozenset({"old_sea_map"})), revision=3)   # e.g. another world's
        self.assertEqual(self.state("old_sea_map"), "delivered")
        self.assertEqual(self.wallet.queued(PLAYER), ["ticket:old_sea_map:1"])

    def test_a_delivered_ticket_is_never_sent_again(self):
        self.run_once(lt.TicketFacts(hall_of_fame=2))
        self.wallet.report(PLAYER, "ticket:eon:1", lt.RECEIPT_GIVEN)
        self.run_once(lt.TicketFacts(hall_of_fame=2))
        # an older save without the island, and settings that no longer name what earned it
        self.sources = lt.validate_sources({**lt.DEFAULT_SOURCES, "eon": ("pokedex:700",)})
        self.run_once(lt.TicketFacts(hall_of_fame=2), revision=9)
        self.run_once(lt.TicketFacts(), revision=10)
        self.assertEqual(self.state("eon"), "delivered")
        self.assertEqual(self.wallet.queued(PLAYER), ["ticket:eon:1"])

    def test_an_unreadable_save_still_settles_receipts_and_earns_nothing(self):
        self.run_once(lt.TicketFacts(hall_of_fame=2))
        self.wallet.report(PLAYER, "ticket:eon:1", lt.RECEIPT_GIVEN)
        self.assertEqual(self.run_once(None, revision=None), [lt.TICKET_BY_KEY["eon"]])
        self.assertEqual(self.book.rows(PLAYER)[0]["state"], "delivered")
        self.assertEqual(len(self.book.rows(PLAYER)), 1)

    def test_a_crash_between_recording_and_queueing_queues_it_on_the_next_pass(self):
        def crash(player, ticket, ref):
            raise OSError("the host stopped")

        with self.assertRaises(OSError):
            lt.reconcile(self.book, PLAYER, sources=self.sources, facts=lt.TicketFacts(hall_of_fame=2), revision=1,
                         grant=crash, receipt=self.wallet.receipt)
        self.assertEqual((self.state("eon"), self.book.row(PLAYER, "eon")["ref"]), ("sent", "ticket:eon:1"))
        self.run_once(lt.TicketFacts(hall_of_fame=2))
        self.run_once(lt.TicketFacts(hall_of_fame=2))
        self.assertEqual(self.wallet.queued(PLAYER), ["ticket:eon:1"])

    def test_the_ledger_survives_a_restart_of_the_host(self):
        self.run_once(lt.TicketFacts(silver_symbols=7, regis=3))
        self.db.close()
        self.db, self.book = open_book(self.path, lambda: self.now)
        self.assertEqual(self.state("mystic"), "sent")
        self.wallet.report(PLAYER, "ticket:mystic:1", lt.RECEIPT_GIVEN)
        self.wallet.report(PLAYER, "ticket:old_sea_map:1", lt.RECEIPT_GIVEN)
        given = self.run_once(lt.TicketFacts(silver_symbols=7, regis=3))
        self.assertEqual({ticket.key for ticket in given}, {"mystic", "old_sea_map"})
        self.assertEqual(sorted(self.wallet.queued(PLAYER)), ["ticket:mystic:1", "ticket:old_sea_map:1"])

    def test_players_are_independent(self):
        self.run_once(lt.TicketFacts(hall_of_fame=2), player=PLAYER)
        self.run_once(lt.TicketFacts(), player=OTHER)
        self.assertEqual(self.wallet.queued(PLAYER), ["ticket:eon:1"])
        self.assertEqual(self.wallet.queued(OTHER), [])
        self.run_once(lt.TicketFacts(hall_of_fame=2), player=OTHER)
        self.assertEqual(self.wallet.queued(OTHER), ["ticket:eon:1"])
        self.wallet.report(OTHER, "ticket:eon:1", lt.RECEIPT_GIVEN)
        self.run_once(lt.TicketFacts(hall_of_fame=2), player=OTHER)
        self.assertEqual((self.state("eon"), self.state("eon", OTHER)), ("sent", "delivered"))

    def test_the_first_source_met_is_the_one_recorded(self):
        self.run_once(lt.TicketFacts(tower_floor=75))
        self.run_once(lt.TicketFacts(tower_floor=75, silver_symbols=7))
        self.assertEqual(self.book.row(PLAYER, "mystic")["source"], "tower_floor:75")

    def test_book_refusals(self):
        with self.assertRaises(lt.TicketError):
            self.book.earn(PLAYER, "gs_ball", "regi_trio")
        with self.assertRaises(lt.TicketError):
            self.book.send(PLAYER, "eon")                       # nothing earned
        self.assertTrue(self.book.earn(PLAYER, "eon", "hall_of_fame:2"))
        self.assertFalse(self.book.earn(PLAYER, "eon", "coop_league:1"))
        ref = self.book.send(PLAYER, "eon")
        with self.assertRaises(lt.TicketError):
            self.book.send(PLAYER, "eon")                       # already on the wallet stream
        self.assertIsNone(self.book.settle(PLAYER, "eon", "ticket:eon:9", 1, 1))
        with self.assertRaises(lt.TicketError):
            self.book.settle(PLAYER, "eon", ref, 3, 1)
        self.assertEqual(self.book.settle(PLAYER, "eon", ref, 1, 1), "delivered")
        self.assertIsNone(self.book.settle(PLAYER, "eon", ref, 0, 1))
        self.assertFalse(self.book.seen(PLAYER, "eon"))


if __name__ == "__main__":
    unittest.main()
