"""Bounded rival-checkpoint extension of the authenticated battle pending RPC.

A Start Now vote is not native battle consent: the host only issues an
ordinary challenge, which every trainer still accepts and enters through the
existing Challenges flow. Only a released native result completes a match.
Clients never submit outcomes, rewards or story flags through this interface.
"""
from __future__ import annotations

from .protocol import MAX_COUNTER, ProtocolError, _fields, _integer
from .rival_catalogue import IDS
from .rival_formats import FORMATS, MODE_MULTI, MODE_SINGLES
from .team_protocol import _uuid

VERSION = 1
OPERATIONS = frozenset({"status", "vote", "match", "recover", "continue"})
CHOICES = frozenset({"start", "wait"})
VIA = frozenset({"battle", "catch_up", "solo"})
VIEW_STATES = frozenset({"open", "countdown", "battling", "completed"})
SESSION_STATES = frozenset({"active", "completed", "canceled"})
MATCH_STATES = frozenset({"pending", "ready", "invited", "playing", "waiting", "resolved", "void"})
MAX_PLAYERS = 4


def _fail(message):
    raise ProtocolError("invalid_server_message", message)


def _text(value, limit, what):
    if type(value) is not str or not 1 <= len(value) <= limit or not value.isprintable():
        _fail(f"rival {what} text is invalid")


def _bool(value, what):
    if type(value) is not bool:
        _fail(f"rival {what} must be a boolean")


def _checkpoint(value):
    if type(value) is not str or value not in IDS:
        raise ProtocolError("invalid_field", "unknown rival checkpoint")


def _player_list(value, what, *, low=1, high=MAX_PLAYERS):
    if type(value) is not list or not low <= len(value) <= high:
        _fail(f"rival {what} has an invalid size")
    for player in value:
        _uuid(player, f"rival {what}")
    if len(set(value)) != len(value):
        _fail(f"rival {what} repeats a trainer")


def validate_rival_request(value):
    """Validate the nested extension; the outer battle RPC owns authentication."""
    if type(value) is not dict or type(value.get("version")) is not int or value["version"] != VERSION:
        raise ProtocolError("rival_unsupported", "unsupported rival checkpoint version")
    operation = value.get("operation")
    if type(operation) is not str or operation not in OPERATIONS:
        raise ProtocolError("invalid_field", "unsupported rival checkpoint operation")
    extra = {
        "status": set(),
        "vote": {"checkpoint_id", "choice"},
        "match": {"checkpoint_id", "session_id", "match", "attempt"},
        "recover": {"checkpoint_id", "session_id", "match", "attempt", "battle_id"},
        "continue": {"checkpoint_id", "via"},
    }[operation]
    _fields(value, {"version", "operation"} | extra)
    if "checkpoint_id" in extra:
        _checkpoint(value["checkpoint_id"])
    for key in ("session_id", "battle_id"):
        if key in extra:
            _uuid(value[key], key)
    if operation == "vote" and (type(value["choice"]) is not str or value["choice"] not in CHOICES):
        raise ProtocolError("invalid_field", "a rival vote is start or wait")
    if operation == "continue" and (type(value["via"]) is not str or value["via"] not in {"catch_up", "solo"}):
        raise ProtocolError("invalid_field", "continue is catch_up or solo")
    if operation in {"match", "recover"}:
        _integer(value["match"], "rival match", 0, 2)
        _integer(value["attempt"], "rival match attempt", int(operation == "recover"), MAX_COUNTER)
    return value


def _match(value, index):
    _fields(value, {"index", "mode", "teams", "attempt", "battle_id", "state", "winners"})
    if type(value["index"]) is not int or value["index"] != index:
        _fail("rival matches changed order")
    if type(value["mode"]) is not int or value["mode"] not in (MODE_SINGLES, MODE_MULTI):
        _fail("rival match mode is not a supported native battle")
    teams = value["teams"]
    size = 1 if value["mode"] == MODE_SINGLES else 2
    if type(teams) is not list or len(teams) != 2:
        _fail("a rival match has two sides")
    for team in teams:
        _player_list(team, "team", low=size, high=size)
    if set(teams[0]) & set(teams[1]):
        _fail("a trainer is on both sides")
    attempt = _integer(value["attempt"], "rival match attempt", 0, MAX_COUNTER)
    state = value["state"]
    if type(state) is not str or state not in MATCH_STATES:
        _fail("rival match state is invalid")
    if attempt:
        _uuid(value["battle_id"], "rival battle")
    elif value["battle_id"] is not None or state not in {"pending", "ready", "void"}:
        _fail("an unissued rival match claims battle progress")
    winners = value["winners"]
    if type(winners) is not list:
        _fail("rival winners must be a list")
    if winners:
        if state != "resolved" or sorted(winners) not in (sorted(teams[0]), sorted(teams[1])):
            _fail("rival winners are not one resolved side")


