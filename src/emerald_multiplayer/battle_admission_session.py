"""Exact original-core provisional hold before any host execution readiness."""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from .battle_admission_intent import FILENAME, read_admission_intent
from .battle_execution_protocol import decode_control, encode_control
from .battle_journal import BattleIntent, BattleJournalError, path_present, read_battle_intent
from .battle_terminal import _read
from .live_checkpoint import _atomic, _json_bytes, _sync_directory
from .native_battle import NativeBinding, NativeQuery, Opcode

FORMAT = "native-battle-admission-receipt-v1"

# Host replies that prove an Enter claim was never recorded: BattleAdmissionHost.claim and BattleDesk._get refuse before
# anything is written. Such an Enter needs no ADMIT; its provisional intent is retired and the window released.
DEFINITE_CLAIM_REFUSALS = frozenset({"battle_not_ready", "battle_missing", "battle_not_participant",
                                     "battle_generation_mismatch", "stale_lease", "battle_resume_disabled"})


class BattleAdmissionRefused(BattleJournalError):
    """Enter refused before any ADMIT: no native hold exists or will exist for it, and no host claim was recorded.

    The latched native window may be released (menu screen flags 3) with the reason; nothing needs recovery. The owner's
    report of 2026-10-20: every such refusal used to leave both games on "Waiting for server..." for good."""


def refused_admission_path(directory, battle_id):
    return Path(directory) / (battle_id + ".refused-admission-intent.json")


def retire_refused_admission(directory, intent):
    """Keep a refused Enter's provisional intent as a record, never as a pending admission: no ADMIT was sent for it
    (its receipt record does not exist) and the host refused its claim before recording it."""
    directory = Path(directory)
    pending, receipt = directory / FILENAME, directory / (intent.battle_id + ".battle-admission-receipt.json")
    if path_present(receipt) or read_admission_intent(pending) != intent:
        raise BattleJournalError("battle_recovery_required", "a refused Enter must still be the exact unadmitted intent")
    _atomic(refused_admission_path(directory, intent.battle_id), pending.read_bytes())
    pending.unlink()
    _sync_directory(directory)


def check_battle_admission(c, directory, challenge, original_session, retained_bridge):
    """Every check of publish_battle_admission, writing nothing: what can refuse an Enter before it is durable."""
    _admission_intent(c, directory, challenge, original_session, retained_bridge)


def publish_battle_admission(c, directory, challenge, original_session, retained_bridge):
    """Synchronous Enter-event stage using already authenticated immutable pins.

    No network request or Flash download precedes the durable record. A native
    Enter latch still owns the field until the later exact ADMIT transfer.
    """
    from .battle_admission_intent import publish_admission_intent
    intent, journal = _admission_intent(c, directory, challenge, original_session, retained_bridge)
    publish_admission_intent(journal.directory / FILENAME, intent)
    return intent


