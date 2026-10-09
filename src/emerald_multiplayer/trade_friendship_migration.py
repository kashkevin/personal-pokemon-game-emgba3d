"""Explicit, backed-up legacy handler initialization in the canonical database.

The owner selected Gen6 species base friendship for missing handler values.
This ledger preserves the observed active byte and every retained opposite value.
It never edits a save, enables effectful trading, or invents a past trainer name.
"""
from dataclasses import replace
from itertools import zip_longest
import hashlib
import json
from pathlib import Path

from .gen6_friendship import TABLE_ID, VALUES_SHA256, base_friendship
from .storage import StorageError, _ExclusiveFileLock
from .trade_friendship import FriendshipHistory, FriendshipPlanError, TrainerIdentity, _integer
from .trade_friendship_observations import checkpoint_observations

POLICY_ID = "gen6-base-missing-handler-values-v1"
# Pinned include/constants/global.h, VERSION_EMERALD (not a guessed game ID).
PROFILE_GAME_VERSION = 3
EXTENSION_VERSION = 800
HISTORY_SCHEMA = {
    "pokemon_friendship_policy": """CREATE TABLE pokemon_friendship_policy (
        singleton INTEGER PRIMARY KEY CHECK(singleton = 1), policy_id TEXT NOT NULL,
        table_id TEXT NOT NULL, table_sha256 TEXT NOT NULL, game_version INTEGER NOT NULL)""",
    "pokemon_friendship_history": """CREATE TABLE pokemon_friendship_history (
        serial INTEGER NOT NULL, sequence INTEGER NOT NULL REFERENCES commit_groups(sequence),
        player_id TEXT NOT NULL, revision INTEGER NOT NULL, history TEXT NOT NULL,
        sha256 TEXT NOT NULL CHECK(length(sha256) = 64), PRIMARY KEY(serial, sequence),
        UNIQUE(player_id, revision, serial), FOREIGN KEY(player_id, revision, serial)
            REFERENCES ownership_memberships(player_id, revision, serial))""",
}
_POLICY_ROW = (1, POLICY_ID, TABLE_ID, VALUES_SHA256, PROFILE_GAME_VERSION)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def initialize_missing_history(serial, original, owner, native_value, species, *, partial=None):
    """Initialize absent values only; preserve known values or reject a conflict.

    A missing previous handling identity stays None for an original owner. This
    is explicitly initialized history, never evidence of a never-traded mon.
    Eggs must be excluded by the canonical-record caller before this operation.
    """
    if type(original) is not TrainerIdentity or type(owner) is not TrainerIdentity:
        raise FriendshipPlanError("initialization requires canonical trainer identities")
    original.validate()
    owner.validate()
    _integer(native_value, 255, "observed native friendship")
    base = base_friendship(species)
    current = int(owner != original)
    if partial is None:
        partial = FriendshipHistory(serial, original, None, None, None, None, False)
    if (type(partial) is not FriendshipHistory or partial.serial != serial or partial.original != original
            or type(partial.known) is not bool or partial.current_handler not in (None, current)
            or partial.current_handler is not None and type(partial.current_handler) is not int):
        raise FriendshipPlanError("partial history differs from its canonical instance or owner")
    if partial.known:
        partial.validate()
    if partial.handler is not None:
        if type(partial.handler) is not TrainerIdentity:
            raise FriendshipPlanError("invalid retained handling identity")
        partial.handler.validate()
    if (type(partial.initialized_fields) is not tuple
            or any(type(key) is not str or key not in ("original_friendship", "handling_friendship")
                   for key in partial.initialized_fields)
            or partial.initialized_fields != tuple(sorted(set(partial.initialized_fields)))
            or type(partial.handler_identity_unknown) is not bool):
        raise FriendshipPlanError("invalid retained initialization provenance")
    handler = partial.handler
    if current:
        if handler is not None and handler.handler_key != owner.handler_key:
            raise FriendshipPlanError("retained current handler differs from the canonical owner")
        if handler is None:
            handler = owner
    active = "handling_friendship" if current else "original_friendship"
    values = {key: getattr(partial, key) for key in ("original_friendship", "handling_friendship")}
    initialized = list(partial.initialized_fields)
    for key, value in values.items():
        if value is not None:
            _integer(value, 255, key)
            if key == active and value != native_value:
                raise FriendshipPlanError("known active friendship differs from its exact native byte")
        else:
            # Active friendship is already known from this save. Only the
            # absent opposite value needs the owner's approved initialization.
            values[key] = native_value if key == active else base
            if key != active:
                initialized.append(key)
    return replace(partial, **values, handler=handler, current_handler=current, known=True,
                   handler_identity_unknown=handler is None and (not partial.known or partial.handler_identity_unknown),
                   initialized_fields=tuple(sorted(set(initialized)))).validate()


