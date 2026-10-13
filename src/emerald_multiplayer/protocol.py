"""Bounded, length-prefixed JSON protocol shared by server and companion."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import math
import re
import struct
import uuid
from typing import Any

# Version 2 adds shared-world presence (followers, mounts), appearance,
# the world clock, World Events and notices. Version 3 adds host-authoritative
# shared wild Pokemon (the "spawns" world field, the "spawn_action" request and
# the presence "weather"). Mixed versions refuse cleanly.
PROTOCOL_VERSION = 3
MAX_FRAME_BYTES = 16_384
MAX_PLAYERS = 4
MAX_COUNTER = 2_147_483_647
MAX_CHECKPOINT_BYTES = 131_088
CHECKPOINT_CHUNK_BYTES = 4096
CHECKPOINT_TYPES = frozenset({
    "checkpoint_info", "checkpoint_read", "checkpoint_begin",
    "checkpoint_chunk", "checkpoint_commit", "checkpoint_abort",
    "ownership_grant",
})
ACTIVITIES = frozenset({"overworld", "menu", "battle", "transition", "unavailable"})
MOVEMENT_MODES = frozenset({"walk", "run", "bike", "surf"})
WORLD_PRESENCE_FIELDS = frozenset({"follower_species", "follower_flags", "mount_state", "mount_species", "mount_flags",
                                   "wallet_seq", "weather"})
_IDENTITY = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")


class ProtocolError(ValueError):
    """A protocol failure with a stable code and safe explanatory text."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def validate_identity(value: Any, field: str) -> str:
    if not isinstance(value, str) or _IDENTITY.fullmatch(value) is None:
        raise ProtocolError("invalid_identity", f"{field} must be a bounded identifier")
    return value


def _integer(value: Any, field: str, minimum: int, maximum: int) -> int:
    # bool is an int subclass, but is never a valid wire counter or coordinate.
    if type(value) is not int or not minimum <= value <= maximum:
        raise ProtocolError("invalid_field", f"{field} is outside its integer bounds")
    return value


def _fields(message: Any, required: set[str], optional: set[str] | None = None) -> None:
    if not isinstance(message, dict):
        raise ProtocolError("invalid_message", "message must be a JSON object")
    names = set(message)
    if not required <= names or names - required - (optional or set()):
        raise ProtocolError("invalid_fields", "message has missing or unexpected fields")


def _version(value: Any) -> None:
    if type(value) is not int or value != PROTOCOL_VERSION:
        raise ProtocolError("unsupported_protocol", "protocol version is incompatible")


def validate_hello(message: dict[str, Any], build_id: str, ruleset_id: str, *, require_credential: bool = False) -> dict[str, Any]:
    _fields(message, {"type", "protocol", "build_id", "ruleset_id", "player_id", "display_name"}, {"credential"})
    if message["type"] != "hello":
        raise ProtocolError("hello_required", "the first message must be hello")
    _version(message["protocol"])
    if validate_identity(message["build_id"], "build_id") != build_id:
        raise ProtocolError("build_mismatch", "game build is incompatible")
    if validate_identity(message["ruleset_id"], "ruleset_id") != ruleset_id:
        raise ProtocolError("ruleset_mismatch", "game ruleset is incompatible")
    player_id = message["player_id"]
    try:
        valid_uuid = isinstance(player_id, str) and str(uuid.UUID(player_id)) == player_id
    except (ValueError, AttributeError):
        valid_uuid = False
    if not valid_uuid:
        raise ProtocolError("invalid_player_id", "player_id must be a canonical UUID")
    name = message["display_name"]
    if not isinstance(name, str) or not 1 <= len(name) <= 24 or not name.strip() or not name.isprintable():
        raise ProtocolError("invalid_display_name", "display_name must contain 1 to 24 printable characters")
    if require_credential and "credential" not in message:
        raise ProtocolError("credentials_required", "this world requires a server-issued player credential")
    if "credential" in message and (not isinstance(message["credential"], str) or re.fullmatch(r"[0-9a-f]{64}", message["credential"]) is None):
        raise ProtocolError("credentials_invalid", "credential must be a 32-byte lower-case hex value")
    return dict(message)


