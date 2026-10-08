"""Canonical startup reconciliation while the emulator is still closed.

This development primitive uses authenticated checkpoint/trade RPCs and the
existing closed-save mirror. It never calls the ROM mailbox, merges offline
progress, confirms a trade, or launches a core. The caller must honor the same
MirrorLease for the entire core lifetime and close its core before leaving.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
import hashlib
from pathlib import Path
from uuid import UUID, uuid4

from .battle_journal import pending_battle, register_battle_path
from .checkpoint_client import CheckpointClient, validate_metadata
from .checkpoint_mirror import (
    MirrorInfo, MirrorLease, inspect_mirror_held, restore_checkpoint_held,
)
from .flash import LAYOUT_ID, inspect_flash
from .live_checkpoint import LiveCheckpointCoordinator, _atomic, _json_bytes, _sync_directory, register_export_path
from .live_trade import LiveTradeCoordinator, _LIMIT as TRADE_JOURNAL_LIMIT
from .ownership import OWNERSHIP_PROFILE, inspect_ownership
from .protocol import MAX_COUNTER


class ColdStartError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ClosedStartResult:
    mirror: MirrorInfo
    lease: MirrorLease
    evidence_path: Path


class _ClosedTradeReader(LiveTradeCoordinator):
    """Reuse strict journal/byte/receipt validation without a running binding.

    The live coordinator remains unchanged. Cold recovery deliberately checks
    the authenticated character rather than the old companion/runtime UUID;
    no asynchronous live method of this reader is used.
    """

    def __init__(self, companion, directory):
        self.companion, self.directory = companion, directory
        self.trade_path = directory / "pending-trade.json"

    def _check_running(self, intent, session):
        pass


class ColdStartRecovery:
    """Authenticate first, then ``async with recovery.open() as verified``.

    Only after the context yields may the caller open its emulator. Keep the
    context entered until that core has closed. Missing canonical enrollment,
    changed leases, corrupt journals and historical trade/newer-head conflicts
    all prevent a yield and preserve recovery inputs. There is no offline mode.
    """

    def __init__(self, companion, private_directory: str | Path, save_path: str | Path):
        self.companion = companion
        self.directory = Path(private_directory).resolve()
        self.save_path = Path(save_path).resolve()
        self.client = CheckpointClient(companion)
        self.directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.export_path = self.directory / "pending-export.json"
        self.emergency_path = self.directory / "pending-emergency.json"
        self.trade_path = self.directory / "pending-trade.json"
        try:
            register_export_path(companion, self.export_path)
        except ValueError as error:
            raise ColdStartError("pending_export", "another private directory owns this character's export recovery") from error
        try:
            register_battle_path(companion, self.directory / "pending-battle.json")
        except ValueError as error:
            raise ColdStartError("pending_battle", "another private directory owns pending battle recovery") from error
        previous = getattr(companion, "_live_trade_pending_path", None)
        if previous is not None and Path(previous) != self.trade_path and Path(previous).exists():
            raise ColdStartError("pending_trade", "another private directory owns this character's trade recovery")
        companion._live_trade_pending_path = self.trade_path

    def _session(self):
        c = self.companion
        try:
            credential = c.config.server_credential
            if not isinstance(credential, bytes) or len(credential) != 32:
                raise ValueError()
            for value in (c.world_id, c.config.player_id):
                if not isinstance(value, str) or str(UUID(value)) != value or not UUID(value).int:
                    raise ValueError()
            if (not c.connected or type(c.session_epoch) is not int or not 1 <= c.session_epoch <= MAX_COUNTER
                    or type(c.server_epoch) is not int or not 1 <= c.server_epoch <= MAX_COUNTER
                    or c.save_profile != (OWNERSHIP_PROFILE if getattr(c.config, "ownership_enabled", False) else LAYOUT_ID)):
                raise ValueError()
        except (AttributeError, TypeError, ValueError):
            raise ColdStartError("authentication_required", "startup needs a provisioned authenticated durable world session") from None
        return (c.world_id, c.session_epoch, c.server_epoch, c.save_profile,
                c.config.player_id, c.config.build_id, c.config.ruleset_id)

    def _closed(self, session):
        if pending_battle(self.companion, self.directory):
            raise ColdStartError("pending_battle", "pending battle requires explicit recovery; cold startup cannot settle it")
        if self._session() != session:
            raise ConnectionError("authenticated startup session changed; retain recovery intent")
        if getattr(self.companion, "_bridge", None) is not None:
            raise ColdStartError("game_active", "close the game before canonical startup reconciliation")

    @staticmethod
    def _read(path, limit):
        try:
            with path.open("rb") as source:
                raw = source.read(limit+1)
        except FileNotFoundError:
            return None
        if len(raw) > limit:
            raise ColdStartError("invalid_journal", "startup journal exceeds its bounded format")
        return raw

    def _unchanged(self, raw):
        for path, original, limit in raw:
            if self._read(path, limit) != original:
                raise ColdStartError("journal_changed", "recovery intent changed while startup was reconciling")

    def _payload_owner(self, payload, session):
        parsed = inspect_flash(payload, save_profile=session[3])
        if session[3] == OWNERSHIP_PROFILE:
            owner = inspect_ownership(parsed)
            if (owner.world_id, owner.player_id) != (session[0], session[4]):
                raise ColdStartError("journal_identity", "frozen checkpoint belongs to another world or player")

    @staticmethod
    def _record(path, value):
        record = {"format": "emerald-closed-start-v1", "record": value,
                  "sha256": hashlib.sha256(_json_bytes(value)).hexdigest()}
        _atomic(path, _json_bytes(record))

    async def _rpc(self, session, operation, **fields):
        self._closed(session)
        response = await self.companion.trade_rpc(operation, **fields)
        self._closed(session)
        return response

    async def _head(self, session):
        self._closed(session)
        head = await self.client.info()
        self._closed(session)
        return validate_metadata(head, self.companion.config, session[3])

    async def _upload(self, session, payload, base, request_id):
        self._closed(session)
        self._payload_owner(payload, session)
        metadata = await self.client.upload(payload, base, transaction_id=request_id)
        self._closed(session)
        return metadata

    async def _reconcile(self, lease, session):
        raw = [(self.export_path, self._read(self.export_path, 4096), 4096),
               (self.trade_path, self._read(self.trade_path, TRADE_JOURNAL_LIMIT), TRADE_JOURNAL_LIMIT),
               (self.emergency_path, self._read(self.emergency_path, 16384), 16384)]
        if all(value is not None for _, value, _ in raw[:2]):
            raise ColdStartError("pending_conflict", "ordinary and trade recovery journals cannot both own this character")
        operation_id = str(uuid4())
        archive = self.directory / "closed-recoveries" / operation_id
        archive.mkdir(mode=0o700, parents=True)
        _sync_directory(archive.parent)
        for path, data, _ in raw:
            if data is not None:
                _atomic(archive / path.name, data)
        ordinary = LiveCheckpointCoordinator(self.companion, self.directory)
        exported = ordinary._load_pending((session[0], session[1], None)) if raw[0][1] is not None else None
        if raw[2][1] is not None:
            from .emergency_save import load_closed_emergency
            try:
                emergency_export = load_closed_emergency(self.directory, session)
            except (ValueError, TypeError, AttributeError, KeyError, OSError) as error:
                raise ColdStartError("emergency_recovery_required", "retain the interrupted core and its emergency evidence") from error
            if raw[1][1] is not None or exported is not None and exported != emergency_export:
                raise ColdStartError("pending_conflict", "emergency preservation conflicts with another recovery intent")
            exported = emergency_export
        trade = _ClosedTradeReader(self.companion, self.directory)
        intent = trade._load((session[0], session[1], None)) if raw[1][1] is not None else None
        self._unchanged(raw)
        self._closed(session)
        resolved_export = resolved_prepare = fate = None
        if exported is not None:
            journal, payload = exported
            resolved_export = await self._upload(session, payload, journal["expected_revision"], journal["operation_id"])
        if intent is not None:
            if not getattr(self.companion.config, "trade_enabled", False):
                raise ColdStartError("trade_unavailable", "this build cannot reconcile its pending trade")
            fate = (await self._rpc(session, "status", transaction_id=intent["transaction_id"]))["trade"]
            if fate["state"] == "offering":
                if fate["generation"] != intent["generation"]:
                    raise ColdStartError("trade_changed", "a new proposal generation cannot replace pending local recovery intent")
                fate = (await self._rpc(session, "cancel", transaction_id=intent["transaction_id"], generation=intent["generation"]))["trade"]
            if fate["state"] not in {"aborted", "committed"}:
                raise ColdStartError("trade_conflict", "startup could not establish authoritative trade fate")
            if intent["fate"] is not None and fate != intent["fate"]:
                raise ColdStartError("trade_conflict", "durable committed trade fate changed")
            if intent["frozen_sha256"] is not None:
                payload = trade._bytes(intent["prepare_id"]+".flash", intent["frozen_sha256"], 131072)
                resolved_prepare = await self._upload(session, payload, intent["expected_revision"], intent["prepare_id"])
                if intent["prepared"] is not None and resolved_prepare != intent["prepared"]:
                    raise ColdStartError("trade_conflict", "exact preparation retry changed immutable checkpoint metadata")
            elif fate["state"] == "committed":
                raise ColdStartError("trade_conflict", "a committed trade cannot lack its frozen preparation")
        recoveries = []
        if getattr(self.companion.config, "trade_enabled", False):
            recoveries = (await self._rpc(session, "pending"))["recoveries"]
        head = await self._head(session)
        if head is None:
            raise ColdStartError("enrollment_required", "this character has no canonical checkpoint to launch")
        recovery = recoveries[0] if recoveries else None
        if recovery is not None:
            if len(recoveries) != 1 or recovery["checkpoint"] != head:
                raise ColdStartError("revision_conflict", "pending trade is not the current canonical head")
            if intent is not None and recovery["transaction_id"] != intent["transaction_id"]:
                raise ColdStartError("trade_conflict", "another pending trade conflicts with local recovery intent")
            if fate is None:
                fate = (await self._rpc(session, "status", transaction_id=recovery["transaction_id"]))["trade"]
            if fate["state"] != "committed" or fate["outcome_fingerprint"] != recovery["outcome_fingerprint"]:
                raise ColdStartError("trade_conflict", "pending recovery lacks its immutable committed fate")
        if fate is not None and fate["state"] == "committed":
            expected_revision = intent["expected_revision"]+2 if intent is not None else fate["revision"]
            if (head["request_id"], head["revision"], head["sha256"]) != (
                    fate["transaction_id"], expected_revision, fate["sha256"]) or fate["revision"] != expected_revision:
                raise ColdStartError("revision_conflict", "historical committed trade cannot overwrite a newer canonical head")
        downloaded = await self.client.download()
        self._closed(session)
        if (downloaded is None or downloaded.metadata != head
                or (downloaded.world_id, downloaded.player_id) != (session[0], session[4])):
            raise ColdStartError("revision_conflict", "canonical head changed during startup download")
        self._payload_owner(downloaded.payload, session)
        if await self._head(session) != head:
            raise ColdStartError("revision_conflict", "canonical head changed before closed restore")
        self._unchanged(raw)
        self._closed(session)
        mirror = restore_checkpoint_held(lease, downloaded, session[0])
        if inspect_mirror_held(lease) != mirror or await self._head(session) != head:
            raise ColdStartError("revision_conflict", "canonical head changed during closed restore")
        record = dict(operation_id=operation_id, mirror=asdict(mirror), session_epoch=session[1],
                      server_epoch=session[2], resolved_export=resolved_export,
                      resolved_prepare=resolved_prepare, trade_fate=fate,
                      journal_sha256={path.name: hashlib.sha256(data).hexdigest()
                                      for path, data, _ in raw if data is not None})
        self._unchanged(raw)
        self._closed(session)
        self._record(archive / "applied.json", record)
        acknowledgment = None
        if fate is not None and fate["state"] == "committed":
            acknowledgment = (await self._rpc(session, "ack", transaction_id=fate["transaction_id"],
                                            revision=head["revision"], sha256=head["sha256"]))["trade"]
            if acknowledgment != dict(transaction_id=fate["transaction_id"], state="acknowledged",
                                       revision=head["revision"], sha256=head["sha256"]):
                raise ColdStartError("trade_conflict", "trade acknowledgment disagrees with installed canonical bytes")
        if await self._head(session) != head:
            raise ColdStartError("revision_conflict", "canonical head changed before the startup gate completed")
        if inspect_mirror_held(lease) != mirror:
            raise ColdStartError("mirror_changed", "the installed mirror changed before startup completed")
        self._unchanged(raw)
        self._closed(session)
        self._record(archive / "completed.json", dict(record, trade_ack=acknowledgment))
        for path, original, _ in raw:
            if original is not None:
                path.unlink()
        _sync_directory(self.directory)
        self._closed(session)
        return ClosedStartResult(mirror, lease, archive / "completed.json")

    @asynccontextmanager
    async def open(self, *, expected_session=None):
        """Yield only a verified current mirror; hold its lock until core closes."""
        with MirrorLease(self.save_path) as lease:
            c = self.companion
            if getattr(c, "_cold_start_active", False):
                raise ColdStartError("startup_active", "this companion already owns a startup/core-lifetime save lease")
            c._cold_start_active = True
            # Also reject a bridge whose hello was already waiting when this
            # gate closed. The launcher alone opens admission after verified
            # reconciliation; no await separates reopening from yielding.
            previous_admission = getattr(c, "_bridge_admission_blocked", False)
            c._bridge_admission_blocked = True
            try:
                async with c.live_checkpoint_lock:
                    session = self._session()
                    if expected_session is not None and session != expected_session:
                        raise ColdStartError("session_changed", "authenticated startup session changed before recovery admission")
                    self._closed(session)
                    c._live_save_owner = asyncio.current_task()
                    try:
                        verified = await self._reconcile(lease, session)
                    finally:
                        c._live_save_owner = None
                # No await separates the last closed check from permission to launch.
                self._closed(session)
                c._bridge_admission_blocked = previous_admission
                yield verified
            finally:
                c._bridge_admission_blocked = previous_admission
                c._cold_start_active = False
