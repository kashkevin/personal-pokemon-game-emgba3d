"""Owner-only committed trade journal; never an apply/acknowledge operation."""
from __future__ import annotations

import base64

from .protocol import MAX_COUNTER, ProtocolError, _fields, _integer
from .team_protocol import _uuid

SCOPE = "recorded-personal-trade-archive-v1"
PAGE_SIZE = 6


class TradeArchiveUnsupported(ValueError):
    code = "trade_archive_unsupported"


def default_trade_archive_request(**changes):
    value = dict(version=1, through=0, before=0, peer=None, serial=0, record=0)
    value.update(changes)
    return validate_trade_archive_request(value)


def validate_trade_archive_request(value):
    _fields(value, {"version", "through", "before", "peer", "serial", "record"})
    if type(value["version"]) is not int or value["version"] != 1:
        raise ProtocolError("trade_archive_unsupported", "unsupported trade journal version")
    for key in ("through", "before", "record"):
        _integer(value[key], key, 0, MAX_COUNTER)
    _integer(value["serial"], "serial", 0, 1048575)
    if value["before"] and (not value["through"] or value["before"] > value["through"]):
        raise ProtocolError("invalid_field", "trade cursor exceeds its snapshot")
    if value["peer"] is not None:
        _uuid(value["peer"], "peer")
    return dict(value)


def validate_trade_archive_reply(value, actor, request=None):
    from .trade_inspection import summarize_record
    _fields(value, {"scope", "version", "player_id", "through", "next_before", "total", "rows"})
    if (value["scope"] != SCOPE or type(value["version"]) is not int or value["version"] != 1
            or value["player_id"] != actor):
        raise ProtocolError("identity_mismatch", "trade journal belongs to another player or version")
    for key in ("through", "total"):
        _integer(value[key], key, 0, MAX_COUNTER)
    if value["next_before"] is not None:
        _integer(value["next_before"], "next_before", 1, value["through"])
    rows = value["rows"]
    if type(rows) is not list or len(rows) > PAGE_SIZE or value["total"] < len(rows):
        raise ProtocolError("invalid_server_message", "invalid trade journal page size")
    if request is not None:
        validate_trade_archive_request(request)
        if request["through"] and request["through"] != value["through"]:
            raise ProtocolError("identity_mismatch", "trade journal snapshot changed")
    sequences, ids = [], set()
    for row in rows:
        _fields(row, {"sequence", "transaction_id", "peer", "revision", "applied", "sent", "received"})
        _integer(row["sequence"], "sequence", 1, value["through"])
        _integer(row["revision"], "revision", 2, MAX_COUNTER)
        _uuid(row["transaction_id"], "transaction_id")
        _uuid(row["peer"], "peer")
        if row["peer"] == actor or type(row["applied"]) is not bool or row["transaction_id"] in ids:
            raise ProtocolError("invalid_server_message", "foreign or repeated trade journal row")
        ids.add(row["transaction_id"])
        sequences.append(row["sequence"])
        serials = []
        for key in ("sent", "received"):
            try:
                if type(row[key]) is not str or len(row[key]) != 136:
                    raise ValueError()
                raw = base64.b64decode(row[key], validate=True)
                if base64.b64encode(raw).decode("ascii") != row[key]:
                    raise ValueError()
                serials.append(summarize_record(raw).serial)
            except (ValueError, TypeError) as error:
                raise ProtocolError("invalid_server_message", "trade journal Pokemon record is invalid") from error
        if serials[0] == serials[1]:
            raise ProtocolError("invalid_server_message", "trade journal repeats one owned instance")
        if request is not None and ((request["before"] and row["sequence"] >= request["before"])
                or request["peer"] not in (None, row["peer"])
                or request["record"] not in (0, row["sequence"])
                or request["serial"] and request["serial"] not in serials):
            raise ProtocolError("identity_mismatch", "trade journal changed its filters or cursor")
    if sequences != sorted(set(sequences), reverse=True):
        raise ProtocolError("invalid_server_message", "trade journal order differs")
    if value["next_before"] is not None and (len(rows) != PAGE_SIZE
            or value["next_before"] != sequences[-1] or value["total"] <= PAGE_SIZE):
        raise ProtocolError("invalid_server_message", "trade journal next cursor differs")
    if not value["through"] and (rows or value["total"] or value["next_before"] is not None):
        raise ProtocolError("invalid_server_message", "empty trade journal claims activity")
    if request is not None and not request["before"] and len(rows) != min(value["total"], PAGE_SIZE):
        raise ProtocolError("invalid_server_message", "first trade page omits matching records")
    if request is not None and not request["before"] and (value["next_before"] is not None) != (value["total"] > PAGE_SIZE):
        raise ProtocolError("invalid_server_message", "first trade page omits its continuation")
    return value