def _admission_intent(c, directory, challenge, original_session, retained_bridge):
    from .battle_admission_intent import BattleAdmissionIntent
    from .battle_journal import BattleJournal
    from .battle_session import RenewedBattleSession
    from .battle_protocol import _view
    from .native_battle import NativeControl
    from .native_battle_resume import Admission
    s = original_session
    owner = c._live_save_owner
    # The native Enter latch can beat BEGIN's response through separate IPC.
    # Publishing only the already-authenticated choice is safe while that exact
    # lost controller drains; ADMIT itself still waits for its lifecycle lock.
    from .emergency_save import EmergencySaveController
    saver = getattr(c, "_emergency_controller", None)
    draining_original = (type(s) is RenewedBattleSession and type(saver) is EmergencySaveController
        and saver.companion is c and saver.task is owner and owner is not None and not owner.done()
        and not c.connected and c._reconnect_blocked
        and saver.bridge is retained_bridge and saver.session == (s.world_id, s.lease_epoch, s.incarnation)
        and saver.active_export is None and saver.lost.is_set() and saver.result.state == "preserving"
        and saver.identity == dict(world_id=s.world_id, player_id=s.player_id, build_id=s.build_id,
                                   ruleset_id=s.ruleset_id, save_profile=s.save_profile))
    if (type(s) is not RenewedBattleSession or c._bridge is not retained_bridge or retained_bridge is None
            or not retained_bridge.battle_capable or c.battle_incarnation != s.incarnation
            or getattr(c, "_live_battle_runtime_id", None) != s.runtime_id
            or (c.config.player_id, c.config.build_id, c.config.ruleset_id) != (s.player_id, s.build_id, s.ruleset_id)
            or getattr(c.config, "battle_resume_abi_version", 0) != 1 or c.config.battle_abi_version != 3
            or not c.config.development_battle_channel or not c.config.ownership_enabled
            or type(c.config.server_credential) is not bytes or len(c.config.server_credential) != 32
            or getattr(c, "_live_binding", None) != (s.world_id, s.lease_epoch, s.incarnation)
            or owner not in (None, asyncio.current_task()) and not draining_original):
        raise BattleJournalError("battle_admission_required", "Enter requires its captured original authenticated native core")
    if c.connected:
        if (c.world_id, c.server_epoch, c.session_epoch, c.save_profile) != (s.world_id, s.server_epoch, s.lease_epoch, s.save_profile):
            raise BattleJournalError("battle_recovery_required", "Enter cannot adopt replacement authentication")
    elif not c._reconnect_blocked:
        raise BattleJournalError("battle_recovery_required", "disconnected Enter requires the retained original reconnect fence")
    _view(challenge, s.player_id)
    slot = challenge["players"].index(s.player_id)
    cp = challenge["checkpoints"][slot]
    command = NativeControl(s.incarnation, s.lease_epoch, challenge["battle_id"], 1, Opcode.ADMIT,
        phase=challenge["mode"], source_slot=slot, data=Admission(challenge["generation"], s.player_id, s.runtime_id).pack())
    intent = BattleAdmissionIntent(s.world_id, s.player_id, s.build_id, s.ruleset_id, s.save_profile,
        s.server_epoch, s.lease_epoch, s.incarnation, s.runtime_id, cp["revision"], cp["sha256"], _json_bytes(challenge), command)
    journal = BattleJournal(c, directory)
    if path_present(journal.path):
        raise BattleJournalError("character_busy", "a full native battle already owns this core")
    journal._other_recovery()
    return intent, journal


async def prepare_battle_admission(c, directory, challenge):
    """Transfer the still-held native Players menu into an exact battle hold."""
    from .battle_journal import BattleJournal
    journal = BattleJournal(c, directory)
    bridge = c._bridge
    from .battle_terminal import authenticated_session
    from .battle_session import RenewedBattleSession
    path = journal.directory / FILENAME
    if not path_present(path):
        publish_battle_admission(c, journal.directory, challenge, authenticated_session(c), bridge)
    intent = read_admission_intent(path)
    if intent.challenge != challenge:
        raise BattleJournalError("battle_recovery_required", "another provisional challenge owns the retained core")
    original = RenewedBattleSession(**{key: getattr(intent, key) for key in
        ("world_id", "player_id", "build_id", "ruleset_id", "save_profile", "server_epoch", "lease_epoch", "incarnation", "runtime_id")})
    publish_battle_admission(c, journal.directory, challenge, original, bridge)
    async with c.live_checkpoint_lock:
        if c._live_save_owner is not None or getattr(c, "_live_battle_owner", None) is not None or path_present(journal.path):
            raise BattleJournalError("character_busy", "another character lifecycle owns battle admission")
        journal._other_recovery()
        if (getattr(c, "_live_binding", None) != (intent.world_id, intent.lease_epoch, intent.incarnation)
                or path_present(journal.directory / "pending-emergency.json")):
            raise BattleJournalError("battle_admission_required", "battle admission needs its original native save binding")
        c._live_save_owner = c._live_battle_owner = asyncio.current_task()
        try:
            if not path_present(path) or read_admission_intent(path) != intent:
                raise BattleJournalError("battle_recovery_required", "provisional Enter intent disappeared before preparation")
            if c.connected:
                from .companion import BattleChallengeError
                try:
                    claimed = (await c.battle_challenge_rpc("claim", battle_id=intent.battle_id,
                        generation=intent.generation, incarnation=intent.incarnation, runtime_id=intent.runtime_id))["result"]
                    if claimed != intent.challenge or authenticated_session(c) != original or c._bridge is not bridge:
                        raise BattleJournalError("battle_recovery_required", "Enter claim changed its original accepted challenge")
                except BattleChallengeError as error:
                    if (error.code in DEFINITE_CLAIM_REFUSALS and getattr(c.config, "menu_release_abi_version", 0) == 1
                            and not path_present(journal.directory / (intent.battle_id + ".battle-admission-receipt.json"))):
                        # The host answered, and refused before recording the claim (the challenge expired, was
                        # cancelled or changed): this Enter cannot become a battle, so it never becomes a hold.
                        retire_refused_admission(journal.directory, intent)
                        raise BattleAdmissionRefused(error.code, str(error)) from error
                    await hold_admission(c, journal.directory, intent, bridge)
                    raise
                except (Exception, asyncio.CancelledError):
                    # Exact native ADMIT proves the already-selected Enter if
                    # its host claim reply was lost. It grants no battle start.
                    await hold_admission(c, journal.directory, intent, bridge)
                    raise
            # Canonical bytes are checked by the executor before readiness or
            # PREPARE. Admission needs only the authenticated accepted pins, so
            # a failed network download cannot strand the native menu latch.
            await hold_admission(c, journal.directory, intent, bridge)
            return intent
        finally:
            c._live_save_owner = c._live_battle_owner = None


