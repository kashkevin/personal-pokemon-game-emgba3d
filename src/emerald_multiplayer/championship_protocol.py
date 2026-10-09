"""Bounded Championship extension of the authenticated battle pending RPC.

Bracket consent never grants native battle consent. Only the existing battle
service can issue a match, and only its durable result can advance the bracket.
This module validates public projections; it accepts no winner/save claims.
"""
from __future__ import annotations

import re

from .protocol import MAX_COUNTER, ProtocolError, _fields, _integer
from .team_protocol import _uuid

VERSION = 1
HISTORY_LIMIT = 4
OPERATIONS = frozenset({"status", "history", "create", "accept", "cancel", "match", "recover"})
STATES = frozenset({"proposed", "active", "completed", "canceled"})
MATCH_STATES = frozenset({"blocked", "ready", "invited", "playing", "waiting", "draw", "won", "canceled"})
_HASH = re.compile(r"[0-9a-f]{64}\Z")


def _fail(message):
    raise ProtocolError("invalid_server_message", message)


def _digest(value):
    if type(value) is not str or _HASH.fullmatch(value) is None:
        raise ProtocolError("invalid_field", "Championship fingerprint must be a SHA256 digest")


def _players(value, *, count=4):
    if type(value) is not list or len(value) != count:
        _fail("Championship has an incorrect participant count")
    for player in value:
        _uuid(player, "Championship participant")
    if len(set(value)) != count:
        _fail("Championship repeats a participant")


def _names(value):
    if (type(value) is not list or len(value) != 4
            or any(type(name) is not str or not 1 <= len(name) <= 24
                   or not name.strip() or not name.isprintable() for name in value)):
        _fail("Championship participant names are invalid")


def _consent(value, players):
    if (type(value) is not list or any(type(player) is not str for player in value)
            or len(value) != len(set(value)) or not set(value) <= set(players)):
        _fail("Championship consent has a foreign or repeated participant")


def validate_championship_request(value):
    """Validate the nested extension; the outer battle RPC owns authentication."""
    if (type(value) is not dict or type(value.get("version")) is not int
            or value["version"] != VERSION):
        raise ProtocolError("championship_unsupported", "unsupported Championship version")
    operation = value.get("operation")
    if type(operation) is not str or operation not in OPERATIONS:
        raise ProtocolError("invalid_field", "unsupported Championship operation")
    extra = {
        "status": set(), "history": set(),
        "create": {"championship_id", "players"},
        "accept": {"championship_id", "generation", "fingerprint"},
        "cancel": {"championship_id", "generation", "fingerprint"},
        "match": {"championship_id", "generation", "fingerprint", "round", "attempt"},
        "recover": {"championship_id", "generation", "fingerprint", "round", "attempt", "battle_id"},
    }[operation]
    _fields(value, {"version", "operation"} | extra)
    for key in ("championship_id", "generation", "battle_id"):
        if key in extra:
            _uuid(value[key], key)
    if "fingerprint" in extra:
        _digest(value["fingerprint"])
    if operation == "create":
        _players(value["players"])
    if operation in {"match", "recover"}:
        _integer(value["round"], "Championship round", 0, 2)
        _integer(value["attempt"], "Championship match attempt", int(operation == "recover"), MAX_COUNTER)
    return value


def _match(value, index, players):
    _fields(value, {"round", "players", "attempt", "battle_id", "state", "winner"})
    if type(value["round"]) is not int or value["round"] != index:
        _fail("Championship rounds changed order")
    if type(value["players"]) is not list or value["players"] != players:
        _fail("Championship match changed its bracket participants")
    if players:
        _players(players, count=2)
    attempt = _integer(value["attempt"], "Championship match attempt", 0, MAX_COUNTER)
    state = value["state"]
    if type(state) is not str or state not in MATCH_STATES:
        _fail("Championship match state is invalid")
    if attempt:
        _uuid(value["battle_id"], "Championship battle")
        if not players or state in {"blocked", "ready"}:
            _fail("Issued Championship match has no valid execution state")
    elif value["battle_id"] is not None or state not in {"blocked", "ready"}:
        _fail("Unissued Championship match claims battle progress")
    if not players and state != "blocked":
        _fail("Championship final is not waiting for both semifinal winners")
    if state == "won":
        if value["winner"] not in players:
            _fail("Championship match winner was not a participant")
    elif value["winner"] is not None:
        _fail("Unsettled Championship match claims a winner")


