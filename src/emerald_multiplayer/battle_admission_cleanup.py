"""Retained-core cleanup of a never-reserved admission, with a held save handoff.

Host loss is not cancellation. An explicit authenticated request durably revokes
the original consent before these controls run. Bound or uncertain BINDs always
remain in the ordinary all-trainers recovery protocol.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
import hashlib
import struct
from pathlib import Path

from .battle_admission_cleanup_protocol import AdmissionCancellation, validate_cancellation_view
from .battle_admission_intent import BattleAdmissionIntent, FILENAME, read_admission_intent
from .battle_execution_protocol import decode_control, encode_control
from .battle_journal import BattleJournal, BattleJournalError, path_present
from .battle_session import RenewedBattleSession
from .battle_terminal import _read, _identity, authenticated_session, BattleHandoffAuthority
from .live_checkpoint import _atomic, _json_bytes, _sync_directory
from .native_battle import NativeControl, Opcode
from .native_battle_resume import Admission

FORMAT = "native-unreserved-admission-cleanup-v1"


@dataclass(frozen=True)
class AdmissionCleanupCompletion:
    battle_id: str
    generation: str
    canonical_revision: int
    canonical_sha256: str
    renewed_session: RenewedBattleSession
    state: str = "admission_canceled"


def cleanup_path(directory, intent):
    return Path(directory) / (intent.battle_id + ".admission-cleanup.json")


def _command(intent, session, result, opcode=Opcode.ADMISSION_CANCEL_HOLD):
    payload = AdmissionCancellation(Admission(intent.generation, intent.player_id, intent.runtime_id),
        intent.lease_epoch, result["tombstone_sha256"]).pack()
    return NativeControl(intent.incarnation, session.lease_epoch, intent.battle_id, 1, opcode,
        phase=intent.admit.phase, source_slot=intent.admit.source_slot, data=payload)


def _ready_control(intent, session):
    return NativeControl(intent.incarnation, session.lease_epoch, intent.battle_id, 1, Opcode.ADMISSION_CANCEL_READY,
        phase=intent.admit.phase, source_slot=intent.admit.source_slot,
        data=intent.admit.data + struct.pack("<I", intent.lease_epoch))


def _validate(value, intent):
    try:
        if (set(value) != {"format", "intent", "session", "cancellation", "ready_b64", "command_b64", "response_b64", "host_ack", "previous_terminal"}
                or value["format"] != FORMAT or value["intent"] != intent.value()
                or type(value["host_ack"]) is not bool):
            raise ValueError()
        session = RenewedBattleSession(**value["session"])
        _identity(session, intent)
        previous = value["previous_terminal"]
        if previous is not None:
            from .battle_protocol import _digest
            if (type(previous) is not dict or set(previous) != {"lease", "sha256"}
                    or type(previous["lease"]) is not int or not intent.lease_epoch <= previous["lease"] < session.lease_epoch):
                raise ValueError()
            _digest(previous["sha256"])
        readiness = decode_control(value["ready_b64"], response=True)
        readiness.validate_response(_ready_control(intent, session))
        if readiness.status:
            raise ValueError()
        result = validate_cancellation_view(value["cancellation"], intent.player_id)
        if ((result["battle_id"], result["generation"], result["incarnation"], result["runtime_id"], result["original_lease"])
                != (intent.battle_id, intent.generation, intent.incarnation, intent.runtime_id, intent.lease_epoch)
                or result["acknowledged"]):
            raise ValueError()
        command = _command(intent, session, result)
        if value["command_b64"] != encode_control(command):
            raise ValueError()
        if value["response_b64"] is not None:
            response = decode_control(value["response_b64"], response=True)
            response.validate_response(command)
            if response.status:
                raise ValueError()
        elif value["host_ack"]:
            raise ValueError()
        return session, command
    except (ValueError, TypeError, KeyError) as error:
        raise BattleJournalError("battle_recovery_required", "neutral cleanup evidence changed its original held core") from error


def verify_cleanup_completion(c, directory, completion, intent, bridge):
    if (type(intent) is not BattleAdmissionIntent or type(completion) is not AdmissionCleanupCompletion
            or (completion.battle_id, completion.generation, completion.canonical_revision,
                completion.canonical_sha256, completion.state) !=
               (intent.battle_id, intent.generation, intent.canonical_revision, intent.canonical_sha256, "admission_canceled")
            or c._bridge is not bridge or authenticated_session(c) != completion.renewed_session
            or c._live_save_owner is not None or getattr(c, "_live_battle_owner", None) is not None):
        raise BattleJournalError("battle_recovery_required", "cleanup completion lost its exact retained core")
    directory = Path(directory)
    if (path_present(directory / "pending-battle.json") or path_present(directory / FILENAME)
            or read_admission_intent(directory / (intent.battle_id + ".canceled-admission-intent.json")) != intent):
        raise BattleJournalError("battle_recovery_required", "cleanup cannot retire another local admission")
    value = _read(cleanup_path(directory, intent))
    session, _ = _validate(value, intent)
    if session != completion.renewed_session or not value["host_ack"] or value["response_b64"] is None:
        raise BattleJournalError("battle_recovery_required", "neutral hold is not durably acknowledged by core and host")
    return value


def verify_cleanup_retirement_predecessor(directory, saved, completion, intent, old_session):
    """An already-retired saver never acquires a newer lease on retry."""
    try:
        old = RenewedBattleSession(**saved["renewed_session"])
        _identity(old, intent)
        new = completion.renewed_session
        if (old.lease_epoch > new.lease_epoch or old.server_epoch > new.server_epoch
                or old.lease_epoch == new.lease_epoch and old.server_epoch != new.server_epoch):
            return False
        path = cleanup_path(directory, intent)
        if old != new:
            path = path.with_name(path.stem + "." + str(old.lease_epoch) + ".json")
        value = _read(path)
        recorded, _ = _validate(value, intent)
        return (recorded == old and value["host_ack"] and value["response_b64"] is not None
            and saved == dict(schema=1, battle_id=intent.battle_id, old_session=list(old_session),
                renewed_session=old.value(), canonical_revision=intent.canonical_revision,
                canonical_sha256=intent.canonical_sha256,
                terminal_receipt_sha256=hashlib.sha256(_json_bytes(value)).hexdigest()))
    except (ValueError, OSError, TypeError, KeyError):
        return False


def prepare_cleanup_successor(c, directory):
    """Check an already-retired lifecycle before any fresh native save BIND."""
    path = getattr(c, "_live_battle_terminal_pending_path", None)
    if path is None or not str(path).endswith(".admission-cleanup.json"):
        return False
    value = _read(Path(path))
    intent = BattleAdmissionIntent.from_value(value["intent"])
    recorded, _ = _validate(value, intent)
    if (Path(path) != cleanup_path(directory, intent) or recorded != authenticated_session(c)
            or not value["host_ack"] or value["response_b64"] is None
            or getattr(c, "_emergency_controller", None) is not None
            or read_admission_intent(Path(directory) / (intent.battle_id + ".canceled-admission-intent.json")) != intent):
        raise BattleJournalError("battle_recovery_required", "fresh saver has no exact retired admission authority")
    return True


class AdmissionCleanupSession:
    def __init__(self, companion, directory, intent):
        if type(intent) is not BattleAdmissionIntent:
            raise BattleJournalError("battle_recovery_required", "bound battles cannot use neutral admission cleanup")
        self.companion, self.journal, self.intent = companion, BattleJournal(companion, directory), intent
        self.bridge = companion._bridge
        self.path = cleanup_path(self.journal.directory, intent)
        self.owner, self.record, self.session = None, None, None
        self.revocation_requested = False

    def _retained(self):
        c, i, d = self.companion, self.intent, self.journal.directory
        if (getattr(c.config, "battle_admission_cleanup_abi_version", 0) != 1
                or self.bridge is None or c._bridge is not self.bridge or not self.bridge.battle_capable
                or c.battle_incarnation != i.incarnation or c._live_battle_runtime_id != i.runtime_id
                or (c.config.player_id, c.config.build_id, c.config.ruleset_id) != (i.player_id, i.build_id, i.ruleset_id)
                or not c.config.ownership_enabled or not c.config.development_battle_channel
                or getattr(c.config, "battle_resume_abi_version", 0) != 1
                or path_present(d / "pending-battle.json") or path_present(d / "pending-emergency.json")):
            raise BattleJournalError("battle_recovery_required", "neutral cleanup requires the exact original unbound game")
        self.journal._other_recovery()
        execution = d / "native-battle-execution.json"
        if path_present(execution):
            previous = _read(execution)
            if previous.get("intent", {}).get("battle_id") == i.battle_id:
                raise BattleJournalError("battle_recovery_required", "a persisted full native dispatch forbids neutral cleanup")
        source = d / FILENAME
        if not path_present(source):
            source = d / (i.battle_id + ".canceled-admission-intent.json")
            value = _read(self.path)
            _validate(value, i)
            if not value["host_ack"] or value["response_b64"] is None:
                anchor = value["previous_terminal"]
                if anchor is None:
                    raise BattleJournalError("battle_recovery_required", "unlinked admission has no terminal hold evidence")
                archive = self.path.with_name(self.path.stem + "." + str(anchor["lease"]) + ".json")
                terminal = _read(archive)
                original, _ = _validate(terminal, i)
                if (hashlib.sha256(_json_bytes(terminal)).hexdigest() != anchor["sha256"]
                        or original.lease_epoch != anchor["lease"] or not terminal["host_ack"]
                        or terminal["response_b64"] is None or terminal["cancellation"] != value["cancellation"]):
                    raise BattleJournalError("battle_recovery_required", "renewed cleanup lost its previous exact terminal authority")
        if read_admission_intent(source) != i:
            raise BattleJournalError("battle_recovery_required", "original provisional intent changed")

    def _authorizes_reconnect(self):
        c = self.companion
        try:
            self._retained()
            return (self.owner is not None and asyncio.current_task() is self.owner
                and c._live_save_owner is self.owner and c._live_battle_owner is self.owner
                and c._live_battle_executor is self)
        except (ValueError, OSError, ConnectionError):
            return False

    def _session(self):
        session = authenticated_session(self.companion)
        _identity(session, self.intent)
        if self.session is not None and (session.server_epoch < self.session.server_epoch
                or session.lease_epoch < self.session.lease_epoch
                or session.lease_epoch == self.session.lease_epoch and session.server_epoch != self.session.server_epoch):
            raise BattleJournalError("battle_recovery_required", "cleanup authentication moved backwards")
        return session

    def _accept_welcome(self, welcome):
        self._retained()
        c = self.companion
        if (self.owner is None or c._live_save_owner is not self.owner
                or getattr(c, "_battle_recovery_authority", None) is not self):
            raise BattleJournalError("battle_recovery_required", "cleanup reconnect authority expired")
        _identity(RenewedBattleSession(welcome["world_id"], c.config.player_id, c.config.build_id,
            c.config.ruleset_id, welcome["save_profile"], welcome["server_epoch"], welcome["session_epoch"],
            self.intent.incarnation, self.intent.runtime_id), self.intent)

    def _authorizes(self, command):
        try:
            return (self._authorizes_reconnect() and self.record is not None
                and self._session() == self.session and _validate(self.record, self.intent)[1] == command
                and self.record["response_b64"] is None and _read(self.path) == self.record)
        except (ValueError, OSError, ConnectionError):
            return False

    async def revoke_before_menu_drain(self):
        """Host revocation precedes canceling an exact waiting menu executor.

        This grants no native control authority and takes no save ownership.
        If reservation wins the race, it raises without interrupting that task.
        """
        c, i = self.companion, self.intent
        self._retained()
        session = self._session()
        ready = await self.ready()
        self.revocation_requested = True
        result = (await c.battle_challenge_rpc("cancel_admission", battle_id=i.battle_id,
            generation=i.generation, incarnation=i.incarnation, runtime_id=i.runtime_id,
            cleanup_ready_b64=encode_control(ready), cleanup_receipt_b64=None))["result"]
        self._retained()
        if self._session() != session:
            raise BattleJournalError("battle_recovery_required", "cleanup authentication changed during revocation")
        record = dict(format=FORMAT, intent=i.value(), session=session.value(), cancellation=result,
            ready_b64=encode_control(ready), command_b64=encode_control(_command(i, session, result)),
            response_b64=None, host_ack=False, previous_terminal=None)
        _validate(record, i)
        if path_present(self.path):
            previous = _read(self.path)
            previous_session, _ = _validate(previous, i)
            if previous_session != session or previous["cancellation"] != result:
                raise BattleJournalError("battle_recovery_required", "active menu cancellation changed its durable identity")
        else:
            _atomic(self.path, _json_bytes(record))
        return result

    async def ready(self):
        """Observational capacity/phase proof before an irreversible host revoke."""
        c = self.companion
        authority = AdmissionCleanupReadinessAuthority(self)
        if getattr(c, "_live_battle_cleanup_readiness", None) is not None:
            raise BattleJournalError("character_busy", "another cleanup readiness query is pending")
        _atomic(authority.path, _json_bytes(authority.record))
        c._live_battle_cleanup_readiness = authority
        try:
            response = await c.battle_rpc(authority.command)
            response.validate_response(authority.command)
            if response.status:
                raise BattleJournalError("battle_recovery_required", "native admission cannot safely promise cancellation capacity")
            authority.record["response_b64"] = encode_control(response)
            _atomic(authority.path, _json_bytes(authority.record))
            self._retained()
            if self._session() != authority.session:
                raise BattleJournalError("battle_recovery_required", "readiness changed its authenticated lease")
            return response
        finally:
            if c._live_battle_cleanup_readiness is authority:
                c._live_battle_cleanup_readiness = None

    async def run(self):
        c, i, d = self.companion, self.intent, self.journal.directory
        self._retained()
        old = getattr(c, "_emergency_controller", None)
        if old is not None:
            await old.drain()
        async with c.live_checkpoint_lock:
            if c._live_save_owner is not None or getattr(c, "_live_battle_owner", None) is not None:
                raise BattleJournalError("character_busy", "another lifecycle owns this admission")
            self.owner = asyncio.current_task()
            c._live_save_owner = c._live_battle_owner = self.owner
            c._live_battle_executor = self
            try:
                await c.reconnect_retained_battle(self)
                self.session = self._session()
                fields = dict(battle_id=i.battle_id, generation=i.generation,
                              incarnation=i.incarnation, runtime_id=i.runtime_id)
                ready = await self.ready()
                fields["cleanup_ready_b64"] = encode_control(ready)
                self.revocation_requested = True
                result = (await c.battle_challenge_rpc("cancel_admission", **fields, cleanup_receipt_b64=None))["result"]
                self._retained()
                command = _command(i, self.session, result)
                record = dict(format=FORMAT, intent=i.value(), session=self.session.value(), cancellation=result,
                    ready_b64=encode_control(ready), command_b64=encode_control(command),
                    response_b64=None, host_ack=False, previous_terminal=None)
                _validate(record, i)
                if path_present(self.path):
                    previous = _read(self.path)
                    previous_session, _ = _validate(previous, i)
                    if previous["cancellation"] != result:
                        raise BattleJournalError("battle_recovery_required", "host cancellation tombstone changed")
                    if previous_session == self.session:
                        record = previous
                    else:
                        if (self.session.server_epoch < previous_session.server_epoch or self.session.lease_epoch <= previous_session.lease_epoch):
                            raise BattleJournalError("battle_recovery_required", "cleanup cannot replace newer authentication")
                        archive = self.path.with_name(self.path.stem + "." + str(previous_session.lease_epoch) + ".json")
                        if path_present(archive) and _read(archive) != previous:
                            raise BattleJournalError("battle_recovery_required", "archived cleanup receipt differs")
                        _atomic(archive, _json_bytes(previous))
                        record["previous_terminal"] = (dict(lease=previous_session.lease_epoch,
                            sha256=hashlib.sha256(_json_bytes(previous)).hexdigest())
                            if previous["host_ack"] and previous["response_b64"] is not None else previous["previous_terminal"])
                self.record = record
                _atomic(self.path, _json_bytes(record))
                if record["response_b64"] is None:
                    receipt = await c.battle_rpc(command)
                    receipt.validate_response(command)
                    if receipt.status:
                        raise BattleJournalError("battle_recovery_required", "native core refused neutral admission hold")
                    record["response_b64"] = encode_control(receipt)
                    _atomic(self.path, _json_bytes(record))
                ack = (await c.battle_challenge_rpc("cancel_admission", **fields,
                    cleanup_receipt_b64=record["response_b64"]))["result"]
                if ack != dict(result, acknowledged=True) or self._session() != self.session:
                    raise BattleJournalError("battle_recovery_required", "host did not acknowledge the exact terminal hold")
                record["host_ack"] = True
                _atomic(self.path, _json_bytes(record))
                self._retained()
                c._live_battle_terminal_pending_path = self.path
                pending, archive = d / FILENAME, d / (i.battle_id + ".canceled-admission-intent.json")
                if path_present(pending):
                    if path_present(archive) and archive.read_bytes() != pending.read_bytes():
                        raise BattleJournalError("battle_recovery_required", "archived admission changed before retirement")
                    _atomic(archive, pending.read_bytes())
                    pending.unlink()
                    _sync_directory(d)
            finally:
                c._live_save_owner = c._live_battle_owner = None
                if c._live_battle_executor is self:
                    c._live_battle_executor = None
                self.owner = None
        result = AdmissionCleanupCompletion(i.battle_id, i.generation, i.canonical_revision, i.canonical_sha256, self.session)
        verify_cleanup_completion(c, d, result, i, self.bridge)
        return result


class AdmissionCleanupReadinessAuthority:
    """Read-only exact phase/capacity query; never steals the menu's save lock."""
    def __init__(self, cleanup):
        cleanup._retained()
        self.cleanup, self.owner = cleanup, asyncio.current_task()
        self.session = cleanup._session()
        self.command = _ready_control(cleanup.intent, self.session)
        self.path = cleanup.path.with_name(cleanup.path.stem + ".ready.json")
        self.record = dict(format=FORMAT + "-ready", intent=cleanup.intent.value(), session=self.session.value(),
            command_b64=encode_control(self.command), response_b64=None)

    def _authorizes(self, command):
        c = self.cleanup.companion
        try:
            self.cleanup._retained()
            return (asyncio.current_task() is self.owner and c._live_battle_cleanup_readiness is self
                and command == self.command and self.cleanup._session() == self.session
                and self.record["response_b64"] is None and _read(self.path) == self.record)
        except (ValueError, OSError, ConnectionError):
            return False