def _validate_receipt(value, intent):
    if (type(value) is not dict or set(value) != {"format", "intent", "command_b64", "response_b64"}
            or value["format"] != FORMAT or value["intent"] != intent.value()
            or value["command_b64"] != encode_control(intent.admit)):
        raise BattleJournalError("battle_recovery_required", "provisional hold evidence changed its original intent")
    if value["response_b64"] is None:
        return None
    response = decode_control(value["response_b64"], response=True)
    response.validate_response(intent.admit)
    query = NativeQuery.unpack(response.data)
    challenge = intent.challenge
    if (response.status or not query.provisional or
            (query.generation, query.player_count, query.local_slot, query.mode) !=
            (intent.generation, len(challenge["players"]), intent.admit.source_slot, intent.admit.phase)):
        raise BattleJournalError("battle_recovery_required", "native ADMIT did not preserve the original provisional hold")
    return response


def read_admission_receipt(directory, intent):
    path = Path(directory) / (intent.battle_id + ".battle-admission-receipt.json")
    response = _validate_receipt(_read(path), intent)
    if response is None:
        raise BattleJournalError("battle_recovery_required", "provisional native hold has no exact receipt")
    return response


class AdmissionHoldAuthority:
    """One persisted ADMIT, under the original idle save binding, even offline."""
    def __init__(self, companion, directory, intent, bridge):
        self.companion, self.directory, self.intent, self.bridge = companion, Path(directory), intent, bridge
        self.owner = asyncio.current_task()
        self.path = self.directory / (intent.battle_id + ".battle-admission-receipt.json")
        self.record = dict(format=FORMAT, intent=intent.value(), command_b64=encode_control(intent.admit), response_b64=None)

    def _retained(self):
        c, i = self.companion, self.intent
        if (self.bridge is None or c._bridge is not self.bridge or not self.bridge.battle_capable
                or c.battle_incarnation != i.incarnation or c._live_battle_runtime_id != i.runtime_id
                or (c.config.player_id, c.config.build_id, c.config.ruleset_id) != (i.player_id, i.build_id, i.ruleset_id)
                or getattr(c.config, "battle_resume_abi_version", 0) != 1
                or getattr(c, "_live_binding", None) != (i.world_id, i.lease_epoch, i.incarnation)
                or read_admission_intent(self.directory / FILENAME) != i):
            raise BattleJournalError("battle_recovery_required", "provisional hold lost its exact original bound core")

    def _authorizes(self, command):
        c, i = self.companion, self.intent
        try:
            self._retained()
            session_valid = ((c.world_id, c.server_epoch, c.session_epoch, c.save_profile) ==
                (i.world_id, i.server_epoch, i.lease_epoch, i.save_profile)) if c.connected else c._reconnect_blocked
            return (session_valid and asyncio.current_task() is self.owner
                and c._live_save_owner is self.owner and c._live_battle_owner is self.owner
                and c._live_battle_executor is self and command == i.admit
                and self.record["response_b64"] is None and _read(self.path) == self.record)
        except (ValueError, OSError, ConnectionError):
            return False


async def hold_admission(c, directory, intent, bridge):
    """Caller owns the checkpoint lock; no readiness is sent until this returns."""
    owner = asyncio.current_task()
    if c._live_save_owner is not owner or getattr(c, "_live_battle_owner", None) not in (None, owner):
        raise BattleJournalError("character_busy", "provisional hold requires the original lifecycle lock")
    authority = AdmissionHoldAuthority(c, directory, intent, bridge)
    authority._retained()
    if path_present(authority.path):
        value = _read(authority.path)
        receipt = _validate_receipt(value, intent)
        if receipt is not None:
            return receipt
    _atomic(authority.path, _json_bytes(authority.record))
    prior_owner = getattr(c, "_live_battle_owner", None)
    prior_executor = getattr(c, "_live_battle_executor", None)
    c._live_battle_owner, c._live_battle_executor = owner, authority
    try:
        response = await c.battle_rpc(intent.admit)
        response.validate_response(intent.admit)
        authority.record["response_b64"] = encode_control(response)
        _atomic(authority.path, _json_bytes(authority.record))
        _validate_receipt(authority.record, intent)
        authority._retained()
        return response
    finally:
        c._live_battle_owner, c._live_battle_executor = prior_owner, prior_executor


