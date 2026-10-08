"""Same-database, lease-bound personal attempt receipts with explicit migration.

An attempt begins when an authored interaction is durably admitted. If its ACK
is lost, retrying that exact native request returns its original number. The
record never contains a seed, PID, shiny value, reward or character snapshot.
"""
from itertools import zip_longest
import hashlib
import json
from pathlib import Path

from .reset_protocol import ENCOUNTERS, SCOPE, validate_reset_request
from .protocol import ProtocolError
from .storage import StorageError, _ExclusiveFileLock, _counter, _player_id

EXTENSION_VERSION = 200
ATTEMPT_SCHEMA = {
    "personal_reset_attempts": """CREATE TABLE personal_reset_attempts (
        player_id TEXT NOT NULL REFERENCES players(player_id),
        encounter_id INTEGER NOT NULL, attempt INTEGER NOT NULL CHECK(attempt BETWEEN 1 AND 4294967295),
        request_id TEXT NOT NULL, server_epoch INTEGER NOT NULL, lease_epoch INTEGER NOT NULL,
        incarnation INTEGER NOT NULL, sequence INTEGER NOT NULL, observed_count INTEGER NOT NULL,
        checkpoint_revision INTEGER NOT NULL, sha256 TEXT NOT NULL,
        PRIMARY KEY(player_id, encounter_id, attempt), UNIQUE(player_id, request_id),
        UNIQUE(player_id, server_epoch, lease_epoch, incarnation, sequence),
        FOREIGN KEY(player_id, checkpoint_revision) REFERENCES checkpoints(player_id, revision))""",
}


def _digest(values):
    return hashlib.sha256(json.dumps(values, separators=(",", ":"), ensure_ascii=True).encode("ascii")).hexdigest()


def enable_reset_attempts(store, backup_path):
    """Add the optional ledger only while idle, after verifying a new backup."""
    if not store._supports_battle_reservations or store._base_schema_version not in (2, 3):
        raise StorageError("reset_migration_unsupported", "personal attempts require an ownership world")
    if store.reset_attempts_enabled:
        store.integrity_check()
        return False
    lock = None
    if store._owner_lock is None:
        lock = _ExclusiveFileLock(store.path.with_name(store.path.name + ".owner.lock"))
        try:
            lock.acquire()
        except OSError as error:
            raise StorageError("host_active", "close the host before personal attempt migration") from error
    old_schema, old_version = store._schema, store._schema_version
    try:
        store.integrity_check()
        if store._connection.execute("SELECT 1 FROM players WHERE lease_epoch IS NOT NULL").fetchone():
            raise StorageError("lease_active", "close characters before personal attempt migration")
        backup = store.backup(Path(backup_path))
        with type(store)(backup, store.build_id, store.ruleset_id, store.save_profile,
                         max_payload_bytes=store.max_payload_bytes) as verified:
            if verified.metadata != store.metadata or any(a != b for a, b in zip_longest(
                    verified._connection.iterdump(), store._connection.iterdump())):
                raise StorageError("reset_migration_backup", "personal attempt backup differs from its source")
        try:
            with store._transaction():
                store._validate_schema()
                if store._connection.execute("SELECT 1 FROM players WHERE lease_epoch IS NOT NULL").fetchone():
                    raise StorageError("lease_active", "a character became active during migration")
                for sql in ATTEMPT_SCHEMA.values():
                    store._connection.execute(sql)
                store._schema = {**old_schema, **ATTEMPT_SCHEMA}
                store._schema_version = old_version + EXTENSION_VERSION
                store._connection.execute(f"PRAGMA user_version = {store._schema_version}")
                store._validate_schema()
                ResetAttempts(store)._integrity()
        finally:
            if store._connection.execute("PRAGMA user_version").fetchone()[0] == old_version:
                store._schema, store._schema_version = old_schema, old_version
        store.integrity_check()
        return True
    finally:
        if lock is not None:
            lock.release()


