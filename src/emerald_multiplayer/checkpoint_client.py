"""Bounded checkpoint transfers sharing the companion's heartbeat connection.

This module transfers ordinary, closed-game saves. It never reads or writes
emulator RAM and never applies a downloaded save to a running game.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
from contextlib import aclosing
from dataclasses import dataclass
import hashlib
import re
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from .protocol import MAX_COUNTER, PROTOCOL_VERSION, ProtocolError, CHECKPOINT_CHUNK_BYTES

# Chunk requests in flight at once (Companion.checkpoint_pipeline; the companion allows eight checkpoint requests
# pending). Over the internet a whole save used to cost 33 round trips, one a chunk (the owner's report of 2026-10-23:
# trading and saving over the internet were slow), now about nine.
TRANSFER_WINDOW = 4

if TYPE_CHECKING:
    from .companion import Companion, CompanionConfig


class CheckpointError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _uuid(value: Any) -> bool:
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


def _int(value: Any, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def validate_metadata(value: Any, config: CompanionConfig, profile: str) -> dict[str, Any] | None:
    if value is None:
        return None
    fields = {"revision", "request_id", "size", "sha256", "build_id", "ruleset_id", "save_profile"}
    if not isinstance(value, dict) or set(value) != fields or not _int(value["revision"], 1, MAX_COUNTER) or not _uuid(value["request_id"]):
        raise ProtocolError("invalid_server_message", "invalid checkpoint metadata")
    if type(value["size"]) is not int or value["size"] not in (131072, 131088) or not isinstance(value["sha256"], str) or re.fullmatch("[0-9a-f]{64}", value["sha256"]) is None:
        raise ProtocolError("invalid_server_message", "invalid checkpoint size or hash")
    if (value["build_id"], value["ruleset_id"], value["save_profile"]) != (config.build_id, config.ruleset_id, profile):
        raise ProtocolError("identity_mismatch", "checkpoint belongs to an incompatible save profile")
    return value


def validate_checkpoint_reply(message: Any, config: CompanionConfig, epoch: int, profile: str) -> dict[str, Any]:
    common = {"type", "protocol", "session_epoch", "request_id", "operation"}
    if not isinstance(message, dict) or not common <= set(message) or type(message["protocol"]) is not int or message["protocol"] != PROTOCOL_VERSION:
        raise ProtocolError("invalid_server_message", "invalid checkpoint reply envelope")
    if not _int(message["session_epoch"], 1, MAX_COUNTER) or message["session_epoch"] != epoch or not _uuid(message["request_id"]):
        raise ProtocolError("session_epoch_mismatch", "checkpoint reply has an invalid session or request")
    op = message["operation"]
    if not isinstance(op, str) or op not in {"info", "read", "begin", "chunk", "commit", "abort"}:
        raise ProtocolError("invalid_server_message", "unknown checkpoint operation")
    if message["type"] == "checkpoint_error":
        if set(message) != common | {"code", "message"} or not isinstance(message["code"], str) or not 1 <= len(message["code"]) <= 128 or not isinstance(message["message"], str) or not 1 <= len(message["message"]) <= 512:
            raise ProtocolError("invalid_server_message", "invalid checkpoint error")
        return message
    extras = {
        "info": set(), "read": {"offset", "data_b64", "eof"},
        "begin": {"upload_id", "next_offset"}, "chunk": {"upload_id", "next_offset"},
        "commit": {"upload_id"}, "abort": {"upload_id"},
    }[op]
    if message["type"] != "checkpoint_result" or set(message) != common | {"checkpoint"} | extras:
        raise ProtocolError("invalid_server_message", "invalid checkpoint result fields")
    metadata = validate_metadata(message["checkpoint"], config, profile)
    if "upload_id" in extras and not _uuid(message["upload_id"]):
        raise ProtocolError("invalid_server_message", "invalid upload identity")
    if "next_offset" in extras and not _int(message["next_offset"], 0, 131088):
        raise ProtocolError("invalid_server_message", "invalid upload position")
    if op == "read":
        if metadata is None or not _int(message["offset"], 0, metadata["size"]) or type(message["eof"]) is not bool:
            raise ProtocolError("invalid_server_message", "invalid checkpoint read position")
        data = decode_chunk(message["data_b64"])
        if message["offset"] + len(data) > metadata["size"] or message["eof"] != (message["offset"] + len(data) == metadata["size"]):
            raise ProtocolError("invalid_server_message", "invalid checkpoint read end")
    return message


def decode_chunk(encoded: Any) -> bytes:
    if not isinstance(encoded, str) or not 1 <= len(encoded) <= 5464:
        raise ProtocolError("invalid_server_message", "invalid checkpoint chunk size")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ProtocolError("invalid_server_message", "invalid checkpoint chunk encoding") from None
    if not 1 <= len(data) <= CHECKPOINT_CHUNK_BYTES or base64.b64encode(data).decode("ascii") != encoded:
        raise ProtocolError("invalid_server_message", "checkpoint chunk exceeds its bounds")
    return data


@dataclass(frozen=True)
class DownloadedCheckpoint:
    world_id: str
    player_id: str
    metadata: dict[str, Any]
    payload: bytes


class CheckpointClient:
    def __init__(self, companion: Companion):
        self.companion = companion
        self._transfer_lock = asyncio.Lock()

    def _session(self) -> tuple[str, int]:
        c = self.companion
        if not c.connected or c.world_id is None or c.session_epoch is None:
            raise ConnectionError("no authenticated checkpoint session")
        return c.world_id, c.session_epoch

    async def _answers(self, operation, requests):
        """The answers to `requests` (field dicts) in order: up to TRANSFER_WINDOW in flight through the companion's
        checkpoint_pipeline, else one at a time."""
        pipeline = getattr(self.companion, "checkpoint_pipeline", None)
        if pipeline is None:
            for fields in requests:
                yield await self.companion.checkpoint_rpc(operation, **fields)
            return
        async with aclosing(pipeline(operation, requests, window=TRANSFER_WINDOW)) as answers:
            async for answer in answers:
                yield answer

    async def info(self) -> dict[str, Any] | None:
        return (await self.companion.checkpoint_rpc("info"))["checkpoint"]

    async def download(self) -> DownloadedCheckpoint | None:
        from .flash import inspect_flash
        async with self._transfer_lock:
            session = self._session()
            metadata = await self.info()
            if metadata is None:
                return None
            data = bytearray()

            def reads():
                for offset in range(0, metadata["size"], CHECKPOINT_CHUNK_BYTES):
                    if self._session() != session:
                        raise ConnectionError("checkpoint session changed during download")
                    yield dict(expected_revision=metadata["revision"], offset=offset, length=CHECKPOINT_CHUNK_BYTES)
            async with aclosing(self._answers("read", reads())) as answers:
                async for response in answers:
                    if self._session() != session:
                        raise ConnectionError("checkpoint session changed during download")
                    if response["checkpoint"] != metadata or response["offset"] != len(data):
                        raise ProtocolError("invalid_server_message", "checkpoint changed during download")
                    data.extend(decode_chunk(response["data_b64"]))
            payload = bytes(data)
            if self._session() != session:
                raise ConnectionError("checkpoint session changed before download completed")
            if len(payload) != metadata["size"] or hashlib.sha256(payload).hexdigest() != metadata["sha256"]:
                raise ProtocolError("invalid_server_message", "downloaded checkpoint hash mismatch")
            snapshot = inspect_flash(payload, save_profile=self.companion.save_profile)
            from .ownership import OWNERSHIP_PROFILE, inspect_ownership
            if snapshot.save_profile == OWNERSHIP_PROFILE:
                owner = inspect_ownership(snapshot)
                if (owner.world_id, owner.player_id) != (session[0], self.companion.config.player_id):
                    raise ProtocolError("identity_mismatch", "ownership checkpoint belongs to another world or character")
            return DownloadedCheckpoint(session[0], self.companion.config.player_id, metadata, payload)

    async def upload(self, payload: bytes, expected_revision: int, *, transaction_id: str | None = None) -> dict[str, Any]:
        """Keep transaction_id and original bytes for an uncertain-ack retry.

        A retry never adopts a newer revision or invents a replacement transaction.
        Caller must keep the game closed while obtaining this ordinary save.
        """
        from .flash import inspect_flash
        inspect_flash(payload, save_profile=self.companion.save_profile)
        async with self._transfer_lock:
            session = self._session()
            transaction_id = transaction_id or str(uuid4())
            fingerprint = {"expected_revision": expected_revision, "size": len(payload), "sha256": hashlib.sha256(payload).hexdigest(), "save_profile": self.companion.save_profile}
            result = await self.companion.checkpoint_rpc("begin", request_id=transaction_id, **fingerprint)
            if result["upload_id"] != transaction_id:
                raise ProtocolError("invalid_server_message", "server changed checkpoint transaction identity")
            offset = result["next_offset"]
            if offset > len(payload):
                raise ProtocolError("invalid_server_message", "server upload offset exceeds its payload")

            def chunks():
                for start in range(offset, len(payload), CHECKPOINT_CHUNK_BYTES):
                    if self._session() != session:
                        raise ConnectionError("checkpoint session changed during upload")
                    chunk = payload[start:start + CHECKPOINT_CHUNK_BYTES]
                    yield dict(upload_id=transaction_id, offset=start, data_b64=base64.b64encode(chunk).decode("ascii"))
            acknowledged = offset
            async with aclosing(self._answers("chunk", chunks())) as answers:
                async for result in answers:
                    end = min(acknowledged + CHECKPOINT_CHUNK_BYTES, len(payload))
                    if result["upload_id"] != transaction_id or result["next_offset"] != end:
                        raise ProtocolError("invalid_server_message", "server did not acknowledge the exact checkpoint chunk")
                    acknowledged = end
            if self._session() != session:
                raise ConnectionError("checkpoint session changed before commit")
            result = await self.companion.checkpoint_rpc("commit", upload_id=transaction_id, **fingerprint)
            if self._session() != session:
                raise ConnectionError("checkpoint session changed before commit acknowledgement completed")
            metadata = result["checkpoint"]
            if result["upload_id"] != transaction_id or metadata is None or metadata["request_id"] != transaction_id or metadata["revision"] != expected_revision + 1 or metadata["sha256"] != fingerprint["sha256"] or metadata["size"] != len(payload):
                raise ProtocolError("invalid_server_message", "checkpoint commit does not match the requested transaction")
            return metadata
