"""Frontier-style Championship entry rules (expansion Phase 8): the party
reader, the rules, the host setting file and the Championship hook. Real
SQLite/flash fixtures (as test_championship_recovery); no game proof."""
from __future__ import annotations

import json
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from emerald_multiplayer.championship import Championships
from emerald_multiplayer.flash import POKEMON_SIZE, SAVED_PARTY_COUNT_OFFSET, SAVED_PARTY_OFFSET, inspect_flash, _GROWTH_SUBSTRUCT_OFFSETS
from emerald_multiplayer.frontier_rules import (
    DEFAULT_ROTATION, LEGENDARY, RULE_NAMES, FrontierRuleError, FrontierSettings, PartyMember, check_party,
    party_members)
from emerald_multiplayer.protocol import ProtocolError
from emerald_multiplayer.server import WorldServer
import test_battle_desk as fixtures


def mon(species, level, item=0, egg=False, personality=0x12345678, ot_id=0xCAFE):
    box = bytearray(POKEMON_SIZE)
    struct.pack_into("<II", box, 0, personality, ot_id)
    box[19] = 2 | (4 if egg else 0)
    growth = struct.pack("<HHIBBH", species & 0x7FF, item & 0x3FF, 1000, 0, 70, 0)
    key = personality ^ ot_id
    plain = bytearray(48)
    index = _GROWTH_SUBSTRUCT_OFFSETS[personality % 24]
    plain[index * 12:index * 12 + 12] = growth
    for word in range(12):
        struct.pack_into("<I", box, 32 + word * 4, struct.unpack_from("<I", plain, word * 4)[0] ^ key)
    box[84] = level
    return bytes(box)


def party_block(*mons):
    block = bytearray(SAVED_PARTY_OFFSET + 6 * POKEMON_SIZE)
    block[SAVED_PARTY_COUNT_OFFSET] = len(mons)
    for slot, data in enumerate(mons):
        block[SAVED_PARTY_OFFSET + slot * POKEMON_SIZE:SAVED_PARTY_OFFSET + (slot + 1) * POKEMON_SIZE] = data
    return bytes(block)


class PartyReaderTests(unittest.TestCase):
    def test_reads_species_level_and_item_for_every_substruct_order(self):
        for personality in range(24):
            block = party_block(mon(25, 33, item=44, personality=personality + 24 * 5))
            self.assertEqual(party_members(block), [PartyMember(25, 33, 44)], personality)

    def test_eggs_do_not_count_and_the_count_byte_bounds_the_read(self):
        block = party_block(mon(25, 5), mon(172, 1, egg=True), mon(1, 9))
        self.assertEqual([m.species for m in party_members(block)], [25, 1])
        self.assertEqual(party_members(party_block()), [])


class RuleTests(unittest.TestCase):
    def test_each_rule(self):
        mons = [PartyMember(25, 50, 10), PartyMember(26, 31, 11)]
        self.assertIsNone(check_party("open", []))
        self.assertIsNone(check_party("level_50", mons))
        self.assertEqual(check_party("level_30", mons), "Over level 30")
        self.assertEqual(check_party("level_50", mons + [PartyMember(1, 51, 0)]), "Over level 50")
        self.assertEqual(check_party("species_clause", mons + [PartyMember(25, 5, 0)]), "Same species twice")
        self.assertIsNone(check_party("species_clause", mons))
        self.assertEqual(check_party("item_clause", mons + [PartyMember(3, 5, 10)]), "Same item twice")
        self.assertIsNone(check_party("item_clause", mons + [PartyMember(3, 5, 0), PartyMember(4, 5, 0)]))  # no item is not an item
        self.assertEqual(check_party("no_legendaries", mons + [PartyMember(150, 5, 0)]), "Legendary not allowed")
        self.assertEqual(check_party("no_legendaries", [PartyMember(721, 5, 0)]), "Legendary not allowed")
        self.assertIsNone(check_party("no_legendaries", [PartyMember(722, 5, 0), PartyMember(143, 5, 0)]))
        self.assertEqual(check_party("level_50", []), "Has no Pokemon")
        with self.assertRaises(FrontierRuleError):
            check_party("anything", mons)

    def test_the_legendary_list_is_the_kanto_to_kalos_one(self):
        self.assertEqual(len(LEGENDARY), 11 + 10 + 15 + 12 + 6)
        self.assertTrue({150, 151, 249, 250, 251, 384, 385, 386, 483, 484, 487, 493, 494, 649, 716, 718}.issubset(LEGENDARY))
        self.assertFalse({143, 149, 248, 376, 479, 637, 715}.intersection(LEGENDARY))


