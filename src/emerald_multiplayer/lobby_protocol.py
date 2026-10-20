"""Strict battle lobby RPCs (Update 32, feature 10; battle_lobby.py).

Like the team channel (team_protocol.py): an authenticated ownership world, no actor claims or save contents in a
request, replies that describe session-local lobbies. A lost reply needs a status read; a timeout is not an answer.
"""
from __future__ import annotations

import math
import re
from typing import Any

from .battle_lobby import FORMATS, SCOPE
from .protocol import MAX_COUNTER, PROTOCOL_VERSION, ProtocolError, _fields, _integer
from .team_protocol import _uuid

LOBBY_OPERATIONS = frozenset({"create", "join", "decline", "leave", "start", "status"})
LOBBY_TYPES = frozenset("lobby_" + operation for operation in LOBBY_OPERATIONS)
STATES = frozenset({"open", "started", "ended"})
REASONS = frozenset({None, "cancelled", "creator_left", "timed_out", "nobody_joined"})
_CODE = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_ALL_FORMATS = frozenset(f for formats in FORMATS.values() for f in formats)


def validate_lobby_common(message: Any, session_epoch: int) -> dict[str, Any]:
    if (not isinstance(message, dict) or not isinstance(message.get("type"), str)
            or message["type"] not in LOBBY_TYPES):
        raise ProtocolError("invalid_type", "unsupported lobby operation")
    if _integer(message.get("session_epoch"), "session_epoch", 1, MAX_COUNTER) != session_epoch:
        raise ProtocolError("session_epoch_mismatch", "lobby request belongs to another authenticated lease")
    _uuid(message.get("request_id"), "request_id")
    return message


def validate_lobby_request(message: Any, session_epoch: int) -> dict[str, Any]:
    validate_lobby_common(message, session_epoch)
    operation = message["type"].removeprefix("lobby_")
    extra = {
        "create": {"lobby_id", "invitees"},
        "join": {"lobby_id", "generation"},
        "decline": {"lobby_id", "generation"},
        "leave": {"lobby_id", "generation"},
        "start": {"lobby_id", "generation", "battle_id"},
        "status": set(),
    }[operation]
    _fields(message, {"type", "request_id", "session_epoch"} | extra)
    for key in extra - {"invitees"}:
        _uuid(message[key], key)
    if operation == "create":
        invitees = message["invitees"]
        if type(invitees) is not list or not 1 <= len(invitees) <= 3:
            raise ProtocolError("invalid_field", "a lobby invites one to three other trainers")
        for player in invitees:
            _uuid(player, "invitee")
        if len(set(invitees)) != len(invitees):
            raise ProtocolError("invalid_field", "lobby invitees must be distinct")
    return dict(message)


def _players(value, name, bound=4):
    if type(value) is not list or len(value) > bound:
        raise ProtocolError("invalid_server_message", f"invalid lobby {name}")
    for player in value:
        _uuid(player, name)
    if len(set(value)) != len(value):
        raise ProtocolError("invalid_server_message", f"repeated lobby {name}")
    return value