def validate_checkpoint_common(message: dict[str, Any], session_epoch: int) -> dict[str, Any]:
    """Validate correlation/lease fields before a recoverable RPC body error."""
    if not isinstance(message, dict) or not isinstance(message.get("type"), str) or message["type"] not in CHECKPOINT_TYPES:
        raise ProtocolError("invalid_type", "unsupported checkpoint operation")
    epoch = _integer(message.get("session_epoch"), "session_epoch", 1, MAX_COUNTER)
    if epoch != session_epoch:
        raise ProtocolError("session_epoch_mismatch", "checkpoint session epoch is incompatible")
    _request_uuid(message.get("request_id"), "request_id")
    return message


def _request_uuid(value: Any, name: str) -> str:
    try:
        valid = isinstance(value, str) and str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        valid = False
    if not valid:
        raise ProtocolError("invalid_request_id", f"{name} must be a canonical UUID")
    return value


def validate_checkpoint_request(message: dict[str, Any], session_epoch: int) -> dict[str, Any]:
    """Validate a bounded checkpoint RPC; chunk returns local-only data bytes.

    Request IDs correlate replies. The begin request ID is also the stable
    upload ID used by the store's exactly-once-effect commit/retry logic.
    """
    validate_checkpoint_common(message, session_epoch)
    kind = message["type"]
    common = {"type", "request_id", "session_epoch"}
    fingerprint = {"expected_revision", "size", "sha256", "save_profile"}
    extras = {
        "checkpoint_info": set(),
        "checkpoint_read": {"expected_revision", "offset", "length"},
        "checkpoint_begin": fingerprint,
        "checkpoint_chunk": {"upload_id", "offset", "data_b64"},
        "checkpoint_commit": fingerprint | {"upload_id"},
        "checkpoint_abort": {"upload_id"},
        "ownership_grant": {"expected_revision", "incarnation", "count"},
    }
    _fields(message, common | extras[kind])
    result = dict(message)
    if "expected_revision" in message:
        _integer(message["expected_revision"], "expected_revision", 1 if kind == "checkpoint_read" else 0, MAX_COUNTER)
    if "upload_id" in message:
        _request_uuid(message["upload_id"], "upload_id")
    if "offset" in message:
        _integer(message["offset"], "offset", 0, MAX_CHECKPOINT_BYTES)
    if kind == "checkpoint_read":
        _integer(message["length"], "length", 1, CHECKPOINT_CHUNK_BYTES)
    if kind == "ownership_grant":
        _integer(message["incarnation"], "incarnation", 1, 0xFFFFFFFF)
        _integer(message["count"], "count", 1, 432)
    if kind in ("checkpoint_begin", "checkpoint_commit"):
        if type(message["size"]) is not int or message["size"] not in (131_072, MAX_CHECKPOINT_BYTES):
            raise ProtocolError("invalid_checkpoint_size", "checkpoint must be Flash with an optional mGBA RTC footer")
        if not isinstance(message["sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", message["sha256"]) is None:
            raise ProtocolError("invalid_checkpoint_hash", "checkpoint SHA256 is invalid")
        validate_identity(message["save_profile"], "save_profile")
    if kind == "checkpoint_chunk":
        encoded = message["data_b64"]
        if not isinstance(encoded, str) or not 1 <= len(encoded) <= 4 * ((CHECKPOINT_CHUNK_BYTES + 2) // 3):
            raise ProtocolError("invalid_checkpoint_chunk", "checkpoint chunk exceeds its size limit")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as error:
            raise ProtocolError("invalid_checkpoint_chunk", "checkpoint chunk is not valid base64") from error
        if not 1 <= len(data) <= CHECKPOINT_CHUNK_BYTES or base64.b64encode(data).decode("ascii") != encoded:
            raise ProtocolError("invalid_checkpoint_chunk", "checkpoint chunk is not canonical bounded base64")
        result["data"] = data
    return result


def validate_presence(message: dict[str, Any], session_epoch: int) -> dict[str, Any]:
    required = {
        "type", "session_epoch", "seq", "map_epoch", "map_group", "map_number",
        "x", "y", "direction", "elevation", "avatar_gender", "activity",
    }
    _fields(message, required, {"movement_mode"} | WORLD_PRESENCE_FIELDS)
    if message["type"] != "presence":
        raise ProtocolError("invalid_type", "expected a presence message")
    epoch = _integer(message["session_epoch"], "session_epoch", 1, MAX_COUNTER)
    if epoch != session_epoch:
        raise ProtocolError("session_epoch_mismatch", "session epoch is incompatible")
    result = {
        "session_epoch": epoch,
        "seq": _integer(message["seq"], "seq", 0, MAX_COUNTER),
        "map_epoch": _integer(message["map_epoch"], "map_epoch", 0, MAX_COUNTER),
        "map_group": _integer(message["map_group"], "map_group", 0, 255),
        "map_number": _integer(message["map_number"], "map_number", 0, 255),
        "x": _integer(message["x"], "x", -32768, 32767),
        "y": _integer(message["y"], "y", -32768, 32767),
        "direction": _integer(message["direction"], "direction", 1, 4),
        "elevation": _integer(message["elevation"], "elevation", 0, 15),
        "avatar_gender": _integer(message["avatar_gender"], "avatar_gender", 0, 1),
        "activity": message["activity"],
        "movement_mode": message.get("movement_mode", "walk"),
    }
    if not isinstance(result["activity"], str) or result["activity"] not in ACTIVITIES:
        raise ProtocolError("invalid_field", "activity is unsupported")
    if not isinstance(result["movement_mode"], str) or result["movement_mode"] not in MOVEMENT_MODES:
        raise ProtocolError("invalid_field", "movement_mode is unsupported")
    for name, high in (("follower_species", 1700), ("follower_flags", 7), ("mount_state", 1),
                       ("mount_species", 1700), ("mount_flags", 3), ("wallet_seq", 255)):
        result[name] = _integer(message.get(name, 0), name, 0, high)
    # The overworld weather the game shows (shared spawns weigh species by it).
    if "weather" in message:
        result["weather"] = _integer(message["weather"], "weather", 0, 255)
    return result


def validate_heartbeat(message: dict[str, Any], session_epoch: int) -> dict[str, Any]:
    _fields(message, {"type", "protocol", "session_epoch", "nonce"})
    if message["type"] not in ("ping", "pong"):
        raise ProtocolError("invalid_type", "expected a heartbeat message")
    _version(message["protocol"])
    epoch = _integer(message["session_epoch"], "session_epoch", 1, MAX_COUNTER)
    if epoch != session_epoch:
        raise ProtocolError("session_epoch_mismatch", "session epoch is incompatible")
    _integer(message["nonce"], "nonce", 0, MAX_COUNTER)
    return dict(message)


def encode_message(message: dict[str, Any]) -> bytes:
    if not isinstance(message, dict):
        raise ProtocolError("invalid_message", "message must be a JSON object")
    try:
        payload = json.dumps(message, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise ProtocolError("invalid_json", "message cannot be encoded as JSON") from error
    if not 1 <= len(payload) <= MAX_FRAME_BYTES:
        raise ProtocolError("frame_too_large", "JSON frame exceeds its size limit")
    return struct.pack("!I", len(payload)) + payload


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError("invalid_json", "duplicate JSON object keys are forbidden")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ProtocolError("invalid_json", "non-finite JSON numbers are forbidden")


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ProtocolError("invalid_json", "non-finite JSON numbers are forbidden")
    return parsed


async def read_message(reader: asyncio.StreamReader) -> dict[str, Any] | None:
    """Read one complete frame, returning None only on clean frame-boundary EOF."""
    try:
        header = await reader.readexactly(4)
    except asyncio.IncompleteReadError as error:
        if not error.partial:
            return None
        raise ProtocolError("truncated_frame", "connection ended during the frame header") from error
    size = struct.unpack("!I", header)[0]
    if not 1 <= size <= MAX_FRAME_BYTES:
        raise ProtocolError("frame_too_large", "frame length is outside its size limit")
    try:
        payload = await reader.readexactly(size)
    except asyncio.IncompleteReadError as error:
        raise ProtocolError("truncated_frame", "connection ended during the frame payload") from error
    try:
        message = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_invalid_constant, parse_float=_finite_float)
    except (ValueError, UnicodeError, RecursionError) as error:
        if isinstance(error, ProtocolError):
            raise
        raise ProtocolError("invalid_json", "frame is not valid UTF-8 JSON") from error
    if not isinstance(message, dict):
        raise ProtocolError("invalid_message", "message must be a JSON object")
    return message
