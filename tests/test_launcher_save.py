"""Launcher ownership around a simulated completed checkpoint operation.

TLS, startup, child lifetime and file leases are real; the native save exporter
is stubbed here and covered separately by live-checkpoint/actual-core tests.
"""
import asyncio
from contextlib import asynccontextmanager
from unittest.mock import patch, PropertyMock
import unittest
from uuid import uuid4

from emerald_multiplayer.checkpoint_client import CheckpointClient
from emerald_multiplayer.checkpoint_mirror import MirrorLease, MirrorError
from emerald_multiplayer.companion import Companion
from emerald_multiplayer.flash import FLASH_SIZE
from emerald_multiplayer.launcher_session import LauncherSessionError, SessionState
from emerald_multiplayer.live_checkpoint import LiveCheckpointCoordinator, LiveSaveError, LiveExportResult
import test_launcher_session as fixture


class LauncherSaveTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixture.LauncherSessionTests.setUp
    asyncTearDown = fixture.LauncherSessionTests.asyncTearDown
    session = fixture.LauncherSessionTests.session
    spawn = fixture.LauncherSessionTests.spawn

    @asynccontextmanager
    async def playing(self):
        session = self.session()
        with patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn):
            async with session.open():
                play = asyncio.create_task(session.play())
                try:
                    async with asyncio.timeout(10):
                        while session._game is None: await asyncio.sleep(.005)
                    yield session, play
                finally:
                    for child in self.children:
                        if child.returncode is None: child.terminate()
                    await play

    async def completed(self, coordinator, *, expected_revision, expected_session):
        c = coordinator.companion
        self.assertEqual(expected_session, (c.world_id, c.session_epoch, c.save_incarnation))
        metadata = dict(await CheckpointClient(c).info())
        operation = str(uuid4())
        # Closed startup fixtures include an RTC trailer. Native live export
        # returns only Flash, so its completion metadata has no trailer.
        metadata.update(revision=expected_revision + 1, request_id=operation, size=FLASH_SIZE)
        return LiveExportResult(operation, metadata, metadata["sha256"], "a" * 64, "b" * 32)

    async def test_explicit_saves_use_startup_then_verified_completed_revision(self):
        revisions = []
        async def save(coordinator, **fields):
            revisions.append(fields["expected_revision"])
            return await self.completed(coordinator, **fields)
        async with self.playing() as (session, play):
            with patch.object(Companion, "save_incarnation", new_callable=PropertyMock, return_value=100), \
                    patch.object(LiveCheckpointCoordinator, "checkpoint", save):
                self.assertTrue(await session.save())
                self.assertTrue(await session.save())
                self.assertEqual(revisions, [1, 2])
                self.assertEqual(session.status.revision, 3)
                self.assertEqual(session.status.code, "saved")
                self.assertTrue(session.can_save)
        self.assertEqual(session._revision, 3)

    async def test_missing_initial_bridge_and_definite_busy_require_explicit_retry(self):
        async with self.playing() as (session, play):
            self.assertFalse(await session.save())
            self.assertEqual(session.status.code, "save_not_ready")
            async def busy(*args, **kwargs):
                raise LiveSaveError("rom_unsafe", "not exported", safe_to_retry=True)
            with patch.object(Companion, "save_incarnation", new_callable=PropertyMock, return_value=100), \
                    patch.object(LiveCheckpointCoordinator, "checkpoint", busy):
                self.assertFalse(await session.save())
                self.assertTrue(session.can_save)
                self.assertEqual(session.status.revision, 1)

    async def test_uncertain_save_blocks_followup_and_keeps_recovery_status_on_close(self):
        async with self.playing() as (session, play):
            async def uncertain(*args, **kwargs):
                raise LiveSaveError("reply_lost", "private details stay out of UI")
            with patch.object(Companion, "save_incarnation", new_callable=PropertyMock, return_value=100), \
                    patch.object(LiveCheckpointCoordinator, "checkpoint", uncertain):
                self.assertFalse(await session.save())
                self.assertFalse(session.can_save)
                self.assertEqual(session.status.code, "save_recovery_required")
                with self.assertRaises(LauncherSessionError): await session.save()
                self.children[0].terminate()
                await play
                self.assertEqual(session.status.code, "save_recovery_required")

    async def test_bad_completion_does_not_adopt_server_revision(self):
        async def malformed(coordinator, **fields):
            result = await self.completed(coordinator, **fields)
            result.metadata["request_id"] = str(uuid4())
            return result
        async with self.playing() as (session, play):
            with patch.object(Companion, "save_incarnation", new_callable=PropertyMock, return_value=100), \
                    patch.object(LiveCheckpointCoordinator, "checkpoint", malformed):
                self.assertFalse(await session.save())
                self.assertEqual(session.status.revision, 1)
                self.assertFalse(session.can_save)

    async def test_changed_native_incarnation_refuses_another_save(self):
        async def save(coordinator, **fields): return await self.completed(coordinator, **fields)
        async with self.playing() as (session, play):
            with patch.object(Companion, "save_incarnation", new_callable=PropertyMock, return_value=100) as incarnation, \
                    patch.object(LiveCheckpointCoordinator, "checkpoint", save):
                self.assertTrue(await session.save())
                incarnation.return_value = 101
                self.assertFalse(await session.save())
                self.assertEqual(session.status.code, "save_recovery_required")

    async def test_close_and_repeated_cancellation_drain_save_with_file_lease_held(self):
        entered, finish = asyncio.Event(), asyncio.Event()
        async def slow(coordinator, **fields):
            entered.set()
            await finish.wait()
            return await self.completed(coordinator, **fields)
        async with self.playing() as (session, play):
            with patch.object(Companion, "save_incarnation", new_callable=PropertyMock, return_value=100), \
                    patch.object(LiveCheckpointCoordinator, "checkpoint", slow):
                saving = asyncio.create_task(session.save())
                await asyncio.wait_for(entered.wait(), 5)
                with self.assertRaises(LauncherSessionError) as caught: await session.save()
                self.assertEqual(caught.exception.code, "save_busy")
                saving.cancel(); await asyncio.sleep(0); saving.cancel()
                self.children[0].terminate()
                await asyncio.sleep(.05)
                self.assertFalse(play.done())
                self.assertFalse(saving.done())
                with self.assertRaises(MirrorError):
                    with MirrorLease(session.profile_directory / "character.sav"): pass
                finish.set()
                with self.assertRaises(asyncio.CancelledError): await saving
                await play
                self.assertEqual(session.status.revision, 2)
                with MirrorLease(session.profile_directory / "character.sav"): pass
