"""Update 31 engine port, app side: the rival battle's environment in the native preparation, and the manifest marker.

A rival checkpoint battle names its checkpoint and canonical battle environment in the preparation's u32 (engine
include/constants/multiplayer_rival.h MP_RIVAL_PREP_WORD), so every core draws the same background and resolves the
environment-dependent moves alike. Real BattleDesk / BattleResults / WorldServer objects, simulated native receipts
(no game core runs here; the engine's own checks are --selftest-rival and tools/pc_port/rival_check.py).
"""
import struct
import unittest
from unittest.mock import patch

from emerald_multiplayer.battle_desk import BattleError
from emerald_multiplayer.battle_mailbox import BattleMailboxError
from emerald_multiplayer.battle_protocol import challenge_view, _view
from emerald_multiplayer.coop_code import encode as ladder_code
from emerald_multiplayer.native_battle import Preparation
from emerald_multiplayer.protocol import ProtocolError
from emerald_multiplayer.rival_catalogue import (BY_ID, ENVIRONMENT_IDS, IDS, PREPARATION_TAG, preparation_word,
                                                 valid_preparation_word)
import test_battle_manifest as manifest_fixture
import test_rival_integration as integration
import test_rival_server as server_fixture

PLAIN = ENVIRONMENT_IDS["BATTLE_ENVIRONMENT_PLAIN"]


class PreparationWordTests(unittest.TestCase):
    def test_each_checkpoint_has_the_engine_word_tag_order_and_canonical_environment(self):
        self.assertEqual(PLAIN, 9)  # enum BattleEnvironments; check_rival_catalogue.py re-reads it from the engine
        words = [preparation_word(cid) for cid in IDS]
        self.assertEqual(words, [PREPARATION_TAG | (order << 8) | PLAIN for order in range(1, 6)])
        self.assertEqual(words[2], 0x52560309)  # Route 110: checkpoint 3, PLAIN
        self.assertTrue(all(valid_preparation_word(word) for word in words))
        self.assertTrue(all(BY_ID[cid].canonical_environment in ENVIRONMENT_IDS for cid in IDS))

    def test_nothing_else_is_a_rival_word(self):
        for word in (0, 1, 8, ladder_code(1, 2, 50), PREPARATION_TAG, PREPARATION_TAG | (6 << 8) | PLAIN,
                     PREPARATION_TAG | (3 << 8), PREPARATION_TAG | (3 << 8) | 0, True, -1, "0x52560309", None):
            with self.subTest(word=word):
                self.assertFalse(valid_preparation_word(word))

    def test_the_preparation_codec_carries_a_rival_word_and_refuses_other_values(self):
        rng = bytes(range(1, 17))
        prepared = Preparation(5, 7, 0x12345678, 0xCAFEBABE, rng, preparation_word("route119"))
        packed = prepared.pack()
        self.assertEqual(struct.unpack_from("<I", packed, 32)[0], 0x52560409)
        self.assertEqual(Preparation.unpack(packed), prepared)
        self.assertEqual(Preparation.unpack(Preparation(5, 7, 1, 2, rng, 3).pack()).gym, 3)  # co-op Gym codes unchanged
        for bad in (PREPARATION_TAG | (4 << 8) | 0, 0x10000, 9):
            with self.subTest(bad=bad):
                with self.assertRaises(BattleMailboxError):
                    Preparation(5, 7, 1, 2, rng, bad)
                with self.assertRaises(BattleMailboxError):
                    Preparation.unpack(packed[:32] + struct.pack("<I", bad))