def _project(store, row, actor):
    from .flash import inspect_flash
    from .ownership import inspect_ownership
    from .storage import StorageError
    from .trade_flash import _party_record
    from .trade_storage import TradeSide, _fingerprint, _validate_swap
    connection = store._connection
    if actor not in (row["a_player"], row["b_player"]):
        raise StorageError("trade_not_participant", "this trade is not in the player's journal")
    group = connection.execute("SELECT kind FROM commit_groups WHERE sequence=?", (row["sequence"],)).fetchone()
    if group is None or group["kind"] != "trade":
        raise StorageError("storage_corrupt", "trade journal has no paired commit group")
    after, before, sides = [], [], []
    for prefix in ("a", "b"):
        cp = connection.execute("SELECT * FROM checkpoints WHERE player_id=? AND revision=?",
            (row[prefix + "_player"], row[prefix + "_revision"])).fetchone()
        if cp is None or cp["request_id"] != row["transaction_id"] or cp["revision"] != cp["expected_revision"] + 1:
            raise StorageError("storage_corrupt", "trade journal lacks its original paired checkpoint")
        order = connection.execute("SELECT sequence FROM checkpoint_order WHERE player_id=? AND revision=?",
            (cp["player_id"], cp["revision"])).fetchone()
        if order is None or order["sequence"] != row["sequence"]:
            raise StorageError("storage_corrupt", "trade journal ordering changed")
        old = connection.execute("SELECT * FROM checkpoints WHERE player_id=? AND revision=?",
            (cp["player_id"], cp["expected_revision"])).fetchone()
        if old is None:
            raise StorageError("storage_corrupt", "trade journal lacks its original source")
        after.append(store._checkpoint(cp)); before.append(store._checkpoint(old))
        sides.append(TradeSide(cp["player_id"], 1, cp["expected_revision"], row[prefix + "_serial"], cp["payload"]))
    if _fingerprint(tuple(sides), store.build_id, store.ruleset_id, store.save_profile) != row["fingerprint"]:
        raise StorageError("storage_corrupt", "trade journal commitment changed")
    effect = False
    if store.trade_effects_enabled:
        from .trade_effect_storage import audit_commit
        effect = audit_commit(store, row["transaction_id"], tuple(before), tuple(cp.payload for cp in after))
    if not effect:
        _validate_swap(before[0].payload, sides[0].serial, before[1].payload, sides[1].serial,
                       after[0].payload, after[1].payload)
    slot = 0 if actor == row["a_player"] else 1
    sent_snapshot = inspect_flash(before[slot].payload, save_profile=store.save_profile)
    received_snapshot = inspect_flash(after[slot].payload, save_profile=store.save_profile)
    sent = _party_record(sent_snapshot, inspect_ownership(sent_snapshot), sides[slot].serial)[1]
    received = _party_record(received_snapshot, inspect_ownership(received_snapshot), sides[1 - slot].serial)[1]
    ack = connection.execute("SELECT * FROM trade_recovery WHERE player_id=? AND transaction_id=?",
        (actor, row["transaction_id"])).fetchone()
    cp = after[slot]
    if ack is None or (ack["revision"], ack["sha256"]) != (cp.revision, cp.sha256) or ack["acknowledged"] not in (0, 1):
        raise StorageError("storage_corrupt", "trade journal delivery receipt differs")
    return dict(sequence=row["sequence"], transaction_id=row["transaction_id"], peer=sides[1 - slot].player_id,
        revision=cp.revision, applied=bool(ack["acknowledged"]),
        sent=base64.b64encode(sent).decode("ascii"), received=base64.b64encode(received).decode("ascii"))


def read_trade_archive(store, actor, lease, request):
    from .trade_storage import TradeCheckpointStore
    if not isinstance(store, TradeCheckpointStore):
        raise ProtocolError("trade_archive_unsupported", "this world has no paired trade journal")
    request = validate_trade_archive_request(request)
    if request["peer"] == actor:
        raise ProtocolError("invalid_field", "select a different trading partner")
    with store._transaction():
        store._require_lease(actor, lease)
        store._validate_schema()
        connection = store._connection
        maximum = connection.execute("SELECT COALESCE(MAX(sequence),0) FROM trade_transactions "
            "WHERE ? IN (a_player,b_player)", (actor,)).fetchone()[0]
        through = request["through"] or maximum
        if through > maximum:
            raise ProtocolError("trade_archive_changed", "trade snapshot exceeds this trainer's journal")
        clauses, arguments = ["? IN (a_player,b_player)", "sequence<=?"], [actor, through]
        if request["peer"] is not None:
            clauses.append("? IN (a_player,b_player)"); arguments.append(request["peer"])
        if request["serial"]:
            clauses.append("? IN (a_serial,b_serial)"); arguments.append(request["serial"])
        if request["record"]:
            clauses.append("sequence=?"); arguments.append(request["record"])
        where = " AND ".join(clauses)
        total = connection.execute("SELECT COUNT(*) FROM trade_transactions WHERE " + where, arguments).fetchone()[0]
        if request["before"]:
            where += " AND sequence<?"; arguments.append(request["before"])
        rows = connection.execute("SELECT * FROM trade_transactions WHERE " + where + " ORDER BY sequence DESC LIMIT ?",
            (*arguments, PAGE_SIZE + 1)).fetchall()
        result = dict(version=1, scope=SCOPE, player_id=actor, through=through, total=total,
            rows=[_project(store, row, actor) for row in rows[:PAGE_SIZE]],
            next_before=rows[PAGE_SIZE - 1]["sequence"] if len(rows) > PAGE_SIZE else None)
    return validate_trade_archive_reply(result, actor, request)


async def fetch_trade_archive(companion, request=None):
    from .companion import BattleChallengeError
    request = default_trade_archive_request() if request is None else validate_trade_archive_request(request)
    original = (companion.world_id, companion.server_epoch, companion.session_epoch)
    try:
        reply = await companion.battle_challenge_rpc("history", trade_archive=request)
    except BattleChallengeError as error:
        if error.code in {"invalid_fields", "trade_archive_unsupported"}:
            raise TradeArchiveUnsupported("This host does not provide your trade journal.") from error
        raise
    if not companion.connected or original != (companion.world_id, companion.server_epoch, companion.session_epoch):
        raise ConnectionError("trade journal changed authenticated session")
    return validate_trade_archive_reply(reply["trade_archive"], companion.config.player_id, request)
