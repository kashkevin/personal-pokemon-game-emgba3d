"""Durable development trade orchestration for the same running ROM.

Only the allocated ROM mailbox changes Flash. This module never edits a live
save, resumes on a timeout, or confirms for the peer. A replaced companion or
IPC incarnation requires the future paused-start recovery gate. Native trade
effects and player UI remain separate acceptance work.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import re
import struct
from uuid import UUID, uuid4
import zlib

from .checkpoint_client import validate_metadata
from .flash import FLASH_SIZE, inspect_flash
from .live_checkpoint import LiveCheckpointCoordinator, LiveSaveError, _atomic, _json_bytes, _sync_directory
from .live_receipt import record_live_apply, read_live_receipt
from .ownership import OWNERSHIP_PROFILE, inspect_ownership
from .protocol import MAX_COUNTER
from .save_mailbox import Opcode, SaveControl, State, TradeHold, SAVE_CHUNK_SIZE


class LiveTradeError(LiveSaveError):
    pass


_FORMAT = "emerald-live-trade-v1"
_LIMIT = 16_384
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_PHASES = {"intent", "starting", "frozen", "prepared", "committed", "applied", "acknowledged", "releasing", "aborting"}
_FIELDS = {"schema", "world_id", "player_id", "build_id", "ruleset_id", "save_profile",
    "transaction_id", "generation", "prepare_id", "expected_revision", "incarnation", "runtime_id",
    "phase", "frozen_sha256", "prepared", "fate", "canonical", "receipt_id", "applied_sha256",
    "control", "export_ended"}


def _uuid(value):
    return isinstance(value, str) and str(UUID(value)) == value and UUID(value).int != 0


def _digest(value):
    return isinstance(value, str) and _SHA.fullmatch(value) is not None


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate journal field")
        result[key] = value
    return result


class LiveTradeCoordinator(LiveCheckpointCoordinator):
    """Prepare, offer and confirm this actor; explicitly reconcile durable fate.

    The proposal is opened separately with authenticated ``trade_rpc('open')``.
    Its generation and the locally verified base revision are required inputs.
    ``confirm`` records consent only; ``resume`` applies a committed result or
    safely aborts an authoritatively absent proposal. Call ``keepalive`` while a
    confirmation UI waits. All exceptions retain the journal and ROM hold.
    """

    def __init__(self, companion, directory: Path):
        super().__init__(companion, directory)
        self.trade_path = self.directory / "pending-trade.json"
        previous = getattr(companion, "_live_trade_pending_path", None)
        if previous is not None and Path(previous) != self.trade_path and Path(previous).exists():
            raise LiveTradeError("pending_trade", "another private directory owns this character's pending trade")
        companion._live_trade_pending_path = self.trade_path
        if getattr(companion, "_live_trade_runtime_id", None) is None:
            companion._live_trade_runtime_id = str(uuid4())

    def _session(self):
        c = self.companion
        if not getattr(c.config, "trade_enabled", False):
            raise LiveTradeError("trade_unavailable", "live trading requires the verified ownership trade build")
        session = super()._session()
        if c.save_profile != OWNERSHIP_PROFILE:
            raise LiveTradeError("trade_unavailable", "live trading requires the verified ownership trade build")
        return session

    def _same_session(self, expected):
        current = self._session()
        if current[0] != expected[0] or current[2] != expected[2]:
            raise LiveTradeError("recovery_required", "the world or game incarnation changed; retain trade intent for canonical recovery")
        if current[1] != expected[1]:
            raise ConnectionError("the authenticated trade lease changed; resume against its authoritative fate")

    def _check_running(self, intent, session):
        if (intent["incarnation"] != session[2]
                or intent["runtime_id"] != self.companion._live_trade_runtime_id):
            raise LiveTradeError("recovery_required", "the game or companion was replaced; retain trade intent for paused-start canonical recovery")

    def _validate_intent(self, intent):
        try:
            c = self.companion
            if not isinstance(intent, dict) or set(intent) != _FIELDS or type(intent["schema"]) is not int or intent["schema"] != 1:
                raise ValueError()
            for field in ("world_id", "player_id", "transaction_id", "generation", "prepare_id", "runtime_id"):
                if not _uuid(intent[field]):
                    raise ValueError()
            if intent["transaction_id"] == intent["prepare_id"]:
                raise ValueError()
            if (type(intent["expected_revision"]) is not int or not 1 <= intent["expected_revision"] <= MAX_COUNTER-2
                    or type(intent["incarnation"]) is not int or not 1 <= intent["incarnation"] <= 0xFFFFFFFF
                    or intent["phase"] not in _PHASES or type(intent["export_ended"]) is not bool):
                raise ValueError()
            if (intent["player_id"], intent["build_id"], intent["ruleset_id"], intent["save_profile"]) != (
                    c.config.player_id, c.config.build_id, c.config.ruleset_id, OWNERSHIP_PROFILE):
                raise LiveTradeError("journal_identity", "trade intent belongs to another player, build or profile")
            base = intent["expected_revision"]
            if intent["frozen_sha256"] is not None and not _digest(intent["frozen_sha256"]):
                raise ValueError()
            prepared = validate_metadata(intent["prepared"], c.config, OWNERSHIP_PROFILE)
            if prepared is not None and (prepared["request_id"], prepared["revision"], prepared["sha256"], prepared["size"]) != (
                    intent["prepare_id"], base+1, intent["frozen_sha256"], FLASH_SIZE):
                raise ValueError()
            fate = intent["fate"]
            if fate is not None:
                if (not isinstance(fate, dict) or set(fate) != {"transaction_id", "state", "outcome_fingerprint", "revision", "sha256"}
                        or fate["transaction_id"] != intent["transaction_id"] or fate["state"] != "committed"
                        or type(fate["revision"]) is not int or fate["revision"] != base+2
                        or not _digest(fate["sha256"]) or not _digest(fate["outcome_fingerprint"])):
                    raise ValueError()
            canonical = validate_metadata(intent["canonical"], c.config, OWNERSHIP_PROFILE)
            if canonical is not None and (fate is None or (canonical["request_id"], canonical["revision"], canonical["sha256"]) != (
                    intent["transaction_id"], base+2, fate["sha256"])):
                raise ValueError()
            receipt, applied = intent["receipt_id"], intent["applied_sha256"]
            if (receipt is None) != (applied is None) or (receipt is not None and (not _uuid(receipt) or not _digest(applied) or canonical is None)):
                raise ValueError()
            if intent["export_ended"] and prepared is None:
                raise ValueError()
            if intent["phase"] in {"frozen", "prepared", "committed", "applied", "acknowledged", "releasing", "aborting"} and intent["frozen_sha256"] is None:
                raise ValueError()
            if intent["phase"] in {"prepared", "applied", "acknowledged", "releasing", "aborting"} and prepared is None:
                raise ValueError()
            if intent["phase"] in {"committed", "applied", "acknowledged", "releasing"} and fate is None:
                raise ValueError()
            if intent["phase"] in {"applied", "acknowledged", "releasing"} and receipt is None:
                raise ValueError()
            if intent["control"] is not None:
                raw = base64.b64decode(intent["control"], validate=True)
                if base64.b64encode(raw).decode("ascii") != intent["control"]:
                    raise ValueError()
                command = SaveControl.unpack(raw).validate_command()
                if (command.request_id != intent["transaction_id"] or command.incarnation != intent["incarnation"]
                        or command.opcode not in (Opcode.REBIND_TRADE, Opcode.ABORT_TRADE, Opcode.RELEASE_TRADE)
                        or command.revision not in (base+1, base+2)):
                    raise ValueError()
        except LiveTradeError:
            raise
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as error:
            raise LiveTradeError("invalid_journal", "pending trade metadata is malformed or inconsistent") from error
        return intent

    def _save(self, intent):
        self._validate_intent(intent)
        envelope = {"format": _FORMAT, "intent": intent, "sha256": hashlib.sha256(_json_bytes(intent)).hexdigest()}
        raw = _json_bytes(envelope)
        if len(raw) > _LIMIT:
            raise LiveTradeError("invalid_journal", "trade journal exceeds its bounded format")
        _atomic(self.trade_path, raw)

    def _load(self, session):
        if not self.trade_path.exists():
            raise LiveTradeError("trade_missing", "this character has no pending local trade")
        try:
            with self.trade_path.open("rb") as source:
                raw = source.read(_LIMIT+1)
            if len(raw) > _LIMIT:
                raise ValueError()
            envelope = json.loads(raw, object_pairs_hook=_unique,
                parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
            if (not isinstance(envelope, dict) or set(envelope) != {"format", "intent", "sha256"}
                    or envelope["format"] != _FORMAT or not _digest(envelope["sha256"])
                    or hashlib.sha256(_json_bytes(envelope["intent"])).hexdigest() != envelope["sha256"]):
                raise ValueError()
        except (ValueError, UnicodeError, TypeError, RecursionError) as error:
            raise LiveTradeError("invalid_journal", "pending trade journal failed integrity validation") from error
        intent = self._validate_intent(envelope["intent"])
        if intent["world_id"] != session[0]:
            raise LiveTradeError("journal_identity", "trade intent belongs to another world")
        self._check_running(intent, session)
        if intent["frozen_sha256"] is not None:
            self._bytes(intent["prepare_id"] + ".flash", intent["frozen_sha256"], FLASH_SIZE)
        if intent["canonical"] is not None:
            self._bytes(intent["transaction_id"] + ".canonical.flash", intent["canonical"]["sha256"], intent["canonical"]["size"])
        if intent["receipt_id"] is not None:
            applied = self._bytes(intent["receipt_id"] + ".applied.flash", intent["applied_sha256"], FLASH_SIZE)
            receipt = read_live_receipt(self.directory / (intent["receipt_id"] + ".live-apply.json"))
            if (receipt.world_id, receipt.player_id, receipt.revision, receipt.canonical_request_id,
                    receipt.canonical_container_sha256, receipt.actual_rom_flash_sha256, receipt.rom_request_id,
                    receipt.incarnation) != (session[0], intent["player_id"], intent["expected_revision"]+2,
                    intent["transaction_id"], intent["canonical"]["sha256"], intent["applied_sha256"],
                    intent["transaction_id"], intent["incarnation"]):
                raise LiveTradeError("journal_receipt", "trade apply receipt disagrees with the pending result")
            if inspect_flash(applied, save_profile=OWNERSHIP_PROFILE).state_sha256 != receipt.normalized_state_sha256:
                raise LiveTradeError("journal_receipt", "trade readback disagrees with its receipt")
        return intent

    def _bytes(self, filename, sha, size):
        try:
            with (self.directory / filename).open("rb") as source:
                data = source.read(size+1)
        except OSError as error:
            raise LiveTradeError("journal_bytes", "immutable trade bytes are unavailable") from error
        if len(data) != size or hashlib.sha256(data).hexdigest() != sha:
            raise LiveTradeError("journal_bytes", "immutable trade bytes failed integrity verification")
        parsed = inspect_flash(data, save_profile=OWNERSHIP_PROFILE)
        owned = inspect_ownership(parsed)
        if (owned.world_id, owned.player_id) != (self.companion.world_id, self.companion.config.player_id):
            raise LiveTradeError("journal_identity", "stored trade bytes belong to another character")
        return data

    def _immutable(self, filename, data):
        path = self.directory / filename
        if path.exists():
            with path.open("rb") as source:
                existing = source.read(len(data)+1)
            if existing != data:
                raise LiveTradeError("journal_conflict", "an immutable trade artifact already records different bytes")
        else:
            _atomic(path, data)

    async def _rpc(self, session, operation, **fields):
        result = await self.companion.trade_rpc(operation, **fields)
        self._same_session(session)
        return result

    async def _fate(self, intent, session):
        view = (await self._rpc(session, "status", transaction_id=intent["transaction_id"]))["trade"]
        if view["state"] == "committed":
            self._record_fate(intent, view)
        elif intent["fate"] is not None:
            raise LiveTradeError("trade_conflict", "a previously committed trade has no authoritative outcome")
        return view

    def _record_fate(self, intent, view):
        if intent["fate"] is not None and intent["fate"] != view:
            raise LiveTradeError("trade_conflict", "durable trade fate changed")
        intent["fate"] = view
        if intent["phase"] not in {"applied", "acknowledged", "releasing"}:
            intent["phase"] = "committed"
        self._save(intent)

    async def _query(self, intent, session):
        self._check_running(intent, session)
        command = SaveControl(session[2], session[1], intent["transaction_id"], 1, 0, FLASH_SIZE, 0, Opcode.QUERY_TRADE)
        response = await self.companion.save_rpc(command)
        self._same_session(session)
        hold = TradeHold.parse(self._ok(response))
        if hold.incarnation != session[2] or hold.session_epoch > session[1]:
            raise LiveTradeError("recovery_required", "ROM trade binding does not match this running game")
        if hold.active and (hold.transaction_id != intent["transaction_id"]
                or hold.revision not in (intent["expected_revision"]+1, intent["expected_revision"]+2)):
            raise LiveTradeError("recovery_required", "a different trade owns the ROM hold")
        return hold

    async def _held(self, intent, session):
        hold = await self._query(intent, session)
        if not hold.active:
            raise LiveTradeError("recovery_required", "the pending trade lost its ROM hold; retain intent for canonical recovery")
        if hold.phase == State.ERROR:
            raise LiveTradeError("recovery_required", "Flash failed while the trade was held; close-game canonical recovery is required")
        control = None if intent["control"] is None else SaveControl.unpack(base64.b64decode(intent["control"]))
        if hold.session_epoch < session[1]:
            control = SaveControl(session[2], session[1], intent["transaction_id"], 1, 0, FLASH_SIZE, hold.revision, Opcode.REBIND_TRADE)
            intent["control"] = base64.b64encode(control.pack()).decode("ascii")
            self._save(intent)
        elif control is None or control.opcode != Opcode.REBIND_TRADE or control.session_epoch != session[1]:
            control = None
        if control is not None:
            response = await self.companion.save_rpc(control)
            self._same_session(session); self._ok(response)
            self.companion._live_binding, self.companion._live_sequence = session, 1
            intent["control"] = None
            self._save(intent)
        elif getattr(self.companion, "_live_binding", None) != session:
            raise LiveTradeError("recovery_required", "the live command sequence cannot be proved for this ROM binding")
        if hold.expired:
            await self._command(session, intent["transaction_id"], hold.revision, Opcode.KEEP_TRADE)
        return hold

    async def prepare(self, transaction_id: str, generation: str, expected_revision: int):
        """Freeze and durably checkpoint preparation; END retains the trade hold."""
        try:
            valid = _uuid(transaction_id) and _uuid(generation)
        except ValueError:
            valid = False
        if not valid or type(expected_revision) is not int or not 1 <= expected_revision <= MAX_COUNTER-2:
            raise LiveTradeError("invalid_field", "trade preparation requires UUIDs and an explicit revision with two remaining slots")
        async with self._own():
            session = self._session()
            if self.pending_path.exists():
                raise LiveTradeError("pending_export", "resolve the ordinary checkpoint before preparing a trade")
            if self.trade_path.exists():
                intent = self._load(session)
                if (transaction_id, generation, expected_revision) != (intent["transaction_id"], intent["generation"], intent["expected_revision"]):
                    raise LiveTradeError("pending_trade", "resolve the existing trade before preparing another")
                view = await self._fate(intent, session)
                if view["state"] != "offering" or view["generation"] != generation:
                    raise LiveTradeError("trade_changed", "resume the pending trade's authoritative outcome")
            else:
                view = (await self._rpc(session, "status", transaction_id=transaction_id))["trade"]
                if view["state"] != "offering" or view["generation"] != generation or any(
                        offer["player_id"] == self.companion.config.player_id for offer in view["offers"]):
                    raise LiveTradeError("trade_changed", "a current unoffered proposal is required before preparing")
                if (await self._rpc(session, "pending"))["recoveries"]:
                    raise LiveTradeError("recovery_required", "apply the previous canonical trade first")
                head = await self.client.info(); self._same_session(session)
                if head is None or head["revision"] != expected_revision:
                    raise LiveTradeError("revision_conflict", "the locally verified trade base differs from the canonical head")
                intent = dict(schema=1, world_id=session[0], player_id=self.companion.config.player_id,
                    build_id=self.companion.config.build_id, ruleset_id=self.companion.config.ruleset_id,
                    save_profile=OWNERSHIP_PROFILE, transaction_id=transaction_id, generation=generation,
                    prepare_id=str(uuid4()), expected_revision=expected_revision, incarnation=session[2],
                    runtime_id=self.companion._live_trade_runtime_id, phase="intent", frozen_sha256=None,
                    prepared=None, fate=None, canonical=None, receipt_id=None, applied_sha256=None,
                    control=None, export_ended=False)
                self._save(intent)
            return await self._prepare(intent, session)

    async def _prepare(self, intent, session):
        revision = intent["expected_revision"]+1
        # BEGIN is issued only after the durable phase changes to "starting".
        # An intent-only interruption can safely establish/retry its initial
        # binding; the existing exact pending BIND protects a lost ACK.
        if intent["phase"] == "intent":
            await self._bind(session)
        hold = await self._query(intent, session)
        if hold.active:
            hold = await self._held(intent, session)
            if hold.import_started or hold.revision != revision:
                raise LiveTradeError("recovery_required", "a post-trade import cannot return to preparation")
        else:
            if intent["frozen_sha256"] is not None:
                raise LiveTradeError("recovery_required", "a stored frozen preparation lost its ROM hold")
            await self._bind(session)
            await self._prepare_ownership(session, intent["expected_revision"], enroll=False)
        if not intent["export_ended"]:
            if intent["fate"] is None:
                intent["phase"] = "starting" if intent["frozen_sha256"] is None else intent["phase"]
            self._save(intent)
            begin = await self._command(session, intent["transaction_id"], revision, Opcode.BEGIN_TRADE_EXPORT)
            payload = await self._read_flash(session, intent["transaction_id"], revision)
            parsed = inspect_flash(payload, save_profile=OWNERSHIP_PROFILE)
            counter, rotation = struct.unpack_from("<II", begin.data)
            actual_rotation = (-struct.unpack_from("<H", payload, parsed.metadata.bank*14*4096+4084)[0]) % 14
            if (counter, rotation) != (parsed.metadata.counter, actual_rotation):
                raise LiveTradeError("export_metadata", "frozen trade Flash disagrees with its save metadata")
            self._immutable(intent["prepare_id"] + ".flash", payload)
            sha = hashlib.sha256(payload).hexdigest()
            if intent["frozen_sha256"] is not None and intent["frozen_sha256"] != sha:
                raise LiveTradeError("journal_conflict", "restarted export changed the frozen preparation")
            intent["frozen_sha256"] = sha
            if intent["fate"] is None:
                intent["phase"] = "frozen"
            self._save(intent)
        else:
            payload = self._bytes(intent["prepare_id"] + ".flash", intent["frozen_sha256"], FLASH_SIZE)
        metadata = await self.client.upload(payload, intent["expected_revision"], transaction_id=intent["prepare_id"])
        self._same_session(session)
        if intent["prepared"] is not None and intent["prepared"] != metadata:
            raise LiveTradeError("trade_conflict", "preparation retry returned a different immutable checkpoint")
        intent["prepared"] = metadata
        if intent["fate"] is None:
            intent["phase"] = "prepared"
        self._save(intent)
        if not intent["export_ended"]:
            await self._held(intent, session)
            response = await self._command(session, intent["transaction_id"], revision, Opcode.END, offset=FLASH_SIZE)
            self._crc(response, payload)
            intent["export_ended"] = True
            self._save(intent)
        return metadata

    @staticmethod
    def _crc(response, payload):
        if len(response.data) != 4 or struct.unpack("<I", response.data)[0] != zlib.crc32(payload):
            raise LiveTradeError("final_crc", "the ROM did not acknowledge the exact complete trade readback")

    async def status(self):
        async with self._own():
            session = self._session()
            return await self._fate(self._load(session), session)

    async def keepalive(self):
        async with self._own():
            session = self._session(); intent = self._load(session)
            hold = await self._held(intent, session)
            return await self._command(session, intent["transaction_id"], hold.revision, Opcode.KEEP_TRADE)

    async def offer(self, serial: int):
        if type(serial) is not int or not 1 <= serial <= 0xFFFFF:
            raise LiveTradeError("invalid_field", "offered identity must be a nonzero 20-bit serial")
        async with self._own():
            session = self._session(); intent = self._load(session)
            if not intent["export_ended"] or intent["prepared"] is None or intent["fate"] is not None:
                raise LiveTradeError("preparation_required", "durably prepare this character before offering")
            await self._held(intent, session)
            head = await self.client.info(); self._same_session(session)
            if head != intent["prepared"]:
                raise LiveTradeError("revision_conflict", "the canonical preparation changed before offering")
            payload = self._bytes(intent["prepare_id"] + ".flash", intent["frozen_sha256"], FLASH_SIZE)
            if not any(r.serial == serial and r.location.startswith("party:") for r in inspect_ownership(
                    inspect_flash(payload, save_profile=OWNERSHIP_PROFILE)).records):
                raise LiveTradeError("invalid_trade", "the offered identity is not in this frozen party")
            return (await self._rpc(session, "offer", transaction_id=intent["transaction_id"],
                generation=intent["generation"], revision=head["revision"], sha256=head["sha256"], serial=serial))["trade"]

    async def confirm(self, fingerprint: str):
        if not _digest(fingerprint):
            raise LiveTradeError("invalid_field", "confirmation needs the complete displayed consent fingerprint")
        async with self._own():
            session = self._session(); intent = self._load(session)
            if not intent["export_ended"]:
                raise LiveTradeError("preparation_required", "finish frozen preparation before consenting")
            await self._held(intent, session)
            view = (await self._rpc(session, "confirm", transaction_id=intent["transaction_id"],
                generation=intent["generation"], fingerprint=fingerprint))["trade"]
            if view["state"] == "committed":
                self._record_fate(intent, view)
            return view

    async def _terminal(self, intent, session, opcode, revision):
        previous = None if intent["control"] is None else SaveControl.unpack(base64.b64decode(intent["control"]))
        if previous is not None and previous.opcode == opcode and previous.session_epoch == session[1]:
            command = previous
        else:
            self.companion._live_sequence += 1
            if self.companion._live_sequence > MAX_COUNTER:
                raise LiveTradeError("counter_exhausted", "trade command sequence is exhausted")
            command = SaveControl(session[2], session[1], intent["transaction_id"], self.companion._live_sequence,
                0, FLASH_SIZE, revision, opcode)
            intent["control"] = base64.b64encode(command.pack()).decode("ascii")
            self._save(intent)
        response = await self.companion.save_rpc(command, timeout=20)
        self._same_session(session)
        return self._ok(response)

    def _finish(self, intent, outcome):
        # An explicitly canceled proposal may reopen the same transaction UUID
        # with a fresh generation. Preserve each consent generation's outcome.
        self._immutable(intent["transaction_id"] + "." + intent["generation"] + ".trade-complete.json",
            _json_bytes({"intent": intent, "outcome": outcome}))
        self.trade_path.unlink()
        _sync_directory(self.directory)
        return {"transaction_id": intent["transaction_id"], "state": outcome, "checkpoint": intent["canonical"] or intent["prepared"]}

    async def _abort(self, intent, session):
        if intent["phase"] == "intent":
            # No BEGIN could have run: "starting" is fsynced before that send.
            # Establish the initial binding, durably preserve the current game
            # via preparation, then use the ordinary authoritative abort path.
            await self._prepare(intent, session)
        hold = await self._query(intent, session)
        if not hold.active:
            if intent["phase"] != "aborting" or intent["control"] is None:
                raise LiveTradeError("recovery_required", "inactive ROM state cannot prove a pending trade was safely aborted")
            command = SaveControl.unpack(base64.b64decode(intent["control"]))
            frozen = self._bytes(intent["prepare_id"] + ".flash", intent["frozen_sha256"], FLASH_SIZE)
            if (command.opcode != Opcode.ABORT_TRADE or hold.phase != State.BOUND
                    or hold.revision != intent["expected_revision"]+1 or hold.next_offset != FLASH_SIZE
                    or hold.crc32 != zlib.crc32(frozen)):
                raise LiveTradeError("recovery_required", "ROM state does not prove the recorded abort")
            if command.session_epoch == session[1]:
                await self._terminal(intent, session, Opcode.ABORT_TRADE, command.revision)
            return self._finish(intent, "aborted")
        if hold.import_started:
            raise LiveTradeError("recovery_required", "an imported trade cannot be aborted; recover its canonical outcome")
        await self._prepare(intent, session)
        head = await self.client.info(); self._same_session(session)
        if head != intent["prepared"]:
            raise LiveTradeError("revision_conflict", "preparation is no longer the current canonical character")
        await self._held(intent, session)
        intent["phase"] = "aborting"; self._save(intent)
        await self._terminal(intent, session, Opcode.ABORT_TRADE, intent["expected_revision"]+1)
        return self._finish(intent, "aborted")

    async def cancel(self):
        async with self._own():
            session = self._session(); intent = self._load(session)
            view = (await self._rpc(session, "cancel", transaction_id=intent["transaction_id"], generation=intent["generation"]))["trade"]
            if view["state"] == "committed":
                self._record_fate(intent, view)
                return await self._apply(intent, session)
            if intent["fate"] is not None:
                raise LiveTradeError("trade_conflict", "a committed trade cannot be canceled")
            return await self._abort(intent, session)

    async def _apply(self, intent, session):
        fate = intent["fate"]
        if fate is None:
            raise LiveTradeError("trade_conflict", "canonical import requires committed server fate")
        pending = (await self._rpc(session, "pending"))["recoveries"]
        head = await self.client.info(); self._same_session(session)
        if head is None or (head["request_id"], head["revision"], head["sha256"]) != (
                intent["transaction_id"], intent["expected_revision"]+2, fate["sha256"]):
            raise LiveTradeError("revision_conflict", "never apply historical trade fate over a newer canonical head")
        if pending:
            if len(pending) != 1 or pending[0]["transaction_id"] != intent["transaction_id"] or pending[0]["checkpoint"] != head or pending[0]["outcome_fingerprint"] != fate["outcome_fingerprint"]:
                raise LiveTradeError("trade_conflict", "pending recovery is not this exact committed result")
        elif intent["receipt_id"] is None:
            raise LiveTradeError("recovery_required", "the server result was acknowledged without this coordinator's verified apply")
        downloaded = await self.client.download(); self._same_session(session)
        if downloaded is None or downloaded.metadata != head or (downloaded.world_id, downloaded.player_id) != (session[0], intent["player_id"]):
            raise LiveTradeError("trade_conflict", "downloaded trade result changed or belongs to another character")
        parsed = inspect_flash(downloaded.payload, save_profile=OWNERSHIP_PROFILE)
        self._immutable(intent["transaction_id"] + ".canonical.flash", downloaded.payload)
        if intent["canonical"] is not None and intent["canonical"] != head:
            raise LiveTradeError("trade_conflict", "immutable committed checkpoint metadata changed")
        intent["canonical"] = head; self._save(intent)
        hold = await self._query(intent, session)
        if not hold.active:
            if intent["phase"] != "releasing" or intent["receipt_id"] is None or intent["control"] is None:
                raise LiveTradeError("recovery_required", "inactive ROM state cannot prove the canonical trade was released")
            control = SaveControl.unpack(base64.b64decode(intent["control"]))
            applied = self._bytes(intent["receipt_id"] + ".applied.flash", intent["applied_sha256"], FLASH_SIZE)
            if (control.opcode != Opcode.RELEASE_TRADE or hold.phase != State.BOUND
                    or hold.revision != head["revision"] or hold.next_offset != FLASH_SIZE
                    or hold.crc32 != zlib.crc32(applied)):
                raise LiveTradeError("recovery_required", "ROM state does not prove the recorded canonical release")
            if control.session_epoch == session[1]:
                self._crc(await self._terminal(intent, session, Opcode.RELEASE_TRADE, head["revision"]), applied)
            return self._finish(intent, "applied")
        if not hold.import_started:
            await self._prepare(intent, session)
        hold = await self._held(intent, session)
        applied = None
        if intent["receipt_id"] is not None and hold.phase == State.COMMITTED and hold.next_offset == FLASH_SIZE:
            prior = self._bytes(intent["receipt_id"] + ".applied.flash", intent["applied_sha256"], FLASH_SIZE)
            if hold.crc32 == zlib.crc32(prior):
                applied = prior
        if applied is None:
            payload = parsed.flash
            rotation = (-struct.unpack_from("<H", payload, parsed.metadata.bank*14*4096+4084)[0]) % 14
            await self._command(session, intent["transaction_id"], head["revision"], Opcode.BEGIN_IMPORT,
                data=struct.pack("<IIII", zlib.crc32(payload), parsed.metadata.counter, rotation, parsed.metadata.trainer_id))
            for offset in range(0, FLASH_SIZE, SAVE_CHUNK_SIZE):
                response = await self._command(session, intent["transaction_id"], head["revision"], Opcode.WRITE,
                    offset=offset, data=payload[offset:offset+SAVE_CHUNK_SIZE])
                if response.offset != offset+SAVE_CHUNK_SIZE:
                    raise LiveTradeError("write_position", "the ROM did not acknowledge the exact staged trade chunk")
            if await self.client.info() != head:
                raise LiveTradeError("revision_conflict", "canonical trade changed before Flash publication")
            self._same_session(session)
            await self._held(intent, session)
            await self._command(session, intent["transaction_id"], head["revision"], Opcode.COMMIT, offset=FLASH_SIZE, timeout=20)
            applied = await self._read_flash(session, intent["transaction_id"], head["revision"])
            if inspect_flash(applied, save_profile=OWNERSHIP_PROFILE).state_sha256 != parsed.state_sha256:
                raise LiveTradeError("applied_state", "trade readback differs from the canonical game state")
            receipt_id = str(uuid4())
            self._immutable(receipt_id + ".applied.flash", applied)
            record_live_apply(self.directory / (receipt_id + ".live-apply.json"), downloaded, applied,
                operation_id=receipt_id, rom_request_id=intent["transaction_id"], session_epoch=session[1], incarnation=session[2])
            intent["receipt_id"], intent["applied_sha256"], intent["phase"] = receipt_id, hashlib.sha256(applied).hexdigest(), "applied"
            self._save(intent)
        if await self.client.info() != head:
            raise LiveTradeError("revision_conflict", "canonical trade changed before recovery acknowledgment")
        self._same_session(session)
        await self._rpc(session, "ack", transaction_id=intent["transaction_id"], revision=head["revision"], sha256=head["sha256"])
        intent["phase"] = "acknowledged"; self._save(intent)
        await self._held(intent, session)
        intent["phase"] = "releasing"; self._save(intent)
        response = await self._terminal(intent, session, Opcode.RELEASE_TRADE, head["revision"])
        self._crc(response, applied)
        return self._finish(intent, "applied")

    async def resume(self):
        """Recover this same running ROM after an uncertain ACK or remote reconnect."""
        async with self._own():
            session = self._session(); intent = self._load(session)
            view = await self._fate(intent, session)
            if view["state"] == "committed":
                return await self._apply(intent, session)
            if view["state"] == "aborted":
                return await self._abort(intent, session)
            if view["generation"] != intent["generation"]:
                raise LiveTradeError("trade_changed", "a new proposal generation requires a new explicit preparation")
            await self._prepare(intent, session)
            return view

    async def recover(self):
        return await self.resume()
