"""Wire validation for the protocol-2 shared-world extensions."""
from __future__ import annotations

import re
import uuid
from typing import Any

from .protocol import MAX_COUNTER, ProtocolError

WORLD_TYPES = frozenset({"world_action", "appearance_get", "appearance_set", "friendship_get",
                         "wager_get", "wager_set", "wager_accept", "wager_decline", "wallet_applied",
                         "gym_coop", "spawn_action", "base_publish", "base_visibility", "base_get", "frontier", "habitat_get"})
ACTIONS = frozenset({"claim", "result", "release"})
RESULTS = frozenset({"caught", "defeated", "ran", "lost", "cancelled"})
_HEX16 = re.compile(r"[0-9a-f]{16}\Z")
_BASE_HEX = re.compile(r"[0-9a-f]{320}\Z")
_EVENT_FIELDS = {"event_id", "species", "level", "shiny", "mega", "map_group", "map_number", "x", "y",
                 "held_item", "perfect_ivs", "seconds_left", "claimant"}
FRONTIER_OPS = frozenset({"status", "propose", "accept", "cancel", "retire", "battle", "shop_buy", "bring"})
SPAWN_ACTIONS = frozenset({"claim", "result", "release"})
SPAWN_RESULTS = frozenset({"caught", "defeated", "ran", "lost", "cancelled"})
SPAWN_KINDS = frozenset({"normal", "outbreak"})
_SPAWN_FIELDS = {"spawn_id", "species", "level", "personality", "shiny", "form", "kind", "x", "y", "facing",
                 "move_seq", "mine", "busy", "fresh", "seconds_left"}
MAX_SPAWN_SLOTS = 12


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


def validate_spawns(value: Any) -> dict | None:
    """The shared wild Pokemon of the map this player stands on (protocol 3)."""
    if value is None:
        return None
    if type(value) is not dict or set(value) != {"map_group", "map_number", "shared", "slots"}:
        raise ProtocolError("invalid_server_message", "invalid shared spawns")
    _int(value["map_group"], "spawn map group", 0, 255)
    _int(value["map_number"], "spawn map number", 0, 255)
    if type(value["shared"]) is not bool:
        raise ProtocolError("invalid_server_message", "invalid shared spawn coverage")
    slots = value["slots"]
    if type(slots) is not list or len(slots) > MAX_SPAWN_SLOTS:
        raise ProtocolError("invalid_server_message", "too many shared spawns")
    if slots and not value["shared"]:
        raise ProtocolError("invalid_server_message", "shared spawns on a map without them")
    seen = set()
    for slot in slots:
        if type(slot) is not dict or set(slot) != _SPAWN_FIELDS:
            raise ProtocolError("invalid_server_message", "invalid shared spawn")
        _int(slot["spawn_id"], "spawn id", 1, MAX_COUNTER)
        if slot["spawn_id"] in seen:
            raise ProtocolError("invalid_server_message", "duplicate shared spawn")
        seen.add(slot["spawn_id"])
        _int(slot["species"], "spawn species", 1, 1700)
        _int(slot["level"], "spawn level", 1, 100)
        _int(slot["personality"], "spawn personality", 0, 0xFFFFFFFF)
        _int(slot["form"], "spawn form", 0, 255)
        _int(slot["x"], "spawn x", 0, 32767)
        _int(slot["y"], "spawn y", 0, 32767)
        _int(slot["facing"], "spawn facing", 1, 4)
        _int(slot["move_seq"], "spawn move", 0, 255)
        _int(slot["seconds_left"], "spawn timer", 0, 0xFFFFFFFF)
        if slot["kind"] not in SPAWN_KINDS:
            raise ProtocolError("invalid_server_message", "invalid shared spawn kind")
        for flag in ("shiny", "mine", "busy", "fresh"):
            if type(slot[flag]) is not bool:
                raise ProtocolError("invalid_server_message", "invalid shared spawn flags")
        if slot["mine"] and slot["busy"]:
            raise ProtocolError("invalid_server_message", "a shared spawn is either mine or busy")
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


def validate_wallet(value: Any) -> dict | None:
    """This player's next wager wallet adjustment (per-player world field)."""
    if value is None:
        return None
    if type(value) is not dict or set(value) != {"seq", "delta"}:
        raise ProtocolError("invalid_server_message", "invalid wallet adjustment")
    _int(value["seq"], "wallet sequence", 1, 0xFFFF)
    from .rewards import valid_wallet_delta
    if type(value["delta"]) is not int or not valid_wallet_delta(value["delta"]):
        raise ProtocolError("invalid_server_message", "a wallet adjustment moves money, Battle Points or an item")
    return value


