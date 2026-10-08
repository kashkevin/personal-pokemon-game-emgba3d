"""Durable original-core consent before any provisional native field hold.

This is host evidence captured from authenticated consent, never a client
replacement for a missing challenge. Native ADMIT proofs preserve the exact
original core and ordinary sequence base across a pre-BIND host restart.
"""
from __future__ import annotations

import json
from pathlib import Path
import stat

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
        if (b.state != "accepted" or b.consent != set(b.players)
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
            value["canceled"] = True
            _atomic(path, _json_bytes(value))

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
