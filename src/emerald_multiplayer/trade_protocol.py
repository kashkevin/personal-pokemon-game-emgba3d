"""Bounded authenticated trade controls; saves use the existing chunked channel.

Actor identity comes from the server connection, never a request body. Trading
clients must obtain a fresh remote lease whenever their authenticated ROM bridge
is lost or reincarnates. A timeout is uncertainty, not an authoritative abort.
"""
from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from .checkpoint_client import validate_metadata
from .flash import MAX_SPECIES_ID
from .ownership_protocol import MAX_SERIAL, OWNERSHIP_PROFILE
from .protocol import MAX_COUNTER, PROTOCOL_VERSION, ProtocolError, _fields, _integer

TRADE_OPERATIONS = frozenset({"open", "offer", "confirm", "cancel", "status", "pending", "ack"})
TRADE_TYPES = frozenset("trade_" + operation for operation in TRADE_OPERATIONS)
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_CODE = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")


def _uuid(value: Any, field: str) -> str:
    try:
        if not isinstance(value, str) or str(UUID(value)) != value or UUID(value).int == 0:
            raise ValueError()
    except (ValueError, AttributeError, TypeError):
        raise ProtocolError("invalid_field", f"{field} must be a nonzero canonical UUID") from None
    return value


def _hash(value: Any, field: str) -> str:
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        raise ProtocolError("invalid_field", f"{field} must be a lower-case SHA256")
    return value


def validate_trade_common(message: Any, session_epoch: int) -> dict[str, Any]:
    """Validate correlation before a recoverable body error can be answered."""
    if not isinstance(message, dict) or not isinstance(message.get("type"), str) or message["type"] not in TRADE_TYPES:
        raise ProtocolError("invalid_type", "unsupported trade operation")
    epoch = _integer(message.get("session_epoch"), "session_epoch", 1, MAX_COUNTER)
    if epoch != session_epoch:
        raise ProtocolError("session_epoch_mismatch", "trade belongs to another authenticated lease")
    _uuid(message.get("request_id"), "request_id")
    return message


def validate_trade_request(message: Any, session_epoch: int) -> dict[str, Any]:
    validate_trade_common(message, session_epoch)
    operation = message["type"].removeprefix("trade_")
    common = {"type", "request_id", "session_epoch"}
    extras = {
        "open": {"peer", "transaction_id"},
        "offer": {"transaction_id", "generation", "revision", "sha256", "serial"},
        "confirm": {"transaction_id", "generation", "fingerprint"},
        "cancel": {"transaction_id", "generation"},
        "status": {"transaction_id"},
        "pending": set(),
        "ack": {"transaction_id", "revision", "sha256"},
    }[operation]
    _fields(message, common | extras)
    for field in extras & {"peer", "transaction_id", "generation"}:
        _uuid(message[field], field)
    for field in extras & {"sha256", "fingerprint"}:
        _hash(message[field], field)
    if "revision" in extras:
        _integer(message["revision"], "revision", 1, MAX_COUNTER)
    if "serial" in extras:
        _integer(message["serial"], "serial", 1, MAX_SERIAL)
    return dict(message)


def _players(value: Any, actor: str) -> list[str]:
    if not isinstance(value, list) or len(value) != 2:
        raise ProtocolError("invalid_server_message", "trade needs exactly two player identities")
    for player in value:
        _uuid(player, "player_id")
    if value != sorted(set(value)) or actor not in value:
        raise ProtocolError("identity_mismatch", "trade participants are duplicated, unordered or foreign")
    return value