class RivalEnvironmentDeskTests(integration.RivalIntegrationTests):
    """The Desk carries the word from the rival match to every trainer's preparation (only when the host enables it)."""

    def invite_as(self, actor):
        lease = self.leases[actor]
        word = preparation_word(self.checkpoint)

        def invite(match, battle_id):
            if match.mode == 2:
                self.desk.invite(actor, lease, next(p for p in match.players if p != actor), battle_id, environment=word)
            else:
                own = next(t for t in match.teams if actor in t)
                other = next(t for t in match.teams if actor not in t)
                self.desk.invite_multi(actor, lease, next(p for p in own if p != actor), tuple(other), battle_id,
                                       environment=word)
        return invite

    def assert_environment_everywhere(self, word):
        self.assertEqual(self.view["environment"], word)
        public = challenge_view(self.view)
        self.assertEqual(public["environment"], word)
        for player in self.view["players"]:
            _view(public, player)  # every companion's validator accepts it

    def durable_view(self):
        import json
        row = self.store._connection.execute("SELECT record FROM battle_reservations WHERE battle_id=?", (self.battle_id,)).fetchone()
        return json.loads(row["record"])["view"]

    def test_singles_rival_battle_prepares_every_core_with_the_checkpoint_environment_and_completes(self):
        self.checkpoint = "route110"
        self.gather([0, 1], integration.ROUTE110)
        self.issue(0)
        self.assert_environment_everywhere(0x52560309)
        players = [self.slot(p) for p in self.view["players"]]
        self.call("accept", players[1] if players[0] == 0 else players[0], self.view["fingerprint"])
        for i in players:
            self.call("register", i, 100 + i)
        for i in players:
            request, _, _ = self.prepare(i)  # the Desk verifies the exact preparation bytes, word included
            self.assertEqual(Preparation.unpack(request.data).gym, 0x52560309)
        # The durable reservation keeps the word for exact recovery, and its own validator accepts the record.
        self.assertEqual(self.durable_view()["environment"], 0x52560309)
        self.assertTrue(self.desk.reservations.contains(self.battle_id))
        self.desk.authorize_start(self.battle_id, self.generation)
        for i in players:
            self.start(i); self.parts(i)
        self.desk.authorize_running(self.battle_id, self.generation)
        for i in players:
            self.finish(i, outcome=1)
        for i in players:
            self.release_with(i, 1)
        self.assertEqual(self.rpc(0, "status")["state"], "completed")

    def test_two_versus_two_rival_battle_carries_the_word_in_mode_3(self):
        self.checkpoint = "route119"
        self.gather([0, 1, 2, 3], integration.ROUTE119)
        self.issue(0)
        self.assertEqual(self.view["mode"], 3)
        self.assert_environment_everywhere(0x52560409)
        self.assertEqual(self.play(2)["state"], "closed")
        self.assertEqual(self.rpc(1, "status")["state"], "completed")

    def test_the_word_is_part_of_consent_and_a_retry_cannot_change_it(self):
        self.checkpoint = "route110"
        lease = self.leases[self.ids[0]]
        battle_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
        with_word = self.desk.invite(self.ids[0], lease, self.ids[1], battle_id, environment=preparation_word("route110"))
        with self.assertRaises(BattleError) as caught:
            self.desk.invite(self.ids[0], lease, self.ids[1], battle_id)
        self.assertEqual(caught.exception.code, "request_conflict")
        self.assertEqual(with_word["environment"], preparation_word("route110"))
        self.assertNotIn("environment", challenge_view({**with_word, "environment": 0}))

    def test_only_rival_words_and_only_pvp_battles_carry_an_environment(self):
        lease = self.leases[self.ids[0]]
        for word in (3, ladder_code(1, 2, 50), PREPARATION_TAG | (3 << 8)):
            with self.subTest(word=word), self.assertRaises(BattleError) as caught:
                self.desk.invite(self.ids[0], lease, self.ids[1], "cccccccc-cccc-4ccc-8ccc-cccccccccccc", environment=word)
            self.assertEqual(caught.exception.code, "invalid_battle")
        with self.assertRaises(BattleError):
            self.desk._invite(self.ids[0], lease, tuple(self.ids), "dddddddd-dddd-4ddd-8ddd-dddddddddddd", mode=5,
                              environment=preparation_word("route110"))

    def test_the_companion_validator_refuses_a_bad_or_misplaced_environment(self):
        self.checkpoint = "route110"
        self.gather([0, 1], integration.ROUTE110)
        self.issue(0)
        public = challenge_view(self.view)
        for bad in (3, PREPARATION_TAG, True):
            with self.subTest(bad=bad), self.assertRaises(ProtocolError):
                _view({**public, "environment": bad}, self.view["players"][0])
        with self.assertRaises(ProtocolError):
            _view({**public, "mode": 5, "environment": public["environment"]}, self.view["players"][0])


