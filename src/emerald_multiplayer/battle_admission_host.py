"""Durable original-core consent before any provisional native field hold.

This is host evidence captured from authenticated consent, never a client
replacement for a missing challenge. Native ADMIT proofs preserve the exact
original core and ordinary sequence base across a pre-BIND host restart.
"""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
import stat
from dataclasses import replace

from .battle_desk import BattleError
from .battle_execution_journal import RouteJournal
from .battle_execution_protocol import decode_control, encode_control
from .battle_protocol import challenge_view, _view
from .battle_recovery_protocol import recovery_view
from .live_checkpoint import _atomic, _json_bytes
from .native_battle import NativeBinding, NativeControl, NativeQuery, Opcode
from .native_battle_resume import Admission


class BattleAdmissionHost:
    def __init__(self, execution):
        self.execution, self.desk = execution, execution.desk
        self.ready = {}

    def _path(self, battle_id):
        return self.execution.directory / (battle_id+".consent.json")

    def _read(self, battle_id):
        path = self._path(battle_id)
        try:
            if not stat.S_ISREG(path.lstat().st_mode):
                raise OSError("original consent must be a regular file")
            with path.open("rb") as source:
                raw = source.read(32769)
        except OSError as error:
            raise BattleError("battle_admission_invalid", "original durable consent is unavailable") from error
        try:
            value = json.loads(raw)
            if (len(raw) > 32768 or raw != _json_bytes(value) or set(value) != {
                    "format", "world_id", "build_id", "ruleset_id", "save_profile", "server_epoch",
                    "view", "leases", "rng", "identities", "proofs", "claimed", "canceled"}
                    or value["format"] != "native-original-core-consent-v1"):
                raise ValueError()
            metadata = self.desk.store._validate_metadata()
            if any(value[key] != metadata[key] for key in ("world_id", "build_id", "ruleset_id", "save_profile")):
                raise ValueError()
            from .protocol import MAX_COUNTER
            if type(value["server_epoch"]) is not int or not 1 <= value["server_epoch"] <= metadata["server_epoch"]:
                raise ValueError()
            view = value["view"]
            _view(view, view["sender"])
            if view["battle_id"] != battle_id or len(value["leases"]) != len(view["players"]):
                raise ValueError()
            if any(type(lease) is not int or not 1 <= lease <= MAX_COUNTER for lease in value["leases"]):
                raise ValueError()
            if (type(value["rng"]) is not str or len(value["rng"]) != 32
                    or bytes.fromhex(value["rng"]).hex() != value["rng"] or not any(bytes.fromhex(value["rng"]))):
                raise ValueError()
            if (type(value["identities"]) is not dict or type(value["proofs"]) is not dict
                    or not set(value["identities"]).issubset(view["consent"])
                    or not set(value["proofs"]).issubset(value["identities"])):
                raise ValueError()
            if (type(value["claimed"]) is not list or len(set(value["claimed"])) != len(value["claimed"])
                    or not set(value["claimed"]).issubset(value["identities"]) or type(value["canceled"]) is not bool):
                raise ValueError()
            for actor, identity in value["identities"].items():
                if set(identity) != {"incarnation", "runtime_id"}:
                    raise ValueError()
                self._identity(identity)
            for actor, proof in value["proofs"].items():
                self._proof(value, actor, proof)
            return value
        except (KeyError, TypeError, ValueError) as error:
            raise BattleError("battle_admission_invalid", "original consent cannot be reconstructed exactly") from error

    @staticmethod
    def _identity(request):
        from .battle_mailbox import _integer, _uuid
        _integer(request["incarnation"], 1, 0xFFFFFFFF, "original native incarnation")
        _uuid(request["runtime_id"], "original native runtime")
        return dict(incarnation=request["incarnation"], runtime_id=request["runtime_id"])

    def require_identity(self, request):
        try:
            return self._identity(request)
        except (KeyError, ValueError) as error:
            raise BattleError("battle_original_core_required", "consent requires the verified original game core") from error

    def capture(self, actor, lease, request):
        identity = self.require_identity(request)
        b = self.desk._get(actor, lease, request["battle_id"], historical=True)
        if actor not in b.consent or b.state not in ("invited", "accepted"):
            raise BattleError("battle_not_ready", "the original trainer has not consented")
        path = self._path(b.battle_id)
        previous = self._read(b.battle_id) if path.exists() else None
        if previous is not None:
            if previous["canceled"]:
                raise BattleError("battle_admission_canceled", "original consent is irrevocably canceled")
            if (previous["view"]["generation"] != b.generation or previous["leases"] != list(b.leases)
                    or previous["rng"] != b.rng.hex()
                    or (actor in previous["identities"] and previous["identities"][actor] != identity)):
                raise BattleError("battle_incarnation_changed", "consent cannot replace its original native core")
        metadata = self.desk.store._validate_metadata()
        value = dict(format="native-original-core-consent-v1",
            **{key: metadata[key] for key in ("world_id", "build_id", "ruleset_id", "save_profile", "server_epoch")},
            view=challenge_view(self.desk._view(b)), leases=list(b.leases), rng=b.rng.hex(),
            identities={} if previous is None else previous["identities"],
            proofs={} if previous is None else previous["proofs"],
            claimed=[] if previous is None else previous["claimed"],
            canceled=False if previous is None else previous["canceled"])
        value["identities"][actor] = identity
        try:
            _atomic(path, _json_bytes(value))
        except BaseException:
            self.desk._recover(b, "original_consent_not_durable")
            raise

    def claim(self, actor, lease, request):
        b = self.desk._get(actor, lease, request["battle_id"], request["generation"])
        value = self._read(b.battle_id)
        if (value["canceled"] or b.state != "accepted" or b.consent != set(b.players)
                or value["view"]["state"] != "accepted"
                or value["identities"].get(actor) != self.require_identity(request)):
            raise BattleError("battle_not_ready", "Enter requires the exact accepted original game core")
        if actor not in value["claimed"]:
            value["claimed"].append(actor)
            _atomic(self._path(b.battle_id), _json_bytes(value))
        b.resumable = True
        return self.desk._view(b)

    def canceled(self, battle_id):
        path = self._path(battle_id)
        if path.exists():
            value = self._read(battle_id)
            if not value["canceled"]:
                value["canceled"] = True
                _atomic(path, _json_bytes(value))

    def assert_not_canceled(self, battle_id):
        """Synchronous first-BIND fence, including after host reconstruction."""
        from .battle_journal import path_present
        if path_present(self._path(battle_id)) and self._read(battle_id)["canceled"]:
            raise BattleError("battle_admission_canceled", "original consent is irrevocably canceled")

    def has_consent(self, battle_id):
        """Presence is only a contradiction check, never proof of safe absence."""
        from .battle_journal import path_present
        return path_present(self._path(battle_id))

    def unentered_terminal(self, battle_id, *, revoke=False):
        """Affirmative incomplete-consent evidence, before any eligible Enter.

        The accepted descriptor is persisted before it can reach a client, and
        claim/ADMIT require that fully accepted descriptor. A partial record is
        therefore useful evidence; a missing record is not. Cancellation fences
        late capture/claim/BIND before the volatile invitation is archived.
        """
        from .battle_admission_cleanup_protocol import UnenteredInvitationTerminal
        if not self.has_consent(battle_id):
            return None
        value = self._read(battle_id)
        view = value["view"]
        if (view["mode"] != 2 or view["state"] != "invited" or view["outcome"] is not None
                or set(view["consent"]) != {view["sender"]}
                or set(value["identities"]) != {view["sender"]}
                or value["claimed"] or value["proofs"]):
            return None
        battle = self.desk._active.get(battle_id) or self.desk._history.get(battle_id)
        if battle is not None:
            if (battle.generation != view["generation"] or battle.fingerprint != view["fingerprint"]
                    or battle.sender != view["sender"] or list(battle.players) != view["players"]
                    or list(battle.leases) != value["leases"] or battle.mode != view["mode"]):
                raise BattleError("battle_admission_invalid", "unentered invitation identity changed")
            if (battle.state not in {"invited", "aborted", "recovery_required"}
                    or battle.consent == set(battle.players) or battle.resumable):
                return None
        try:
            self._unreserved(value)
        except BattleError as error:
            if error.code == "battle_recovery_required":
                return None
            raise
        if not value["canceled"]:
            if not revoke:
                return None
            value["canceled"] = True
            _atomic(self._path(battle_id), _json_bytes(value))
        # A lost tombstone-write reply may leave only this volatile cleanup.
        # Completing it is safe even on a read: cancellation is already durable.
        if battle is not None and battle.state != "aborted":
            self.desk._abort(battle, "unentered_invitation_canceled")
        return UnenteredInvitationTerminal(
            value["world_id"], value["build_id"], value["ruleset_id"], battle_id,
            view["generation"], view["sender"], view["mode"], tuple(view["players"]),
            view["fingerprint"], hashlib.sha256(_json_bytes(value)).hexdigest())

    def _unreserved(self, value):
        from .battle_journal import path_present
        view, battle_id = value["view"], value["view"]["battle_id"]
        row = self.desk.store._connection.execute(
            "SELECT battle_id FROM battle_reservations WHERE battle_id=?", (battle_id,)).fetchone()
        room = self.execution.rooms.get(battle_id)
        battle = self.desk._active.get(battle_id) or self.desk._history.get(battle_id)
        if (row is not None or path_present(self.execution.directory / (battle_id + ".events.jsonl"))
                or battle is not None and (battle.bind_intent or battle.bound or battle.prepared or battle.started)
                or room is not None and (room.pending or room.acknowledged or room.journal is not None)):
            raise BattleError("battle_recovery_required", "a reserved or possibly dispatched battle cannot use neutral cleanup")
        # A prior host may have persisted a command before losing its in-memory
        # room. Never infer absence from the current process's maps alone.
        path = self.execution.directory / (battle_id + ".json")
        if path_present(path):
            from .battle_terminal import _read
            record = _read(path)
            if (set(record) != {"format", "world_id", "build_id", "ruleset_id", "battle_id", "generation",
                    "fingerprint", "players", "leases", "incarnations", "state", "error", "admitted", "pending", "acknowledged"}
                    or record["format"] != "native-battle-execution-intent-v1"
                    or any(record[key] != value[key] for key in ("world_id", "build_id", "ruleset_id", "leases"))
                    or any(record[key] != view[key] for key in ("battle_id", "generation", "fingerprint", "players"))
                    or type(record["incarnations"]) is not dict
                    or any(actor not in value["identities"] or type(incarnation) is not int
                        or incarnation != value["identities"][actor]["incarnation"]
                        for actor, incarnation in record["incarnations"].items())
                    or record["pending"] != {} or record["acknowledged"] != {} or record["admitted"] != {}
                    or record["state"] not in ("waiting", "executing", "aborted") or record["error"] is not None):
                raise BattleError("battle_recovery_required", "persisted execution cannot prove undispatched admission")

    def cancel_admission(self, actor, lease, request):
        """Durably revoke only a battle that has NEVER obtained a reservation.

        No await occurs between exclusion, tombstone publication and archive.
        A canceled consent is immutable; its digest names every retry forever.
        """
        from .battle_admission_cleanup_protocol import AdmissionCancellation, SCOPE
        from .battle_journal import path_present
        from .battle_terminal import _read
        value = self._read(request["battle_id"])
        view = value["view"]
        cp = self.desk._auth(actor, lease)
        if (actor not in value["identities"] or view["generation"] != request["generation"]
                or value["identities"][actor] != self.require_identity(request)):
            raise BattleError("battle_incarnation_changed", "cleanup requires its original consented game core")
        slot = view["players"].index(actor)
        pinned = view["checkpoints"][slot]
        if (lease < value["leases"][slot] or cp is None
                or (cp.revision, cp.sha256) != (pinned["revision"], pinned["sha256"])):
            raise BattleError("canonical_head_mismatch", "cleanup changed its original canonical checkpoint")
        import struct
        ready = NativeControl(request["incarnation"], lease, view["battle_id"], 1, Opcode.ADMISSION_CANCEL_READY,
            phase=view["mode"], source_slot=slot,
            data=Admission(view["generation"], actor, request["runtime_id"]).pack() + struct.pack("<I", value["leases"][slot]))
        receipt = decode_control(request["cleanup_ready_b64"], response=True)
        receipt.validate_response(ready)
        if receipt.status:
            raise BattleError("invalid_receipt", "native capacity/phase readiness was refused")
        self._unreserved(value)
        if not value["canceled"]:
            value["canceled"] = True
            _atomic(self._path(view["battle_id"]), _json_bytes(value))
        battle = self.desk._active.get(view["battle_id"])
        if battle is not None:
            self.desk._abort(battle, "admission_canceled")
        room = self.execution.rooms.get(view["battle_id"])
        if room is not None:
            room.state = "aborted"
            self.execution._persist(room)
        digest = hashlib.sha256(_json_bytes(value)).hexdigest()
        result = dict(scope=SCOPE, battle_id=view["battle_id"], generation=view["generation"],
            **value["identities"][actor], original_lease=value["leases"][slot],
            tombstone_sha256=digest, acknowledged=request["cleanup_receipt_b64"] is not None)
        if result["acknowledged"]:
            payload = AdmissionCancellation(Admission(view["generation"], actor, result["runtime_id"]),
                result["original_lease"], digest).pack()
            command = NativeControl(result["incarnation"], lease, view["battle_id"], 1,
                Opcode.ADMISSION_CANCEL_HOLD, phase=view["mode"], source_slot=slot, data=payload)
            receipt = decode_control(request["cleanup_receipt_b64"], response=True)
            receipt.validate_response(command)
            if receipt.status:
                raise BattleError("invalid_receipt", "neutral native hold was not acknowledged")
            record = dict(format=SCOPE, player_id=actor, result=result,
                          command_b64=encode_control(command), receipt_b64=encode_control(receipt))
            path = self.execution.directory / (view["battle_id"] + "." + actor + "." + str(lease) + ".cancel-ack.json")
            if path_present(path) and _read(path) != record:
                raise BattleError("invalid_receipt", "neutral cleanup acknowledgment changed")
            _atomic(path, _json_bytes(record))
        return result

    def _handoff_path(self, battle_id, actor):
        return self.execution.directory / (battle_id + "." + actor + ".cancel-handoff.json")

    def _handoff_record(self, value, actor, receipt):
        """Reconstruct one receipt only from the durable original HOLD ACK."""
        from .battle_admission_cleanup_protocol import (AdmissionCancellation, HANDOFF_SCOPE,
            SCOPE, handoff_view)
        from .battle_terminal import _read
        view = value["view"]
        identity = value["identities"][actor]
        slot = view["players"].index(actor)
        digest = hashlib.sha256(_json_bytes(value)).hexdigest()
        payload = AdmissionCancellation(Admission(view["generation"], actor, identity["runtime_id"]),
            value["leases"][slot], digest).pack()
        command = NativeControl(identity["incarnation"], receipt.session_epoch, view["battle_id"], 1,
            Opcode.ADMISSION_CANCEL_HANDOFF, phase=view["mode"], source_slot=slot, data=payload)
        command.validate_command(player_id=actor)
        receipt.validate_response(command)
        if (receipt.status or not value["canceled"]
                or receipt.session_epoch > self.desk.store._validate_metadata()["session_epoch"]):
            raise ValueError("handoff requires its immutable cancellation and successful receipt")
        held = replace(command, opcode=Opcode.ADMISSION_CANCEL_HOLD)
        ack_path = self.execution.directory / (view["battle_id"] + "." + actor + "."
            + str(command.session_epoch) + ".cancel-ack.json")
        ack = _read(ack_path)
        expected = dict(format=SCOPE, player_id=actor,
            result=dict(scope=SCOPE, battle_id=view["battle_id"], generation=view["generation"],
                **identity, original_lease=value["leases"][slot], tombstone_sha256=digest, acknowledged=True),
            command_b64=encode_control(held), receipt_b64=encode_control(held))
        # Successful HOLD echoes the entire exact command, including payload.
        if ack != expected:
            raise ValueError("handoff lacks the exact successful host-acknowledged HOLD")
        return dict(format=HANDOFF_SCOPE, **{key: value[key] for key in
                ("world_id", "build_id", "ruleset_id", "save_profile")}, player_id=actor,
            result=handoff_view(receipt), hold_sha256=hashlib.sha256(_json_bytes(ack)).hexdigest(),
            command_b64=encode_control(command), receipt_b64=encode_control(receipt))

    def admission_handoff(self, actor, lease, request):
        """Record an already completed native release; issue no native control.

        A newer authenticated lease may deliver the original historical receipt.
        The current checkpoint need not be rolled back to the admitted revision.
        """
        from .battle_journal import path_present
        from .battle_terminal import _read
        self.desk._auth(actor, lease)
        value = self._read(request["battle_id"])
        if (value["view"]["generation"] != request["generation"]
                or value["identities"].get(actor) != self.require_identity(request)):
            raise BattleError("battle_incarnation_changed", "handoff differs from original durable consent")
        self._unreserved(value)
        try:
            receipt = decode_control(request["handoff_receipt_b64"], response=True)
            if receipt.session_epoch > lease:
                raise ValueError("handoff receipt belongs to a future lease")
            record = self._handoff_record(value, actor, receipt)
            path = self._handoff_path(request["battle_id"], actor)
            if path_present(path):
                if _read(path) != record:
                    raise ValueError("the original terminal handoff changed")
            else:
                _atomic(path, _json_bytes(record))
        except (ValueError, TypeError, KeyError) as error:
            raise BattleError("invalid_receipt", "retain the exact original terminal handoff and host HOLD acknowledgment") from error
        return record["result"]

    def terminal(self, battle_id):
        """Read affirmative all-originals handoff evidence, never absence proof."""
        from .battle_admission_cleanup_protocol import AdmissionCleanupTerminal
        from .battle_journal import path_present
        from .battle_mailbox import _uuid
        from .battle_terminal import _read
        _uuid(battle_id, "battle ID")
        if not path_present(self._path(battle_id)):
            return None
        value = self._read(battle_id)
        view = value["view"]
        if (not value["canceled"] or view["state"] != "accepted"
                or set(value["identities"]) != set(view["players"])
                or set(view["consent"]) != set(view["players"])):
            return None
        paths = [self._handoff_path(battle_id, actor) for actor in view["players"]]
        if not all(path_present(path) for path in paths):
            return None
        self._unreserved(value)
        records = []
        try:
            for actor, path in zip(view["players"], paths):
                record = _read(path)
                receipt = decode_control(record["receipt_b64"], response=True)
                if record != self._handoff_record(value, actor, receipt):
                    raise ValueError("terminal handoff no longer matches original consent")
                records.append(record)
        except (ValueError, TypeError, KeyError) as error:
            raise BattleError("battle_admission_invalid", "original terminal handoff evidence is inconsistent") from error
        return AdmissionCleanupTerminal(value["world_id"], value["build_id"], value["ruleset_id"],
            battle_id, view["generation"], view["sender"], view["mode"], tuple(view["players"]),
            view["fingerprint"], hashlib.sha256(_json_bytes(records)).hexdigest())

    @staticmethod
    def _proof(value, actor, proof):
        if type(proof) is not dict or set(proof) != {"command", "receipt"}:
            raise ValueError("invalid admission proof")
        command = decode_control(proof["command"])
        receipt = decode_control(proof["receipt"], response=True)
        receipt.validate_response(command)
        view, identity = value["view"], value["identities"][actor]
        slot = view["players"].index(actor)
        if (command.opcode != Opcode.ADMIT or command.sequence != 1 or receipt.status
                or command.battle_id != view["battle_id"] or command.incarnation != identity["incarnation"]
                or command.session_epoch != value["leases"][slot] or command.phase != view["mode"]
                or command.source_slot != slot
                or Admission.unpack(command.data) != Admission(view["generation"], actor, identity["runtime_id"])):
            raise ValueError("admission replaced its original consented core")
        return NativeQuery.unpack(receipt.data)

    def prove(self, actor, lease, request):
        value = self._read(request["battle_id"])
        view = value["view"]
        if (value["canceled"] or view["state"] != "accepted" or set(view["consent"]) != set(view["players"])
                or set(value["identities"]) != set(view["players"]) or actor not in view["players"]
                or view["generation"] != request["generation"]
                or value["identities"][actor] != self.require_identity(request)):
            raise BattleError("battle_incarnation_changed", "provisional core differs from durable accepted consent")
        slot = view["players"].index(actor)
        cp = self.desk._auth(actor, lease)
        pinned = view["checkpoints"][slot]
        if (lease < value["leases"][slot] or cp is None
                or (cp.revision, cp.sha256) != (pinned["revision"], pinned["sha256"])):
            raise BattleError("canonical_head_mismatch", "provisional admission changed its accepted owned checkpoint")
        try:
            proof = dict(command=request["admission_b64"], receipt=request["admission_receipt_b64"])
            query = self._proof(value, actor, proof)
            if actor in value["proofs"] and value["proofs"][actor] != proof:
                raise ValueError("original admission receipt changed")
        except (KeyError, ValueError) as error:
            raise BattleError("invalid_admission", "retain the exact successful original provisional hold") from error
        if actor not in value["proofs"] or actor not in value["claimed"]:
            value["proofs"][actor] = proof
            if actor not in value["claimed"]:
                value["claimed"].append(actor)
            _atomic(self._path(view["battle_id"]), _json_bytes(value))
        return value, query

    def recover(self, actor, lease, request):
        value, _ = self.prove(actor, lease, request)
        view = value["view"]
        ready = self.ready.setdefault(view["battle_id"], {})
        ready[actor] = (lease, dict(request))
        if len(ready) != len(view["players"]):
            return recovery_view(view["battle_id"], view["generation"], "waiting")
        for player in view["players"]:
            current, proof = ready[player]
            self.prove(player, current, proof)
        value = self._read(view["battle_id"])
        record = self._reservation(value)
        sequences = [self._proof(value, player, value["proofs"][player]).last_sequence for player in view["players"]]
        path = self.execution.directory / (view["battle_id"]+".events.jsonl")
        header = dict(record=record, battle_id=view["battle_id"], generation=view["generation"], players=view["players"],
            leases=record["leases"], incarnations=record["incarnations"], mode=view["mode"], initial_sequences=sequences)
        journal = RouteJournal(path, header, create=not path.exists())
        if journal.completed:
            raise BattleError("battle_admission_invalid", "provisional conversion cannot replace an executed full intent")
        for slot, player in enumerate(view["players"]):
            binding = NativeBinding(view["generation"], tuple(view["players"]), tuple(record["leases"]),
                tuple(record["incarnations"]), slot, mode=view["mode"], resumable=True)
            bind = NativeControl(record["incarnations"][slot], record["leases"][slot], view["battle_id"],
                sequences[slot]+1, Opcode.BIND, phase=view["mode"], source_slot=slot, data=binding.pack())
            if player not in journal.pending:
                journal.append("command", player, 1, bind)
            elif journal.pending[player] != (1, bind):
                raise BattleError("battle_admission_invalid", "original undispatched BIND changed")
        result = recovery_view(view["battle_id"], view["generation"], "admitting", "admission")
        result["admission"] = dict(bind_b64=encode_control(journal.pending[actor][1]), original_server_epoch=record["server_epoch"])
        return result

    def register_full(self, actor, lease, request, record):
        """Count an authenticated, durably acknowledged full intent at bootstrap.

        A second host loss can split the group between full intents and their
        original provisional records. The full-intent recovery path has already
        checked the exact BIND hash against the route journal; its original
        ADMIT evidence comes only from this durable consent record.
        """
        value = self._read(request["battle_id"])
        if (value["view"] != record["view"] or value["leases"] != record["leases"]
                or value["server_epoch"] != record["server_epoch"]
                or value["identities"].get(actor, {}).get("incarnation") != request["incarnation"]
                or actor not in value["proofs"]):
            raise BattleError("battle_admission_invalid", "full intent lost its original provisional evidence")
        proof = value["proofs"][actor]
        original = dict(battle_id=request["battle_id"], generation=request["generation"],
            incarnation=request["incarnation"], runtime_id=value["identities"][actor]["runtime_id"],
            admission_b64=proof["command"], admission_receipt_b64=proof["receipt"])
        self.prove(actor, lease, original)
        self.ready.setdefault(request["battle_id"], {})[actor] = (lease, original)

    def _reservation(self, value):
        """Publish only preexisting consent after every original ADMIT proof.

        No full BIND existed before this transaction. Original retired leases
        describe immutable consent; current authenticated heads were checked
        for every trainer immediately before this synchronous publication.
        """
        from .battle_reservations import SCOPE, _digest, _json
        store, view = self.desk.store, value["view"]
        self.assert_not_canceled(view["battle_id"])
        with store._transaction():
            old = store._connection.execute("SELECT * FROM battle_reservations WHERE battle_id=?", (view["battle_id"],)).fetchone()
            if old is not None:
                record = self.desk.reservations._read(old)
                if (old["terminal_kind"] is not None or record["view"] != view
                        or record["leases"] != value["leases"] or record["rng"] != value["rng"]
                        or record["incarnations"] != [value["identities"][player]["incarnation"] for player in view["players"]]):
                    raise BattleError("battle_admission_invalid", "a terminal battle cannot acquire provisional admission")
                return record
            self.desk.reservations._assert_available(view["players"])
            record = dict(scope=SCOPE, **{key: value[key] for key in
                ("world_id", "build_id", "ruleset_id", "save_profile", "server_epoch", "view", "leases", "rng")},
                incarnations=[value["identities"][player]["incarnation"] for player in view["players"]])
            mask = (1 << len(view["players"]))-1
            store._connection.execute("INSERT INTO battle_reservations VALUES (?, ?, ?, NULL, NULL, ?)",
                (view["battle_id"], _json(record), mask, _digest([record, mask, None, None])))
            store._connection.executemany("INSERT INTO battle_reservation_actors VALUES (?, ?, ?)",
                [(player, view["battle_id"], slot) for slot, player in enumerate(view["players"])])
            self.desk.reservations._active()
            return record
