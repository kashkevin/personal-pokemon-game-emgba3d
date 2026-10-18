"""A character that comes back to a world: the world records its newer save as the account's next source.

A world account holds one character's history (``ownership_storage``): the first source (``ownership_enrollments``), then
checkpoints. A character is universal (the owner's decision, 2026-10-18): the same trainer is played in Solo worlds and in
friends' worlds, and its Pokémon, levels and items go with it. When the character has progressed somewhere else since its
last checkpoint here, the world cannot continue the old history; instead it records a *transfer*: the character's current
save, detached from the other world (``character_transfer.detach_from_world``), becomes the source of the account's next
generation. The account keeps its history; nothing is rewritten or deleted:

* the transfer row names the revision it follows (``base_revision`` = the account's latest checkpoint when it was made);
* the next checkpoint (``base_revision + 1``) must keep exactly the transferred Pokémon in their places (as a first
  enrollment must keep its source), and every one of them gets a new identity of this world from a fresh allocation;
* every Pokémon the account still owned here from its earlier generation is retired at that checkpoint (reason 1, "left
  the world"), so no identity stays active twice and the history audit still balances;
* a transfer that has not been followed by a checkpoint yet may be replaced (a retry, or a newer save); once followed, it
  is history.

The transfer is refused while anything of the account is unfinished: a committed trade not yet applied, a battle
reservation, or a Pokémon of the incoming save that another account of this world owns right now (a copy of a Pokémon
traded away here). The world's host enables this once per world with a verified backup (``enable_character_transfers``).
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from itertools import zip_longest
from pathlib import Path

from .flash import FlashError, LAYOUT_ID, inspect_flash
from .ownership import extract_source_inventory
from .storage import StorageError, _ExclusiveFileLock, _player_id

EXTENSION_VERSION = 3200
TRANSFER_SCHEMA = {
    "ownership_transfers": """CREATE TABLE ownership_transfers (
        player_id TEXT NOT NULL REFERENCES players(player_id),
        base_revision INTEGER NOT NULL CHECK(base_revision > 0),
        source_sha256 TEXT NOT NULL CHECK(length(source_sha256) = 64),
        source_payload BLOB NOT NULL, source_profile TEXT NOT NULL,
        trainer_id INTEGER NOT NULL CHECK(trainer_id BETWEEN 0 AND 4294967295),
        inventory_json TEXT NOT NULL, inventory_sha256 TEXT NOT NULL CHECK(length(inventory_sha256) = 64),
        PRIMARY KEY(player_id, base_revision),
        FOREIGN KEY(player_id, base_revision) REFERENCES checkpoints(player_id, revision)
    )""",
}
RETIRE_LEFT_WORLD = 1   # the existing "released" reason: the Pokémon left this world with its trainer


@dataclass(frozen=True)
class Transfer:
    player_id: str
    base_revision: int
    source_sha256: str
    inventory_sha256: str
    count: int


@dataclass(frozen=True)
class Source:
    """The source a checkpoint's generation started from: the first enrollment (base 0) or a transfer."""
    trainer_id: int
    inventory_json: str
    base_revision: int
    source_sha256: str


def _inventory_of(payload):
    try:
        source = inspect_flash(payload, save_profile=LAYOUT_ID)
        records = extract_source_inventory(source)
    except FlashError as error:
        raise StorageError("invalid_enrollment", "a transferred character must be a valid save with no world identities") from error
    from .ownership_storage import _digest, _inventory
    text = _inventory(records)
    return source, records, text, _digest(text)


def source_for(store, player_id, revision):
    """The generation source for checkpoint ``revision`` of ``player_id`` (a pending transfer applies to latest + 1)."""
    if "ownership_transfers" in store._schema:
        row = store._connection.execute(
            "SELECT trainer_id, inventory_json, base_revision, source_sha256 FROM ownership_transfers "
            "WHERE player_id = ? AND base_revision < ? ORDER BY base_revision DESC LIMIT 1", (player_id, revision)).fetchone()
        if row is not None:
            return Source(row["trainer_id"], row["inventory_json"], row["base_revision"], row["source_sha256"])
    enrollment = store._enrollment(player_id)
    return Source(enrollment["trainer_id"], enrollment["inventory_json"], 0, enrollment["source_sha256"])


def pending_source(store, player_id):
    """('enroll' | 'transfer', base_revision, source_sha256) for a source not yet followed by a checkpoint, or None."""
    player = store._connection.execute("SELECT latest_revision FROM players WHERE player_id = ?", (player_id,)).fetchone()
    if player is None:
        return None
    latest = player["latest_revision"]
    if latest == 0:
        row = store._connection.execute("SELECT source_sha256 FROM ownership_enrollments WHERE player_id = ?", (player_id,)).fetchone()
        return ("enroll", 0, row["source_sha256"]) if row is not None else None
    if "ownership_transfers" in store._schema:
        row = store._connection.execute("SELECT source_sha256 FROM ownership_transfers WHERE player_id = ? AND base_revision = ?",
                                        (player_id, latest)).fetchone()
        if row is not None:
            return ("transfer", latest, row["source_sha256"])
    return None