def validate_teammate(value: Any) -> str | None:
    """This player's connected host-formed teammate (per-player world field)."""
    if value is None:
        return None
    return _uuid(value, "teammate")


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
    elif kind == "spawn_action":
        expected = {"type", "session_epoch", "request_id", "action", "spawn_id", "result", "seq"}
        if set(message) != expected:
            raise ProtocolError("invalid_fields", "spawn action has missing or unexpected fields")
        if message["action"] not in SPAWN_ACTIONS:
            raise ProtocolError("invalid_field", "unsupported spawn action")
        _int(message["spawn_id"], "spawn id", 1, MAX_COUNTER)
        _int(message["seq"], "action seq", 1, 0xFFFFFFFF)
        if message["action"] == "result":
            if message["result"] not in SPAWN_RESULTS:
                raise ProtocolError("invalid_field", "unsupported spawn result")
        elif message["result"] is not None:
            raise ProtocolError("invalid_field", "only results carry an outcome")
    elif kind == "base_publish":
        if set(message) != {"type", "session_epoch", "request_id", "seq", "base"}:
            raise ProtocolError("invalid_fields", "secret base publication has unexpected fields")
        _int(message["seq"], "base sequence", 1, 0xFFFFFFFF)
        if message["base"] is not None and (type(message["base"]) is not str
                                            or _BASE_HEX.fullmatch(message["base"]) is None):
            raise ProtocolError("invalid_field", "secret base must be 320 lower-case hex digits")
    elif kind == "frontier":
        base = {"type", "session_epoch", "request_id", "op"}
        if set(message) not in (base, base | {"incarnation", "runtime_id"}, base | {"mode"}, base | {"slot"}, base | {"mask"}):
            raise ProtocolError("invalid_fields", "Frontier request has unexpected fields")
        if message["op"] not in FRONTIER_OPS:
            raise ProtocolError("invalid_field", "unsupported Frontier operation")
        if "incarnation" in message:
            _int(message["incarnation"], "native incarnation", 1, 0xFFFFFFFF)
            _uuid(message["runtime_id"], "native runtime")
        if "mode" in message and (message["op"] != "propose" or message["mode"] not in ("frontier", "league")):
            raise ProtocolError("invalid_field", "unsupported Frontier mode")
        if "slot" in message:
            if message["op"] != "shop_buy":
                raise ProtocolError("invalid_field", "only a purchase names a shop slot")
            _int(message["slot"], "shop slot", 0, 31)
        elif message["op"] == "shop_buy":
            raise ProtocolError("invalid_field", "a purchase names a shop slot")
        if "mask" in message:
            if message["op"] != "bring":
                raise ProtocolError("invalid_field", "only a team selection names a mask")
            _int(message["mask"], "team mask", 0, 63)
        elif message["op"] == "bring":
            raise ProtocolError("invalid_field", "a team selection names a mask")
    elif kind == "base_visibility":
        if set(message) != {"type", "session_epoch", "request_id", "mode"}:
            raise ProtocolError("invalid_fields", "secret base visibility has unexpected fields")
        if message["mode"] not in ("everyone", "team", "nobody"):
            raise ProtocolError("invalid_field", "unsupported secret base visibility")
    elif kind in ("appearance_get", "friendship_get", "base_get", "habitat_get"):
        if set(message) != {"type", "session_epoch", "request_id"}:
            raise ProtocolError("invalid_fields", "shared-world read has unexpected fields")
    elif kind in ("wager_get", "wager_decline"):
        if set(message) != {"type", "session_epoch", "request_id", "battle_id"}:
            raise ProtocolError("invalid_fields", "wager request has unexpected fields")
        _uuid(message["battle_id"], "battle_id")
    elif kind in ("wager_set", "wager_accept"):
        if set(message) != {"type", "session_epoch", "request_id", "battle_id", "amount"}:
            raise ProtocolError("invalid_fields", "wager request has unexpected fields")
        _uuid(message["battle_id"], "battle_id")
        _int(message["amount"], "wager amount", 0, 999_999)
    elif kind == "gym_coop":
        # The requesting game's native core (incarnation and runtime_id), as a
        # battle invite carries it: the request is the challenger's consent, and
        # native admission needs that consent bound to its original core.
        base = {"type", "session_epoch", "request_id", "gym"}
        if set(message) not in (base, base | {"incarnation", "runtime_id"}):
            raise ProtocolError("invalid_fields", "co-op Gym request has unexpected fields")
        _int(message["gym"], "co-op Gym", 1, 8)
        if "incarnation" in message:
            _int(message["incarnation"], "native incarnation", 1, 0xFFFFFFFF)
            _uuid(message["runtime_id"], "native runtime")
    elif kind == "wallet_applied":
        if set(message) != {"type", "session_epoch", "request_id", "seq", "amount"}:
            raise ProtocolError("invalid_fields", "wallet receipt has unexpected fields")
        _int(message["seq"], "wallet sequence", 1, 0xFFFF)
        _int(message["amount"], "wallet amount", 0, 999_999)
    else:
        if set(message) != {"type", "session_epoch", "request_id", "appearance"}:
            raise ProtocolError("invalid_fields", "appearance update has unexpected fields")
        if validate_appearance_hex(message["appearance"]) is None:
            raise ProtocolError("invalid_field", "appearance is required")
    return message


