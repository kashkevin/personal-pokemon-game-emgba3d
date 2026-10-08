"""Authenticated original-core recovery exchange with distinct dispatch stages."""
from .battle_execution_protocol import decode_control, execution_view, validate_execution_request, validate_execution_view
from .native_battle import Opcode
from .native_battle_resume import Retirement
from .protocol import ProtocolError, _fields

SCOPE = "native-battle-recovery-v1"
STAGES = ("recovery", "route", "terminal", "admission")


def validate_recovery_request(message):
    validate_execution_request(message)
    if ((message["response_b64"] is None) != (message["response_stage"] is None)
            or (message["response_stage"] is not None and message["response_stage"] not in STAGES)):
        raise ProtocolError("invalid_field", "recovery receipt requires its exact dispatch stage")


def recovery_view(battle_id, generation, state, stage="recovery", command=None, command_id=0):
    result = execution_view(battle_id, generation, state, command, command_id)
    return {**result, "scope": SCOPE, "stage": stage}


def validate_recovery_view(value, request=None):
    fields = {"scope", "battle_id", "generation", "state", "stage", "command_b64", "command_id"}
    if value.get("stage") == "terminal":
        fields.add("terminal")
    if value.get("stage") == "admission":
        fields.add("admission")
    _fields(value, fields)
    if (value["scope"] != SCOPE or value["stage"] not in STAGES
            or value["state"] not in ("waiting", "admitting", "executing", "closed", "recovery_required")):
        raise ProtocolError("invalid_server_message", "unsupported original-core recovery stage")
    validate_execution_view({key: item for key, item in {**value, "scope": "native-battle-execution-v1"}.items()
                             if key not in ("stage", "terminal", "admission")}, request=request)
    if value["stage"] == "admission":
        if value["state"] != "admitting" or value["command_b64"] is not None:
            raise ProtocolError("invalid_server_message", "provisional conversion requires an undispatched BIND")
        admission = value["admission"]
        _fields(admission, {"bind_b64", "original_server_epoch"})
        from .protocol import _integer, MAX_COUNTER
        from .native_battle import NativeBinding
        _integer(admission["original_server_epoch"], "original_server_epoch", 1, MAX_COUNTER)
        bind = decode_control(admission["bind_b64"])
        binding = NativeBinding.unpack(bind.data)
        if (bind.opcode != Opcode.BIND or not binding.resumable or bind.battle_id != value["battle_id"]
                or binding.generation != value["generation"]):
            raise ProtocolError("identity_mismatch", "provisional conversion changed the original battle")
        if request is not None and (bind.incarnation != request["incarnation"]
                or bind.session_epoch > request["session_epoch"]):
            raise ProtocolError("identity_mismatch", "provisional conversion changed the original native core")
    if value["stage"] == "terminal":
        if value["state"] != "closed" or value["command_b64"] is not None:
            raise ProtocolError("invalid_server_message", "terminal recovery requires durable global closure")
        terminal = value["terminal"]
        _fields(terminal, {"release_b64", "receipt_b64", "retire_b64"})
        release = decode_control(terminal["release_b64"])
        receipt = decode_control(terminal["receipt_b64"], response=True)
        retire = decode_control(terminal["retire_b64"])
        receipt.validate_response(release)
        retired = Retirement.unpack(retire.data)
        if (release.opcode != Opcode.RELEASE or retire.opcode != Opcode.RETIRE or receipt.status
                or release.battle_id != value["battle_id"] or retire.battle_id != value["battle_id"]
                or retired.generation != value["generation"] or retired.release_sequence != release.sequence
                or retire.data[20:] != release.data
                or (retire.incarnation, retire.source_slot, retire.phase) !=
                   (release.incarnation, release.source_slot, release.phase)
                or retire.session_epoch < release.session_epoch):
            raise ProtocolError("identity_mismatch", "terminal recovery changed its proven original release")
        if request is not None and (retire.incarnation, retire.session_epoch) != (
                request["incarnation"], request["session_epoch"]):
            raise ProtocolError("identity_mismatch", "terminal retirement changed current authentication")
    return value
