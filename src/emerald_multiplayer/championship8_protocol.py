"""Championship protocol version 2 (step 18, docs/championships-eight.md): eight places with computer trainers.

Version 2 carries every Championship bracket in one public shape, whatever it is stored as: the eight-place bracket
(``format`` 8: two to four players and the Battle Tower floor trainers that fill the other places, quarterfinals,
semifinals, final) and the four players' bracket of before (``format`` 4, docs/championships.md: two semifinals and a
final, read from its own sidecar and shown in this shape). Bracket consent never grants native battle consent; a match
between two players is still the existing challenge (BattleDesk) and only its released result advances the bracket; a
match against a computer trainer is the player's own game's battle (the Tower's solo command, mode 2) and only the result
that game reports for the host's own ticket advances it; two computer trainers never battle (the higher seed goes on).
This module validates public projections; it accepts no winner or save claims from a client.
"""
from __future__ import annotations

import re

from .protocol import MAX_COUNTER, ProtocolError, _fields, _integer
from .team_protocol import _uuid

VERSION = 2
HISTORY_LIMIT = 4
OPERATIONS = frozenset({"status", "history", "create", "accept", "cancel", "match", "recover"})
STATES = frozenset({"proposed", "active", "completed", "canceled"})
MATCH_STATES = frozenset({"blocked", "ready", "invited", "playing", "waiting", "draw", "won", "canceled"})
KINDS = frozenset({"players", "computer", "auto"})
RULES = frozenset({"open", "species_clause", "item_clause", "level_50", "level_30", "no_legendaries"})
MIN_PLAYERS, MAX_PLAYERS = 2, 4
FLOORS = 100
_HASH = re.compile(r"[0-9a-f]{64}\Z")

# The two bracket shapes: the first round's pairs of seeds (seed 0 is the first place), which earlier matches feed each
# later one (its seeds are their winners, in that order), and each match's stage (1 quarterfinal, 2 semifinal, 3 final:
# the round byte of a computer match's command).
FORMATS = {
    4: {"pairs": ((0, 1), (2, 3)), "feeders": {2: (0, 1)}, "stages": (2, 2, 3)},
    8: {"pairs": ((0, 7), (3, 4), (1, 6), (2, 5)), "feeders": {4: (0, 1), 5: (2, 3), 6: (4, 5)},
        "stages": (1, 1, 1, 1, 2, 2, 3)},
}
STAGE_NAMES = {1: "Quarterfinal", 2: "Semifinal", 3: "Final"}


def _fail(message):
    raise ProtocolError("invalid_server_message", message)


def _digest(value):
    if type(value) is not str or _HASH.fullmatch(value) is None:
        raise ProtocolError("invalid_field", "Championship fingerprint must be a SHA256 digest")


def _name(value, what):
    if type(value) is not str or not 1 <= len(value) <= 24 or not value.strip() or not value.isprintable():
        _fail(f"Championship {what} is invalid")


def _players(value, minimum=MIN_PLAYERS, maximum=MAX_PLAYERS):
    if type(value) is not list or not minimum <= len(value) <= maximum:
        _fail("Championship has an incorrect player count")
    for player in value:
        _uuid(player, "Championship participant")
    if len(set(value)) != len(value):
        _fail("Championship repeats a participant")


def _consent(value, players):
    if (type(value) is not list or any(type(player) is not str for player in value)
            or len(value) != len(set(value)) or not set(value) <= set(players)):
        _fail("Championship consent has a foreign or repeated participant")


def _ticket(value):
    if type(value) is not int or not 0 < value <= 0xFFFFFFFF or not value & 0xFF:
        _fail("Championship computer match ticket is invalid")


def validate_championship_request(value):
    """Validate the nested extension; the outer battle RPC owns authentication."""
    if type(value) is not dict or type(value.get("version")) is not int or value["version"] != VERSION:
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
        try:
            _players(value["players"])
        except ProtocolError as error:
            raise ProtocolError("invalid_field", error.message) from error
    if operation in {"match", "recover"}:
        _integer(value["round"], "Championship round", 0, 6)
        _integer(value["attempt"], "Championship match attempt", int(operation == "recover"), MAX_COUNTER)
    return value


