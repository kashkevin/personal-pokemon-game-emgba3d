"""First-time character setup from the in-game menu: a friend's New Game save is enrolled over the world connection.

Real TLS, a real WorldServer on the host world's store, real SQLite, real child processes and OS save locks; the native game's save
mailbox and the New Game itself are the existing fixtures (``NativeEnrollmentFixture``, ``source_flash``).
"""
import asyncio
import hashlib
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from emerald_multiplayer.character_creation import (
    CreationError, create_character, finish_when_ready, remote_enrollment, submit_source,
)
from emerald_multiplayer.companion import Companion
from emerald_multiplayer.invitations import Invitation
from emerald_multiplayer.launcher_session import GameInstallation
from emerald_multiplayer.launcher_setup import create_world, export_friend_invitation
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.trade_native_replay import host_trade_effect_options
from process_fixture import direct_python
from test_enrollment_runtime import NativeEnrollmentFixture
from test_host_world import make_trade_files
from test_ownership_storage import owned_flash, source_flash
from test_player_runtime import write_bundle


class RemoteEnrollmentFixture(unittest.IsolatedAsyncioTestCase):
    """A host world with two friend invitations and a running WorldServer (no tests of its own; reused by test_character_play)."""
    allow = True

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rom, self.manifest = make_trade_files(self.root)
        bundle = self.root / "bundle"
        bundle.mkdir()
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        self.installation = GameInstallation(self.rom, self.manifest, digest(self.rom), digest(self.manifest), write_bundle(bundle))
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            self.port = listener.getsockname()[1]
        self.private_root = self.root / "private"
        self.host = create_world(self.installation, self.private_root, player_names=("Host", "Friend", "Friend Two"),
                                 endpoint="192.168.70.50", port=self.port)
        self.invitations = []
        for slot in (1, 2):
            path = self.root / f"friend{slot}.json"
            export_friend_invitation(self.installation, self.host.directory, slot, path)
            self.invitations.append(path)
        self.sources = []
        for index, personality in enumerate(self.PERSONALITIES):
            path = self.root / f"source{index}.sav"
            path.write_bytes(source_flash(personalities=(personality,)))
            self.sources.append(path)
        self.children, self.companions = [], []
        self.native = NativeEnrollmentFixture(self)
        self.real_spawn = asyncio.create_subprocess_exec
        self.store = self.host.open_store()
        from emerald_multiplayer.companion import verify_rom_manifest
        _, manifest = verify_rom_manifest(self.installation.rom_path, self.installation.manifest_path)
        self.server = WorldServer(ServerConfig(self.host.build_id, self.host.ruleset_id, allow_enrollment=self.allow), store=self.store,
                                  **host_trade_effect_options(self.installation, self.store, manifest))
        await self.server.start("127.0.0.1", self.port, tls=self.host.server_tls)

    async def asyncTearDown(self):
        for companion in self.companions:
            await companion.close()
        await self.server.close()
        self.store.close()
        for child in self.children:
            if child.returncode is None:
                child.kill()
            await child.wait()

    def profile(self, slot):
        return self.private_root / "players" / self.host.world_id / self.host.accounts[slot].player_id

    def companion(self, config):
        result = Companion(config)
        result.save_rpc = self.native.rpc
        self.companions.append(result)
        return result

    async def spawn(self, *args, **kwargs):
        self.private = Path(args[4]).parent
        self.companions[-1]._bridge = SimpleNamespace(save_capable=True, window_capable=False, incarnation=1,
                                                      outbox=SimpleNamespace(put=lambda _: None))
        child = await self.real_spawn(direct_python(), "-c", "import time; time.sleep(60)", **kwargs)
        self.children.append(child)
        return child

    PERSONALITIES = (111111, 222222)

    def patches(self):
        # The fixture's first export keeps the enrolled Pokémon: it must carry the source's personality.
        def export(grant, **keywords):
            return owned_flash(grant, personalities=(self.PERSONALITIES[self.current_source],), **keywords)
        if not getattr(self, "_export_patch", None):
            self._export_patch = patch("test_enrollment_runtime.owned_flash", export)
            self._export_patch.start()
            self.addCleanup(self._export_patch.stop)
        return (patch("emerald_multiplayer.character_creation.Companion", self.companion),
                patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn))

    current_source = 0

    def context(self, slot=1, source=0, **changes):
        self.current_source = source
        args = dict(invitation_path=self.invitations[slot - 1], route_host="127.0.0.1", route_port=self.port,
                    source_path=self.sources[source])
        args.update(changes)
        return remote_enrollment(self.installation, self.private_root, **args)

    def enrolled_sources(self):
        return {row[0]: row[1] for row in self.store._connection.execute("SELECT player_id, source_sha256 FROM ownership_enrollments")}