def transfer_player(store, player_id, source_payload):
    """Record ``source_payload`` (a detached save) as the next source of a checkpointed account. Idempotent for the same
    bytes; replaces a transfer that no checkpoint has followed yet."""
    _player_id(player_id)
    if "ownership_transfers" not in store._schema:
        raise StorageError("transfer_unsupported", "this world has not been prepared for characters coming back")
    source, records, inventory, digest = _inventory_of(source_payload)
    source_sha = hashlib.sha256(source_payload).hexdigest()
    with store._transaction():
        if store._boot_epoch is not None:
            store._require_boot()
        player = store._connection.execute("SELECT * FROM players WHERE player_id = ?", (player_id,)).fetchone()
        if player is None:
            raise StorageError("player_not_found", "provision the player before transferring a character")
        base = player["latest_revision"]
        if base == 0:
            raise StorageError("enrollment_required", "an account with no checkpoint enrolls its first character instead")
        store._assert_no_battle_reservation(player_id)
        ensure = getattr(store, "_ensure_applied", None)
        if ensure is not None:
            ensure(player_id)
        used = store._connection.execute(
            "SELECT player_id FROM ownership_enrollments WHERE source_sha256 = ? UNION "
            "SELECT player_id FROM ownership_transfers WHERE source_sha256 = ?", (source_sha, source_sha)).fetchall()
        if any(row["player_id"] != player_id for row in used):
            raise StorageError("source_already_enrolled", "that exact character save is already another account's")
        for record in records:
            other = store._connection.execute(
                "SELECT player_id FROM ownership_instances WHERE personality = ? AND ot_id = ? AND status = 'active' AND player_id != ?",
                (record.personality, record.ot_id, player_id)).fetchone()
            if other is not None:
                raise StorageError("pokemon_owned_here", "a Pokémon of this character belongs to another trainer in this world")
        prior = store._connection.execute("SELECT * FROM ownership_transfers WHERE player_id = ? AND base_revision = ?",
                                          (player_id, base)).fetchone()
        if prior is not None:
            if prior["source_sha256"] == source_sha and prior["source_payload"] == source_payload:
                return Transfer(player_id, base, source_sha, prior["inventory_sha256"], len(records))
            store._connection.execute("DELETE FROM ownership_transfers WHERE player_id = ? AND base_revision = ?", (player_id, base))
        store._connection.execute("INSERT INTO ownership_transfers VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (player_id, base, source_sha, source_payload, LAYOUT_ID, source.metadata.trainer_id, inventory, digest))
    return Transfer(player_id, base, source_sha, digest, len(records))


def audit_transfers(store, corrupt):
    """Every transfer row is a valid detached save matching its digests, follows a real checkpoint, and is either the
    account's single pending source or was followed by the next checkpoint."""
    if "ownership_transfers" not in store._schema:
        return
    for row in store._connection.execute("SELECT * FROM ownership_transfers"):
        try:
            source, _, inventory, digest = _inventory_of(row["source_payload"])
        except StorageError:
            corrupt("a character transfer source is invalid")
        if (hashlib.sha256(row["source_payload"]).hexdigest(), source.metadata.trainer_id, inventory, digest, row["source_profile"]) != (
                row["source_sha256"], row["trainer_id"], row["inventory_json"], row["inventory_sha256"], LAYOUT_ID):
            corrupt("character transfer provenance changed")
        latest = store._connection.execute("SELECT latest_revision FROM players WHERE player_id = ?", (row["player_id"],)).fetchone()
        if latest is None or row["base_revision"] > latest["latest_revision"]:
            corrupt("character transfer follows a revision the account never reached")


def enable_character_transfers(store, backup_path):
    """Add the transfer table to an idle world after a verified backup (the same procedure as the other extensions)."""
    if not getattr(store, "_supports_battle_reservations", False) or store._base_schema_version != 3:
        raise StorageError("transfer_migration_unsupported", "characters coming back need a schema-3 ownership world")
    if "ownership_transfers" in store._schema:
        store.integrity_check()
        return False
    lock = None
    if store._owner_lock is None:
        lock = _ExclusiveFileLock(store.path.with_name(store.path.name + ".owner.lock"))
        try:
            lock.acquire()
        except OSError as error:
            raise StorageError("host_active", "close the host before preparing the world") from error
    old_schema, old_version = store._schema, store._schema_version
    try:
        store.integrity_check()
        if store._connection.execute("SELECT 1 FROM players WHERE lease_epoch IS NOT NULL").fetchone():
            raise StorageError("lease_active", "close characters before preparing the world")
        backup = store.backup(Path(backup_path))
        with type(store)(backup, store.build_id, store.ruleset_id, store.save_profile,
                         max_payload_bytes=store.max_payload_bytes) as verified:
            if verified.metadata != store.metadata or any(a != b for a, b in zip_longest(
                    verified._connection.iterdump(), store._connection.iterdump())):
                raise StorageError("transfer_migration_backup", "the backup differs from the world")
        try:
            with store._transaction():
                store._validate_schema()
                if store._connection.execute("SELECT 1 FROM players WHERE lease_epoch IS NOT NULL").fetchone():
                    raise StorageError("lease_active", "a character became active while preparing the world")
                for sql in TRANSFER_SCHEMA.values():
                    store._connection.execute(sql)
                store._schema = {**old_schema, **TRANSFER_SCHEMA}
                store._schema_version = old_version + EXTENSION_VERSION
                store._connection.execute(f"PRAGMA user_version = {store._schema_version}")
                store._validate_schema()
        except BaseException:
            store._schema, store._schema_version = old_schema, old_version
            raise
        store.integrity_check()
        return True
    finally:
        if lock is not None:
            lock.release()


__all__ = ["EXTENSION_VERSION", "TRANSFER_SCHEMA", "RETIRE_LEFT_WORLD", "Source", "Transfer", "audit_transfers",
           "enable_character_transfers", "pending_source", "source_for", "transfer_player"]
