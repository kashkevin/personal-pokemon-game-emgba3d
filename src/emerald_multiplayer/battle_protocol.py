"""Authenticated consent and bounded execution of host-issued native controls.

The execute exchange acknowledges only one exact host-issued control. Clients
cannot choose BIND, START, routing, winner, or release through this interface.
"""
from __future__ import annotations

import re

from .protocol import MAX_COUNTER, PROTOCOL_VERSION, ProtocolError, _fields, _integer
from .team_protocol import _uuid

BATTLE_OPERATIONS = frozenset({"invite", "invite_multi", "accept", "claim", "cancel", "status", "pending", "history", "waiting", "execute", "resume"})
BATTLE_TYPES = frozenset("battle_" + op for op in BATTLE_OPERATIONS)
STATES = frozenset({"invited", "accepted", "prepared", "starting", "running", "finishing",
                    "release_authorized", "closed", "aborting", "aborted", "recovery_required"})
SCOPE = "session-local-native-challenges-v1"
_CODE = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")


def validate_battle_common(message, epoch):
    if (not isinstance(message, dict) or not isinstance(message.get("type"), str)
            or message["type"] not in BATTLE_TYPES):
        raise ProtocolError("invalid_type", "unsupported battle challenge operation")
    _integer(message.get("session_epoch"), "session_epoch", 1, MAX_COUNTER)
    if message["session_epoch"] != epoch:
        raise ProtocolError("session_epoch_mismatch", "battle request belongs to another lease")
    _uuid(message.get("request_id"), "request_id")
    return message


def validate_battle_request(message, epoch):
    validate_battle_common(message, epoch)
    operation = message["type"].removeprefix("battle_")
    extra = {
        "invite": {"peer", "battle_id"},
        "invite_multi": {"teammate", "opponents", "battle_id"},
        "accept": {"battle_id", "generation", "fingerprint"},
        "claim": {"battle_id", "generation", "incarnation", "runtime_id"},
        "cancel": {"battle_id", "generation"},
        "status": {"battle_id"}, "pending": set(), "history": set(), "waiting": set(),
        "execute": {"battle_id", "generation", "incarnation", "response_b64", "response_id"},
        "resume": {"battle_id", "generation", "incarnation", "response_b64", "response_id", "response_stage"},
    }[operation]
    if operation in ("execute", "resume") and "admission_sha256" in message:
        extra = extra | {"admission_sha256"}
    identity_fields = {"incarnation", "runtime_id"}
    if operation == "claim" or (operation in ("invite", "invite_multi", "accept") and identity_fields.intersection(message)):
        extra = extra | identity_fields
        _integer(message.get("incarnation"), "incarnation", 1, 0xFFFFFFFF)
        _uuid(message.get("runtime_id"), "runtime_id")
    provisional_fields = {"runtime_id", "admission_b64", "admission_receipt_b64"}
    if operation in ("execute", "resume") and provisional_fields.intersection(message):
        extra = extra | provisional_fields
    _fields(message, {"type", "request_id", "session_epoch"} | extra)
    for key in extra - {"opponents", "fingerprint", "incarnation", "response_b64", "response_id", "response_stage", "admission_sha256", "admission_b64", "admission_receipt_b64"}:
        _uuid(message[key], key)
    if operation == "execute":
        from .battle_execution_protocol import validate_execution_request
        validate_execution_request(message)
    elif operation == "resume":
        from .battle_recovery_protocol import validate_recovery_request
        validate_recovery_request(message)
    if "opponents" in extra:
        opponents = message["opponents"]
        if type(opponents) is not list or len(opponents) != 2:
            raise ProtocolError("invalid_field", "Multi requires two opposing players")
        for opponent in opponents:
            _uuid(opponent, "opponent")
        if len({message["teammate"], *opponents}) != 3:
            raise ProtocolError("invalid_field", "Multi participants must be distinct")
    if "fingerprint" in extra:
        _digest(message["fingerprint"])
    return dict(message)


def _digest(value):
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        raise ProtocolError("invalid_field", "battle fingerprint must be a SHA256 digest")


def challenge_view(view):
    """Expose consent and canonical counts; never native RNG or save bytes."""
    mode = view.get("mode", 2)
    return dict(scope=SCOPE, battle_id=view["battle_id"], generation=view["generation"],
        sender=view["sender"], mode=mode, state=view["state"], reason=view["reason"],
        players=list(view["players"]), fingerprint=view["fingerprint"],
        consent=list(view["consent"]), outcome=view["outcome"],
        checkpoints=[dict(cp) for cp in view["checkpoints"]])