def _short_text(value: Any, name: str, limit: int = 40) -> str:
    if type(value) is not str or not 0 < len(value) <= limit or any(not 32 <= ord(c) <= 126 for c in value):
        raise ProtocolError("invalid_server_message", f"invalid {name}")
    return value


def validate_extras(value: Any) -> dict | None:
    """The host's secret bases for this player and the PokeNav world view
    (Phases 6 and 7). Absent from older hosts."""
    if value is None:
        return None
    if type(value) is not dict or set(value) != {"bases", "nav"}:
        raise ProtocolError("invalid_server_message", "invalid world extras")
    bases = value["bases"]
    if type(bases) is not list or len(bases) > 6:
        raise ProtocolError("invalid_server_message", "too many secret bases")
    for item in bases:
        if type(item) is not dict or set(item) != {"owner", "slot", "record"}:
            raise ProtocolError("invalid_server_message", "invalid secret base")
        _short_text(item["owner"], "secret base owner", 128)
        _int(item["slot"], "secret base slot", 0, 3)
        if type(item["record"]) is not str or _BASE_HEX.fullmatch(item["record"]) is None:
            raise ProtocolError("invalid_server_message", "invalid secret base record")
    nav = value["nav"]
    base_keys = {"players", "outbreak", "event"}
    if type(nav) is not dict or not base_keys <= set(nav) <= base_keys | {"rule", "time", "tod"}:
        raise ProtocolError("invalid_server_message", "invalid PokeNav view")
    if type(nav["players"]) is not list or len(nav["players"]) > 4:
        raise ProtocolError("invalid_server_message", "invalid PokeNav players")
    for player in nav["players"]:
        if type(player) is not dict or set(player) != {"player_id", "place", "weather"}:
            raise ProtocolError("invalid_server_message", "invalid PokeNav player")
        _short_text(player["player_id"], "PokeNav player", 128)
        _short_text(player["place"], "PokeNav place")
        if player["weather"] is not None:
            _short_text(player["weather"], "PokeNav weather", 20)
    if nav.get("time") is not None:
        if not isinstance(nav["time"], str) or re.fullmatch(r"\d\d:\d\d", nav["time"]) is None:
            raise ProtocolError("invalid_server_message", "invalid PokeNav time")
    if nav.get("tod") is not None:
        _short_text(nav["tod"], "PokeNav time of day", 10)
    if nav.get("rule") is not None:
        _short_text(nav["rule"], "Frontier rule", 20)
    for key in ("outbreak", "event"):
        entry = nav[key]
        if entry is None:
            continue
        if type(entry) is not dict or set(entry) not in ({"name", "place", "seconds_left"},
                                                         {"name", "place", "seconds_left", "waiting"}):
            raise ProtocolError("invalid_server_message", f"invalid PokeNav {key}")
        if "waiting" in entry:
            _short_text(entry["waiting"], "PokeNav waiting")
        _short_text(entry["name"], "PokeNav name")
        _short_text(entry["place"], "PokeNav place")
        _int(entry["seconds_left"], "PokeNav time", 0, 86_400)
    return value


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