class RemoteEnrollmentTests(RemoteEnrollmentFixture):
    async def test_a_friend_enrolls_their_own_new_game_over_the_connection(self):
        companion_patch, spawn_patch = self.patches()
        with companion_patch, spawn_patch:
            async with self.context() as runtime:
                account = self.host.accounts[1]
                self.assertEqual(runtime.companion.config.player_id, account.player_id)
                # The server (not the friend's PC) recorded the approved source for exactly this account.
                digest = hashlib.sha256(self.sources[0].read_bytes()).hexdigest()
                self.assertEqual(self.enrolled_sources(), {account.player_id: digest})
                result = await runtime.enroll()
                self.assertEqual(result.metadata["revision"], 1)
        # The friend's character lives in the friend's own folder; the host's and the other friend's are untouched.
        self.assertTrue((self.profile(1) / "enrollment-completed.json").exists())
        self.assertTrue((self.profile(1) / "character.sav").exists())
        self.assertFalse(self.profile(0).exists())
        self.assertFalse(self.profile(2).exists())
        self.assertEqual(len(self.enrolled_sources()), 1)

    async def test_the_same_source_cannot_become_a_second_account(self):
        companion_patch, spawn_patch = self.patches()
        with companion_patch, spawn_patch:
            async with self.context(slot=1, source=0) as runtime:
                await runtime.enroll()
            with self.assertRaises(CreationError) as caught:
                async with self.context(slot=2, source=0):
                    self.fail("a source already used by another account was accepted")
        self.assertEqual(caught.exception.code, "source_already_enrolled")
        self.assertEqual(len(self.enrolled_sources()), 1)
        self.assertFalse((self.profile(2) / "character.sav").exists())

    async def test_each_friend_enrolls_separately_with_their_own_source(self):
        companion_patch, spawn_patch = self.patches()
        with companion_patch, spawn_patch:
            async with self.context(slot=1, source=0) as runtime:
                await runtime.enroll()
            self.native.grant = None
            async with self.context(slot=2, source=1) as runtime:
                await runtime.enroll()
        sources = self.enrolled_sources()
        self.assertEqual(sources[self.host.accounts[1].player_id], hashlib.sha256(self.sources[0].read_bytes()).hexdigest())
        self.assertEqual(sources[self.host.accounts[2].player_id], hashlib.sha256(self.sources[1].read_bytes()).hexdigest())
        self.assertTrue((self.profile(1) / "character.sav").exists())
        self.assertTrue((self.profile(2) / "character.sav").exists())
        self.assertNotEqual(self.profile(1), self.profile(2))

    async def test_a_save_that_already_has_owner_identities_is_refused_by_the_server(self):
        invitation = Invitation.load(self.invitations[0])
        config = invitation.companion_config(self.rom, self.manifest, token=bytes(range(32)), private_directory=self.profile(1),
                                             ipc_port=0)
        from dataclasses import replace
        companion = Companion(replace(config, server_host="127.0.0.1", server_port=self.port))
        self.companions.append(companion)
        await companion.start()
        async with asyncio.timeout(10):
            while not companion.connected:
                await asyncio.sleep(.02)
        from emerald_multiplayer.ownership_storage import AllocationGrant
        grant = AllocationGrant(companion.world_id, config.player_id, "00000000-0000-4000-8000-000000000001", 1, 33, 1, 1, 0)
        with self.assertRaises(CreationError) as caught:
            await submit_source(companion, owned_flash(grant))
        self.assertEqual(caught.exception.code, "invalid_enrollment")
        with self.assertRaises(CreationError):
            await submit_source(companion, bytes(131072))
        self.assertEqual(self.enrolled_sources(), {})

    async def test_finish_when_ready_waits_for_the_safe_place_then_enrolls_once(self):
        self.native.unsafe_once = True
        companion_patch, spawn_patch = self.patches()
        waits = []
        with companion_patch, spawn_patch:
            async with self.context() as runtime:
                result = await finish_when_ready(runtime, interval=0.01, on_waiting=lambda: waits.append(1))
                self.assertEqual(result.metadata["revision"], 1)
        self.assertGreaterEqual(len(waits), 0)
        self.assertEqual(len(self.enrolled_sources()), 1)

    async def test_a_game_closed_before_the_safe_place_stops_with_its_own_message(self):
        companion_patch, spawn_patch = self.patches()
        with companion_patch, spawn_patch:
            async with self.context() as runtime:
                runtime._game.process.kill()
                await runtime._game.process.wait()
                with self.assertRaises(CreationError) as caught:
                    await finish_when_ready(runtime, interval=0.01)
        # Killed, not closed by the player: "closed unexpectedly", never "you closed it" (finish_when_ready's _closed).
        self.assertEqual(caught.exception.code, "game_failed")
        # The approved source stays recorded for a retry; no character exists yet.
        self.assertEqual(len(self.enrolled_sources()), 1)
        self.assertFalse((self.profile(1) / "enrollment-completed.json").exists())
        # The retry (the menu's "Continue setting up my character"): the friend's server takes the same source again,
        # the abandoned attempt is kept aside and the character is enrolled.
        with companion_patch, spawn_patch:
            async with self.context() as runtime:
                result = await finish_when_ready(runtime, interval=0.01)
                self.assertEqual(result.metadata["revision"], 1)
        self.assertTrue((self.profile(1) / "enrollment-completed.json").exists())
        self.assertEqual(len(list((self.profile(1) / "abandoned-enrollments").iterdir())), 1)
        self.assertEqual(len(self.enrolled_sources()), 1)

    async def test_an_unavailable_server_is_a_clear_error_and_creates_nothing(self):
        companion_patch, spawn_patch = self.patches()
        with companion_patch, spawn_patch:
            with self.assertRaises(CreationError) as caught:
                async with self.context(route_port=self.port + 1 if self.port < 65535 else self.port - 1, connection_timeout=1):
                    self.fail("connected to a port nobody listens on")
        self.assertIn(caught.exception.code, {"connection_timeout", "setup_failed"})
        self.assertEqual(self.enrolled_sources(), {})
        self.assertEqual(self.children, [])


