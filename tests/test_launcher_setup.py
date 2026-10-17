"""Host setup through real TLS/storage and children; native export is a fixture."""
import asyncio
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from emerald_multiplayer.checkpoint_client import CheckpointClient
from emerald_multiplayer.checkpoint_mirror import MirrorError, MirrorLease
from emerald_multiplayer.companion import Companion
from emerald_multiplayer.host_world import HostWorld
from emerald_multiplayer.invitations import Invitation
from emerald_multiplayer.launcher_session import GameInstallation
from emerald_multiplayer.launcher_setup import (
    LauncherSetupError, create_world, export_friend_invitation, host_enrollment,
)
from emerald_multiplayer.server import ServerConfig, WorldServer
from process_fixture import direct_python
from test_enrollment_runtime import NativeEnrollmentFixture
from test_host_world import make_trade_files
from test_ownership_storage import source_flash
from test_player_runtime import write_bundle


class LauncherSetupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rom, self.manifest = make_trade_files(self.root)
        bundle = self.root / "bundle"
        bundle.mkdir()
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        self.installation = GameInstallation(self.rom, self.manifest, digest(self.rom),
                                             digest(self.manifest), write_bundle(bundle))
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            self.port = listener.getsockname()[1]
        self.host = create_world(self.installation, self.root / "private",
            player_names=("Host", "Friend"), endpoint="192.168.70.50", port=self.port)
        self.source = self.root / "original.sav"
        self.original = source_flash()
        self.source.write_bytes(self.original)
        self.states, self.children, self.companions = [], [], []
        self.native = NativeEnrollmentFixture(self)
        self.real_spawn = asyncio.create_subprocess_exec
        self.spawned = asyncio.Event()

    async def asyncTearDown(self):
        for child in self.children:
            if child.returncode is None:
                child.kill()
            await child.wait()

    def profile(self, slot=0):
        return self.root / "private" / "players" / self.host.world_id / self.host.accounts[slot].player_id

    def context(self, **changes):
        args = dict(world_directory=self.host.directory, slot=0, source_path=self.source,
                    bind_address="127.0.0.1", on_status=self.states.append)
        args.update(changes)
        return host_enrollment(self.installation, self.root / "private", **args)

    def companion(self, config):
        result = Companion(config)
        result.save_rpc = self.native.rpc
        self.companions.append(result)
        return result

    async def spawn(self, *args, **kwargs):
        self.private = Path(args[4]).parent
        self.assertEqual(Path(args[4]).read_bytes(), self.original)
        self.assertEqual(kwargs["cwd"].parent, (self.root / "private" / "launches").resolve())
        self.assertEqual(Path(args[2]).parent, kwargs["cwd"])
        with self.assertRaises(MirrorError):
            with MirrorLease(args[4]):
                self.fail("bootstrap spawn lost its private save lease")
        self.companions[-1]._bridge = SimpleNamespace(save_capable=True, window_capable=False,
            incarnation=1, outbox=SimpleNamespace(put=lambda _: None))
        child = await self.real_spawn(direct_python(), "-c", "import time; time.sleep(60)", **kwargs)
        self.children.append(child)
        self.spawned.set()
        return child

    def fixture(self):
        return (patch("emerald_multiplayer.launcher_setup.Companion", self.companion),
                patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn))

    async def test_changed_gui_selected_source_refuses_before_approval_or_child(self):
        selected_sha256 = hashlib.sha256(self.original).hexdigest()
        self.source.write_bytes(source_flash(personalities=(887766,)))
        with self.assertRaises(LauncherSetupError) as caught:
            async with self.context(expected_source_sha256=selected_sha256):
                self.fail("changed character must not be approved or opened")
        self.assertEqual(caught.exception.code, "source_changed")
        self.assertFalse(self.children)
        self.assertFalse(self.companions)
        with self.host.open_store() as store:
            self.assertEqual(store._connection.execute("SELECT COUNT(*) FROM ownership_enrollments").fetchone()[0], 0)
        self.assertFalse((self.profile() / "pending-enrollment.json").exists())

    async def test_creation_uses_private_unique_worlds_without_boot_or_listener(self):
        second = create_world(self.installation, self.root / "private",
            player_names=("Second",), endpoint="127.0.0.1", port=self.port)
        self.assertNotEqual(second.directory, self.host.directory)
        self.assertEqual(second.directory.parent, self.root / "private" / "worlds")
        with second.open_store() as store:
            self.assertEqual(store.metadata.server_epoch, 0)
            self.assertEqual(store._connection.execute("SELECT count(*) FROM ownership_enrollments").fetchone()[0], 0)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", self.port))

    async def test_installation_change_precedes_any_new_world_or_source_mutation(self):
        self.rom.write_bytes(b"changed")
        before = tuple((self.root / "private" / "worlds").iterdir())
        with self.assertRaises(LauncherSetupError) as caught:
            create_world(self.installation, self.root / "private",
                         player_names=("Host",), endpoint="127.0.0.1", port=self.port)
        self.assertEqual(caught.exception.code, "installation_changed")
        self.assertEqual(tuple((self.root / "private" / "worlds").iterdir()), before)
        with self.assertRaises(LauncherSetupError):
            async with self.context():
                self.fail("changed installation entered bootstrap")
        self.assertEqual(self.source.read_bytes(), self.original)

    async def test_invitation_save_as_is_friend_only_and_never_overwrites(self):
        destination = self.root / "friend.json"
        self.assertEqual(export_friend_invitation(self.installation, self.host.directory, 1, destination), destination)
        invitation = Invitation.load(destination)
        self.assertEqual(invitation.player_id, self.host.accounts[1].player_id)
        self.assertEqual(invitation.endpoint, self.host.endpoint)
        original = destination.read_bytes()
        with self.assertRaises(LauncherSetupError) as caught:
            export_friend_invitation(self.installation, self.host.directory, 1, destination)
        self.assertEqual(caught.exception.code, "invitation_exists")
        for slot in (0, 2, True):
            with self.assertRaises(LauncherSetupError):
                export_friend_invitation(self.installation, self.host.directory, slot, self.root / "invalid.json")
        self.assertEqual(destination.read_bytes(), original)
        self.assertFalse((self.root / "invalid.json").exists())

    async def test_missing_source_or_invalid_configuration_does_not_boot_or_approve(self):
        for args, code in ((dict(source_path=None), "source_required"),
                           (dict(slot=3), "invalid_profile"),
                           (dict(slot=True), "invalid_configuration"),
                           (dict(host_route="8.8.8.8"), "invalid_configuration")):
            with self.assertRaises(LauncherSetupError) as caught:
                async with self.context(**args):
                    self.fail("invalid setup entered bootstrap")
            self.assertEqual(caught.exception.code, code)
        with self.host.open_store() as store:
            self.assertEqual(store.metadata.server_epoch, 0)
            self.assertEqual(store._connection.execute("SELECT count(*) FROM ownership_enrollments").fetchone()[0], 0)
        self.assertEqual(self.children, [])

    async def test_oversized_character_path_refuses_before_host_boot_and_source_approval(self):
        private = self.root / ("a" * 100) / ("b" * 100)
        with patch("emerald_multiplayer.player_runtime._WINDOWS_NATIVE_PATHS", True):
            with self.assertRaises(LauncherSetupError) as caught:
                async with host_enrollment(self.installation, private,
                        world_directory=self.host.directory, slot=0, source_path=self.source,
                        on_status=self.states.append):
                    self.fail("unsupported save path reached source approval")
        self.assertEqual(caught.exception.code, "runtime_path")
        self.assertEqual(self.states[-1].code, "runtime_path")
        self.assertFalse(private.exists())
        with self.host.open_store() as store:
            self.assertEqual(store.metadata.server_epoch, 0)
            self.assertEqual(store._connection.execute("SELECT count(*) FROM ownership_enrollments").fetchone()[0], 0)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(self.children, [])

    async def test_live_tls_explicit_enrollment_closes_child_before_transport(self):
        descriptor = (self.host.directory / "host.json").read_bytes()
        companion_patch, spawn_patch = self.fixture()
        with companion_patch, spawn_patch:
            async with self.context() as runtime:
                c = runtime.companion
                self.assertEqual(c.config.player_id, self.host.accounts[0].player_id)
                self.assertEqual(c.config.server_host, "127.0.0.1")
                self.assertEqual(c.config.server_tls.certificate_sha256, self.host.certificate_sha256)
                c.config.server_tls.verify_peer(c._remote_writer)
                self.assertIsNone(await CheckpointClient(c).info())
                result = await runtime.enroll()
                self.assertEqual(result.metadata["revision"], 1)
                self.assertTrue(c.connected)
                self.assertIsNotNone(self.children[0].returncode)
                with self.assertRaises(MirrorError):
                    with MirrorLease(runtime.save_path):
                        self.fail("setup released save before context closure")
        self.assertFalse(c.connected)
        self.assertEqual(self.states[-1].code, "enrolled")
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual((self.host.directory / "host.json").read_bytes(), descriptor)
        with self.host.open_store() as store:
            store.integrity_check()
            self.assertEqual(store._connection.execute("SELECT count(*) FROM checkpoints").fetchone()[0], 1)
        public = json.dumps([asdict(s) for s in self.states])
        for account in self.host.accounts:
            self.assertNotIn(account.credential.hex(), public)
        self.assertNotIn(str(self.source), public)
        with MirrorLease(runtime.save_path):
            pass

    async def test_host_can_explicitly_prepare_provisioned_friend_under_its_own_identity(self):
        companion_patch, spawn_patch = self.fixture()
        with companion_patch, spawn_patch:
            async with self.context(slot=1) as runtime:
                self.assertEqual(runtime.companion.config.player_id, self.host.accounts[1].player_id)
                self.assertEqual(runtime.directory, self.profile(1))
                self.assertEqual(runtime.approval.player_id, self.host.accounts[1].player_id)
                await runtime.enroll()
        self.assertFalse(self.profile(0).exists())
        self.assertEqual(self.source.read_bytes(), self.original)

    async def test_running_host_prevents_approval_without_fencing_its_lease(self):
        with self.host.open_store() as store:
            server = WorldServer(ServerConfig(self.host.build_id, self.host.ruleset_id), store=store)
            # Different port exercises the store owner lock, not just bind failure.
            await server.start("127.0.0.1", 0, tls=self.host.server_tls)
            try:
                before = store.metadata
                with self.assertRaises(LauncherSetupError) as caught:
                    async with self.context():
                        self.fail("second host entered bootstrap")
                self.assertEqual(caught.exception.code, "world_active")
                self.assertEqual(store.metadata, before)
                self.assertEqual(store._connection.execute("SELECT count(*) FROM ownership_enrollments").fetchone()[0], 0)
            finally:
                await server.close()

    async def test_uncertain_journal_preserved_and_no_child_started(self):
        private = self.profile()
        private.mkdir(parents=True)
        pending = private / "pending-enrollment.json"
        pending.write_bytes(b"uncertain")
        with self.assertRaises(LauncherSetupError) as caught:
            async with self.context():
                self.fail("pending enrollment entered bootstrap")
        self.assertEqual(caught.exception.code, "recovery_required")
        self.assertEqual(pending.read_bytes(), b"uncertain")
        self.assertFalse((private / "character.sav").exists())
        self.assertEqual(self.children, [])

    async def test_cancellation_drains_child_before_network_and_releases_save(self):
        entered = asyncio.Event()
        async def run():
            async with self.context():
                entered.set()
                await asyncio.Future()
        companion_patch, spawn_patch = self.fixture()
        with companion_patch, spawn_patch:
            task = asyncio.create_task(run())
            await asyncio.wait_for(entered.wait(), 10)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertIsNotNone(self.children[0].returncode)
        self.assertFalse(self.companions[0].connected)
        self.assertTrue((self.profile() / "pending-enrollment.json").exists())
        self.assertEqual(self.source.read_bytes(), self.original)
        with MirrorLease(self.profile() / "character.sav"):
            pass
        with self.host.open_store() as store:
            store.begin_server_boot()

    async def test_the_games_end_keeps_its_own_code_through_setup(self):
        """A crash of the enrollment game is reported as such, not flattened to setup_failed (the owner's report,
        2026-10-17: "Setting up your character could not finish" for a game that had crashed)."""
        from emerald_multiplayer.character_creation import CreationError
        for code in ("game_failed", "game_closed"):
            companion_patch, spawn_patch = self.fixture()
            with companion_patch, spawn_patch, self.subTest(code=code):
                with self.assertRaises(LauncherSetupError) as caught:
                    async with self.context(restart_abandoned=True):
                        raise CreationError(code)
                self.assertEqual(caught.exception.code, code)

    async def abandon(self):
        """One attempt whose game ends before the safe place (the body leaves without enrolling)."""
        from emerald_multiplayer.character_creation import CreationError
        companion_patch, spawn_patch = self.fixture()
        with companion_patch, spawn_patch:
            with self.assertRaises(LauncherSetupError):
                async with self.context():
                    raise CreationError("game_failed")
        self.assertTrue((self.profile() / "pending-enrollment.json").exists())
        return {p.name: p.read_bytes() for p in self.profile().iterdir()
                if p.is_file() and p.name != "character.sav.mirror.lock"}

    async def test_an_abandoned_attempt_restarts_when_asked_and_its_files_are_kept(self):
        before = await self.abandon()
        # Not asked (the launcher's explicit setup): unchanged, the attempt waits for recovery.
        with self.assertRaises(LauncherSetupError) as caught:
            async with self.context():
                self.fail("restarted without being asked")
        self.assertEqual(caught.exception.code, "recovery_required")
        # Asked (the in-game menu's "Continue setting up my character"): set aside, then a whole new enrollment.
        companion_patch, spawn_patch = self.fixture()
        with companion_patch, spawn_patch:
            async with self.context(restart_abandoned=True) as runtime:
                result = await runtime.enroll()
                self.assertEqual(result.metadata["revision"], 1)
        self.assertEqual(self.states[-1].code, "enrolled")
        self.assertFalse((self.profile() / "pending-enrollment.json").exists())
        self.assertTrue((self.profile() / "enrollment-completed.json").exists())
        kept = list((self.profile() / "abandoned-enrollments").iterdir())
        self.assertEqual(len(kept), 1)
        self.assertEqual({p.name: p.read_bytes() for p in kept[0].iterdir()},
                         {name: data for name, data in before.items() if not name.startswith("host-")})
        self.assertEqual(self.source.read_bytes(), self.original)
        with self.host.open_store() as store:
            self.assertEqual(store._connection.execute("SELECT count(*) FROM checkpoints").fetchone()[0], 1)

    async def test_an_attempt_that_went_further_is_never_restarted(self):
        await self.abandon()
        for name, data in (("0" * 8 + "-0000-4000-8000-" + "0" * 12 + ".grant.json", b"{}"),
                           ("pending-export.json", b"{}"), ("unknown.bin", b"?")):
            extra = self.profile() / name
            extra.write_bytes(data)
            listing = sorted(p.name for p in self.profile().iterdir())
            companion_patch, spawn_patch = self.fixture()
            with companion_patch, spawn_patch, self.subTest(extra=name):
                with self.assertRaises(LauncherSetupError) as caught:
                    async with self.context(restart_abandoned=True):
                        self.fail("restarted an attempt that went further")
                self.assertEqual(caught.exception.code, "recovery_required")
                self.assertEqual(sorted(p.name for p in self.profile().iterdir()), listing)
                self.assertFalse((self.profile() / "abandoned-enrollments").exists())
            extra.unlink()
        # Another source's intent is not this attempt either.
        pending = self.profile() / "pending-enrollment.json"
        original = pending.read_bytes()
        pending.write_bytes(original.replace(original[-20:-4], b"0" * 16))
        with self.assertRaises(LauncherSetupError) as caught:
            async with self.context(restart_abandoned=True):
                self.fail("restarted a different attempt")
        self.assertEqual(caught.exception.code, "recovery_required")
        self.assertFalse((self.profile() / "abandoned-enrollments").exists())

    async def test_observer_and_context_errors_cannot_disclose_private_details(self):
        secret = self.host.accounts[0].credential.hex()
        def observer(status):
            self.states.append(status)
            raise RuntimeError(secret)
        companion_patch, spawn_patch = self.fixture()
        with companion_patch, spawn_patch:
            with self.assertRaises(LauncherSetupError) as caught:
                async with self.context(on_status=observer):
                    raise RuntimeError(secret)
        self.assertEqual(caught.exception.code, "setup_failed")
        self.assertNotIn(secret, str(caught.exception))
        self.assertNotIn(secret, repr(self.states))
        self.assertIsNotNone(self.children[0].returncode)
        self.assertFalse(self.companions[0].connected)
