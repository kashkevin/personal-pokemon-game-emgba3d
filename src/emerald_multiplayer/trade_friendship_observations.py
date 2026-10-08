"""Optional same-database native friendship observations, never invented history.

Every row is reproducible from its immutable canonical checkpoint. It records
the active native byte and explicit unknown handler history; it cannot authorize
Gen6 side effects or initialize absent opposite-handler friendship.
"""
from itertools import zip_longest
import hashlib
import json
from pathlib import Path
import struct

from .flash import (
    BOX_CAPACITY, BOX_POKEMON_SIZE, FUSIONS_OFFSET, POKEMON_SIZE,
    SAVED_PARTY_OFFSET, FlashError, inspect_flash,
)
from .ownership import (
    DAYCARE_OFFSET, DAYCARE_MON_SIZE, OWNERSHIP_PROFILE, SERIAL_MAX,
    _SUBSTRUCT_OFFSETS, _decode_box, inspect_ownership,
)
from .storage import Checkpoint, StorageError, _ExclusiveFileLock, _counter, _player_id

EXTENSION_VERSION = 400
OBSERVATION_SCHEMA = {
    "pokemon_friendship_observations": """CREATE TABLE pokemon_friendship_observations (
        player_id TEXT NOT NULL, revision INTEGER NOT NULL, serial INTEGER NOT NULL,
        observation TEXT NOT NULL, sha256 TEXT NOT NULL CHECK(length(sha256) = 64),
        PRIMARY KEY(player_id, revision, serial),
        FOREIGN KEY(player_id, revision, serial)
            REFERENCES ownership_memberships(player_id, revision, serial))""",
}


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _box(snapshot, location):
    # Locations come from inspect_ownership, never directly from a request.
    parts = location.split(":")
    if parts[0] == "party":
        data, offset = snapshot.save_block1, SAVED_PARTY_OFFSET + int(parts[1])*POKEMON_SIZE
    elif parts[0] == "box":
        data, offset = snapshot.storage, 4 + (int(parts[1])*BOX_CAPACITY+int(parts[2]))*BOX_POKEMON_SIZE
    elif parts[0] == "daycare":
        data, offset = snapshot.save_block1, DAYCARE_OFFSET + int(parts[1])*DAYCARE_MON_SIZE
    elif parts[0] == "fusion":
        data, offset = snapshot.storage, FUSIONS_OFFSET + int(parts[1])*POKEMON_SIZE
    else:
        raise ValueError("unknown validated ownership location")
    return data[offset:offset+BOX_POKEMON_SIZE]


def checkpoint_observations(checkpoint):
    """Return deterministic rows for all occupied ownership locations.

    Neither an original-trainer match nor first allocation means never traded.
    All historical handler values remain unknown until separate qualified
    provenance exists. Eggs label the native byte as hatch cycles explicitly.
    """
    try:
        if type(checkpoint) is not Checkpoint or type(checkpoint.payload) is not bytes:
            raise ValueError("immutable checkpoint required")
        _player_id(checkpoint.player_id)
        _counter(checkpoint.revision, "revision", 1)
        if (checkpoint.save_profile != OWNERSHIP_PROFILE
                or hashlib.sha256(checkpoint.payload).hexdigest() != checkpoint.sha256):
            raise ValueError("checkpoint profile or hash differs")
        snapshot = inspect_flash(checkpoint.payload, save_profile=OWNERSHIP_PROFILE)
        owned = inspect_ownership(snapshot)
        if owned.player_id != checkpoint.player_id:
            raise ValueError("checkpoint owner differs")
        rows = []
        for record in sorted(owned.records, key=lambda record: record.serial):
            box = _box(snapshot, record.location)
            serial, pid, ot, species, content = _decode_box(box, record.location)
            if (serial, pid, ot, species, content) != (record.serial, record.personality, record.ot_id,
                                                      record.species, record.content_sha256):
                raise ValueError("observation source differs from the ownership record")
            plain = struct.pack("<12I", *(v ^ pid ^ ot for v in struct.unpack_from("<12I", box, 32)))
            growth, misc = (_SUBSTRUCT_OFFSETS[i][pid % 24]*12 for i in (0, 3))
            origins = struct.unpack_from("<H", plain, misc+2)[0]
            egg = bool(box[19] & 4 or struct.unpack_from("<I", plain, misc+4)[0] & (1 << 30))
            value = {
                "schema": 1, "location": record.location, "personality": pid, "species": species,
                "original": {"name": box[20:27].split(b"\xff", 1)[0].hex(), "gender": origins >> 15,
                             "trainer_id": ot, "version": (origins >> 7) & 15},
                "owner": {"name": snapshot.metadata.name.hex(), "gender": snapshot.metadata.gender,
                          "trainer_id": snapshot.metadata.trainer_id},
                "native_value": plain[growth+9], "native_role": "hatch_cycles" if egg else "friendship",
                "handler_history": "unknown",
            }
            raw = _json(value)
            digest = hashlib.sha256(_json([owned.world_id, checkpoint.player_id, checkpoint.revision,
                checkpoint.request_id, checkpoint.sha256, checkpoint.build_id, checkpoint.ruleset_id,
                checkpoint.save_profile, serial, value]).encode("ascii")).hexdigest()
            rows.append((checkpoint.player_id, checkpoint.revision, serial, raw, digest))
        return tuple(rows)
    except (FlashError, ValueError, TypeError, KeyError, struct.error) as error:
        raise StorageError("friendship_observation_invalid", "canonical native friendship observation failed validation") from error


