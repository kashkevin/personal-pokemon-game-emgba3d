"""The wireless minigames with the world's players (KNOWN_ISSUES MS-141c): the companion's requests, the host's replies
and pushes, and the game's minigame frames (the engine's src/platform/mp_minigames.c, carried by its bridge as 'm').

Berry Crush, Pokemon Jump and Dodrio Berry Picking need GBAs linked by the Wireless Adapter. On the PC the group is a
virtual wireless group over the world: the leader's game is its parent, each member's a child (the engine's NetLink),
and every frame of the link goes through the host - the leader's frame to every member, a member's command to the
leader. The lobby is session-local on the host and nothing of it is saved: a group of one leader and up to three members
(a world has four players at most) plays one game; it ends when its leader ends it, when its game ends (every player
leaves), or for everyone when one of its players disconnects once it has started.
"""
from __future__ import annotations

import re
from typing import Any

from .protocol import MAX_COUNTER, MAX_PLAYERS, PROTOCOL_VERSION, ProtocolError, _fields, _integer, validate_identity
from .team_protocol import _uuid

# name: (the game's ACTIVITY_* number, the fewest players the game takes)
ACTIVITIES = {"berry_crush": (10, 2), "pokemon_jump": (9, 2), "dodrio": (11, 3)}
GAME_ACTIVITY = {number: name for name, (number, _) in ACTIVITIES.items()}
TITLES = {"berry_crush": "BERRY CRUSH", "pokemon_jump": "POKEMON JUMP", "dodrio": "DODRIO BERRY-PICKING"}
MAX_GROUP = MAX_PLAYERS
OPERATIONS = frozenset({"status", "open", "join", "start", "leave"})
REQUEST_TYPES = frozenset("minigame_" + operation for operation in OPERATIONS)
MINIGAME_TYPES = REQUEST_TYPES | {"minigame_link"}
PUSH_TYPES = frozenset({"minigame_started", "minigame_closed", "minigame_link"})
CLOSE_REASONS = frozenset({"leader_ended", "player_lost", "host_stopped"})
PLAYER_BYTES = 16                  # a game's link player: name 8 (the game's characters), gender, language, version, id
CMD_BYTES = 14                     # a member's command of a frame
FRAME_BYTES = 5 * CMD_BYTES        # the leader's frame: every player's command
_HEX = re.compile(r"(?:[0-9a-f]{2})*\Z")
_CODE = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
GROUP_MAX = 0x7FFFFFFF

# The game's frames ('m' payloads): a link frame, or the lobby's operations.
KIND_LINK = 1
KIND_LOBBY = 2
OP_HELLO = 1      # game -> companion: [activity, link player]
OP_LEAVE = 2      # game -> companion: [reason]
LEAVE_ENDED = 0   # its game closed the group's link at its end, as every player's game does: the others are not told
LEAVE_LOST = 1    # its group's link was lost (the game's communication error)
LEAVE_LOBBY = 2   # it left the lobby: a group that has started (the start crossing the leave) ends for the others
OP_STARTED = 1    # companion -> game: [activity, players, own index, players x link player]
OP_CLOSED = 2     # companion -> game: [reason]


def _hex(value: Any, name: str, sizes: tuple[int, ...]) -> bytes:
    if not isinstance(value, str) or _HEX.fullmatch(value) is None or len(value) // 2 not in sizes:
        raise ProtocolError("invalid_field", f"{name} must be lowercase hex of {' or '.join(map(str, sizes))} bytes")
    return bytes.fromhex(value)


def link_player(value: Any) -> bytes:
    """A game's link player (16 bytes as lowercase hex): its name in the game's characters (8 bytes, ended by 0xFF unless
    all 7 are used), gender 0 or 1, language 1-7, version, trainer id."""
    raw = _hex(value, "link_player", (PLAYER_BYTES,))
    if raw[8] not in (0, 1) or not 1 <= raw[9] <= 7 or raw[0] == 0xFF:
        raise ProtocolError("invalid_field", "link_player has an invalid name, gender or language")
    return raw


def _activity(value: Any) -> str:
    if not isinstance(value, str) or value not in ACTIVITIES:
        raise ProtocolError("invalid_field", "unknown minigame")
    return value