def entrant_kind(entrant):
    return "player" if entrant["player"] is not None else "computer"


def match_kind(entrants, seeds):
    """A match's kind from its two seeds: two players, a player and a computer trainer, or two computer trainers."""
    if not seeds:
        return None
    people = sum(entrants[seed]["player"] is not None for seed in seeds)
    return "players" if people == 2 else "computer" if people == 1 else "auto"


def match_players(entrants, match):
    """The players (UUIDs) of a match, in seed order: two, one (against a computer trainer) or none."""
    return [entrants[seed]["player"] for seed in match["seeds"] if entrants[seed]["player"] is not None]


def expected_seeds(view, index):
    """The seeds a match must have now: its first-round pair, or its feeders' winners once both are known."""
    shape = FORMATS[view["format"]]
    if index < len(shape["pairs"]):
        return list(shape["pairs"][index])
    first, second = shape["feeders"][index]
    feeders = view["matches"][first], view["matches"][second]
    return [match["winner"] for match in feeders] if all(match["state"] == "won" for match in feeders) else []


def _entrant(value, seed, fmt):
    _fields(value, {"seed", "player", "name", "title", "floor"})
    if type(value["seed"]) is not int or value["seed"] != seed:
        _fail("Championship places changed order")
    _name(value["name"], "place name")
    if value["player"] is not None:
        _uuid(value["player"], "Championship participant")
        if value["title"] is not None or value["floor"] is not None:
            _fail("A player's place claims a computer trainer")
    else:
        if fmt == 4:
            _fail("The four players' bracket has no computer place")
        _name(value["title"], "computer trainer's class")
        _integer(value["floor"], "computer trainer's floor", 1, FLOORS)


def _match(view, index, match):
    _fields(match, {"round", "stage", "seeds", "kind", "attempt", "battle_id", "ticket", "state", "winner"})
    shape = FORMATS[view["format"]]
    if type(match["round"]) is not int or match["round"] != index:
        _fail("Championship rounds changed order")
    if type(match["stage"]) is not int or match["stage"] != shape["stages"][index]:
        _fail("Championship match has the wrong stage")
    seeds = expected_seeds(view, index)
    if type(match["seeds"]) is not list or match["seeds"] != seeds:
        _fail("Championship match changed its places")
    kind = match_kind(view["entrants"], seeds)
    if match["kind"] != kind:
        _fail("Championship match has the wrong kind")
    attempt = _integer(match["attempt"], "Championship match attempt", 0, MAX_COUNTER)
    state = match["state"]
    if type(state) is not str or state not in MATCH_STATES:
        _fail("Championship match state is invalid")
    if not seeds:
        if state != "blocked" or attempt or match["battle_id"] is not None or match["ticket"] is not None:
            _fail("Championship match is not waiting for its places")
    elif kind == "auto":
        # Two computer trainers never battle: the higher seed goes on once the bracket is active.
        if attempt or match["battle_id"] is not None or match["ticket"] is not None or state not in {"ready", "won"}:
            _fail("Two computer trainers' match claims a battle")
        if state == "won" and match["winner"] != min(seeds):
            _fail("Two computer trainers' match did not send the higher seed on")
    else:
        if attempt:
            _uuid(match["battle_id"], "Championship battle")
            if state in {"blocked", "ready"}:
                _fail("Issued Championship match has no valid execution state")
        elif match["battle_id"] is not None or state != "ready":
            _fail("Unissued Championship match claims battle progress")
        if kind == "players":
            if match["ticket"] is not None:
                _fail("A match between players has no ticket")
        else:
            if (match["ticket"] is None) != (attempt == 0):
                _fail("A computer match's ticket is missing or early")
            if match["ticket"] is not None:
                _ticket(match["ticket"])
            if state == "waiting":
                _fail("A computer match never waits for a native recovery")
    if state == "won":
        if match["winner"] not in seeds:
            _fail("Championship match winner was not a participant")
    elif match["winner"] is not None:
        _fail("Unsettled Championship match claims a winner")


