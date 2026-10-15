"""Durable admission barriers, not a native battle resume implementation.

The explicit 102/103 migration adds this capability to schema 2/3 in the same
SQLite database. A character backup therefore includes its unresolved holds.
Only the trusted BattleDesk can publish reservation/terminal facts. No public
request can acknowledge, cancel, resume, expire or delete a reservation.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from itertools import zip_longest
import json
from pathlib import Path

from .battle_protocol import SCOPE as CHALLENGE_SCOPE, _view
from .native_battle import NativeBinding, NativeControl, Opcode
from .protocol import ProtocolError
from .storage import StorageError, _ExclusiveFileLock, _counter, _player_id

EXTENSION_VERSION = 100
SCOPE = "durable-native-battle-reservations-v1"
MAX_RECORD_BYTES = 8192
RESERVATION_SCHEMA = {
    "battle_reservations": """CREATE TABLE battle_reservations (
        battle_id TEXT PRIMARY KEY, record TEXT NOT NULL,
        authorized_mask INTEGER NOT NULL CHECK(authorized_mask BETWEEN 1 AND 15),
        terminal_kind TEXT CHECK(terminal_kind IN ('aborted', 'closed')),
        terminal_digest TEXT, sha256 TEXT NOT NULL,
        CHECK((terminal_kind IS NULL AND terminal_digest IS NULL) OR
              (terminal_kind IS NOT NULL AND length(terminal_digest) = 64)))""",
    "battle_reservation_actors": """CREATE TABLE battle_reservation_actors (
        player_id TEXT PRIMARY KEY REFERENCES players(player_id),
        battle_id TEXT NOT NULL REFERENCES battle_reservations(battle_id),
        source_slot INTEGER NOT NULL CHECK(source_slot BETWEEN 0 AND 3),
        UNIQUE(battle_id, source_slot))""",
}


@dataclass(frozen=True)
class BattleReservationTerminal:
    """Trusted read projection of an already verified durable terminal fact.

    This is not a public receipt, a client cancellation claim or release
    authority. Reading it never changes a reservation or character barrier.
    """
    world_id: str
    build_id: str
    ruleset_id: str
    battle_id: str
    generation: str
    sender: str
    mode: int
    players: tuple[str, ...]
    fingerprint: str
    kind: str
    digest: str


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value):
    return hashlib.sha256(_json(value).encode("ascii")).hexdigest()


def _hash(value):
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("invalid digest")


def enable_battle_reservations(store, backup_path):
    """Explicit offline migration; require a new, verified pre-migration backup.

    Existing leases must first be closed normally. Never silently migrate an
    opened legacy world, remove a backup, or reconstruct missing schema tables.
    """
    if not store._supports_battle_reservations or store._base_schema_version not in (2, 3):
        raise StorageError("battle_migration_unsupported", "battle reservations require an ownership world")
    if store.battle_reservations_enabled:
        store.integrity_check()
        return False
    lock = None
    if store._owner_lock is None:
        lock = _ExclusiveFileLock(store.path.with_name(store.path.name + ".owner.lock"))
        try:
            lock.acquire()
        except OSError as error:
            raise StorageError("host_active", "close the existing host before migration") from error
    old_schema, old_version = store._schema, store._schema_version
    try:
        store.integrity_check()
        if store._connection.execute("SELECT 1 FROM players WHERE lease_epoch IS NOT NULL").fetchone():
            raise StorageError("lease_active", "close authenticated characters before migration")
        backup = store.backup(Path(backup_path))
        with type(store)(backup, store.build_id, store.ruleset_id, store.save_profile,
                         max_payload_bytes=store.max_payload_bytes) as verified:
            if (verified.metadata != store.metadata or any(a != b for a, b in zip_longest(
                    verified._connection.iterdump(), store._connection.iterdump()))):
                raise StorageError("battle_migration_backup", "the migration backup differs from its source")
        try:
            with store._transaction():
                store._validate_schema()
                if store._connection.execute("SELECT 1 FROM players WHERE lease_epoch IS NOT NULL").fetchone():
                    raise StorageError("lease_active", "a character became active during migration")
                for sql in RESERVATION_SCHEMA.values():
                    store._connection.execute(sql)
                store._schema = {**old_schema, **RESERVATION_SCHEMA}
                store._schema_version = old_version + EXTENSION_VERSION
                store._connection.execute(f"PRAGMA user_version = {store._schema_version}")
                store._validate_schema()
                BattleReservations(store)._integrity()
        finally:
            # A failed transaction must not leave a legacy instance pretending
            # it has the capability. An uncertain successful COMMIT keeps it.
            version = store._connection.execute("PRAGMA user_version").fetchone()[0]
            if version == old_version:
                store._schema, store._schema_version = old_schema, version
        store.integrity_check()
        return True
    finally:
        if lock is not None:
            lock.release()


def validate_waiting(value, actor):
    if (type(value) is not dict or set(value) != {"scope", "battle_id", "generation", "mode",
            "players", "state", "resume_supported"} or value["scope"] != SCOPE
            or value["state"] != "waiting" or value["resume_supported"] is not False
            or type(value["mode"]) is not int or value["mode"] not in (2, 3, 4, 5)):
        raise ProtocolError("invalid_server_message", "invalid durable battle waiting status")
    try:
        _player_id(value["battle_id"]); _player_id(value["generation"])
        players = value["players"]
        if type(players) is not list or len(players) != (4 if value["mode"] in (3, 5) else 2):
            raise ValueError()
        for player in players:
            _player_id(player)
        if len(set(players)) != len(players) or actor not in players:
            raise ValueError()
    except (StorageError, ValueError, TypeError) as error:
        raise ProtocolError("invalid_server_message", "foreign or malformed battle waiting status") from error


class BattleReservations:
    def __init__(self, store):
        if not store.battle_reservations_enabled:
            raise StorageError("battle_migration_required", "explicit backed-up battle reservation migration is required")
        self.store = store

    def _read(self, row):
        try:
            raw = row["record"]
            if type(raw) is not str or len(raw) > MAX_RECORD_BYTES:
                raise ValueError()
            record = json.loads(raw)
            if (type(record) is not dict or set(record) - {"brings"} != {"scope", "world_id", "build_id", "ruleset_id",
                    "save_profile", "server_epoch", "view", "leases", "incarnations", "rng"}
                    or record["scope"] != SCOPE or raw != _json(record)):
                raise ValueError()
            if "brings" in record and (type(record["brings"]) is not list or len(record["brings"]) != 2
                                       or any(type(m) is not int or not 0 <= m <= 0x3F for m in record["brings"])
                                       or not any(record["brings"]) or record["view"].get("mode") != 4):
                raise ValueError()
            metadata = self.store._validate_metadata()
            for key in ("world_id", "build_id", "ruleset_id", "save_profile"):
                if record[key] != metadata[key]:
                    raise ValueError()
            _counter(record["server_epoch"], "server epoch", 1)
            if record["server_epoch"] > metadata["server_epoch"]:
                raise ValueError()
            view = record["view"]
            _view(view, view["sender"])
            if (view["state"] != "accepted" or view["reason"] is not None or view["outcome"] is not None
                    or set(view["consent"]) != set(view["players"]) or view["battle_id"] != row["battle_id"]):
                raise ValueError()
            NativeBinding(view["generation"], tuple(view["players"]), tuple(record["leases"]),
                          tuple(record["incarnations"]), 0, mode=view["mode"])
            if (type(record["rng"]) is not str or len(record["rng"]) != 32
                    or bytes.fromhex(record["rng"]).hex() != record["rng"] or bytes.fromhex(record["rng"]) == bytes(16)):
                raise ValueError()
            mask = row["authorized_mask"]
            if type(mask) is not int or not 1 <= mask < 1 << len(view["players"]):
                raise ValueError()
            terminal = row["terminal_kind"]
            if terminal is None:
                if row["terminal_digest"] is not None:
                    raise ValueError()
            elif terminal not in ("aborted", "closed"):
                raise ValueError()
            else:
                _hash(row["terminal_digest"])
            if row["sha256"] != _digest([record, mask, terminal, row["terminal_digest"]]):
                raise ValueError()
            for cp in view["checkpoints"]:
                saved = self.store._connection.execute("SELECT sha256 FROM checkpoints WHERE player_id=? AND revision=?",
                    (cp["player_id"], cp["revision"])).fetchone()
                if saved is None or saved["sha256"] != cp["sha256"]:
                    raise ValueError()
            return record
        except (ValueError, TypeError, KeyError, RecursionError, ProtocolError) as error:
            raise StorageError("battle_reservation_invalid", "battle reservation could not be verified") from error

    def _active(self):
        self.store._validate_schema()
        rows = self.store._connection.execute("SELECT * FROM battle_reservations WHERE terminal_kind IS NULL").fetchall()
        records = [self._read(row) for row in rows]
        expected = sorted((p, r["view"]["battle_id"], i) for r in records for i, p in enumerate(r["view"]["players"]))
        actual = sorted(tuple(row) for row in self.store._connection.execute(
            "SELECT player_id, battle_id, source_slot FROM battle_reservation_actors"))
        if actual != expected or len({p for p, _, _ in expected}) != len(expected):
            raise StorageError("battle_reservation_invalid", "battle participant barriers disagree with durable records")
        return records

    def _integrity(self):
        self._active()
        for row in self.store._connection.execute("SELECT * FROM battle_reservations WHERE terminal_kind IS NOT NULL"):
            self._read(row)

    def _assert_available(self, players):
        if any(set(players).intersection(r["view"]["players"]) for r in self._active()):
            raise StorageError("battle_busy", "an unresolved native battle reserves this character's mutations")

    def assert_available(self, *players):
        with self.store._transaction():
            self._assert_available(players)

    def contains(self, battle_id):
        with self.store._transaction():
            self.store._validate_schema()
            row = self.store._connection.execute("SELECT * FROM battle_reservations WHERE battle_id=?", (battle_id,)).fetchone()
            if row is not None:
                self._read(row)
            return row is not None

    def terminal(self, battle_id):
        """Read a terminal record without relying on bounded Desk history.

        None means no durable terminal evidence, including an active row. It
        never proves that an invitation, provisional Enter or BIND did not run.
        Only the existing trusted _finish path may create the fact returned here.
        """
        _player_id(battle_id)
        with self.store._transaction():
            # This also rejects stray terminal actor barriers instead of
            # allowing this read to conceal a conflicting held lifecycle.
            self._active()
            row = self.store._connection.execute(
                "SELECT * FROM battle_reservations WHERE battle_id=?", (battle_id,)).fetchone()
            if row is None:
                return None
            record = self._read(row)
            if row["terminal_kind"] is None:
                return None
            view = record["view"]
            return BattleReservationTerminal(
                record["world_id"], record["build_id"], record["ruleset_id"],
                view["battle_id"], view["generation"], view["sender"], view["mode"],
                tuple(view["players"]), view["fingerprint"], row["terminal_kind"], row["terminal_digest"])

    def waiting(self, actor, lease):
        with self.store._transaction():
            self.store._require_lease(actor, lease)
            result = []
            for record in self._active():
                view = record["view"]
                if actor in view["players"]:
                    result.append(dict(scope=SCOPE, battle_id=view["battle_id"], generation=view["generation"],
                        mode=view["mode"], players=list(view["players"]), state="waiting", resume_supported=False))
            return result

    def _reserve(self, battle, actor):
        """Trusted Desk, before dispatch; all actors remain held until terminal."""
        view = dict(scope=CHALLENGE_SCOPE, battle_id=battle.battle_id, generation=battle.generation,
            sender=battle.sender, mode=battle.mode, state="accepted", reason=None, outcome=None,
            players=list(battle.players), fingerprint=battle.fingerprint, consent=sorted(battle.players),
            checkpoints=[dict(player_id=r.player_id, source_slot=r.source_slot, revision=r.revision,
                sha256=r.checkpoint_sha256, party_count=r.party_count) for r in battle.roster])
        if battle.mode == 4:
            view["gym"] = battle.gym  # retained for exact co-op Gym recovery
        with self.store._transaction():
            metadata = self.store._require_boot()
            record = dict(scope=SCOPE, world_id=metadata["world_id"], build_id=self.store.build_id,
                ruleset_id=self.store.ruleset_id, save_profile=self.store.save_profile,
                server_epoch=metadata["server_epoch"], view=view, leases=list(battle.leases),
                incarnations=[battle.incarnations[p] for p in battle.players], rng=battle.rng.hex())
            if any(r.bring for r in battle.roster):
                record["brings"] = [r.bring for r in battle.roster]   # co-op team selection, retained for exact recovery
            for p, lease, cp in zip(battle.players, battle.leases, view["checkpoints"]):
                player = self.store._require_lease(p, lease)
                if player["latest_revision"] != cp["revision"]:
                    raise StorageError("revision_conflict", "battle canonical head changed before reservation")
            self._active()
            old = self.store._connection.execute("SELECT * FROM battle_reservations WHERE battle_id=?", (battle.battle_id,)).fetchone()
            mask = 1 << battle.players.index(actor)
            if old is not None:
                if self._read(old) != record or old["terminal_kind"] is not None:
                    raise StorageError("battle_reservation_conflict", "battle ID already has another durable lifecycle")
                mask |= old["authorized_mask"]
                self.store._connection.execute("UPDATE battle_reservations SET authorized_mask=?, sha256=? WHERE battle_id=?",
                    (mask, _digest([record, mask, None, None]), battle.battle_id))
            else:
                self._assert_available(battle.players)
                self.store._connection.execute("INSERT INTO battle_reservations VALUES (?, ?, ?, NULL, NULL, ?)",
                    (battle.battle_id, _json(record), mask, _digest([record, mask, None, None])))
                self.store._connection.executemany("INSERT INTO battle_reservation_actors VALUES (?, ?, ?)",
                    [(p, battle.battle_id, i) for i, p in enumerate(battle.players)])
            self._active()

    def _finish(self, battle, kind, actor, request, response):
        """Trusted Desk after full native receipt validation, before unblocking."""
        receipts = dict(battle.receipts)
        receipts[(actor, request.opcode)] = (request.pack(), response.pack())
        if kind == "closed":
            if (battle.state != "release_authorized" or set(battle.finished) != set(battle.players)
                    or battle.released | {actor} != set(battle.players)):
                raise StorageError("battle_reservation_state", "all restored native releases are required")
            required = [(p, op) for p in battle.players for op in
                (Opcode.BIND, Opcode.PREPARE, Opcode.START, Opcode.QUERY, Opcode.RELEASE)]
        elif kind == "aborted":
            if battle.state != "aborting" or battle.abort_pending != {actor} or battle.started:
                raise StorageError("battle_reservation_state", "all authorized pre-start aborts are required")
            required = [(p, Opcode.ABORT_PRE_START) for p in sorted(battle.bind_intent)]
        else:
            raise StorageError("battle_reservation_state", "unsupported terminal lifecycle")
        material = bytearray((SCOPE + ":" + kind).encode("ascii"))
        lineage = battle.lease_lineage or (battle.leases,)
        if battle.lease_lineage:
            if (not battle.resumable or battle.leases not in lineage or battle.renewal_digest is None
                    or any(len(epoch) != len(battle.players) for epoch in lineage)):
                raise StorageError("battle_reservation_state", "renewed terminal evidence lacks its verified lineage")
            _hash(battle.renewal_digest)
            # The terminal fact hashes the actual historical native receipts.
            # A later original-core reconnect can add a valid lease proof
            # without changing a result already durably published here.
        for p, opcode in required:
            raw_request, raw_response = receipts[(p, opcode)]
            control, reply = NativeControl.unpack(raw_request), NativeControl.unpack(raw_response)
            slot = battle.players.index(p)
            if (control.battle_id != battle.battle_id or control.source_slot != slot or control.opcode != opcode
                    or control.incarnation != battle.incarnations[p]
                    or control.session_epoch not in {epoch[slot] for epoch in lineage}):
                raise StorageError("battle_reservation_state", "terminal evidence changed its participant binding")
            reply.validate_response(control)
            if reply.status:
                raise StorageError("battle_reservation_state", "terminal receipt was not successful")
            material.extend(raw_request); material.extend(raw_response)
        digest = hashlib.sha256(material).hexdigest()
        with self.store._transaction():
            self.store._require_boot()
            self._active()
            row = self.store._connection.execute("SELECT * FROM battle_reservations WHERE battle_id=?", (battle.battle_id,)).fetchone()
            if row is None:
                raise StorageError("battle_reservation_invalid", "the durable battle reservation is missing")
            record = self._read(row)
            if battle.lease_lineage and tuple(record["leases"]) != lineage[0]:
                raise StorageError("battle_reservation_conflict", "renewal lineage changed the original reserved leases")
            if (record["view"]["generation"] != battle.generation or record["view"]["fingerprint"] != battle.fingerprint
                    or row["authorized_mask"] != sum(1 << battle.players.index(p) for p in battle.bind_intent)):
                raise StorageError("battle_reservation_conflict", "terminal evidence changed the reserved lifecycle")
            if row["terminal_kind"] is not None:
                if (row["terminal_kind"], row["terminal_digest"]) != (kind, digest):
                    raise StorageError("battle_reservation_conflict", "terminal retry changed its evidence")
                return
            self.store._connection.execute("UPDATE battle_reservations SET terminal_kind=?, terminal_digest=?, sha256=? WHERE battle_id=?",
                (kind, digest, _digest([record, row["authorized_mask"], kind, digest]), battle.battle_id))
            self.store._connection.execute("DELETE FROM battle_reservation_actors WHERE battle_id=?", (battle.battle_id,))