def validate_minigame_request(message: Any, session_epoch: int) -> dict[str, Any]:
    """A companion's request (with a request_id, answered) or a link frame (minigame_link, never answered)."""
    if not isinstance(message, dict) or message.get("type") not in MINIGAME_TYPES:
        raise ProtocolError("invalid_type", "unsupported minigame operation")
    if _integer(message.get("session_epoch"), "session_epoch", 1, MAX_COUNTER) != session_epoch:
        raise ProtocolError("session_epoch_mismatch", "minigame request belongs to another authenticated lease")
    kind = message["type"]
    if kind == "minigame_link":
        _fields(message, {"type", "session_epoch", "group_id", "data"})
        _integer(message["group_id"], "group_id", 1, GROUP_MAX)
        _hex(message["data"], "data", (0, CMD_BYTES, FRAME_BYTES))
        return dict(message)
    extra = {"minigame_status": {"activity"}, "minigame_open": {"activity", "link_player"},
             "minigame_join": {"group_id", "link_player"}, "minigame_start": {"group_id"},
             "minigame_leave": {"group_id", "lost"}}[kind]
    _fields(message, {"type", "session_epoch", "request_id"} | extra)
    _uuid(message["request_id"], "request_id")
    if "activity" in extra:
        _activity(message["activity"])
    if "group_id" in extra:
        _integer(message["group_id"], "group_id", 0 if kind == "minigame_leave" else 1, GROUP_MAX)
    if "link_player" in extra:
        link_player(message["link_player"])
    if "lost" in extra and type(message["lost"]) is not bool:
        # lost: the player's game is gone from a group that has started (or never started its link): the others' games
        # would wait for it, so the group ends for them; otherwise its game closed the link at its end, as all do
        raise ProtocolError("invalid_field", "lost must be a boolean")
    return dict(message)


def _group_view(view: Any, actor: str) -> None:
    _fields(view, {"group_id", "activity", "leader", "players", "index", "started", "minimum"})
    _integer(view["group_id"], "group_id", 1, GROUP_MAX)
    _activity(view["activity"])
    players = view["players"]
    if type(players) is not list or not 1 <= len(players) <= MAX_GROUP:
        raise ProtocolError("invalid_server_message", "a group has one to four players")
    for player in players:
        _fields(player, {"player_id", "display_name"})
        validate_identity(player["player_id"], "player_id")
        if not isinstance(player["display_name"], str) or not 1 <= len(player["display_name"]) <= 64:
            raise ProtocolError("invalid_server_message", "invalid player name")
    if players[0]["player_id"] != view["leader"]:
        raise ProtocolError("invalid_server_message", "a group's leader is its first player")
    _integer(view["index"], "index", 0, len(players) - 1)
    if players[view["index"]]["player_id"] != actor or type(view["started"]) is not bool:
        raise ProtocolError("invalid_server_message", "a group view names its reader")
    _integer(view["minimum"], "minimum", 2, MAX_GROUP)


def validate_minigame_reply(message: Any, actor: str, epoch: int, request: dict[str, Any] | None = None) -> dict:
    """A host's minigame_result or minigame_error (for ``request`` when given)."""
    common = {"type", "protocol", "session_epoch", "request_id", "operation"}
    if (not isinstance(message, dict) or message.get("type") not in ("minigame_result", "minigame_error")
            or not common <= set(message) or message["protocol"] != PROTOCOL_VERSION
            or message["session_epoch"] != epoch or message["operation"] not in OPERATIONS):
        raise ProtocolError("invalid_server_message", "invalid minigame reply envelope")
    _uuid(message["request_id"], "request_id")
    if request is not None and (message["request_id"] != request["request_id"]
                                or "minigame_" + message["operation"] != request["type"]):
        raise ProtocolError("invalid_server_message", "minigame reply does not match its request")
    if message["type"] == "minigame_error":
        _fields(message, common | {"code", "message"})
        if (not isinstance(message["code"], str) or _CODE.fullmatch(message["code"]) is None
                or not isinstance(message["message"], str) or not 1 <= len(message["message"]) <= 512):
            raise ProtocolError("invalid_server_message", "invalid minigame error")
        return dict(message)
    _fields(message, common | {"result"})
    result = message["result"]
    if message["operation"] == "status":
        _fields(result, {"activity", "groups", "mine"})
        _activity(result["activity"])
        if type(result["groups"]) is not list or len(result["groups"]) > MAX_GROUP:
            raise ProtocolError("invalid_server_message", "invalid minigame groups")
        for group in result["groups"]:
            _fields(group, {"group_id", "leader_name", "players", "minimum"})
            _integer(group["group_id"], "group_id", 1, GROUP_MAX)
            _integer(group["players"], "players", 1, MAX_GROUP)
            _integer(group["minimum"], "minimum", 2, MAX_GROUP)
            if not isinstance(group["leader_name"], str) or not 1 <= len(group["leader_name"]) <= 64:
                raise ProtocolError("invalid_server_message", "invalid group leader name")
        if result["mine"] is not None:
            _group_view(result["mine"], actor)
    elif message["operation"] in ("open", "join", "start"):
        _group_view(result, actor)
    else:
        _fields(result, {"left"})
        if type(result["left"]) is not bool:
            raise ProtocolError("invalid_server_message", "invalid minigame leave")
    return dict(message)