class AdmissionCleanupOfflineHoldAuthority:
    """Only replay an already persisted host-authorized HOLD on host loss."""
    def __init__(self, controller, cleanup, record):
        self.controller, self.cleanup, self.record = controller, cleanup, record
        self.owner = asyncio.current_task()
        self.command = _validate(record, cleanup.intent)[1]

    def _authorizes(self, command):
        c, controller, i = self.cleanup.companion, self.controller, self.cleanup.intent
        try:
            self.cleanup._retained()
            return (not c.connected and c._reconnect_blocked and c._emergency_controller is controller
                and controller.bridge is self.cleanup.bridge and not controller._admission_cleanup_successor
                and controller.session == (i.world_id, i.lease_epoch, i.incarnation)
                and controller.base_revision == i.canonical_revision and controller.active_export is None
                and controller.lost.is_set() and asyncio.current_task() is self.owner
                and c._live_save_owner is self.owner and c._live_battle_owner is self.owner
                and c._live_battle_executor is self and command == self.command
                and self.record["response_b64"] is None and _read(self.cleanup.path) == self.record)
        except (ValueError, OSError, ConnectionError):
            return False


async def hold_original_cleanup_for_emergency(controller):
    """A proven terminal hold precedes original-controller deferral, even offline.

    A newly armed successor owns emergency saving normally. This function never
    retires a pending emergency export or invents cancellation after host loss.
    """
    c, d = controller.companion, controller.directory
    if controller._admission_cleanup_successor:
        return False
    pending = d / FILENAME
    if path_present(d / "pending-battle.json"):
        return False
    if path_present(pending):
        intent = read_admission_intent(pending)
        path = cleanup_path(d, intent)
        if not path_present(path):
            return False
    else:
        path = getattr(c, "_live_battle_terminal_pending_path", None)
        if path is None or not str(path).endswith(".admission-cleanup.json"):
            return False
        value = _read(Path(path))
        intent = BattleAdmissionIntent.from_value(value["intent"])
        if Path(path) != cleanup_path(d, intent):
            raise BattleJournalError("battle_recovery_required", "terminal cleanup path changed its owned directory")
    cleanup = AdmissionCleanupSession(c, d, intent)
    cleanup._retained()
    if (c.connected or c._bridge is not controller.bridge or not c._reconnect_blocked
            or controller.session != (intent.world_id, intent.lease_epoch, intent.incarnation)
            or controller.base_revision != intent.canonical_revision or controller.active_export is not None
            or controller.path.exists() or getattr(c, "_live_binding", None) != controller.session):
        raise BattleJournalError("battle_recovery_required", "original cleanup cannot adopt another emergency lifecycle")
    record = _read(path)
    _validate(record, intent)
    if record["response_b64"] is not None:
        return True
    authority = AdmissionCleanupOfflineHoldAuthority(controller, cleanup, record)
    previous = getattr(c, "_live_battle_owner", None), getattr(c, "_live_battle_executor", None)
    c._live_battle_owner, c._live_battle_executor = asyncio.current_task(), authority
    try:
        receipt = await c.battle_rpc(authority.command)
        receipt.validate_response(authority.command)
        if receipt.status:
            raise BattleJournalError("battle_recovery_required", "original native cleanup hold remains uncertain")
        record["response_b64"] = encode_control(receipt)
        _atomic(path, _json_bytes(record))
        cleanup._retained()
        return True
    finally:
        c._live_battle_owner, c._live_battle_executor = previous


