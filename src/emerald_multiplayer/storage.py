"""Transactional, versioned checkpoints for independent authenticated players.

The caller validates an ordinary save container before passing its opaque bytes
here. This module neither imports saves into a running ROM nor models trades.
One serving process owns a store; a newer boot fences older process instances.
"""
from __future__ import annotations

from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import sqlite3
from typing import Iterator
import uuid

from .protocol import MAX_COUNTER

SCHEMA_VERSION = 1
APPLICATION_ID = 0x454D4350
MAX_CHECKPOINT_BYTES = 131_088
_IDENTIFIER = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")


class StorageError(ValueError):
    """A fail-closed storage error with a stable, safe public code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass(frozen=True)
class WorldMetadata:
    world_id: str
    server_epoch: int
    session_epoch: int


@dataclass(frozen=True)
class Player:
    player_id: str
    display_name: str


@dataclass(frozen=True)
class PlayerIdentity(Player):
    credential: bytes = field(repr=False)


@dataclass(frozen=True)
class Checkpoint:
    player_id: str
    revision: int
    request_id: str
    payload: bytes = field(repr=False)
    sha256: str
    build_id: str
    ruleset_id: str
    save_profile: str


_SCHEMA = {
    "world_metadata": """CREATE TABLE world_metadata (
        singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
        world_id TEXT NOT NULL, build_id TEXT NOT NULL,
        ruleset_id TEXT NOT NULL, save_profile TEXT NOT NULL,
        max_payload_bytes INTEGER NOT NULL CHECK(max_payload_bytes > 0),
        server_epoch INTEGER NOT NULL CHECK(server_epoch >= 0),
        session_epoch INTEGER NOT NULL CHECK(session_epoch >= 0)
    )""",
    "players": """CREATE TABLE players (
        player_id TEXT PRIMARY KEY, display_name TEXT NOT NULL,
        credential_hash BLOB NOT NULL CHECK(length(credential_hash) = 32),
        latest_revision INTEGER NOT NULL DEFAULT 0 CHECK(latest_revision >= 0),
        lease_epoch INTEGER, lease_server_epoch INTEGER,
        CHECK((lease_epoch IS NULL AND lease_server_epoch IS NULL) OR
              (lease_epoch > 0 AND lease_server_epoch > 0))
    )""",
    "checkpoints": """CREATE TABLE checkpoints (
        player_id TEXT NOT NULL REFERENCES players(player_id),
        revision INTEGER NOT NULL CHECK(revision > 0),
        request_id TEXT NOT NULL, expected_revision INTEGER NOT NULL,
        payload BLOB NOT NULL, sha256 TEXT NOT NULL CHECK(length(sha256) = 64),
        build_id TEXT NOT NULL, ruleset_id TEXT NOT NULL,
        save_profile TEXT NOT NULL,
        PRIMARY KEY(player_id, revision), UNIQUE(player_id, request_id),
        CHECK(revision = expected_revision + 1)
    )""",
}


def _identifier(value: str, name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise StorageError("invalid_field", f"{name} must be a bounded identifier")
    return value


def _player_id(value: str) -> str:
    try:
        valid = isinstance(value, str) and str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        valid = False
    if not valid:
        raise StorageError("invalid_field", "player_id must be a canonical UUID")
    return value


def _counter(value: int, name: str, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= MAX_COUNTER:
        raise StorageError("invalid_field", f"{name} is outside its integer bounds")
    return value


def _sql_identity(sql: str) -> str:
    return " ".join(sql.split()).casefold()


class _ExclusiveFileLock:
    """Advisory lifetime lock shared by the host and closed-save controller."""

    def __init__(self, path: Path):
        self.path, self._file = path, None

    def acquire(self) -> None:
        if self._file is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                if handle.seek(0, 2) == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            handle.close()
            raise
        self._file = handle

    def release(self) -> None:
        if self._file is not None:
            handle, self._file = self._file, None
            try:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()


class CheckpointStore:
    """SQLite checkpoint owner with explicit boot and authenticated leases.

    Every mutation commits before returning. Retrying a committed request under
    a fresh authenticated lease returns its original checkpoint, including after
    restart. A stale lease never gains authority through an idempotent request.
    """

    _schema = _SCHEMA
    _schema_version = SCHEMA_VERSION
    _supports_battle_reservations = False

    def __init__(self, path: str | Path, build_id: str, ruleset_id: str,
                 save_profile: str, *, max_payload_bytes: int = MAX_CHECKPOINT_BYTES):
        self.path = Path(path).resolve()
        self.build_id = _identifier(build_id, "build_id")
        self.ruleset_id = _identifier(ruleset_id, "ruleset_id")
        self.save_profile = _identifier(save_profile, "save_profile")
        if type(max_payload_bytes) is not int or not 1 <= max_payload_bytes <= MAX_CHECKPOINT_BYTES:
            raise StorageError("invalid_field", "checkpoint byte limit is invalid")
        self.max_payload_bytes = max_payload_bytes
        self._boot_epoch: int | None = None
        self._owner_lock: _ExclusiveFileLock | None = None
        self._closed = False
        self._base_schema = self._schema
        self._base_schema_version = self._schema_version
        new = not self.path.exists() or self.path.stat().st_size == 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._connection = sqlite3.connect(self.path, isolation_level=None, timeout=5)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA synchronous = FULL")
            with self._transaction():
                if new:
                    existing = self._connection.execute("SELECT name FROM sqlite_master").fetchall()
                    if existing:
                        raise StorageError("schema_incompatible", "new store unexpectedly has a schema")
                    for sql in self._schema.values():
                        self._connection.execute(sql)
                    self._connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
                    self._connection.execute(f"PRAGMA user_version = {self._schema_version}")
                    self._connection.execute(
                        "INSERT INTO world_metadata VALUES (1, ?, ?, ?, ?, ?, 0, 0)",
                        (str(uuid.uuid4()), self.build_id, self.ruleset_id,
                         self.save_profile, self.max_payload_bytes))
                    self._initialize_extra_schema()
                # Recognize an explicitly migrated capability; opening a legacy
                # world never creates these tables or changes its version.
                if self._supports_battle_reservations:
                    from .battle_reservations import EXTENSION_VERSION, RESERVATION_SCHEMA
                    from .reset_attempts import EXTENSION_VERSION as RESET_VERSION, ATTEMPT_SCHEMA
                    version = self._connection.execute("PRAGMA user_version").fetchone()[0]
                    extension = version - self._base_schema_version
                    capabilities = [(EXTENSION_VERSION, RESERVATION_SCHEMA), (RESET_VERSION, ATTEMPT_SCHEMA)]
                    if self._base_schema_version == 3:
                        from .trade_friendship_observations import EXTENSION_VERSION as FRIENDSHIP_VERSION, OBSERVATION_SCHEMA
                        capabilities.append((FRIENDSHIP_VERSION, OBSERVATION_SCHEMA))
                        from .trade_friendship_migration import EXTENSION_VERSION as HISTORY_VERSION, HISTORY_SCHEMA
                        capabilities.append((HISTORY_VERSION, HISTORY_SCHEMA))
                        from .trade_effect_storage import EXTENSION_VERSION as EFFECT_VERSION, EFFECT_SCHEMA
                        capabilities.append((EFFECT_VERSION, EFFECT_SCHEMA))
                        from .character_transfers import EXTENSION_VERSION as TRANSFER_VERSION, TRANSFER_SCHEMA
                        capabilities.append((TRANSFER_VERSION, TRANSFER_SCHEMA))
                    for mask in range(1, 1 << len(capabilities)):
                        selected = [item for index, item in enumerate(capabilities) if mask & (1 << index)]
                        if extension == sum(item[0] for item in selected):
                            self._schema = dict(self._base_schema)
                            for _, schema in selected:
                                self._schema.update(schema)
                            self._schema_version = version
                            break
                self._validate_schema()
                self._validate_metadata()
            self._connection.execute("PRAGMA journal_mode = WAL")
            self.integrity_check()
        except BaseException as error:
            if hasattr(self, "_connection"):
                self._connection.close()
            self._closed = True
            if isinstance(error, sqlite3.DatabaseError):
                raise StorageError("storage_corrupt", "checkpoint database could not be opened safely") from error
            raise

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        if self._closed:
            raise StorageError("storage_closed", "checkpoint store is closed")
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            yield
            self._connection.execute("COMMIT")
        except BaseException as error:
            if self._connection.in_transaction:
                with suppress(sqlite3.DatabaseError):
                    self._connection.execute("ROLLBACK")
            if isinstance(error, sqlite3.DatabaseError):
                code = getattr(error, "sqlite_errorcode", 0) & 255
                corrupt = code in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB)
                raise StorageError("storage_corrupt" if corrupt else "storage_error",
                                   "checkpoint transaction failed") from error
            raise

    def _validate_schema(self) -> None:
        version = self._connection.execute("PRAGMA user_version").fetchone()[0]
        application = self._connection.execute("PRAGMA application_id").fetchone()[0]
        rows = self._connection.execute(
            "SELECT name, type, sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'").fetchall()
        if (version != self._schema_version or application != APPLICATION_ID
                or len(rows) != len(self._schema)
                or any(row["type"] != "table" or row["name"] not in self._schema
                       or _sql_identity(row["sql"]) != _sql_identity(self._schema[row["name"]])
                       for row in rows)):
            raise StorageError("schema_incompatible", "checkpoint schema is unknown; migration is required")

    def _initialize_extra_schema(self) -> None:
        """Subclass initialization, only when creating an explicit new store."""

    @property
    def battle_reservations_enabled(self) -> bool:
        return "battle_reservations" in self._schema

    @property
    def reset_attempts_enabled(self) -> bool:
        return "personal_reset_attempts" in self._schema

    @property
    def friendship_observations_enabled(self) -> bool:
        return "pokemon_friendship_observations" in self._schema

    @property
    def friendship_history_enabled(self) -> bool:
        return "pokemon_friendship_history" in self._schema

    @property
    def trade_effects_enabled(self) -> bool:
        return "trade_effect_commits" in self._schema

    @property
    def character_transfers_enabled(self) -> bool:
        return "ownership_transfers" in self._schema

    def _assert_no_battle_reservation(self, *players) -> None:
        """Called inside the owning store transaction, including direct APIs."""
        if self.battle_reservations_enabled:
            from .battle_reservations import BattleReservations
            BattleReservations(self)._assert_available(players)

    def _prepare_checkpoint(self, player: sqlite3.Row, revision: int, payload: bytes):
        """Validate subclass state under the checkpoint's write transaction."""
        return None

    def _write_checkpoint_extras(self, checkpoint: Checkpoint, prepared) -> None:
        """Write subclass state atomically with the checkpoint and head."""

    def _integrity_extra(self) -> None:
        """Audit subclass state within the same integrity read transaction."""

    def _validate_metadata(self) -> sqlite3.Row:
        rows = self._connection.execute("SELECT * FROM world_metadata").fetchall()
        if len(rows) != 1 or rows[0]["singleton"] != 1:
            raise StorageError("storage_corrupt", "world metadata is missing or invalid")
        row = rows[0]
        _player_id(row["world_id"])
        _counter(row["server_epoch"], "server_epoch")
        _counter(row["session_epoch"], "session_epoch")
        if row["server_epoch"] > row["session_epoch"]:
            raise StorageError("storage_corrupt", "world epoch ordering is invalid")
        self._bindings(row["build_id"], row["ruleset_id"], row["save_profile"])
        if row["max_payload_bytes"] != self.max_payload_bytes:
            raise StorageError("payload_limit_mismatch", "checkpoint byte limit differs from the stored profile")
        return row

    def _bindings(self, build_id: str, ruleset_id: str, save_profile: str) -> None:
        for name, value, expected in (("build", build_id, self.build_id),
                                      ("ruleset", ruleset_id, self.ruleset_id),
                                      ("save_profile", save_profile, self.save_profile)):
            _identifier(value, name)
            if value != expected:
                raise StorageError(f"{name}_mismatch", f"checkpoint {name} is incompatible")

    def _require_boot(self) -> sqlite3.Row:
        row = self._validate_metadata()
        if self._boot_epoch is None:
            raise StorageError("boot_required", "begin_server_boot must precede lease operations")
        if self._boot_epoch != row["server_epoch"]:
            raise StorageError("server_fenced", "a newer server boot owns this store")
        return row

    @property
    def metadata(self) -> WorldMetadata:
        with self._transaction():
            row = self._validate_metadata()
            return WorldMetadata(row["world_id"], row["server_epoch"], row["session_epoch"])

    def begin_server_boot(self) -> WorldMetadata:
        locked_here = self._owner_lock is None
        if locked_here:
            lock = _ExclusiveFileLock(self.path.with_name(self.path.name + ".owner.lock"))
            try:
                lock.acquire()
            except OSError as error:
                raise StorageError("host_active", "another host owns this checkpoint database") from error
            self._owner_lock = lock
        try:
            with self._transaction():
                row = self._validate_metadata()
                if row["server_epoch"] == MAX_COUNTER or row["session_epoch"] == MAX_COUNTER:
                    raise StorageError("counter_exhausted", "world epochs exhausted; explicit maintenance is required")
                boot, session = row["server_epoch"] + 1, row["session_epoch"] + 1
                self._connection.execute(
                    "UPDATE world_metadata SET server_epoch = ?, session_epoch = ? WHERE singleton = 1",
                    (boot, session))
                self._connection.execute("UPDATE players SET lease_epoch = NULL, lease_server_epoch = NULL")
                result = WorldMetadata(row["world_id"], boot, session)
        except BaseException:
            if locked_here:
                self._owner_lock.release()
                self._owner_lock = None
            raise
        self._boot_epoch = boot
        return result

    def create_player(self, display_name: str) -> PlayerIdentity:
        if (not isinstance(display_name, str) or not 1 <= len(display_name) <= 24
                or not display_name.strip() or not display_name.isprintable()):
            raise StorageError("invalid_field", "display_name must contain 1 to 24 printable characters")
        identity = PlayerIdentity(str(uuid.uuid4()), display_name, secrets.token_bytes(32))
        with self._transaction():
            if self._boot_epoch is not None:
                self._require_boot()
            self._connection.execute(
                "INSERT INTO players (player_id, display_name, credential_hash) VALUES (?, ?, ?)",
                (identity.player_id, identity.display_name, hashlib.sha256(identity.credential).digest()))
        return identity

    def _authenticate(self, player_id: str, credential: bytes) -> sqlite3.Row:
        # A malformed/unknown owner and a wrong secret share the same response.
        try:
            _player_id(player_id)
        except StorageError:
            raise StorageError("credentials_invalid", "owner credentials are invalid") from None
        if not isinstance(credential, bytes) or len(credential) != 32:
            raise StorageError("credentials_invalid", "owner credentials are invalid")
        row = self._connection.execute("SELECT * FROM players WHERE player_id = ?", (player_id,)).fetchone()
        stored = row["credential_hash"] if row is not None else bytes(32)
        matches = hmac.compare_digest(stored, hashlib.sha256(credential).digest())
        if not matches or row is None:
            raise StorageError("credentials_invalid", "owner credentials are invalid")
        return row

    def authenticate(self, player_id: str, credential: bytes) -> Player:
        with self._transaction():
            row = self._authenticate(player_id, credential)
            return Player(row["player_id"], row["display_name"])

    def acquire_lease(self, player_id: str, credential: bytes) -> int:
        with self._transaction():
            metadata = self._require_boot()
            player = self._authenticate(player_id, credential)
            if player["lease_epoch"] is not None:
                raise StorageError("lease_active", "this character already has an active lease")
            if metadata["session_epoch"] == MAX_COUNTER:
                raise StorageError("counter_exhausted", "session epochs exhausted; explicit maintenance is required")
            epoch = metadata["session_epoch"] + 1
            self._connection.execute("UPDATE world_metadata SET session_epoch = ? WHERE singleton = 1", (epoch,))
            self._connection.execute(
                "UPDATE players SET lease_epoch = ?, lease_server_epoch = ? WHERE player_id = ?",
                (epoch, self._boot_epoch, player_id))
            return epoch

    def _require_lease(self, player_id: str, lease_epoch: int) -> sqlite3.Row:
        self._require_boot()
        _player_id(player_id)
        _counter(lease_epoch, "lease_epoch", 1)
        row = self._connection.execute("SELECT * FROM players WHERE player_id = ?", (player_id,)).fetchone()
        if row is None or row["lease_epoch"] != lease_epoch or row["lease_server_epoch"] != self._boot_epoch:
            raise StorageError("stale_lease", "the character lease is no longer active")
        return row

    def release_lease(self, player_id: str, lease_epoch: int) -> bool:
        _player_id(player_id)
        _counter(lease_epoch, "lease_epoch", 1)
        with self._transaction():
            self._require_boot()
            cursor = self._connection.execute(
                "UPDATE players SET lease_epoch = NULL, lease_server_epoch = NULL "
                "WHERE player_id = ? AND lease_epoch = ? AND lease_server_epoch = ?",
                (player_id, lease_epoch, self._boot_epoch))
            return cursor.rowcount == 1

    def _checkpoint(self, row: sqlite3.Row) -> Checkpoint:
        payload = row["payload"]
        if (not isinstance(payload, bytes) or not 1 <= len(payload) <= self.max_payload_bytes
                or hashlib.sha256(payload).hexdigest() != row["sha256"]):
            raise StorageError("storage_corrupt", "stored checkpoint bytes failed integrity verification")
        self._bindings(row["build_id"], row["ruleset_id"], row["save_profile"])
        return Checkpoint(row["player_id"], row["revision"], row["request_id"],
                          payload, row["sha256"], row["build_id"], row["ruleset_id"], row["save_profile"])

    def read_checkpoint(self, player_id: str, lease_epoch: int,
                        *, revision: int | None = None) -> Checkpoint | None:
        if revision is not None:
            _counter(revision, "revision", 1)
        with self._transaction():
            player = self._require_lease(player_id, lease_epoch)
            wanted = player["latest_revision"] if revision is None else revision
            row = self._connection.execute(
                "SELECT * FROM checkpoints WHERE player_id = ? AND revision = ?", (player_id, wanted)).fetchone()
            return self._checkpoint(row) if row is not None else None

    def checkpoint_head(self, player_id: str, lease_epoch: int) -> tuple[int, str] | None:
        """(revision, sha256) of the player's latest checkpoint under the same lease check as
        read_checkpoint, but without reading or re-hashing the payload: for callers that only
        compare a head with a frozen one (a battle's per-RPC canonical-change check, M25). The
        stored hash was verified when the checkpoint was written and is verified again by every
        reader of the payload and by integrity_check."""
        _player_id(player_id)
        _counter(lease_epoch, "lease_epoch", 1)
        with self._transaction():
            player = self._require_lease(player_id, lease_epoch)
            row = self._connection.execute(
                "SELECT revision, sha256, build_id, ruleset_id, save_profile FROM checkpoints "
                "WHERE player_id = ? AND revision = ?", (player_id, player["latest_revision"])).fetchone()
            if row is None:
                return None
            self._bindings(row["build_id"], row["ruleset_id"], row["save_profile"])
            return row["revision"], row["sha256"]

    def commit_checkpoint(self, player_id: str, lease_epoch: int, request_id: str,
                          expected_revision: int, payload: bytes, build_id: str,
                          ruleset_id: str, save_profile: str) -> Checkpoint:
        _identifier(request_id, "request_id")
        _counter(expected_revision, "expected_revision")
        self._bindings(build_id, ruleset_id, save_profile)
        if not isinstance(payload, bytes) or not 1 <= len(payload) <= self.max_payload_bytes:
            raise StorageError("invalid_field", "checkpoint payload is outside its byte bounds")
        sha = hashlib.sha256(payload).hexdigest()
        with self._transaction():
            player = self._require_lease(player_id, lease_epoch)
            self._assert_no_battle_reservation(player_id)
            prior = self._connection.execute(
                "SELECT * FROM checkpoints WHERE player_id = ? AND request_id = ?", (player_id, request_id)).fetchone()
            if prior is not None:
                if (prior["expected_revision"] != expected_revision or prior["sha256"] != sha
                        or prior["payload"] != payload or prior["build_id"] != build_id
                        or prior["ruleset_id"] != ruleset_id or prior["save_profile"] != save_profile):
                    raise StorageError("request_conflict", "request_id was already committed with different content")
                result = self._checkpoint(prior)
            else:
                if player["latest_revision"] != expected_revision:
                    raise StorageError("revision_conflict", "checkpoint revision changed; read the canonical checkpoint")
                if expected_revision == MAX_COUNTER:
                    raise StorageError("counter_exhausted", "checkpoint revisions exhausted; explicit maintenance is required")
                revision = expected_revision + 1
                prepared = self._prepare_checkpoint(player, revision, payload)
                self._connection.execute(
                    "INSERT INTO checkpoints VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (player_id, revision, request_id, expected_revision, payload, sha,
                     build_id, ruleset_id, save_profile))
                self._connection.execute("UPDATE players SET latest_revision = ? WHERE player_id = ?", (revision, player_id))
                result = Checkpoint(player_id, revision, request_id, payload, sha, build_id, ruleset_id, save_profile)
                self._write_checkpoint_extras(result, prepared)
        return result

    def integrity_check(self) -> None:
        with self._transaction():
            self._validate_schema()
            self._validate_metadata()
            if [row[0] for row in self._connection.execute("PRAGMA integrity_check")] != ["ok"]:
                raise StorageError("storage_corrupt", "SQLite integrity verification failed")
            if self._connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise StorageError("storage_corrupt", "checkpoint ownership references are invalid")
            for row in self._connection.execute("SELECT * FROM players"):
                _player_id(row["player_id"])
                _counter(row["latest_revision"], "latest_revision")
                maximum, count = self._connection.execute(
                    "SELECT COALESCE(MAX(revision), 0), COUNT(*) FROM checkpoints WHERE player_id = ?",
                    (row["player_id"],)).fetchone()
                if maximum != row["latest_revision"] or count != maximum:
                    raise StorageError("storage_corrupt", "checkpoint history has a revision gap")
                if row["lease_epoch"] is not None:
                    _counter(row["lease_epoch"], "lease_epoch", 1)
                    _counter(row["lease_server_epoch"], "lease_server_epoch", 1)
            for row in self._connection.execute("SELECT * FROM checkpoints"):
                _identifier(row["request_id"], "request_id")
                self._checkpoint(row)
            self._integrity_extra()
            if self.battle_reservations_enabled:
                from .battle_reservations import BattleReservations
                BattleReservations(self)._integrity()
            if self.reset_attempts_enabled:
                from .reset_attempts import ResetAttempts
                ResetAttempts(self)._integrity()

    def backup(self, path: str | Path) -> Path:
        """Create a consistent new SQLite backup; never overwrite a destination."""
        destination = Path(path).resolve()
        if destination == self.path or destination.exists():
            raise StorageError("backup_exists", "backup destination must be a new file")
        self.integrity_check()
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Reserve the destination exclusively before SQLite opens it.
        with destination.open("xb"):
            pass
        try:
            target = sqlite3.connect(destination, isolation_level=None)
            try:
                target.execute("PRAGMA synchronous = FULL")
                self._connection.backup(target)
                if [row[0] for row in target.execute("PRAGMA integrity_check")] != ["ok"]:
                    raise StorageError("storage_corrupt", "backup integrity verification failed")
            finally:
                target.close()
        except sqlite3.DatabaseError as error:
            raise StorageError("storage_error", "consistent checkpoint backup failed") from error
        return destination

    def close(self) -> None:
        if not self._closed:
            try:
                self._connection.close()
            finally:
                self._closed = True
                if self._owner_lock is not None:
                    self._owner_lock.release()
                    self._owner_lock = None

    def __enter__(self) -> CheckpointStore:
        return self

    def __exit__(self, *args) -> None:
        self.close()
