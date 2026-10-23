"""Explicit recovery of the same live battle core under renewed authentication.

The original admission intent never changes. Host-issued controls and their
receipts are persisted separately before they can authorize native mutation.
No new core, canonical head adoption, save import or battle result is invented.
"""
from __future__ import annotations

import asyncio
import base64
from dataclasses import replace
import json
from pathlib import Path
import stat

from .battle_execution_protocol import decode_control, encode_control
from .battle_journal import BattleIntent, BattleJournal, BattleJournalError, path_present, read_battle_intent
from .battle_roster import CanonicalBattler
from .battle_session import BattleCompletion, RenewedBattleSession
from .checkpoint_client import CheckpointClient
from .live_checkpoint import _atomic, _json_bytes, _sync_directory
from .rival_catalogue import valid_preparation_word
from .native_battle import COOP_PHASE, NativeBinding, NativeQuery, Opcode, Preparation, ordinary_route, supports_native_phase
from .native_battle_resume import ResumeAuthorization, ResumeQuery
from .storage import Checkpoint

FORMAT = "native-battle-client-recovery-v1"
RECORD_FIELDS = {"format", "state", "intent", "renewed_session", "binding_b64", "stage",
    "dispatch_id", "command_b64", "response_b64", "route_id", "route_command_b64", "route_response_b64",
    "release_command_b64", "release_response_b64"}


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
    except (OSError, ValueError, TypeError, RecursionError) as error:
        raise BattleJournalError("battle_recovery_required", "retained battle evidence is malformed") from error


def _binding(value):
    try:
        raw = base64.b64decode(value, validate=True)
        if base64.b64encode(raw).decode("ascii") != value:
            raise ValueError()
        return NativeBinding.unpack(raw)
    except (ValueError, TypeError) as error:
        raise BattleJournalError("battle_recovery_required", "retained battle binding is malformed") from error


def _same_roster(new, old):
    ResumeAuthorization(new, b"r"*16, 1, 1).validate_previous(old)


def _release(command, response, intent):
    if command is None or response is None or command.opcode != Opcode.RELEASE or response.status:
        raise BattleJournalError("battle_recovery_required", "an exact successful native RELEASE receipt is required")
    response.validate_response(command)
    if (command.battle_id, command.incarnation, command.phase) != (
            intent.battle_id, intent.incarnation, intent.bind.phase):
        raise BattleJournalError("battle_recovery_required", "native RELEASE belongs to another retained battle")


def _record_pair(command_value, response_value, dispatch_id, intent, renewed):
    if (type(dispatch_id) is not int or not 0 <= dispatch_id <= 0x7FFFFFFF
            or (dispatch_id == 0) != (command_value is None)
            or (command_value is None and response_value is not None)):
        raise BattleJournalError("battle_recovery_required", "retained dispatch and receipt are inconsistent")
    command = None if command_value is None else decode_control(command_value)
    response = None if response_value is None else decode_control(response_value, response=True)
    if command is not None:
        binding = NativeBinding.unpack(intent.bind.data)
        if ((command.battle_id, command.incarnation, command.phase) != (intent.battle_id, intent.incarnation, intent.bind.phase)
                or not intent.lease_epoch <= command.session_epoch <= renewed.lease_epoch
                or (command.opcode != Opcode.RECEIVE and command.source_slot != binding.local_slot)):
            raise BattleJournalError("battle_recovery_required", "retained dispatch belongs to another original core")
        if response is not None:
            response.validate_response(command)
    return command, response