def validate_championship_view(value, actor):
    _fields(value, {"format", "championship_id", "generation", "fingerprint", "sender", "players", "names", "rule",
                    "entrants", "state", "consent", "cancel_consent", "champion", "matches"})
    if type(value["format"]) is not int or value["format"] not in FORMATS:
        _fail("Championship format is invalid")
    fmt = value["format"]
    for key in ("championship_id", "generation", "sender"):
        _uuid(value[key], key)
    _digest(value["fingerprint"])
    players = value["players"]
    _players(players, *((4, 4) if fmt == 4 else (MIN_PLAYERS, MAX_PLAYERS)))
    if type(value["names"]) is not list or len(value["names"]) != len(players):
        _fail("Championship participant names are invalid")
    for name in value["names"]:
        _name(name, "participant name")
    if actor not in players or value["sender"] != players[0]:
        raise ProtocolError("identity_mismatch", "Championship belongs to other participants")
    if type(value["rule"]) is not str or value["rule"] not in RULES:
        _fail("Championship rule is invalid")
    entrants = value["entrants"]
    if type(entrants) is not list or len(entrants) != fmt:
        _fail("Championship has the wrong number of places")
    for seed, entrant in enumerate(entrants):
        _entrant(entrant, seed, fmt)
    people = [entrant for entrant in entrants if entrant["player"] is not None]
    computers = [entrant for entrant in entrants if entrant["player"] is None]
    # The players hold the first places (the proposer first), the computer trainers the rest, the higher floor first.
    if ([entrant["player"] for entrant in people] != players or entrants[:len(people)] != people
            or [entrant["name"] for entrant in people] != value["names"]):
        _fail("Championship players do not hold the first places")
    floors = [entrant["floor"] for entrant in computers]
    if floors != sorted(floors, reverse=True) or len(set(floors)) != len(floors):
        _fail("Championship computer trainers are not ranked by floor")
    state = value["state"]
    if type(state) is not str or state not in STATES:
        _fail("Championship state is invalid")
    _consent(value["consent"], players)
    _consent(value["cancel_consent"], players)
    if value["sender"] not in value["consent"]:
        _fail("Championship proposal omits its proposer's explicit consent")
    if state in {"active", "completed"} and set(value["consent"]) != set(players):
        _fail("Championship became active without every player's consent")
    matches = value["matches"]
    if type(matches) is not list or len(matches) != len(FORMATS[fmt]["stages"]):
        _fail("Championship has the wrong number of matches")
    for index, match in enumerate(matches):
        _match(value, index, match)
    issued = [match["battle_id"] for match in matches if match["battle_id"] is not None]
    tickets = [match["ticket"] for match in matches if match["ticket"] is not None]
    if len(set(issued)) != len(issued) or len(set(tickets)) != len(tickets):
        _fail("Championship rounds share a battle identity")
    if state == "proposed" and any(match["attempt"] or match["state"] == "won" for match in matches):
        _fail("Championship started a match before bracket consent")
    final = matches[-1]
    if state == "completed":
        if final["state"] != "won" or value["champion"] != final["winner"]:
            _fail("Championship champion differs from the settled final")
    elif value["champion"] is not None or final["state"] == "won":
        _fail("Incomplete Championship claims a final winner")
    return value


def _command(value):
    _fields(value, {"ticket", "floor", "table_hash", "round", "flags"})
    _ticket(value["ticket"])
    _integer(value["floor"], "computer trainer's floor", 1, FLOORS)
    _integer(value["table_hash"], "Tower table hash", 0, 0xFFFFFFFF)
    _integer(value["round"], "Championship stage", 1, 3)
    _integer(value["flags"], "Championship match flags", 0, 1)


