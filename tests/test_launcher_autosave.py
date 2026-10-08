"""Launcher policy over real TLS/store/runtime/lease and strict native fixtures."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import UUID

from emerald_multiplayer.autosave import AutosaveState
from emerald_multiplayer.checkpoint_client import CheckpointClient
from emerald_multiplayer.checkpoint_mirror import MirrorError, MirrorLease
from emerald_multiplayer.flash import FLASH_SIZE, inspect_flash
from emerald_multiplayer.launcher_session import LauncherSessionError
from emerald_multiplayer.launcher_settings import AUTOSAVE_INTERVAL, LauncherSettings, LauncherSettingsError
from emerald_multiplayer.live_checkpoint import LiveCheckpointCoordinator, LiveSaveError
from emerald_multiplayer.ownership import inspect_ownership, OWNERSHIP_PROFILE
from emerald_multiplayer.ownership_storage import AllocationGrant
from emerald_multiplayer.save_mailbox import Opcode, SaveControl, Status
from test_autosave import Clock
from test_companion import make_pose
from test_live_checkpoint import FakeCompanion
from test_ownership_client import status as ownership_status
from test_ownership_storage import owned_flash
import test_launcher_save as saves
import test_launcher_session as fixture


async def wait_until(predicate):
    async with asyncio.timeout(15):
        while not predicate():
            await asyncio.sleep(.005)


class SettingsTests(unittest.TestCase):
    def test_default_fixed_interval_and_per_profile_atomic_roundtrip(self):
        self.assertEqual(AUTOSAVE_INTERVAL, 300)
        with tempfile.TemporaryDirectory() as value:
            first, second = Path(value) / "first", Path(value) / "second"
            self.assertTrue(LauncherSettings.load(first).autosave_enabled)
            self.assertFalse(first.exists())
            LauncherSettings(False).save(first)
            self.assertFalse(LauncherSettings.load(first).autosave_enabled)
            self.assertTrue(LauncherSettings.load(second).autosave_enabled)
            LauncherSettings(True).save(first)
            self.assertTrue(LauncherSettings.load(first).autosave_enabled)
            self.assertEqual(len(list(first.iterdir())), 1)

    def test_corruption_is_not_silently_reset_to_enabled(self):
        with tempfile.TemporaryDirectory() as value:
            directory = Path(value)
            path = directory / "launcher-settings.json"
            for raw in (b"private arbitrary content", b"x" * 4097,
                        b'{"format":"emerald-launcher-settings-v1","autosave_enabled":0}',
                        b'{"format":"unknown","autosave_enabled":false}'):
                with self.subTest(raw=raw[:30]):
                    path.write_bytes(raw)
                    with self.assertRaises(LauncherSettingsError) as caught:
                        LauncherSettings.load(directory)
                    self.assertEqual(caught.exception.code, "settings_unavailable")
                    self.assertNotIn("private arbitrary", str(caught.exception))
                    self.assertEqual(path.read_bytes(), raw)

    def test_failed_replace_preserves_previous_preference(self):
        with tempfile.TemporaryDirectory() as value:
            directory = Path(value)
            LauncherSettings(False).save(directory)
            with patch("emerald_multiplayer.live_checkpoint.os.replace", side_effect=OSError("secret path")):
                with self.assertRaises(LauncherSettingsError) as caught:
                    LauncherSettings(True).save(directory)
            self.assertNotIn("secret", str(caught.exception))
            self.assertFalse(LauncherSettings.load(directory).autosave_enabled)
            self.assertEqual(len(list(directory.iterdir())), 1)


class LauncherAutosaveTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixture.LauncherSessionTests.setUp
    asyncTearDown = fixture.LauncherSessionTests.asyncTearDown
    session = fixture.LauncherSessionTests.session
    spawn = fixture.LauncherSessionTests.spawn
    completed = saves.LauncherSaveTests.completed

    @asynccontextmanager
    async def playing(self, *, enabled=True, bridge=True):
        session = self.session()
        self.clock = Clock()
        session._autosave_clock = self.clock
        with patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn):
            async with session.open():
                if not enabled:
                    await session.set_autosave_enabled(False)
                play = asyncio.create_task(session.play())
                try:
                    await wait_until(lambda: session._game is not None)
                    self.c = session._companion
                    if bridge:
                        self.attach_bridge(session)
                        if enabled:
                            await wait_until(lambda: session._autosave is not None)
                    yield session, play
                finally:
                    if hasattr(self, "release_checkpoint"):
                        self.release_checkpoint.set()
                    for child in self.children:
                        if child.returncode is None: child.terminate()
                    if not play.cancelled():
                        await play
                    self.c._bridge = None

    def attach_bridge(self, session):
        self.c._bridge = SimpleNamespace(save_capable=True, incarnation=100,
            outbox=SimpleNamespace(put=lambda _: None))
        self.c._local_pose, self.c._last_pose_time = make_pose(), self.clock()
        session._autosave_wake.set()

    def advance(self, session, seconds):
        self.clock.value += seconds
        self.c._last_pose_time = self.clock()
        session._autosave_wake.set()
        if session._autosave is not None:
            session._autosave._wake.set()

    async def test_real_tls_checkpoint_at_five_minutes_then_manual_and_auto_share_verified_revision(self):
        async with self.playing() as (session, _):
            original = (session.profile_directory / "character.sav").read_bytes()
            native = SimpleNamespace(rom_flash=original[:FLASH_SIZE], rng=bytes(32),
                mode=None, stage=bytearray(), operation=None, commands=[],
                save_incarnation=100, session_epoch=self.c.session_epoch, control_hook=None,
                lose_end_ack=False, bad_end_crc=False, _rotation=FakeCompanion._rotation)
            native_errors = []
            previous = inspect_ownership(inspect_flash(original, save_profile=OWNERSHIP_PROFILE))
            active_grant = None
            def ownership_bytes():
                grant = active_grant or previous
                return ownership_status(flags=3 if active_grant else 1, missing=0,
                    remaining=grant.end_exclusive-grant.start if active_grant else 0,
                    world=grant.world_id, player=grant.player_id, grant=grant.grant_id,
                    next_id=grant.start if active_grant else previous.next_serial,
                    end=grant.end_exclusive, lease=grant.lease_epoch, incarnation=grant.incarnation)
            async def rpc(control, **options):
                nonlocal active_grant
                try:
                    if control.opcode in (Opcode.QUERY_OWNERSHIP, Opcode.GRANT_OWNERSHIP):
                        control = SaveControl.unpack(control.pack()).validate_command()
                        native.commands.append(control)
                        if control.opcode == Opcode.GRANT_OWNERSHIP:
                            world, player, grant, start, end, enroll = struct.unpack("<16s16s16sIII", control.data)
                            self.assertEqual(enroll, 0)
                            active_grant = AllocationGrant(str(UUID(bytes=world)), str(UUID(bytes=player)),
                                str(UUID(bytes=grant)), start, end, control.session_epoch, control.incarnation,
                                control.revision)
                            self.assertTrue((session.profile_directory / (active_grant.grant_id + ".grant.json")).exists())
                            native.rom_flash = owned_flash(active_grant,
                                records=tuple((r.location, r.serial) for r in previous.records),
                                personalities=tuple(r.personality for r in previous.records), next_serial=start)
                        return SaveControl.unpack(replace(control, data=ownership_bytes(), status=Status.OK).pack()).validate_response()
                    if control.opcode == Opcode.BEGIN_EXPORT:
                        control = SaveControl.unpack(control.pack()).validate_command()
                        native.commands.append(control)
                        self.assertIsNone(native.mode)
                        native.mode, native.operation = "export", control.request_id
                        parsed = inspect_flash(native.rom_flash, save_profile=OWNERSHIP_PROFILE)
                        sector = struct.unpack_from("<H", native.rom_flash, parsed.metadata.bank*14*4096+4084)[0]
                        data = struct.pack("<II", parsed.metadata.counter, (-sector) % 14) + native.rng
                        return SaveControl.unpack(replace(control, data=data, status=Status.OK).pack()).validate_response()
                    return await FakeCompanion.save_rpc(native, control, **options)
                except Exception as error:
                    native_errors.append(repr(error))
                    raise
            self.c.save_rpc = rpc
            self.assertEqual(session._autosave.interval, 300)
            self.advance(session, 299)
            await asyncio.sleep(.03)
            self.assertEqual(native.commands, [])
            self.advance(session, 1)
            await wait_until(lambda: session._revision == 2 or session._save_failed)
            self.assertFalse(session._save_failed, (native_errors, session.status,
                [command.opcode for command in native.commands]))
            self.assertEqual((await CheckpointClient(self.c).info())["revision"], 2)
            self.assertTrue(await session.save())
            self.assertTrue(await session.save())  # Manual is not timer-throttled.
            self.assertEqual(session._revision, 4)
            await wait_until(lambda: session._autosave is not None)
            self.advance(session, 299)
            await asyncio.sleep(.03)
            self.assertEqual(session._revision, 4)
            self.advance(session, 1)
            await wait_until(lambda: session._revision == 5)
            self.assertEqual((await CheckpointClient(self.c).info())["revision"], 5)
            self.assertFalse((session.profile_directory / "pending-export.json").exists())
            self.assertEqual((session.profile_directory / "character.sav").read_bytes(), original)

    async def test_timer_waits_for_initial_native_bridge_and_safe_scene(self):
        calls = []
        async def checkpoint(coordinator, **fields):
            calls.append(fields["expected_revision"])
            return await self.completed(coordinator, **fields)
        with patch.object(LiveCheckpointCoordinator, "checkpoint", checkpoint):
            async with self.playing(bridge=False) as (session, _):
                self.advance(session, 1000)
                await asyncio.sleep(.03)
                self.assertIsNone(session._autosave)
                self.attach_bridge(session)
                await wait_until(lambda: session._autosave is not None)
                self.c._local_pose = make_pose(activity=0)
                self.advance(session, 300)
                await wait_until(lambda: session.status.code == "autosave_deferred")
                self.assertEqual(calls, [])
                self.c._local_pose = make_pose()
                self.c._live_battle_owner = object()
                self.advance(session, 0)
                await asyncio.sleep(.03)
                self.assertEqual(calls, [])
                self.c._live_battle_owner = None
                self.advance(session, 0)
                await wait_until(lambda: session._revision == 2)
                self.assertEqual(calls, [1])

    async def test_toggle_off_persists_for_same_player_without_disabling_manual_save(self):
        calls = []
        async def checkpoint(coordinator, **fields):
            calls.append(fields["expected_revision"])
            return await self.completed(coordinator, **fields)
        with patch.object(LiveCheckpointCoordinator, "checkpoint", checkpoint):
            async with self.playing() as (session, _):
                await session.set_autosave_enabled(False)
                self.advance(session, 1000)
                await asyncio.sleep(.03)
                self.assertEqual(calls, [])
                self.assertTrue(await session.save())
                self.assertEqual(calls, [1])
                self.assertFalse(session.status.autosave_enabled)
                private = session.profile_directory
            self.assertFalse(LauncherSettings.load(private).autosave_enabled)
            async with self.session().open() as reopened:
                self.assertFalse(reopened.autosave_enabled)
            other = self.private / "players" / self.host.world_id / self.host.accounts[1].player_id
            self.assertTrue(LauncherSettings.load(other).autosave_enabled)

    async def test_safe_manual_refusal_preserves_due_autosave_and_has_no_overlap(self):
        calls = []
        async def checkpoint(coordinator, **fields):
            calls.append(fields["expected_revision"])
            if len(calls) == 1:
                raise LiveSaveError("rom_unsafe", "safe refusal", safe_to_retry=True)
            return await self.completed(coordinator, **fields)
        with patch.object(LiveCheckpointCoordinator, "checkpoint", checkpoint):
            async with self.playing() as (session, _):
                self.advance(session, 290)
                self.assertFalse(await session.save())
                await wait_until(lambda: session._autosave is not None)
                self.advance(session, 10)
                await wait_until(lambda: session._revision == 2)
                self.assertEqual(calls, [1, 1])

    async def test_toggle_during_manual_save_preserves_single_flight_and_restarts_from_completion(self):
        entered, finish = asyncio.Event(), asyncio.Event()
        self.release_checkpoint = finish
        calls = []
        async def checkpoint(coordinator, **fields):
            calls.append(fields["expected_revision"])
            entered.set()
            await finish.wait()
            return await self.completed(coordinator, **fields)
        with patch.object(LiveCheckpointCoordinator, "checkpoint", checkpoint):
            async with self.playing() as (session, _):
                manual = asyncio.create_task(session.save())
                await asyncio.wait_for(entered.wait(), 5)
                await session.set_autosave_enabled(False)
                await session.set_autosave_enabled(True)
                self.advance(session, 600)
                await asyncio.sleep(.03)
                self.assertEqual(calls, [1])
                self.assertFalse(session.can_save)
                self.assertEqual(session.status.code, "saving")
                finish.set()
                self.assertTrue(await manual)
                await wait_until(lambda: session._autosave is not None)
                self.advance(session, 299)
                await asyncio.sleep(.03)
                self.assertEqual(calls, [1])
                self.advance(session, 1)
                await wait_until(lambda: session._revision == 3)
                self.assertEqual(calls, [1, 2])

    async def test_changed_incarnation_after_toggle_is_terminal_before_any_checkpoint(self):
        async with self.playing() as (session, _):
            await session.set_autosave_enabled(False)
            self.c._bridge.incarnation += 1
            await session.set_autosave_enabled(True)
            await wait_until(lambda: session._save_failed)
            self.assertEqual(session._revision, 1)
            self.assertFalse(session.can_save)
            self.assertEqual(session.status.code, "save_recovery_required")

    async def test_unreadable_settings_refuse_before_host_or_child_creation(self):
        private = self.private / "players" / self.host.world_id / self.host.accounts[0].player_id
        private.mkdir(parents=True)
        settings = private / "launcher-settings.json"
        settings.write_text("private invalid settings")
        session = self.session()
        with self.assertRaises(LauncherSessionError) as caught:
            async with session.open(): self.fail("invalid settings were accepted")
        self.assertEqual(caught.exception.code, "settings_unavailable")
        self.assertIsNone(session._server)
        self.assertEqual(self.children, [])
        self.assertEqual(settings.read_text(), "private invalid settings")

    async def test_uncertain_autosave_and_new_incarnation_cannot_be_reenabled_or_adopt_a_head(self):
        calls = []
        async def checkpoint(coordinator, **fields):
            calls.append(fields["expected_revision"])
            raise LiveSaveError("reply_lost", "private secret")
        with patch.object(LiveCheckpointCoordinator, "checkpoint", checkpoint):
            async with self.playing() as (session, _):
                self.advance(session, 300)
                await wait_until(lambda: session._save_failed)
                self.assertEqual(session._revision, 1)
                await session.set_autosave_enabled(False)
                self.c._bridge.incarnation = 101
                await session.set_autosave_enabled(True)
                self.advance(session, 600)
                await asyncio.sleep(.03)
                self.assertEqual(calls, [1])
                self.assertFalse(session.can_save)
                self.assertEqual(session.status.code, "save_recovery_required")

    async def test_toggle_and_close_drain_autosave_with_lease_through_repeated_cancel(self):
        entered, finish = asyncio.Event(), asyncio.Event()
        self.release_checkpoint = finish
        async def checkpoint(coordinator, **fields):
            entered.set()
            await finish.wait()
            return await self.completed(coordinator, **fields)
        with patch.object(LiveCheckpointCoordinator, "checkpoint", checkpoint):
            async with self.playing() as (session, play):
                self.advance(session, 300)
                await asyncio.wait_for(entered.wait(), 5)
                with self.assertRaises(LauncherSessionError) as caught:
                    await session.save()
                self.assertEqual(caught.exception.code, "save_busy")
                off = asyncio.create_task(session.set_autosave_enabled(False))
                await wait_until(lambda: not session.autosave_enabled)
                with self.assertRaises(LauncherSessionError):
                    await session.set_autosave_enabled(True)
                off.cancel(); await asyncio.sleep(0); off.cancel()
                play.cancel(); await asyncio.sleep(0); play.cancel()
                await asyncio.sleep(.03)
                self.assertFalse(off.done())
                self.assertFalse(play.done())
                with self.assertRaises(MirrorError):
                    with MirrorLease(session.profile_directory / "character.sav"): pass
                finish.set()
                with self.assertRaises(asyncio.CancelledError): await off
                with self.assertRaises(asyncio.CancelledError): await play
                self.assertEqual(session._revision, 2)
                self.assertFalse(LauncherSettings.load(session.profile_directory).autosave_enabled)
