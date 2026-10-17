"""Authenticated consent and bounded execution of host-issued native controls.

The execute exchange acknowledges only one exact host-issued control. Clients
cannot choose BIND, START, routing, winner, or release through this interface.
"""
from __future__ import annotations

import re

from .coop_code import valid_code
from .rival_catalogue import valid_preparation_word
from .protocol import MAX_COUNTER, PROTOCOL_VERSION, ProtocolError, _fields, _integer
from .team_protocol import _uuid

BATTLE_OPERATIONS = frozenset({"invite", "invite_multi", "invite_ffa", "accept", "claim", "cancel", "cancel_admission", "admission_handoff", "status", "pending", "history", "waiting", "execute", "resume"})
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
        "invite_ffa": {"opponents", "battle_id"},
        "accept": {"battle_id", "generation", "fingerprint"},
        "claim": {"battle_id", "generation", "incarnation", "runtime_id"},
        "cancel": {"battle_id", "generation"},
        "cancel_admission": {"battle_id", "generation", "incarnation", "runtime_id", "cleanup_ready_b64", "cleanup_receipt_b64"},
        "admission_handoff": {"battle_id", "generation", "incarnation", "runtime_id", "handoff_receipt_b64"},
        "status": {"battle_id"}, "pending": set(), "history": set(), "waiting": set(),
        "execute": {"battle_id", "generation", "incarnation", "response_b64", "response_id"},
        "resume": {"battle_id", "generation", "incarnation", "response_b64", "response_id", "response_stage"},
    }[operation]
    championship_match = False
    if operation == "pending" and "championship" in message:
        from .championship_protocol import validate_championship_request
        validate_championship_request(message["championship"])
        extra = extra | {"championship"}
        championship_match = message["championship"]["operation"] == "match"
    if operation == "pending" and "rival" in message:
        if "championship" in message:
            raise ProtocolError("invalid_fields", "request one battle pending extension at a time")
        from .rival_protocol import validate_rival_request
        validate_rival_request(message["rival"])
        extra = extra | {"rival"}
        # A rival match is issued by its requesting trainer, exactly like a Championship match.
        championship_match = message["rival"]["operation"] == "match"
    if operation == "pending" and "admission_handoff_version" in message:
        if "championship" in message or "rival" in message or type(message["admission_handoff_version"]) is not int or message["admission_handoff_version"] != 1:
            raise ProtocolError("admission_handoff_unsupported", "unsupported admission handoff capability query")
        extra = extra | {"admission_handoff_version"}
    card_fields = {"player_card_version", "card_player"}
    history_extensions = {"battle_archive", "reset_history", "trade_archive"}.intersection(message)
    if history_extensions:
        if operation != "history" or len(history_extensions) != 1 or card_fields.intersection(message):
            raise ProtocolError("invalid_fields", "request one private history view at a time")
        key = next(iter(history_extensions))
        if key == "battle_archive":
            from .battle_archive import validate_battle_archive_request
            validate_battle_archive_request(message[key])
        elif key == "reset_history":
            from .reset_history import validate_reset_history_request
            validate_reset_history_request(message[key])
        else:
            from .trade_archive import validate_trade_archive_request
            validate_trade_archive_request(message[key])
        extra = extra | history_extensions
    if operation == "history" and card_fields.intersection(message):
        from .player_card import SUPPORTED_VERSIONS
        extra = extra | card_fields
        if type(message.get("player_card_version")) is not int or message["player_card_version"] not in SUPPORTED_VERSIONS:
            raise ProtocolError("player_card_unsupported", "unsupported Trainer Card version")
    if operation in ("execute", "resume") and "admission_sha256" in message:
        extra = extra | {"admission_sha256"}
    identity_fields = {"incarnation", "runtime_id"}
    if operation in ("claim", "cancel_admission", "admission_handoff") or ((operation in ("invite", "invite_multi", "invite_ffa", "accept") or championship_match) and identity_fields.intersection(message)):
        extra = extra | identity_fields
        _integer(message.get("incarnation"), "incarnation", 1, 0xFFFFFFFF)
        _uuid(message.get("runtime_id"), "runtime_id")
    provisional_fields = {"runtime_id", "admission_b64", "admission_receipt_b64"}
    if operation in ("execute", "resume") and provisional_fields.intersection(message):
        extra = extra | provisional_fields
    _fields(message, {"type", "request_id", "session_epoch"} | extra)
    for key in extra - {"opponents", "fingerprint", "incarnation", "response_b64", "response_id", "response_stage", "admission_sha256", "admission_b64", "admission_receipt_b64", "cleanup_receipt_b64", "cleanup_ready_b64", "handoff_receipt_b64", "admission_handoff_version", "player_card_version", "championship", "rival", "battle_archive", "reset_history", "trade_archive"}:
        _uuid(message[key], key)
    if operation == "execute":
        from .battle_execution_protocol import validate_execution_request
        validate_execution_request(message)
    elif operation == "resume":
        from .battle_recovery_protocol import validate_recovery_request
        validate_recovery_request(message)
    elif operation == "cancel_admission":
        from .battle_execution_protocol import decode_control
        from .native_battle import Opcode
        for key, opcode in (("cleanup_ready_b64", Opcode.ADMISSION_CANCEL_READY),
                            ("cleanup_receipt_b64", Opcode.ADMISSION_CANCEL_HOLD)):
            if key == "cleanup_receipt_b64" and message[key] is None:
                continue
            receipt = decode_control(message[key], response=True)
            if receipt.opcode != opcode or receipt.status:
                raise ProtocolError("invalid_field", "cleanup needs its exact successful native readiness/hold receipt")
    elif operation == "admission_handoff":
        from .battle_execution_protocol import decode_control
        from .native_battle import Opcode
        from .battle_admission_cleanup_protocol import AdmissionCancellation
        receipt = decode_control(message["handoff_receipt_b64"], response=True)
        if receipt.opcode != Opcode.ADMISSION_CANCEL_HANDOFF or receipt.status:
            raise ProtocolError("invalid_field", "handoff needs the successful original native receipt")
        decode_control(message["handoff_receipt_b64"])  # Preserve normal RPC errors for malformed command fields.
        cancellation = AdmissionCancellation.unpack(receipt.data)
        if ((receipt.battle_id, receipt.incarnation, cancellation.admission.generation,
                cancellation.admission.runtime_id) != (message["battle_id"], message["incarnation"],
                message["generation"], message["runtime_id"]) or receipt.session_epoch > epoch):
            raise ProtocolError("identity_mismatch", "handoff changed its original admission or lease")
    if "opponents" in extra and operation == "invite_ffa":
        opponents = message["opponents"]
        if type(opponents) is not list or len(opponents) != 3:
            raise ProtocolError("invalid_field", "a free-for-all requires three other trainers")
        for opponent in opponents:
            _uuid(opponent, "opponent")
        if len(set(opponents)) != 3:
            raise ProtocolError("invalid_field", "free-for-all participants must be distinct")
    elif "opponents" in extra:
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
    result = dict(scope=SCOPE, battle_id=view["battle_id"], generation=view["generation"],
        sender=view["sender"], mode=mode, state=view["state"], reason=view["reason"],
        players=list(view["players"]), fingerprint=view["fingerprint"],
        consent=list(view["consent"]), outcome=view["outcome"],
        checkpoints=[dict(cp) for cp in view["checkpoints"]])
    if mode == 4:
        result["gym"] = view["gym"]  # co-op Gym: which Leader and partner
    if view.get("environment"):
        result["environment"] = view["environment"]  # Update 31: a rival checkpoint battle and its battle environment
    return result