def _summary(value, actor):
    _fields(value, {"championship_id", "format", "players", "names", "champion", "champion_name", "state"})
    _uuid(value["championship_id"], "Championship history ID")
    if type(value["format"]) is not int or value["format"] not in FORMATS:
        _fail("Championship history format is invalid")
    _players(value["players"], *((4, 4) if value["format"] == 4 else (MIN_PLAYERS, MAX_PLAYERS)))
    if type(value["names"]) is not list or len(value["names"]) != len(value["players"]):
        _fail("Championship history names are invalid")
    for name in value["names"]:
        _name(name, "participant name")
    if actor not in value["players"]:
        raise ProtocolError("identity_mismatch", "Championship history belongs to another player")
    if type(value["state"]) is not str or value["state"] not in {"completed", "canceled"}:
        _fail("Championship history contains an unsettled bracket")
    if value["state"] == "completed":
        _name(value["champion_name"], "champion's name")
        if value["champion"] is not None and value["champion"] not in value["players"]:
            _fail("Championship history winner was not a participant")
    elif value["champion"] is not None or value["champion_name"] is not None:
        _fail("Canceled Championship history claims a champion")


def validate_championship_reply(value, actor, request=None):
    """Validate only public bracket data and its exact request correlation."""
    if type(value) is not dict:
        _fail("Championship response is not an object")
    _fields(value, {"version", "operation", "current", "history"} | ({"command"} if "command" in value else set()))
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
    if "command" in value:
        _command(value["command"])
        if value["operation"] != "match" or current is None:
            _fail("Only a match reply carries a computer match's command")
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
        elif operation in {"match", "recover"}:
            if request["round"] >= len(current["matches"]):
                raise ProtocolError("identity_mismatch", "Championship reply has no such match")
            match = current["matches"][request["round"]]
            if actor not in match_players(current["entrants"], match):
                raise ProtocolError("identity_mismatch", "Championship reply changed the requested match")
            if operation == "match":
                if (match["battle_id"] is None
                        or match["attempt"] not in (request["attempt"], request["attempt"] + 1)):
                    raise ProtocolError("identity_mismatch", "Championship reply changed the requested match attempt")
                if "command" in value and (match["kind"] != "computer" or match["ticket"] != value["command"]["ticket"]
                                           or match["stage"] != value["command"]["round"]):
                    raise ProtocolError("identity_mismatch", "Championship command differs from its match")
            elif match["battle_id"] != request["battle_id"] or match["attempt"] != request["attempt"]:
                raise ProtocolError("identity_mismatch", "Championship recovery changed the original match")
    return value


def four_player_view(view):
    """The four players' bracket of before (championship_protocol version 1's view) in this version's shape: the four
    players hold places 0-3, its two semifinals and final are matches 0-2, winners are places."""
    seat = {player: index for index, player in enumerate(view["players"])}
    entrants = [dict(seed=index, player=player, name=view["names"][index], title=None, floor=None)
                for index, player in enumerate(view["players"])]
    matches = []
    for index, match in enumerate(view["matches"]):
        seeds = [seat[player] for player in match["players"]]
        matches.append(dict(round=index, stage=FORMATS[4]["stages"][index], seeds=seeds,
                            kind="players" if seeds else None, attempt=match["attempt"], battle_id=match["battle_id"],
                            ticket=None, state=match["state"],
                            winner=None if match["winner"] is None else seat[match["winner"]]))
    return dict(format=4, championship_id=view["championship_id"], generation=view["generation"],
                fingerprint=view["fingerprint"], sender=view["sender"], players=list(view["players"]),
                names=list(view["names"]), rule="open", entrants=entrants, state=view["state"],
                consent=list(view["consent"]), cancel_consent=list(view["cancel_consent"]),
                champion=None if view["champion"] is None else seat[view["champion"]], matches=matches)


def summary_of(view):
    """A finished bracket as history shows it (no checkpoints, results or other rosters' data)."""
    champion = view["champion"]
    entrant = None if champion is None else view["entrants"][champion]
    return dict(championship_id=view["championship_id"], format=view["format"], players=list(view["players"]),
                names=list(view["names"]), champion=None if entrant is None else entrant["player"],
                champion_name=None if entrant is None else entrant["name"], state=view["state"])


__all__ = ["FORMATS", "HISTORY_LIMIT", "KINDS", "MATCH_STATES", "OPERATIONS", "RULES", "STAGE_NAMES", "STATES",
           "VERSION", "entrant_kind", "expected_seeds", "four_player_view", "match_kind", "match_players", "summary_of",
           "validate_championship_reply", "validate_championship_request", "validate_championship_view"]
