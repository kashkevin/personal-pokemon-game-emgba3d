"""Personal static-attempt admission; no encounter properties travel over RPC."""
from .protocol import MAX_COUNTER, PROTOCOL_VERSION, ProtocolError, _fields, _integer
from .team_protocol import _uuid

SCOPE = "personal-static-attempts-v1"
# Explicit compiled source descriptors. No wild, gift or World Event source.
SOURCES = {
    0x1001: "New Mauville Voltorb 1", 0x1002: "New Mauville Voltorb 2", 0x1003: "New Mauville Voltorb 3",
    0x1004: "Aqua Hideout Electrode 1", 0x1005: "Aqua Hideout Electrode 2",
    0x1006: "Ancient Tomb Registeel", 0x1007: "Desert Ruins Regirock", 0x1008: "Island Cave Regice",
    0x1009: "Sky Pillar Rayquaza",
    0x100A: "Battle Frontier Sudowoodo",
    0x100B: "Marine Cave Kyogre", 0x100C: "Terra Cave Groudon",
    0x100D: "Route 120 Kecleon 1", 0x100E: "Route 120 Kecleon 2", 0x100F: "Route 120 Kecleon 3",
    0x1010: "Route 120 Kecleon 4", 0x1011: "Route 120 Kecleon 5",
    0x1012: "Route 119 Kecleon 1", 0x1013: "Route 119 Kecleon 2",
    0x1014: "Navel Rock Lugia",
    0x1015: "Navel Rock Ho-Oh", 0x1016: "Faraway Island Mew",
    0x1017: "Birth Island Deoxys", 0x1018: "Southern Island Latios", 0x1019: "Southern Island Latias",
}
ENCOUNTERS = frozenset(SOURCES)
RESET_TYPES = frozenset({"reset_begin"})


def validate_reset_common(message, epoch):
    if type(message) is not dict or type(message.get("type")) is not str or message["type"] not in RESET_TYPES:
        raise ProtocolError("invalid_type", "unsupported personal encounter operation")
    _integer(message.get("session_epoch"), "session_epoch", 1, MAX_COUNTER)
    if message["session_epoch"] != epoch:
        raise ProtocolError("session_epoch_mismatch", "personal encounter belongs to another lease")
    _uuid(message.get("request_id"), "request_id")
    return message


def validate_reset_request(message, epoch):
    validate_reset_common(message, epoch)
    _fields(message, {"type", "session_epoch", "request_id", "encounter_id", "incarnation", "sequence", "observed_count"})
    _integer(message["encounter_id"], "encounter_id", 1, 0xFFFFFFFF)
    if message["encounter_id"] not in ENCOUNTERS:
        raise ProtocolError("reset_ineligible", "this encounter has no audited personal reset source")
    for key in ("incarnation", "sequence"):
        _integer(message[key], key, 1, 0xFFFFFFFF)
    _integer(message["observed_count"], "observed_count", 0, 0xFFFFFFFF)
    return dict(message)


def validate_reset_reply(message, actor, world, epoch, request=None):
    if type(message) is not dict or type(message.get("type")) is not str or message["type"] not in ("reset_result", "reset_error"):
        raise ProtocolError("invalid_server_message", "invalid personal encounter reply")
    extra = {"result"} if message["type"] == "reset_result" else {"code", "message"}
    _fields(message, {"type", "protocol", "session_epoch", "request_id", "world_id", "player_id"} | extra)
    _uuid(message["request_id"], "request_id")
    if (type(message["protocol"]) is not int or message["protocol"] != PROTOCOL_VERSION
            or type(message["session_epoch"]) is not int or message["session_epoch"] != epoch
            or message["world_id"] != world or message["player_id"] != actor):
        raise ProtocolError("identity_mismatch", "foreign personal encounter reply")
    if request is not None and message["request_id"] != request["request_id"]:
        raise ProtocolError("identity_mismatch", "personal encounter reply correlation differs")
    if "result" in message:
        result = message["result"]
        _fields(result, {"scope", "encounter_id", "incarnation", "sequence", "attempt"})
        if result["scope"] != SCOPE or type(result["encounter_id"]) is not int or result["encounter_id"] not in ENCOUNTERS:
            raise ProtocolError("invalid_server_message", "unknown personal encounter scope")
        for key in ("encounter_id", "incarnation", "sequence", "attempt"):
            _integer(result[key], key, 1, 0xFFFFFFFF)
        if request is not None and any(result[k] != request[k] for k in ("encounter_id", "incarnation", "sequence")):
            raise ProtocolError("identity_mismatch", "personal encounter reply changed its request")
        if request is not None and result["attempt"] <= request["observed_count"]:
            raise ProtocolError("invalid_server_message", "personal encounter counter did not advance")
    else:
        for key in ("code", "message"):
            if type(message[key]) is not str or not 1 <= len(message[key]) <= 256 or not message[key].isprintable():
                raise ProtocolError("invalid_server_message", "invalid personal encounter error")
    return dict(message)