def _session(value):
    _fields(value, {"session_id", "format", "players", "names", "state", "matches"})
    _uuid(value["session_id"], "rival session")
    if type(value["format"]) is not str or value["format"] not in FORMATS:
        _fail("rival format is invalid")
    _player_list(value["players"], "session", low=2)
    if type(value["names"]) is not list or len(value["names"]) != len(value["players"]):
        _fail("rival session names do not match its trainers")
    for name in value["names"]:
        _text(name, 24, "name")
    if type(value["state"]) is not str or value["state"] not in SESSION_STATES:
        _fail("rival session state is invalid")
    matches = value["matches"]
    expected = {"singles": 1, "round_robin": 3, "multi": 1}[value["format"]]
    if type(matches) is not list or len(matches) != expected:
        _fail("rival session has the wrong number of matches")
    battles = []
    for index, match in enumerate(matches):
        _match(match, index)
        if not set(match["teams"][0] + match["teams"][1]) <= set(value["players"]):
            _fail("a rival match names a trainer outside its session")
        if match["battle_id"] is not None:
            battles.append(match["battle_id"])
    if len(set(battles)) != len(battles):
        _fail("rival matches share a battle")


def _completion(value):
    _fields(value, {"session_id", "format", "players", "winners", "standings"})
    _uuid(value["session_id"], "rival completion")
    if type(value["format"]) is not str or value["format"] not in FORMATS:
        _fail("rival completion format is invalid")
    _player_list(value["players"], "completion", low=2)
    if type(value["winners"]) is not list or not set(value["winners"]) <= set(value["players"]):
        _fail("rival completion winners are not participants")
    standings = value["standings"]
    if type(standings) is not list or len(standings) != len(value["players"]):
        _fail("rival standings do not cover the participants")
    for row in standings:
        _fields(row, {"player_id", "name", "wins", "losses", "draws"})
        if row["player_id"] not in value["players"]:
            _fail("rival standings name an outsider")
        _text(row["name"], 24, "standing name")
        for key in ("wins", "losses", "draws"):
            _integer(row[key], f"rival {key}", 0, 3)


def _view(value, actor):
    _fields(value, {"checkpoint_id", "title", "mandatory", "declinable", "state", "message", "present",
                    "others_online", "countdown_ms", "grace_ms", "can_start", "can_wait", "can_solo",
                    "can_catch_up", "session", "completion", "cleared", "via"})
    _checkpoint(value["checkpoint_id"])
    _text(value["title"], 16, "title")
    _text(value["message"], 32, "message")
    for key in ("mandatory", "declinable", "can_start", "can_wait", "can_solo", "can_catch_up", "cleared"):
        _bool(value[key], key)
    if type(value["state"]) is not str or value["state"] not in VIEW_STATES:
        _fail("rival checkpoint state is invalid")
    present = value["present"]
    if type(present) is not list or len(present) > MAX_PLAYERS:
        _fail("rival presence list is invalid")
    for row in present:
        _fields(row, {"player_id", "name", "vote"})
        _uuid(row["player_id"], "rival present player")
        _text(row["name"], 24, "present name")
        if row["vote"] is not None and row["vote"] not in CHOICES:
            _fail("rival vote is invalid")
    if len({row["player_id"] for row in present}) != len(present):
        _fail("rival presence repeats a trainer")
    _integer(value["others_online"], "rival others online", 0, MAX_PLAYERS)
    for key in ("countdown_ms", "grace_ms"):
        if value[key] is not None:
            _integer(value[key], f"rival {key}", 0, 3_600_000)
    if (value["countdown_ms"] is None) != (value["state"] != "countdown"):
        _fail("rival countdown does not match its state")
    if value["session"] is not None:
        _session(value["session"])
    if value["completion"] is not None:
        _completion(value["completion"])
    if (value["completion"] is not None) != (value["state"] == "completed"):
        _fail("rival completion does not match its state")
    if value["via"] is not None and value["via"] not in VIA:
        _fail("rival clear route is invalid")
    if value["cleared"] != (value["via"] is not None):
        _fail("rival clear flag and route disagree")
    if value["can_start"] and (value["state"] in {"battling", "completed"} or actor not in
                               {row["player_id"] for row in present}):
        _fail("rival Start offered outside an open lobby")


def _summary(value):
    _fields(value, {"checkpoint_id", "completed", "cleared", "via"})
    _checkpoint(value["checkpoint_id"])
    _bool(value["completed"], "completed")
    _bool(value["cleared"], "cleared")
    if value["via"] is not None and value["via"] not in VIA:
        _fail("rival clear route is invalid")
    if value["cleared"] != (value["via"] is not None):
        _fail("rival clear flag and route disagree")


def validate_rival_reply(value, actor, request=None):
    _fields(value, {"version", "operation", "here", "checkpoints"})
    if type(value["version"]) is not int or value["version"] != VERSION:
        _fail("unsupported rival checkpoint response version")
    if type(value["operation"]) is not str or value["operation"] not in OPERATIONS:
        _fail("unsupported rival checkpoint response operation")
    if value["here"] is not None:
        _view(value["here"], actor)
    checkpoints = value["checkpoints"]
    if type(checkpoints) is not list or [row.get("checkpoint_id") if type(row) is dict else None
                                          for row in checkpoints] != list(IDS):
        _fail("rival checkpoint summary must list every checkpoint in story order")
    for row in checkpoints:
        _summary(row)
    if request is not None:
        validate_rival_request(request)
        if value["operation"] != request["operation"]:
            _fail("rival response does not match the request operation")
        if "checkpoint_id" in request and request["operation"] != "continue":
            here = value["here"]
            if here is None or here["checkpoint_id"] != request["checkpoint_id"]:
                raise ProtocolError("identity_mismatch", "rival response changed the checkpoint")
        if request["operation"] == "match":
            session = value["here"]["session"]
            if session is None or session["session_id"] != request["session_id"]:
                raise ProtocolError("identity_mismatch", "rival response changed the session")
    return value
