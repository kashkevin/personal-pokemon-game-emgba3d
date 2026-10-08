"""Opt-in, always-connected scheduling of verified live checkpoints.

There is no shipping interval, enrollment, offline mode, automatic recovery, or
save-file access here. The caller supplies the revision proven by launch/recovery
and stops this scheduler before closing its owned core.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from enum import Enum
import inspect
import math
from pathlib import Path
from typing import Callable
from uuid import UUID

from .checkpoint_client import validate_metadata
from .flash import FLASH_SIZE, LAYOUT_ID
from .live_checkpoint import LiveExportResult, LiveSaveError
from .mailbox import Pose
from .ownership import OWNERSHIP_PROFILE
from .protocol import MAX_COUNTER


class AutosaveError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class AutosaveState(str, Enum):
    NEW = "new"
    WAITING = "waiting"
    DEFERRED = "deferred"
    SAVING = "saving"
    STOPPING = "stopping"
    STOPPED = "stopped"
    RECOVERY_REQUIRED = "recovery_required"


@dataclass(frozen=True)
class AutosaveStatus:
    state: AutosaveState
    code: str
    expected_revision: int
    completed: int = 0
    callback_errors: int = 0


def _duration(value, name):
    if type(value) not in (float, int) or not math.isfinite(value) or not 0 < value <= 86_400:
        raise ValueError(f"{name} must be finite, positive, and at most one day")


async def _drain(task):
    """Wait through repeated caller cancellation without cancelling a save."""
    canceled = False
    while not task.done():
        try:
            # wait() never cancels its child or forwards its exception. The
            # caller retrieves result() exactly once after draining; this also
            # avoids Python 3.14 shield's late-exception cancellation logging.
            await asyncio.wait((task,))
        except asyncio.CancelledError:
            canceled = True
    return canceled


class AutosaveScheduler:
    """One coalesced worker, tied to one authenticated game incarnation.

    ``safe_point`` is a synchronous additional battle/reset/runtime gate. It
    supplements fresh local pose checks; the ROM remains the final authority.
    ``on_status`` is a synchronous observer. Its errors cannot cancel a save.
    A failure/reconnect is terminal: explicitly reconcile and create a new
    scheduler using the resulting verified revision, never the server head.
    """

    def __init__(self, coordinator, *, expected_revision: int, interval: float,
                 poll_interval: float = 0.25, safe_point: Callable[[], bool] | None = None,
                 on_status: Callable[[AutosaveStatus], None] | None = None,
                 clock: Callable[[], float] | None = None):
        if type(expected_revision) is not int or not 1 <= expected_revision < MAX_COUNTER:
            raise ValueError("autosave needs an existing verified local revision below the counter limit")
        _duration(interval, "autosave interval")
        _duration(poll_interval, "poll interval")
        if poll_interval > 30:
            raise ValueError("poll interval must be at most 30 seconds")
        for callback in (safe_point, on_status, clock):
            if callback is not None and (not callable(callback) or inspect.iscoroutinefunction(callback)):
                raise ValueError("autosave callbacks and clock must be synchronous callables")
        self.coordinator, self.companion = coordinator, coordinator.companion
        self.interval, self.poll_interval = float(interval), float(poll_interval)
        self.safe_point, self.on_status = safe_point, on_status
        self.clock = clock or (lambda: asyncio.get_running_loop().time())
        self.status = AutosaveStatus(AutosaveState.NEW, "not_started", expected_revision)
        self.last_result: LiveExportResult | None = None
        self._task: asyncio.Task | None = None
        self._inflight: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self._stop_requested = False
        self._due = False
        self._binding = None
        self._last_clock = None
        self._next_due = self._eligible_at = 0.0

    def _publish(self, state, code):
        new = replace(self.status, state=state, code=code)
        if new == self.status:
            return
        self.status = new
        if self.on_status is not None:
            try:
                result = self.on_status(new)
                if inspect.isawaitable(result):
                    if inspect.iscoroutine(result):
                        result.close()
                    raise TypeError("status observer returned an awaitable")
            except (Exception, asyncio.CancelledError):
                self.status = replace(self.status, callback_errors=self.status.callback_errors + 1)

    def _now(self):
        value = self.clock()
        if (type(value) not in (float, int) or not math.isfinite(value)
                or (self._last_clock is not None and value < self._last_clock)):
            raise AutosaveError("clock_invalid", "autosave requires a finite monotonic clock")
        self._last_clock = value
        return value

    def _session(self):
        c = self.companion
        try:
            for value in (c.world_id, c.config.player_id):
                if type(value) is not str or str(UUID(value)) != value or not UUID(value).int:
                    raise ValueError()
            credential = c.config.server_credential
            incarnation = c.save_incarnation
            if (not c.connected or type(credential) is not bytes or len(credential) != 32
                    or not getattr(c.config, "save_enabled", False)
                    or c.save_profile != (OWNERSHIP_PROFILE if getattr(c.config, "ownership_enabled", False) else LAYOUT_ID)
                    or type(c.session_epoch) is not int or not 1 <= c.session_epoch <= MAX_COUNTER
                    or type(c.server_epoch) is not int or not 1 <= c.server_epoch <= MAX_COUNTER
                    or type(incarnation) is not int or not 1 <= incarnation <= 0xFFFFFFFF
                    or c._bridge is None or not c._bridge.save_capable):
                raise ValueError()
            return (c.world_id, c.config.player_id, c.config.build_id, c.config.ruleset_id,
                    c.save_profile, c.server_epoch, c.session_epoch, incarnation)
        except (AttributeError, ValueError, TypeError, ConnectionError):
            raise AutosaveError("connection_lost", "autosave requires the same authenticated live-save bridge") from None

    def _unchanged_session(self):
        if self._session() != self._binding:
            raise AutosaveError("session_changed", "world, build, lease or game incarnation changed; verify recovery before restarting autosave")

    def _pending_export(self):
        return Path(self.coordinator.pending_path).exists()

    def _gate(self, now):
        c = self.companion
        trade_paths = [Path(self.coordinator.directory) / "pending-trade.json"]
        shared = getattr(c, "_live_trade_pending_path", None)
        if shared is not None:
            trade_paths.append(Path(shared))
        if any(path.exists() for path in trade_paths):
            return "pending_trade"
        if (c.live_checkpoint_lock.locked() or getattr(c, "_live_save_owner", None) is not None
                or getattr(c, "_save_pending", {}) or getattr(c, "_battle_pending", {})
                or getattr(c, "_bridge_admission_blocked", False)):
            return "lifecycle_busy"
        if self._pending_export():
            raise AutosaveError("pending_export", "resolve the durable export before restarting autosave")
        pose, seen = getattr(c, "_local_pose", None), getattr(c, "_last_pose_time", None)
        freshness = getattr(c.config, "pause_timeout", None)
        if (not isinstance(pose, Pose) or type(seen) not in (float, int) or not math.isfinite(seen)
                or type(freshness) not in (float, int) or not math.isfinite(freshness) or freshness <= 0
                or not 0 <= now - seen <= freshness
                or pose.network_fields(True)["activity"] != "overworld"):
            return "game_unavailable"
        if self.safe_point is not None:
            try:
                safe = self.safe_point()
                if type(safe) is not bool:
                    if inspect.iscoroutine(safe):
                        safe.close()
                    raise ValueError()
            except (Exception, asyncio.CancelledError):
                raise AutosaveError("gate_failed", "the extra battle/reset/runtime gate failed") from None
            if not safe:
                return "unsafe_scene"
        return None

    async def start(self):
        if self._task is not None or self.status.state is not AutosaveState.NEW:
            raise AutosaveError("already_started", "a stopped scheduler must be replaced after explicit verification")
        owner = getattr(self.companion, "_autosave_owner", None)
        if owner is not None and owner is not self:
            raise AutosaveError("scheduler_active", "one autosave scheduler already owns this companion")
        try:
            self._binding = self._session()
            now = self._now()
            if self._pending_export():
                raise AutosaveError("pending_export", "resolve the durable export before starting autosave")
        except (Exception, asyncio.CancelledError) as error:
            self._publish(AutosaveState.RECOVERY_REQUIRED, self._error_code(error))
            raise
        self._next_due, self._eligible_at = now + self.interval, now
        self.companion._autosave_owner = self
        self._publish(AutosaveState.WAITING, "timer")
        self._task = asyncio.create_task(self._run(), name="verified-autosave")

    def request(self):
        """Coalesce a due request; never bypass the interval after a completed save."""
        if (self._task is None or self._task.done() or self._stop_requested
                or self.status.state is AutosaveState.RECOVERY_REQUIRED):
            return False
        self._due = True
        self._wake.set()
        return True

    @staticmethod
    def _error_code(error):
        if isinstance(error, AutosaveError):
            return error.code
        if isinstance(error, LiveSaveError):
            return error.code
        return "checkpoint_uncertain"

    async def _checkpoint(self):
        # The child can start after queued disconnect/reconnect work. Check its
        # full scheduler binding, then ask the coordinator to fence the world,
        # lease and incarnation again after acquiring its lifecycle lock.
        self._unchanged_session()
        expected = self._binding[0], self._binding[6], self._binding[7]
        return await self.coordinator.checkpoint(
            expected_revision=self.status.expected_revision, expected_session=expected)

    async def _save(self):
        self._due = False
        self._publish(AutosaveState.SAVING, "checkpoint")
        # Independent task ownership lasts through every read/journal/ACK step.
        self._inflight = asyncio.create_task(self._checkpoint(), name="autosave-checkpoint")
        try:
            canceled = await _drain(self._inflight)
            try:
                result = self._inflight.result()
            except (Exception, asyncio.CancelledError):
                if canceled:
                    raise AutosaveError("scheduler_canceled", "scheduler cancellation requires explicit verification") from None
                raise
        finally:
            self._inflight = None
        if canceled:
            raise AutosaveError("scheduler_canceled", "scheduler cancellation requires explicit verification")
        self._unchanged_session()
        if not isinstance(result, LiveExportResult):
            raise AutosaveError("checkpoint_result", "checkpoint result has an unsupported type")
        try:
            metadata = validate_metadata(result.metadata, self.companion.config, self.companion.save_profile)
        except ValueError:
            raise AutosaveError("checkpoint_result", "checkpoint result has invalid metadata") from None
        if (metadata is None
                or metadata["revision"] != self.status.expected_revision + 1
                or metadata["request_id"] != result.operation_id
                or metadata["size"] != FLASH_SIZE or metadata["sha256"] != result.flash_sha256
                or self._pending_export()):
            raise AutosaveError("checkpoint_result", "checkpoint did not prove a complete matching revision")
        self.last_result = result
        self.status = replace(self.status, expected_revision=metadata["revision"], completed=self.status.completed + 1)
        now = self._now()
        self._eligible_at = self._next_due = now + self.interval
        self._publish(AutosaveState.WAITING, "timer")

    async def _run(self):
        try:
            while not self._stop_requested:
                self._unchanged_session()
                now = self._now()
                self._due |= now >= self._next_due
                if self._due and now >= self._eligible_at:
                    reason = self._gate(now)
                    if reason is not None:
                        self._publish(AutosaveState.DEFERRED, reason)
                    else:
                        try:
                            await self._save()
                        except LiveSaveError as error:
                            self._inflight = None
                            self._unchanged_session()
                            if (error.code not in {"rom_busy", "rom_unsafe"}
                                    or not getattr(error, "safe_to_retry", False)
                                    or self._pending_export()):
                                raise
                            # Definite pre-journal refusal only; no unknown fate
                            # is silently retried or changed to a new revision.
                            self._due = True
                            self._publish(AutosaveState.DEFERRED, error.code)
                if self._stop_requested:
                    break
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), self.poll_interval)
                except asyncio.TimeoutError:
                    pass
        except (Exception, asyncio.CancelledError) as error:
            self._publish(AutosaveState.RECOVERY_REQUIRED, self._error_code(error))
        finally:
            if self.status.state is not AutosaveState.RECOVERY_REQUIRED:
                self._publish(AutosaveState.STOPPED, "stopped")
            if getattr(self.companion, "_autosave_owner", None) is self:
                self.companion._autosave_owner = None

    async def stop(self):
        """Idempotent stop; wait for any checkpoint before the caller closes ROM."""
        self._stop_requested = True
        self._wake.set()
        if self._task is None:
            if self.status.state is not AutosaveState.RECOVERY_REQUIRED:
                self._publish(AutosaveState.STOPPED, "stopped")
            return
        if not self._task.done() and self.status.state is not AutosaveState.RECOVERY_REQUIRED:
            self._publish(AutosaveState.STOPPING, "waiting_for_checkpoint")
        canceled = await _drain(self._task)
        self._task.result()
        if canceled:
            raise asyncio.CancelledError()
