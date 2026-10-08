"""Real TLS admission for durable holds without a local native battle journal."""
import unittest
from unittest.mock import patch
from uuid import uuid4

from emerald_multiplayer.battle_desk import BattleDesk
from emerald_multiplayer.battle_reservations import enable_battle_reservations
from emerald_multiplayer.launcher_session import LauncherSessionError, SessionState
from emerald_multiplayer.protocol import ProtocolError
from emerald_multiplayer.server import WorldServer
import test_launcher_session as fixture


class LauncherBattleAdmissionTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixture.LauncherSessionTests.setUp
    asyncTearDown = fixture.LauncherSessionTests.asyncTearDown
    session = fixture.LauncherSessionTests.session
    friend = fixture.LauncherSessionTests.friend

    def reserve(self, store, leases):
        desk = BattleDesk(store, leases.get)
        first, second = self.host.accounts[:2]
        battle = str(uuid4())
        view = desk.invite(first.player_id, leases[first.player_id], second.player_id, battle)
        generation = view["generation"]
        desk.accept(second.player_id, leases[second.player_id], battle, generation, view["fingerprint"])
        for slot, player in enumerate((first, second)):
            desk.register(player.player_id, leases[player.player_id], battle, generation, 100+slot)
        desk.authorize_bind(first.player_id, leases[first.player_id], battle, generation)
        return desk.reservations.waiting(first.player_id, leases[first.player_id])

    def migrate(self):
        with self.host.open_store() as store:
            store.begin_server_boot()  # Close fixture leases before the explicit offline migration.
            enable_battle_reservations(store, self.root / "before-battle-reservations.sqlite3")

    async def test_restart_with_battles_disabled_blocks_both_players_without_local_journals(self):
        self.migrate()
        with self.host.open_store() as store:
            store.begin_server_boot()
            leases = {p.player_id: store.acquire_lease(p.player_id, p.credential) for p in self.host.accounts[:2]}
            waiting = self.reserve(store, leases)
        for restart in range(2):
            with self.subTest(restart=restart), patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec") as spawn:
                async with self.session().open() as host:
                    self.assertIsNone(host._server.battle_desk)
                    async with self.friend().open() as friend:
                        for session in (host, friend):
                            self.assertFalse((session.profile_directory / "pending-battle.json").exists())
                            self.assertEqual(session.status.state, SessionState.BLOCKED)
                            self.assertEqual(session.status.code, "pending_battle")
                            reply = await session._companion.battle_challenge_rpc("waiting")
                            self.assertEqual(reply["result"], waiting)
                            self.assertFalse(reply["result"][0]["resume_supported"])
                            with self.assertRaises(LauncherSessionError) as caught:
                                await session.play()
                            self.assertEqual(caught.exception.code, "pending_battle")
                            self.assertFalse((session.profile_directory / "character.sav").exists())
                        host._store.integrity_check()
                        self.assertEqual(host._store.read_checkpoint(
                            host._companion.config.player_id, host._companion.session_epoch).revision, 1)
                spawn.assert_not_called()

    async def test_empty_waiting_on_legacy_world_is_observational_without_migration(self):
        async with self.session().open() as session:
            self.assertFalse(session._store.battle_reservations_enabled)
            self.assertEqual(session.status.state, SessionState.READY)
            self.assertEqual((await session._companion.battle_challenge_rpc("waiting"))["result"], [])
            self.assertFalse(session._store.battle_reservations_enabled)
            self.assertFalse((session.profile_directory / "character.sav").exists())

    async def test_unavailable_waiting_capability_is_not_treated_as_an_empty_hold(self):
        original = WorldServer._battle_challenge
        def unavailable(server, actor, request):
            if request["type"] == "battle_waiting":
                raise ProtocolError("battle_disabled", "untrusted private host detail")
            return original(server, actor, request)
        with patch.object(WorldServer, "_battle_challenge", unavailable), \
                patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec") as spawn:
            async with self.session().open() as session:
                self.assertEqual(session.status.state, SessionState.BLOCKED)
                self.assertEqual(session.status.code, "battle_recovery_unavailable")
                with self.assertRaises(LauncherSessionError) as caught:
                    await session.play()
                self.assertEqual(caught.exception.code, "battle_recovery_unavailable")
                self.assertNotIn("private host", str(caught.exception))
                self.assertFalse((session.profile_directory / "character.sav").exists())
            spawn.assert_not_called()

    async def test_hold_created_after_ready_is_rechecked_before_runtime_recovery(self):
        self.migrate()
        with patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec") as spawn:
            async with self.session().open() as session:
                self.assertEqual(session.status.state, SessionState.READY)
                friend = self.host.accounts[1]
                friend_lease = session._store.acquire_lease(friend.player_id, friend.credential)
                leases = {session._companion.config.player_id: session._companion.session_epoch,
                          friend.player_id: friend_lease}
                self.reserve(session._store, leases)
                with self.assertRaises(LauncherSessionError) as caught:
                    await session.play()
                self.assertEqual(caught.exception.code, "pending_battle")
                self.assertFalse((session.profile_directory / "character.sav").exists())
            spawn.assert_not_called()