def _identity(value):
    return [value.name.hex(), value.gender, value.trainer_id, value.version]


def _encode(history):
    history.validate()
    return dict(serial=history.serial, original=_identity(history.original),
        original_friendship=history.original_friendship,
        handler=None if history.handler is None else _identity(history.handler),
        handling_friendship=history.handling_friendship, current_handler=history.current_handler,
        initialized_fields=list(history.initialized_fields), handler_identity_unknown=history.handler_identity_unknown)


def _decode(value):
    if type(value) is not dict or set(value) != {"serial", "original", "original_friendship", "handler",
            "handling_friendship", "current_handler", "initialized_fields", "handler_identity_unknown"}:
        raise FriendshipPlanError("retained friendship fields differ")
    def trainer(fields):
        if type(fields) is not list or len(fields) != 4 or type(fields[0]) is not str:
            raise FriendshipPlanError("retained trainer representation differs")
        identity = TrainerIdentity(bytes.fromhex(fields[0]), *fields[1:]).validate()
        if _identity(identity) != fields:
            raise FriendshipPlanError("retained trainer encoding is noncanonical")
        return identity
    if type(value["initialized_fields"]) is not list:
        raise FriendshipPlanError("retained initialization provenance differs")
    return FriendshipHistory(value["serial"], trainer(value["original"]), value["original_friendship"],
        None if value["handler"] is None else trainer(value["handler"]), value["handling_friendship"],
        value["current_handler"], True, tuple(value["initialized_fields"]), value["handler_identity_unknown"]).validate()


def _advance(serial, observation, previous):
    if observation["native_role"] == "hatch_cycles":
        return dict(state="unknown", reason="egg_hatch_cycles", value=None)
    ot, trainer = observation["original"], observation["owner"]
    original = TrainerIdentity(bytes.fromhex(ot["name"]), ot["gender"], ot["trainer_id"], ot["version"])
    owner = TrainerIdentity(bytes.fromhex(trainer["name"]), trainer["gender"], trainer["trainer_id"], PROFILE_GAME_VERSION)
    original.validate()
    owner.validate()
    history = _decode(previous["value"]) if previous is not None and previous["state"] == "ready" else None
    if history is None:
        if not 1 <= observation["species"] <= 721:
            return dict(state="unknown", reason="unmapped_species_base", value=None)
        history = initialize_missing_history(serial, original, owner, observation["native_value"], observation["species"])
    else:
        if (history.serial, history.original) != (serial, original):
            raise FriendshipPlanError("retained non-egg instance changed its original trainer")
        current = int(original != owner)
        changes = {"current_handler": current,
                   "handling_friendship" if current else "original_friendship": observation["native_value"]}
        if current:
            # Existing exact-swap trades are observations, not retrospective
            # Gen6 effects. Preserve the real native byte, even across owners.
            changes["handler"] = owner
            changes["handler_identity_unknown"] = False
        history = replace(history, **changes).validate()
    return dict(state="ready", reason=None, value=_encode(history))