def admission_fields(intent, receipt):
    _validate_receipt(dict(format=FORMAT, intent=intent.value(), command_b64=encode_control(intent.admit),
        response_b64=encode_control(receipt)), intent)
    return dict(runtime_id=intent.runtime_id, admission_b64=encode_control(intent.admit),
        admission_receipt_b64=encode_control(receipt))


def original_battle_intent(admission, receipt, command, original_server_epoch):
    """Only the host's exact original BIND may replace provisional metadata."""
    query = NativeQuery.unpack(receipt.data)
    challenge = admission.challenge
    bound = NativeBinding.unpack(command.data)
    if (command.opcode != Opcode.BIND or not bound.resumable or original_server_epoch != admission.server_epoch
            or command.sequence != query.last_sequence + 1
            or (bound.generation, bound.players, bound.local_slot, bound.mode) !=
               (admission.generation, tuple(challenge["players"]), admission.admit.source_slot, admission.admit.phase)
            or (command.battle_id, command.incarnation, command.session_epoch) !=
               (admission.battle_id, admission.incarnation, admission.lease_epoch)):
        raise BattleJournalError("battle_recovery_required", "full BIND differs from the consented original provisional core")
    value = dict(schema=1, **{key: getattr(admission, key) for key in
        ("world_id", "player_id", "build_id", "ruleset_id", "save_profile", "server_epoch", "lease_epoch",
         "incarnation", "runtime_id", "canonical_revision", "canonical_sha256")},
        battle_id=admission.battle_id, generation=admission.generation, bind_b64=encode_control(command))
    return BattleIntent.from_value(value)


def publish_full_intent(directory, admission, intent):
    """Preserve both identities until the full original BIND is durable."""
    from .battle_journal import FORMAT as BATTLE_FORMAT
    from .battle_admission_intent import read_admission_intent
    import os
    from contextlib import suppress
    from uuid import uuid4
    directory = Path(directory)
    if read_admission_intent(directory / FILENAME) != admission:
        raise BattleJournalError("battle_recovery_required", "original provisional intent changed before conversion")
    path = directory / "pending-battle.json"
    value = intent.value()
    raw = _json_bytes(dict(format=BATTLE_FORMAT, intent=value, sha256=hashlib.sha256(_json_bytes(value)).hexdigest()))
    if path_present(path):
        if read_battle_intent(path) != intent:
            raise BattleJournalError("battle_recovery_required", "another full battle intent owns the core")
        _sync_directory(directory)
        return
    stage = directory / (str(uuid4()) + ".battle-conversion.stage")
    try:
        _atomic(stage, raw)
        try:
            os.link(stage, path)
        except FileExistsError:
            if read_battle_intent(path) != intent:
                raise BattleJournalError("battle_recovery_required", "another full battle won admission")
        _sync_directory(directory)
    finally:
        with suppress(FileNotFoundError):
            stage.unlink()


def finish_conversion(directory, admission, intent):
    directory = Path(directory)
    if read_battle_intent(directory / "pending-battle.json") != intent:
        raise BattleJournalError("battle_recovery_required", "full BIND disappeared before provisional retirement")
    path = directory / FILENAME
    if path_present(path):
        if read_admission_intent(path) != admission:
            raise BattleJournalError("battle_recovery_required", "another provisional intent appeared during conversion")
        archive = directory / (admission.battle_id + ".battle-admission-intent.json")
        if path_present(archive) and archive.read_bytes() != path.read_bytes():
            raise BattleJournalError("battle_recovery_required", "archived provisional intent differs")
        _atomic(archive, path.read_bytes())
        path.unlink()
        _sync_directory(directory)


def verify_admission_conversion(directory, admission, intent):
    directory = Path(directory)
    archived = read_admission_intent(directory / (admission.battle_id + ".battle-admission-intent.json"))
    if archived != admission:
        raise BattleJournalError("battle_recovery_required", "provisional conversion lost its original immutable intent")
    receipt = read_admission_receipt(directory, admission)
    if original_battle_intent(admission, receipt, intent.bind, intent.server_epoch) != intent:
        raise BattleJournalError("battle_recovery_required", "full original BIND differs from its native provisional receipt")
    return intent
