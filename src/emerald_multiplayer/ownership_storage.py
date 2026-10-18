"""Explicit schema-2 checkpoints with world-scoped Pokémon ownership.

Schema 1 is never upgraded on open. Provision a new world and explicitly enroll
copied legacy saves before allocating IDs. This foundation has no owner transfer
or network enrollment operation.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4

from .flash import FlashError, LAYOUT_ID, inspect_flash
from .ownership import extract_source_inventory, inspect_ownership
from .ownership_protocol import MAX_OWNED_RECORDS, MAX_SERIAL, OWNERSHIP_PROFILE
from .protocol import MAX_COUNTER
from .storage import (
    Checkpoint, CheckpointStore, MAX_CHECKPOINT_BYTES, StorageError, _SCHEMA,
    _counter, _player_id,
)

OWNERSHIP_SCHEMA_VERSION = 2

_OWNERSHIP_SCHEMA = {
    **_SCHEMA,
    "ownership_allocator": """CREATE TABLE ownership_allocator (
        singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
        next_serial INTEGER NOT NULL CHECK(next_serial BETWEEN 1 AND 1048576)
    )""",
    "ownership_enrollments": """CREATE TABLE ownership_enrollments (
        player_id TEXT PRIMARY KEY REFERENCES players(player_id),
        source_sha256 TEXT NOT NULL UNIQUE CHECK(length(source_sha256) = 64),
        source_payload BLOB NOT NULL, source_profile TEXT NOT NULL,
        trainer_id INTEGER NOT NULL CHECK(trainer_id BETWEEN 0 AND 4294967295),
        inventory_json TEXT NOT NULL, inventory_sha256 TEXT NOT NULL CHECK(length(inventory_sha256) = 64)
    )""",
    "ownership_grants": """CREATE TABLE ownership_grants (
        start INTEGER PRIMARY KEY CHECK(start BETWEEN 1 AND 1048575),
        end_exclusive INTEGER NOT NULL CHECK(end_exclusive > start AND end_exclusive <= 1048576 AND end_exclusive - start <= 432),
        grant_id TEXT NOT NULL UNIQUE, player_id TEXT NOT NULL REFERENCES players(player_id),
        request_id TEXT NOT NULL, expected_revision INTEGER NOT NULL CHECK(expected_revision >= 0),
        lease_epoch INTEGER NOT NULL CHECK(lease_epoch > 0),
        incarnation INTEGER NOT NULL CHECK(incarnation BETWEEN 1 AND 4294967295),
        UNIQUE(player_id, request_id)
    )""",
    "ownership_instances": """CREATE TABLE ownership_instances (
        serial INTEGER PRIMARY KEY CHECK(serial BETWEEN 1 AND 1048575),
        player_id TEXT NOT NULL REFERENCES players(player_id),
        grant_id TEXT NOT NULL REFERENCES ownership_grants(grant_id),
        personality INTEGER NOT NULL CHECK(personality BETWEEN 0 AND 4294967295),
        ot_id INTEGER NOT NULL CHECK(ot_id BETWEEN 0 AND 4294967295),
        status TEXT NOT NULL CHECK(status IN ('active', 'retired')),
        birth_revision INTEGER NOT NULL CHECK(birth_revision > 0),
        last_revision INTEGER NOT NULL CHECK(last_revision >= birth_revision),
        retirement_reason INTEGER CHECK(retirement_reason IN (1, 2)),
        FOREIGN KEY(player_id, last_revision) REFERENCES checkpoints(player_id, revision),
        CHECK((status = 'active' AND retirement_reason IS NULL) OR (status = 'retired' AND retirement_reason IS NOT NULL))
    )""",
    "ownership_commits": """CREATE TABLE ownership_commits (
        player_id TEXT NOT NULL, revision INTEGER NOT NULL,
        manifest_sha256 TEXT NOT NULL CHECK(length(manifest_sha256) = 64),
        PRIMARY KEY(player_id, revision),
        FOREIGN KEY(player_id, revision) REFERENCES checkpoints(player_id, revision)
    )""",
    "ownership_memberships": """CREATE TABLE ownership_memberships (
        player_id TEXT NOT NULL, revision INTEGER NOT NULL,
        serial INTEGER NOT NULL REFERENCES ownership_instances(serial),
        location TEXT NOT NULL, personality INTEGER NOT NULL, ot_id INTEGER NOT NULL,
        species INTEGER NOT NULL, content_sha256 TEXT NOT NULL CHECK(length(content_sha256) = 64),
        PRIMARY KEY(player_id, revision, serial), UNIQUE(player_id, revision, location),
        FOREIGN KEY(player_id, revision) REFERENCES checkpoints(player_id, revision)
    )""",
    "ownership_events": """CREATE TABLE ownership_events (
        player_id TEXT NOT NULL, revision INTEGER NOT NULL,
        serial INTEGER NOT NULL REFERENCES ownership_instances(serial),
        kind TEXT NOT NULL CHECK(kind IN ('acquire', 'retain', 'retire')),
        reason INTEGER CHECK(reason IN (1, 2)),
        PRIMARY KEY(player_id, revision, serial),
        FOREIGN KEY(player_id, revision) REFERENCES checkpoints(player_id, revision),
        CHECK((kind = 'retire' AND reason IS NOT NULL) OR (kind != 'retire' AND reason IS NULL))
    )""",
}


@dataclass(frozen=True)
class Enrollment:
    player_id: str
    source_sha256: str
    inventory_sha256: str
    count: int


@dataclass(frozen=True)
class AllocationGrant:
    world_id: str
    player_id: str
    grant_id: str
    start: int
    end_exclusive: int
    lease_epoch: int
    incarnation: int
    expected_revision: int


def _uuid(value: str, name: str) -> str:
    try:
        if not isinstance(value, str) or str(UUID(value)) != value or UUID(value).int == 0:
            raise ValueError()
    except (ValueError, AttributeError, TypeError):
        raise StorageError("invalid_field", f"{name} must be a nonzero canonical UUID") from None
    return value


def _inventory(records) -> str:
    # UID assignment changes neither this checksum-independent boxed content nor
    # its initial location. The first enrollment happens before ordinary play.
    values = [[r.location, r.personality, r.ot_id, r.species, r.content_sha256] for r in records]
    return json.dumps(sorted(values), separators=(",", ":"), ensure_ascii=True)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("ascii")).hexdigest()


class OwnershipCheckpointStore(CheckpointStore):
    """New schema-2 world, durable burned ranges and checkpoint-bound ledger."""

    _schema = _OWNERSHIP_SCHEMA
    _schema_version = OWNERSHIP_SCHEMA_VERSION
    _supports_battle_reservations = True

    def __init__(self, path: str | Path, build_id: str, ruleset_id: str,
                 save_profile: str = OWNERSHIP_PROFILE, *, max_payload_bytes: int = MAX_CHECKPOINT_BYTES):
        if save_profile != OWNERSHIP_PROFILE:
            raise StorageError("save_profile_mismatch", "ownership store requires its explicit save profile")
        super().__init__(path, build_id, ruleset_id, save_profile, max_payload_bytes=max_payload_bytes)

    def _initialize_extra_schema(self) -> None:
        self._connection.execute("INSERT INTO ownership_allocator VALUES (1, 1)")

    def enroll_player(self, player_id: str, source_payload: bytes, *, replace_unconsumed: bool = False) -> Enrollment:
        """Offline host authorization of one unchanged, wholly unassigned source.

        The first owned checkpoint must preserve all boxed content and locations;
        gameplay between enrollment and that checkpoint is intentionally refused.
        A native party's volatile HP/stats tail is not part of boxed content.
        """
        _player_id(player_id)
        try:
            source = inspect_flash(source_payload, save_profile=LAYOUT_ID)
            records = extract_source_inventory(source)
        except FlashError as error:
            raise StorageError("invalid_enrollment", "enrollment source must be a valid legacy save with no assigned IDs") from error
        inventory = _inventory(records)
        source_sha = hashlib.sha256(source_payload).hexdigest()
        with self._transaction():
            if self._boot_epoch is not None:
                self._require_boot()
            player = self._connection.execute("SELECT * FROM players WHERE player_id = ?", (player_id,)).fetchone()
            if player is None:
                raise StorageError("player_not_found", "provision the player before enrolling its source")
            prior = self._connection.execute("SELECT * FROM ownership_enrollments WHERE player_id = ?", (player_id,)).fetchone()
            if prior is not None:
                if prior["source_sha256"] != source_sha or prior["source_payload"] != source_payload:
                    # A first source no checkpoint has followed yet may be replaced when the caller asks (the menu's retry
                    # with another or newer character after an attempt that never finished): nothing was built on it.
                    if not replace_unconsumed or player["latest_revision"]:
                        raise StorageError("enrollment_conflict", "this player already has a different enrollment source")
                    if self._connection.execute("SELECT 1 FROM ownership_enrollments WHERE source_sha256 = ? AND player_id != ?",
                                                (source_sha, player_id)).fetchone():
                        raise StorageError("source_already_enrolled", "that exact source character is already enrolled")
                    self._connection.execute(
                        "UPDATE ownership_enrollments SET source_sha256 = ?, source_payload = ?, source_profile = ?, trainer_id = ?, "
                        "inventory_json = ?, inventory_sha256 = ? WHERE player_id = ?",
                        (source_sha, source_payload, LAYOUT_ID, source.metadata.trainer_id, inventory, _digest(inventory), player_id))
            else:
                if player["latest_revision"]:
                    raise StorageError("enrollment_conflict", "a checkpointed player cannot enroll another source")
                if self._connection.execute("SELECT 1 FROM ownership_enrollments WHERE source_sha256 = ?", (source_sha,)).fetchone():
                    raise StorageError("source_already_enrolled", "that exact source character is already enrolled")
                self._connection.execute("INSERT INTO ownership_enrollments VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (player_id, source_sha, source_payload, LAYOUT_ID, source.metadata.trainer_id, inventory, _digest(inventory)))
        return Enrollment(player_id, source_sha, _digest(inventory), len(records))

    def has_enrollment(self, player_id: str) -> bool:
        """Whether an approved source is recorded for this account (read only)."""
        return self._connection.execute("SELECT 1 FROM ownership_enrollments WHERE player_id = ?", (player_id,)).fetchone() is not None

    def _enrollment(self, player_id: str):
        row = self._connection.execute("SELECT * FROM ownership_enrollments WHERE player_id = ?", (player_id,)).fetchone()
        if row is None:
            raise StorageError("enrollment_required", "the host must explicitly enroll this player's source save")
        return row

    def _grant(self, row) -> AllocationGrant:
        world = self._validate_metadata()["world_id"]
        return AllocationGrant(world, row["player_id"], row["grant_id"], row["start"], row["end_exclusive"],
                               row["lease_epoch"], row["incarnation"], row["expected_revision"])

    def reserve_instances(self, player_id: str, lease_epoch: int, request_id: str,
                          expected_revision: int, incarnation: int, count: int) -> AllocationGrant:
        """Durably burn a bounded range before acknowledgment; no activation yet."""
        _uuid(request_id, "request_id")
        _counter(expected_revision, "expected_revision")
        if type(incarnation) is not int or not 1 <= incarnation <= 0xFFFFFFFF:
            raise StorageError("invalid_field", "incarnation is outside uint32 bounds")
        if type(count) is not int or not 1 <= count <= MAX_OWNED_RECORDS:
            raise StorageError("invalid_field", "allocation count is outside roster bounds")
        with self._transaction():
            player = self._require_lease(player_id, lease_epoch)
            self._assert_no_battle_reservation(player_id)
            self._enrollment(player_id)
            prior = self._connection.execute("SELECT * FROM ownership_grants WHERE player_id = ? AND request_id = ?", (player_id, request_id)).fetchone()
            if prior is not None:
                if (prior["lease_epoch"], prior["expected_revision"], prior["incarnation"], prior["end_exclusive"] - prior["start"]) != (lease_epoch, expected_revision, incarnation, count):
                    raise StorageError("request_conflict", "allocation request was reused with different bindings")
                return self._grant(prior)
            if player["latest_revision"] != expected_revision:
                raise StorageError("revision_conflict", "allocation base differs from the canonical checkpoint")
            start = self._connection.execute("SELECT next_serial FROM ownership_allocator WHERE singleton = 1").fetchone()[0]
            if start + count > MAX_SERIAL + 1:
                raise StorageError("identity_exhausted", "world Pokémon identity capacity is exhausted")
            grant_id = str(uuid4())
            self._connection.execute("INSERT INTO ownership_grants VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (start, start + count, grant_id, player_id, request_id, expected_revision, lease_epoch, incarnation))
            self._connection.execute("UPDATE ownership_allocator SET next_serial = ? WHERE singleton = 1", (start + count,))
            return AllocationGrant(self._validate_metadata()["world_id"], player_id, grant_id, start, start + count,
                                   lease_epoch, incarnation, expected_revision)

    def _serial_grant(self, serial: int):
        row = self._connection.execute("SELECT * FROM ownership_grants WHERE start <= ? ORDER BY start DESC LIMIT 1", (serial,)).fetchone()
        return row if row is not None and serial < row["end_exclusive"] else None

    def _prepare_checkpoint(self, player, revision: int, payload: bytes):
        from .character_transfers import RETIRE_LEFT_WORLD, source_for
        generation = source_for(self, player["player_id"], revision)
        # The first checkpoint after a transfer starts the account's next generation (character_transfers.py).
        boundary = generation.base_revision > 0 and generation.base_revision == revision - 1
        try:
            parsed = inspect_flash(payload, expected_trainer_id=generation.trainer_id, save_profile=self.save_profile)
            owned = inspect_ownership(parsed)
        except FlashError as error:
            raise StorageError("invalid_ownership", "checkpoint has invalid ownership metadata or Pokémon") from error
        if (owned.world_id, owned.player_id) != (self._validate_metadata()["world_id"], player["player_id"]):
            raise StorageError("ownership_identity_mismatch", "checkpoint belongs to another ownership world or player")
        grant = self._connection.execute("SELECT * FROM ownership_grants WHERE grant_id = ?", (owned.grant_id,)).fetchone()
        if (grant is None or grant["player_id"] != player["player_id"]
                or (grant["start"], grant["end_exclusive"], grant["lease_epoch"], grant["incarnation"]) !=
                   (owned.start, owned.end_exclusive, owned.lease_epoch, owned.incarnation)):
            raise StorageError("allocation_mismatch", "checkpoint allocation grant is invalid or fenced")
        # Serialized lease/incarnation bind the grant's issuance provenance.
        # The current authenticated RPC lease authorizes this commit. Keeping
        # those roles separate permits exact frozen pending bytes to survive a
        # restart without rewriting their hash/base/UUID. Old RPC leases are
        # still fenced by _require_lease before reaching this hook.
        prior = {row["serial"]: row for row in self._connection.execute(
            "SELECT * FROM ownership_memberships WHERE player_id = ? AND revision = ?", (player["player_id"], revision - 1))}
        current = {record.serial: record for record in owned.records}
        retired = {entry.serial: entry.reason for entry in owned.retirements}
        if generation.base_revision == revision - 1 and _inventory(owned.records) != generation.inventory_json:
            raise StorageError("enrollment_inventory_mismatch", "first ownership checkpoint changed its enrolled Pokémon inventory")
        if boundary and retired:
            raise StorageError("invalid_retirement", "a transferred character starts with no retirements")
        additions = {}
        for serial, record in current.items():
            row = self._connection.execute("SELECT * FROM ownership_instances WHERE serial = ?", (serial,)).fetchone()
            if row is not None and boundary:
                raise StorageError("ownership_conflict", "a transferred character's Pokémon need new identities of this world")
            if row is not None:
                if row["player_id"] != player["player_id"]:
                    raise StorageError("foreign_ownership", "a Pokémon is owned by another player")
                if row["status"] != "active":
                    raise StorageError("retired_identity", "a retired Pokémon cannot reappear")
                if serial not in prior:
                    raise StorageError("ownership_conflict", "active ownership does not match the previous checkpoint")
                if (row["personality"], row["ot_id"]) != (record.personality, record.ot_id):
                    raise StorageError("immutable_identity_changed", "a Pokémon's immutable origin attributes changed")
            else:
                # Trusted ROMs may carry already-assigned but uncheckpointed IDs
                # across a rebind. A historical player grant proves issuance,
                # not birth-time consumption: canonical identity starts at this
                # first commit. ROM load/rebind revokes old mint authority; this
                # is intentionally not hostile-client or future-trade proof.
                allocated = self._serial_grant(serial)
                if allocated is None:
                    raise StorageError("unknown_identity", "a Pokémon identity was never issued")
                if allocated["player_id"] != player["player_id"]:
                    raise StorageError("foreign_allocation", "a Pokémon identity was allocated to another player")
                if allocated["grant_id"] == owned.grant_id and serial >= owned.next_serial:
                    raise StorageError("allocation_mismatch", "a Pokémon identity exceeds its consumed allocation cursor")
                additions[serial] = allocated["grant_id"]
        missing = set(prior) - set(current)
        if boundary:
            # Every Pokémon of the earlier generation leaves the world with the character's old save.
            retired = {serial: RETIRE_LEFT_WORLD for serial in missing}
            return owned, prior, additions, missing, retired
        if not missing <= set(retired):
            raise StorageError("retirement_required", "missing Pokémon require explicit release or NPC exchange entries")
        for serial, reason in retired.items():
            row = self._connection.execute("SELECT * FROM ownership_instances WHERE serial = ?", (serial,)).fetchone()
            if row is None or row["player_id"] != player["player_id"]:
                raise StorageError("invalid_retirement", "retirement does not name this player's registered Pokémon")
            if row["status"] == "retired":
                if row["retirement_reason"] != reason:
                    raise StorageError("retirement_conflict", "a retired Pokémon's reason cannot change")
            elif serial not in missing:
                raise StorageError("invalid_retirement", "retirement conflicts with retained ownership")
        return owned, prior, additions, missing, retired

    def _write_checkpoint_extras(self, checkpoint: Checkpoint, prepared) -> None:
        owned, prior, additions, missing, retired = prepared
        player_id, revision = checkpoint.player_id, checkpoint.revision
        self._connection.execute("INSERT INTO ownership_commits VALUES (?, ?, ?)", (player_id, revision, owned.manifest_sha256))
        for record in owned.records:
            if record.serial in additions:
                self._connection.execute("INSERT INTO ownership_instances VALUES (?, ?, ?, ?, ?, 'active', ?, ?, NULL)",
                    (record.serial, player_id, additions[record.serial], record.personality, record.ot_id, revision, revision))
                kind = "acquire"
            else:
                self._connection.execute("UPDATE ownership_instances SET last_revision = ? WHERE serial = ?", (revision, record.serial))
                kind = "retain"
            self._connection.execute("INSERT INTO ownership_memberships VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (player_id, revision, record.serial, record.location, record.personality, record.ot_id, record.species, record.content_sha256))
            self._connection.execute("INSERT INTO ownership_events VALUES (?, ?, ?, ?, NULL)", (player_id, revision, record.serial, kind))
        for serial in missing:
            self._connection.execute("UPDATE ownership_instances SET status = 'retired', last_revision = ?, retirement_reason = ? WHERE serial = ?",
                (revision, retired[serial], serial))
            self._connection.execute("INSERT INTO ownership_events VALUES (?, ?, ?, 'retire', ?)", (player_id, revision, serial, retired[serial]))

    def read_ownership(self, player_id: str, lease_epoch: int, *, revision: int | None = None) -> tuple[dict, ...]:
        """Private owner's immutable membership view; history is not restore authority."""
        if revision is not None:
            _counter(revision, "revision", 1)
        with self._transaction():
            player = self._require_lease(player_id, lease_epoch)
            wanted = player["latest_revision"] if revision is None else revision
            return tuple(dict(row) for row in self._connection.execute(
                "SELECT serial, location, personality, ot_id, species, content_sha256 FROM ownership_memberships WHERE player_id = ? AND revision = ? ORDER BY serial",
                (player_id, wanted)))

    def _integrity_extra(self) -> None:
        def corrupt(message):
            raise StorageError("storage_corrupt", message)
        allocator = self._connection.execute("SELECT * FROM ownership_allocator").fetchall()
        if len(allocator) != 1 or allocator[0]["singleton"] != 1:
            corrupt("ownership allocator is missing")
        next_serial = 1
        for row in self._connection.execute("SELECT * FROM ownership_grants ORDER BY start"):
            _uuid(row["grant_id"], "grant_id"); _uuid(row["request_id"], "request_id")
            if row["start"] != next_serial:
                corrupt("ownership allocation history has a gap or overlap")
            next_serial = row["end_exclusive"]
            _counter(row["expected_revision"], "expected_revision")
            _counter(row["lease_epoch"], "lease_epoch", 1)
            if self._connection.execute("SELECT 1 FROM ownership_enrollments WHERE player_id = ?", (row["player_id"],)).fetchone() is None:
                corrupt("ownership allocation lacks enrollment provenance")
        if allocator[0]["next_serial"] != next_serial:
            corrupt("ownership allocator differs from its burned history")
        for row in self._connection.execute("SELECT * FROM ownership_enrollments"):
            try:
                source = inspect_flash(row["source_payload"], save_profile=LAYOUT_ID)
                inventory = _inventory(extract_source_inventory(source))
            except FlashError as error:
                raise StorageError("storage_corrupt", "ownership enrollment source is invalid") from error
            if (hashlib.sha256(row["source_payload"]).hexdigest(), source.metadata.trainer_id, inventory, _digest(inventory), row["source_profile"]) != (
                    row["source_sha256"], row["trainer_id"], row["inventory_json"], row["inventory_sha256"], LAYOUT_ID):
                corrupt("ownership enrollment provenance changed")
        checkpoints = self._connection.execute("SELECT * FROM checkpoints ORDER BY player_id, revision").fetchall()
        if self._connection.execute("SELECT COUNT(*) FROM ownership_commits").fetchone()[0] != len(checkpoints):
            corrupt("checkpoint ownership manifest is missing")
        history = {}
        previous = {}
        for cp in checkpoints:
            enrollment = self._connection.execute("SELECT * FROM ownership_enrollments WHERE player_id = ?", (cp["player_id"],)).fetchone()
            if enrollment is None:
                corrupt("historical ownership checkpoint lacks enrollment")
            try:
                owned = inspect_ownership(inspect_flash(cp["payload"], expected_trainer_id=enrollment["trainer_id"], save_profile=self.save_profile))
            except FlashError as error:
                raise StorageError("storage_corrupt", "historical ownership checkpoint is invalid") from error
            metadata = self._connection.execute("SELECT manifest_sha256 FROM ownership_commits WHERE player_id = ? AND revision = ?", (cp["player_id"], cp["revision"])).fetchone()
            if metadata is None or metadata[0] != owned.manifest_sha256 or (owned.world_id, owned.player_id) != (self._validate_metadata()["world_id"], cp["player_id"]):
                corrupt("historical ownership manifest differs from its payload")
            actual = list(self._connection.execute("SELECT serial, location, personality, ot_id, species, content_sha256 FROM ownership_memberships WHERE player_id = ? AND revision = ? ORDER BY serial", (cp["player_id"], cp["revision"])))
            expected = [(r.serial, r.location, r.personality, r.ot_id, r.species, r.content_sha256) for r in sorted(owned.records, key=lambda r: r.serial)]
            if [tuple(row) for row in actual] != expected:
                corrupt("historical Pokémon membership differs from its checkpoint")
            grant = self._connection.execute("SELECT * FROM ownership_grants WHERE grant_id = ?", (owned.grant_id,)).fetchone()
            if grant is None or (grant["player_id"], grant["start"], grant["end_exclusive"], grant["lease_epoch"], grant["incarnation"]) != (
                    cp["player_id"], owned.start, owned.end_exclusive, owned.lease_epoch, owned.incarnation):
                corrupt("historical ownership grant differs from its checkpoint")
            if cp["revision"] == 1 and _inventory(owned.records) != enrollment["inventory_json"]:
                corrupt("first ownership checkpoint differs from enrollment")
            old = previous.get(cp["player_id"], set())
            current = {record.serial for record in owned.records}
            retired = {entry.serial: entry.reason for entry in owned.retirements}
            missing = old - current
            if not missing <= set(retired):
                corrupt("historical missing Pokémon lacks a retirement entry")
            expected_events = []
            for record in owned.records:
                if record.serial not in history:
                    allocated = self._serial_grant(record.serial)
                    if allocated is None or allocated["player_id"] != cp["player_id"]:
                        corrupt("historical Pokémon identity lacks its owner's allocation")
                    if allocated["grant_id"] == owned.grant_id and record.serial >= owned.next_serial:
                        corrupt("historical Pokémon identity exceeded the allocation cursor")
                    history[record.serial] = [cp["player_id"], allocated["grant_id"], record.personality, record.ot_id,
                                              "active", cp["revision"], cp["revision"], None]
                    kind = "acquire"
                else:
                    state = history[record.serial]
                    if state[0] != cp["player_id"] or state[4] != "active" or record.serial not in old or (state[2], state[3]) != (record.personality, record.ot_id):
                        corrupt("historical ownership reintroduced or changed an identity")
                    state[6] = cp["revision"]
                    kind = "retain"
                expected_events.append((record.serial, kind, None))
            for serial, reason in retired.items():
                state = history.get(serial)
                if state is None or state[0] != cp["player_id"]:
                    corrupt("historical retirement names an unowned identity")
                if state[4] == "retired":
                    if state[7] != reason:
                        corrupt("historical retirement reason changed")
                elif serial not in missing:
                    corrupt("historical retirement conflicts with active ownership")
            for serial in missing:
                state = history[serial]
                state[4], state[6], state[7] = "retired", cp["revision"], retired[serial]
                expected_events.append((serial, "retire", retired[serial]))
            events = [tuple(row) for row in self._connection.execute(
                "SELECT serial, kind, reason FROM ownership_events WHERE player_id = ? AND revision = ? ORDER BY serial",
                (cp["player_id"], cp["revision"]))]
            if events != sorted(expected_events):
                corrupt("historical ownership events differ from the checkpoint transition")
            previous[cp["player_id"]] = current
        for player in self._connection.execute("SELECT * FROM players"):
            latest = {row[0] for row in self._connection.execute("SELECT serial FROM ownership_memberships WHERE player_id = ? AND revision = ?", (player["player_id"], player["latest_revision"]))}
            active = {row[0] for row in self._connection.execute("SELECT serial FROM ownership_instances WHERE player_id = ? AND status = 'active'", (player["player_id"],))}
            if latest != active:
                corrupt("active Pokémon ownership differs from the latest checkpoint")
        instances = {row["serial"]: [row[key] for key in ("player_id", "grant_id", "personality", "ot_id", "status", "birth_revision", "last_revision", "retirement_reason")]
                     for row in self._connection.execute("SELECT * FROM ownership_instances")}
        if instances != history:
            corrupt("current Pokémon ownership or tombstones differ from immutable history")