def _validate_record(value, intent):
    if (set(value) != RECORD_FIELDS or value["format"] != FORMAT
            or value["state"] not in {"executing", "closed"} or value["intent"] != intent.value()
            or value["stage"] not in {"recovery", "route"} or type(value["renewed_session"]) is not dict):
        raise BattleJournalError("battle_recovery_required", "renewal evidence differs from the original intent")
    try:
        renewed = RenewedBattleSession(**value["renewed_session"])
    except (TypeError, ValueError, OverflowError) as error:
        raise BattleJournalError("battle_recovery_required", "retained renewal session is malformed") from error
    if ((renewed.world_id, renewed.player_id, renewed.build_id, renewed.ruleset_id,
         renewed.save_profile, renewed.incarnation, renewed.runtime_id) !=
        (intent.world_id, intent.player_id, intent.build_id, intent.ruleset_id,
         intent.save_profile, intent.incarnation, intent.runtime_id)
            or renewed.server_epoch < intent.server_epoch or renewed.lease_epoch < intent.lease_epoch
            or (renewed.lease_epoch == intent.lease_epoch and renewed.server_epoch != intent.server_epoch)):
        raise BattleJournalError("battle_recovery_required", "retained renewal changed the original identity")
    bound = _binding(value["binding_b64"])
    original = NativeBinding.unpack(intent.bind.data)
    _same_roster(bound, original)
    if bound.leases[bound.local_slot] > renewed.lease_epoch:
        raise BattleJournalError("battle_recovery_required", "native binding exceeds authenticated renewal")
    command, response = _record_pair(value["command_b64"], value["response_b64"], value["dispatch_id"], intent, renewed)
    route, route_response = _record_pair(value["route_command_b64"], value["route_response_b64"], value["route_id"], intent, renewed)
    if route is not None and not ordinary_route(route.opcode):
        raise BattleJournalError("battle_recovery_required", "retained ordinary route contains recovery commands")
    if value["stage"] == "route":
        if (command, response, value["dispatch_id"]) != (route, route_response, value["route_id"]):
            raise BattleJournalError("battle_recovery_required", "latest route and dispatch evidence disagree")
    elif command is not None:
        if command.opcode not in {Opcode.QUERY, Opcode.SUSPEND, Opcode.REAUTHORIZE, Opcode.RESUME, Opcode.BIND}:
            raise BattleJournalError("battle_recovery_required", "retained recovery dispatched an ordinary mutation")
        if command.opcode == Opcode.REAUTHORIZE and ResumeAuthorization.unpack(command.data).binding != bound:
            raise BattleJournalError("battle_recovery_required", "persisted reauthorization changed its native binding")
    release, released = _record_pair(value["release_command_b64"], value["release_response_b64"],
        0 if value["release_command_b64"] is None else 1, intent, renewed)
    if release is not None or value["state"] == "closed":
        _release(release, released, intent)
    return bound, renewed


def verify_recovery_completion(companion, directory, completion, intent, bridge, *, _pending_allowed=False):
    """Recheck durable terminal evidence before transferring save ownership."""
    if (type(completion) is not BattleCompletion or type(completion.renewed_session) is not RenewedBattleSession
            or (completion.battle_id, completion.generation, completion.canonical_revision,
                completion.canonical_sha256, completion.state) !=
               (intent.battle_id, intent.generation, intent.canonical_revision, intent.canonical_sha256, "closed")):
        raise BattleJournalError("battle_recovery_required", "completion differs from the original canonical battle")
    session = completion.renewed_session
    c = companion
    current = RenewedBattleSession(c.world_id, c.config.player_id, c.config.build_id, c.config.ruleset_id,
        c.save_profile, c.server_epoch, c.session_epoch, c.battle_incarnation, c._live_battle_runtime_id)
    if (c.connected is not True or c._bridge is not bridge or current != session
            or getattr(c, "_live_save_owner", None) is not None or getattr(c, "_live_battle_owner", None) is not None):
        raise BattleJournalError("battle_recovery_required", "completion lost its exact retained authenticated core")
    directory = Path(directory)
    pending = directory / "pending-battle.json"
    if path_present(pending) and (not _pending_allowed or read_battle_intent(pending) != intent):
        raise BattleJournalError("battle_recovery_required", "battle admission has not completed terminal settlement")
    value = _read(directory / (intent.battle_id + ".battle-recovery-complete.json"))
    bound, recorded_session = _validate_record(value, intent)
    if (value.get("format") != FORMAT or value.get("state") != "closed"
            or value.get("intent") != intent.value() or value.get("renewed_session") != session.value()):
        raise BattleJournalError("battle_recovery_required", "durable terminal receipt differs from completion")
    if recorded_session != session or bound.leases[bound.local_slot] != session.lease_epoch:
        raise BattleJournalError("battle_recovery_required", "terminal native binding differs from authenticated lease")
    _release(decode_control(value.get("release_command_b64")),
             decode_control(value.get("release_response_b64"), response=True), intent)
    from .battle_terminal import verify_retirement
    verify_retirement(c, directory, intent, bridge, session)
    return value


