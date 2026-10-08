"""Same-core host-loss preservation; canonical reconciliation stays closed-only.

No save file is replaced here. A successful result means exact Flash plus its
ordinary pending-export intent are durable locally, never that the host saved.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import struct
from uuid import UUID, uuid4
import zlib

from .battle_journal import pending_battle
from .emergency_protocol import EmergencyHold
from .flash import FLASH_SIZE, inspect_flash
from .live_checkpoint import LiveCheckpointCoordinator, LiveSaveError, _atomic, _json_bytes
from .ownership import OWNERSHIP_PROFILE, inspect_ownership
from .protocol import MAX_COUNTER
from .save_mailbox import Opcode, SaveControl, State, Status


@dataclass(frozen=True)
class EmergencyAuthority:
    bridge: object
    session: tuple
    operation_id: str
    base_revision: int


@dataclass(frozen=True)
class EmergencyResult:
    state: str
    operation_id: str | None = None
    sha256: str | None = None
    # Only a verified native receipt following durable local bytes permits
    # orderly child closure. Every uncertain/unsafe/battle result retains it.
    can_close: bool = False


def _read_json(path, limit=16384):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate emergency journal field")
            result[key] = value
        return result
    with Path(path).open("rb") as source:
        data = source.read(limit + 1)
    if len(data) > limit:
        raise ValueError("emergency journal exceeds its limit")
    return json.loads(data, object_pairs_hook=unique)


def load_closed_emergency(directory, session):
    """Read only a fully receipted candidate, including interrupted cleanup.

    An uncertain or incomplete hold never grants permission to abandon its
    still-running native state and launch a replacement core.
    """
    directory = Path(directory)
    record = _read_json(directory / "pending-emergency.json")
    identity_keys = ("world_id", "player_id", "build_id", "ruleset_id", "save_profile")
    fields = {"schema", *identity_keys, "operation_id", "expected_revision", "session_epoch",
              "incarnation", "state", "sha256", "size", "crc32"}
    if (not isinstance(record, dict) or set(record) != fields or type(record["schema"]) is not int
            or record["schema"] != 1 or record["state"] != "preserved"
            or tuple(record[k] for k in identity_keys) != (session[0], session[4], session[5], session[6], session[3])
            or str(UUID(record["operation_id"])) != record["operation_id"] or not UUID(record["operation_id"]).int
            or type(record["expected_revision"]) is not int or not 1 <= record["expected_revision"] < MAX_COUNTER
            or any(type(record[k]) is not int or not 1 <= record[k] <= MAX_COUNTER for k in ("session_epoch", "incarnation"))
            or type(record["size"]) is not int or record["size"] != FLASH_SIZE
            or type(record["crc32"]) is not int or not 0 <= record["crc32"] <= 0xFFFFFFFF):
        raise ValueError("emergency journal has no complete exact preservation receipt")
    with (directory / (record["operation_id"] + ".flash")).open("rb") as source:
        payload = source.read(FLASH_SIZE + 1)
    if (len(payload) != FLASH_SIZE or hashlib.sha256(payload).hexdigest() != record["sha256"]
            or zlib.crc32(payload) != record["crc32"]):
        raise ValueError("preserved emergency bytes changed")
    parsed = inspect_flash(payload, save_profile=record["save_profile"])
    owner = inspect_ownership(parsed)
    if (owner.world_id, owner.player_id, owner.lease_epoch, owner.incarnation) != (
            session[0], session[4], record["session_epoch"], record["incarnation"]):
        raise ValueError("preserved ownership provenance changed")
    return ({k: record[k] for k in ("schema", *identity_keys, "operation_id", "expected_revision", "sha256", "size")}, payload)


class EmergencySaveController:
    """One controller per running leased character, explicitly armed online.

    Caller owns the game's MirrorLease throughout ``drain`` and must retain
    an unsafe/uncertain core. This optional ABI2 controller does not auto-arm
    on construction, change autosave preferences, reconnect or resume battles.
    """
    def __init__(self, companion, directory: Path, *, on_status=None):
        if getattr(companion, "_emergency_controller", None) is not None:
            raise ValueError("another emergency controller owns this companion")
        self.companion = companion
        self.directory = Path(directory).resolve()
        self.coordinator = LiveCheckpointCoordinator(companion, self.directory)
        self.path = self.directory / "pending-emergency.json"
        self.on_status = on_status
        self.session = self.bridge = self.base_revision = self.identity = None
        self.active_export = None
        self.needs_arm = True
        self.task = None
        self.result = EmergencyResult("unarmed")
        self.lost = asyncio.Event()

    def _publish(self, state, operation_id=None, sha256=None, can_close=False):
        self.result = EmergencyResult(state, operation_id, sha256, can_close)
        if self.on_status is not None:
            self.on_status(self.result)
        return self.result

    async def arm(self, expected_revision: int):
        c, live = self.companion, self.coordinator
        if self.task is not None or self.lost.is_set():
            raise LiveSaveError("emergency_started", "a lost core cannot be armed again")
        if type(expected_revision) is not int or not 1 <= expected_revision < MAX_COUNTER:
            raise ValueError("pre-arming requires the verified local canonical revision")
        async with live._own():
            live._assert_no_trade()
            session = live._session()
            bridge = c._bridge
            if (getattr(c.config, "emergency_save_abi_version", 0) != 2 or bridge is None
                    or not bridge.emergency_save_capable or c.save_profile != OWNERSHIP_PROFILE):
                raise LiveSaveError("emergency_unavailable", "the verified core lacks the complete preservation ABI")
            if self.path.exists() or live.pending_path.exists():
                raise LiveSaveError("pending_export", "recover existing preservation before arming another core")
            head = await live.client.info()
            live._same_session(session)
            if head is None or head["revision"] != expected_revision:
                raise LiveSaveError("revision_conflict", "pre-arm revision differs from the verified local save")
            await live._bind(session)
            status = await live._prepare_ownership(session, expected_revision, enroll=False)
            live._same_session(session)
            if c._bridge is not bridge or status is None or not status.active_grant:
                raise LiveSaveError("ownership_grant", "pre-arm did not retain the exact core allocation")
            grant = _read_json(self.directory / (status.grant_id + ".grant.json"))
            self._verify_grant(grant, session, status.grant_id)
            if (grant["end_exclusive"] != status.end_exclusive or not grant["start"] <= status.next_serial <= status.end_exclusive
                    or grant["expected_revision"] > expected_revision):
                raise LiveSaveError("ownership_grant", "pre-arm allocation differs from its durable grant")
            identity = {"world_id": session[0], "player_id": c.config.player_id,
                        "build_id": c.config.build_id, "ruleset_id": c.config.ruleset_id,
                        "save_profile": c.save_profile}
            _atomic(self.directory / "emergency-arm.json", _json_bytes({
                "schema": 1, **identity, "session_epoch": session[1], "incarnation": session[2],
                "expected_revision": expected_revision, "grant": grant}))
            live._same_session(session)
            self.session, self.bridge = session, bridge
            self.base_revision, self.identity = expected_revision, identity
            self.needs_arm = False
            c._emergency_controller = self
            return self._publish("armed")

    def _verify_grant(self, grant, session, grant_id):
        fields = {"world_id", "player_id", "lease_epoch", "incarnation", "grant_id", "start", "end_exclusive", "expected_revision"}
        if (not isinstance(grant, dict) or set(grant) != fields or
                tuple(grant.get(k) for k in ("world_id", "player_id", "lease_epoch", "incarnation", "grant_id")) !=
                (session[0], self.companion.config.player_id, session[1], session[2], grant_id)
                or any(type(grant[k]) is not int for k in ("start", "end_exclusive", "expected_revision", "lease_epoch", "incarnation"))
                or not 1 <= grant["start"] < grant["end_exclusive"] <= 1 << 20
                or not 0 <= grant["expected_revision"] < MAX_COUNTER):
            raise LiveSaveError("ownership_grant", "preservation grant provenance differs from its armed core")

    def checkpoint_started(self, session, operation_id, base):
        if session != self.session or base != self.base_revision or self.lost.is_set():
            raise LiveSaveError("emergency_binding", "ordinary checkpoint differs from its armed core")
        self.active_export = (operation_id, base)

    def checkpoint_refused(self, session, operation_id):
        if session == self.session and self.active_export and self.active_export[0] == operation_id:
            self.active_export = None

    def checkpoint_completed(self, session, operation_id, metadata):
        if (session != self.session or self.active_export != (operation_id, self.base_revision)
                or metadata["revision"] != self.base_revision + 1 or metadata["request_id"] != operation_id):
            raise LiveSaveError("emergency_binding", "completed checkpoint differs from its armed core")
        self.base_revision = metadata["revision"]
        self.active_export = None
        self.needs_arm = False

    def trade_completed(self, session, intent, outcome):
        """Synchronous terminal hook before the trade journal is removed.

        LiveTradeCoordinator has verified its native ABORT/RELEASE receipt.
        The exact local revision advances immediately, while a canonical
        import requires a fresh grant before preservation is advertised armed.
        """
        from .checkpoint_client import validate_metadata
        c = self.companion
        self.coordinator._same_session(session)
        if (session != self.session or c._bridge is not self.bridge or self.lost.is_set()
                or c._live_save_owner is not asyncio.current_task() or self.active_export is not None
                or outcome not in {"applied", "aborted"}):
            raise LiveSaveError("emergency_binding", "completed trade differs from the armed native lifecycle")
        checkpoint = validate_metadata(intent["canonical"] or intent["prepared"], c.config, c.save_profile)
        expected = intent["expected_revision"] + (2 if outcome == "applied" else 1)
        request = intent["transaction_id"] if outcome == "applied" else intent["prepare_id"]
        if (checkpoint is None or checkpoint["revision"] != expected or checkpoint["request_id"] != request
                or (intent["world_id"], intent["player_id"]) != (session[0], c.config.player_id)):
            raise LiveSaveError("emergency_binding", "trade completion cannot adopt a different canonical head")
        path = self.directory / (intent["transaction_id"] + "." + intent["generation"] + ".emergency-adoption.json")
        record = {"schema": 1, **self.identity, "session_epoch": session[1], "incarnation": session[2],
                  "checkpoint": checkpoint, "outcome": outcome}
        if path.exists():
            if _read_json(path) != record or self.base_revision not in {intent["expected_revision"], expected}:
                raise LiveSaveError("emergency_binding", "trade adoption retry changed its exact receipt")
        else:
            if self.base_revision != intent["expected_revision"]:
                raise LiveSaveError("emergency_binding", "trade completion would rebase the retained core")
            _atomic(path, _json_bytes(record))
        self.base_revision = expected
        self.needs_arm = True

    def connection_lost(self):
        """Called synchronously before Companion clears its authentication."""
        if self.task is not None:
            return
        self.lost.set()
        self.task = asyncio.create_task(self._preserve(), name="host-loss-preservation")

    async def drain(self):
        """Do not abandon an in-flight native command or release its file lease."""
        if self.task is None:
            return self.result
        canceled = False
        while not self.task.done():
            try:
                await asyncio.shield(self.task)
            except asyncio.CancelledError:
                canceled = True
        result = self.task.result()
        if canceled:
            raise asyncio.CancelledError()
        return result

    async def _command(self, authority, opcode, offset=0):
        c = self.companion
        c._live_sequence += 1
        if c._live_sequence > MAX_COUNTER:
            raise LiveSaveError("counter_exhausted", "native command sequence is exhausted")
        command = SaveControl(authority.session[2], authority.session[1], authority.operation_id,
                              c._live_sequence, offset, FLASH_SIZE, authority.base_revision + 1, opcode)
        # A timeout can leave the Lua mailbox pending. Exact replay retains
        # sequence/UUID and is safe; no retry allocates another operation.
        for attempt in range(2):
            try:
                response = await c.emergency_save_rpc(authority, command)
                break
            except asyncio.TimeoutError:
                if attempt:
                    raise
        result = response[0] if opcode == Opcode.READ_WINDOW else response
        if result.status != Status.OK:
            raise LiveSaveError("rom_" + Status(result.status).name.lower(), "native emergency preservation refused")
        return response

    def _record(self, record, state, **updates):
        record = {**record, "state": state, **updates}
        _atomic(self.path, _json_bytes(record))
        return record

    async def _preserve(self):
        c, live = self.companion, self.coordinator
        record = None
        try:
            async with c.live_checkpoint_lock:
                c._live_save_owner = asyncio.current_task()
                try:
                    if pending_battle(c, self.directory):
                        return self._publish("battle_waiting")
                    if (self.directory / "pending-trade.json").exists():
                        return self._publish("trade_waiting")
                    if (c.connected or c._bridge is not self.bridge or getattr(c, "_live_binding", None) != self.session
                            or not c._reconnect_blocked):
                        raise ConnectionError("the armed bridge is no longer retained")
                    operation, base = self.active_export or (str(uuid4()), self.base_revision)
                    authority = EmergencyAuthority(self.bridge, self.session, operation, base)
                    c._emergency_authority = authority
                    if self.path.exists():
                        raise LiveSaveError("pending_export", "an earlier emergency intent already owns this core")
                    record = self._record({"schema": 1, **self.identity, "operation_id": operation,
                                           "expected_revision": base, "session_epoch": self.session[1],
                                           "incarnation": self.session[2]}, "holding")
                    self._publish("preserving", operation)
                    opcode = Opcode.PROMOTE_EMERGENCY_EXPORT if self.active_export else Opcode.BEGIN_EMERGENCY_EXPORT
                    begin = await self._command(authority, opcode)
                    payload = bytearray()
                    window = c.config.save_window_enabled and self.bridge.window_capable
                    while len(payload) < FLASH_SIZE:
                        offset = len(payload)
                        if window:
                            response, block = await self._command(authority, Opcode.READ_WINDOW, offset)
                            if len(block) != 4096 or struct.unpack("<I", response.data)[0] != zlib.crc32(block):
                                raise LiveSaveError("read_position", "emergency Flash window failed validation")
                        else:
                            response = await self._command(authority, Opcode.READ, offset)
                            block = response.data
                            if len(block) != 128:
                                raise LiveSaveError("read_position", "emergency Flash chunk is incomplete")
                        if response.offset != offset:
                            raise LiveSaveError("read_position", "emergency Flash cursor changed")
                        payload.extend(block)
                    payload = bytes(payload)
                    parsed = inspect_flash(payload, save_profile=self.identity["save_profile"])
                    counter, rotation = struct.unpack_from("<II", begin.data)
                    first = struct.unpack_from("<H", payload, parsed.metadata.bank * 14 * 4096 + 4084)[0]
                    if (counter, rotation) != (parsed.metadata.counter, (-first) % 14):
                        raise LiveSaveError("export_metadata", "preserved Flash differs from frozen native metadata")
                    owner = inspect_ownership(parsed)
                    if (owner.world_id, owner.player_id) != (self.session[0], c.config.player_id):
                        raise LiveSaveError("ownership_identity", "preserved Flash belongs to another character")
                    grant = _read_json(self.directory / (owner.grant_id + ".grant.json"))
                    self._verify_grant(grant, self.session, owner.grant_id)
                    if (grant["start"], grant["end_exclusive"]) != (owner.start, owner.end_exclusive) or grant["expected_revision"] > base:
                        raise LiveSaveError("ownership_grant", "frozen allocation differs from its retained grant")
                    intent = {"schema": 1, **self.identity, "operation_id": operation,
                              "expected_revision": base, "sha256": hashlib.sha256(payload).hexdigest(), "size": FLASH_SIZE}
                    if live.pending_path.exists():
                        if (_read_json(live.pending_path, 4096) != intent
                                or (self.directory / (operation + ".flash")).read_bytes() != payload):
                            raise LiveSaveError("pending_conflict", "an immutable earlier export differs from the promoted bytes")
                    else:
                        live._save_pending(intent, payload)
                    # Reopen exact disk files before asking for the native
                    # preservation receipt. A failed write never means saved.
                    if (_read_json(live.pending_path, 4096) != intent
                            or (self.directory / (operation + ".flash")).read_bytes() != payload):
                        raise LiveSaveError("journal_hash", "durable emergency readback failed")
                    record = self._record(record, "bytes_durable", sha256=intent["sha256"], size=FLASH_SIZE)
                    receipt = await self._command(authority, Opcode.PRESERVE_EMERGENCY, FLASH_SIZE)
                    if struct.unpack("<I", receipt.data)[0] != zlib.crc32(payload):
                        raise LiveSaveError("final_crc", "native preservation receipt differs from durable bytes")
                    hold = EmergencyHold.parse(await self._command(authority, Opcode.QUERY_EMERGENCY))
                    if not hold.preserved or hold.crc32 != zlib.crc32(payload):
                        raise LiveSaveError("emergency_hold", "native core did not retain the complete preserved stream")
                    self._record(record, "preserved", crc32=hold.crc32)
                    return self._publish("preserved", operation, intent["sha256"], True)
                finally:
                    c._live_save_owner = None
        except Exception:
            if record is not None:
                try:
                    self._record(record, "uncertain")
                except OSError:
                    pass
            return self._publish("unsaved_held", None if record is None else record["operation_id"])
