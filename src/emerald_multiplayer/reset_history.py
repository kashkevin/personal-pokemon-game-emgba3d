"""Authenticated personal admission receipts, never inferred encounter outcomes."""
from .protocol import MAX_COUNTER, ProtocolError, _fields, _integer
from .reset_protocol import ENCOUNTERS
from .team_protocol import _uuid

SCOPE = "personal-static-attempt-history-v1"
_REQUEST = {"version", "encounter_id", "through_attempt", "before_attempt", "limit"}
_ENTRY = {"attempt", "request_id", "checkpoint_revision", "observed_count"}


class ResetHistoryUnsupported(ValueError):
    """The connected host explicitly refused the optional history extension."""
    code = "reset_history_unsupported"


def default_reset_history_request(encounter_id, limit=10):
    return validate_reset_history_request(dict(version=1, encounter_id=encounter_id,
        through_attempt=None, before_attempt=None, limit=limit))


def validate_reset_history_request(request):
    _fields(request, _REQUEST)
    _integer(request["version"], "version", 1, 1)
    _integer(request["encounter_id"], "encounter_id", 1, 0xFFFFFFFF)
    if request["encounter_id"] not in ENCOUNTERS:
        raise ProtocolError("reset_ineligible", "unknown personal encounter source")
    _integer(request["limit"], "limit", 1, 20)
    through, before = request["through_attempt"], request["before_attempt"]
    if through is not None:
        _integer(through, "through_attempt", 0, 0xFFFFFFFF)
    if before is not None:
        _integer(before, "before_attempt", 1, 0xFFFFFFFF)
        if through is None or before > through:
            raise ProtocolError("invalid_field", "history cursor requires its original snapshot")
    return dict(request)


def _entry(value):
    _fields(value, _ENTRY)
    _integer(value["attempt"], "attempt", 1, 0xFFFFFFFF)
    _integer(value["observed_count"], "observed_count", 0, value["attempt"] - 1)
    _integer(value["checkpoint_revision"], "checkpoint_revision", 1, MAX_COUNTER)
    _uuid(value["request_id"], "request_id")
    return dict(value)


def validate_reset_history_reply(reply, request=None):
    _fields(reply, {"scope", "encounter_id", "through_attempt", "current_attempt",
                   "before_attempt", "limit", "next_before", "first", "latest", "entries"})
    if reply["scope"] != SCOPE:
        raise ProtocolError("invalid_server_message", "unknown personal history scope")
    actual = validate_reset_history_request({"version": 1, **{key: reply[key] for key in
        ("encounter_id", "through_attempt", "before_attempt", "limit")}})
    through = _integer(reply["through_attempt"], "through_attempt", 0, 0xFFFFFFFF)
    _integer(reply["current_attempt"], "current_attempt", through, 0xFFFFFFFF)
    if request is not None:
        request = validate_reset_history_request(request)
        if (any(request[key] != actual[key] for key in ("encounter_id", "before_attempt", "limit"))
                or (request["through_attempt"] is not None and request["through_attempt"] != through)
                or (request["through_attempt"] is None and reply["current_attempt"] != through)):
            raise ProtocolError("identity_mismatch", "personal history changed its requested snapshot")
    top = min(through, reply["before_attempt"] - 1) if reply["before_attempt"] is not None else through
    count = min(top, reply["limit"])
    if type(reply["entries"]) is not list or len(reply["entries"]) != count:
        raise ProtocolError("invalid_server_message", "personal history page is incomplete")
    entries = [_entry(value) for value in reply["entries"]]
    if [value["attempt"] for value in entries] != list(range(top, top - count, -1)):
        raise ProtocolError("invalid_server_message", "personal history has a gap or changed order")
    if len({value["request_id"] for value in entries}) != len(entries):
        raise ProtocolError("invalid_server_message", "personal history repeats an admission identity")
    next_before = entries[-1]["attempt"] if entries and entries[-1]["attempt"] > 1 else None
    if reply["next_before"] is not None:
        _integer(reply["next_before"], "next_before", 2, 0xFFFFFFFF)
    if reply["next_before"] != next_before:
        raise ProtocolError("invalid_server_message", "personal history cursor differs")
    first = latest = None
    if through:
        first, latest = _entry(reply["first"]), _entry(reply["latest"])
        if first["attempt"] != 1 or latest["attempt"] != through:
            raise ProtocolError("invalid_server_message", "personal history bounds differ")
        if (through == 1 and first != latest) or (through > 1 and first["request_id"] == latest["request_id"]):
            raise ProtocolError("invalid_server_message", "personal history bound identities differ")
        for entry in entries:
            if (entry["attempt"] == 1 and entry != first) or (entry["attempt"] == through and entry != latest):
                raise ProtocolError("invalid_server_message", "personal history bound receipt differs")
        visible = {entry["attempt"]: entry for entry in [first, latest, *entries]}
        if len({entry["request_id"] for entry in visible.values()}) != len(visible):
            raise ProtocolError("invalid_server_message", "personal history reuses a bound admission identity")
    elif reply["first"] is not None or reply["latest"] is not None:
        raise ProtocolError("invalid_server_message", "empty personal history has bound receipts")
    return {**reply, "entries": entries, "first": first, "latest": latest}


async def read_reset_history(companion, request):
    from .companion import BattleChallengeError
    request = validate_reset_history_request(request)
    original = (companion.world_id, companion.server_epoch, companion.session_epoch)
    try:
        reply = await companion.battle_challenge_rpc("history", reset_history=request)
    except BattleChallengeError as error:
        if error.code == "invalid_fields":
            raise ResetHistoryUnsupported("this host does not support personal attempt history") from error
        raise
    if not companion.connected or original != (companion.world_id, companion.server_epoch, companion.session_epoch):
        raise ConnectionError("personal history changed authenticated session")
    if "reset_history" not in reply:
        raise ProtocolError("invalid_server_message", "host omitted the requested personal history")
    return validate_reset_history_reply(reply["reset_history"], request)
