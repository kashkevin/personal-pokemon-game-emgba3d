"""Durable terminal hold transfer from a released battle to a fresh saver.

RETIRE removes the obsolete battle-resume latch but keeps the field held.
HANDOFF is permitted only after the exact successor emergency controller is
fully armed and registered. Neither control advances ordinary battle state.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import stat
import struct
from uuid import UUID

from .battle_execution_protocol import decode_control, encode_control
from .battle_journal import BattleJournalError, path_present
from .live_checkpoint import _atomic, _json_bytes
from .native_battle import NativeControl, Opcode

FORMAT = "native-battle-terminal-retirement-v1"
HANDOFF_FORMAT = "native-battle-save-handoff-v1"


def _read(path):
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError()
        with path.open("rb") as source:
            raw = source.read(65537)
        value = json.loads(raw)
        if len(raw) > 65536 or type(value) is not dict or _json_bytes(value) != raw:
            raise ValueError()
        return value
    except (ValueError, OSError, TypeError, RecursionError) as error:
        raise BattleJournalError("battle_recovery_required", "terminal battle evidence is malformed") from error


def authenticated_session(c):
    from .battle_session import RenewedBattleSession
    if c.connected is not True:
        raise ConnectionError("terminal battle requires current authentication")
    return RenewedBattleSession(c.world_id, c.config.player_id, c.config.build_id, c.config.ruleset_id,
        c.save_profile, c.server_epoch, c.session_epoch, c.battle_incarnation, c._live_battle_runtime_id)


def _identity(session, intent):
    if ((session.world_id, session.player_id, session.build_id, session.ruleset_id, session.save_profile,
         session.incarnation, session.runtime_id) != (intent.world_id, intent.player_id, intent.build_id,
         intent.ruleset_id, intent.save_profile, intent.incarnation, intent.runtime_id)
            or session.server_epoch < intent.server_epoch or session.lease_epoch < intent.lease_epoch
            or (session.lease_epoch == intent.lease_epoch and session.server_epoch != intent.server_epoch)):
        raise BattleJournalError("battle_recovery_required", "terminal authentication changed the original core")


def _release(command, response, intent):
    if (command.opcode != Opcode.RELEASE or response.status
            or (command.battle_id, command.incarnation, command.phase, command.source_slot) !=
               (intent.battle_id, intent.incarnation, intent.bind.phase, intent.bind.source_slot)):
        raise BattleJournalError("battle_recovery_required", "terminal retirement needs the exact successful RELEASE")
    command.validate_command()
    response.validate_response(command)
    return UUID(intent.generation).bytes + struct.pack("<I", command.sequence) + command.data


def _control(session, intent, payload, opcode):
    return NativeControl(session.incarnation, session.lease_epoch, intent.battle_id, 1, opcode,
        phase=intent.bind.phase, source_slot=intent.bind.source_slot, data=payload)


def _validate(value, intent):
    from .battle_session import RenewedBattleSession
    fields = {"format", "intent", "session", "host_closed", "release_command_b64",
        "release_response_b64", "command_b64", "response_b64"}
    try:
        if set(value) != fields or value["format"] != FORMAT or value["intent"] != intent.value() or value["host_closed"] is not True:
            raise ValueError()
        session = RenewedBattleSession(**value["session"])
        _identity(session, intent)
        release = decode_control(value["release_command_b64"])
        receipt = decode_control(value["release_response_b64"], response=True)
        payload = _release(release, receipt, intent)
        command = decode_control(value["command_b64"])
        if command != _control(session, intent, payload, Opcode.RETIRE):
            raise ValueError()
        if value["response_b64"] is not None:
            response = decode_control(value["response_b64"], response=True)
            response.validate_response(command)
            if response.status or response.data != payload:
                raise ValueError()
        return session, command
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        raise BattleJournalError("battle_recovery_required", "native retirement evidence differs from terminal authority") from error


def verify_retirement(c, directory, intent, bridge, session):
    if c._bridge is not bridge or authenticated_session(c) != session:
        raise BattleJournalError("battle_recovery_required", "retirement lost its original bridge or authentication")
    value = _read(Path(directory) / (intent.battle_id + ".battle-retirement.json"))
    recorded, _ = _validate(value, intent)
    if recorded != session or value["response_b64"] is None:
        raise BattleJournalError("battle_recovery_required", "native terminal hold retirement is not acknowledged")
    return value


class _RetirementAuthority:
    def __init__(self, executor, record, path, bridge):
        self.executor, self.record, self.path, self.bridge = executor, record, path, bridge
        self.owner = asyncio.current_task()

    def authorizes(self, command):
        c = self.executor.companion
        try:
            _validate(self.record, self.executor.intent)
            return (asyncio.current_task() is self.owner and c._live_battle_owner is self.owner
                and c._live_save_owner is self.owner and c._live_battle_executor is self.executor
                and c._bridge is self.bridge and authenticated_session(c).value() == self.record["session"]
                and self.record["response_b64"] is None and encode_control(command) == self.record["command_b64"]
                and _read(self.path) == self.record)
        except (ValueError, OSError, ConnectionError):
            return False


async def retire_battle(executor, host_view, release, response):
    """Own a native RETIRE only after this session received host global closure."""
    c, intent, directory = executor.companion, executor.intent, executor.journal.directory
    if (host_view["state"] != "closed" or host_view["battle_id"] != intent.battle_id
            or host_view["generation"] != intent.generation or host_view["command_b64"] is not None
            or host_view["command_id"] != 0 or c._live_battle_executor is not executor
            or c._live_battle_owner is not asyncio.current_task() or c._live_save_owner is not asyncio.current_task()
            or getattr(c.config, "battle_resume_abi_version", 0) != 1):
        raise BattleJournalError("battle_recovery_required", "native retirement has no exact authenticated global closure")
    session, bridge = authenticated_session(c), c._bridge
    if bridge is None or bridge is not executor.bridge:
        raise BattleJournalError("battle_recovery_required", "terminal retirement requires the original retained bridge")
    _identity(session, intent)
    payload = _release(release, response, intent)
    command = _control(session, intent, payload, Opcode.RETIRE)
    if host_view.get("stage") == "terminal" and decode_control(host_view["terminal"]["retire_b64"]) != command:
        raise BattleJournalError("battle_recovery_required", "host terminal retirement differs from this authenticated core")
    record = dict(format=FORMAT, intent=intent.value(), session=session.value(), host_closed=True,
        release_command_b64=encode_control(release), release_response_b64=encode_control(response),
        command_b64=encode_control(command), response_b64=None)
    path = directory / (intent.battle_id + ".battle-retirement.json")
    c._live_battle_terminal_pending_path = path
    if path_present(path):
        previous = _read(path)
        old_session, _ = _validate(previous, intent)
        if (session.server_epoch < old_session.server_epoch or session.lease_epoch < old_session.lease_epoch
                or (session.lease_epoch == old_session.lease_epoch and session.server_epoch != old_session.server_epoch)
                or replace(decode_control(previous["release_command_b64"]), session_epoch=release.session_epoch) != release
                or replace(decode_control(previous["release_response_b64"], response=True), session_epoch=response.session_epoch) != response):
            raise BattleJournalError("battle_recovery_required", "terminal retirement cannot replace its original RELEASE")
        if old_session == session and previous["response_b64"] is not None:
            return session
        if old_session != session:
            archive = directory / (intent.battle_id + ".battle-retirement."
                + str(old_session.server_epoch) + "." + str(old_session.lease_epoch) + ".json")
            if path_present(archive) and archive.read_bytes() != _json_bytes(previous):
                raise BattleJournalError("battle_recovery_required", "archived native retirement differs")
            _atomic(archive, _json_bytes(previous))
    _atomic(path, _json_bytes(record))
    authority = _RetirementAuthority(executor, record, path, bridge)
    executor._terminal_authority = authority
    try:
        receipt = await c.battle_rpc(command)
        receipt.validate_response(command)
        if receipt.status or receipt.data != payload:
            raise BattleJournalError("battle_recovery_required", "native terminal retirement was refused")
        record["response_b64"] = encode_control(receipt)
        _atomic(path, _json_bytes(record))
        verify_retirement(c, directory, intent, bridge, session)
        return session
    finally:
        executor._terminal_authority = None


class BattleHandoffAuthority:
    """An exact registered successor owns only its persisted final hold release."""
    def __init__(self, companion, directory, completion, intent, bridge, successor):
        self.companion, self.directory = companion, Path(directory)
        self.completion, self.intent, self.bridge, self.successor = completion, intent, bridge, successor
        self.owner = asyncio.current_task()
        self.path = self.directory / (intent.battle_id + ".battle-handoff.json")
        self.record = None

    def _ready(self):
        from .emergency_save import EmergencySaveController
        c, s = self.companion, self.successor
        session = self.completion.renewed_session
        if (type(s) is not EmergencySaveController or s.companion is not c
                or c._bridge is not self.bridge or authenticated_session(c) != session
                or c._emergency_controller is not s or s.bridge is not self.bridge
                or s.session != (session.world_id, session.lease_epoch, session.incarnation)
                or s.base_revision != self.intent.canonical_revision or s.result.state != "armed"
                or s.needs_arm or s.lost.is_set() or s.task is not None or s.active_export is not None
                or c._live_binding != s.session or getattr(c, "_live_bind_pending", None) is not None
                or any(path_present(self.directory / name) for name in
                    ("pending-battle.json", "pending-battle-admission.json", "pending-export.json", "pending-trade.json", "pending-emergency.json"))):
            raise BattleJournalError("battle_recovery_required", "fresh registered emergency saver does not own the terminal handoff")
        armed = _read(self.directory / "emergency-arm.json")
        identity = dict(world_id=session.world_id, player_id=session.player_id, build_id=session.build_id,
            ruleset_id=session.ruleset_id, save_profile=session.save_profile)
        if (s.identity != identity or set(armed) != {"schema", *identity, "session_epoch", "incarnation", "expected_revision", "grant"}
                or type(armed["schema"]) is not int
                or armed != {"schema": 1, **identity, "session_epoch": session.lease_epoch,
                    "incarnation": session.incarnation, "expected_revision": s.base_revision, "grant": armed.get("grant")}
                or type(armed["grant"]) is not dict):
            raise BattleJournalError("battle_recovery_required", "successor durable arm evidence changed")
        from .battle_journal import _uuid
        _uuid(armed["grant"].get("grant_id"))
        s._verify_grant(armed["grant"], s.session, armed["grant"].get("grant_id"))
        if armed["grant"]["expected_revision"] > s.base_revision:
            raise BattleJournalError("battle_recovery_required", "successor grant exceeds the restored canonical base")

    def _authorizes(self, command):
        c = self.companion
        try:
            self._ready()
            retirement = verify_retirement(c, self.directory, self.intent, self.bridge, self.completion.renewed_session)
            expected = replace(decode_control(retirement["command_b64"]), opcode=Opcode.HANDOFF)
            return (asyncio.current_task() is self.owner and c._live_battle_owner is self.owner
                and c._live_save_owner is self.owner and c._live_battle_executor is self
                and command == expected and self.record is not None and self.record["response_b64"] is None
                and encode_control(command) == self.record["command_b64"] and _read(self.path) == self.record)
        except (ValueError, OSError, ConnectionError):
            return False


async def complete_battle_handoff(c, directory, completion, original_intent, retained_bridge, successor):
    """Release the native terminal hold only under a fully armed successor."""
    from .battle_recovery_session import verify_recovery_completion
    authority = BattleHandoffAuthority(c, directory, completion, original_intent, retained_bridge, successor)
    async with c.live_checkpoint_lock:
        verify_recovery_completion(c, directory, completion, original_intent, retained_bridge)
        authority._ready()
        retirement = verify_retirement(c, directory, original_intent, retained_bridge, completion.renewed_session)
        retired = decode_control(retirement["command_b64"])
        command = replace(retired, opcode=Opcode.HANDOFF)
        record = dict(format=HANDOFF_FORMAT, intent=original_intent.value(), session=completion.renewed_session.value(),
            retirement_sha256=hashlib.sha256(_json_bytes(retirement)).hexdigest(),
            command_b64=encode_control(command), response_b64=None)
        if path_present(authority.path):
            previous = _read(authority.path)
            if {**previous, "response_b64": None} != record:
                raise BattleJournalError("battle_recovery_required", "terminal handoff evidence changed")
            if previous["response_b64"] is not None:
                receipt = decode_control(previous["response_b64"], response=True)
                receipt.validate_response(command)
                if receipt.status or receipt.data != command.data:
                    raise BattleJournalError("battle_recovery_required", "terminal handoff receipt is invalid")
                c._live_battle_terminal_pending_path = None
                return completion
        authority.record = record
        _atomic(authority.path, _json_bytes(record))
        c._live_save_owner = c._live_battle_owner = authority.owner
        c._live_battle_executor = authority
        try:
            receipt = await c.battle_rpc(command)
            receipt.validate_response(command)
            if receipt.status or receipt.data != command.data:
                raise BattleJournalError("battle_recovery_required", "native terminal handoff was refused")
            record["response_b64"] = encode_control(receipt)
            _atomic(authority.path, _json_bytes(record))
            authority._ready()
            c._live_battle_terminal_pending_path = None
            return completion
        finally:
            c._live_save_owner = c._live_battle_owner = None
            if c._live_battle_executor is authority:
                c._live_battle_executor = None
