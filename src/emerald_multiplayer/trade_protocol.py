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

TRADE_OPERATIONS = frozenset({"open", "offer", "confirm", "prepare", "prepared", "cancel", "status", "pending", "proposals", "ack", "inspect", "effect_source", "effect_prepared"})
TRADE_TYPES = frozenset("trade_" + operation for operation in TRADE_OPERATIONS)
PREPARATION_VERSION = 1
PREPARATION_OPERATIONS = frozenset({"open", "offer", "confirm", "prepare", "prepared", "proposals", "inspect", "effect_source", "effect_prepared"})
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
    if "effects_version" in message:
        if type(message["effects_version"]) is not int or message["effects_version"] != 1:
            raise ProtocolError("trade_effect_unsupported", "unsupported native effect version")
        common.add("effects_version")
    if operation == "effect_prepared" and message.get("effects_version") != 1:
        raise ProtocolError("trade_effect_negotiation_required", "native effect receipts require explicit negotiation")
    for feature in ("inspection_version", "effect_source_version"):
        if feature in message:
            if operation != "status" or type(message[feature]) is not int or message[feature] != 1:
                raise ProtocolError("invalid_field", "unsupported read-only trade feature negotiation")
            common.add(feature)
    if operation in PREPARATION_OPERATIONS or "preparation_version" in message:
        if type(message.get("preparation_version")) is not int or message["preparation_version"] != PREPARATION_VERSION:
            raise ProtocolError("trade_preparation_unsupported", "recipient preparation version 1 is required before offering or consenting")
        common.add("preparation_version")
    extras = {
        "open": {"peer", "transaction_id"},
        "offer": {"transaction_id", "generation", "revision", "sha256", "serial"},
        "confirm": {"transaction_id", "generation", "fingerprint"},
        "prepare": {"transaction_id", "generation"},
        "inspect": {"transaction_id", "generation", "fingerprint"},
        "effect_source": {"transaction_id", "generation", "preparation_id"},
        "prepared": {"transaction_id", "generation", "fingerprint", "preparation_id", "candidate_sha256"},
        "effect_prepared": {"transaction_id", "generation", "fingerprint", "preparation_id", "candidate_sha256", "candidate_size", "record_sha256", "choices"},
        "cancel": {"transaction_id", "generation"},
        "status": {"transaction_id"},
        "pending": set(),
        "proposals": set(),
        "ack": {"transaction_id", "revision", "sha256"},
    }[operation]
    _fields(message, common | extras)
    for field in extras & {"peer", "transaction_id", "generation"}:
        _uuid(message[field], field)
    for field in extras & {"sha256", "fingerprint", "preparation_id", "candidate_sha256", "record_sha256"}:
        _hash(message[field], field)
    if "revision" in extras:
        _integer(message["revision"], "revision", 1, MAX_COUNTER)
    if "serial" in extras:
        _integer(message["serial"], "serial", 1, MAX_SERIAL)
    if operation == "effect_prepared":
        from .trade_effect_preparation import validate_effect_receipt
        try:
            validate_effect_receipt({k: message[k] for k in ("choices", "candidate_sha256", "candidate_size", "record_sha256")})
        except (ValueError, TypeError, KeyError) as error:
            raise ProtocolError("invalid_field", "invalid native effect receipt") from error
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
        "open": {"offering", "preparing", "committed"},
        "offer": {"offering"},
        "confirm": {"offering", "preparing", "committed"},
        "prepare": {"recipient_preparation", "committed"},
        "inspect": {"inspection"},
        "effect_source": {"effect_source"},
        "prepared": {"preparing", "committed"},
        "effect_prepared": {"preparing", "committed"},
        "proposals": {"offering", "preparing"},
        "cancel": {"aborted", "committed"},
        "status": {"offering", "preparing", "aborted", "committed"},
        "ack": {"acknowledged"},
    }
    state = value["state"]
    if not isinstance(state, str) or state not in states[operation]:
        raise ProtocolError("invalid_server_message", "trade state is incompatible with the operation")
    common = {"transaction_id", "state"}
    if state == "inspection":
        from .trade_inspection import validate_inspection
        validate_inspection(value, actor)
    elif state == "effect_source":
        _fields(value, common | {"source"})
        from .trade_effect_source import validate_effect_source
        try:
            validate_effect_source(value["source"], actor)
        except (ValueError, TypeError, KeyError) as error:
            raise ProtocolError("invalid_server_message", "invalid recipient effect source") from error
        if value["source"]["transaction_id"] != value["transaction_id"]:
            raise ProtocolError("identity_mismatch", "effect source names another trade")
    elif state == "aborted":
        _fields(value, common)
    elif state == "recipient_preparation":
        _fields(value, common | {"preparation"})
        from .trade_preparation import TradePreparationError, validate_preparation
        try:
            if type(value["preparation"]) is not dict:
                raise TradePreparationError("preparation must be an object")
            if value["preparation"].get("format") == "emerald-trade-recipient-effects-v2":
                from .trade_effect_preparation import validate_effect_preparation
                description = validate_effect_preparation(value["preparation"])
            else:
                description = validate_preparation(value["preparation"])
        except (TradePreparationError, ValueError, TypeError) as error:
            raise ProtocolError("invalid_server_message", "invalid recipient preparation") from error
        if (description["recipient_id"], description["transaction_id"]) != (actor, value["transaction_id"]):
            raise ProtocolError("identity_mismatch", "preparation belongs to another recipient or transaction")
    elif state in {"committed", "acknowledged"}:
        extras = {"revision", "sha256"}
        if state == "committed":
            extras.add("outcome_fingerprint")
            _hash(value.get("outcome_fingerprint"), "outcome_fingerprint")
        _fields(value, common | extras)
        _integer(value["revision"], "revision", 1, MAX_COUNTER)
        _hash(value["sha256"], "sha256")
    else:
        extras = {"generation", "fingerprint", "players", "confirmations", "offers"}
        effectful = "capability" in value
        if effectful:
            from .trade_effect_flash import PLAN_ID
            if value["capability"] != PLAN_ID:
                raise ProtocolError("trade_effect_unsupported", "unknown trade effect capability")
            extras.add("capability")
        if state == "preparing":
            extras |= {"preparation_id", "prepared"}
        _fields(value, common | extras)
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
        if not isinstance(confirmations, list) or len(confirmations) > (2 if state == "preparing" else 1):
            raise ProtocolError("invalid_server_message", "invalid uncommitted confirmation count")
        for player in confirmations:
            _uuid(player, "confirmed player_id")
        if confirmations != sorted(set(confirmations)) or any(p not in offer_players for p in confirmations) or (confirmations and len(offers) != 2):
            raise ProtocolError("invalid_server_message", "confirmation does not identify a complete offered participant")
        if state == "preparing":
            _hash(value["preparation_id"], "preparation_id")
            prepared = value["prepared"]
            if (confirmations != players or type(prepared) is not list or len(prepared) > (2 if effectful else 1)
                    or any(type(p) is not str or p not in players for p in prepared)
                    or prepared != sorted(set(prepared))):
                raise ProtocolError("invalid_server_message", "invalid exact recipient preparation state")


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
    if "effects_version" in message:
        if type(message["effects_version"]) is not int or message["effects_version"] != 1:
            raise ProtocolError("trade_effect_unsupported", "unsupported native effect acknowledgement")
        common.add("effects_version")
    if "preparation_version" in message:
        if type(message["preparation_version"]) is not int or message["preparation_version"] != PREPARATION_VERSION:
            raise ProtocolError("trade_preparation_unsupported", "host recipient preparation version is unsupported")
        common.add("preparation_version")
    elif message["type"] == "trade_result" and operation in PREPARATION_OPERATIONS:
        raise ProtocolError("trade_preparation_unsupported", "host did not negotiate recipient preparation before consent")
    for feature in ("inspection_version", "effect_source_version"):
        if feature in message:
            if operation != "status" or message["type"] != "trade_result" or type(message[feature]) is not int or message[feature] != 1:
                raise ProtocolError("invalid_server_message", "invalid read-only trade capability acknowledgement")
            common.add(feature)
    if message["type"] == "trade_error":
        _fields(message, common | {"code", "message"})
        if not isinstance(message["code"], str) or _CODE.fullmatch(message["code"]) is None or not isinstance(message["message"], str) or not 1 <= len(message["message"]) <= 512 or not message["message"].isprintable():
            raise ProtocolError("invalid_server_message", "invalid trade error text")
    elif message["type"] == "trade_result":
        if operation == "proposals":
            _fields(message, common | {"proposals"})
            proposals = message["proposals"]
            if not isinstance(proposals, list) or len(proposals) > 1:
                raise ProtocolError("invalid_server_message", "trade proposals exceed the per-player bound")
            for proposal in proposals:
                _trade(proposal, "proposals", config.player_id)
        elif operation == "pending":
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
        views = message.get("proposals", [message.get("trade", {})])
        if any(view.get("capability") == "native-recipient-save-effects-v1"
               or view.get("preparation", {}).get("format") == "emerald-trade-recipient-effects-v2" for view in views):
            if message.get("effects_version") != 1:
                raise ProtocolError("trade_effect_negotiation_required", "host supplied effect consent without negotiation")
    else:
        raise ProtocolError("invalid_server_message", "unexpected trade reply type")
    return message