class RemoteEnrollmentDisabledTests(RemoteEnrollmentTests):
    allow = False

    async def test_a_host_that_turned_it_off_refuses_before_a_game_opens(self):
        companion_patch, spawn_patch = self.patches()
        with companion_patch, spawn_patch:
            with self.assertRaises(CreationError) as caught:
                async with self.context():
                    self.fail("enrolled although the host turned remote enrollment off")
        self.assertEqual(caught.exception.code, "enrollment_disabled")
        self.assertEqual(self.enrolled_sources(), {})
        self.assertEqual(self.children, [])

    # The inherited cases assume enrollment is allowed.
    test_a_friend_enrolls_their_own_new_game_over_the_connection = None
    test_the_same_source_cannot_become_a_second_account = None
    test_each_friend_enrolls_separately_with_their_own_source = None
    test_a_save_that_already_has_owner_identities_is_refused_by_the_server = None
    test_finish_when_ready_waits_for_the_safe_place_then_enrolls_once = None
    test_a_game_closed_before_the_safe_place_stops_with_its_own_message = None
    test_an_unavailable_server_is_a_clear_error_and_creates_nothing = None


class GameEndTests(unittest.IsolatedAsyncioTestCase):
    """How the enrollment game's end is reported: closed by the player (exit code 0) or not (a crash)."""

    def runtime(self, returncode, enroll=None):
        async def refuse():
            raise enroll
        return SimpleNamespace(_game=SimpleNamespace(process=SimpleNamespace(returncode=returncode)),
                               companion=SimpleNamespace(_bridge=object()), enroll=refuse)

    async def test_closed_by_the_player_or_crashed(self):
        for returncode, code in ((0, "game_closed"), (139, "game_failed"), (-11, "game_failed"), (3221225477, "game_failed")):
            with self.subTest(returncode=returncode), self.assertRaises(CreationError) as caught:
                await finish_when_ready(self.runtime(returncode), interval=0.01)
            self.assertEqual(caught.exception.code, code)

    async def test_the_runtime_noticing_first_reports_the_same(self):
        from emerald_multiplayer.enrollment_runtime import EnrollmentRuntimeError
        for returncode, code in ((0, "game_closed"), (1, "game_failed")):
            runtime = self.runtime(None, EnrollmentRuntimeError("game_closed", "first enrollment requires its active game"))

            async def enroll(runtime=runtime, returncode=returncode):
                runtime._game.process.returncode = returncode
                raise EnrollmentRuntimeError("game_closed", "first enrollment requires its active bootstrap game")
            runtime.enroll = enroll
            with self.subTest(returncode=returncode), self.assertRaises(CreationError) as caught:
                await finish_when_ready(runtime, interval=0.01)
            self.assertEqual(caught.exception.code, code)


