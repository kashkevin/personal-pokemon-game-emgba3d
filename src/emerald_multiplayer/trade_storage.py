"""Explicit schema-3 paired trades; schema-2 worlds are never upgraded on open.

This is the persistence primitive, not an offer/confirmation UI or native trade
simulation. A coordinator must obtain both players' consent to the immutable
offer before calling commit_trade. The first transform is an exact party swap.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json

from .flash import FlashError, LAYOUT_ID, inspect_flash
from .ownership import extract_source_inventory, inspect_ownership
from .ownership_protocol import MAX_SERIAL, OWNERSHIP_PROFILE
from .ownership_storage import OwnershipCheckpointStore, _OWNERSHIP_SCHEMA, _digest, _inventory, _uuid
from .protocol import MAX_COUNTER
from .storage import Checkpoint, StorageError, _counter, _player_id

TRADE_SCHEMA_VERSION = 3
_TRADE_SCHEMA = {
    **_OWNERSHIP_SCHEMA,
    "ownership_instances": """CREATE TABLE ownership_instances (
        serial INTEGER PRIMARY KEY CHECK(serial BETWEEN 1 AND 1048575),
        player_id TEXT NOT NULL REFERENCES players(player_id),
        birth_player_id TEXT NOT NULL REFERENCES players(player_id),
        grant_id TEXT NOT NULL REFERENCES ownership_grants(grant_id),
        personality INTEGER NOT NULL CHECK(personality BETWEEN 0 AND 4294967295),
        ot_id INTEGER NOT NULL CHECK(ot_id BETWEEN 0 AND 4294967295),
        status TEXT NOT NULL CHECK(status IN ('active', 'retired')),
        birth_revision INTEGER NOT NULL CHECK(birth_revision > 0),
        last_revision INTEGER NOT NULL CHECK(last_revision > 0),
        retirement_reason INTEGER CHECK(retirement_reason IN (1, 2)),
        FOREIGN KEY(birth_player_id, birth_revision) REFERENCES checkpoints(player_id, revision),
        FOREIGN KEY(player_id, last_revision) REFERENCES checkpoints(player_id, revision),
        CHECK((status = 'active' AND retirement_reason IS NULL) OR (status = 'retired' AND retirement_reason IS NOT NULL))
    )""",
    "commit_groups": """CREATE TABLE commit_groups (
        sequence INTEGER PRIMARY KEY CHECK(sequence BETWEEN 1 AND 2147483647),
        kind TEXT NOT NULL CHECK(kind IN ('checkpoint', 'trade'))
    )""",
    "checkpoint_order": """CREATE TABLE checkpoint_order (
        player_id TEXT NOT NULL, revision INTEGER NOT NULL,
        sequence INTEGER NOT NULL REFERENCES commit_groups(sequence),
        PRIMARY KEY(player_id, revision),
        FOREIGN KEY(player_id, revision) REFERENCES checkpoints(player_id, revision)
    )""",
    "trade_transactions": """CREATE TABLE trade_transactions (
        transaction_id TEXT PRIMARY KEY,
        sequence INTEGER NOT NULL UNIQUE REFERENCES commit_groups(sequence),
        fingerprint TEXT NOT NULL CHECK(length(fingerprint) = 64),
        a_player TEXT NOT NULL, a_revision INTEGER NOT NULL, a_serial INTEGER NOT NULL,
        b_player TEXT NOT NULL, b_revision INTEGER NOT NULL, b_serial INTEGER NOT NULL,
        CHECK(a_player < b_player AND a_serial != b_serial),
        FOREIGN KEY(a_player, a_revision) REFERENCES checkpoints(player_id, revision),
        FOREIGN KEY(b_player, b_revision) REFERENCES checkpoints(player_id, revision)
    )""",
    "ownership_events": """CREATE TABLE ownership_events (
        player_id TEXT NOT NULL, revision INTEGER NOT NULL,
        serial INTEGER NOT NULL REFERENCES ownership_instances(serial),
        kind TEXT NOT NULL CHECK(kind IN ('acquire', 'retain', 'retire', 'transfer_in', 'transfer_out')),
        reason INTEGER CHECK(reason IN (1, 2)),
        transaction_id TEXT REFERENCES trade_transactions(transaction_id),
        PRIMARY KEY(player_id, revision, serial),
        FOREIGN KEY(player_id, revision) REFERENCES checkpoints(player_id, revision),
        CHECK((kind = 'retire' AND reason IS NOT NULL) OR (kind != 'retire' AND reason IS NULL)),
        CHECK(kind NOT IN ('transfer_in', 'transfer_out') OR transaction_id IS NOT NULL)
    )""",
    "trade_recovery": """CREATE TABLE trade_recovery (
        player_id TEXT NOT NULL, transaction_id TEXT NOT NULL REFERENCES trade_transactions(transaction_id),
        revision INTEGER NOT NULL, sha256 TEXT NOT NULL CHECK(length(sha256) = 64),
        acknowledged INTEGER NOT NULL DEFAULT 0 CHECK(acknowledged IN (0, 1)),
        PRIMARY KEY(player_id, transaction_id),
        FOREIGN KEY(player_id, revision) REFERENCES checkpoints(player_id, revision)
    )""",
}


@dataclass(frozen=True)
class TradeSide:
    player_id: str
    lease_epoch: int
    expected_revision: int
    serial: int
    payload: bytes = field(repr=False)


@dataclass(frozen=True)
class TradeResult:
    sequence: int
    transaction_id: str
    checkpoint_a: Checkpoint
    checkpoint_b: Checkpoint
    outcome_fingerprint: str


@dataclass(frozen=True)
class TradeRecovery:
    sequence: int
    transaction_id: str
    checkpoint: Checkpoint
    outcome_fingerprint: str


def _side(side: TradeSide) -> None:
    if type(side) is not TradeSide:
        raise StorageError("invalid_field", "trade sides must be typed TradeSide records")
    _player_id(side.player_id)
    _counter(side.lease_epoch, "lease_epoch", 1)
    _counter(side.expected_revision, "expected_revision", 1)
    if type(side.serial) is not int or not 1 <= side.serial <= MAX_SERIAL:
        raise StorageError("invalid_field", "offered serial is outside identity bounds")
    if not isinstance(side.payload, bytes) or len(side.payload) not in (131072, 131088):
        raise StorageError("invalid_field", "trade post-image must be a complete Flash container")


def _fingerprint(sides: tuple[TradeSide, TradeSide], build: str, rules: str, profile: str) -> str:
    # Current authentication leases may change on recovery; the committed
    # content, parties, original bases, and offered IDs may never change.
    value = [build, rules, profile, [[s.player_id, s.expected_revision, s.serial,
             len(s.payload), hashlib.sha256(s.payload).hexdigest()] for s in sides]]
    return _digest(json.dumps(value, separators=(",", ":"), ensure_ascii=True))


def _validate_swap(before_a: bytes, serial_a: int, before_b: bytes, serial_b: int,
                   after_a: bytes, after_b: bytes) -> None:
    from .trade_flash import TradeFlashError, validate_party_swap
    try:
        validate_party_swap(before_a, serial_a, before_b, serial_b, after_a, after_b)
    except (TradeFlashError, FlashError) as error:
        raise StorageError("invalid_trade", "trade post-images are not the authorized exact party exchange") from error


class TradeCheckpointStore(OwnershipCheckpointStore):
    """Opt-in new world with atomic paired revisions and immutable transfer history."""

    _schema, _schema_version = _TRADE_SCHEMA, TRADE_SCHEMA_VERSION

    def _ensure_applied(self, player_id: str) -> None:
        if self._connection.execute("SELECT 1 FROM trade_recovery WHERE player_id = ? AND acknowledged = 0", (player_id,)).fetchone():
            raise StorageError("trade_recovery_required", "apply the committed trade before another persistent mutation")

    def _prepare_checkpoint(self, player, revision: int, payload: bytes):
        self._ensure_applied(player["player_id"])
        return super()._prepare_checkpoint(player, revision, payload)

    def reserve_instances(self, player_id, lease_epoch, request_id, expected_revision, incarnation, count):
        # Store calls are synchronous and confined to SQLite's owning thread;
        # there is no scheduling point between this guard and the base method.
        with self._transaction():
            self._require_lease(player_id, lease_epoch)
            self._ensure_applied(player_id)
        return super().reserve_instances(player_id, lease_epoch, request_id, expected_revision, incarnation, count)

    def _group(self, kind: str) -> int:
        sequence = self._connection.execute("SELECT COALESCE(MAX(sequence), 0) FROM commit_groups").fetchone()[0] + 1
        if sequence > MAX_COUNTER:
            raise StorageError("counter_exhausted", "commit ordering exhausted; explicit maintenance is required")
        self._connection.execute("INSERT INTO commit_groups VALUES (?, ?)", (sequence, kind))
        return sequence

    def _membership(self, checkpoint, owned, events):
        self._connection.execute("INSERT INTO ownership_commits VALUES (?, ?, ?)",
                                 (checkpoint.player_id, checkpoint.revision, owned.manifest_sha256))
        for r in owned.records:
            self._connection.execute("INSERT INTO ownership_memberships VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (checkpoint.player_id, checkpoint.revision, r.serial, r.location, r.personality,
                 r.ot_id, r.species, r.content_sha256))
        for serial, kind, reason, transaction in events:
            self._connection.execute("INSERT INTO ownership_events VALUES (?, ?, ?, ?, ?, ?)",
                (checkpoint.player_id, checkpoint.revision, serial, kind, reason, transaction))

    def _write_checkpoint_extras(self, checkpoint: Checkpoint, prepared) -> None:
        owned, prior, additions, missing, retired = prepared
        player, revision = checkpoint.player_id, checkpoint.revision
        events = []
        for record in owned.records:
            if record.serial in additions:
                self._connection.execute("INSERT INTO ownership_instances VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, NULL)",
                    (record.serial, player, player, additions[record.serial], record.personality, record.ot_id, revision, revision))
                kind = "acquire"
            else:
                self._connection.execute("UPDATE ownership_instances SET last_revision = ? WHERE serial = ?", (revision, record.serial))
                kind = "retain"
            events.append((record.serial, kind, None, None))
        for serial in missing:
            self._connection.execute("UPDATE ownership_instances SET status = 'retired', last_revision = ?, retirement_reason = ? WHERE serial = ?",
                                     (revision, retired[serial], serial))
            events.append((serial, "retire", retired[serial], None))
        self._membership(checkpoint, owned, events)
        self._connection.execute("INSERT INTO checkpoint_order VALUES (?, ?, ?)", (player, revision, self._group("checkpoint")))

    def _owned(self, player_id: str, payload: bytes):
        enrollment = self._enrollment(player_id)
        try:
            owned = inspect_ownership(inspect_flash(payload, expected_trainer_id=enrollment["trainer_id"], save_profile=self.save_profile))
        except FlashError as error:
            raise StorageError("invalid_ownership", "trade checkpoint contains invalid ownership state") from error
        if (owned.world_id, owned.player_id) != (self._validate_metadata()["world_id"], player_id):
            raise StorageError("ownership_identity_mismatch", "trade checkpoint belongs to another world or player")
        grant = self._connection.execute("SELECT * FROM ownership_grants WHERE grant_id = ?", (owned.grant_id,)).fetchone()
        if grant is None or (grant["player_id"], grant["start"], grant["end_exclusive"], grant["lease_epoch"], grant["incarnation"]) != (
                player_id, owned.start, owned.end_exclusive, owned.lease_epoch, owned.incarnation):
            raise StorageError("allocation_mismatch", "trade checkpoint grant provenance changed")
        return owned

    def _result(self, row) -> TradeResult:
        checkpoints = []
        for prefix in ("a", "b"):
            cp = self._connection.execute("SELECT * FROM checkpoints WHERE player_id = ? AND revision = ?",
                         (row[prefix + "_player"], row[prefix + "_revision"])).fetchone()
            if cp is None:
                raise StorageError("storage_corrupt", "committed trade checkpoint is missing")
            checkpoints.append(self._checkpoint(cp))
        return TradeResult(row["sequence"], row["transaction_id"], *checkpoints, row["fingerprint"])

    def _check_preimage_ledger(self, checkpoint: Checkpoint) -> None:
        owned = self._owned(checkpoint.player_id, checkpoint.payload)
        actual = [tuple(r) for r in self._connection.execute(
            "SELECT serial, location, personality, ot_id, species, content_sha256 FROM ownership_memberships WHERE player_id = ? AND revision = ? ORDER BY serial",
            (checkpoint.player_id, checkpoint.revision))]
        expected = [(r.serial, r.location, r.personality, r.ot_id, r.species, r.content_sha256)
                    for r in sorted(owned.records, key=lambda r: r.serial)]
        if actual != expected:
            raise StorageError("storage_corrupt", "trade pre-image differs from canonical membership")
        for r in owned.records:
            row = self._connection.execute("SELECT * FROM ownership_instances WHERE serial = ?", (r.serial,)).fetchone()
            if row is None or (row["player_id"], row["status"], row["personality"], row["ot_id"]) != (
                    checkpoint.player_id, "active", r.personality, r.ot_id):
                raise StorageError("storage_corrupt", "trade pre-image differs from current ownership")

    def commit_trade(self, transaction_id: str, side_a: TradeSide, side_b: TradeSide,
                     build_id: str, ruleset_id: str, save_profile: str = OWNERSHIP_PROFILE) -> TradeResult:
        """Commit a mutually confirmed exact exchange, or replay its original result.

        Sides/results are ordered by player UUID. Fresh authenticated leases may
        retry; stale leases never do. This primitive does not infer consent from
        a socket send and must be called by the offer/confirmation coordinator.
        """
        _uuid(transaction_id, "transaction_id")
        _side(side_a); _side(side_b)
        if side_a.player_id == side_b.player_id or side_a.serial == side_b.serial:
            raise StorageError("invalid_trade", "a trade requires two distinct players and instances")
        sides = tuple(sorted((side_a, side_b), key=lambda side: side.player_id))
        self._bindings(build_id, ruleset_id, save_profile)
        if any(len(s.payload) > self.max_payload_bytes for s in sides):
            raise StorageError("invalid_field", "trade post-image exceeds this world's checkpoint limit")
        fingerprint = _fingerprint(sides, build_id, ruleset_id, save_profile)
        with self._transaction():
            players = [self._require_lease(s.player_id, s.lease_epoch) for s in sides]
            prior = self._connection.execute("SELECT * FROM trade_transactions WHERE transaction_id = ?", (transaction_id,)).fetchone()
            if prior is not None:
                result = self._result(prior)
                if prior["fingerprint"] != fingerprint or any(cp.payload != s.payload for cp, s in zip((result.checkpoint_a, result.checkpoint_b), sides)):
                    raise StorageError("request_conflict", "trade transaction was already committed with different content")
                return result
            before = []
            for s, player in zip(sides, players):
                self._ensure_applied(s.player_id)
                if player["latest_revision"] != s.expected_revision:
                    raise StorageError("revision_conflict", "trade base differs from the current canonical checkpoint")
                if s.expected_revision == MAX_COUNTER:
                    raise StorageError("counter_exhausted", "trade revision capacity exhausted")
                if self._connection.execute("SELECT 1 FROM checkpoints WHERE player_id = ? AND request_id = ?", (s.player_id, transaction_id)).fetchone():
                    raise StorageError("request_conflict", "trade ID is already used by an ordinary checkpoint")
                cp = self._connection.execute("SELECT * FROM checkpoints WHERE player_id = ? AND revision = ?", (s.player_id, s.expected_revision)).fetchone()
                if cp is None:
                    raise StorageError("checkpoint_missing", "a trade requires both canonical pre-images")
                before.append(self._checkpoint(cp))
                self._check_preimage_ledger(before[-1])
                instance = self._connection.execute("SELECT * FROM ownership_instances WHERE serial = ?", (s.serial,)).fetchone()
                if instance is None or instance["player_id"] != s.player_id or instance["status"] != "active":
                    raise StorageError("foreign_ownership", "the offered instance is not owned by this player")
            _validate_swap(before[0].payload, sides[0].serial, before[1].payload, sides[1].serial, sides[0].payload, sides[1].payload)
            owned = [self._owned(s.player_id, s.payload) for s in sides]
            sequence = self._group("trade")
            checkpoints = []
            for s in sides:
                revision, sha = s.expected_revision + 1, hashlib.sha256(s.payload).hexdigest()
                self._connection.execute("INSERT INTO checkpoints VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (s.player_id, revision, transaction_id, s.expected_revision, s.payload, sha, build_id, ruleset_id, save_profile))
                self._connection.execute("UPDATE players SET latest_revision = ? WHERE player_id = ?", (revision, s.player_id))
                self._connection.execute("INSERT INTO checkpoint_order VALUES (?, ?, ?)", (s.player_id, revision, sequence))
                checkpoints.append(Checkpoint(s.player_id, revision, transaction_id, s.payload, sha, build_id, ruleset_id, save_profile))
            self._connection.execute("INSERT INTO trade_transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (transaction_id, sequence, fingerprint, sides[0].player_id, checkpoints[0].revision, sides[0].serial,
                 sides[1].player_id, checkpoints[1].revision, sides[1].serial))
            for i, (cp, parsed) in enumerate(zip(checkpoints, owned)):
                incoming, outgoing = sides[1-i].serial, sides[i].serial
                events = [(outgoing, "transfer_out", None, transaction_id)]
                for record in parsed.records:
                    self._connection.execute("UPDATE ownership_instances SET player_id = ?, last_revision = ? WHERE serial = ?",
                                              (cp.player_id, cp.revision, record.serial))
                    events.append((record.serial, "transfer_in" if record.serial == incoming else "retain", None, transaction_id))
                self._membership(cp, parsed, events)
                self._connection.execute("INSERT INTO trade_recovery VALUES (?, ?, ?, ?, 0)",
                                          (cp.player_id, transaction_id, cp.revision, cp.sha256))
            return TradeResult(sequence, transaction_id, *checkpoints, fingerprint)

    def read_trade(self, player_id: str, lease_epoch: int, transaction_id: str) -> TradeResult | None:
        _uuid(transaction_id, "transaction_id")
        with self._transaction():
            self._require_lease(player_id, lease_epoch)
            row = self._connection.execute("SELECT * FROM trade_transactions WHERE transaction_id = ?", (transaction_id,)).fetchone()
            if row is not None and player_id not in (row["a_player"], row["b_player"]):
                raise StorageError("trade_not_participant", "this player is not a participant in that trade")
            return self._result(row) if row is not None else None

    def pending_trade_recovery(self, player_id: str, lease_epoch: int) -> tuple[TradeRecovery, ...]:
        with self._transaction():
            self._require_lease(player_id, lease_epoch)
            rows = self._connection.execute("SELECT t.*, r.revision FROM trade_recovery r JOIN trade_transactions t USING(transaction_id) WHERE r.player_id = ? AND r.acknowledged = 0 ORDER BY t.sequence", (player_id,)).fetchall()
            values = []
            for row in rows:
                result = self._result(row)
                cp = result.checkpoint_a if result.checkpoint_a.player_id == player_id else result.checkpoint_b
                values.append(TradeRecovery(result.sequence, result.transaction_id, cp, result.outcome_fingerprint))
            return tuple(values)

    def acknowledge_trade(self, player_id: str, lease_epoch: int, transaction_id: str, revision: int, sha256: str) -> None:
        _uuid(transaction_id, "transaction_id"); _counter(revision, "revision", 1)
        if not isinstance(sha256, str) or len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
            raise StorageError("invalid_field", "trade acknowledgment SHA256 is invalid")
        with self._transaction():
            self._require_lease(player_id, lease_epoch)
            row = self._connection.execute("SELECT * FROM trade_recovery WHERE player_id = ? AND transaction_id = ?", (player_id, transaction_id)).fetchone()
            if row is None:
                raise StorageError("trade_not_participant", "this player has no result for that trade")
            if (row["revision"], row["sha256"]) != (revision, sha256):
                raise StorageError("trade_ack_mismatch", "trade acknowledgment does not identify the committed result")
            self._connection.execute("UPDATE trade_recovery SET acknowledged = 1 WHERE player_id = ? AND transaction_id = ?", (player_id, transaction_id))

    def _integrity_extra(self) -> None:
        """Replay immutable globally ordered groups, including atomic two-owner moves."""
        def corrupt(message):
            raise StorageError("storage_corrupt", message)
        try:
            self._audit_history(corrupt)
        except StorageError as error:
            if error.code == "storage_corrupt":
                raise
            raise StorageError("storage_corrupt", "trade/ownership history failed validation") from error
        except (FlashError, ValueError, KeyError, TypeError) as error:
            raise StorageError("storage_corrupt", "trade/ownership history is invalid") from error

    def _audit_history(self, corrupt):
        allocator = self._connection.execute("SELECT * FROM ownership_allocator").fetchall()
        if len(allocator) != 1 or allocator[0]["singleton"] != 1:
            corrupt("ownership allocator is missing")
        cursor = 1
        for grant in self._connection.execute("SELECT * FROM ownership_grants ORDER BY start"):
            _uuid(grant["grant_id"], "grant_id"); _uuid(grant["request_id"], "request_id")
            _counter(grant["expected_revision"], "expected_revision"); _counter(grant["lease_epoch"], "lease_epoch", 1)
            if grant["start"] != cursor or not 1 <= grant["incarnation"] <= 0xFFFFFFFF:
                corrupt("ownership ranges overlap or have an invalid incarnation")
            self._enrollment(grant["player_id"])
            cursor = grant["end_exclusive"]
        if allocator[0]["next_serial"] != cursor:
            corrupt("ownership allocator differs from its burned history")
        for row in self._connection.execute("SELECT * FROM ownership_enrollments"):
            parsed = inspect_flash(row["source_payload"], save_profile=LAYOUT_ID)
            inventory = _inventory(extract_source_inventory(parsed))
            if (hashlib.sha256(row["source_payload"]).hexdigest(), parsed.metadata.trainer_id, inventory, _digest(inventory), row["source_profile"]) != (
                    row["source_sha256"], row["trainer_id"], row["inventory_json"], row["inventory_sha256"], LAYOUT_ID):
                corrupt("enrollment provenance changed")
        checkpoints = {(r["player_id"], r["revision"]): r for r in self._connection.execute("SELECT * FROM checkpoints")}
        if self._connection.execute("SELECT COUNT(*) FROM ownership_commits").fetchone()[0] != len(checkpoints):
            corrupt("ownership manifest is missing")
        if self._connection.execute("SELECT COUNT(*) FROM checkpoint_order").fetchone()[0] != len(checkpoints):
            corrupt("checkpoint global order is incomplete")
        state, previous, seen = {}, {}, set()
        trade_ids = set()
        groups = self._connection.execute("SELECT * FROM commit_groups ORDER BY sequence").fetchall()
        for expected_sequence, group in enumerate(groups, 1):
            if group["sequence"] != expected_sequence:
                corrupt("global commit history has a gap")
            refs = self._connection.execute("SELECT * FROM checkpoint_order WHERE sequence = ? ORDER BY player_id", (expected_sequence,)).fetchall()
            paired = group["kind"] == "trade"
            if len(refs) != (2 if paired else 1):
                corrupt("commit group has the wrong participant count")
            cps, owned = [], []
            for ref in refs:
                key = (ref["player_id"], ref["revision"])
                if key in seen or key not in checkpoints:
                    corrupt("checkpoint group reference is duplicated or missing")
                seen.add(key)
                cp = checkpoints[key]
                if cp["expected_revision"] != previous.get(cp["player_id"], (0, set()))[0]:
                    corrupt("global checkpoint ordering is inconsistent")
                parsed = self._owned(cp["player_id"], cp["payload"])
                manifest = self._connection.execute("SELECT manifest_sha256 FROM ownership_commits WHERE player_id = ? AND revision = ?", key).fetchone()
                records = [tuple(r) for r in self._connection.execute("SELECT serial, location, personality, ot_id, species, content_sha256 FROM ownership_memberships WHERE player_id = ? AND revision = ? ORDER BY serial", key)]
                expected = [(r.serial, r.location, r.personality, r.ot_id, r.species, r.content_sha256) for r in sorted(parsed.records, key=lambda r: r.serial)]
                if manifest is None or manifest[0] != parsed.manifest_sha256 or records != expected:
                    corrupt("ownership membership or manifest differs from its immutable payload")
                if cp["revision"] == 1 and _inventory(parsed.records) != self._enrollment(cp["player_id"])["inventory_json"]:
                    corrupt("first checkpoint differs from enrollment")
                cps.append(cp); owned.append(parsed)
            trade = self._connection.execute("SELECT * FROM trade_transactions WHERE sequence = ?", (expected_sequence,)).fetchone()
            if paired:
                if trade is None:
                    corrupt("paired checkpoint lacks a trade result")
                _uuid(trade["transaction_id"], "transaction_id")
                trade_ids.add(trade["transaction_id"])
                if [(c["player_id"], c["revision"], c["request_id"]) for c in cps] != [
                        (trade[p + "_player"], trade[p + "_revision"], trade["transaction_id"]) for p in ("a", "b")]:
                    corrupt("trade participants differ from the paired checkpoints")
                sides = tuple(TradeSide(c["player_id"], 1, c["expected_revision"], trade[p + "_serial"], c["payload"]) for c, p in zip(cps, ("a", "b")))
                for s in sides:
                    _side(s)
                    origin = state.get(s.serial)
                    if origin is None or origin[0] != s.player_id or origin[5] != "active":
                        corrupt("trade offered an unowned or retired identity")
                pre = [checkpoints[(c["player_id"], c["expected_revision"])]["payload"] for c in cps]
                _validate_swap(pre[0], sides[0].serial, pre[1], sides[1].serial, sides[0].payload, sides[1].payload)
                if _fingerprint(sides, self.build_id, self.ruleset_id, self.save_profile) != trade["fingerprint"]:
                    corrupt("trade outcome fingerprint changed")
            elif trade is not None:
                corrupt("ordinary checkpoint has a paired trade record")
            for i, (cp, parsed) in enumerate(zip(cps, owned)):
                player, revision = cp["player_id"], cp["revision"]
                old = previous.get(player, (0, set()))[1]
                current = {r.serial for r in parsed.records}
                retired = {r.serial: r.reason for r in parsed.retirements}
                events = []
                for record in parsed.records:
                    serial = record.serial
                    if paired and serial == sides[1-i].serial:
                        origin = state[serial]
                        if (origin[3], origin[4]) != (record.personality, record.ot_id):
                            corrupt("trade changed immutable origin attributes")
                        origin[0], origin[7] = player, revision
                        kind = "transfer_in"
                    elif serial not in state:
                        grant = self._serial_grant(serial)
                        if paired or grant is None or grant["player_id"] != player or (grant["grant_id"] == parsed.grant_id and serial >= parsed.next_serial):
                            corrupt("identity lacks an authorized allocation")
                        state[serial] = [player, player, grant["grant_id"], record.personality, record.ot_id, "active", revision, revision, None]
                        kind = "acquire"
                    else:
                        origin = state[serial]
                        if origin[0] != player or origin[5] != "active" or serial not in old or (origin[3], origin[4]) != (record.personality, record.ot_id):
                            corrupt("ordinary checkpoint reintroduced or changed an identity")
                        origin[7] = revision
                        kind = "retain"
                    events.append((serial, kind, None, trade["transaction_id"] if paired else None))
                missing = old - current
                if paired:
                    if missing != {sides[i].serial}:
                        corrupt("trade removed an unrelated identity")
                    events.append((sides[i].serial, "transfer_out", None, trade["transaction_id"]))
                else:
                    if not missing <= retired.keys():
                        corrupt("missing identity lacks explicit retirement")
                    for serial, reason in retired.items():
                        origin = state.get(serial)
                        if origin is None or origin[0] != player or (origin[5] == "retired" and origin[8] != reason) or (origin[5] == "active" and serial not in missing):
                            corrupt("retirement history is inconsistent")
                    for serial in missing:
                        origin = state[serial]
                        origin[5], origin[7], origin[8] = "retired", revision, retired[serial]
                        events.append((serial, "retire", retired[serial], None))
                actual = [tuple(r) for r in self._connection.execute("SELECT serial, kind, reason, transaction_id FROM ownership_events WHERE player_id = ? AND revision = ? ORDER BY serial", (player, revision))]
                if actual != sorted(events):
                    corrupt("ownership events differ from their checkpoint transition")
                previous[player] = (revision, current)
        if seen != checkpoints.keys() or self._connection.execute("SELECT COUNT(*) FROM trade_transactions").fetchone()[0] != len(trade_ids):
            corrupt("checkpoint or trade is missing from global history")
        actual_state = {r["serial"]: [r[k] for k in ("player_id", "birth_player_id", "grant_id", "personality", "ot_id", "status", "birth_revision", "last_revision", "retirement_reason")]
                        for r in self._connection.execute("SELECT * FROM ownership_instances")}
        if actual_state != state:
            corrupt("current owners, origin attributes or tombstones differ from immutable history")
        for player in self._connection.execute("SELECT * FROM players"):
            latest = previous.get(player["player_id"], (0, set()))
            active = {serial for serial, value in state.items() if value[0] == player["player_id"] and value[5] == "active"}
            if latest != (player["latest_revision"], active):
                corrupt("latest membership differs from active ownership")
        receipts = self._connection.execute("SELECT * FROM trade_recovery").fetchall()
        if len(receipts) != 2 * len(trade_ids):
            corrupt("trade recovery history is incomplete")
        for receipt in receipts:
            trade = self._connection.execute("SELECT * FROM trade_transactions WHERE transaction_id = ?", (receipt["transaction_id"],)).fetchone()
            cp = checkpoints.get((receipt["player_id"], receipt["revision"]))
            if trade is None or cp is None or receipt["player_id"] not in (trade["a_player"], trade["b_player"]) or cp["request_id"] != receipt["transaction_id"] or cp["sha256"] != receipt["sha256"]:
                corrupt("trade recovery receipt differs from committed result")
            if not receipt["acknowledged"] and self._connection.execute("SELECT latest_revision FROM players WHERE player_id = ?", (receipt["player_id"],)).fetchone()[0] != receipt["revision"]:
                corrupt("unapplied trade was overwritten by later progress")