def _trade(value: Any, operation: str, actor: str) -> None:
    if not isinstance(value, dict) or not {"transaction_id", "state"} <= set(value):
        raise ProtocolError("invalid_server_message", "invalid trade state")
    _uuid(value["transaction_id"], "transaction_id")
    states = {
        "open": {"offering", "committed"},
        "offer": {"offering"},
        "confirm": {"offering", "committed"},
        "cancel": {"aborted", "committed"},
        "status": {"offering", "aborted", "committed"},
        "ack": {"acknowledged"},
    }
    state = value["state"]
    if not isinstance(state, str) or state not in states[operation]:
        raise ProtocolError("invalid_server_message", "trade state is incompatible with the operation")
    common = {"transaction_id", "state"}
    if state == "aborted":
        _fields(value, common)
    elif state in {"committed", "acknowledged"}:
        extras = {"revision", "sha256"}
        if state == "committed":
            extras.add("outcome_fingerprint")
            _hash(value.get("outcome_fingerprint"), "outcome_fingerprint")
        _fields(value, common | extras)
        _integer(value["revision"], "revision", 1, MAX_COUNTER)
        _hash(value["sha256"], "sha256")
    else:
        _fields(value, common | {"generation", "fingerprint", "players", "confirmations", "offers"})
        _uuid(value["generation"], "generation")
        players = _players(value["players"], actor)
        offers = value["offers"]
        if not isinstance(offers, list) or not 0 <= len(offers) <= 2:
            raise ProtocolError("invalid_server_message", "trade offers exceed the two-player bound")
        offer_players, serials = [], []
        for offer in offers:
            _fields(offer, {"player_id", "serial", "species", "revision", "sha256"})
            player = _uuid(offer["player_id"], "player_id")
            if player not in players:
                raise ProtocolError("identity_mismatch", "offer belongs to another participant")
            _integer(offer["serial"], "serial", 1, MAX_SERIAL)
            _integer(offer["species"], "species", 1, MAX_SPECIES_ID)
            _integer(offer["revision"], "revision", 1, MAX_COUNTER)
            _hash(offer["sha256"], "sha256")
            offer_players.append(player); serials.append(offer["serial"])
        if offer_players != sorted(set(offer_players)) or len(set(serials)) != len(serials):
            raise ProtocolError("invalid_server_message", "trade offers are duplicated or unordered")
        if len(offers) == 2:
            _hash(value["fingerprint"], "fingerprint")
        elif value["fingerprint"] is not None:
            raise ProtocolError("invalid_server_message", "an incomplete offer cannot have a consent fingerprint")
        confirmations = value["confirmations"]
        # Synchronous second consent commits or clears on failure; it cannot
        # leave a publicly offering state with two accepted confirmations.
        if not isinstance(confirmations, list) or len(confirmations) > 1:
            raise ProtocolError("invalid_server_message", "invalid uncommitted confirmation count")
        for player in confirmations:
            _uuid(player, "confirmed player_id")
        if confirmations != sorted(set(confirmations)) or any(p not in offer_players for p in confirmations) or (confirmations and len(offers) != 2):
            raise ProtocolError("invalid_server_message", "confirmation does not identify a complete offered participant")


def validate_trade_reply(message: Any, config, profile: str, world_id: str, epoch: int) -> dict[str, Any]:
    common = {"type", "protocol", "session_epoch", "request_id", "operation", "world_id", "player_id"}
    if not isinstance(message, dict) or not common <= set(message) or type(message["protocol"]) is not int or message["protocol"] != PROTOCOL_VERSION:
        raise ProtocolError("invalid_server_message", "invalid trade reply envelope")
    _integer(message["session_epoch"], "session_epoch", 1, MAX_COUNTER)
    if message["session_epoch"] != epoch:
        raise ProtocolError("session_epoch_mismatch", "trade reply belongs to another lease")
    _uuid(message["request_id"], "request_id")
    _uuid(message["world_id"], "world_id"); _uuid(message["player_id"], "player_id")
    if profile != OWNERSHIP_PROFILE or (message["world_id"], message["player_id"]) != (world_id, config.player_id):
        raise ProtocolError("identity_mismatch", "trade reply belongs to another ownership world or player")
    operation = message["operation"]
    if not isinstance(operation, str) or operation not in TRADE_OPERATIONS:
        raise ProtocolError("invalid_server_message", "unsupported trade reply operation")
    if message["type"] == "trade_error":
        _fields(message, common | {"code", "message"})
        if not isinstance(message["code"], str) or _CODE.fullmatch(message["code"]) is None or not isinstance(message["message"], str) or not 1 <= len(message["message"]) <= 512 or not message["message"].isprintable():
            raise ProtocolError("invalid_server_message", "invalid trade error text")
    elif message["type"] == "trade_result":
        if operation == "pending":
            _fields(message, common | {"recoveries"})
            recoveries = message["recoveries"]
            if not isinstance(recoveries, list) or len(recoveries) > 1:
                raise ProtocolError("invalid_server_message", "pending trade recovery exceeds its per-player bound")
            for recovery in recoveries:
                _fields(recovery, {"transaction_id", "sequence", "outcome_fingerprint", "checkpoint"})
                _uuid(recovery["transaction_id"], "transaction_id")
                _integer(recovery["sequence"], "sequence", 1, MAX_COUNTER)
                _hash(recovery["outcome_fingerprint"], "outcome_fingerprint")
                metadata = validate_metadata(recovery["checkpoint"], config, profile)
                if metadata is None or metadata["request_id"] != recovery["transaction_id"]:
                    raise ProtocolError("identity_mismatch", "pending checkpoint is not the committed trade result")
        else:
            _fields(message, common | {"trade"})
            _trade(message["trade"], operation, config.player_id)
    else:
        raise ProtocolError("invalid_server_message", "unexpected trade reply type")
    return message
