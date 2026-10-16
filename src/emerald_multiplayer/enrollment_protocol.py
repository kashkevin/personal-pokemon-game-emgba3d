"""First-time character enrollment over the world connection (Update 30).

A friend creates a new character on their own PC with the game's ordinary New Game (``draft_runtime``). To make that character the
friend's account in the host's world, its save is sent here, once, and the server records it as the account's approved source
(``OwnershipCheckpointStore.enroll_player``), exactly what the host's own PC does for the host's character. The server decides
everything; the friend's PC only supplies the bytes:

* the sender is the authenticated account of this session (its credential was checked at hello); it can only enroll itself;
* the account must have no canonical character yet, and no different source recorded (a retry of the same source is fine);
* the bytes must be a complete, valid legacy save with no assigned ownership identifiers (``flash.inspect_flash`` and
  ``extract_source_inventory`` run on the server) and must not be the source of another account;
* the world's host can turn this off (``ServerConfig.allow_enrollment``), after which only the host's own PC can enroll.

After this the friend's game bootstraps exactly as in the host-approved flow (``enrollment_runtime``): the first checkpoint must keep
every Pokémon of the source and the server's allocation grants give each one its owner identity.
"""
from __future__ import annotations

import base64
import binascii
import re
from typing import Any
import uuid

from .protocol import MAX_CHECKPOINT_BYTES, MAX_COUNTER, CHECKPOINT_CHUNK_BYTES, ProtocolError, _fields, _integer, _request_uuid

ENROLLMENT_TYPES = frozenset({"enrollment_status", "enrollment_begin", "enrollment_chunk", "enrollment_commit"})
SOURCE_SIZES = (131_072, MAX_CHECKPOINT_BYTES)


def validate_enrollment_common(message: Any, session_epoch: int) -> dict[str, Any]:
    if not isinstance(message, dict) or not isinstance(message.get("type"), str) or message["type"] not in ENROLLMENT_TYPES:
        raise ProtocolError("invalid_type", "unsupported enrollment operation")
    if _integer(message.get("session_epoch"), "session_epoch", 1, MAX_COUNTER) != session_epoch:
        raise ProtocolError("session_epoch_mismatch", "enrollment request belongs to another authenticated lease")
    _request_uuid(message.get("request_id"), "request_id")
    return message


def validate_enrollment_request(message: Any, session_epoch: int) -> dict[str, Any]:
    validate_enrollment_common(message, session_epoch)
    kind = message["type"]
    fingerprint = {"size", "sha256"}
    extras = {
        "enrollment_status": set(),
        "enrollment_begin": fingerprint,
        "enrollment_chunk": {"upload_id", "offset", "data_b64"},
        "enrollment_commit": fingerprint | {"upload_id"},
    }
    _fields(message, {"type", "request_id", "session_epoch"} | extras[kind])
    result = dict(message)
    if "upload_id" in message:
        _request_uuid(message["upload_id"], "upload_id")
    if "offset" in message:
        _integer(message["offset"], "offset", 0, MAX_CHECKPOINT_BYTES)
    if kind in ("enrollment_begin", "enrollment_commit"):
        if type(message["size"]) is not int or message["size"] not in SOURCE_SIZES:
            raise ProtocolError("invalid_checkpoint_size", "an enrollment source is a Flash save with an optional RTC footer")
        if not isinstance(message["sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", message["sha256"]) is None:
            raise ProtocolError("invalid_checkpoint_hash", "enrollment source SHA256 is invalid")
    if kind == "enrollment_chunk":
        encoded = message["data_b64"]
        if not isinstance(encoded, str) or not 1 <= len(encoded) <= 4 * ((CHECKPOINT_CHUNK_BYTES + 2) // 3):
            raise ProtocolError("invalid_checkpoint_chunk", "enrollment chunk exceeds its size limit")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as error:
            raise ProtocolError("invalid_checkpoint_chunk", "enrollment chunk is not valid base64") from error
        if not 1 <= len(data) <= CHECKPOINT_CHUNK_BYTES or base64.b64encode(data).decode("ascii") != encoded:
            raise ProtocolError("invalid_checkpoint_chunk", "enrollment chunk is not canonical bounded base64")
        result["data"] = data
    return result


def new_request_id() -> str:
    return str(uuid.uuid4())


class EnrollmentRemoteError(ValueError):
    """The host refused or failed an enrollment step; ``code`` is the server's stable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
