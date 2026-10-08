"""Bounded native execution replies for an already consented battle.

The client reports only the response to the host's one outstanding command.
It cannot request an opcode, alter a roster, seed a battle, or submit an outcome.
"""
import base64

from .native_battle import NativeControl
from .protocol import ProtocolError, _fields, _integer
from .team_protocol import _uuid

SCOPE = "native-battle-execution-v1"
STATES = frozenset(("waiting", "executing", "closed", "aborted", "recovery_required"))


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
        if command.battle_id != value["battle_id"] or value["state"] != "executing":
            raise ProtocolError("identity_mismatch", "native command differs from its execution lifecycle")
    if request is not None:
        if (value["battle_id"], value["generation"]) != (request["battle_id"], request["generation"]):
            raise ProtocolError("identity_mismatch", "native execution changed battle identity")
        if command is not None and (command.incarnation, command.session_epoch) != (
                request["incarnation"], request["session_epoch"]):
            raise ProtocolError("identity_mismatch", "native command changed the authenticated incarnation")
    return value