def validate_championship_view(value, actor):
    _fields(value, {"championship_id", "generation", "fingerprint", "sender", "players", "names",
                    "state", "consent", "cancel_consent", "champion", "matches"})
    for key in ("championship_id", "generation", "sender"):
        _uuid(value[key], key)
    _digest(value["fingerprint"])
    players = value["players"]
    _players(players)
    _names(value["names"])
    if actor not in players or value["sender"] != players[0]:
        raise ProtocolError("identity_mismatch", "Championship belongs to other participants")
    state = value["state"]
    if type(state) is not str or state not in STATES:
        _fail("Championship state is invalid")
    _consent(value["consent"], players)
    _consent(value["cancel_consent"], players)
    if value["sender"] not in value["consent"]:
        _fail("Championship proposal omits its proposer's explicit consent")
    if state in {"active", "completed"} and set(value["consent"]) != set(players):
        _fail("Championship became active without all four consents")
    matches = value["matches"]
    if type(matches) is not list or len(matches) != 3:
        _fail("Championship requires two semifinals and one final")
    _match(matches[0], 0, players[:2])
    _match(matches[1], 1, players[2:])
    finalists = ([matches[0]["winner"], matches[1]["winner"]]
                 if all(match["state"] == "won" for match in matches[:2]) else [])
    _match(matches[2], 2, finalists)
    issued = [match["battle_id"] for match in matches if match["battle_id"] is not None]
    if len(set(issued)) != len(issued):
        _fail("Championship rounds share a battle identity")
    if state == "proposed" and any(match["attempt"] for match in matches):
        _fail("Championship started a match before bracket consent")
    if state == "completed":
        if matches[2]["state"] != "won" or value["champion"] != matches[2]["winner"]:
            _fail("Championship champion differs from the settled final")
    elif value["champion"] is not None or matches[2]["state"] == "won":
        _fail("Incomplete Championship claims a final winner")
    return value


def _summary(value, actor):
    _fields(value, {"championship_id", "players", "names", "champion", "state"})
    _uuid(value["championship_id"], "Championship history ID")
    _players(value["players"])
    _names(value["names"])
    if actor not in value["players"]:
        raise ProtocolError("identity_mismatch", "Championship history belongs to another player")
    if type(value["state"]) is not str or value["state"] not in {"completed", "canceled"}:
        _fail("Championship history contains an unsettled bracket")
    if value["state"] == "completed":
        if value["champion"] not in value["players"]:
            _fail("Championship history winner was not a participant")
    elif value["champion"] is not None:
        _fail("Canceled Championship history claims a champion")


def validate_championship_reply(value, actor, request=None):
    """Validate only public bracket data and its exact request correlation."""
    _fields(value, {"version", "operation", "current", "history"})
    if type(value["version"]) is not int or value["version"] != VERSION:
        _fail("Unsupported Championship response version")
    if type(value["operation"]) is not str or value["operation"] not in OPERATIONS:
        _fail("Unsupported Championship response operation")
    current = value["current"]
    if current is not None:
        validate_championship_view(current, actor)
    history = value["history"]
    if type(history) is not list or len(history) > HISTORY_LIMIT:
        _fail("Championship history exceeds its bounded limit")
    for summary in history:
        _summary(summary, actor)
    ids = [summary["championship_id"] for summary in history]
    if len(set(ids)) != len(ids):
        _fail("Championship history repeats a bracket")
    if request is not None:
        validate_championship_request(request)
        operation = request["operation"]
        if value["operation"] != operation:
            _fail("Championship response does not match the request operation")
        if operation not in {"status", "history"}:
            if current is None or current["championship_id"] != request["championship_id"]:
                raise ProtocolError("identity_mismatch", "Championship response changed the target bracket")
            for key in ("generation", "fingerprint"):
                if key in request and current[key] != request[key]:
                    raise ProtocolError("identity_mismatch", "Championship response changed the accepted bracket")
        if operation == "create":
            if current["players"] != request["players"] or current["sender"] != actor:
                raise ProtocolError("identity_mismatch", "Championship proposal changed its ordered participants")
        elif operation == "match":
            match = current["matches"][request["round"]]
            if (actor not in match["players"] or match["battle_id"] is None
                    or match["attempt"] not in (request["attempt"], request["attempt"] + 1)):
                raise ProtocolError("identity_mismatch", "Championship reply changed the requested match attempt")
        elif operation == "recover":
            match = current["matches"][request["round"]]
            if (actor not in match["players"] or match["battle_id"] != request["battle_id"]
                    or match["attempt"] != request["attempt"]):
                raise ProtocolError("identity_mismatch", "Championship recovery changed the original match")
    return value