class FriendshipHistoryLedger:
    """Canonical commit-group companion; no public packet or client authority."""
    def __init__(self, store):
        if not store.friendship_history_enabled:
            raise StorageError("friendship_migration_required", "handler history requires the explicit backed-up migration")
        self.store = store

    def _policy(self):
        rows = self.store._connection.execute("SELECT * FROM pokemon_friendship_policy").fetchall()
        if len(rows) != 1 or tuple(rows[0]) != _POLICY_ROW:
            raise StorageError("friendship_history_invalid", "retained initialization policy differs")

    def _entry(self, checkpoint, sequence, serial, observation, previous):
        prior = json.loads(previous[4]) if previous is not None else None
        value = None
        if self.store.trade_effects_enabled:
            from .trade_effect_storage import effect_history
            value = effect_history(self.store, sequence, serial, observation)
        if value is None:
            value = _advance(serial, observation, prior)
        value["previous_sha256"] = None if previous is None else previous[5]
        raw = _json(value)
        digest = hashlib.sha256(_json([list(_POLICY_ROW), self.store._validate_metadata()["world_id"],
            checkpoint.build_id, checkpoint.ruleset_id, checkpoint.save_profile, checkpoint.player_id,
            checkpoint.revision, checkpoint.request_id, checkpoint.sha256, sequence, serial, value]).encode("ascii")).hexdigest()
        return serial, sequence, checkpoint.player_id, checkpoint.revision, raw, digest

    def _checkpoints(self, sequence=None):
        query = "SELECT c.*, o.sequence FROM checkpoints c JOIN checkpoint_order o USING(player_id,revision)"
        args = ()
        if sequence is not None:
            query += " WHERE o.sequence=?"
            args = (sequence,)
        return self.store._connection.execute(query + " ORDER BY o.sequence,c.player_id", args)

    def _append_group(self, sequence):
        connection = self.store._connection
        if not connection.in_transaction:
            raise StorageError("friendship_transaction_required", "handler history must share the canonical save transaction")
        self._policy()
        for saved in self._checkpoints(sequence):
            checkpoint = self.store._checkpoint(saved)
            for _, _, serial, raw, _ in checkpoint_observations(checkpoint):
                previous = connection.execute("SELECT * FROM pokemon_friendship_history WHERE serial=? AND sequence<? ORDER BY sequence DESC LIMIT 1",
                                              (serial, sequence)).fetchone()
                row = self._entry(checkpoint, sequence, serial, json.loads(raw), previous)
                connection.execute("INSERT INTO pokemon_friendship_history VALUES (?,?,?,?,?,?)", row)

    def _integrity(self):
        self._policy()
        # Reconstruct independently of retained rows, globally ordered. Trade
        # post-images share one group; ownership replay rejects duplicate UIDs.
        previous, seen, last_sequence = {}, set(), None
        actual_rows = iter(self.store._connection.execute(
            "SELECT * FROM pokemon_friendship_history ORDER BY sequence,player_id,serial"))
        for saved in self._checkpoints():
            checkpoint, sequence = self.store._checkpoint(saved), saved["sequence"]
            if sequence != last_sequence:
                seen, last_sequence = set(), sequence
            for _, _, serial, raw, _ in checkpoint_observations(checkpoint):
                key = serial, sequence
                if key in seen:
                    raise StorageError("friendship_history_invalid", "an instance is duplicated within one commit group")
                seen.add(key)
                row = self._entry(checkpoint, sequence, serial, json.loads(raw), previous.get(serial))
                actual = next(actual_rows, None)
                if actual is None or tuple(actual) != row:
                    raise StorageError("friendship_history_invalid", "handler history differs from canonical observations and policy")
                previous[serial] = row
        if next(actual_rows, None) is not None:
            raise StorageError("friendship_history_invalid", "handler history contains extra observations")

    def read_current(self, player_id, lease_epoch, serial):
        """Return only the authenticated owner's current complete typed history."""
        if type(serial) is not int or not 1 <= serial <= 1048575:
            raise StorageError("invalid_field", "an assigned owned instance is required")
        with self.store._transaction():
            player = self.store._require_lease(player_id, lease_epoch)
            owned = self.store._connection.execute("SELECT * FROM ownership_instances WHERE serial=?", (serial,)).fetchone()
            if owned is None or owned["status"] != "active" or owned["player_id"] != player_id:
                raise StorageError("foreign_ownership", "handler history belongs to another character")
            self._policy()
            row = self.store._connection.execute("SELECT * FROM pokemon_friendship_history WHERE player_id=? AND revision=? AND serial=?",
                (player_id, player["latest_revision"], serial)).fetchone()
            if row is None:
                raise StorageError("friendship_history_invalid", "current canonical handler history is missing")
            saved = self.store._connection.execute("SELECT * FROM checkpoints WHERE player_id=? AND revision=?",
                (player_id, player["latest_revision"])).fetchone()
            order = self.store._connection.execute("SELECT sequence FROM checkpoint_order WHERE player_id=? AND revision=?",
                (player_id, player["latest_revision"])).fetchone()
            if saved is None or order is None or order["sequence"] != row["sequence"]:
                raise StorageError("friendship_history_invalid", "current handler history lacks its canonical commit group")
            checkpoint = self.store._checkpoint(saved)
            observation = next((json.loads(raw) for _, _, uid, raw, _ in checkpoint_observations(checkpoint) if uid == serial), None)
            previous = self.store._connection.execute("SELECT * FROM pokemon_friendship_history WHERE serial=? AND sequence<? ORDER BY sequence DESC LIMIT 1",
                (serial, row["sequence"])).fetchone()
            if observation is None or tuple(row) != self._entry(checkpoint, row["sequence"], serial, observation, previous):
                raise StorageError("friendship_history_invalid", "current handler history differs from its canonical record")
            value = json.loads(row["history"])
            if value["state"] != "ready":
                raise StorageError("friendship_history_unknown", value["reason"])
            return _decode(value["value"])


