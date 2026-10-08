"""Explicit live checkpoint/recovery through a verified ROM-owned mailbox.

The game freezes its own callbacks while it serializes or stages Flash. This
coordinator never writes a running .sav, party, save block, or emulator state.
Scheduling automatic saves and deciding offline-play policy remain separate.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
from typing import Any
from uuid import UUID, uuid4
import zlib

from .checkpoint_client import CheckpointClient, validate_metadata
from .flash import FLASH_SIZE, inspect_flash
from .live_receipt import record_live_apply
from .protocol import MAX_COUNTER
from .save_mailbox import Opcode, SaveControl, Status, SAVE_CHUNK_SIZE


class LiveSaveError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class LiveExportResult:
    operation_id: str
    metadata: dict[str, Any]
    flash_sha256: str
    state_sha256: str
    frozen_rng_hex: str


def _sync_directory(path: Path) -> None:
    if os.name != "nt":
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _atomic(path: Path, payload: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".stage")
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        with suppress(FileNotFoundError):
            Path(temporary).unlink()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


class LiveCheckpointCoordinator:
    """One explicit lifecycle per companion; durable bytes precede server RPCs.

    ``directory`` is private launcher data, outside the repository and any shared
    folders. A pending export blocks another export until its exact transaction
    is resolved. The source Flash bytes are retained as private recovery evidence.
    """

    def __init__(self, companion, directory: Path):
        self.companion = companion
        self.client = CheckpointClient(companion)
        self.directory = Path(directory).resolve()
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.pending_path = self.directory / "pending-export.json"

    def _session(self) -> tuple[str, int, int]:
        c = self.companion
        if not c.connected or c.world_id is None or c.session_epoch is None:
            raise ConnectionError("a live checkpoint requires an authenticated world")
        return c.world_id, c.session_epoch, c.save_incarnation

    def _same_session(self, expected) -> None:
        if self._session() != expected:
            raise ConnectionError("world lease or game incarnation changed during the live checkpoint")

    @asynccontextmanager
    async def _own(self):
        c = self.companion
        async with c.live_checkpoint_lock:
            c._live_save_owner = asyncio.current_task()
            try:
                yield
            finally:
                c._live_save_owner = None

    async def _bind(self, session) -> None:
        c = self.companion
        self._same_session(session)
        if getattr(c, "_live_binding", None) == session:
            return
        pending = getattr(c, "_live_bind_pending", None)
        if pending is None or pending[0] != session:
            control = SaveControl(session[2], session[1], str(uuid4()), 1, 0, FLASH_SIZE, 0, Opcode.BIND)
            c._live_bind_pending = (session, control)
        else:
            control = pending[1]  # A lost BIND acknowledgement retries the exact request.
        response = await c.save_rpc(control)
        self._same_session(session)
        self._ok(response)
        c._live_binding, c._live_sequence = session, 1
        c._live_bind_pending = None

    @staticmethod
    def _ok(response, *, canceled=False):
        if response.status == Status.OK or (canceled and response.status == Status.CANCELED):
            return response
        status = Status(response.status)
        raise LiveSaveError("rom_" + status.name.lower(), f"the game rejected live-save command: {status.name.lower()}")

    async def _command(self, session, operation_id: str, revision: int, opcode, *, offset=0, data=b"", timeout=12.0, canceled=False):
        self._same_session(session)
        c = self.companion
        if getattr(c, "_live_binding", None) != session:
            raise ConnectionError("ROM save binding changed")
        c._live_sequence += 1
        if c._live_sequence > MAX_COUNTER:
            raise LiveSaveError("counter_exhausted", "reconnect the game bridge before issuing another save command")
        control = SaveControl(session[2], session[1], operation_id, c._live_sequence,
                              offset, FLASH_SIZE, revision, opcode, data=data)
        response = await c.save_rpc(control, timeout=timeout)
        self._same_session(session)
        return self._ok(response, canceled=canceled)

    async def _read_flash(self, session, operation_id, revision) -> bytes:
        payload = bytearray()
        while len(payload) < FLASH_SIZE:
            response = await self._command(session, operation_id, revision, Opcode.READ, offset=len(payload))
            if response.offset != len(payload) or len(response.data) != SAVE_CHUNK_SIZE:
                raise LiveSaveError("read_position", "the game returned an unexpected Flash chunk")
            payload.extend(response.data)
        result = bytes(payload)
        inspect_flash(result, save_profile=self.companion.save_profile)
        return result

    async def _end(self, session, operation_id, revision, payload):
        response = await self._command(session, operation_id, revision, Opcode.END, offset=FLASH_SIZE, timeout=20)
        if len(response.data) != 4 or struct.unpack("<I", response.data)[0] != zlib.crc32(payload):
            raise LiveSaveError("final_crc", "the game did not acknowledge the exact complete Flash readback")

    async def _cancel(self, session, operation_id, revision):
        # This cannot undo a published import. The ROM finishes/reloads committed
        # state and merely releases it; an incomplete stage discards its bank.
        with suppress(ConnectionError, asyncio.TimeoutError, LiveSaveError, ValueError):
            await self._command(session, operation_id, revision, Opcode.CANCEL, canceled=True, timeout=20)

    def _intent(self, session, operation_id, base_revision, payload):
        return {
            "schema": 1, "world_id": session[0], "player_id": self.companion.config.player_id,
            "build_id": self.companion.config.build_id, "ruleset_id": self.companion.config.ruleset_id,
            "save_profile": self.companion.save_profile, "operation_id": operation_id,
            "expected_revision": base_revision, "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
        }

    def _save_pending(self, intent, payload):
        if self.pending_path.exists():
            raise LiveSaveError("pending_export", "resolve the previous checkpoint acknowledgement before saving again")
        _atomic(self.directory / (intent["operation_id"] + ".flash"), payload)
        _atomic(self.pending_path, _json_bytes(intent))

    def _finish_pending(self, intent, metadata, *, outcome):
        _atomic(self.directory / (intent["operation_id"] + ".export.json"),
                _json_bytes({"intent": intent, "checkpoint": metadata, "outcome": outcome}))
        self.pending_path.unlink()
        _sync_directory(self.directory)

    def _load_pending(self, session):
        if not self.pending_path.exists():
            return None
        with self.pending_path.open("rb") as source:
            raw = source.read(4097)
        if len(raw) > 4096:
            raise LiveSaveError("invalid_journal", "pending checkpoint metadata exceeds its limit")
        try:
            def unique(pairs):
                result = {}
                for name, value in pairs:
                    if name in result:
                        raise ValueError("duplicate journal field")
                    result[name] = value
                return result
            intent = json.loads(raw, object_pairs_hook=unique)
            expected_fields = {"schema", "world_id", "player_id", "build_id", "ruleset_id", "save_profile", "operation_id", "expected_revision", "sha256", "size"}
            if not isinstance(intent, dict) or set(intent) != expected_fields:
                raise ValueError()
            if type(intent["schema"]) is not int or intent["schema"] != 1 or str(UUID(intent["operation_id"])) != intent["operation_id"]:
                raise ValueError()
            if type(intent["expected_revision"]) is not int or not 0 <= intent["expected_revision"] < MAX_COUNTER or type(intent["size"]) is not int or intent["size"] != FLASH_SIZE:
                raise ValueError()
        except (ValueError, TypeError, AttributeError, KeyError, UnicodeError, RecursionError):
            raise LiveSaveError("invalid_journal", "pending checkpoint metadata is invalid") from None
        c = self.companion
        expected = (session[0], c.config.player_id, c.config.build_id, c.config.ruleset_id, c.save_profile)
        actual = tuple(intent[key] for key in ("world_id", "player_id", "build_id", "ruleset_id", "save_profile"))
        if actual != expected:
            raise LiveSaveError("journal_identity", "pending checkpoint belongs to another player, world, or build")
        with (self.directory / (intent["operation_id"] + ".flash")).open("rb") as source:
            payload = source.read(FLASH_SIZE + 1)
        if len(payload) != FLASH_SIZE or hashlib.sha256(payload).hexdigest() != intent["sha256"]:
            raise LiveSaveError("journal_hash", "pending checkpoint bytes failed integrity verification")
        inspect_flash(payload, save_profile=self.companion.save_profile)
        return intent, payload

    async def checkpoint(self, *, expected_revision: int | None = None) -> LiveExportResult:
        return await self._checkpoint(expected_revision=expected_revision, enroll=False)

    async def enroll(self) -> LiveExportResult:
        """Explicit first enrollment after the host provisions the legacy source.

        This neither rebinds an existing world nor adopts a server revision.
        """
        return await self._checkpoint(expected_revision=0, enroll=True)

    async def _prepare_ownership(self, session, base, *, enroll):
        from .ownership import OWNERSHIP_PROFILE
        from .ownership_client import parse_status, grant_bytes
        c = self.companion
        if c.save_profile != OWNERSHIP_PROFILE:
            if enroll:
                raise LiveSaveError("ownership_unavailable", "explicit ownership enrollment requires the ownership save profile")
            return
        if not getattr(c.config, "ownership_enabled", False):
            raise LiveSaveError("ownership_unavailable", "the verified ROM has no ownership capability")
        if enroll and base:
            raise LiveSaveError("already_enrolled", "an existing canonical character cannot be enrolled again")
        status = parse_status((await self._command(session, str(uuid4()), base, Opcode.QUERY_OWNERSHIP)).data)
        if status.enrolled and (status.world_id, status.player_id) != (session[0], c.config.player_id):
            raise LiveSaveError("ownership_identity", "the game belongs to a different world or character")
        if not status.enrolled and not enroll:
            raise LiveSaveError("enrollment_required", "explicit legacy enrollment is required before the first ownership checkpoint")
        if status.active_grant and (status.lease_epoch, status.incarnation) != (session[1], session[2]):
            raise LiveSaveError("ownership_session", "the game reports an allocation from a different session")
        # A fresh grant is required after every load, even with no new Pokémon.
        if not status.active_grant or status.remaining < status.missing:
            result = await c.checkpoint_rpc("ownership_grant", expected_revision=base,
                                           incarnation=session[2], count=max(32, status.missing))
            self._same_session(session)
            grant = result["grant"]
            if (grant["world_id"], grant["player_id"], grant["lease_epoch"], grant["incarnation"], grant["expected_revision"]) != (
                    session[0], c.config.player_id, session[1], session[2], base):
                raise LiveSaveError("ownership_grant", "allocation reply does not match this character and revision")
            # A lost allocation acknowledgement burns unused IDs safely. Retain
            # every acknowledged range before exposing it to the live game.
            _atomic(self.directory / (grant["grant_id"] + ".grant.json"), _json_bytes(grant))
            assigned = parse_status((await self._command(session, grant["grant_id"], base,
                Opcode.GRANT_OWNERSHIP, data=grant_bytes(grant, enroll=not status.enrolled))).data)
            if (not assigned.active_grant or assigned.grant_id != grant["grant_id"]
                    or assigned.world_id != session[0] or assigned.player_id != c.config.player_id
                    or (assigned.lease_epoch, assigned.incarnation) != (session[1], session[2])
                    or assigned.next_serial != grant["start"] or assigned.end_exclusive != grant["end_exclusive"]
                    or assigned.remaining < assigned.missing):
                raise LiveSaveError("ownership_grant", "the game did not accept the exact allocation")

    async def _checkpoint(self, *, expected_revision: int | None, enroll: bool) -> LiveExportResult:
        """Save against the local revision verified by the launcher.

        Reading the server's head cannot establish an older running game's
        revision. Only first enrollment with no canonical save can omit it.
        """
        async with self._own():
            session = self._session()
            if self.pending_path.exists():
                raise LiveSaveError("pending_export", "resolve the previous checkpoint before creating another")
            head = await self.client.info()
            base = head["revision"] if head is not None else 0
            if head is not None and expected_revision is None:
                raise LiveSaveError("revision_required", "supply the local revision established by verified restore or enrollment")
            if expected_revision is not None and (type(expected_revision) is not int or expected_revision != base):
                raise LiveSaveError("revision_conflict", "requested base differs from the canonical checkpoint")
            if base >= MAX_COUNTER:
                raise LiveSaveError("counter_exhausted", "checkpoint revisions are exhausted")
            await self._bind(session)
            await self._prepare_ownership(session, base, enroll=enroll)
            operation_id, revision, finished = str(uuid4()), base + 1, False
            try:
                begin = await self._command(session, operation_id, revision, Opcode.BEGIN_EXPORT)
                if len(begin.data) != 40:
                    raise LiveSaveError("export_metadata", "the game returned invalid frozen-save metadata")
                payload = await self._read_flash(session, operation_id, revision)
                frozen = inspect_flash(payload, save_profile=self.companion.save_profile)
                counter, rotation = struct.unpack_from("<II", begin.data)
                first_sector_id = struct.unpack_from("<H", payload, frozen.metadata.bank * 14 * 4096 + 4084)[0]
                if counter != frozen.metadata.counter or rotation != (-first_sector_id) % 14:
                    raise LiveSaveError("export_metadata", "Flash does not match the game's frozen-save metadata")
                intent = self._intent(session, operation_id, base, payload)
                self._save_pending(intent, payload)
                metadata = await self.client.upload(payload, base, transaction_id=operation_id)
                self._same_session(session)
                await self._end(session, operation_id, revision, payload)
                finished = True
                self._finish_pending(intent, metadata, outcome="server-acknowledged-and-ROM-released")
                return LiveExportResult(operation_id, metadata, frozen.sha256, frozen.state_sha256, begin.data[8:].hex())
            finally:
                if not finished:
                    await self._cancel(session, operation_id, revision)

    async def resolve_pending(self) -> dict[str, Any] | None:
        """Retry exactly the stored bytes/base/UUID; never adopt a newer base."""
        async with self._own():
            session = self._session()
            pending = self._load_pending(session)
            if pending is None:
                return None
            intent, payload = pending
            metadata = await self.client.upload(payload, intent["expected_revision"], transaction_id=intent["operation_id"])
            self._same_session(session)
            await self._bind(session)
            await self._cancel(session, intent["operation_id"], intent["expected_revision"] + 1)
            self._finish_pending(intent, metadata, outcome="exact-transaction-reconciled")
            return metadata

    async def recover(self):
        """Apply the latest canonical checkpoint without replacing a live file."""
        async with self._own():
            session = self._session()
            if self.pending_path.exists():
                raise LiveSaveError("pending_export", "resolve the pending save before recovering a canonical checkpoint")
            canonical = await self.client.download()
            if canonical is None:
                raise LiveSaveError("checkpoint_missing", "this player has no canonical checkpoint to recover")
            self._same_session(session)
            c = self.companion
            if (canonical.world_id, canonical.player_id) != (session[0], c.config.player_id):
                raise LiveSaveError("checkpoint_identity", "downloaded checkpoint belongs to another world or player")
            metadata = validate_metadata(canonical.metadata, c.config, c.save_profile)
            if (metadata is None or not isinstance(canonical.payload, bytes)
                    or len(canonical.payload) != metadata["size"]
                    or hashlib.sha256(canonical.payload).hexdigest() != metadata["sha256"]):
                raise LiveSaveError("checkpoint_hash", "downloaded checkpoint bytes do not match their canonical metadata")
            parsed = inspect_flash(canonical.payload, save_profile=self.companion.save_profile)
            payload = parsed.flash  # The emulator's native RTC footer remains in its open mapping.
            rotation = (-struct.unpack_from("<H", payload, parsed.metadata.bank * 14 * 4096 + 4084)[0]) % 14
            operation_id, revision, finished = str(uuid4()), canonical.metadata["revision"], False
            _atomic(self.directory / (operation_id + ".recovery.flash"), payload)
            _atomic(self.directory / (operation_id + ".recovery-intent.json"), _json_bytes({
                "operation_id": operation_id, "world_id": session[0], "player_id": canonical.player_id,
                "checkpoint": canonical.metadata, "state_sha256": parsed.state_sha256,
            }))
            await self._bind(session)
            try:
                await self._command(session, operation_id, revision, Opcode.BEGIN_IMPORT,
                                    data=struct.pack("<IIII", zlib.crc32(payload), parsed.metadata.counter, rotation, parsed.metadata.trainer_id))
                for offset in range(0, FLASH_SIZE, SAVE_CHUNK_SIZE):
                    response = await self._command(session, operation_id, revision, Opcode.WRITE, offset=offset, data=payload[offset:offset + SAVE_CHUNK_SIZE])
                    if response.offset != offset + SAVE_CHUNK_SIZE:
                        raise LiveSaveError("write_position", "the game did not acknowledge the exact staged chunk")
                if await self.client.info() != canonical.metadata:
                    raise LiveSaveError("revision_conflict", "canonical checkpoint changed before ROM import commit")
                await self._command(session, operation_id, revision, Opcode.COMMIT, offset=FLASH_SIZE, timeout=20)
                applied = await self._read_flash(session, operation_id, revision)
                if inspect_flash(applied, save_profile=self.companion.save_profile).state_sha256 != parsed.state_sha256:
                    raise LiveSaveError("applied_state", "imported Flash differs from the canonical player state")
                await self._end(session, operation_id, revision, applied)
                self._same_session(session)
                acknowledged_head = await self.client.info()
                self._same_session(session)
                if acknowledged_head != canonical.metadata:
                    raise LiveSaveError("revision_conflict", "canonical checkpoint changed before import acknowledgement")
                receipt = record_live_apply(self.directory / (operation_id + ".live-apply.json"), canonical, applied,
                                           operation_id=operation_id, session_epoch=session[1], incarnation=session[2])
                finished = True
                return receipt
            finally:
                if not finished:
                    await self._cancel(session, operation_id, revision)
