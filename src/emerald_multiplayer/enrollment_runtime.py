"""Explicit host-approved first enrollment; normal play still needs recovery.

This local backend accepts an existing wholly unassigned legacy save. It does
not register remote players, create a New Game, select offline policy or write
live emulator state. Only the native enrollment/export path assigns IDs.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import hashlib
from pathlib import Path

from .battle_journal import path_present
from .checkpoint_client import CheckpointClient
from .checkpoint_mirror import MirrorLease, sidecar_path
from .cold_start import ColdStartRecovery
from .companion import verify_rom_manifest
from .flash import LAYOUT_ID, MAX_CONTAINER_SIZE, inspect_flash
from .live_checkpoint import LiveCheckpointCoordinator, _atomic, _json_bytes, _sync_directory
from .ownership import OWNERSHIP_PROFILE, extract_source_inventory
from .player_runtime import NativeGame, _finish_even_if_cancelled, _open_child, _preflight_launch, _stop
from .trade_storage import TradeCheckpointStore


class EnrollmentRuntimeError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _source_bytes(path):
    with Path(path).open("rb") as source:
        payload = source.read(MAX_CONTAINER_SIZE + 1)
    if len(payload) > MAX_CONTAINER_SIZE:
        raise EnrollmentRuntimeError("invalid_source", "the enrollment source exceeds its save size limit")
    extract_source_inventory(inspect_flash(payload, save_profile=LAYOUT_ID))
    return payload


@dataclass(frozen=True)
class EnrollmentApproval:
    """Local host authorization, obtained through approve_enrollment_source.

    This is an application value, not a network capability or registration RPC.
    The server independently enforces its stored source provenance and grants.
    """
    world_id: str
    player_id: str
    build_id: str
    ruleset_id: str
    source_sha256: str
    source_path: Path = field(repr=False)
    payload: bytes = field(repr=False)


def approve_enrollment_source(store, player_id, source_path, *, expected_source_sha256=None):
    """Explicit local-host mutation: authorize exact source provenance once."""
    if not isinstance(store, TradeCheckpointStore):
        raise EnrollmentRuntimeError("unsupported_world", "first enrollment requires a schema-3 host world")
    path = Path(source_path).resolve(strict=True)
    payload = _source_bytes(path)
    if (expected_source_sha256 is not None
            and hashlib.sha256(payload).hexdigest() != expected_source_sha256):
        raise EnrollmentRuntimeError("source_changed", "the selected source changed before host approval")
    enrollment = store.enroll_player(player_id, payload)
    return EnrollmentApproval(store.metadata.world_id, player_id, store.build_id,
                              store.ruleset_id, enrollment.source_sha256, path, payload)


class EnrollmentRuntime:
    """One bootstrap child under a continuous exclusive private save lease.

    Authenticate the companion first. Inside open(), use ordinary Continue,
    then explicitly await enroll() when the native game reaches a safe field
    point. Successful enrollment closes the bootstrap child before returning.
    Subsequent play uses PlayerRuntime/ColdStartRecovery. No automatic retry or
    rollback follows an uncertain export; recover() resolves closed evidence.
    """

    def __init__(self, companion, bundle, private_directory, save_path, approval, *, launch_root=None):
        self.companion, self.bundle, self.approval = companion, bundle, approval
        self.directory = Path(private_directory).resolve()
        self.save_path = Path(save_path).resolve()
        self.launch_root = Path(launch_root).resolve() if launch_root is not None else None
        if self.save_path.parent != self.directory:
            raise EnrollmentRuntimeError("private_path", "the enrollment mirror must stay inside its private profile")
        if not isinstance(approval, EnrollmentApproval) or self.save_path == approval.source_path:
            raise EnrollmentRuntimeError("invalid_source", "an approved original source must be separate from its private mirror")
        self.pending_path = self.directory / "pending-enrollment.json"
        self.source_copy = self.directory / "enrollment-source.flash"
        self.receipt_path = self.directory / "enrollment-completed.json"
        self._entered = self._active = self._closing = self._attempted = False
        self._game = self._task = self._gate = self._session = None
        self.result = None

    def _identity(self, gate):
        session = gate._session()
        a = self.approval
        if (a.world_id, a.player_id, a.build_id, a.ruleset_id) != (
                session[0], session[4], session[5], session[6]) or session[3] != OWNERSHIP_PROFILE:
            raise EnrollmentRuntimeError("approval_identity", "source approval belongs to another world, character or build")
        if hashlib.sha256(a.payload).hexdigest() != a.source_sha256:
            raise EnrollmentRuntimeError("source_changed", "the approved source bytes changed")
        extract_source_inventory(inspect_flash(a.payload, save_profile=LAYOUT_ID))
        return session

    def _check_session(self):
        if self._closing or self._identity(self._gate) != self._session:
            raise EnrollmentRuntimeError("session_changed", "the authenticated enrollment session changed")

    def _intent(self):
        a = self.approval
        return dict(format="emerald-first-enrollment-v1", world_id=a.world_id,
                    player_id=a.player_id, build_id=a.build_id, ruleset_id=a.ruleset_id,
                    save_profile=OWNERSHIP_PROFILE, source_sha256=a.source_sha256)

    def _clear_initial_paths(self, gate):
        paths = [gate.export_path, gate.trade_path, self.pending_path, self.source_copy,
                 self.receipt_path, self.save_path, sidecar_path(self.save_path)]
        if any(path_present(path) for path in paths):
            raise EnrollmentRuntimeError("recovery_required", "existing enrollment, save or journal requires closed recovery")

    async def _drain_enrollment(self):
        if self._task is not None and self._task is not asyncio.current_task() and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    @asynccontextmanager
    async def open(self):
        if self._entered:
            raise EnrollmentRuntimeError("session_used", "each enrollment runtime can be entered only once")
        self._entered = True
        executable, bridge = self.bundle.verify()
        c = self.companion
        build, manifest = verify_rom_manifest(c.config.rom_path, c.config.manifest_path)
        if build != c.config.build_id:
            raise EnrollmentRuntimeError("game_changed", "the installed game differs from the authenticated build")
        if isinstance(bridge, NativeGame) and bridge.rom_sha256 != build:
            raise EnrollmentRuntimeError("game_changed", "the native game was built for another ROM")
        _preflight_launch(executable, c.config.rom_path, self.save_path, self.directory,
                          launch_root=self.launch_root)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        for name in ("_live_export_pending_path", "_live_trade_pending_path", "_live_battle_pending_path"):
            registered = getattr(c, name, None)
            if registered is not None and path_present(registered):
                raise EnrollmentRuntimeError("recovery_required", "registered lifecycle intent requires closed recovery")
        gate = self._gate = ColdStartRecovery(c, self.directory, self.save_path)
        with MirrorLease(self.save_path):
            if getattr(c, "_cold_start_active", False) or getattr(c, "_bridge_admission_blocked", False):
                raise EnrollmentRuntimeError("startup_active", "another lifecycle owns startup admission")
            c._cold_start_active = True
            c._bridge_admission_blocked = True
            try:
                async with c.live_checkpoint_lock:
                    session = self._session = self._identity(gate)
                    gate._closed(session)
                    self._clear_initial_paths(gate)
                    if _source_bytes(self.approval.source_path) != self.approval.payload:
                        raise EnrollmentRuntimeError("source_changed", "the approved original source changed before copying")
                    c._live_save_owner = asyncio.current_task()
                    try:
                        head = await CheckpointClient(c).info()
                        gate._closed(session)
                        if head is not None:
                            raise EnrollmentRuntimeError("already_enrolled", "use normal recovery for an existing canonical character")
                        pending = await c.trade_rpc("pending")
                        gate._closed(session)
                        if pending["recoveries"]:
                            raise EnrollmentRuntimeError("recovery_required", "committed trade recovery precedes character admission")
                        self._clear_initial_paths(gate)
                        _atomic(self.source_copy, self.approval.payload)
                        _atomic(self.pending_path, _json_bytes(self._intent()))
                        _atomic(self.save_path, self.approval.payload)
                    finally:
                        c._live_save_owner = None
                gate._closed(session)
                c._bridge_admission_blocked = False
                async with _open_child(c, self.bundle, self.directory, self.save_path,
                                       build, manifest, self._check_session,
                                       launch_root=self.launch_root) as game:
                    self._game, self._active = game, True
                    try:
                        yield game
                    finally:
                        self._closing = True
                        cleanup = asyncio.create_task(self._drain_enrollment())
                        _, cancelled = await _finish_even_if_cancelled(cleanup)
                        if cancelled:
                            raise asyncio.CancelledError()
            finally:
                self._active = False
                c._bridge_admission_blocked = False
                c._cold_start_active = False

    async def enroll(self):
        if not self._active or self._closing or self._game.process.returncode is not None:
            raise EnrollmentRuntimeError("game_closed", "first enrollment requires its active bootstrap game")
        if self._task is not None or self._attempted:
            raise EnrollmentRuntimeError("enrollment_started", "resolve the prior enrollment before another attempt")
        self._check_session()
        coordinator = LiveCheckpointCoordinator(self.companion, self.directory)
        native_session = coordinator._session()
        self._task, self._attempted = asyncio.current_task(), True
        try:
            result = await coordinator.enroll(expected_session=native_session)
            self._check_session()
            if result.metadata["revision"] != 1:
                raise EnrollmentRuntimeError("revision_conflict", "first enrollment did not establish revision one")
            stop = asyncio.create_task(_stop(self._game.process))
            _, cancelled = await _finish_even_if_cancelled(stop)
            if cancelled:
                raise asyncio.CancelledError()
            # The verified export and session were fenced immediately before
            # our own stop. Bridge EOF deliberately revokes that connection.
            # Complete only this exact local enrollment receipt; any next
            # game must establish a fresh session and canonical recovery.
            if self._game.process.returncode is None:
                raise EnrollmentRuntimeError("game_active", "bootstrap child has not closed")
            self._complete(result.metadata)
            self.result = result
            return result
        except Exception as error:
            if getattr(error, "safe_to_retry", False):
                self._attempted = False
            raise
        finally:
            self._task = None

    def _complete(self, metadata):
        self._verify_attempt()
        _atomic(self.receipt_path, _json_bytes(dict(self._intent(), checkpoint=metadata)))
        # Keep the immutable source and every native grant/export receipt.
        self.pending_path.unlink()
        _sync_directory(self.directory)

    def _verify_attempt(self):
        with self.pending_path.open("rb") as source:
            raw = source.read(4097)
        if len(raw) > 4096 or raw != _json_bytes(self._intent()):
            raise EnrollmentRuntimeError("recovery_required", "pending enrollment differs from its exact approved identity")
        if _source_bytes(self.source_copy) != self.approval.payload:
            raise EnrollmentRuntimeError("source_changed", "the retained enrollment source changed")

    async def recover(self):
        """Closed exact-export reconciliation only; never launches or recopies."""
        if self._entered:
            raise EnrollmentRuntimeError("session_used", "closed recovery requires a fresh runtime object")
        self._entered = True
        gate = ColdStartRecovery(self.companion, self.directory, self.save_path)
        expected_session = self._identity(gate)
        # Do not reinterpret malformed/foreign attempts as a fresh enrollment.
        self._verify_attempt()
        async with gate.open(expected_session=expected_session) as result:
            # ColdStartRecovery owns the lease and resolves any pending exact
            # export before installing the current canonical owned character.
            self._complete({name: getattr(result.mirror, name) for name in (
                "revision", "request_id", "sha256", "size", "build_id", "ruleset_id", "save_profile")})
            return result