def _view(value, actor):
    if type(value) is not dict:
        raise ProtocolError("invalid_server_message", "invalid battle challenge")
    coop = value.get("mode") == 4
    rival = "environment" in value and value.get("mode") in (2, 3)
    _fields(value, {"scope", "battle_id", "generation", "sender", "mode", "state",
                    "reason", "players", "fingerprint", "consent", "outcome", "checkpoints"}
            | ({"gym"} if coop else set()) | ({"environment"} if rival else set()))
    for key in ("battle_id", "generation", "sender"):
        _uuid(value[key], key)
    _digest(value["fingerprint"])
    if value["scope"] != SCOPE or type(value["mode"]) is not int or value["mode"] not in (2, 3, 4, 5):
        raise ProtocolError("invalid_server_message", "unsupported battle challenge format")
    if coop:
        if not valid_code(value["gym"]):
            raise ProtocolError("invalid_server_message", "invalid co-op battle code")
    if rival and not valid_preparation_word(value["environment"]):
        raise ProtocolError("invalid_server_message", "invalid rival checkpoint battle")
    count = 4 if value["mode"] in (3, 5) else 2
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
    # A free-for-all names its winner (slot + 1, 1-4) or a draw (5); every other format has a team result 1-3.
    if outcome is not None and (type(outcome) is not int or outcome not in ((1, 2, 3, 4, 5) if value["mode"] == 5 else (1, 2, 3))):
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
        card_fields = {"player_card_version", "player_card"}
        has_card = bool(card_fields.intersection(message))
        has_championship = "championship" in message
        has_rival = "rival" in message
        has_handoff = "admission_handoff_version" in message
        history_extensions = {"battle_archive", "reset_history", "trade_archive"}.intersection(message)
        _fields(message, common | {"result"} | (card_fields if has_card else set())
                | ({"championship"} if has_championship else set()) | ({"rival"} if has_rival else set())
                | ({"admission_handoff_version"} if has_handoff else set()) | history_extensions)
        if history_extensions:
            if op != "history" or len(history_extensions) != 1 or has_card:
                raise ProtocolError("invalid_server_message", "invalid private history extension")
            key = next(iter(history_extensions))
            requested = request.get(key) if request is not None else None
            if key == "battle_archive":
                from .battle_archive import validate_battle_archive_reply
                validate_battle_archive_reply(message[key], actor, requested)
            elif key == "reset_history":
                from .reset_history import validate_reset_history_reply
                validate_reset_history_reply(message[key], requested)
            else:
                from .trade_archive import validate_trade_archive_reply
                validate_trade_archive_reply(message[key], actor, requested)
        if has_rival:
            from .rival_protocol import validate_rival_reply
            if op != "pending" or has_championship:
                raise ProtocolError("invalid_server_message", "invalid rival checkpoint response extension")
            validate_rival_reply(message["rival"], actor)
        if has_handoff and (op != "pending" or has_championship or has_rival
                or type(message["admission_handoff_version"]) is not int or message["admission_handoff_version"] != 1):
            raise ProtocolError("invalid_server_message", "invalid admission handoff capability")
        if has_championship:
            from .championship_protocol import validate_championship_reply
            if op != "pending":
                raise ProtocolError("invalid_server_message", "invalid Championship response extension")
            validate_championship_reply(message["championship"], actor)
        if has_card:
            from .player_card import SUPPORTED_VERSIONS, validate_player_card
            if (op != "history" or type(message["player_card_version"]) is not int
                    or message["player_card_version"] not in SUPPORTED_VERSIONS):
                raise ProtocolError("invalid_server_message", "invalid Trainer Card response extension")
            target = message["player_card"].get("player_id") if type(message["player_card"]) is dict else None
            validate_player_card(message["player_card"], actor, target)
            if message["player_card"]["version"] != message["player_card_version"]:
                raise ProtocolError("invalid_server_message", "Trainer Card version differs from its envelope")
        result = message["result"]
        if op == "cancel_admission":
            from .battle_admission_cleanup_protocol import validate_cancellation_view
            validate_cancellation_view(result, actor, request)
        elif op == "admission_handoff":
            from .battle_admission_cleanup_protocol import validate_handoff_view
            validate_handoff_view(result, actor, request)
        elif op == "resume":
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
        if message["type"] == "battle_result" and op == "pending":
            if ("admission_handoff_version" in request) != ("admission_handoff_version" in message):
                raise ProtocolError("invalid_server_message", "admission handoff capability was omitted or unsolicited")
            requested = "championship" in request
            if requested != ("championship" in message):
                raise ProtocolError("invalid_server_message", "Championship extension was omitted or unsolicited")
            if requested:
                from .championship_protocol import validate_championship_reply
                validate_championship_reply(message["championship"], actor, request["championship"])
            requested = "rival" in request
            if requested != ("rival" in message):
                raise ProtocolError("invalid_server_message", "rival checkpoint extension was omitted or unsolicited")
            if requested:
                from .rival_protocol import validate_rival_reply
                validate_rival_reply(message["rival"], actor, request["rival"])
        if message["type"] == "battle_result" and op == "history":
            extensions = {"battle_archive", "reset_history", "trade_archive"}
            if extensions.intersection(message) != extensions.intersection(request):
                raise ProtocolError("invalid_server_message", "private history extension was omitted or unsolicited")
            requested = "player_card_version" in request
            if requested != ("player_card_version" in message):
                raise ProtocolError("invalid_server_message", "Trainer Card extension was omitted or unsolicited")
            if requested:
                from .player_card import validate_player_card
                if message["player_card_version"] != request["player_card_version"]:
                    raise ProtocolError("invalid_server_message", "Trainer Card changed the requested version")
                validate_player_card(message["player_card"], actor, request["card_player"])
        if message["type"] == "battle_result" and op not in ("pending", "history", "waiting", "execute", "resume", "cancel_admission", "admission_handoff"):
            result = message["result"]
            if result["battle_id"] != request["battle_id"]:
                raise ProtocolError("identity_mismatch", "battle reply changed the target")
            for key in ("generation", "fingerprint"):
                if key in request and result[key] != request[key]:
                    raise ProtocolError("identity_mismatch", "battle reply changed the accepted challenge")
            if op == "invite_ffa":
                if (result["sender"] != actor or set(result["players"]) != {actor, *request["opponents"]}
                        or result["mode"] != 5 or result["players"][0] != actor):
                    raise ProtocolError("identity_mismatch", "free-for-all invitation changed its participants")
            if op in ("invite", "invite_multi"):
                expected = {actor, request["peer"]} if op == "invite" else {actor, request["teammate"], *request["opponents"]}
                if result["sender"] != actor or set(result["players"]) != expected or result["mode"] != (2 if op == "invite" else 3):
                    raise ProtocolError("identity_mismatch", "battle invitation changed its participants")
                if op == "invite_multi":
                    own = set(result["players"][::2])
                    if own != {actor, request["teammate"]}:
                        raise ProtocolError("identity_mismatch", "battle invitation changed the teams")
    return message
