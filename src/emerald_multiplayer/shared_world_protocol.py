"""Wire validation for the protocol-2 shared-world extensions."""
from __future__ import annotations

import re
import uuid
from typing import Any

from .protocol import MAX_COUNTER, ProtocolError

WORLD_TYPES = frozenset({"world_action", "appearance_get", "appearance_set"})
ACTIONS = frozenset({"claim", "result", "release"})
RESULTS = frozenset({"caught", "defeated", "ran", "lost", "cancelled"})
_HEX16 = re.compile(r"[0-9a-f]{16}\Z")
_EVENT_FIELDS = {"event_id", "species", "level", "shiny", "mega", "map_group", "map_number", "x", "y",
                 "held_item", "perfect_ivs", "seconds_left", "claimant"}


def _int(value: Any, name: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ProtocolError("invalid_field", f"{name} is outside its integer bounds")
    return value


def _uuid(value: Any, name: str) -> str:
    try:
        ok = isinstance(value, str) and str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        ok = False
    if not ok:
        raise ProtocolError("invalid_field", f"{name} must be a canonical UUID")
    return value


def validate_clock(value: Any) -> dict:
    if type(value) is not dict or set(value) != {"seconds", "running"} or type(value["running"]) is not bool:
        raise ProtocolError("invalid_server_message", "invalid world clock")
    _int(value["seconds"], "clock seconds", 0, 0xFFFFFFFF)
    return value


def validate_event(value: Any) -> dict | None:
    if value is None:
        return None
    if type(value) is not dict or set(value) != _EVENT_FIELDS:
        raise ProtocolError("invalid_server_message", "invalid world event")
    _int(value["event_id"], "event id", 1, MAX_COUNTER)
    _int(value["species"], "event species", 1, 1700)
    _int(value["level"], "event level", 1, 100)
    _int(value["map_group"], "event map group", 0, 255)
    _int(value["map_number"], "event map number", 0, 255)
    _int(value["x"], "event x", 0, 32767)
    _int(value["y"], "event y", 0, 32767)
    _int(value["held_item"], "event item", 0, 0xFFFF)
    _int(value["perfect_ivs"], "event IVs", 0, 6)
    _int(value["seconds_left"], "event timer", 0, 0xFFFFFFFF)
    if type(value["shiny"]) is not bool or type(value["mega"]) is not bool:
        raise ProtocolError("invalid_server_message", "invalid world event flags")
    if value["claimant"] is not None:
        _uuid(value["claimant"], "event claimant")
    return value


def validate_notice(value: Any) -> dict | None:
    if value is None:
        return None
    if type(value) is not dict or set(value) != {"id", "text", "to"}:
        raise ProtocolError("invalid_server_message", "invalid world notice")
    _int(value["id"], "notice id", 1, MAX_COUNTER)
    text = value["text"]
    if not isinstance(text, str) or len(text) > 64 or any(not 32 <= ord(c) < 127 for c in text):
        raise ProtocolError("invalid_server_message", "invalid world notice text")
    if value["to"] is not None:
        if type(value["to"]) is not list or len(value["to"]) > 4:
            raise ProtocolError("invalid_server_message", "invalid world notice recipients")
        for player in value["to"]:
            _uuid(player, "notice recipient")
    return value


def validate_appearance_hex(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _HEX16.fullmatch(value) is None:
        raise ProtocolError("invalid_server_message", "invalid appearance")
    from .appearance import validate_appearance
    try:
        validate_appearance(bytes.fromhex(value))
    except ValueError as error:
        raise ProtocolError("invalid_server_message", "invalid appearance") from error
    return value


def validate_world_request(message: Any, session_epoch: int) -> dict:
    if not isinstance(message, dict) or message.get("type") not in WORLD_TYPES:
        raise ProtocolError("invalid_type", "unsupported shared-world operation")
    _int(message.get("session_epoch"), "session_epoch", 1, MAX_COUNTER)
    if message["session_epoch"] != session_epoch:
        raise ProtocolError("session_epoch_mismatch", "shared-world session epoch is incompatible")
    _uuid(message.get("request_id"), "request_id")
    kind = message["type"]
    if kind == "world_action":
        expected = {"type", "session_epoch", "request_id", "action", "event_id", "result", "seq"}
        if set(message) != expected:
            raise ProtocolError("invalid_fields", "world action has missing or unexpected fields")
        if message["action"] not in ACTIONS:
            raise ProtocolError("invalid_field", "unsupported world action")
        _int(message["event_id"], "event id", 1, MAX_COUNTER)
        _int(message["seq"], "action seq", 1, 0xFFFFFFFF)
        if message["action"] == "result":
            if message["result"] not in RESULTS:
                raise ProtocolError("invalid_field", "unsupported event result")
        elif message["result"] is not None:
            raise ProtocolError("invalid_field", "only results carry an outcome")
    elif kind == "appearance_get":
        if set(message) != {"type", "session_epoch", "request_id"}:
            raise ProtocolError("invalid_fields", "appearance request has unexpected fields")
    else:
        if set(message) != {"type", "session_epoch", "request_id", "appearance"}:
            raise ProtocolError("invalid_fields", "appearance update has unexpected fields")
        if validate_appearance_hex(message["appearance"]) is None:
            raise ProtocolError("invalid_field", "appearance is required")
    return message


def validate_world_reply(message: Any) -> dict:
    if not isinstance(message, dict) or message.get("type") not in ("world_result", "world_error"):
        raise ProtocolError("invalid_server_message", "unexpected shared-world reply")
    _uuid(message.get("request_id"), "request_id")
    if message["type"] == "world_error":
        if set(message) != {"type", "request_id", "code", "message"}:
            raise ProtocolError("invalid_server_message", "invalid shared-world error")
    elif set(message) != {"type", "request_id", "result"} or type(message["result"]) is not dict:
        raise ProtocolError("invalid_server_message", "invalid shared-world result")
    return message
