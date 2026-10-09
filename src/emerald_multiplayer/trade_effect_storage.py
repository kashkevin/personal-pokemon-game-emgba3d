"""Explicit effect extension, atomic proof publication and native replay barrier.

Structural startup replay is deliberately insufficient to enable writes. Every
retained effect commit must also be reproduced by the pinned host native worker
before the store clears its mutation fence. No database is migrated on open.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
from itertools import zip_longest
import json
from pathlib import Path

from .flash import inspect_flash
from .storage import StorageError, _ExclusiveFileLock
from .trade_effect_flash import prepare_effect_pair, _private_blocks
from .trade_effect_preparation import (
    canonical, digest, describe_effect_pair, decode_effect_plan,
    validate_effect_preparation, validate_effect_receipt,
)
from .trade_friendship_migration import _encode, _decode

EXTENSION_VERSION = 1600
EFFECT_SCHEMA = {
    "trade_effect_policy": """CREATE TABLE trade_effect_policy (
        singleton INTEGER PRIMARY KEY CHECK(singleton=1), policy_id TEXT NOT NULL
    )""",
    "trade_effect_proposals": """CREATE TABLE trade_effect_proposals (
        transaction_id TEXT PRIMARY KEY, generation TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('active','cancelled','committed')),
        document TEXT NOT NULL, sha256 TEXT NOT NULL CHECK(length(sha256)=64)
    )""",
    "trade_effect_commits": """CREATE TABLE trade_effect_commits (
        transaction_id TEXT PRIMARY KEY REFERENCES trade_transactions(transaction_id),
        document TEXT NOT NULL, sha256 TEXT NOT NULL CHECK(length(sha256)=64)
    )""",
}


def read_effect_policy(store):
    from .trade_effect_preparation import POLICIES
    require(store.trade_effects_enabled, "this world has not explicitly enabled native effects")
    rows = store._connection.execute("SELECT * FROM trade_effect_policy").fetchall()
    require(len(rows) == 1 and rows[0]["singleton"] == 1 and rows[0]["policy_id"] in POLICIES,
            "native effect geographic policy is missing or unknown")
    return rows[0]["policy_id"]


def require(condition, message):
    if not condition:
        raise StorageError("trade_effect_invalid", message)


def parse_document(row):
    try:
        value = json.loads(row["document"])
    except (ValueError, TypeError) as error:
        raise StorageError("storage_corrupt", "invalid retained trade effect document") from error
    require(canonical(value) == row["document"] and digest(value) == row["sha256"],
            "retained trade effect document changed")
    return value


def _inputs(document, before):
    require(type(document) is dict and set(document) == {"descriptions", "receipts", "records", "histories", "outcome_sha256"},
            "invalid committed native effect fields")
    descriptions = document["descriptions"]
    require(type(descriptions) is list and len(descriptions) == 2, "both committed effect descriptions required")
    for description in descriptions:
        validate_effect_preparation(description)
    first = descriptions[0]
    plans = tuple(decode_effect_plan(v) for v in first["effects"]["offers"])
    leases = tuple(p["lease_epoch"] for p in first["players"])
    expected = describe_effect_pair(first["world_id"], first["transaction_id"], first["generation"], first["fingerprint"],
        tuple(before), leases, plans, **{k: first["effects"][k] for k in ("engine_source_sha256", "profile_game_version", "policy_id")})
    require(tuple(descriptions) == expected, "effect plans differ from original canonical checkpoints")
    require(type(document["receipts"]) is list and len(document["receipts"]) == 2, "both native receipts required")
    choices = tuple(validate_effect_receipt(v) for v in document["receipts"])
    require(type(document["records"]) is list and len(document["records"]) == 2
            and type(document["histories"]) is list and len(document["histories"]) == 2,
            "both native records and resulting histories required")
    return first, plans, leases, choices


def check_result(document, before, pair):
    first, _, _, _ = _inputs(document, before)
    require(pair.preparation_sha256 == first["preparation_id"] and pair.outcome_sha256 == document["outcome_sha256"],
            "native pair preparation or outcome differs")
    for receipt, record, history, witness, payload in zip(document["receipts"], document["records"], document["histories"],
            (pair.recipient_a, pair.recipient_b), (pair.after_a, pair.after_b)):
        require(record == base64.b64encode(witness.candidate).decode("ascii") and history == _encode(witness.resulting_history),
                "native record or handler result differs")
        require((receipt["candidate_sha256"], receipt["candidate_size"], receipt["record_sha256"]) ==
                (hashlib.sha256(payload).hexdigest(), len(payload), hashlib.sha256(witness.candidate).hexdigest()),
                "recipient did not acknowledge the exact native candidate")
    return pair


def make_document(descriptions, receipts, before, pair):
    value = dict(descriptions=list(descriptions), receipts=list(receipts),
        records=[base64.b64encode(w.candidate).decode("ascii") for w in (pair.recipient_a, pair.recipient_b)],
        histories=[_encode(w.resulting_history) for w in (pair.recipient_a, pair.recipient_b)],
        outcome_sha256=pair.outcome_sha256)
    check_result(value, before, pair)
    return value


def structural_replay(document, before):
    """Check all independently derived bytes; never clear native authorization.

    Native-selected species/stats/moves cannot be verified by parsing a stored
    result. Those fields are only admitted after async native_replay below.
    """
    from .trade_effect_flash import _private_blocks_with_gifts
    from .ownership import inspect_ownership
    from .trade_flash import _party_record
    first, plans, leases, choices = _inputs(document, before)
    records = []
    for raw in document["records"]:
        require(type(raw) is str and len(raw) == 136, "invalid retained effect party record")
        try:
            record = base64.b64decode(raw, validate=True)
        except (ValueError, TypeError) as error:
            raise StorageError("trade_effect_invalid", "invalid retained native record") from error
        require(len(record) == 100 and base64.b64encode(record).decode("ascii") == raw, "noncanonical native record")
        records.append(record)
    record_cursor = iter(records)
    snapshots = [inspect_flash(cp.payload, save_profile=cp.save_profile) for cp in before]
    source_by_blocks = {s.save_block1: s for s in snapshots}
    def saved_blocks(block1, block2, partner, outgoing, incoming, friendship, decisions):
        snapshot = source_by_blocks[block1]
        i = snapshots.index(snapshot)
        require(snapshot.save_block2 == block2 and partner == snapshots[1-i].save_block1, "private source blocks differ")
        from .flash import SAVED_PARTY_OFFSET, POKEMON_SIZE
        off, _ = _party_record(snapshot, inspect_ownership(snapshot), plans[i].history.serial)
        peer_record = _party_record(snapshots[1-i], inspect_ownership(snapshots[1-i]), plans[1-i].history.serial)[1]
        require(outgoing == (off - SAVED_PARTY_OFFSET) // POKEMON_SIZE, "private source slot differs")
        return _private_blocks(snapshot, snapshots[1-i], off, peer_record, records[i])
    pair = prepare_effect_pair(before[0], plans[0], before[1], plans[1],
        transaction_id=first["transaction_id"], generation=first["generation"], fingerprint=first["fingerprint"],
        leases=leases, engine_source_sha256=first["effects"]["engine_source_sha256"],
        profile_game_version=first["effects"]["profile_game_version"], choices_a=choices[0], choices_b=choices[1],
        replay_native=lambda *_: next(record_cursor), replay_save_native=saved_blocks)
    return check_result(document, before, pair)


async def native_replay(adapter, document, before):
    first, plans, leases, choices = _inputs(document, before)
    require((adapter.engine_source_sha256, adapter.profile_game_version) ==
            (first["effects"]["engine_source_sha256"], first["effects"]["profile_game_version"]),
            "native worker differs from committed effect engine")
    pair = await adapter.prepare_pair(before[0], plans[0], before[1], plans[1], transaction_id=first["transaction_id"],
        generation=first["generation"], fingerprint=first["fingerprint"], leases=leases,
        choices_a=choices[0], choices_b=choices[1])
    return check_result(document, before, pair)


@dataclass(frozen=True)
class EffectCommitAuthority:
    owner: object
    document: dict
    pair: object


def audit_commit(store, transaction_id, before, after):
    row = store._connection.execute("SELECT * FROM trade_effect_commits WHERE transaction_id=?", (transaction_id,)).fetchone()
    if row is None:
        return False
    document = parse_document(row)
    pair = structural_replay(document, before)
    require((pair.after_a, pair.after_b) == tuple(after), "effect checkpoints differ from retained native proof")
    # The plan must use the authoritative history immediately preceding trade.
    first = document["descriptions"][0]
    require(first["effects"]["policy_id"] == read_effect_policy(store), "native history used another geographic policy")
    consent = store._connection.execute("SELECT * FROM trade_effect_proposals WHERE transaction_id=?", (transaction_id,)).fetchone()
    require(consent is not None and consent["state"] == "committed", "native result lacks durable completed consent")
    retained = parse_document(consent)
    ids = [p["player_id"] for p in first["players"]]
    require(retained.get("players") == ids and retained.get("confirmed") == ids
            and retained.get("preparations") == document["descriptions"]
            and retained.get("leases") == [p["lease_epoch"] for p in first["players"]]
            and (retained.get("transaction_id"), retained.get("generation")) == (transaction_id, first["generation"])
            and [retained.get("receipts", {}).get(p) for p in ids] == document["receipts"],
            "native publication differs from original durable mutual consent")
    expected_offers = [dict(player_id=p["player_id"], serial=p["serial"], revision=p["revision"], sha256=p["sha256"],
        species=_record_from_checkpoint(cp, p["serial"])[0][3]) for cp, p in zip(before, first["players"])]
    require(retained.get("offers") == expected_offers and type(retained.get("edit")) is int and 0 <= retained["edit"] <= 2147483647,
            "native publication changed the consented offered pair")
    material = [first["world_id"], transaction_id, first["generation"], retained["edit"],
        [[p["player_id"], p["lease_epoch"], p["revision"], p["sha256"], p["serial"]] for p in first["players"]]]
    fingerprint = hashlib.sha256(b"EM-TRADE-CONSENT-1\0" + json.dumps(material, separators=(",", ":")).encode("ascii")).hexdigest()
    require(fingerprint == first["fingerprint"], "native mutual-consent fingerprint changed")
    for cp, plan in zip(before, first["effects"]["offers"]):
        history = store._connection.execute("SELECT history FROM pokemon_friendship_history WHERE player_id=? AND revision=? AND serial=?",
            (cp.player_id, cp.revision, plan["history"]["serial"])).fetchone()
        require(history is not None and json.loads(history[0])["value"] == plan["history"],
                "native effect used noncanonical handler history")
    return True


def _record_from_checkpoint(checkpoint, serial):
    from .ownership import inspect_ownership
    from .trade_flash import _party_record
    from .trade_effect_witness import _record
    snapshot = inspect_flash(checkpoint.payload, save_profile=checkpoint.save_profile)
    return _record(_party_record(snapshot, inspect_ownership(snapshot), serial)[1])


def effect_history(store, sequence, serial, observation):
    row = store._connection.execute("SELECT e.* FROM trade_effect_commits e JOIN trade_transactions t USING(transaction_id) WHERE t.sequence=?",
                                    (sequence,)).fetchone()
    if row is None:
        return None
    document = parse_document(row)
    for value in document["histories"]:
        history = _decode(value)
        if history.serial == serial:
            active = history.handling_friendship if history.current_handler else history.original_friendship
            require(observation["native_role"] != "hatch_cycles" and observation["native_value"] == active,
                    "native post-image friendship differs from atomic handler history")
            return dict(state="ready", reason=None, value=value)
    return None


def enable_trade_effects(store, backup_path, *, policy_id):
    """Explicit idle, backed-up schema extension; this never enables a worker."""
    from .trade_effect_preparation import POLICIES
    require(policy_id in POLICIES, "an explicit approved geographic policy is required")
    require(store._base_schema_version == 3 and store.friendship_history_enabled,
            "complete migrated handler history is required before native effect publication")
    if store.trade_effects_enabled:
        require(read_effect_policy(store) == policy_id, "existing geographic policy cannot be silently replaced")
        store.integrity_check()
        return False
    lock = None
    if store._owner_lock is None:
        lock = _ExclusiveFileLock(store.path.with_name(store.path.name + ".owner.lock"))
        lock.acquire()
    old_schema, old_version = store._schema, store._schema_version
    try:
        store.integrity_check()
        require(not store._connection.execute("SELECT 1 FROM players WHERE lease_epoch IS NOT NULL").fetchone(),
                "close characters before native effect migration")
        backup = store.backup(Path(backup_path))
        with type(store)(backup, store.build_id, store.ruleset_id, store.save_profile,
                         max_payload_bytes=store.max_payload_bytes) as verified:
            require(verified.metadata == store.metadata and all(a == b for a, b in zip_longest(
                verified._connection.iterdump(), store._connection.iterdump())), "native effect backup differs from source")
        try:
            with store._transaction():
                require(not store._connection.execute("SELECT 1 FROM players WHERE lease_epoch IS NOT NULL").fetchone(),
                        "a character became active during native effect migration")
                for sql in EFFECT_SCHEMA.values():
                    store._connection.execute(sql)
                store._connection.execute("INSERT INTO trade_effect_policy VALUES (1,?)", (policy_id,))
                store._schema = {**old_schema, **EFFECT_SCHEMA}
                store._schema_version = old_version + EXTENSION_VERSION
                store._connection.execute(f"PRAGMA user_version = {store._schema_version}")
                store._validate_schema()
        finally:
            if store._connection.execute("PRAGMA user_version").fetchone()[0] == old_version:
                store._schema, store._schema_version = old_schema, old_version
        return True
    finally:
        if lock is not None:
            lock.release()
