"""One client-owned native execution, after an acknowledged menu close.

Every mutation is the host-issued exact command persisted before mailbox use.
The original battle intent remains until all native RELEASE receipts close the
host lifecycle. Failure leaves it and the original held core available.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import stat

from .battle_execution_protocol import decode_control, encode_control, validate_execution_view
from .battle_journal import BattleJournal, BattleJournalError, path_present, read_battle_intent
from .battle_protocol import _view
from .battle_roster import CanonicalBattler
from .checkpoint_client import CheckpointClient
from .live_checkpoint import _atomic, _json_bytes, _sync_directory
from .native_battle import NativeBinding, NativeControl, Opcode, Preparation
from .storage import Checkpoint


@dataclass(frozen=True)
class RenewedBattleSession:
    world_id: str
    player_id: str
    build_id: str
    ruleset_id: str
    save_profile: str
    server_epoch: int
    lease_epoch: int
    incarnation: int
    runtime_id: str

    def __post_init__(self):
        from .battle_journal import _uuid, _counter, _identifier
        from .ownership import OWNERSHIP_PROFILE
        for value in (self.world_id, self.player_id, self.runtime_id):
            _uuid(value)
        for value in (self.build_id, self.ruleset_id):
            _identifier(value)
        for value in (self.server_epoch, self.lease_epoch):
            _counter(value)
        _counter(self.incarnation, 0xFFFFFFFF)
        if self.save_profile != OWNERSHIP_PROFILE:
            raise ValueError("battle renewal requires the exact ownership profile")

    def value(self):
        return asdict(self)


@dataclass(frozen=True)
class BattleCompletion:
    battle_id: str
    generation: str
    canonical_revision: int
    canonical_sha256: str
    state: str = "closed"
    renewed_session: RenewedBattleSession | None = None


class NativeBattleSession:
    def __init__(self, companion, private_directory):
        self.companion = companion
        self.journal = BattleJournal(companion, private_directory)
        self.path = self.journal.directory / "native-battle-execution.json"
        self.intent = None
        self._command = None
        self._dispatch_id = 0
        self._response = None
        self._active = False
        self._terminal_authority = None
        self.bridge = getattr(companion, "_bridge", None)
        self.admission_intent = self.admission_receipt = None

    def _persist(self, state="executing"):
        _atomic(self.path, _json_bytes(dict(format="native-battle-client-execution-v1",
            state=state, intent=self.intent.value(), dispatch_id=self._dispatch_id,
            command_b64=encode_control(self._command),
            response_b64=None if self._response is None else encode_control(self._response))))

    def _authorizes(self, control):
        """Companion-only mutation capability; a pending filename is no grant."""
        if self._terminal_authority is not None:
            return self._terminal_authority.authorizes(control)
        c = self.companion
        if (not self._active or c._live_battle_owner is not asyncio.current_task()
                or getattr(c, "_live_battle_executor", None) is not self
                or control != self._command or self.intent is None):
            return False
        try:
            if getattr(c.config, "battle_resume_abi_version", 0) == 1 and c._bridge is not self.bridge:
                return False
            self.journal._current(self.intent)
            if read_battle_intent(self.journal.path) != self.intent:
                return False
            if not stat.S_ISREG(self.path.lstat().st_mode):
                return False
            with self.path.open("rb") as source:
                raw = source.read(32769)
            return raw == _json_bytes(dict(format="native-battle-client-execution-v1",
                state="executing", intent=self.intent.value(), dispatch_id=self._dispatch_id,
                command_b64=encode_control(control), response_b64=None))
        except (ValueError, OSError):
            return False

    async def _terminal(self, view):
        if (view["state"] != "closed" or self._command is None
                or self._command.opcode != Opcode.RELEASE or self._response is None
                or self._response.status):
            raise BattleJournalError("battle_recovery_required", "all native releases have not been verified")
        self._response.validate_response(self._command)
        self.journal._current(self.intent)
        if read_battle_intent(self.journal.path) != self.intent:
            raise BattleJournalError("battle_recovery_required", "battle intent changed before settlement")
        renewed = None
        if getattr(self.companion.config, "battle_resume_abi_version", 0) == 1:
            from .battle_terminal import retire_battle
            from .battle_recovery_session import FORMAT
            import base64
            renewed = await retire_battle(self, view, self._command, self._response)
            encoded = encode_control(self._command)
            response = encode_control(self._response)
            record = dict(format=FORMAT, state="closed", intent=self.intent.value(),
                renewed_session=renewed.value(), binding_b64=base64.b64encode(self.intent.bind.data).decode("ascii"),
                stage="route", dispatch_id=self._dispatch_id, command_b64=encoded, response_b64=response,
                route_id=self._dispatch_id, route_command_b64=encoded, route_response_b64=response,
                release_command_b64=encoded, release_response_b64=response)
            terminal = self.journal.directory / (self.intent.battle_id + ".battle-recovery-complete.json")
            if path_present(terminal) and terminal.read_bytes() != _json_bytes(record):
                raise BattleJournalError("battle_recovery_required", "normal battle terminal receipt changed")
            _atomic(terminal, _json_bytes(record))
        # Keep the completed execution evidence before removing the admission
        # barrier. A crash before unlink is conservative, never double release.
        self._persist("closed")
        receipt = self.journal.directory / (self.intent.battle_id + ".battle-complete.json")
        if path_present(receipt):
            raise BattleJournalError("battle_recovery_required", "battle completion path already exists")
        _atomic(receipt, self.path.read_bytes())
        if read_battle_intent(self.journal.path) != self.intent:
            raise BattleJournalError("battle_recovery_required", "battle intent changed during settlement")
        self.journal.path.unlink()
        _sync_directory(self.journal.directory)
        return BattleCompletion(self.intent.battle_id, self.intent.generation,
                                self.intent.canonical_revision, self.intent.canonical_sha256,
                                renewed_session=renewed)

    async def run(self, challenge):
        c = self.companion
        _view(challenge, c.config.player_id)
        if (challenge["state"] != "accepted" or set(challenge["consent"]) != set(challenge["players"])
                or self._active or self.intent is not None):
            raise BattleJournalError("battle_not_ready", "all players must accept the exact challenge")
        if getattr(c.config, "battle_resume_abi_version", 0) == 1:
            from .battle_admission_session import prepare_battle_admission, read_admission_receipt
            self.admission_intent = await prepare_battle_admission(c, self.journal.directory, challenge)
            self.admission_receipt = read_admission_receipt(self.journal.directory, self.admission_intent)
        captured = self.journal._session()
        actor = c.config.player_id
        slot = challenge["players"].index(actor)
        async with c.live_checkpoint_lock:
            if (getattr(c, "_live_save_owner", None) is not None
                    or getattr(c, "_live_battle_owner", None) is not None
                    or path_present(self.journal.path)):
                raise BattleJournalError("character_busy", "resolve the existing character lifecycle first")
            self.journal._other_recovery()
            c._live_save_owner = c._live_battle_owner = asyncio.current_task()
            c._live_battle_executor = self
            c._live_battle_admission_control = None
            self._active = True
            try:
                downloaded = await CheckpointClient(c).download()
                if downloaded is None or self.journal._session() != captured:
                    raise BattleJournalError("canonical_head_mismatch", "battle checkpoint is unavailable")
                meta = downloaded.metadata
                checkpoint = Checkpoint(actor, meta["revision"], meta["request_id"], downloaded.payload,
                    meta["sha256"], meta["build_id"], meta["ruleset_id"], meta["save_profile"])
                roster = CanonicalBattler.from_checkpoint(checkpoint, world_id=c.world_id,
                    build_id=c.config.build_id, ruleset_id=c.config.ruleset_id,
                    source_slot=slot, mode=challenge["mode"])
                accepted = challenge["checkpoints"][slot]
                if (roster.revision, roster.checkpoint_sha256, roster.party_count) != (
                        accepted["revision"], accepted["sha256"], accepted["party_count"]):
                    raise BattleJournalError("canonical_head_mismatch", "party changed after challenge consent")
                binding = None
                admission_sha256 = None
                while True:
                    if self.journal._session() != captured:
                        raise BattleJournalError("battle_recovery_required", "retain the original held battle core")
                    if getattr(c.config, "battle_resume_abi_version", 0) == 1 and c._bridge is not self.bridge:
                        raise BattleJournalError("battle_recovery_required", "native execution lost its original bridge")
                    admission = {} if admission_sha256 is None else {"admission_sha256": admission_sha256}
                    if self.admission_intent is not None:
                        from .battle_admission_session import admission_fields
                        admission.update(admission_fields(self.admission_intent, self.admission_receipt))
                    view = (await c.battle_challenge_rpc("execute", battle_id=challenge["battle_id"],
                        generation=challenge["generation"], incarnation=c.battle_incarnation,
                        response_id=self._dispatch_id if self._response is not None else 0,
                        response_b64=None if self._response is None else encode_control(self._response), **admission))["result"]
                    validate_execution_view(view, request=dict(battle_id=challenge["battle_id"],
                        generation=challenge["generation"], incarnation=c.battle_incarnation,
                        session_epoch=captured[6]))
                    if self.journal._session() != captured:
                        raise BattleJournalError("battle_recovery_required", "authenticated battle session changed")
                    if view["state"] == "closed":
                        return await self._terminal(view)
                    if view["state"] == "aborted" and self.intent is None and self.admission_intent is None:
                        return BattleCompletion(challenge["battle_id"], challenge["generation"],
                            roster.revision, roster.checkpoint_sha256, state="aborted")
                    if view["state"] in ("aborted", "recovery_required"):
                        raise BattleJournalError("battle_recovery_required", "battle remains held for recovery")
                    if view["command_b64"] is None:
                        await asyncio.sleep(.01)
                        continue
                    command = decode_control(view["command_b64"])
                    dispatch_id = view["command_id"]
                    if view["state"] == "admitting":
                        if command.opcode != Opcode.BIND or self._response is not None:
                            raise BattleJournalError("battle_order", "admission can only persist the original BIND")
                        proposed = NativeBinding.unpack(command.data)
                        if (proposed.generation, proposed.players, proposed.local_slot, proposed.mode) != (
                                challenge["generation"], tuple(challenge["players"]), slot, challenge["mode"]):
                            raise BattleJournalError("battle_intent_mismatch", "admission roster changed after consent")
                        command.validate_command(binding=proposed, player_id=actor)
                        if command.battle_id != challenge["battle_id"]:
                            raise BattleJournalError("battle_intent_mismatch", "admission targets another battle")
                        if self.intent is None:
                            if dispatch_id != self._dispatch_id + 1:
                                raise BattleJournalError("battle_order", "first admission dispatch skipped a command")
                            binding = proposed
                            if self.admission_intent is not None:
                                from .battle_admission_session import original_battle_intent
                                original_battle_intent(self.admission_intent, self.admission_receipt, command,
                                    self.admission_intent.server_epoch)
                            self.intent = await self.journal._admit(binding, command, roster)
                        elif (self.intent.bind, self._command, self._dispatch_id) != (command, command, dispatch_id):
                            raise BattleJournalError("battle_order", "durable admission retry changed its exact BIND")
                        self._command, self._dispatch_id, self._response = command, dispatch_id, None
                        c._live_battle_admission_control = None
                        self._persist("admitting")
                        if self.admission_intent is not None:
                            from .battle_admission_session import finish_conversion
                            finish_conversion(self.journal.directory, self.admission_intent, self.intent)
                        admission_sha256 = hashlib.sha256(command.pack()).hexdigest()
                        await asyncio.sleep(.01)
                        continue
                    admitted_dispatch = (admission_sha256 is not None and self.intent is not None
                        and command == self.intent.bind == self._command and dispatch_id == self._dispatch_id
                        and self._response is None)
                    if dispatch_id == self._dispatch_id:
                        if not admitted_dispatch and (command != self._command or self._response is None):
                            raise BattleJournalError("battle_order", "native dispatch retry changed its command")
                        if not admitted_dispatch:
                            continue
                    if not admitted_dispatch and dispatch_id != self._dispatch_id + 1:
                        raise BattleJournalError("battle_order", "native dispatch IDs must be consecutive")
                    if binding is None:
                        if command.opcode != Opcode.BIND:
                            raise BattleJournalError("battle_order", "native execution must begin with BIND")
                        if getattr(c.config, "battle_resume_abi_version", 0) == 1:
                            raise BattleJournalError("battle_order", "resumable BIND requires the exact durable admission barrier")
                        binding = NativeBinding.unpack(command.data)
                        if (binding.generation, binding.players, binding.local_slot, binding.mode) != (
                                challenge["generation"], tuple(challenge["players"]), slot, challenge["mode"]):
                            raise BattleJournalError("battle_intent_mismatch", "native roster changed after consent")
                        self.intent = await self.journal._admit(binding, command, roster)
                        c._live_battle_admission_control = command
                    elif command.opcode == Opcode.BIND and not admitted_dispatch:
                        raise BattleJournalError("battle_order", "native execution cannot replace its BIND")
                    command.validate_command(binding=binding, player_id=actor)
                    if command.battle_id != challenge["battle_id"]:
                        raise BattleJournalError("battle_intent_mismatch", "native command targets another battle")
                    if command.opcode == Opcode.PREPARE:
                        preparation = Preparation.unpack(command.data)
                        if preparation != roster.preparation(preparation.rng, challenge.get("gym", 0)):
                            raise BattleJournalError("canonical_head_mismatch", "native preparation changed the personal party")
                    self._command, self._dispatch_id, self._response = command, dispatch_id, None
                    self._persist()
                    response = await c.battle_rpc(command)
                    response.validate_response(command)
                    self._response = response
                    self._persist()
                    admission_sha256 = None
                    self.admission_intent = self.admission_receipt = None
            finally:
                self._active = False
                c._live_save_owner = c._live_battle_owner = None
                c._live_battle_admission_control = None
                if getattr(c, "_live_battle_executor", None) is self:
                    c._live_battle_executor = None
