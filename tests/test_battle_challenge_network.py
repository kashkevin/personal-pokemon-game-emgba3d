"""Four authenticated TCP companions; no emulator execution is claimed."""
import asyncio
from pathlib import Path
import secrets
import tempfile
import unittest
from uuid import uuid4

from emerald_multiplayer.companion import BASELINE_RULESET, Companion, CompanionConfig, BattleChallengeError
from emerald_multiplayer.ownership_protocol import OWNERSHIP_PROFILE
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.trade_storage import TradeCheckpointStore
from test_companion import make_files
from test_ownership_storage import source_flash, owned_flash
from test_team_network import wait_until


class BattleChallengeNetworkTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.rom, self.manifest = make_files(self.temp.name)
        fixture = CompanionConfig(self.rom, self.manifest, str(uuid4()), "Fixture", secrets.token_bytes(32))
        self.store = TradeCheckpointStore(Path(self.temp.name) / "world.sqlite3", fixture.build_id, BASELINE_RULESET)
        self.store.begin_server_boot()
        self.players, self.heads = [], []
        for i in range(4):
            p = self.store.create_player(f"Trainer {i}")
            lease = self.store.acquire_lease(p.player_id, p.credential)
            personalities = (7 + i * 2, 8 + i * 2)
            self.store.enroll_player(p.player_id, source_flash(("party:0", "party:1"), personalities=personalities))
            grant = self.store.reserve_instances(p.player_id, lease, str(uuid4()), 0, 1, 32)
            payload = owned_flash(grant, (("party:0", grant.start), ("party:1", grant.start + 1)), personalities=personalities)
            self.heads.append(self.store.commit_checkpoint(p.player_id, lease, str(uuid4()), 0,
                payload, fixture.build_id, BASELINE_RULESET, OWNERSHIP_PROFILE))
            self.store.release_lease(p.player_id, lease)
            self.players.append(p)
        self.server = WorldServer(ServerConfig(fixture.build_id, BASELINE_RULESET,
            heartbeat_interval=.05, idle_timeout=10), store=self.store,
            development_teams=True, development_battles=True)
        await self.server.start(port=0)
        self.companions = []
        for p in self.players:
            companion = Companion(CompanionConfig(self.rom, self.manifest, p.player_id, p.display_name,
                secrets.token_bytes(32), server_port=self.server.address[1], ipc_port=0,
                server_credential=p.credential, reconnect_delay=.02, remote_timeout=15))
            self.companions.append(companion)
            await companion.start()
        await wait_until(lambda: all(c.connected for c in self.companions))

    async def asyncTearDown(self):
        for c in self.companions: await c.close()
        await self.server.close()
        self.store.close()
        self.temp.cleanup()

    async def rpc(self, i, op, **fields):
        return (await self.companions[i].battle_challenge_rpc(op, **fields))["result"]

    async def invite(self):
        return await self.rpc(0, "invite", peer=self.players[1].player_id, battle_id=str(uuid4()))

    async def accept(self, i, view):
        return await self.rpc(i, "accept", battle_id=view["battle_id"], generation=view["generation"],
                              fingerprint=view["fingerprint"])

    async def error(self, code, i, op, **fields):
        with self.assertRaises(BattleChallengeError) as caught:
            await self.rpc(i, op, **fields)
        self.assertEqual(caught.exception.code, code)

    async def test_invite_discovery_independent_accept_and_cancel(self):
        view = await self.invite()
        self.assertEqual(await self.rpc(1, "pending"), [view])
        self.assertEqual(await self.rpc(2, "pending"), [])
        await self.error("battle_not_recipient", 0, "accept", battle_id=view["battle_id"],
                         generation=view["generation"], fingerprint=view["fingerprint"])
        accepted = await self.accept(1, view)
        self.assertEqual(accepted["state"], "accepted")
        self.assertEqual(len(accepted["consent"]), 2)
        self.assertFalse(self.server.battle_desk._active[view["battle_id"]].bind_intent)
        canceled = await self.rpc(1, "cancel", battle_id=view["battle_id"], generation=view["generation"])
        self.assertEqual(canceled["state"], "aborted")
        self.assertEqual(await self.rpc(0, "pending"), [])
        self.assertEqual(await self.rpc(0, "status", battle_id=view["battle_id"]), canceled)

    async def test_four_human_consent_never_inherits_teammate_choice(self):
        view = await self.rpc(0, "invite_multi", teammate=self.players[2].player_id,
            opponents=[self.players[1].player_id, self.players[3].player_id], battle_id=str(uuid4()))
        self.assertEqual(view["mode"], 3)
        self.assertEqual(set(view["players"][::2]), {self.players[0].player_id, self.players[2].player_id})
        for i in (1, 2):
            self.assertEqual((await self.accept(i, view))["state"], "invited")
        accepted = await self.accept(3, view)
        self.assertEqual(accepted["state"], "accepted")
        self.assertEqual(len(accepted["consent"]), 4)
        self.assertFalse(self.server.battle_desk._active[view["battle_id"]].incarnations)
        for i in range(4):
            self.assertEqual(await self.rpc(i, "pending"), [accepted])

    async def test_wrong_participant_and_changed_fingerprint_refused(self):
        view = await self.invite()
        await self.error("battle_not_participant", 2, "status", battle_id=view["battle_id"])
        await self.error("battle_offer_changed", 1, "accept", battle_id=view["battle_id"],
                         generation=view["generation"], fingerprint="0" * 64)
        await self.error("battle_generation_mismatch", 1, "cancel", battle_id=view["battle_id"], generation=str(uuid4()))
        self.assertEqual((await self.rpc(1, "status", battle_id=view["battle_id"]))["state"], "invited")

    async def test_exact_invitation_retry_does_not_create_new_rng_or_consent(self):
        view = await self.invite()
        repeat = await self.rpc(0, "invite", peer=self.players[1].player_id, battle_id=view["battle_id"])
        self.assertEqual(repeat, view)
        self.assertEqual(len(self.server.battle_desk._active), 1)
        await self.error("request_conflict", 0, "invite", peer=self.players[2].player_id, battle_id=view["battle_id"])

    async def test_default_gate_returns_controlled_error_and_keeps_connection(self):
        self.server.battle_desk = None
        await self.error("battle_disabled", 0, "pending")
        self.assertTrue(self.companions[0].connected)
        self.assertEqual((await self.companions[0].team_rpc("status"))["result"]["teams"], [])

    async def test_reconnect_revokes_consent_and_never_resumes_battle(self):
        view = await self.invite()
        await self.accept(1, view)
        old = self.companions[1].session_epoch
        self.server.sessions[self.players[1].player_id].close("test_disconnect")
        await wait_until(lambda: self.companions[1].connected and self.companions[1].session_epoch != old)
        status = await self.rpc(1, "status", battle_id=view["battle_id"])
        self.assertEqual(status["state"], "aborted")
        self.assertEqual(status["consent"], [])
        self.assertEqual(await self.rpc(0, "pending"), [])

    async def test_possible_native_hold_is_not_released_by_remote_cancel(self):
        view = await self.invite()
        await self.accept(1, view)
        desk = self.server.battle_desk
        for i in (0, 1):
            desk.register(self.players[i].player_id, self.companions[i].session_epoch,
                view["battle_id"], view["generation"], 100 + i)
        desk.authorize_bind(self.players[0].player_id, self.companions[0].session_epoch,
                            view["battle_id"], view["generation"])
        canceled = await self.rpc(1, "cancel", battle_id=view["battle_id"], generation=view["generation"])
        self.assertEqual(canceled["state"], "aborting")
        self.assertIsNone(canceled["outcome"])
        self.assertIn(view["battle_id"], desk._active)
        self.assertEqual(await self.rpc(1, "pending"), [canceled])

    async def test_invalid_local_request_never_sends_and_checkpoint_heads_stay_exact(self):
        for fields in (dict(timeout=True), dict(timeout=float("nan")), dict(player_id=self.players[1].player_id)):
            with self.assertRaises(ValueError):
                await self.companions[0].battle_challenge_rpc("pending", **fields)
        with self.assertRaises(ValueError):
            await self.companions[0].battle_challenge_rpc("start")
        for i, p in enumerate(self.players):
            self.assertEqual(self.store.read_checkpoint(p.player_id, self.companions[i].session_epoch), self.heads[i])
