"""Real launcher/TLS/child lifetime with explicit native IPC-exit ordering.

The native bridge and checkpoint producer remain strict fixtures. A real Python
child exits with the requested status only after its private signal is written.
"""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from emerald_multiplayer.checkpoint_mirror import MirrorError, MirrorLease
from emerald_multiplayer.launcher_gui import SessionWorker
from emerald_multiplayer.launcher_session import LauncherSessionError
from emerald_multiplayer.live_checkpoint import LiveCheckpointCoordinator, LiveSaveError
from process_fixture import direct_python
from test_autosave import Clock
from test_companion import make_pose
from test_launcher_autosave import wait_until
import test_launcher_session as fixture


class LauncherExitTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixture.LauncherSessionTests.setUp
    asyncTearDown = fixture.LauncherSessionTests.asyncTearDown
    session = fixture.LauncherSessionTests.session

    async def spawn_until_signal(self, *args, **kwargs):
        save = Path(args[4])
        self.assertEqual(save.read_bytes(), self.payloads[save.parent.name])
        with self.assertRaises(MirrorError):
            with MirrorLease(save):
                pass
        source = ("import pathlib,sys,time; p=pathlib.Path(sys.argv[1]); "
                  "exec('while not p.exists(): time.sleep(.01)'); sys.exit(int(p.read_text()))")
        child = await self.real_spawn(direct_python(), "-c", source, str(self.exit_signal), **kwargs)
        self.children.append(child)
        return child

    @asynccontextmanager
    async def playing_worker(self):
        self.exit_signal = self.root / "child-exit.txt"
        self.clock = Clock()
        def factory(*args, **kwargs):
            self.running = self.session(on_status=kwargs["on_status"])
            self.running._autosave_clock = self.clock
            return self.running
        worker = SessionWorker(self.installation, self.private, factory=factory)
        with patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn_until_signal):
            task = asyncio.create_task(worker._session({}))
            try:
                await wait_until(lambda: hasattr(self, "running") and self.running._game is not None)
                self.c = self.running._companion
                self.c._bridge = SimpleNamespace(save_capable=True, incarnation=100,
                    outbox=SimpleNamespace(put=lambda _: None))
                self.c._local_pose, self.c._last_pose_time = make_pose(), self.clock()
                self.running._autosave_wake.set()
                await wait_until(lambda: self.running._autosave is not None)
                yield self.running, task, worker
            finally:
                if hasattr(self, "finish_checkpoint"):
                    self.finish_checkpoint.set()
                if not self.exit_signal.exists():
                    self.exit_signal.write_text("0")
                await asyncio.wait_for(task, 15)

    def disconnect_bridge(self, session):
        # Match Companion's real IPC EOF order before the OS reports exit.
        self.c._bridge = None
        self.c._disconnect_remote()
        session._autosave_wake.set()
        if session._autosave is not None:
            session._autosave._wake.set()

    def make_due(self, session):
        self.clock.value += 300
        self.c._last_pose_time = self.clock()
        session._autosave_wake.set()
        session._autosave._wake.set()

    async def test_idle_bridge_eof_is_not_normal_close_until_zero_process_exit(self):
        with patch.object(LiveCheckpointCoordinator, "checkpoint") as checkpoint:
            async with self.playing_worker() as (session, task, worker):
                self.disconnect_bridge(session)
                await wait_until(lambda: session._save_failed)
                self.assertTrue(session._idle_save_disconnect)
                self.assertFalse(session.status.connected)
                self.assertFalse(session.can_save)
                self.assertFalse(task.done())
                with self.assertRaises(LauncherSessionError):
                    await session.save()
                self.exit_signal.write_text("0")
                self.assertEqual(await task, "game_closed")
                self.assertFalse(session._save_failed)
                checkpoint.assert_not_called()
                events = []
                while not worker.events.empty():
                    events.append(worker.events.get_nowait())
                self.assertFalse(any(event.code == "saved" for event in events))

    async def test_nonzero_exit_retains_even_an_idle_disconnect_warning(self):
        async with self.playing_worker() as (session, task, _):
            self.disconnect_bridge(session)
            await wait_until(lambda: session._save_failed)
            self.exit_signal.write_text("7")
            self.assertEqual(await task, "save_recovery_required")
            self.assertFalse(session.status.connected)
            self.assertEqual(session.status.code, "save_recovery_required")

    async def test_uncertain_autosave_disconnect_and_zero_exit_keep_recovery_priority(self):
        entered = asyncio.Event()
        self.finish_checkpoint = asyncio.Event()
        async def uncertain(*args, **kwargs):
            entered.set()
            await self.finish_checkpoint.wait()
            raise ConnectionError("private native acknowledgment was lost")
        with patch.object(LiveCheckpointCoordinator, "checkpoint", uncertain):
            async with self.playing_worker() as (session, task, _):
                original = (session.profile_directory / "character.sav").read_bytes()
                self.make_due(session)
                await asyncio.wait_for(entered.wait(), 5)
                self.disconnect_bridge(session)
                self.finish_checkpoint.set()
                await wait_until(lambda: session._save_failed)
                self.assertFalse(session._idle_save_disconnect)
                self.assertFalse(session.status.connected)
                self.assertEqual(session.status.code, "save_recovery_required")
                self.exit_signal.write_text("0")
                self.assertEqual(await task, "save_recovery_required")
                self.assertEqual(session.status.code, "save_recovery_required")
                self.assertEqual((session.profile_directory / "character.sav").read_bytes(), original)

    async def test_uncertain_manual_save_is_not_downgraded_by_later_idle_loss(self):
        async def uncertain(*args, **kwargs):
            raise LiveSaveError("reply_lost", "private native acknowledgment was lost")
        with patch.object(LiveCheckpointCoordinator, "checkpoint", uncertain):
            async with self.playing_worker() as (session, task, _):
                self.assertFalse(await session.save())
                self.disconnect_bridge(session)
                await wait_until(lambda: session._autosave_task.done())
                self.assertFalse(session._idle_save_disconnect)
                self.assertEqual(session.status.code, "save_recovery_required")
                self.exit_signal.write_text("0")
                self.assertEqual(await task, "save_recovery_required")

    async def test_pending_export_appearing_during_idle_shutdown_is_retained(self):
        async with self.playing_worker() as (session, task, _):
            self.disconnect_bridge(session)
            await wait_until(lambda: session._idle_save_disconnect)
            pending = session.profile_directory / "pending-export.json"
            pending.write_bytes(b"retained uncertain export fixture")
            self.exit_signal.write_text("0")
            self.assertEqual(await task, "save_recovery_required")
            self.assertEqual(pending.read_bytes(), b"retained uncertain export fixture")

    async def test_changed_live_incarnation_and_toggle_cannot_restart_saving(self):
        with patch.object(LiveCheckpointCoordinator, "checkpoint") as checkpoint:
            async with self.playing_worker() as (session, task, _):
                self.c._bridge.incarnation = 101
                session._autosave._wake.set()
                await wait_until(lambda: session._save_failed)
                self.assertTrue(session.status.connected)
                await session.set_autosave_enabled(False)
                await session.set_autosave_enabled(True)
                self.assertFalse(session.can_save)
                with self.assertRaises(LauncherSessionError):
                    await session.save()
                checkpoint.assert_not_called()
                self.exit_signal.write_text("0")
                self.assertEqual(await task, "game_closed")