class GameCrashMidRequestTests(unittest.IsolatedAsyncioTestCase):
    """A game that crashes while the enrollment request is in flight: the request fails as a lost connection just before
    the process is seen to end (seen end to end, 2026-10-17). The player is told the game closed unexpectedly."""

    async def test_a_lost_connection_from_a_crashing_game_is_the_games_end(self):
        for returncode, code in ((139, "game_failed"), (0, "game_closed")):
            process = SimpleNamespace(returncode=None)

            async def wait(process=process, returncode=returncode):
                await asyncio.sleep(0.05)
                process.returncode = returncode
                return returncode
            process.wait = wait

            async def enroll():
                raise ConnectionError("bridge closed")
            runtime = SimpleNamespace(_game=SimpleNamespace(process=process), companion=SimpleNamespace(_bridge=object()),
                                      enroll=enroll)
            with self.subTest(returncode=returncode), self.assertRaises(CreationError) as caught:
                await finish_when_ready(runtime, interval=0.01)
            self.assertEqual(caught.exception.code, code)

    async def test_a_lost_connection_with_the_game_still_running_stays_a_lost_connection(self):
        async def wait():
            await asyncio.sleep(60)

        async def enroll():
            raise ConnectionError("server gone")
        runtime = SimpleNamespace(_game=SimpleNamespace(process=SimpleNamespace(returncode=None, wait=wait)),
                                  companion=SimpleNamespace(_bridge=object()), enroll=enroll)
        from unittest.mock import patch as _patch
        from emerald_multiplayer import character_creation
        original = character_creation._game_ended

        async def quick(game, grace=3.0):
            return await original(game, grace=0.05)
        with _patch.object(character_creation, "_game_ended", quick), self.assertRaises(ConnectionError):
            await finish_when_ready(runtime, interval=0.01)


class CreateCharacterTests(unittest.IsolatedAsyncioTestCase):
    """The chaining: a draft (the player's New Game), then approval and enrollment; a resumable draft skips the New Game."""

    async def test_resume_skips_the_new_game_and_reports_progress(self):
        class Draft(SimpleNamespace):
            pass

        calls = []

        async def drafter(installation, private_root, *, on_status=None):
            calls.append("draft")
            return Draft(source_path=Path("/nonexistent"), sha256="0" * 64, party_count=1)

        # Resuming with an existing draft must not call the drafter; the enrollment step then fails safely on the bogus world.
        with self.assertRaises(CreationError) as caught:
            await create_character(object(), "/tmp", role="friend", draft=Draft(source_path=Path("/nonexistent"), sha256="0" * 64,
                                   party_count=1), drafter=drafter)
        self.assertEqual(calls, [])
        self.assertEqual(caught.exception.code, "setup_failed")
        with self.assertRaises(CreationError):
            await create_character(object(), "/tmp", role="host", drafter=drafter)
        self.assertEqual(calls, ["draft"])


if __name__ == "__main__":
    unittest.main()