class AdmissionCleanupHandoffAuthority(BattleHandoffAuthority):
    """Reuse exact fresh-saver checks; cancellation is a separate typed proof."""
    def _authorizes(self, command):
        c = self.companion
        try:
            self._ready()
            value = _read(cleanup_path(self.directory, self.intent))
            session, held = _validate(value, self.intent)
            return (value["host_ack"] and value["response_b64"] is not None
                and session == self.completion.renewed_session and asyncio.current_task() is self.owner
                and c._live_battle_owner is self.owner and c._live_save_owner is self.owner
                and c._live_battle_executor is self and command == replace(held, opcode=Opcode.ADMISSION_CANCEL_HANDOFF)
                and self.record is not None and self.record["response_b64"] is None and _read(self.path) == self.record)
        except (ValueError, OSError, ConnectionError):
            return False


def _retained_handoff(c, directory, path):
    """Validate immutable local release evidence without requiring a live core."""
    directory = Path(directory)
    record = _read(path)
    try:
        if set(record) != {"format", "intent", "session", "cleanup_sha256", "command_b64", "response_b64"}:
            raise ValueError("invalid handoff record shape")
        intent = BattleAdmissionIntent.from_value(record["intent"])
        session = RenewedBattleSession(**record["session"])
        _identity(session, intent)
        if (record["format"] != FORMAT + "-handoff"
                or path != directory / (intent.battle_id + ".admission-cleanup-handoff.json")
                or (intent.world_id, intent.player_id, intent.build_id, intent.ruleset_id, intent.save_profile)
                    != (c.world_id, c.config.player_id, c.config.build_id, c.config.ruleset_id, c.save_profile)
                or not c.connected or session.lease_epoch > c.session_epoch
                or session.server_epoch > c.server_epoch):
            raise ValueError("handoff belongs to another authenticated world or character")
        if record["response_b64"] is None:
            return None  # A dispatched command is not proof of completion.
        if read_admission_intent(directory / (intent.battle_id + ".canceled-admission-intent.json")) != intent:
            raise ValueError("handoff changed its original admission archive")
        cleanup = cleanup_path(directory, intent)
        value = _read(cleanup)
        if hashlib.sha256(_json_bytes(value)).hexdigest() != record["cleanup_sha256"]:
            cleanup = cleanup.with_name(cleanup.stem + "." + str(session.lease_epoch) + ".json")
            value = _read(cleanup)
        recorded, held = _validate(value, intent)
        if (recorded != session or not value["host_ack"] or value["response_b64"] is None
                or hashlib.sha256(_json_bytes(value)).hexdigest() != record["cleanup_sha256"]):
            raise ValueError("handoff lacks its original acknowledged cleanup")
        command = replace(held, opcode=Opcode.ADMISSION_CANCEL_HANDOFF)
        receipt = decode_control(record["response_b64"], response=True)
        receipt.validate_response(command)
        if receipt.status or record["command_b64"] != encode_control(command):
            raise ValueError("handoff lacks its exact successful native receipt")
        return intent, receipt
    except (ValueError, TypeError, KeyError) as error:
        raise BattleJournalError("battle_recovery_required", "retained admission handoff proof is inconsistent") from error