def _view(value, actor):
    _fields(value, {"scope", "battle_id", "generation", "sender", "mode", "state",
                    "reason", "players", "fingerprint", "consent", "outcome", "checkpoints"})
    for key in ("battle_id", "generation", "sender"):
        _uuid(value[key], key)
    _digest(value["fingerprint"])
    if value["scope"] != SCOPE or type(value["mode"]) is not int or value["mode"] not in (2, 3):
        raise ProtocolError("invalid_server_message", "unsupported battle challenge format")
    count = 2 if value["mode"] == 2 else 4
    players = value["players"]
    if type(players) is not list or len(players) != count:
        raise ProtocolError("invalid_server_message", "incorrect battle participant count")
    for player in players:
        _uuid(player, "participant")
    if len(set(players)) != count or actor not in players or value["sender"] not in players:
        raise ProtocolError("identity_mismatch", "foreign or repeated battle participant")
    if not isinstance(value["state"], str) or value["state"] not in STATES:
        raise ProtocolError("invalid_server_message", "invalid battle state")
    reason = value["reason"]
    if reason is not None and (not isinstance(reason, str) or _CODE.fullmatch(reason) is None):
        raise ProtocolError("invalid_server_message", "invalid battle status reason")
    consent = value["consent"]
    if type(consent) is not list or any(type(p) is not str for p in consent):
        raise ProtocolError("invalid_server_message", "invalid battle consent")
    if len(consent) != len(set(consent)) or not set(consent) <= set(players):
        raise ProtocolError("identity_mismatch", "foreign or repeated battle consent")
    outcome = value["outcome"]
    if outcome is not None and (type(outcome) is not int or outcome not in (1, 2, 3)):
        raise ProtocolError("invalid_server_message", "invalid battle outcome")
    checkpoints = value["checkpoints"]
    if type(checkpoints) is not list or len(checkpoints) != count:
        raise ProtocolError("invalid_server_message", "incorrect canonical battle roster")
    for slot, cp in enumerate(checkpoints):
        _fields(cp, {"player_id", "source_slot", "revision", "sha256", "party_count"})
        if cp["player_id"] != players[slot] or type(cp["source_slot"]) is not int or cp["source_slot"] != slot:
            raise ProtocolError("identity_mismatch", "canonical battle slots changed")
        _integer(cp["revision"], "revision", 1, MAX_COUNTER)
        _integer(cp["party_count"], "party_count", 1, 6)
        _digest(cp["sha256"])


def validate_battle_reply(message, actor, world_id, epoch, request=None):
    common = {"type", "protocol", "session_epoch", "request_id", "operation", "world_id", "player_id"}
    if (not isinstance(message, dict) or not common <= set(message)
            or type(message["protocol"]) is not int or message["protocol"] != PROTOCOL_VERSION):
        raise ProtocolError("invalid_server_message", "invalid battle reply envelope")
    _integer(message["session_epoch"], "session_epoch", 1, MAX_COUNTER)
    for key in ("request_id", "world_id", "player_id"):
        _uuid(message[key], key)
    if (message["session_epoch"], message["world_id"], message["player_id"]) != (epoch, world_id, actor):
        raise ProtocolError("identity_mismatch", "battle reply belongs to another world, player or lease")
    op = message["operation"]
    if not isinstance(op, str) or op not in BATTLE_OPERATIONS:
        raise ProtocolError("invalid_server_message", "unsupported battle reply operation")
    if message["type"] == "battle_error":
        _fields(message, common | {"code", "message"})
        if (not isinstance(message["code"], str) or _CODE.fullmatch(message["code"]) is None
                or not isinstance(message["message"], str) or not 1 <= len(message["message"]) <= 512
                or not message["message"].isprintable()):
            raise ProtocolError("invalid_server_message", "invalid battle error text")
    elif message["type"] == "battle_result":
        _fields(message, common | {"result"})
        result = message["result"]
        if op == "resume":
            from .battle_recovery_protocol import validate_recovery_view
            validate_recovery_view(message["result"], request=request)
        elif op == "execute":
            from .battle_execution_protocol import validate_execution_view
            validate_execution_view(result, request=request)
        elif op == "waiting":
            from .battle_reservations import validate_waiting
            if type(result) is not list or len(result) > 1:
                raise ProtocolError("invalid_server_message", "too many durable battle reservations")
            for view in result:
                validate_waiting(view, actor)
        elif op == "history":
            from .battle_results import HISTORY_LIMIT, validate_result
            if type(result) is not list or len(result) > HISTORY_LIMIT:
                raise ProtocolError("invalid_server_message", "invalid battle history size")
            sequences, battles = [], set()
            for view in result:
                validate_result(view, actor)
                sequences.append(view["sequence"])
                battles.add(view["battle_id"])
            if sequences != sorted(set(sequences), reverse=True) or len(battles) != len(result):
                raise ProtocolError("invalid_server_message", "battle history order or identity changed")
        elif op == "pending":
            if type(result) is not list or len(result) > 1:
                raise ProtocolError("invalid_server_message", "too many active battles for one player")
            for view in result:
                _view(view, actor)
        else:
            _view(result, actor)
    else:
        raise ProtocolError("invalid_server_message", "unexpected battle reply type")
    if request is not None:
        validate_battle_request(request, epoch)
        if message["request_id"] != request["request_id"] or op != request["type"].removeprefix("battle_"):
            raise ProtocolError("invalid_server_message", "battle reply does not match its request")
        if message["type"] == "battle_result" and op not in ("pending", "history", "waiting", "execute", "resume"):
            result = message["result"]
            if result["battle_id"] != request["battle_id"]:
                raise ProtocolError("identity_mismatch", "battle reply changed the target")
            for key in ("generation", "fingerprint"):
                if key in request and result[key] != request[key]:
                    raise ProtocolError("identity_mismatch", "battle reply changed the accepted challenge")
            if op in ("invite", "invite_multi"):
                expected = {actor, request["peer"]} if op == "invite" else {actor, request["teammate"], *request["opponents"]}
                if result["sender"] != actor or set(result["players"]) != expected or result["mode"] != (2 if op == "invite" else 3):
                    raise ProtocolError("identity_mismatch", "battle invitation changed its participants")
                if op == "invite_multi":
                    own = set(result["players"][::2])
                    if own != {actor, request["teammate"]}:
                        raise ProtocolError("identity_mismatch", "battle invitation changed the teams")
    return message
