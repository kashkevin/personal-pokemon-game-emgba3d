"""Bounded ownership allocation RPC validation; no creature or trade payloads."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from .protocol import MAX_COUNTER, PROTOCOL_VERSION, ProtocolError

OWNERSHIP_PROFILE = "rhh-1.17.1-bb1093-ownership-v1"
MAX_SERIAL = 0xFFFFF
MAX_OWNED_RECORDS = 432


def _uuid(value: Any) -> bool:
    try:
        return isinstance(value, str) and str(UUID(value)) == value and UUID(value).int != 0
    except (ValueError, AttributeError, TypeError):
        return False


def _integer(value: Any, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def validate_ownership_reply(message: Any, config, profile: str, world_id: str, epoch: int) -> dict[str, Any]:
    common = {"type", "protocol", "session_epoch", "request_id", "operation"}
    if (not isinstance(message, dict) or not common <= set(message)
            or type(message["protocol"]) is not int or message["protocol"] != PROTOCOL_VERSION
            or message["operation"] != "ownership_grant" or not _uuid(message["request_id"])):
        raise ProtocolError("invalid_server_message", "invalid ownership reply envelope")
    if not _integer(message["session_epoch"], 1, MAX_COUNTER) or message["session_epoch"] != epoch:
        raise ProtocolError("session_epoch_mismatch", "ownership reply belongs to another lease")
    if profile != OWNERSHIP_PROFILE or not _uuid(world_id):
        raise ProtocolError("identity_mismatch", "ownership profile or world is incompatible")
    if message["type"] == "checkpoint_error":
        if (set(message) != common | {"code", "message"}
                or not isinstance(message["code"], str) or not 1 <= len(message["code"]) <= 128
                or not isinstance(message["message"], str) or not 1 <= len(message["message"]) <= 512):
            raise ProtocolError("invalid_server_message", "invalid ownership error reply")
        return message
    if set(message) != common | {"checkpoint", "grant"} or message["type"] != "checkpoint_result" or message["checkpoint"] is not None:
        raise ProtocolError("invalid_server_message", "invalid ownership result fields")
    grant = message["grant"]
    fields = {"world_id", "player_id", "grant_id", "start", "end_exclusive", "lease_epoch", "incarnation", "expected_revision"}
    if (not isinstance(grant, dict) or set(grant) != fields
            or not all(_uuid(grant[key]) for key in ("world_id", "player_id", "grant_id"))
            or (grant["world_id"], grant["player_id"]) != (world_id, config.player_id)
            or not _integer(grant["lease_epoch"], 1, MAX_COUNTER) or grant["lease_epoch"] != epoch
            or not _integer(grant["incarnation"], 1, 0xFFFFFFFF)
            or not _integer(grant["expected_revision"], 0, MAX_COUNTER)
            or not _integer(grant["start"], 1, MAX_SERIAL)
            or not _integer(grant["end_exclusive"], 2, MAX_SERIAL + 1)
            or not 1 <= grant["end_exclusive"] - grant["start"] <= MAX_OWNED_RECORDS):
        raise ProtocolError("identity_mismatch", "invalid ownership grant identity or bounds")
    return message