async def publish_cleanup_handoffs(c, directory, *, battle_id=None):
    """Deliver completed historical receipts; never replay a native operation.

    The immutable receipt remains the outbox until its exact host ACK is local.
    Cold startup and Championship reads also call this after authentication.
    """
    from .battle_admission_cleanup_protocol import handoff_view, validate_handoff_view
    directory = Path(directory)
    if battle_id is not None:
        from .battle_journal import _uuid
        _uuid(battle_id)
        paths = [directory / (battle_id + ".admission-cleanup-handoff.json")]
    else:
        paths = sorted(directory.glob("*.admission-cleanup-handoff.json"))
    for path in paths:
        retained = _retained_handoff(c, directory, path)
        if retained is None:
            continue
        intent, receipt = retained
        ack_path = path.with_suffix(".host-ack.json")
        expected = handoff_view(receipt)
        ack = dict(format=FORMAT + "-host-handoff-ack", world_id=intent.world_id,
            player_id=intent.player_id, result=expected)
        if path_present(ack_path):
            if _read(ack_path) != ack:
                raise BattleJournalError("battle_recovery_required", "host handoff acknowledgment changed")
            continue
        # Negotiate through an existing operation first. Older hosts reject
        # the optional field with a normal RPC error, without losing the lease
        # to an unknown message type. Such hosts keep the receipt queued.
        supported = await _handoff_publication_available(c)
        if not supported:
            return
        fields = dict(battle_id=intent.battle_id, generation=intent.generation,
            incarnation=intent.incarnation, runtime_id=intent.runtime_id,
            handoff_receipt_b64=encode_control(receipt))
        result = (await c.battle_challenge_rpc("admission_handoff", **fields))["result"]
        validate_handoff_view(result, intent.player_id, fields)
        # Publishing is observational, but never acknowledge a receipt that
        # changed locally or changed authenticated world while in flight.
        if _retained_handoff(c, directory, path) != retained or result != expected:
            raise BattleJournalError("battle_recovery_required", "handoff changed during host publication")
        _atomic(ack_path, _json_bytes(ack))