def validate_minigame_push(message: Any, epoch: int) -> dict[str, Any]:
    """A host's push: a group's start, its end, or a link frame of it."""
    if not isinstance(message, dict) or message.get("type") not in PUSH_TYPES or message.get("session_epoch") != epoch:
        raise ProtocolError("invalid_server_message", "invalid minigame push")
    kind = message["type"]
    if kind == "minigame_link":
        _fields(message, {"type", "session_epoch", "group_id", "source", "data"})
        _integer(message["group_id"], "group_id", 1, GROUP_MAX)
        _integer(message["source"], "source", 0, MAX_GROUP - 1)
        _hex(message["data"], "data", (0, CMD_BYTES, FRAME_BYTES))
    elif kind == "minigame_started":
        _fields(message, {"type", "protocol", "session_epoch", "group_id", "activity", "index", "link_players"})
        _integer(message["group_id"], "group_id", 1, GROUP_MAX)
        _activity(message["activity"])
        players = message["link_players"]
        if type(players) is not list or not 2 <= len(players) <= MAX_GROUP:
            raise ProtocolError("invalid_server_message", "a started group has two to four players")
        for player in players:
            link_player(player)
        _integer(message["index"], "index", 0, len(players) - 1)
    else:
        _fields(message, {"type", "protocol", "session_epoch", "group_id", "reason"})
        _integer(message["group_id"], "group_id", 1, GROUP_MAX)
        if message["reason"] not in CLOSE_REASONS:
            raise ProtocolError("invalid_server_message", "unknown reason a group closed")
    return dict(message)


# ---- the game's frames ('m') -----------------------------------------------------------------------------------------

def parse_game_frame(payload: bytes) -> tuple[str, Any]:
    """An 'm' payload from the game: ("link", bytes) or ("hello", (activity, link player bytes)) or ("leave", reason)."""
    if type(payload) is not bytes or not payload:
        raise ValueError("empty minigame frame")
    if payload[0] == KIND_LINK:
        data = payload[1:]
        if len(data) not in (0, CMD_BYTES, FRAME_BYTES):
            raise ValueError("a link frame is 0, 14 or 70 bytes")
        return "link", data
    if payload[0] != KIND_LOBBY or len(payload) < 2:
        raise ValueError("unknown minigame frame")
    if payload[1] == OP_HELLO:
        if len(payload) != 3 + PLAYER_BYTES or payload[2] not in GAME_ACTIVITY:
            raise ValueError("invalid minigame hello")
        player = payload[3:]
        link_player(player.hex())
        return "hello", (GAME_ACTIVITY[payload[2]], player)
    if payload[1] == OP_LEAVE and len(payload) == 3 and payload[2] in (LEAVE_ENDED, LEAVE_LOST, LEAVE_LOBBY):
        return "leave", payload[2]
    raise ValueError("unknown minigame lobby operation")


def started_frame(activity: str, index: int, players: list[bytes]) -> bytes:
    """The game's STARTED: [kind, op, activity, players, own index, players x link player]."""
    if activity not in ACTIVITIES or not 2 <= len(players) <= MAX_GROUP or not 0 <= index < len(players):
        raise ValueError("invalid start")
    if any(len(player) != PLAYER_BYTES for player in players):
        raise ValueError("invalid link player")
    return bytes([KIND_LOBBY, OP_STARTED, ACTIVITIES[activity][0], len(players), index]) + b"".join(players)


def closed_frame(reason: str) -> bytes:
    return bytes([KIND_LOBBY, OP_CLOSED, sorted(CLOSE_REASONS).index(reason) + 1 if reason in CLOSE_REASONS else 0])


def link_frame(source: int, data: bytes) -> bytes:
    """A link frame for the game: [kind, source, frame]."""
    if not 0 <= source < MAX_GROUP or len(data) not in (0, CMD_BYTES, FRAME_BYTES):
        raise ValueError("invalid link frame")
    return bytes([KIND_LINK, source]) + data
