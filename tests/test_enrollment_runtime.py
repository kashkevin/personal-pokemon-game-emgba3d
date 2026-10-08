"""Real TLS/store/child/OS-lock lifecycle; native mailbox is a strict fixture.

Fixture-created encrypted Flash simulates the ROM's first export. These tests
do not claim native gameplay or Windows input acceptance.
"""
import asyncio
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import secrets
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4
import zlib

from emerald_multiplayer.checkpoint_client import CheckpointClient
from emerald_multiplayer.checkpoint_mirror import MirrorError, MirrorLease
from emerald_multiplayer.cold_start import ColdStartError
from emerald_multiplayer.companion import Companion
from emerald_multiplayer.enrollment_runtime import (
    EnrollmentRuntime, EnrollmentRuntimeError, approve_enrollment_source,
)
from emerald_multiplayer.flash import inspect_flash
from emerald_multiplayer.host_world import HostWorld
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE, inspect_ownership
from emerald_multiplayer.ownership_storage import AllocationGrant
from emerald_multiplayer.player_runtime import PlayerRuntime, PlayerRuntimeError
from emerald_multiplayer.save_mailbox import Opcode, SaveControl, Status, SAVE_CHUNK_SIZE
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.storage import StorageError
from process_fixture import direct_python
from test_host_world import make_trade_files
from test_ownership_client import status
from test_ownership_storage import source_flash, owned_flash
from test_player_runtime import write_bundle


class NativeEnrollmentFixture:
    def __init__(self, test):
        self.test = test
        self.grant = None
        self.payload = None
        self.commands = []
        self.hook = None
        self.unsafe_once = False
        self.lose_end = False

    def ownership_status(self):
        if self.grant is None:
            return status(missing=1)
        g = self.grant
        return status(flags=3, missing=1, remaining=g.end_exclusive-g.start,
                      world=g.world_id, player=g.player_id, grant=g.grant_id,
                      next_id=g.start, end=g.end_exclusive, lease=g.lease_epoch, incarnation=g.incarnation)

    async def rpc(self, control, **options):
        control = SaveControl.unpack(control.pack()).validate_command()
        self.commands.append(control.opcode)
        if self.hook:
            await self.hook(control)
        data, status_code = b"", Status.OK
        if self.unsafe_once and control.opcode == Opcode.BIND:
            self.unsafe_once = False
            status_code = Status.UNSAFE
        elif control.opcode == Opcode.BIND:
            pass
        elif control.opcode == Opcode.QUERY_OWNERSHIP:
            data = self.ownership_status()
        elif control.opcode == Opcode.GRANT_OWNERSHIP:
            world, player, grant, start, end, enroll = struct.unpack("<16s16s16sIII", control.data)
            self.test.assertEqual(enroll, 1)
            self.grant = AllocationGrant(str(UUID(bytes=world)), str(UUID(bytes=player)),
                str(UUID(bytes=grant)), start, end, control.session_epoch, control.incarnation, 0)
            # Existing coordinator must journal the acknowledged grant before
            # the native endpoint can observe it.
            self.test.assertTrue((self.test.private / (self.grant.grant_id + ".grant.json")).exists())
            data = self.ownership_status()
        elif control.opcode == Opcode.BEGIN_EXPORT:
            self.payload = owned_flash(self.grant, next_serial=self.grant.start+1)
            parsed = inspect_flash(self.payload, save_profile=OWNERSHIP_PROFILE)
            sector = struct.unpack_from("<H", self.payload, parsed.metadata.bank*14*4096+4084)[0]
            data = struct.pack("<II", parsed.metadata.counter, (-sector) % 14) + bytes(32)
        elif control.opcode == Opcode.READ:
            data = self.payload[control.offset:control.offset+SAVE_CHUNK_SIZE]
        elif control.opcode == Opcode.END:
            if self.lose_end:
                self.lose_end = False
                raise asyncio.TimeoutError("fixture lost native END")
            data = struct.pack("<I", zlib.crc32(self.payload))
        elif control.opcode == Opcode.CANCEL:
            status_code = Status.CANCELED
        else:
            raise AssertionError(control.opcode)
        return SaveControl.unpack(replace(control, data=data, status=status_code).pack()).validate_response()


class EnrollmentRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.rom, self.manifest = make_trade_files(self.root)
        self.host = HostWorld.create(self.root / "host", self.rom, self.manifest,
            player_names=["Host", "Friend"], endpoint="127.0.0.1", port=8765)
        self.store = self.host.open_store()
        self.source = self.root / "original.sav"
        self.original = source_flash()
        self.source.write_bytes(self.original)
        self.player = self.host.accounts[0]
        self.approval = approve_enrollment_source(self.store, self.player.player_id, self.source)
        self.server = WorldServer(ServerConfig(self.host.build_id, self.host.ruleset_id), store=self.store)
        await self.server.start(port=0, tls=self.host.server_tls)
        self.private = self.root / "private"
        config = self.host.host_companion_config(self.rom, self.manifest,
            token=secrets.token_bytes(32), private_directory=self.root / "trust")
        self.c = Companion(replace(config, server_port=self.server.address[1]))
        await self.c.start()
        for _ in range(500):
            if self.c.connected:
                break
            await asyncio.sleep(.01)
        self.assertTrue(self.c.connected)
        bundle = self.root / "bundle"
        bundle.mkdir()
        self.bundle = write_bundle(bundle)
        self.save = self.private / "character.sav"
        self.children, self.calls = [], []
        self.real_spawn = asyncio.create_subprocess_exec
        self.spawned = asyncio.Event()
        self.native = NativeEnrollmentFixture(self)
        self.save_patch = patch.object(self.c, "save_rpc", self.native.rpc)
        self.save_patch.start()

    async def asyncTearDown(self):
        for child in self.children:
            if child.returncode is None:
                child.kill()
            await child.wait()
        self.c._bridge = None
        await self.c.close()
        await self.server.close()
        self.store.close()
        self.save_patch.stop()
        self.temporary.cleanup()

    def runtime(self, approval=None, directory=None):
        private = directory or self.private
        return EnrollmentRuntime(self.c, self.bundle, private, private / "character.sav", approval or self.approval)

    async def spawn(self, *args, **kwargs):
        save = Path(args[4])
        self.calls.append((args, kwargs))
        self.assertNotIn("shell", kwargs)
        with self.assertRaises(MirrorError):
            with MirrorLease(save):
                self.fail("native creation lost its save lease")
        head = self.store.read_checkpoint(self.player.player_id, self.c.session_epoch)
        self.assertEqual(save.read_bytes(), self.original if head is None else head.payload)
        child = await self.real_spawn(direct_python(), "-c", "import time; time.sleep(60)", **kwargs)
        self.children.append(child)
        self.c._bridge = SimpleNamespace(save_capable=True, window_capable=False, incarnation=1)
        self.spawned.set()
        return child

    def assert_original(self):
        self.assertEqual(self.source.read_bytes(), self.original)
        self.store.integrity_check()

    async def test_tls_native_export_establishes_revision_one_then_normal_recovery_is_required(self):
        self.assertIsNone(await CheckpointClient(self.c).info())
        runtime = self.runtime()
        with patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn):
            async with runtime.open() as game:
                self.assertEqual(self.save.read_bytes(), self.original)
                result = await runtime.enroll()
                self.assertEqual(result.metadata["revision"], 1)
                self.assertIsNotNone(game.process.returncode)
                with self.assertRaises(MirrorError):
                    with MirrorLease(self.save):
                        self.fail("bootstrap context released the lease early")
            self.c._bridge = None
            self.assertFalse(runtime.pending_path.exists())
            self.assertTrue(runtime.source_copy.exists())
            self.assertTrue(runtime.receipt_path.exists())
            # The bootstrap copy is not blessed as canonical. Normal startup
            # must install the actual owned checkpoint under ColdStartRecovery.
            self.assertEqual(self.save.read_bytes(), self.original)
            async with PlayerRuntime(self.c, self.bundle, self.private, self.save).open() as game:
                self.assertEqual(game.startup.mirror.revision, 1)
                owner = inspect_ownership(inspect_flash(self.save.read_bytes(), save_profile=OWNERSHIP_PROFILE))
                self.assertEqual(owner.player_id, self.player.player_id)
        self.c._bridge = None
        self.assert_original()
        self.assertEqual(self.store._connection.execute("SELECT COUNT(*) FROM ownership_grants").fetchone()[0], 1)

    async def test_approval_preserves_original_and_duplicate_or_owned_sources_are_refused(self):
        self.assertIsNone(await CheckpointClient(self.c).info())
        with self.assertRaises(StorageError) as caught:
            approve_enrollment_source(self.store, self.host.accounts[1].player_id, self.source)
        self.assertEqual(caught.exception.code, "source_already_enrolled")
        self.source.write_bytes(b"invalid")
        with self.assertRaises(ValueError):
            approve_enrollment_source(self.store, self.player.player_id, self.source)
        self.source.write_bytes(self.original)
        self.assert_original()

    async def test_changed_original_or_foreign_approval_never_copies_or_spawns(self):
        for approval in (replace(self.approval, world_id=str(uuid4())),
                         replace(self.approval, player_id=self.host.accounts[1].player_id),
                         replace(self.approval, build_id="0"*64)):
            with self.assertRaises(EnrollmentRuntimeError):
                async with self.runtime(approval).open():
                    self.fail("foreign approval yielded")
        self.source.write_bytes(source_flash(personalities=(8,)))
        with self.assertRaises(EnrollmentRuntimeError) as caught:
            async with self.runtime().open():
                self.fail("changed source yielded")
        self.assertEqual(caught.exception.code, "source_changed")
        self.assertFalse(self.save.exists())
        self.assertEqual(self.calls, [])

    async def test_existing_canonical_head_refuses_bootstrap_in_an_empty_profile(self):
        grant = self.store.reserve_instances(self.player.player_id, self.c.session_epoch, str(uuid4()), 0, 1, 32)
        payload = owned_flash(grant)
        self.store.commit_checkpoint(self.player.player_id, self.c.session_epoch, str(uuid4()), 0,
            payload, self.host.build_id, self.host.ruleset_id, OWNERSHIP_PROFILE)
        with self.assertRaises(EnrollmentRuntimeError) as caught:
            async with self.runtime().open():
                self.fail("existing character was reenrolled")
        self.assertEqual(caught.exception.code, "already_enrolled")
        self.assertFalse(self.save.exists())
        self.assert_original()

    async def test_pending_journals_and_existing_mirror_are_preserved(self):
        self.private.mkdir()
        for filename in ("pending-export.json", "pending-trade.json", "pending-battle.json", "character.sav"):
            path = self.private / filename
            path.write_bytes(b"uncertain")
            with self.assertRaises(ValueError):
                async with self.runtime().open():
                    self.fail("uncertain character yielded")
            self.assertEqual(path.read_bytes(), b"uncertain")
            path.unlink()  # Isolated test fixture, never production recovery.
        self.assertEqual(self.calls, [])

    async def test_another_save_owner_prevents_copy_and_native_creation(self):
        self.private.mkdir()
        with MirrorLease(self.save):
            with self.assertRaises(MirrorError):
                async with self.runtime().open():
                    self.fail("second save owner yielded")
        self.assertFalse(self.save.exists())
        self.assert_original()

    async def test_normal_runtime_still_refuses_missing_canonical_enrollment(self):
        with self.assertRaises(ColdStartError) as caught:
            async with PlayerRuntime(self.c, self.bundle, self.private, self.save).open():
                self.fail("normal runtime bypassed canonical recovery")
        self.assertEqual(caught.exception.code, "enrollment_required")
        self.assertEqual(self.calls, [])

    async def test_cancelled_spawn_drains_child_before_releasing_lease_and_retains_source(self):
        release = asyncio.Event()
        async def delayed(*args, **kwargs):
            child = await self.spawn(*args, **kwargs)
            await release.wait()
            return child
        runtime = self.runtime()
        async def run():
            async with runtime.open():
                self.fail("cancelled native creation yielded")
        with patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", delayed):
            task = asyncio.create_task(run())
            await asyncio.wait_for(self.spawned.wait(), 8)
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(MirrorError):
                with MirrorLease(self.save):
                    self.fail("pending creation released its lease")
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, 8)
        self.assertIsNotNone(self.children[0].returncode)
        self.assertTrue(runtime.pending_path.exists())
        self.assertEqual(runtime.source_copy.read_bytes(), self.original)
        with MirrorLease(self.save):
            pass
        self.assert_original()

    async def lost_export(self, stage):
        original_rpc = self.c.checkpoint_rpc
        async def rpc(operation, **fields):
            if operation == "commit" and stage == "before":
                raise ConnectionError("fixture loss before commit")
            response = await original_rpc(operation, **fields)
            if operation == "commit" and stage == "after":
                raise asyncio.TimeoutError("fixture lost commit acknowledgement")
            return response
        self.native.lose_end = stage == "native"
        runtime = self.runtime()
        with patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn):
            async with runtime.open():
                with patch.object(self.c, "checkpoint_rpc", rpc):
                    with self.assertRaises((ConnectionError, asyncio.TimeoutError)):
                        await runtime.enroll()
        self.c._bridge = None
        pending = json.loads((self.private / "pending-export.json").read_text())
        self.assertEqual(pending["expected_revision"], 0)
        payload = (self.private / (pending["operation_id"] + ".flash")).read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(), pending["sha256"])
        self.assertTrue(runtime.pending_path.exists())
        with self.assertRaises(EnrollmentRuntimeError):
            async with self.runtime().open():
                self.fail("uncertainty allowed another bootstrap")
        recovered = await self.runtime().recover()
        self.assertEqual(recovered.mirror.revision, 1)
        self.assertEqual(recovered.mirror.request_id, pending["operation_id"])
        self.assertEqual(self.save.read_bytes(), payload)
        self.assertFalse(runtime.pending_path.exists())
        self.assertEqual(self.store._connection.execute("SELECT COUNT(*) FROM ownership_grants").fetchone()[0], 1)
        self.assertEqual(len(self.children), 1)
        self.assert_original()

    async def test_interrupted_upload_recovers_exact_initial_export_without_recopying(self):
        await self.lost_export("before")

    async def test_lost_server_commit_ack_recovers_without_duplicate_grant_or_revision(self):
        await self.lost_export("after")

    async def test_lost_native_end_ack_retains_export_and_uses_closed_canonical_recovery(self):
        await self.lost_export("native")

    async def test_native_unsafe_before_export_allows_same_context_safe_point_retry(self):
        self.native.unsafe_once = True
        runtime = self.runtime()
        with patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn):
            async with runtime.open():
                with self.assertRaises(ValueError) as caught:
                    await runtime.enroll()
                self.assertTrue(caught.exception.safe_to_retry)
                result = await runtime.enroll()
                self.assertEqual(result.metadata["revision"], 1)
        self.assert_original()

    async def test_changed_session_while_enrollment_waits_refuses_before_grant_or_export(self):
        runtime = self.runtime()
        epoch = self.c.session_epoch
        with patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn):
            async with runtime.open():
                async with self.c.live_checkpoint_lock:
                    task = asyncio.create_task(runtime.enroll())
                    await asyncio.sleep(0)
                    self.assertIs(runtime._task, task)
                    self.assertFalse(task.done())
                    self.c.session_epoch += 1
                try:
                    with self.assertRaisesRegex(ConnectionError, "before lock acquisition"):
                        await task
                finally:
                    self.c.session_epoch = epoch
        self.assertEqual(self.native.commands, [])
        self.assertEqual(self.store._connection.execute("SELECT COUNT(*) FROM ownership_grants").fetchone()[0], 0)
        self.assert_original()

    async def test_changed_session_while_closed_recovery_waits_refuses_before_reconcile(self):
        runtime = self.runtime()
        with patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn):
            async with runtime.open():
                pass
        self.c._bridge = None
        server_epoch = self.c.server_epoch
        async with self.c.live_checkpoint_lock:
            task = asyncio.create_task(self.runtime().recover())
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            self.assertTrue(self.c._bridge_admission_blocked)
            self.c.server_epoch += 1
        try:
            with self.assertRaises(ColdStartError) as caught:
                await task
            self.assertEqual(caught.exception.code, "session_changed")
        finally:
            self.c.server_epoch = server_epoch
        self.assertFalse((self.private / "closed-recoveries").exists())
        self.assertEqual(self.save.read_bytes(), self.original)
        self.assertTrue(runtime.pending_path.exists())
        self.assert_original()

    async def test_context_exit_cancels_pending_enrollment_before_child_and_lease_close(self):
        grant_ready = asyncio.Event()
        async def hold(control):
            if control.opcode == Opcode.BEGIN_EXPORT:
                grant_ready.set()
                await asyncio.Event().wait()
        self.native.hook = hold
        runtime = self.runtime()
        with patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn):
            async with runtime.open():
                task = asyncio.create_task(runtime.enroll())
                await asyncio.wait_for(grant_ready.wait(), 8)
            self.assertTrue(task.cancelled())
        self.assertIsNotNone(self.children[0].returncode)
        self.assertEqual(len(list(self.private.glob("*.grant.json"))), 1)
        self.assertTrue(runtime.pending_path.exists())
        self.assert_original()

    async def test_no_head_after_abandoned_bootstrap_is_not_silently_restarted(self):
        runtime = self.runtime()
        with patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn):
            async with runtime.open():
                pass
        self.c._bridge = None
        with self.assertRaises(ColdStartError) as caught:
            await self.runtime().recover()
        self.assertEqual(caught.exception.code, "enrollment_required")
        self.assertTrue(runtime.pending_path.exists())
        self.assertEqual(self.save.read_bytes(), self.original)

    async def test_bundle_change_during_preflight_prevents_child_and_keeps_approval_evidence(self):
        original_rpc = self.c.checkpoint_rpc
        async def changed(operation, **fields):
            response = await original_rpc(operation, **fields)
            if operation == "info":
                (self.bundle.directory / "SDL2.dll").write_bytes(b"tampered")
            return response
        with patch.object(self.c, "checkpoint_rpc", changed):
            with self.assertRaises(PlayerRuntimeError):
                async with self.runtime().open():
                    self.fail("changed bundle yielded")
        self.assertEqual(self.calls, [])
        self.assert_original()

    async def test_foreign_or_malformed_enrollment_intent_cannot_be_recovered_or_removed(self):
        runtime = self.runtime()
        with patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn):
            async with runtime.open():
                pass
        self.c._bridge = None
        runtime.pending_path.write_bytes(b"uncertain")
        with self.assertRaises(EnrollmentRuntimeError):
            await self.runtime().recover()
        self.assertEqual(runtime.pending_path.read_bytes(), b"uncertain")
        self.assert_original()

    async def test_oversized_native_paths_refuse_before_bootstrap_intent_or_private_copy(self):
        launch_root = self.root / ("a" * 100) / ("b" * 100) / ("c" * 100)
        runtime = EnrollmentRuntime(self.c, self.bundle, self.private, self.save, self.approval,
                                    launch_root=launch_root)
        with patch("emerald_multiplayer.player_runtime._WINDOWS_NATIVE_PATHS", True), \
                patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn):
            with self.assertRaises(PlayerRuntimeError) as caught:
                async with runtime.open():
                    self.fail("unsupported native path entered enrollment")
        self.assertEqual(caught.exception.code, "runtime_path")
        self.assertFalse(self.private.exists())
        self.assertFalse(launch_root.exists())
        self.assertEqual(self.calls, [])
        self.assertEqual(self.native.commands, [])
        self.assertIsNone(await CheckpointClient(self.c).info())
        self.assert_original()