async def _handoff_publication_available(c):
    from .companion import BattleChallengeError
    key = (c.world_id, c.server_epoch, c.session_epoch)
    if not c.connected:
        raise ConnectionError("handoff publication needs authenticated host access")
    cached = getattr(c, "_admission_handoff_publication", None)
    if cached is not None and cached[0] == key:
        return cached[1]
    try:
        response = await c.battle_challenge_rpc("pending", admission_handoff_version=1)
        supported = response.get("admission_handoff_version") == 1
    except BattleChallengeError as error:
        if error.code not in {"invalid_fields", "admission_handoff_unsupported", "battle_disabled"}:
            raise
        supported = False
    if not c.connected or key != (c.world_id, c.server_epoch, c.session_epoch):
        raise ConnectionError("handoff capability changed its authenticated session")
    c._admission_handoff_publication = (key, supported)
    return supported


async def complete_cleanup_handoff(c, directory, completion, intent, bridge, successor):
    # Preserve the existing native-to-saver ownership boundary. Publication of
    # this durable receipt happens on a later Championship read/cold readiness;
    # no new network await can interrupt Launcher adoption after native release.
    authority = AdmissionCleanupHandoffAuthority(c, directory, completion, intent, bridge, successor)
    authority.path = Path(directory) / (intent.battle_id + ".admission-cleanup-handoff.json")
    async with c.live_checkpoint_lock:
        value = verify_cleanup_completion(c, directory, completion, intent, bridge)
        authority._ready()
        command = replace(decode_control(value["command_b64"]), opcode=Opcode.ADMISSION_CANCEL_HANDOFF)
        record = dict(format=FORMAT + "-handoff", intent=intent.value(), session=completion.renewed_session.value(),
            cleanup_sha256=hashlib.sha256(_json_bytes(value)).hexdigest(), command_b64=encode_control(command), response_b64=None)
        if path_present(authority.path):
            previous = _read(authority.path)
            if dict(previous, response_b64=None) != record:
                raise BattleJournalError("battle_recovery_required", "cleanup handoff evidence changed")
            if previous["response_b64"] is not None:
                receipt = decode_control(previous["response_b64"], response=True)
                receipt.validate_response(command)
                if receipt.status:
                    raise BattleJournalError("battle_recovery_required", "cleanup handoff receipt was refused")
                c._live_battle_terminal_pending_path = None
                return completion
        authority.record = record
        _atomic(authority.path, _json_bytes(record))
        c._live_save_owner = c._live_battle_owner = authority.owner
        c._live_battle_executor = authority
        try:
            receipt = await c.battle_rpc(command)
            receipt.validate_response(command)
            if receipt.status:
                raise BattleJournalError("battle_recovery_required", "native cleanup handoff was refused")
            record["response_b64"] = encode_control(receipt)
            _atomic(authority.path, _json_bytes(record))
            authority._ready()
            c._live_battle_terminal_pending_path = None
            return completion
        finally:
            c._live_save_owner = c._live_battle_owner = None
            if c._live_battle_executor is authority:
                c._live_battle_executor = None