class FriendshipObservations:
    def __init__(self, store):
        if not store.friendship_observations_enabled:
            raise StorageError("friendship_migration_required", "friendship observations require an explicit backed-up migration")
        self.store = store

    def _append(self, checkpoint):
        connection = self.store._connection
        if not connection.in_transaction:
            raise StorageError("friendship_transaction_required", "friendship observation must share its canonical transaction")
        saved = connection.execute("SELECT * FROM checkpoints WHERE player_id=? AND revision=?",
                                   (checkpoint.player_id, checkpoint.revision)).fetchone()
        if saved is None or self.store._checkpoint(saved) != checkpoint:
            raise StorageError("friendship_observation_invalid", "observation lacks its exact canonical checkpoint")
        connection.executemany("INSERT INTO pokemon_friendship_observations VALUES (?,?,?,?,?)",
                               checkpoint_observations(checkpoint))

    def _integrity(self):
        connection = self.store._connection
        observed = iter(connection.execute(
            "SELECT * FROM pokemon_friendship_observations ORDER BY player_id,revision,serial"))
        for row in connection.execute("SELECT * FROM checkpoints ORDER BY player_id,revision"):
            for expected in checkpoint_observations(self.store._checkpoint(row)):
                actual = next(observed, None)
                if actual is None or tuple(actual) != expected:
                    raise StorageError("friendship_observation_invalid", "friendship observation history differs from immutable payloads")
        if next(observed, None) is not None:
            raise StorageError("friendship_observation_invalid", "friendship observation history has extra records")

    def read_current(self, player_id, lease_epoch, serial):
        """Authenticated observation of an instance currently owned by this player."""
        if type(serial) is not int or not 1 <= serial <= SERIAL_MAX:
            raise StorageError("invalid_field", "friendship serial is outside ownership bounds")
        with self.store._transaction():
            player = self.store._require_lease(player_id, lease_epoch)
            owned = self.store._connection.execute("SELECT * FROM ownership_instances WHERE serial=?", (serial,)).fetchone()
            if owned is None or owned["player_id"] != player_id or owned["status"] != "active":
                raise StorageError("foreign_ownership", "this instance is not currently owned by the player")
            checkpoint = self.store._connection.execute("SELECT * FROM checkpoints WHERE player_id=? AND revision=?",
                                                        (player_id, player["latest_revision"])).fetchone()
            if checkpoint is None:
                raise StorageError("friendship_observation_invalid", "current owner lacks its canonical checkpoint")
            expected = next((row for row in checkpoint_observations(self.store._checkpoint(checkpoint)) if row[2] == serial), None)
            actual = self.store._connection.execute("SELECT * FROM pokemon_friendship_observations WHERE player_id=? AND revision=? AND serial=?",
                                                    (player_id, player["latest_revision"], serial)).fetchone()
            if expected is None or actual is None or tuple(actual) != expected:
                raise StorageError("friendship_observation_invalid", "current observation differs from its canonical payload")
            return json.loads(expected[3])


def enable_friendship_observations(store, backup_path):
    """Explicit idle migration with a verified new backup and complete backfill."""
    if store._base_schema_version != 3 or "trade_transactions" not in store._base_schema:
        raise StorageError("friendship_migration_unsupported", "friendship observations require an ownership trade world")
    if store.friendship_observations_enabled:
        store.integrity_check()
        return False
    lock = None
    if store._owner_lock is None:
        lock = _ExclusiveFileLock(store.path.with_name(store.path.name + ".owner.lock"))
        try:
            lock.acquire()
        except OSError as error:
            raise StorageError("host_active", "close the host before friendship observation migration") from error
    old_schema, old_version = store._schema, store._schema_version
    try:
        store.integrity_check()
        if store._connection.execute("SELECT 1 FROM players WHERE lease_epoch IS NOT NULL").fetchone():
            raise StorageError("lease_active", "close characters before friendship observation migration")
        backup = store.backup(Path(backup_path))
        with type(store)(backup, store.build_id, store.ruleset_id, store.save_profile,
                         max_payload_bytes=store.max_payload_bytes) as verified:
            if verified.metadata != store.metadata or any(a != b for a, b in zip_longest(
                    verified._connection.iterdump(), store._connection.iterdump())):
                raise StorageError("friendship_migration_backup", "friendship observation backup differs from its source")
        try:
            with store._transaction():
                store._validate_schema()
                if store._connection.execute("SELECT 1 FROM players WHERE lease_epoch IS NOT NULL").fetchone():
                    raise StorageError("lease_active", "a character became active during friendship observation migration")
                for sql in OBSERVATION_SCHEMA.values():
                    store._connection.execute(sql)
                store._schema = {**old_schema, **OBSERVATION_SCHEMA}
                store._schema_version = old_version + EXTENSION_VERSION
                store._connection.execute(f"PRAGMA user_version = {store._schema_version}")
                store._validate_schema()
                ledger = FriendshipObservations(store)
                for row in store._connection.execute("SELECT * FROM checkpoints ORDER BY player_id,revision"):
                    ledger._append(store._checkpoint(row))
                ledger._integrity()
        finally:
            if store._connection.execute("PRAGMA user_version").fetchone()[0] == old_version:
                store._schema, store._schema_version = old_schema, old_version
        store.integrity_check()
        return True
    finally:
        if lock is not None:
            lock.release()