def validate_lobby_view(value: Any, actor: str) -> dict[str, Any]:
    _fields(value, {"scope", "lobby_id", "generation", "creator", "invited", "joined", "declined", "left", "state",
                    "reason", "formats", "format", "battle_id", "expires_in"})
    if value["scope"] != SCOPE or value["state"] not in STATES or value["reason"] not in REASONS:
        raise ProtocolError("invalid_server_message", "invalid lobby state")
    for key in ("lobby_id", "generation", "creator"):
        _uuid(value[key], key)
    invited = _players(value["invited"], "invitee", 3)
    if not invited or value["creator"] in invited:
        raise ProtocolError("invalid_server_message", "a lobby invites one to three other trainers")
    members = {value["creator"], *invited}
    joined, declined, left = (_players(value[k], k) for k in ("joined", "declined", "left"))
    if (not set(joined) <= members or not set(declined) <= set(invited) or not set(left) <= set(invited)
            or set(joined) & set(declined) or actor not in members):
        raise ProtocolError("identity_mismatch", "lobby members are foreign or answer twice")
    formats = value["formats"]
    if (type(formats) is not list or any(f not in _ALL_FORMATS for f in formats)
            or (value["state"] == "open" and formats != list(FORMATS.get(len(joined), ())))):
        raise ProtocolError("invalid_server_message", "lobby formats disagree with its joined trainers")
    if value["state"] == "started":
        _uuid(value["battle_id"], "battle_id")
        if value["format"] not in _ALL_FORMATS:
            raise ProtocolError("invalid_server_message", "a started lobby names its format")
    elif value["battle_id"] is not None or value["format"] is not None:
        raise ProtocolError("invalid_server_message", "only a started lobby has a battle")
    remaining = value["expires_in"]
    if type(remaining) not in (int, float) or not 0 <= remaining <= 3600 or not math.isfinite(remaining):
        raise ProtocolError("invalid_server_message", "lobby deadline is outside its bounds")
    return value


def validate_lobby_reply(message: Any, actor: str, world_id: str, epoch: int,
                         request: dict[str, Any] | None = None) -> dict[str, Any]:
    common = {"type", "protocol", "session_epoch", "request_id", "operation", "world_id", "player_id"}
    if (not isinstance(message, dict) or not common <= set(message)
            or type(message["protocol"]) is not int or message["protocol"] != PROTOCOL_VERSION):
        raise ProtocolError("invalid_server_message", "invalid lobby reply envelope")
    _integer(message["session_epoch"], "session_epoch", 1, MAX_COUNTER)
    for key in ("request_id", "world_id", "player_id"):
        _uuid(message[key], key)
    if (message["session_epoch"], message["world_id"], message["player_id"]) != (epoch, world_id, actor):
        raise ProtocolError("identity_mismatch", "lobby reply belongs to another world, player or lease")
    operation = message["operation"]
    if not isinstance(operation, str) or operation not in LOBBY_OPERATIONS:
        raise ProtocolError("invalid_server_message", "unsupported lobby reply operation")
    if message["type"] == "lobby_error":
        _fields(message, common | {"code", "message"})
        if (not isinstance(message["code"], str) or _CODE.fullmatch(message["code"]) is None
                or not isinstance(message["message"], str) or not 1 <= len(message["message"]) <= 512
                or not message["message"].isprintable()):
            raise ProtocolError("invalid_server_message", "invalid lobby error text")
    elif message["type"] == "lobby_result":
        _fields(message, common | {"result"})
        result = message["result"]
        if operation == "status":
            _fields(result, {"scope", "lobbies"})
            if result["scope"] != SCOPE or type(result["lobbies"]) is not list or len(result["lobbies"]) > 4:
                raise ProtocolError("invalid_server_message", "invalid lobby status")
            for view in result["lobbies"]:
                validate_lobby_view(view, actor)
        else:
            validate_lobby_view(result, actor)
    else:
        raise ProtocolError("invalid_server_message", "unexpected lobby reply type")
    if request is not None:
        validate_lobby_request(request, epoch)
        if message["request_id"] != request["request_id"] or operation != request["type"].removeprefix("lobby_"):
            raise ProtocolError("invalid_server_message", "lobby reply does not match its request")
        if message["type"] == "lobby_result" and operation != "status":
            result = message["result"]
            if result["lobby_id"] != request["lobby_id"]:
                raise ProtocolError("invalid_server_message", "lobby reply refers to another lobby")
            if operation == "create" and (result["creator"] != actor or result["invited"] != request["invitees"]):
                raise ProtocolError("identity_mismatch", "lobby reply changed its trainers")
            if operation == "start" and result["battle_id"] != request["battle_id"]:
                raise ProtocolError("invalid_server_message", "lobby started another battle")
    return message