class OrdinaryBattlesUnchangedTests(integration.RivalIntegrationTests):
    def test_a_rival_battle_without_the_capability_and_any_ordinary_battle_carry_no_environment(self):
        self.checkpoint = "route110"
        self.gather([0, 1], integration.ROUTE110)
        self.issue(0)  # the inherited invite_as: no environment (a host whose game does not advertise rival_abi_version)
        self.assertNotIn("environment", self.view)
        self.assertNotIn("environment", challenge_view(self.view))
        self.assertEqual(self.call("accept", self.slot([p for p in self.view["players"] if p != self.view["sender"]][0]),
                                   self.view["fingerprint"])["state"], "accepted")


class RivalEnvironmentServerTests(server_fixture.RivalServerTests):
    async def test_the_host_enables_the_environment_only_before_it_starts(self):
        with self.assertRaises(ValueError):
            self.server.enable_rival_battle_environment()  # the fixture's server is already running

    async def issue(self):
        await self.move(0, server_fixture.ROUTE110)
        await self.move(1, server_fixture.ROUTE110)
        await self.rival(0, "vote", checkpoint_id="route110", choice="start")
        await self.rival(1, "vote", checkpoint_id="route110", choice="start")
        session = (await self.rival(1, "status"))["rival"]["here"]["session"]
        reply = await self.rival(1, "match", checkpoint_id="route110", session_id=session["session_id"], match=0, attempt=0)
        return reply["result"][0]  # validated by the companion's own battle protocol

    async def test_an_enabled_host_issues_rival_matches_with_the_checkpoint_environment(self):
        self.server._rival_battle_environment = True  # what enable_rival_battle_environment sets before start
        view = await self.issue()
        self.assertEqual(view["environment"], 0x52560309)
        pending = await self.fixture.actors[0].rpc("battle_pending")
        self.assertEqual(pending["result"][0]["environment"], 0x52560309)

    async def test_a_host_without_the_capability_issues_plain_challenges(self):
        view = await self.issue()
        self.assertNotIn("environment", view)


class RivalManifestTests(manifest_fixture.CoopAndWorldManifestTests):
    def test_the_rival_marker_comes_from_the_native_executable_and_needs_the_world_mailbox(self):
        native = "00bd2780 00000004 R gMultiplayerRivalAbiVersion\n"
        plain = self.generate(self.base + self.battle + self.world)
        self.assertNotIn("rival_abi_version", plain)  # the GBA ELF alone never advertises it
        generated = self.generate_native(self.base + self.battle + self.world, native)
        self.assertEqual(generated["rival_abi_version"], 1)
        # MinGW nm (the Windows game): a leading underscore and no size column (a PE executable's symbols have none).
        mingw = self.generate_native(self.base + self.battle + self.world, "00bd2780 R _gMultiplayerRivalAbiVersion\n")
        self.assertEqual(mingw["rival_abi_version"], 1)
        with self.assertRaises(ValueError):
            self.generate_native(self.base + self.battle, native)  # no shared world mailbox
        for bad in ("00bd2780 00000008 R gMultiplayerRivalAbiVersion\n", native + native):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.generate_native(self.base + self.battle + self.world, bad)


# The inherited tests of the fixtures run in their own modules; only this module's tests run here.
for _case in (RivalEnvironmentDeskTests, OrdinaryBattlesUnchangedTests, RivalEnvironmentServerTests, RivalManifestTests):
    for _name in list(vars(_case.__mro__[1])):
        if _name.startswith("test_") and _name not in vars(_case):
            setattr(_case, _name, None)


if __name__ == "__main__":
    unittest.main()
