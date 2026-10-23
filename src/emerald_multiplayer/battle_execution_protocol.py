"""Bounded native execution replies for an already consented battle.

The client reports only the response to the host's one outstanding command.
It cannot request an opcode, alter a roster, seed a battle, or submit an outcome.
"""
import base64

from .native_battle import NativeControl, Opcode
from .protocol import ProtocolError, _fields, _integer
from .team_protocol import _uuid

SCOPE = "native-battle-execution-v1"
STATES = frozenset(("waiting", "admitting", "executing", "closed", "aborted", "recovery_required"))


def encode_control(control):
    return base64.b64encode(control.pack()).decode("ascii")


def decode_control(value, *, response=False):
    try:
        if type(value) is not str or len(value) != 320:
            raise ValueError()
        raw = base64.b64decode(value, validate=True)
        if base64.b64encode(raw).decode("ascii") != value:
            raise ValueError()
        control = NativeControl.unpack(raw)
        return control.validate_response() if response else control.validate_command()
    except ValueError as error:
        raise ProtocolError("invalid_battle_control", "native execution requires one canonical 240-byte control") from error


def validate_execution_request(message):
    _integer(message["incarnation"], "incarnation", 1, 0xFFFFFFFF)
    _integer(message["response_id"], "response_id", 0, 0x7FFFFFFF)
    if (message["response_b64"] is None) != (message["response_id"] == 0):
        raise ProtocolError("invalid_field", "native response and dispatch ID must occur together")
    if message["response_b64"] is not None:
        decode_control(message["response_b64"], response=True)
    admission = message.get("admission_sha256")
    if admission is not None and (type(admission) is not str or len(admission) != 64
            or any(char not in "0123456789abcdef" for char in admission)):
        raise ProtocolError("invalid_field", "native admission requires the exact persisted BIND digest")
    if "admission_b64" in message:
        from .native_battle_resume import Admission
        _uuid(message["runtime_id"], "runtime_id")
        command = decode_control(message["admission_b64"])
        receipt = decode_control(message["admission_receipt_b64"], response=True)
        receipt.validate_response(command)
        if (command.opcode != Opcode.ADMIT or receipt.status or command.sequence != 1
                or command.battle_id != message["battle_id"] or command.incarnation != message["incarnation"]
                or command.session_epoch > message["session_epoch"]
                or Admission.unpack(command.data).runtime_id != message["runtime_id"]):
            raise ProtocolError("invalid_admission", "provisional native proof differs from its original core")


def execution_view(battle_id, generation, state, command=None, command_id=0):
    return dict(scope=SCOPE, battle_id=battle_id, generation=generation,
                state=state, command_id=command_id,
                command_b64=None if command is None else encode_control(command))


def validate_execution_view(value, *, request=None):
    _fields(value, {"scope", "battle_id", "generation", "state", "command_b64", "command_id"})
    _uuid(value["battle_id"], "battle_id"); _uuid(value["generation"], "generation")
    if value["scope"] != SCOPE or type(value["state"]) is not str or value["state"] not in STATES:
        raise ProtocolError("invalid_server_message", "unsupported native execution status")
    command = None
    _integer(value["command_id"], "command_id", 0, 0x7FFFFFFF)
    if (value["command_b64"] is None) != (value["command_id"] == 0):
        raise ProtocolError("invalid_server_message", "native dispatch ID and command must occur together")
    if value["command_b64"] is not None:
        command = decode_control(value["command_b64"])
        if (command.battle_id != value["battle_id"] or value["state"] not in ("admitting", "executing")
                or (value["state"] == "admitting" and command.opcode != 1)):
            raise ProtocolError("identity_mismatch", "native command differs from its execution lifecycle")
    if request is not None:
        if (value["battle_id"], value["generation"]) != (request["battle_id"], request["generation"]):
            raise ProtocolError("identity_mismatch", "native execution changed battle identity")
        if command is not None and (command.incarnation, command.session_epoch) != (
                request["incarnation"], request["session_epoch"]):
            raise ProtocolError("identity_mismatch", "native command changed the authenticated incarnation")
    return value


OBSERVE_SCOPE = "native-battle-observation-v1"


def validate_observation_request(message):
    """KNOWN_ISSUES MS-62: one successful PEEK response of the reporting player's own core."""
    from .native_battle import peek_parts
    _integer(message["incarnation"], "incarnation", 1, 0xFFFFFFFF)
    response = decode_control(message["observation_b64"], response=True)
    try:
        if (response.opcode != Opcode.PEEK or response.status or response.battle_id != message["battle_id"]
                or response.incarnation != message["incarnation"] or response.session_epoch != message["session_epoch"]):
            raise ValueError()
        peek_parts(response)
    except ValueError as error:
        raise ProtocolError("invalid_battle_control", "a battle observation is one exact PEEK response") from error


def validate_observation_view(value, *, request=None):
    _fields(value, {"scope", "battle_id", "generation", "accepted", "routed"})
    _uuid(value["battle_id"], "battle_id"); _uuid(value["generation"], "generation")
    if (value["scope"] != OBSERVE_SCOPE or type(value["accepted"]) is not bool or type(value["routed"]) is not bool
            or (value["accepted"] and not value["routed"])):
        raise ProtocolError("invalid_server_message", "unsupported native observation reply")
    if request is not None and (value["battle_id"], value["generation"]) != (request["battle_id"], request["generation"]):
        raise ProtocolError("identity_mismatch", "native observation changed battle identity")
    return value