class ResetAttempts:
    def __init__(self, store):
        if not store.reset_attempts_enabled:
            raise StorageError("reset_migration_required", "personal attempts require an explicit backed-up migration")
        self.store = store

    def _read(self, row):
        values = list(row)[:-1]
        try:
            actor, encounter, attempt, request_id, server, lease, incarnation, sequence, observed, revision = values
            _player_id(actor); _player_id(request_id)
            for value, name in ((server, "server"), (lease, "lease"), (revision, "revision")):
                _counter(value, name, 1)
            validate_reset_request(dict(type="reset_begin", request_id=request_id, session_epoch=lease,
                encounter_id=encounter, incarnation=incarnation, sequence=sequence, observed_count=observed), lease)
            metadata = self.store._validate_metadata()
            if (type(attempt) is not int or not observed < attempt <= 0xFFFFFFFF
                    or server > metadata["server_epoch"] or lease > metadata["session_epoch"]
                    or row["sha256"] != _digest(values)):
                raise ValueError()
            return dict(scope=SCOPE, encounter_id=encounter, incarnation=incarnation, sequence=sequence, attempt=attempt)
        except (ValueError, TypeError, ProtocolError) as error:
            raise StorageError("reset_attempt_invalid", "personal attempt record failed integrity verification") from error

    def _integrity(self):
        counts = {}
        for row in self.store._connection.execute(
                "SELECT * FROM personal_reset_attempts ORDER BY player_id, encounter_id, attempt"):
            result = self._read(row)
            key = (row["player_id"], result["encounter_id"])
            if result["attempt"] != counts.get(key, 0) + 1:
                raise StorageError("reset_attempt_invalid", "personal attempt history has a gap")
            counts[key] = result["attempt"]

    def begin(self, actor, lease, request):
        request = validate_reset_request(request, lease)
        with self.store._transaction():
            player = self.store._require_lease(actor, lease)
            self.store._require_boot()
            self.store._validate_schema()
            self.store._assert_no_battle_reservation(actor)
            if not player["latest_revision"]:
                raise StorageError("reset_checkpoint_required", "personal encounters require an enrolled checkpoint")
            # A committed but unacknowledged trade cannot be bypassed by a hunt.
            if "trade_recovery" in self.store._schema and self.store._connection.execute(
                    "SELECT 1 FROM trade_recovery WHERE player_id=? AND acknowledged=0", (actor,)).fetchone():
                raise StorageError("trade_busy", "resolve the committed trade before starting a personal encounter")
            previous = self.store._connection.execute(
                "SELECT * FROM personal_reset_attempts WHERE player_id=? AND request_id=?", (actor, request["request_id"])).fetchone()
            metadata = self.store._validate_metadata()
            identity = (metadata["server_epoch"], lease, request["incarnation"], request["sequence"], request["observed_count"])
            if previous is not None:
                result = self._read(previous)
                if (previous["encounter_id"] != request["encounter_id"] or tuple(previous[k] for k in
                        ("server_epoch", "lease_epoch", "incarnation", "sequence", "observed_count")) != identity):
                    raise StorageError("request_conflict", "personal attempt request changed")
                return result
            if self.store._connection.execute("SELECT 1 FROM personal_reset_attempts WHERE player_id=? AND server_epoch=? AND lease_epoch=? AND incarnation=? AND sequence=?",
                    (actor, *identity[:4])).fetchone():
                raise StorageError("request_conflict", "native personal attempt already has another request identity")
            count, length = self.store._connection.execute(
                "SELECT COALESCE(MAX(attempt),0),COUNT(*) FROM personal_reset_attempts WHERE player_id=? AND encounter_id=?",
                (actor, request["encounter_id"])).fetchone()
            if count != length:
                raise StorageError("reset_attempt_invalid", "personal attempt history has a gap")
            if count:
                self._read(self.store._connection.execute(
                    "SELECT * FROM personal_reset_attempts WHERE player_id=? AND encounter_id=? AND attempt=?",
                    (actor, request["encounter_id"], count)).fetchone())
            if request["observed_count"] > count:
                raise StorageError("reset_counter_ahead", "saved hunt count exceeds the host ledger; explicit reconciliation is required")
            if count == 0xFFFFFFFF:
                raise StorageError("reset_counter_exhausted", "personal attempt counter is exhausted")
            values = [actor, request["encounter_id"], count + 1, request["request_id"], *identity, player["latest_revision"]]
            self.store._connection.execute("INSERT INTO personal_reset_attempts VALUES (?,?,?,?,?,?,?,?,?,?,?)", (*values, _digest(values)))
            return dict(scope=SCOPE, encounter_id=request["encounter_id"], incarnation=request["incarnation"],
                        sequence=request["sequence"], attempt=count + 1)