class SettingsTests(unittest.TestCase):
    def write(self, value):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "world.frontier.json"
        path.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
        return path

    def test_absent_means_off(self):
        self.assertFalse(FrontierSettings.load("/nonexistent/world.frontier.json").enabled)

    def test_rotation_follows_the_world_day(self):
        settings = FrontierSettings.load(self.write({}))
        self.assertTrue(settings.enabled)
        self.assertEqual([settings.rule_at(day * 86_400 + 5) for day in range(len(DEFAULT_ROTATION) + 1)],
                         list(DEFAULT_ROTATION) + [DEFAULT_ROTATION[0]])
        short = FrontierSettings.load(self.write({"rotation": ["open", "level_30"], "day_seconds": 600}))
        self.assertEqual([short.rule_at(t) for t in (0, 599, 600, 1199, 1200)],
                         ["open", "open", "level_30", "level_30", "open"])
        self.assertEqual(FrontierSettings.load(self.write({"fixed": "item_clause"})).rule_at(10 ** 7), "item_clause")
        self.assertEqual(short.rule_at(-5), "open")

    def test_bad_files_are_refused_not_ignored(self):
        for bad in ("not json", {"enabled": "yes"}, {"rotation": []}, {"rotation": ["open", "nope"]},
                    {"fixed": "nope"}, {"day_seconds": 5}, {"surprise": 1}, [1]):
            with self.assertRaises(FrontierRuleError, msg=bad):
                FrontierSettings.load(self.write(bad))
        self.assertFalse(FrontierSettings.load(self.write({"enabled": False})).enabled)


class ChampionshipHookTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.BattleDeskTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.store, self.desk = self.fixture.store, self.fixture.desk
        self.players = [p.player_id for p in self.fixture.players]
        self.roster = {p: "Trainer " + str(i) for i, p in enumerate(self.players)}
        self.folder = Path(self.fixture.temp.name)
        self.champ = Championships(self.folder / "championship.sqlite3", world_id=self.store.metadata.world_id,
                                   build_id=self.store.build_id, ruleset_id=self.store.ruleset_id)

    def request(self, operation, view=None, **fields):
        request = dict(version=1, operation=operation, **fields)
        if view is not None:
            request.update({key: view[key] for key in ("championship_id", "generation", "fingerprint")})
        return request

    def handle(self, actor, request, eligibility):
        return self.champ.handle(self.players[actor], request, roster=self.roster, desk=self.desk, results=None,
                                 invite=lambda *a: None, reservations=self.desk.reservations, eligibility=eligibility)

    def test_a_refused_party_cannot_propose_or_accept(self):
        seen = []

        def refuse_third(players):
            seen.append(tuple(players))
            if self.players[2] in players:
                raise ProtocolError("championship_ineligible", "Trainer 2: Over level 50")

        create = self.request("create", championship_id=str(uuid4()), players=list(self.players))
        with self.assertRaises(ProtocolError) as caught:
            self.handle(0, create, refuse_third)
        self.assertEqual(caught.exception.code, "championship_ineligible")
        self.assertEqual(seen, [tuple(self.players)])
        self.assertIsNone(self.handle(0, self.request("status"), None)["current"])   # nothing was stored
        # Once every party fits, the bracket is proposed; then a party that no longer fits cannot consent.
        reply = self.handle(0, create, lambda players: None)
        view = reply["current"]
        self.assertEqual(view["state"], "proposed")
        with self.assertRaises(ProtocolError):
            self.handle(2, self.request("accept", view), refuse_third)
        self.assertEqual(seen[-1], (self.players[2],))
        view = self.handle(1, self.request("accept", view), refuse_third)["current"]   # a fitting party still can
        self.assertEqual(sorted(view["consent"]), sorted([self.players[0], self.players[1]]))

    def test_without_rules_nothing_changes(self):
        create = self.request("create", championship_id=str(uuid4()), players=list(self.players))
        self.assertEqual(self.handle(0, create, None)["current"]["state"], "proposed")


class ServerEligibilityTests(unittest.TestCase):
    """Server._frontier_eligibility against the real saved parties of the fixture."""

    def setUp(self):
        self.fixture = fixtures.BattleDeskTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.store = self.fixture.store
        self.sessions = {p.player_id: SimpleNamespace(player_id=p.player_id, display_name=f"Trainer {i}", closed=False,
                                                      session_epoch=1)
                         for i, p in enumerate(self.fixture.players)}
        self.store.read_checkpoint = lambda pid, epoch: self.fixture.heads[
            [p.player_id for p in self.fixture.players].index(pid)]
        self.rule = "open"
        server = SimpleNamespace(store=self.store, sessions=self.sessions)
        server._frontier_rule = lambda: self.rule
        self.check = lambda players: WorldServer._frontier_eligibility(server, players)
        self.players = list(self.sessions)

    def party(self, index):
        head = self.fixture.heads[index]
        return party_members(inspect_flash(head.payload, save_profile=head.save_profile).save_block1)

    def test_the_fixtures_real_saves_are_read_and_judged(self):
        members = self.party(0)
        self.assertTrue(members)
        self.check(self.players)                                # open: everyone fits
        highest = max(m.level for m in members)
        self.rule = "level_30" if highest > 30 else "level_50"
        if highest > 30 and self.rule == "level_30":
            with self.assertRaises(ProtocolError) as caught:
                self.check(self.players)
            self.assertEqual(caught.exception.code, "championship_ineligible")
            self.assertRegex(str(caught.exception), r"^Trainer \d: Over level 30$")
        else:
            self.check(self.players)

    def test_a_player_who_left_or_has_no_save_is_refused(self):
        self.sessions[self.players[1]].closed = True
        with self.assertRaises(ProtocolError) as caught:
            self.check(self.players)
        self.assertEqual(caught.exception.code, "championship_roster_changed")
        self.sessions[self.players[1]].closed = False
        self.store.read_checkpoint = lambda pid, epoch: None
        with self.assertRaises(ProtocolError) as caught:
            self.check(self.players)
        self.assertEqual(caught.exception.code, "championship_ineligible")


if __name__ == "__main__":
    unittest.main()
