"""Optional ABI1 neutral cleanup; no battle result, rollback, or BIND authority."""
from dataclasses import dataclass
import struct

from .battle_mailbox import BattleMailboxError, _integer
from .native_battle_resume import Admission
from .protocol import MAX_COUNTER, ProtocolError, _fields

SCOPE = "native-unreserved-admission-cancellation-v1"
HANDOFF_SCOPE = "native-unreserved-admission-handoff-v1"


@dataclass(frozen=True)
class AdmissionCleanupTerminal:
    world_id: str
    build_id: str
    ruleset_id: str
    battle_id: str
    generation: str
    sender: str
    mode: int
    players: tuple[str, ...]
    fingerprint: str
    digest: str
    kind: str = "aborted"


@dataclass(frozen=True)
class UnenteredInvitationTerminal:
    """Host revocation of incomplete consent, never a native HOLD receipt."""
    world_id: str
    build_id: str
    ruleset_id: str
    battle_id: str
    generation: str
    sender: str
    mode: int
    players: tuple[str, ...]
    fingerprint: str
    digest: str
    kind: str = "aborted"


@dataclass(frozen=True)
class AdmissionCancellation:
    admission: Admission
    original_lease: int
    tombstone_sha256: str

    def __post_init__(self):
        from .battle_protocol import _digest
        if type(self.admission) is not Admission:
            raise BattleMailboxError("cleanup requires the original admission")
        _integer(self.original_lease, 1, MAX_COUNTER, "original admission lease")
        _digest(self.tombstone_sha256)
        if not any(bytes.fromhex(self.tombstone_sha256)):
            raise BattleMailboxError("cancellation digest must be nonzero")

    def pack(self):
        return self.admission.pack() + struct.pack("<I", self.original_lease) + bytes.fromhex(self.tombstone_sha256)

    @classmethod
    def unpack(cls, data):
        if type(data) is not bytes or len(data) != 84:
            raise BattleMailboxError("admission cleanup requires exactly 84 bytes")
        return cls(Admission.unpack(data[:48]), struct.unpack_from("<I", data, 48)[0], data[52:].hex())


def validate_cancellation_view(value, actor, request=None):
    from .battle_protocol import _digest
    from .team_protocol import _uuid
    _fields(value, {"scope", "battle_id", "generation", "incarnation", "runtime_id",
                    "original_lease", "tombstone_sha256", "acknowledged"})
    for key in ("battle_id", "generation", "runtime_id"):
        _uuid(value[key], key)
    _integer(value["incarnation"], 1, 0xFFFFFFFF, "original incarnation")
    _integer(value["original_lease"], 1, MAX_COUNTER, "original admission lease")
    _digest(value["tombstone_sha256"])
    if not any(bytes.fromhex(value["tombstone_sha256"])):
        raise ProtocolError("invalid_server_message", "cancellation digest must be nonzero")
    if value["scope"] != SCOPE or type(value["acknowledged"]) is not bool:
        raise ProtocolError("invalid_server_message", "invalid neutral admission cancellation")
    if request is not None and (any(value[key] != request[key] for key in
            ("battle_id", "generation", "incarnation", "runtime_id"))
            or value["acknowledged"] != (request["cleanup_receipt_b64"] is not None)):
        raise ProtocolError("identity_mismatch", "cancellation changed its original admission")
    return value


def handoff_view(receipt):
    """Receipt identity only; neither this view nor its hash grants release."""
    import hashlib
    cancellation = AdmissionCancellation.unpack(receipt.data)
    return dict(scope=HANDOFF_SCOPE, battle_id=receipt.battle_id,
        generation=cancellation.admission.generation, incarnation=receipt.incarnation,
        runtime_id=cancellation.admission.runtime_id, original_lease=cancellation.original_lease,
        handoff_lease=receipt.session_epoch, tombstone_sha256=cancellation.tombstone_sha256,
        receipt_sha256=hashlib.sha256(receipt.pack()).hexdigest(), acknowledged=True)


def validate_handoff_view(value, actor, request=None):
    from .battle_protocol import _digest
    from .team_protocol import _uuid
    _fields(value, {"scope", "battle_id", "generation", "incarnation", "runtime_id",
        "original_lease", "handoff_lease", "tombstone_sha256", "receipt_sha256", "acknowledged"})
    for key in ("battle_id", "generation", "runtime_id"):
        _uuid(value[key], key)
    _integer(value["incarnation"], 1, 0xFFFFFFFF, "original incarnation")
    _integer(value["original_lease"], 1, MAX_COUNTER, "original admission lease")
    _integer(value["handoff_lease"], value["original_lease"], MAX_COUNTER, "native handoff lease")
    for key in ("tombstone_sha256", "receipt_sha256"):
        _digest(value[key])
        if not any(bytes.fromhex(value[key])):
            raise ProtocolError("invalid_server_message", "handoff digest must be nonzero")
    if value["scope"] != HANDOFF_SCOPE or value["acknowledged"] is not True:
        raise ProtocolError("invalid_server_message", "invalid admission handoff acknowledgment")
    if request is not None:
        from .battle_execution_protocol import decode_control
        receipt = decode_control(request["handoff_receipt_b64"], response=True)
        if (value != handoff_view(receipt) or any(value[key] != request[key] for key in
                ("battle_id", "generation", "incarnation", "runtime_id"))
                or AdmissionCancellation.unpack(receipt.data).admission.player_id != actor):
            raise ProtocolError("identity_mismatch", "handoff acknowledgment changed the original receipt")
    return value
