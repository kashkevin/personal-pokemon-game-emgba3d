"""Stable, actor-private pages over the already verified released archive."""
from __future__ import annotations

from .protocol import MAX_COUNTER, ProtocolError, _fields, _integer
from .team_protocol import _uuid

SCOPE = "recorded-battle-archive-v1"
PAGE_SIZE = 8


class BattleArchiveUnsupported(ValueError):
    code = "battle_archive_unsupported"


def default_battle_archive_request(**changes):
    value = dict(version=1, through=0, before=0, mode="all", outcome="all",
                 peer=None, relation="all", record=0)
    value.update(changes)
    return validate_battle_archive_request(value)


def validate_battle_archive_request(value):
    _fields(value, {"version", "through", "before", "mode", "outcome", "peer", "relation", "record"})
    if type(value["version"]) is not int or value["version"] != 1:
        raise ProtocolError("battle_archive_unsupported", "unsupported battle archive version")
    for key in ("through", "before", "record"):
        _integer(value[key], key, 0, MAX_COUNTER)
    if value["before"] and (not value["through"] or value["before"] > value["through"]):
        raise ProtocolError("invalid_field", "archive cursor exceeds its snapshot")
    if (value["mode"] not in ("all", "singles", "doubles")
            or value["outcome"] not in ("all", "win", "loss", "draw")
            or value["relation"] not in ("all", "together", "against")):
        raise ProtocolError("invalid_field", "unknown archive filter")
    if value["peer"] is not None:
        _uuid(value["peer"], "peer")
    elif value["relation"] != "all":
        raise ProtocolError("invalid_field", "a relationship filter requires a selected peer")
    return dict(value)


def archive_matches(sequence, mode, outcome, players, actor, request):
    """Pure index predicate; entries originate only from validated results."""
    if actor not in players or request["record"] not in (0, sequence):
        return False
    if request["mode"] != "all" and mode != {"singles": 2, "doubles": 3}[request["mode"]]:
        return False
    slot = players.index(actor)
    verdict = "draw" if outcome == 3 else "win" if outcome == 1 + slot % 2 else "loss"
    if request["outcome"] not in ("all", verdict):
        return False
    peer = request["peer"]
    if peer is None:
        return True
    if peer == actor or peer not in players:
        return False
    relationship = "together" if players.index(peer) % 2 == slot % 2 else "against"
    return request["relation"] in ("all", relationship)


def validate_battle_archive_reply(value, actor, request=None):
    from .battle_results import validate_result
    _fields(value, {"version", "scope", "through", "next_before", "total", "rows"})
    if type(value["version"]) is not int or value["version"] != 1 or value["scope"] != SCOPE:
        raise ProtocolError("invalid_server_message", "unknown battle archive scope")
    for key in ("through", "total"):
        _integer(value[key], key, 0, MAX_COUNTER)
    if value["next_before"] is not None:
        _integer(value["next_before"], "next_before", 1, value["through"])
    rows = value["rows"]
    if type(rows) is not list or len(rows) > PAGE_SIZE or value["total"] < len(rows):
        raise ProtocolError("invalid_server_message", "invalid battle archive page size")
    sequences, identities = [], set()
    if request is not None:
        validate_battle_archive_request(request)
        if request["through"] and value["through"] != request["through"]:
            raise ProtocolError("identity_mismatch", "battle archive snapshot changed")
    for row in rows:
        validate_result(row, actor)
        if row["sequence"] > value["through"] or row["battle_id"] in identities:
            raise ProtocolError("invalid_server_message", "battle archive repeated or exceeded its snapshot")
        sequences.append(row["sequence"])
        identities.add(row["battle_id"])
        if request is not None and ((request["before"] and row["sequence"] >= request["before"])
                or not archive_matches(row["sequence"], row["mode"], row["outcome"], row["players"], actor, request)):
            raise ProtocolError("identity_mismatch", "battle archive changed its filters or cursor")
    if sequences != sorted(set(sequences), reverse=True):
        raise ProtocolError("invalid_server_message", "battle archive order differs")
    if value["next_before"] is not None and (len(rows) != PAGE_SIZE or value["next_before"] != sequences[-1]
            or value["total"] <= PAGE_SIZE):
        raise ProtocolError("invalid_server_message", "battle archive next cursor differs")
    if not value["through"] and (rows or value["total"] or value["next_before"] is not None):
        raise ProtocolError("invalid_server_message", "empty archive has retained activity")
    if request is not None and not request["before"] and len(rows) != min(value["total"], PAGE_SIZE):
        raise ProtocolError("invalid_server_message", "first archive page omits matching records")
    if request is not None and not request["before"] and (value["next_before"] is not None) != (value["total"] > PAGE_SIZE):
        raise ProtocolError("invalid_server_message", "first archive page omits its continuation")
    return value


async def read_battle_archive(companion, request=None):
    from .companion import BattleChallengeError
    request = default_battle_archive_request() if request is None else validate_battle_archive_request(request)
    original = (companion.world_id, companion.server_epoch, companion.session_epoch)
    try:
        reply = await companion.battle_challenge_rpc("history", battle_archive=request)
    except BattleChallengeError as error:
        if error.code in {"invalid_fields", "battle_archive_unsupported"}:
            raise BattleArchiveUnsupported("This host does not provide paged battle records.") from error
        raise
    if not companion.connected or original != (companion.world_id, companion.server_epoch, companion.session_epoch):
        raise ConnectionError("battle archive changed authenticated session")
    return validate_battle_archive_reply(reply["battle_archive"], companion.config.player_id, request)