def enable_friendship_history(store, backup_path):
    """Explicit idle migration; never called automatically by opening a world.

    A new verified backup precedes an all-or-nothing schema/backfill transaction.
    No private world has been migrated by developing this source function.
    """
    if store._base_schema_version != 3 or "trade_transactions" not in store._base_schema:
        raise StorageError("friendship_migration_unsupported", "handler history requires an ownership trade world")
    if store.friendship_history_enabled:
        store.integrity_check()
        return False
    lock = None
    if store._owner_lock is None:
        lock = _ExclusiveFileLock(store.path.with_name(store.path.name + ".owner.lock"))
        try:
            lock.acquire()
        except OSError as error:
            raise StorageError("host_active", "close the host before handler history migration") from error
    old_schema, old_version = store._schema, store._schema_version
    try:
        store.integrity_check()
        if store._connection.execute("SELECT 1 FROM players WHERE lease_epoch IS NOT NULL").fetchone():
            raise StorageError("lease_active", "close characters before handler history migration")
        backup = store.backup(Path(backup_path))
        with type(store)(backup, store.build_id, store.ruleset_id, store.save_profile,
                         max_payload_bytes=store.max_payload_bytes) as verified:
            if verified.metadata != store.metadata or any(a != b for a, b in zip_longest(
                    verified._connection.iterdump(), store._connection.iterdump())):
                raise StorageError("friendship_migration_backup", "handler history backup differs from its source")
        try:
            with store._transaction():
                store._validate_schema()
                if store._connection.execute("SELECT 1 FROM players WHERE lease_epoch IS NOT NULL").fetchone():
                    raise StorageError("lease_active", "a character became active during handler history migration")
                for sql in HISTORY_SCHEMA.values():
                    store._connection.execute(sql)
                store._schema = {**old_schema, **HISTORY_SCHEMA}
                store._schema_version = old_version + EXTENSION_VERSION
                store._connection.execute(f"PRAGMA user_version = {store._schema_version}")
                store._connection.execute("INSERT INTO pokemon_friendship_policy VALUES (?,?,?,?,?)", _POLICY_ROW)
                ledger = FriendshipHistoryLedger(store)
                for group in store._connection.execute("SELECT sequence FROM commit_groups ORDER BY sequence"):
                    ledger._append_group(group[0])
                store._validate_schema()
                ledger._integrity()
        finally:
            if store._connection.execute("PRAGMA user_version").fetchone()[0] == old_version:
                store._schema, store._schema_version = old_schema, old_version
        store.integrity_check()
        return True
    finally:
        if lock is not None:
            lock.release()
