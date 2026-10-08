"""Strict development team RPCs, independent of ROM/battle and trade ABIs.

This channel requires an authenticated ownership world. It never accepts actor
identity claims or save contents, and its replies describe session-local teams.
A lost reply requires status reconciliation; a timeout is not acceptance.
"""
from __future__ import annotations

import math
import re
from typing import Any
from uuid import UUID

from .protocol import MAX_COUNTER, PROTOCOL_VERSION, ProtocolError, _fields, _integer

TEAM_OPERATIONS = frozenset({"invite", "accept", "decline", "cancel", "leave", "status"})
TEAM_TYPES = frozenset("team_" + operation for operation in TEAM_OPERATIONS)
SCOPE = "session-local-development"
_CODE = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")


def _uuid(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 36:
        raise ProtocolError("invalid_field", f"{field} must be a nonzero canonical UUID")
    try:
        parsed = UUID(value)
        valid = str(parsed) == value and parsed.int != 0
    except ValueError:
        valid = False
    if not valid:
        raise ProtocolError("invalid_field", f"{field} must be a nonzero canonical UUID")
    return value


def validate_team_common(message: Any, session_epoch: int) -> dict[str, Any]:
    """Only trustworthy correlation fields may receive a recoverable body error."""
    if (not isinstance(message, dict) or not isinstance(message.get("type"), str)
            or message["type"] not in TEAM_TYPES):
        raise ProtocolError("invalid_type", "unsupported team operation")
    epoch = _integer(message.get("session_epoch"), "session_epoch", 1, MAX_COUNTER)
    if epoch != session_epoch:
        raise ProtocolError("session_epoch_mismatch", "team request belongs to another authenticated lease")
    _uuid(message.get("request_id"), "request_id")
    return message


def validate_team_request(message: Any, session_epoch: int) -> dict[str, Any]:
    validate_team_common(message, session_epoch)
    operation = message["type"].removeprefix("team_")
    extra = {
        "invite": {"peer", "invitation_id"},
        "accept": {"invitation_id", "generation"},
        "decline": {"invitation_id", "generation"},
        "cancel": {"invitation_id", "generation"},
        "leave": {"team_id", "generation"},
        "status": set(),
    }[operation]
    _fields(message, {"type", "request_id", "session_epoch"} | extra)
    for field in extra:
        _uuid(message[field], field)
    return dict(message)


def _formed(value: Any) -> None:
    _fields(value, {"state", "team_id", "generation", "members",
                    "invitation_id", "invitation_generation"})
    if value["state"] != "formed":
        raise ProtocolError("invalid_server_message", "invalid formed team state")
    for field in ("team_id", "generation", "invitation_id", "invitation_generation"):
        _uuid(value[field], field)
    members = value["members"]
    if not isinstance(members, list) or len(members) != 2:
        raise ProtocolError("invalid_server_message", "a team requires exactly two players")
    for player in members:
        _uuid(player, "member")
    if members[0] == members[1]:
        raise ProtocolError("invalid_server_message", "a player cannot occupy both team places")


def _invitation(value: Any) -> None:
    _fields(value, {"state", "invitation_id", "generation", "sender", "recipient", "expires_in"})
    if value["state"] != "invited":
        raise ProtocolError("invalid_server_message", "invalid invitation state")
    for field in ("invitation_id", "generation", "sender", "recipient"):
        _uuid(value[field], field)
    if value["sender"] == value["recipient"]:
        raise ProtocolError("invalid_server_message", "invitation requires different players")
    duration = value["expires_in"]
    if (type(duration) not in (int, float) or not 0 <= duration <= 3600
            or not math.isfinite(duration)):
        raise ProtocolError("invalid_server_message", "invitation duration is outside its bounds")


def _status(value: Any, actor: str) -> None:
    _fields(value, {"scope", "team", "teams", "invitations"})
    if value["scope"] != SCOPE:
        raise ProtocolError("invalid_server_message", "team persistence scope is unsupported")
    teams, invitations = value["teams"], value["invitations"]
    if not isinstance(teams, list) or len(teams) > 2:
        raise ProtocolError("invalid_server_message", "more than two teams were returned")
    players, ids, invitation_ids = set(), set(), set()
    for team in teams:
        _formed(team)
        if (players.intersection(team["members"]) or team["team_id"] in ids
                or team["invitation_id"] in invitation_ids):
            raise ProtocolError("invalid_server_message", "teams overlap or repeat identities")
        players.update(team["members"])
        ids.add(team["team_id"])
        invitation_ids.add(team["invitation_id"])
    own = [team for team in teams if actor in team["members"]]
    if value["team"] != (own[0] if own else None):
        raise ProtocolError("identity_mismatch", "own membership differs from the returned roster")
    if not isinstance(invitations, list) or len(invitations) > 1:
        raise ProtocolError("invalid_server_message", "pending invitation exceeds its per-player bound")
    for invitation in invitations:
        _invitation(invitation)
        if (actor not in (invitation["sender"], invitation["recipient"])
                or players.intersection((invitation["sender"], invitation["recipient"]))):
            raise ProtocolError("identity_mismatch", "invitation is foreign or involves a formed teammate")


def _result(value: Any, operation: str, actor: str) -> None:
    if not isinstance(value, dict):
        raise ProtocolError("invalid_server_message", "invalid team operation result")
    if operation == "status":
        _status(value, actor)
    elif operation == "invite" and value.get("state") == "invited":
        _invitation(value)
        if value["sender"] != actor:
            raise ProtocolError("identity_mismatch", "invitation was sent by another player")
    elif operation in ("invite", "accept"):
        _formed(value)
        member_index = 0 if operation == "invite" else 1
        if value["members"][member_index] != actor:
            raise ProtocolError("identity_mismatch", "formed team does not identify this operation's actor")
    else:
        field = "team_id" if operation == "leave" else "invitation_id"
        _fields(value, {"state", field})
        if value["state"] != {"decline": "declined", "cancel": "canceled", "leave": "left"}[operation]:
            raise ProtocolError("invalid_server_message", "team state is incompatible with the operation")
        _uuid(value[field], field)


def validate_team_reply(message: Any, actor: str, world_id: str, epoch: int,
                        request: dict[str, Any] | None = None) -> dict[str, Any]:
    common = {"type", "protocol", "session_epoch", "request_id", "operation", "world_id", "player_id"}
    if (not isinstance(message, dict) or not common <= set(message)
            or type(message["protocol"]) is not int or message["protocol"] != PROTOCOL_VERSION):
        raise ProtocolError("invalid_server_message", "invalid team reply envelope")
    _integer(message["session_epoch"], "session_epoch", 1, MAX_COUNTER)
    _uuid(message["request_id"], "request_id")
    _uuid(message["world_id"], "world_id")
    _uuid(message["player_id"], "player_id")
    if (message["session_epoch"], message["world_id"], message["player_id"]) != (epoch, world_id, actor):
        raise ProtocolError("identity_mismatch", "team reply belongs to another world, player or lease")
    operation = message["operation"]
    if not isinstance(operation, str) or operation not in TEAM_OPERATIONS:
        raise ProtocolError("invalid_server_message", "unsupported team reply operation")
    if message["type"] == "team_error":
        _fields(message, common | {"code", "message"})
        if (not isinstance(message["code"], str) or _CODE.fullmatch(message["code"]) is None
                or not isinstance(message["message"], str) or not 1 <= len(message["message"]) <= 512
                or not message["message"].isprintable()):
            raise ProtocolError("invalid_server_message", "invalid team error text")
    elif message["type"] == "team_result":
        _fields(message, common | {"result"})
        _result(message["result"], operation, actor)
    else:
        raise ProtocolError("invalid_server_message", "unexpected team reply type")
    if request is not None:
        validate_team_request(request, epoch)
        if (message["request_id"] != request["request_id"]
                or operation != request["type"].removeprefix("team_")):
            raise ProtocolError("invalid_server_message", "team reply does not match its request")
        if message["type"] == "team_result":
            result = message["result"]
            for field in ("invitation_id", "team_id"):
                if field in request and result.get(field) != request[field]:
                    raise ProtocolError("invalid_server_message", "team reply refers to another operation target")
            if operation == "invite":
                participants = ([result["sender"], result["recipient"]]
                                if result["state"] == "invited" else result["members"])
                if participants != [actor, request["peer"]]:
                    raise ProtocolError("identity_mismatch", "team invitation reply changed the participants")
            if operation == "accept" and result["invitation_generation"] != request["generation"]:
                raise ProtocolError("invalid_server_message", "accepted team belongs to another invitation generation")
    return message
