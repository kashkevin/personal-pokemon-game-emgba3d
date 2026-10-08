"""Scheduler policy plus real codec/client/SQLite synthetic-ROM lifecycles.

These tests do not establish actual emulator performance or player acceptance.
"""
import asyncio
from dataclasses import replace
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from uuid import uuid4

from emerald_multiplayer.autosave import AutosaveError, AutosaveScheduler, AutosaveState
from emerald_multiplayer.flash import FLASH_SIZE, LAYOUT_ID
from emerald_multiplayer.live_checkpoint import LiveCheckpointCoordinator, LiveExportResult, LiveSaveError
from emerald_multiplayer.save_mailbox import Opcode, Status
from test_companion import make_pose
from test_live_checkpoint import FakeCompanion


class Clock:
    def __init__(self):
        self.value = 100.0
    def __call__(self):
        return self.value


async def wait_until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.005)


def ready_companion(clock):
    return SimpleNamespace(
        connected=True, world_id=str(uuid4()), server_epoch=1, session_epoch=2,
        save_incarnation=3, save_profile=LAYOUT_ID,
        config=SimpleNamespace(player_id=str(uuid4()), build_id="a"*64, ruleset_id="rules-v1",
            server_credential=bytes(32), save_enabled=True, ownership_enabled=False, pause_timeout=.5),
        _bridge=SimpleNamespace(save_capable=True), _local_pose=make_pose(), _last_pose_time=clock(),
        live_checkpoint_lock=asyncio.Lock(), _live_save_owner=None, _save_pending={}, _battle_pending={},
        _bridge_admission_blocked=False,
    )


def export_result(c, revision):
    operation = str(uuid4())
    metadata = dict(revision=revision, request_id=operation, size=FLASH_SIZE, sha256="f"*64,
                    build_id=c.config.build_id, ruleset_id=c.config.ruleset_id, save_profile=c.save_profile)
    return LiveExportResult(operation, metadata, "f"*64, "d"*64, bytes(32).hex())


class Coordinator:
    """Injected slow/failed operation; application scheduling is under test."""
    def __init__(self, companion, directory):
        self.companion, self.directory = companion, Path(directory)
        self.pending_path = self.directory / "pending-export.json"
        self.calls, self.active, self.max_active = [], 0, 0
        self.expected_sessions = []
        self.started = asyncio.Event()
        self.release = self.hook = self.error = None
        self.cancelled = False
        self.result_transform = lambda result: result

    async def checkpoint(self, *, expected_revision, expected_session=None):
        self.expected_sessions.append(expected_session)
        self.calls.append(expected_revision)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.started.set()
        try:
            if self.release is not None:
                await self.release.wait()
            if self.hook is not None:
                self.hook()
            if self.error is not None:
                error, self.error = self.error, None
                raise error
            return self.result_transform(export_result(self.companion, expected_revision+1))
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        finally:
            self.active -= 1


class AutosaveTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.loop = asyncio.get_running_loop()
        self.previous_handler = self.loop.get_exception_handler()
        self.loop_errors = []
        self.loop.set_exception_handler(lambda loop, context: self.loop_errors.append(context.get("message")))
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.clock = Clock()
        self.c = ready_companion(self.clock)
        self.coordinator = Coordinator(self.c, self.directory)
        self.schedulers = []

    async def asyncTearDown(self):
        if self.coordinator.release is not None:
            self.coordinator.release.set()
        for scheduler in self.schedulers:
            await scheduler.stop()
        self.loop.set_exception_handler(self.previous_handler)
        self.assertEqual(self.loop_errors, [])
        self.temp.cleanup()

    def scheduler(self, **kwargs):
        options = dict(expected_revision=1, interval=10, poll_interval=.02, clock=self.clock)
        options.update(kwargs)
        result = AutosaveScheduler(self.coordinator, **options)
        self.schedulers.append(result)
        return result

    def fresh(self):
        self.c._last_pose_time = self.clock()

    async def test_opt_in_requires_existing_revision_and_explicit_valid_interval(self):
        scheduler = self.scheduler()
        self.assertEqual(scheduler.status.state, AutosaveState.NEW)
        self.assertFalse(scheduler.request())
        await asyncio.sleep(.03)
        self.assertEqual(self.coordinator.calls, [])
        for revision in (None, True, 0, -1, 0x7FFFFFFF):
            with self.subTest(revision=revision), self.assertRaises(ValueError):
                self.scheduler(expected_revision=revision)
        for interval in (True, 0, -1, float("inf"), float("nan"), 86_401):
            with self.subTest(interval=interval), self.assertRaises(ValueError):
                self.scheduler(interval=interval)
        with self.assertRaises(TypeError):
            AutosaveScheduler(self.coordinator, expected_revision=1)
        async def asynchronous():
            pass
        with self.assertRaises(ValueError):
            self.scheduler(on_status=asynchronous)

    async def test_timer_is_coalesced_while_unsafe_and_revision_advances_only_on_success(self):
        scheduler = self.scheduler()
        await scheduler.start()
        self.clock.value = 109
        self.fresh()
        await asyncio.sleep(.03)
        self.assertEqual(self.coordinator.calls, [])
        self.clock.value = 500
        self.c._local_pose = make_pose(activity=0)
        self.fresh()
        for _ in range(100):
            self.assertTrue(scheduler.request())
        await wait_until(lambda: scheduler.status.state is AutosaveState.DEFERRED)
        self.assertEqual(scheduler.status.expected_revision, 1)
        self.assertEqual(self.coordinator.calls, [])
        self.c._local_pose = make_pose()
        await wait_until(lambda: scheduler.status.completed == 1)
        await asyncio.sleep(.06)
        self.assertEqual(self.coordinator.calls, [1])
        self.assertEqual(scheduler.status.expected_revision, 2)
        self.assertEqual(scheduler.last_result.metadata["revision"], 2)

    async def test_slow_export_and_inflight_requests_never_create_overlap_or_catchup_burst(self):
        scheduler = self.scheduler()
        self.coordinator.release = asyncio.Event()
        self.coordinator.hook = lambda: setattr(self.clock, "value", 1000)
        await scheduler.start()
        scheduler.request()
        await self.coordinator.started.wait()
        for _ in range(100):
            scheduler.request()
        self.coordinator.release.set()
        await wait_until(lambda: scheduler.status.completed == 1)
        self.coordinator.hook = None
        self.fresh()
        await asyncio.sleep(.06)
        self.assertEqual(self.coordinator.calls, [1])
        self.clock.value = 1009
        self.fresh()
        await asyncio.sleep(.04)
        self.assertEqual(self.coordinator.calls, [1])
        self.clock.value = 1010
        self.fresh()
        await wait_until(lambda: scheduler.status.completed == 2)
        self.assertEqual(self.coordinator.calls, [1, 2])
        self.assertEqual(self.coordinator.max_active, 1)

    async def test_heartbeat_is_not_fresh_available_gameplay(self):
        scheduler = self.scheduler()
        await scheduler.start()
        scheduler.request()
        for pose, seen in ((make_pose(), 90), (make_pose(), 101),
                           (make_pose(activity=0), 100), (make_pose(movement_mode=4), 100),
                           (None, 100)):
            self.c._local_pose, self.c._last_pose_time = pose, seen
            self.c._heartbeat = 999999
            await wait_until(lambda: scheduler.status.code == "game_unavailable")
            await asyncio.sleep(.025)
            self.assertEqual(self.coordinator.calls, [])
        self.c._local_pose = make_pose()
        self.fresh()
        await wait_until(lambda: scheduler.status.completed == 1)

    async def test_trade_save_battle_and_extra_reset_gate_defer_without_writes(self):
        safe = False
        scheduler = self.scheduler(safe_point=lambda: safe)
        await scheduler.start()
        scheduler.request()
        await wait_until(lambda: scheduler.status.code == "unsafe_scene")
        safe = True
        blockers = (("_save_pending", {1: object()}), ("_battle_pending", {1: object()}),
                    ("_live_save_owner", object()), ("_bridge_admission_blocked", True))
        for name, value in blockers:
            previous = getattr(self.c, name)
            setattr(self.c, name, value)
            await wait_until(lambda: scheduler.status.code == "lifecycle_busy")
            await asyncio.sleep(.025)
            self.assertEqual(self.coordinator.calls, [])
            setattr(self.c, name, previous)
        await self.c.live_checkpoint_lock.acquire()
        await asyncio.sleep(.025)
        self.assertEqual(self.coordinator.calls, [])
        self.c.live_checkpoint_lock.release()
        trade = self.directory / "elsewhere-trade.json"
        trade.write_text("unresolved durable trade")
        self.c._live_trade_pending_path = trade
        await wait_until(lambda: scheduler.status.code == "pending_trade")
        self.assertEqual(self.coordinator.calls, [])
        trade.unlink()
        await wait_until(lambda: scheduler.status.completed == 1)

    async def test_definite_rom_busy_and_unsafe_before_journal_defer_then_retry_same_base(self):
        for code in ("rom_busy", "rom_unsafe"):
            scheduler = self.scheduler()
            self.coordinator.error = LiveSaveError(code, "definite admission refusal", safe_to_retry=True)
            await scheduler.start()
            scheduler.request()
            await wait_until(lambda: scheduler.status.code == code)
            self.assertEqual(scheduler.status.expected_revision, 1)
            await wait_until(lambda: scheduler.status.completed == 1)
            self.assertEqual(self.coordinator.calls[-2:], [1, 1])
            await scheduler.stop()

    async def test_busy_with_durable_journal_and_uncertain_errors_stop_instead_of_retrying(self):
        for error in (LiveSaveError("rom_busy", "late refusal"), asyncio.TimeoutError(),
                      LiveSaveError("rom_canceled", "cancelled operation"), ValueError("fault")):
            scheduler = self.scheduler()
            self.coordinator.error = error
            self.coordinator.hook = lambda: self.coordinator.pending_path.write_text("private durable intent")
            await scheduler.start()
            scheduler.request()
            await wait_until(lambda: scheduler.status.state is AutosaveState.RECOVERY_REQUIRED)
            calls = len(self.coordinator.calls)
            self.clock.value += 1000
            self.fresh()
            self.assertFalse(scheduler.request())
            await asyncio.sleep(.035)
            self.assertEqual(len(self.coordinator.calls), calls)
            self.assertEqual(scheduler.status.expected_revision, 1)
            self.assertEqual(self.coordinator.pending_path.read_text(), "private durable intent")
            with self.assertRaises(AutosaveError):
                await scheduler.start()
            await scheduler.stop()
            self.coordinator.pending_path.unlink()
            self.coordinator.hook = None

    async def test_unmarked_busy_or_unsafe_without_journal_is_terminal(self):
        for code in ("rom_busy", "rom_unsafe"):
            scheduler = self.scheduler()
            self.coordinator.error = LiveSaveError(code, "not proven to be an admission refusal")
            await scheduler.start()
            scheduler.request()
            await wait_until(lambda: scheduler.status.state is AutosaveState.RECOVERY_REQUIRED)
            calls = len(self.coordinator.calls)
            await asyncio.sleep(.04)
            self.assertEqual(len(self.coordinator.calls), calls)
            self.assertFalse(self.coordinator.pending_path.exists())
            self.assertEqual(scheduler.status.expected_revision, 1)
            await scheduler.stop()

    async def test_loss_and_changed_world_lease_incarnation_or_build_are_terminal(self):
        for target, name, value in ((self.c, "connected", False), (self.c, "world_id", str(uuid4())),
                                   (self.c, "session_epoch", 77), (self.c, "save_incarnation", 88),
                                   (self.c, "server_epoch", 2), (self.c.config, "build_id", "b"*64),
                                   (self.c, "save_profile", "wrong-profile")):
            scheduler = self.scheduler()
            await scheduler.start()
            original = getattr(target, name)
            setattr(target, name, value)
            await wait_until(lambda: scheduler.status.state is AutosaveState.RECOVERY_REQUIRED)
            setattr(target, name, original)
            self.assertFalse(scheduler.request())
            self.assertEqual(self.coordinator.calls, [])
            await scheduler.stop()

    async def test_lost_connection_during_export_does_not_adopt_returned_revision(self):
        scheduler = self.scheduler()
        self.coordinator.release = asyncio.Event()
        await scheduler.start()
        scheduler.request()
        await self.coordinator.started.wait()
        self.c.connected = False
        self.coordinator.release.set()
        await wait_until(lambda: scheduler.status.state is AutosaveState.RECOVERY_REQUIRED)
        self.assertEqual(scheduler.status.expected_revision, 1)
        self.assertIsNone(scheduler.last_result)
        self.assertFalse(self.coordinator.cancelled)

    async def test_session_change_before_child_starts_never_invokes_the_coordinator(self):
        def change_before_spawn(status):
            if status.state is AutosaveState.SAVING:
                self.c.session_epoch += 1
        scheduler = self.scheduler(on_status=change_before_spawn)
        await scheduler.start()
        scheduler.request()
        await wait_until(lambda: scheduler.status.state is AutosaveState.RECOVERY_REQUIRED)
        self.assertEqual(scheduler.status.code, "session_changed")
        self.assertEqual(self.coordinator.calls, [])
        self.assertEqual(scheduler.status.expected_revision, 1)

    async def test_wrong_revision_hash_request_or_profile_cannot_advance_verified_cursor(self):
        for changes in (dict(revision=3), dict(sha256="e"*64), dict(request_id=str(uuid4())),
                        dict(save_profile="other-profile")):
            scheduler = self.scheduler()
            self.coordinator.result_transform = lambda result: replace(result, metadata={**result.metadata, **changes})
            await scheduler.start()
            scheduler.request()
            await wait_until(lambda: scheduler.status.state is AutosaveState.RECOVERY_REQUIRED)
            self.assertEqual(scheduler.status.expected_revision, 1)
            self.assertEqual(scheduler.status.code, "checkpoint_result")
            await scheduler.stop()

    async def test_stop_is_idempotent_and_repeated_caller_cancellation_waits_for_export(self):
        scheduler = self.scheduler()
        self.coordinator.release = asyncio.Event()
        await scheduler.start()
        scheduler.request()
        await self.coordinator.started.wait()
        first, second = asyncio.create_task(scheduler.stop()), asyncio.create_task(scheduler.stop())
        await asyncio.sleep(.02)
        first.cancel()
        await asyncio.sleep(.02)
        first.cancel()
        self.assertFalse(first.done())
        self.assertFalse(second.done())
        self.assertFalse(self.coordinator.cancelled)
        self.assertFalse(scheduler.request())
        self.coordinator.release.set()
        with self.assertRaises(asyncio.CancelledError):
            await first
        await second
        await scheduler.stop()
        self.assertEqual(scheduler.status.completed, 1)
        self.assertEqual(scheduler.status.state, AutosaveState.STOPPED)
        self.assertIsNone(self.c._autosave_owner)

    async def test_observer_failure_cannot_cancel_export_and_gate_failure_prevents_export(self):
        def broken_observer(status):
            raise asyncio.CancelledError()
        scheduler = self.scheduler(on_status=broken_observer)
        await scheduler.start()
        scheduler.request()
        await wait_until(lambda: scheduler.status.completed == 1)
        self.assertGreater(scheduler.status.callback_errors, 0)
        self.assertFalse(self.coordinator.cancelled)
        await scheduler.stop()
        def broken_gate():
            raise RuntimeError("untrusted callback detail must not appear in status")
        blocked = self.scheduler(safe_point=broken_gate)
        await blocked.start()
        blocked.request()
        await wait_until(lambda: blocked.status.state is AutosaveState.RECOVERY_REQUIRED)
        self.assertEqual(blocked.status.code, "gate_failed")
        self.assertEqual(self.coordinator.calls, [1])

    async def test_one_scheduler_per_companion_and_pending_export_blocks_start(self):
        first, second = self.scheduler(), self.scheduler()
        await first.start()
        with self.assertRaises(AutosaveError) as caught:
            await second.start()
        self.assertEqual(caught.exception.code, "scheduler_active")
        await first.stop()
        self.coordinator.pending_path.write_text("unresolved")
        with self.assertRaises(AutosaveError) as caught:
            await second.start()
        self.assertEqual(caught.exception.code, "pending_export")
        self.assertEqual(second.status.state, AutosaveState.RECOVERY_REQUIRED)
        self.assertEqual(self.coordinator.calls, [])

    async def test_external_worker_cancellation_preserves_inflight_lifecycle(self):
        scheduler = self.scheduler()
        self.coordinator.release = asyncio.Event()
        await scheduler.start()
        scheduler.request()
        await self.coordinator.started.wait()
        scheduler._task.cancel()
        await asyncio.sleep(.02)
        scheduler._task.cancel()
        self.assertFalse(scheduler._task.done())
        self.assertFalse(self.coordinator.cancelled)
        self.coordinator.release.set()
        await wait_until(lambda: scheduler.status.state is AutosaveState.RECOVERY_REQUIRED)
        self.assertEqual(scheduler.status.code, "scheduler_canceled")
        self.assertEqual(scheduler.status.expected_revision, 1)

    async def test_cancelled_worker_cannot_turn_a_later_busy_error_into_an_automatic_retry(self):
        scheduler = self.scheduler()
        self.coordinator.release = asyncio.Event()
        self.coordinator.error = LiveSaveError("rom_busy", "definite but after scheduler cancellation", safe_to_retry=True)
        await scheduler.start()
        scheduler.request()
        await self.coordinator.started.wait()
        scheduler._task.cancel()
        await asyncio.sleep(.02)
        self.coordinator.release.set()
        await wait_until(lambda: scheduler.status.state is AutosaveState.RECOVERY_REQUIRED)
        self.assertEqual(scheduler.status.code, "scheduler_canceled")
        self.assertEqual(self.coordinator.calls, [1])
        self.assertFalse(self.coordinator.cancelled)

    async def test_missing_credentials_bridge_or_capability_cannot_start_autosave(self):
        for target, name, value in ((self.c.config, "server_credential", None),
                                   (self.c.config, "save_enabled", False),
                                   (self.c, "_bridge", None), (self.c, "connected", False)):
            scheduler = self.scheduler()
            old = getattr(target, name)
            setattr(target, name, value)
            with self.assertRaises(AutosaveError):
                await scheduler.start()
            setattr(target, name, old)
            self.assertEqual(scheduler.status.state, AutosaveState.RECOVERY_REQUIRED)
            self.assertEqual(self.coordinator.calls, [])

    async def test_backwards_or_nonfinite_clock_stops_without_an_export(self):
        for value in (90, float("nan"), float("inf")):
            self.clock.value = 100
            scheduler = self.scheduler()
            await scheduler.start()
            self.clock.value = value
            scheduler.request()
            await wait_until(lambda: scheduler.status.state is AutosaveState.RECOVERY_REQUIRED)
            self.assertEqual(scheduler.status.code, "clock_invalid")
            self.assertEqual(self.coordinator.calls, [])
            await scheduler.stop()


class RealCoordinatorAutosaveTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.clock = Clock()
        self.c = FakeCompanion(self.root)
        self.c.config.server_credential = self.c.identity.credential
        self.c.config.save_enabled = True
        self.c.config.ownership_enabled = False
        self.c.config.pause_timeout = .5
        self.c.server_epoch = self.c.store.metadata.server_epoch
        self.c._bridge = SimpleNamespace(save_capable=True)
        self.c._local_pose, self.c._last_pose_time = make_pose(), self.clock()
        self.coordinator = LiveCheckpointCoordinator(self.c, self.root / "live")
        self.c.pending_journal = self.coordinator.pending_path
        self.scheduler = AutosaveScheduler(self.coordinator, expected_revision=1, interval=10,
                                           poll_interval=.02, clock=self.clock)
        self.native_path = self.root / "character.sav"
        self.native_path.write_bytes(b"closed-file sentinel: scheduler must never touch this")

    async def asyncTearDown(self):
        await self.scheduler.stop()
        self.assertEqual(self.native_path.read_bytes(), b"closed-file sentinel: scheduler must never touch this")
        self.c.close()
        self.temp.cleanup()

    async def test_real_checkpoint_uses_verified_base_all_chunks_durable_intent_and_sqlite_ack(self):
        await self.scheduler.start()
        self.scheduler.request()
        await wait_until(lambda: self.scheduler.status.completed == 1)
        self.assertEqual(self.c.head().revision, 2)
        self.assertEqual(self.c.head().payload, self.c.rom_flash)
        self.assertEqual(self.scheduler.status.expected_revision, 2)
        self.assertFalse(self.coordinator.pending_path.exists())
        self.assertEqual([c.opcode for c in self.c.commands],
                         [Opcode.BIND, Opcode.BEGIN_EXPORT] + [Opcode.READ]*1024 + [Opcode.END])
        self.assertEqual(self.c.upload_payloads[0][:2], (self.scheduler.last_result.operation_id, 1))
        self.assertIsNone(self.c.mode)
        self.c.store.integrity_check()

    async def test_real_session_change_while_waiting_for_lifecycle_lock_precedes_all_rpcs(self):
        acquired, release = asyncio.Event(), asyncio.Event()
        holder = None
        async def hold_lifecycle():
            async with self.c.live_checkpoint_lock:
                acquired.set()
                await release.wait()
        def lock_before_child(status):
            nonlocal holder
            if status.state is AutosaveState.SAVING:
                holder = asyncio.create_task(hold_lifecycle())
        self.scheduler.on_status = lock_before_child
        try:
            await self.scheduler.start()
            self.scheduler.request()
            await acquired.wait()
            await asyncio.sleep(.02)
            self.assertFalse(self.scheduler._inflight.done())
            self.assertEqual(self.c.commands, [])
            self.assertEqual(self.c.server_calls, [])
            self.c.restart()
            release.set()
            await wait_until(lambda: self.scheduler.status.state is AutosaveState.RECOVERY_REQUIRED)
            self.assertEqual(self.c.commands, [])
            self.assertEqual(self.c.server_calls, [])
            self.assertEqual(self.c.upload_payloads, [])
            self.assertEqual(self.scheduler.status.expected_revision, 1)
            self.assertFalse(self.coordinator.pending_path.exists())
        finally:
            release.set()
            if holder is not None:
                await holder

    async def test_real_lost_ack_stops_preserves_exact_journal_and_requires_explicit_resolution(self):
        self.c.lose_commit_ack = True
        await self.scheduler.start()
        self.scheduler.request()
        await wait_until(lambda: self.scheduler.status.state is AutosaveState.RECOVERY_REQUIRED)
        journal = self.coordinator.pending_path.read_bytes()
        self.assertEqual(self.c.head().revision, 2)
        self.assertEqual(self.scheduler.status.expected_revision, 1)
        calls = len(self.c.commands)
        self.clock.value += 100
        self.c._last_pose_time = self.clock()
        await asyncio.sleep(.04)
        self.assertEqual(len(self.c.commands), calls)
        self.assertEqual(self.coordinator.pending_path.read_bytes(), journal)
        await self.scheduler.stop()
        resolved = await self.coordinator.resolve_pending()
        self.assertEqual(resolved["revision"], 2)
        self.assertFalse(self.coordinator.pending_path.exists())
        self.assertEqual(self.c.head().revision, 2)

    async def test_real_external_head_change_stops_before_any_rom_command(self):
        self.c.advance_head(self.c.rom_flash)
        await self.scheduler.start()
        self.scheduler.request()
        await wait_until(lambda: self.scheduler.status.state is AutosaveState.RECOVERY_REQUIRED)
        self.assertEqual(self.scheduler.status.code, "revision_conflict")
        self.assertEqual(self.scheduler.status.expected_revision, 1)
        self.assertEqual(self.c.commands, [])
        self.assertFalse(self.coordinator.pending_path.exists())

    async def test_real_initial_begin_unsafe_is_marked_and_retries_only_same_verified_base(self):
        original = self.c.save_rpc
        refused = False
        async def refuse_first_begin(control, **kwargs):
            nonlocal refused
            if control.opcode == Opcode.BEGIN_EXPORT and not refused:
                refused = True
                self.c.commands.append(control)
                self.c._local_pose = make_pose(activity=0)
                return replace(control, status=Status.UNSAFE)
            return await original(control, **kwargs)
        self.c.save_rpc = refuse_first_begin
        await self.scheduler.start()
        self.scheduler.request()
        await wait_until(lambda: self.scheduler.status.code == "game_unavailable")
        self.assertEqual(self.scheduler.status.state, AutosaveState.DEFERRED)
        self.assertEqual(self.scheduler.status.expected_revision, 1)
        self.assertIsNone(self.c.mode)
        self.assertEqual(self.c.head().revision, 1)
        self.assertFalse(self.coordinator.pending_path.exists())
        self.c._local_pose = make_pose()
        await wait_until(lambda: self.scheduler.status.completed == 1)
        begins = [c for c in self.c.commands if c.opcode == Opcode.BEGIN_EXPORT]
        self.assertEqual(len(begins), 2)
        self.assertEqual([c.revision for c in begins], [2, 2])
        self.assertEqual(self.c.head().revision, 2)
        self.assertEqual([base for operation, base, payload in self.c.upload_payloads], [1])

    async def test_real_read_busy_then_lost_cancel_is_terminal_without_a_durable_journal(self):
        original = self.c.save_rpc
        async def fail_after_begin(control, **kwargs):
            if control.opcode == Opcode.READ:
                self.c.commands.append(control)
                return replace(control, status=Status.BUSY)
            if control.opcode == Opcode.CANCEL:
                self.c.commands.append(control)
                raise asyncio.TimeoutError("cancel acknowledgement lost while ROM remains frozen")
            return await original(control, **kwargs)
        self.c.save_rpc = fail_after_begin
        await self.scheduler.start()
        self.scheduler.request()
        await wait_until(lambda: self.scheduler.status.state is AutosaveState.RECOVERY_REQUIRED)
        self.assertEqual(self.scheduler.status.code, "rom_busy")
        self.assertEqual(self.scheduler.status.expected_revision, 1)
        self.assertEqual(self.c.head().revision, 1)
        self.assertEqual(self.c.mode, "export")
        self.assertFalse(self.coordinator.pending_path.exists())
        self.assertEqual([c.opcode for c in self.c.commands],
                         [Opcode.BIND, Opcode.BEGIN_EXPORT, Opcode.READ, Opcode.CANCEL])
        calls = len(self.c.commands)
        await asyncio.sleep(.04)
        self.assertEqual(len(self.c.commands), calls)