class NativeBattleRecoverySession:
    def __init__(self, companion, private_directory, *, original_intent=None):
        from .battle_admission_intent import BattleAdmissionIntent, FILENAME as ADMISSION_FILE, read_admission_intent
        self.companion = companion
        self.journal = BattleJournal(companion, private_directory)
        self.admission_path = self.journal.directory / ADMISSION_FILE
        self.original_admission = None
        self._provisional = False
        self._admission_sha256 = None
        if path_present(self.journal.path):
            self.intent = read_battle_intent(self.journal.path)
            if type(original_intent) is BattleAdmissionIntent:
                from .battle_admission_session import read_admission_receipt, original_battle_intent
                self.original_admission = original_intent
                receipt = read_admission_receipt(self.journal.directory, original_intent)
                if original_battle_intent(original_intent, receipt, self.intent.bind, self.intent.server_epoch) != self.intent:
                    raise BattleJournalError("battle_recovery_required", "full BIND no longer matches its original provisional intent")
            elif original_intent is not None and self.intent != original_intent:
                raise BattleJournalError("battle_recovery_required", "retained original intent changed")
        elif path_present(self.admission_path):
            self.intent = read_admission_intent(self.admission_path)
            if original_intent is not None and original_intent != self.intent:
                raise BattleJournalError("battle_recovery_required", "retained provisional intent changed")
            self.original_admission = self.intent
            self._provisional = True
        elif type(original_intent) is BattleIntent:
            self.intent = original_intent
        elif type(original_intent) is BattleAdmissionIntent:
            from .battle_admission_session import verify_admission_conversion
            terminal = _read(self.journal.directory / (original_intent.battle_id + ".battle-recovery-complete.json"))
            self.intent = BattleIntent.from_value(terminal["intent"])
            verify_admission_conversion(self.journal.directory, original_intent, self.intent)
            self.original_admission = original_intent
        else:
            raise BattleJournalError("battle_recovery_required", "recovery requires the retained original admission intent")
        self.bridge = companion._bridge
        self.path = self.journal.directory / (self.intent.battle_id + ".native-battle-recovery.json")
        self.original_binding = None if self._provisional else NativeBinding.unpack(self.intent.bind.data)
        self.binding = self.original_binding
        self.renewed_session = None
        self._active = False
        self._owner = None
        self._stage = "recovery"
        self._dispatch_id = 0
        self._command = self._response = None
        self._route_id = 0
        self._route_command = self._route_response = None
        self._release_command = self._release_response = None
        self._observation = self._authorization = None
        self.roster = None
        self._terminal_authority = None
        self._terminal_only = not self._provisional and not path_present(self.journal.path)
        if self._terminal_only:
            self._terminal_evidence()
            companion._live_battle_terminal_pending_path = self.journal.directory / (self.intent.battle_id + ".battle-retirement.json")

    def _terminal_evidence(self):
        from .battle_terminal import _validate as validate_retirement, _read as read_retirement
        value = _read(self.journal.directory / (self.intent.battle_id + ".battle-recovery-complete.json"))
        _, session = _validate_record(value, self.intent)
        retired = read_retirement(self.journal.directory / (self.intent.battle_id + ".battle-retirement.json"))
        retired_session, _ = validate_retirement(retired, self.intent)
        if retired_session != session:
            if retired_session.lease_epoch <= session.lease_epoch or retired_session.server_epoch < session.server_epoch:
                raise BattleJournalError("battle_recovery_required", "terminal retirement authentication moved backwards")
            archived = read_retirement(self.journal.directory / (self.intent.battle_id + ".battle-retirement."
                + str(session.server_epoch) + "." + str(session.lease_epoch) + ".json"))
            archived_session, _ = validate_retirement(archived, self.intent)
            if archived_session != session or archived["response_b64"] is None:
                raise BattleJournalError("battle_recovery_required", "terminal retry lost its original retirement receipt")
        elif retired["response_b64"] is None:
            raise BattleJournalError("battle_recovery_required", "terminal native retirement is unacknowledged")
        if value["state"] != "closed":
            raise BattleJournalError("battle_recovery_required", "terminal retry lacks exact completed native retirement")
        return value

    def _retained(self, *, intent_required=None):
        if intent_required is None:
            intent_required = not self._terminal_only
        c, i = self.companion, self.intent
        phase = i.admit.phase if self._provisional else i.bind.phase
        if (self.bridge is None or c._bridge is not self.bridge or not self.bridge.battle_capable
                or c.battle_incarnation != i.incarnation
                or getattr(c, "_live_battle_runtime_id", None) != i.runtime_id
                or (c.config.player_id, c.config.build_id, c.config.ruleset_id) != (i.player_id, i.build_id, i.ruleset_id)
                or c.config.development_battle_channel is not True
                or c.config.ownership_enabled is not True
                or type(c.config.server_credential) is not bytes or len(c.config.server_credential) != 32
                or getattr(c.config, "battle_resume_abi_version", 0) != 1
                or not supports_native_phase(c.config.battle_abi_version, phase)
                or (not self._provisional and not self.original_binding.resumable)):
            raise BattleJournalError("battle_recovery_required", "recovery requires the exact original opted-in live core")
        if intent_required:
            from .battle_admission_intent import read_admission_intent
            retained = read_admission_intent(self.admission_path) if self._provisional else read_battle_intent(self.journal.path)
            if retained != i:
                raise BattleJournalError("battle_recovery_required", "original battle admission intent changed")
        if not intent_required:
            self._terminal_evidence()
        self.journal._other_recovery()
        if path_present(self.journal.directory / "pending-emergency.json"):
            raise BattleJournalError("battle_recovery_required", "native emergency preservation already owns this core")

    def _session(self):
        c = self.companion
        if c.connected is not True:
            raise ConnectionError("retained battle is waiting for the authenticated host")
        session = RenewedBattleSession(c.world_id, c.config.player_id, c.config.build_id, c.config.ruleset_id,
            c.save_profile, c.server_epoch, c.session_epoch, c.battle_incarnation, c._live_battle_runtime_id)
        self._validate_session(session)
        return session

    def _validate_session(self, session):
        i = self.intent
        if ((session.world_id, session.player_id, session.build_id, session.ruleset_id, session.save_profile,
             session.incarnation, session.runtime_id) !=
            (i.world_id, i.player_id, i.build_id, i.ruleset_id, i.save_profile, i.incarnation, i.runtime_id)
                or session.server_epoch < i.server_epoch or session.lease_epoch < i.lease_epoch
                or (session.lease_epoch == i.lease_epoch and session.server_epoch != i.server_epoch)):
            raise BattleJournalError("battle_recovery_required", "renewed authentication changed the retained identity")
        previous = self.renewed_session
        if previous is not None and (session.server_epoch < previous.server_epoch or session.lease_epoch < previous.lease_epoch
                or (session.lease_epoch == previous.lease_epoch and session.server_epoch != previous.server_epoch)):
            raise BattleJournalError("battle_recovery_required", "renewed battle authentication moved backwards")

    def _authorizes_reconnect(self):
        c = self.companion
        try:
            self._retained()
            return (self._active and self._owner is asyncio.current_task()
                and c._live_save_owner is self._owner and c._live_battle_owner is self._owner
                and getattr(c, "_live_battle_executor", None) is self)
        except (ValueError, OSError, ConnectionError):
            return False

    def _accept_welcome(self, welcome):
        # Called by the dedicated network reader before it publishes connected.
        self._retained()
        c = self.companion
        if (not self._active or c._live_save_owner is not self._owner
                or getattr(c, "_battle_recovery_authority", None) is not self):
            raise BattleJournalError("battle_recovery_required", "battle reconnect authority expired")
        session = RenewedBattleSession(welcome["world_id"], c.config.player_id, c.config.build_id,
            c.config.ruleset_id, welcome["save_profile"], welcome["server_epoch"], welcome["session_epoch"],
            self.intent.incarnation, self.intent.runtime_id)
        self._validate_session(session)

    def _record(self, state="executing"):
        encode = lambda command: None if command is None else encode_control(command)
        return dict(format=FORMAT, state=state, intent=self.intent.value(),
            renewed_session=None if self.renewed_session is None else self.renewed_session.value(),
            binding_b64=base64.b64encode(self.binding.pack()).decode("ascii"),
            stage=self._stage, dispatch_id=self._dispatch_id, command_b64=encode(self._command), response_b64=encode(self._response),
            route_id=self._route_id, route_command_b64=encode(self._route_command), route_response_b64=encode(self._route_response),
            release_command_b64=encode(self._release_command), release_response_b64=encode(self._release_response))

    def _persist(self, state="executing"):
        _atomic(self.path, _json_bytes(self._record(state)))

    def _authorizes(self, control):
        if self._terminal_authority is not None:
            return self._terminal_authority.authorizes(control)
        if not self._authorizes_reconnect() or control != self._command or self._response is not None:
            return False
        try:
            return self._session() == self.renewed_session and _read(self.path) == self._record()
        except (ValueError, OSError, ConnectionError):
            return False

    def _load(self):
        if self._provisional:
            return
        execution = self.journal.directory / "native-battle-execution.json"
        if path_present(execution):
            value = _read(execution)
            fields = {"format", "state", "intent", "dispatch_id", "command_b64", "response_b64"}
            if (set(value) != fields or value["format"] != "native-battle-client-execution-v1"
                    or value["state"] not in {"admitting", "executing", "closed"} or value["intent"] != self.intent.value()):
                raise BattleJournalError("battle_recovery_required", "execution evidence differs from the original intent")
            if value["state"] == "admitting" and (value["command_b64"] != encode_control(self.intent.bind)
                    or value["response_b64"] is not None):
                raise BattleJournalError("battle_recovery_required", "admission must retain the unanswered exact original BIND")
            if value["state"] == "admitting":
                import hashlib
                self._admission_sha256 = hashlib.sha256(self.intent.bind.pack()).hexdigest()
            original_session = RenewedBattleSession(self.intent.world_id, self.intent.player_id,
                self.intent.build_id, self.intent.ruleset_id, self.intent.save_profile,
                self.intent.server_epoch, self.intent.lease_epoch, self.intent.incarnation, self.intent.runtime_id)
            self._route_id = value["dispatch_id"]
            self._route_command, self._route_response = _record_pair(value["command_b64"],
                value["response_b64"], self._route_id, self.intent, original_session)
            if self._route_command is None or not ordinary_route(self._route_command.opcode):
                raise BattleJournalError("battle_recovery_required", "ordinary execution evidence has no valid route command")
            if value["state"] == "closed":
                _release(self._route_command, self._route_response, self.intent)
        if path_present(self.path):
            value = _read(self.path)
            bound, renewed = _validate_record(value, self.intent)
            self.binding = bound
            self._validate_session(renewed)
            self.renewed_session = renewed
            self._route_id = value["route_id"]
            for name in ("route_command", "route_response", "release_command", "release_response"):
                encoded = value[name + "_b64"]
                setattr(self, "_" + name, None if encoded is None else decode_control(encoded, response=name.endswith("response")))
            # A persisted pending renewal is also a lease fence, even if its
            # native acknowledgement was lost before publication.
        if type(self._route_id) is not int or not 0 <= self._route_id <= 0x7FFFFFFF:
            raise BattleJournalError("battle_recovery_required", "retained route dispatch is malformed")
        if (self._route_id == 0) != (self._route_command is None):
            raise BattleJournalError("battle_recovery_required", "retained route command is missing")
        if self._route_command is not None:
            if (self._route_command.battle_id, self._route_command.incarnation, self._route_command.phase) != (
                    self.intent.battle_id, self.intent.incarnation, self.intent.bind.phase):
                raise BattleJournalError("battle_recovery_required", "retained route command names another core")
            if self._route_response is not None:
                self._route_response.validate_response(self._route_command)
                if self._route_command.opcode == Opcode.RELEASE and not self._route_response.status:
                    self._release_command, self._release_response = self._route_command, self._route_response
        if self._release_command is not None or self._release_response is not None:
            _release(self._release_command, self._release_response, self.intent)

    async def _canonical(self):
        downloaded = await CheckpointClient(self.companion).download()
        self._retained()
        if downloaded is None or self._session() != self.renewed_session:
            raise BattleJournalError("battle_recovery_required", "canonical recovery session changed")
        meta, i = downloaded.metadata, self.intent
        if (meta["revision"], meta["sha256"]) != (i.canonical_revision, i.canonical_sha256):
            raise BattleJournalError("canonical_head_mismatch", "battle recovery cannot adopt a different canonical head")
        checkpoint = Checkpoint(i.player_id, meta["revision"], meta["request_id"], downloaded.payload,
            meta["sha256"], meta["build_id"], meta["ruleset_id"], meta["save_profile"])
        self.roster = CanonicalBattler.from_checkpoint(checkpoint, world_id=i.world_id,
            build_id=i.build_id, ruleset_id=i.ruleset_id,
            source_slot=i.admit.source_slot if self._provisional else self.binding.local_slot,
            mode=i.admit.phase if self._provisional else self.binding.mode)

    def _convert_admission(self, admission, receipt, command, original_server_epoch):
        import hashlib
        from .battle_admission_session import original_battle_intent, publish_full_intent, finish_conversion
        full = original_battle_intent(admission, receipt, command, original_server_epoch)
        publish_full_intent(self.journal.directory, admission, full)
        path = self.journal.directory / "native-battle-execution.json"
        value = dict(format="native-battle-client-execution-v1", state="admitting", intent=full.value(),
            dispatch_id=1, command_b64=encode_control(full.bind), response_b64=None)
        if path_present(path):
            previous = _read(path)
            if previous.get("intent") == full.value() and previous != value:
                raise BattleJournalError("battle_recovery_required", "provisional conversion conflicts with executed native history")
            if previous.get("intent") != full.value() and previous.get("state") != "closed":
                raise BattleJournalError("battle_recovery_required", "another unfinished native execution owns conversion")
        _atomic(path, _json_bytes(value))
        finish_conversion(self.journal.directory, admission, full)
        self.intent, self._provisional = full, False
        self.original_binding = self.binding = NativeBinding.unpack(full.bind.data)
        self._route_id, self._route_command, self._route_response = 1, full.bind, None
        self._admission_sha256 = hashlib.sha256(full.bind.pack()).hexdigest()

    async def _bootstrap_admission(self, receipt):
        from .battle_admission_session import admission_fields
        from .battle_recovery_protocol import validate_recovery_view
        admission = self.intent
        while True:
            self._retained()
            if self._session() != self.renewed_session:
                raise ConnectionError("provisional recovery authentication changed")
            fields = dict(battle_id=admission.battle_id, generation=admission.generation,
                incarnation=admission.incarnation, response_stage=None, response_id=0, response_b64=None,
                **admission_fields(admission, receipt))
            view = (await self.companion.battle_challenge_rpc("resume", **fields))["result"]
            validate_recovery_view(view, request={**fields, "session_epoch": self.renewed_session.lease_epoch})
            self._retained()
            if self._session() != self.renewed_session:
                raise ConnectionError("provisional recovery lost authenticated admission")
            if view["state"] == "waiting":
                await asyncio.sleep(.05)
                continue
            if view["state"] != "admitting" or view["stage"] != "admission":
                raise BattleJournalError("battle_recovery_required", "provisional recovery cannot invent native execution")
            descriptor = view["admission"]
            self._convert_admission(admission, receipt, decode_control(descriptor["bind_b64"]),
                descriptor["original_server_epoch"])
            return

    def _validate_command(self, stage, command, dispatch):
        i = self.intent
        command.validate_command(player_id=i.player_id)
        if (command.battle_id, command.incarnation, command.session_epoch, command.phase) != (
                i.battle_id, i.incarnation, self.renewed_session.lease_epoch, i.bind.phase):
            raise BattleJournalError("battle_recovery_required", "host control changed the retained authenticated core")
        if stage == "recovery":
            if command.opcode not in {Opcode.QUERY, Opcode.SUSPEND, Opcode.REAUTHORIZE, Opcode.RESUME, Opcode.BIND}:
                raise BattleJournalError("battle_order", "recovery cannot invent ordinary battle execution")
            if command.opcode == Opcode.REAUTHORIZE:
                renewal = ResumeAuthorization.unpack(command.data)
                renewal.validate_previous(self.binding)
                if not isinstance(self._observation, ResumeQuery) or renewal.last_sequence != self._observation.query.last_sequence:
                    raise BattleJournalError("battle_order", "renewal lacks the exact retained native sequence observation")
                self.binding = renewal.binding
            elif command.opcode == Opcode.RESUME:
                if self._authorization is None or command.data != self._authorization.token + self._authorization.epoch.to_bytes(4, "little"):
                    raise BattleJournalError("battle_order", "resume lacks this attempt's exact native reauthorization")
            elif command.opcode == Opcode.BIND:
                bound = NativeBinding.unpack(command.data)
                _same_roster(bound, self.binding)
                query = self._observation
                # ADMIT deliberately holds the original generation before its
                # first BIND. That exact provisional receipt proves the BIND
                # is still unexecuted; an ordinary held battle does not.
                unexecuted = isinstance(query, NativeQuery) and (
                    (query.provisional and (query.generation, query.player_count, query.local_slot, query.mode) ==
                        (i.generation, len(bound.players), bound.local_slot, bound.mode))
                    or (not query.held and query.generation != i.generation))
                if (not unexecuted
                        or query.last_sequence + 1 != i.bind.sequence
                        or command != replace(i.bind, session_epoch=command.session_epoch, data=bound.pack())):
                    raise BattleJournalError("battle_order", "replacement BIND lacks proof the original was never executed")
                self.binding = bound
            if command.source_slot != self.binding.local_slot:
                raise BattleJournalError("battle_order", "recovery control changed the local participant")
        else:
            if not ordinary_route(command.opcode):
                raise BattleJournalError("battle_order", "ordinary route cannot carry recovery controls")
            if dispatch == self._route_id:
                previous = self._route_command
                expected = None if previous is None else replace(previous, session_epoch=command.session_epoch)
                if previous is not None and previous.opcode == Opcode.BIND:
                    expected = replace(expected, data=self.binding.pack())
                if command != expected:
                    raise BattleJournalError("battle_order", "uncertain route replay changed its exact control")
            elif dispatch != self._route_id + 1:
                raise BattleJournalError("battle_order", "ordinary route skipped a durable dispatch")
            if command.opcode == Opcode.BIND:
                bound = NativeBinding.unpack(command.data)
                if bound != self.binding or command.sequence != i.bind.sequence:
                    raise BattleJournalError("battle_order", "ordinary route changed its original BIND")
            else:
                command.validate_command(binding=self.binding, player_id=i.player_id)
            if command.opcode == Opcode.PREPARE:
                preparation = Preparation.unpack(command.data)
                # Only a co-op Gym binding carries a Gym index, and only a PvP binding a rival checkpoint word (both fixed at consent).
                gym = preparation.gym if self.binding is not None and (self.binding.mode == COOP_PHASE
                                                                       or valid_preparation_word(preparation.gym)) else 0
                if preparation != self.roster.adopting(preparation).preparation(preparation.rng, gym):
                    raise BattleJournalError("canonical_head_mismatch", "resumed native preparation changed the canonical party")

    async def _terminal(self, view):
        self._retained()
        if self._session() != self.renewed_session:
            raise BattleJournalError("battle_recovery_required", "terminal battle authentication changed")
        if view.get("stage") == "terminal":
            terminal = view["terminal"]
            command = decode_control(terminal["release_b64"])
            response = decode_control(terminal["receipt_b64"], response=True)
            local = self._release_command or self._route_command
            if (local is None or local.opcode != Opcode.RELEASE
                    or replace(command, session_epoch=local.session_epoch) != local):
                raise BattleJournalError("battle_recovery_required", "host closure differs from the original local RELEASE intent")
            if self._release_response is not None and replace(response,
                    session_epoch=self._release_response.session_epoch) != self._release_response:
                raise BattleJournalError("battle_recovery_required", "host closure changed the retained local RELEASE receipt")
            # The host's immutable global terminal digest reconciles an
            # uncertain local reply. Native RETIRE still has to prove that this
            # exact original core successfully executed the RELEASE tuple.
            self._release_command, self._release_response = command, response
        _release(self._release_command, self._release_response, self.intent)
        from .battle_terminal import retire_battle
        self.renewed_session = await retire_battle(self, view, self._release_command, self._release_response)
        # A globally closed battle needs no renewed peer claims. Native RETIRE
        # authenticates just this original core's local lease and release tuple.
        leases = tuple(self.renewed_session.lease_epoch if slot == self.binding.local_slot else lease
            for slot, lease in enumerate(self.binding.leases))
        self.binding = replace(self.binding, leases=leases)
        self._persist("closed")
        receipt = self.journal.directory / (self.intent.battle_id + ".battle-recovery-complete.json")
        raw = self.path.read_bytes()
        if path_present(receipt):
            if receipt.read_bytes() != raw:
                previous = _read(receipt)
                _, prior_session = _validate_record(previous, self.intent)
                if (self.renewed_session.lease_epoch <= prior_session.lease_epoch
                        or self.renewed_session.server_epoch < prior_session.server_epoch):
                    raise BattleJournalError("battle_recovery_required", "terminal recovery receipt already differs")
                archive = self.journal.directory / (self.intent.battle_id + ".battle-recovery-complete."
                    + str(prior_session.server_epoch) + "." + str(prior_session.lease_epoch) + ".json")
                if path_present(archive) and archive.read_bytes() != _json_bytes(previous):
                    raise BattleJournalError("battle_recovery_required", "archived terminal recovery receipt differs")
                _atomic(archive, _json_bytes(previous))
                _atomic(receipt, raw)
        else:
            _atomic(receipt, raw)
        if path_present(self.journal.path):
            if read_battle_intent(self.journal.path) != self.intent:
                raise BattleJournalError("battle_recovery_required", "original intent changed before terminal publication")
            self.journal.path.unlink()
            _sync_directory(self.journal.directory)
        return BattleCompletion(self.intent.battle_id, self.intent.generation,
            self.intent.canonical_revision, self.intent.canonical_sha256, renewed_session=self.renewed_session)

    async def run(self):
        c = self.companion
        receipt = self.journal.directory / (self.intent.battle_id + ".battle-recovery-complete.json")
        if path_present(receipt):
            # An unchanged authenticated terminal retry is read-only. A new
            # connection reconfirms global closure and retires only this core.
            self._retained(intent_required=path_present(self.journal.path))
            record = self._terminal_evidence()
            completion = BattleCompletion(self.intent.battle_id, self.intent.generation,
                self.intent.canonical_revision, self.intent.canonical_sha256,
                renewed_session=RenewedBattleSession(**record["renewed_session"]))
            if c.connected and self._session() == completion.renewed_session:
                verify_recovery_completion(c, self.journal.directory, completion, self.intent, self.bridge, _pending_allowed=True)
                if path_present(self.journal.path):
                    self.journal.path.unlink()
                    _sync_directory(self.journal.directory)
                verify_recovery_completion(c, self.journal.directory, completion, self.intent, self.bridge)
                return completion
        self._retained()
        controller = getattr(c, "_emergency_controller", None)
        if controller is not None:
            await controller.drain()
        async with c.live_checkpoint_lock:
            if self._active or getattr(c, "_live_save_owner", None) is not None or getattr(c, "_live_battle_owner", None) is not None:
                raise BattleJournalError("character_busy", "another lifecycle owns this retained core")
            if self.original_admission is not None and not self._provisional and path_present(self.admission_path):
                from .battle_admission_session import read_admission_receipt
                self._convert_admission(self.original_admission,
                    read_admission_receipt(self.journal.directory, self.original_admission), self.intent.bind, self.intent.server_epoch)
            self._load()
            self._owner = asyncio.current_task()
            self._active = True
            c._live_save_owner = c._live_battle_owner = self._owner
            c._live_battle_executor = self
            from .battle_observer import BattleObserver
            observer = None
            try:
                while True:
                    self._retained()
                    try:
                        provisional_receipt = None
                        if self._provisional:
                            from .battle_admission_session import hold_admission
                            provisional_receipt = await hold_admission(c, self.journal.directory, self.intent, self.bridge)
                        await c.reconnect_retained_battle(self)
                        self.renewed_session = self._session()
                        if self._provisional:
                            await self._canonical()
                            await self._bootstrap_admission(provisional_receipt)
                            continue
                        self._stage, self._dispatch_id = "recovery", 0
                        self._command = self._response = self._observation = self._authorization = None
                        self._persist()
                        await self._canonical()
                        while True:
                            from .battle_recovery_protocol import validate_recovery_view
                            self._retained()
                            if self._session() != self.renewed_session:
                                raise ConnectionError("battle recovery session changed")
                            fields = dict(battle_id=self.intent.battle_id, generation=self.intent.generation,
                                incarnation=self.intent.incarnation,
                                response_stage=self._stage if self._response is not None else None,
                                response_id=self._dispatch_id if self._response is not None else 0,
                                response_b64=None if self._response is None else encode_control(self._response))
                            if self._admission_sha256 is not None:
                                fields["admission_sha256"] = self._admission_sha256
                            view = (await c.battle_challenge_rpc("resume", **fields))["result"]
                            validate_recovery_view(view, request={**fields, "session_epoch": self.renewed_session.lease_epoch})
                            if self._session() != self.renewed_session:
                                raise ConnectionError("battle recovery session changed")
                            if view["state"] == "closed":
                                return await self._terminal(view)
                            if view["state"] == "recovery_required":
                                raise BattleJournalError("battle_recovery_required", "retain all original battle cores for recovery")
                            if view["command_b64"] is None:
                                await asyncio.sleep(.05)
                                continue
                            stage, dispatch = view["stage"], view["command_id"]
                            command = decode_control(view["command_b64"])
                            if stage == self._stage and dispatch == self._dispatch_id:
                                if command != self._command or self._response is None:
                                    raise BattleJournalError("battle_order", "host retry changed its exact recovery dispatch")
                                continue
                            if stage == "recovery" and (self._stage != "recovery" or (self._dispatch_id and dispatch != self._dispatch_id + 1)):
                                raise BattleJournalError("battle_order", "recovery dispatch skipped or moved backwards")
                            self._validate_command(stage, command, dispatch)
                            self._stage, self._dispatch_id = stage, dispatch
                            self._command, self._response = command, None
                            if stage == "route":
                                self._route_id, self._route_command, self._route_response = dispatch, command, None
                            if (stage == "route" and observer is None and self.binding is not None
                                    and BattleObserver.enabled(c)):
                                # KNOWN_ISSUES MS-62: the recovered route is the observed one too.
                                observer = BattleObserver(c, self.intent.battle_id, self.intent.generation,
                                    self.intent.incarnation, self.binding.local_slot, self.binding.mode)
                            if observer is not None:
                                observer.holding(command)
                            self._persist()
                            from .battle_session import execute_command
                            response = await execute_command(c, command, observer)
                            self._response = response
                            if observer is not None:
                                observer.executed(command, response)
                            if stage == "route":
                                self._route_response = response
                            if not response.status:
                                if stage == "recovery" and command.opcode == Opcode.QUERY:
                                    self._observation = NativeQuery.unpack(response.data)
                                elif stage == "recovery" and command.opcode in {Opcode.SUSPEND, Opcode.REAUTHORIZE}:
                                    self._observation = ResumeQuery.unpack(response.data)
                                    if command.opcode == Opcode.REAUTHORIZE:
                                        self._authorization = ResumeAuthorization.unpack(command.data)
                                if command.opcode == Opcode.RELEASE:
                                    self._release_command, self._release_response = command, response
                            self._persist()
                    except (ConnectionError, OSError, asyncio.TimeoutError):
                        if c.connected:
                            raise  # A native/disk uncertainty is not permission to reconnect.
                        await asyncio.sleep(max(.25, c.config.reconnect_delay))
            finally:
                if observer is not None:
                    await observer.stop()
                self._active = False
                c._live_save_owner = c._live_battle_owner = None
                if getattr(c, "_live_battle_executor", None) is self:
                    c._live_battle_executor = None
                if getattr(c, "_battle_recovery_authority", None) is self:
                    c._battle_recovery_authority = None
