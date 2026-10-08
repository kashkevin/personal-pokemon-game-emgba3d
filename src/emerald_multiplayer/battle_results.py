"""Immutable records of fully restored, released native battles.

Only a trusted BattleDesk publishes results. This archive cannot settle an
interrupted battle, release a native hold, clear a journal or grant rewards.
It deliberately leaves the accepted character database/schema unchanged.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3

from .protocol import MAX_COUNTER, ProtocolError, validate_identity
from .storage import StorageError
from .team_protocol import _uuid

SCOPE = "durable-native-battle-results-v1"
HISTORY_LIMIT = 8
MAX_RECORD_BYTES = 8192
_SCHEMA = {
    "metadata": "CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "results": """CREATE TABLE results (
        sequence INTEGER PRIMARY KEY,
        battle_id TEXT NOT NULL UNIQUE,
        player0 TEXT NOT NULL, player1 TEXT NOT NULL, player2 TEXT, player3 TEXT,
        record TEXT NOT NULL, sha256 TEXT NOT NULL)""",
}


def validate_result(value, actor):
    # Share the strict canonical roster/consent types, but distinguish terminal
    # archived facts from volatile active challenges in every public reply.
    from .battle_protocol import _view, SCOPE as CHALLENGE_SCOPE
    if type(value) is not dict or set(value) != {"scope", "sequence", "battle_id",
            "generation", "sender", "mode", "players", "fingerprint", "outcome", "checkpoints"}:
        raise ProtocolError("invalid_server_message", "invalid battle history fields")
    if (value["scope"] != SCOPE or type(value["sequence"]) is not int
            or not 1 <= value["sequence"] <= MAX_COUNTER
            or type(value["outcome"]) is not int or value["outcome"] not in (1, 2, 3)):
        raise ProtocolError("invalid_server_message", "invalid completed battle history")
    projected = {key: item for key, item in value.items() if key not in ("scope", "sequence")}
    projected.update(scope=CHALLENGE_SCOPE, state="closed", reason=None, consent=value["players"])
    _view(projected, actor)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _record(value):
    if type(value) is not dict or set(value) != {"summary", "receipts_sha256"}:
        raise ValueError("invalid archived record")
    summary = value["summary"]
    if type(summary) is not dict or "players" not in summary or type(summary["players"]) is not list or not summary["players"]:
        raise ValueError("missing result roster")
    # Sequence is assigned by SQLite and never accepted from a caller.
    validate_result(dict(summary, scope=SCOPE, sequence=1), summary["players"][0])
    if "scope" in summary or "sequence" in summary:
        raise ValueError("archive metadata is not caller supplied")
    digest = value["receipts_sha256"]
    if type(digest) is not str or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("invalid receipt digest")
    raw = _json(value)
    if len(raw.encode("ascii")) > MAX_RECORD_BYTES:
        raise ValueError("record exceeds bound")
    return raw


class BattleResults:
    """One transactional sidecar, pinned to the world's immutable identity.

    Connections are short lived. The owning WorldServer's existing exclusive
    world lock remains the host-admission fence. SQLite enforces unique battle
    IDs and atomic insertion even across an uncertain commit/retry.
    """

    def __init__(self, path, *, world_id, build_id, ruleset_id):
        _uuid(world_id, "world_id")
        validate_identity(build_id, "build_id")
        validate_identity(ruleset_id, "ruleset_id")
        self.path = Path(path).resolve()
        self.identity = dict(format=SCOPE, world_id=world_id, build_id=build_id, ruleset_id=ruleset_id)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # An existing schema-less file may be a truncated archive. Replacing
        # that evidence would also erase completed-ID replay protection.
        with self._transaction(initialize=not self.path.exists()):
            pass

    @contextmanager
    def _transaction(self, *, initialize=False):
        connection = None
        try:
            connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("BEGIN IMMEDIATE")
            schema = {row["name"]: row["sql"] for row in connection.execute(
                "SELECT name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_autoindex_%'")}
            if not schema and initialize:
                for sql in _SCHEMA.values():
                    connection.execute(sql)
                connection.executemany("INSERT INTO metadata VALUES (?, ?)", self.identity.items())
                schema = dict(_SCHEMA)
            if schema != _SCHEMA:
                raise StorageError("battle_archive_invalid", "battle history schema could not be verified")
            metadata = dict(connection.execute("SELECT key, value FROM metadata"))
            if metadata != self.identity:
                raise StorageError("battle_archive_mismatch", "battle history belongs to another world or release")
            yield connection
            connection.execute("COMMIT")
        except BaseException as error:
            if connection is not None and connection.in_transaction:
                connection.execute("ROLLBACK")
            if isinstance(error, (sqlite3.DatabaseError, OSError)):
                raise StorageError("battle_archive_unavailable", "battle history could not be accessed safely") from error
            raise
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _read(row):
        try:
            raw = row["record"]
            if type(raw) is not str or len(raw) > MAX_RECORD_BYTES:
                raise ValueError()
            value = json.loads(raw)
            if (_record(value) != raw or hashlib.sha256(raw.encode("ascii")).hexdigest() != row["sha256"]):
                raise ValueError()
            summary = value["summary"]
            players = summary["players"] + [None] * (4 - len(summary["players"]))
            if summary["battle_id"] != row["battle_id"] or players != [row[f"player{i}"] for i in range(4)]:
                raise ValueError()
            result = dict(summary, scope=SCOPE, sequence=row["sequence"])
            validate_result(result, players[0])
            return result
        except (ValueError, TypeError, KeyError, RecursionError, ProtocolError) as error:
            raise StorageError("battle_archive_invalid", "battle history record could not be verified") from error

    def _append_closed(self, summary, receipts_sha256):
        """Trusted Desk only, after the final successful RELEASE is validated."""
        try:
            raw = _record(dict(summary=summary, receipts_sha256=receipts_sha256))
        except (ValueError, TypeError, ProtocolError) as error:
            raise StorageError("battle_archive_invalid", "invalid completed battle record") from error
        with self._transaction() as connection:
            previous = connection.execute("SELECT * FROM results WHERE battle_id = ?", (summary["battle_id"],)).fetchone()
            if previous is not None:
                result = self._read(previous)
                if previous["record"] != raw:
                    raise StorageError("battle_result_conflict", "battle ID already records another completed result")
                return result
            players = summary["players"] + [None] * (4 - len(summary["players"]))
            connection.execute("INSERT INTO results (battle_id, player0, player1, player2, player3, record, sha256) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)", (summary["battle_id"], *players, raw, hashlib.sha256(raw.encode("ascii")).hexdigest()))
            return self._read(connection.execute("SELECT * FROM results WHERE battle_id = ?", (summary["battle_id"],)).fetchone())

    def contains(self, battle_id):
        _uuid(battle_id, "battle_id")
        with self._transaction() as connection:
            row = connection.execute("SELECT * FROM results WHERE battle_id = ?", (battle_id,)).fetchone()
            if row is not None:
                self._read(row)
            return row is not None

    def history(self, actor):
        """Caller authenticates the current actor/lease before this private read."""
        _uuid(actor, "player_id")
        with self._transaction() as connection:
            rows = connection.execute("SELECT * FROM results WHERE ? IN (player0, player1, player2, player3) "
                "ORDER BY sequence DESC LIMIT ?", (actor, HISTORY_LIMIT)).fetchall()
            results = [self._read(row) for row in rows]
            for result in results:
                validate_result(result, actor)
            return results
