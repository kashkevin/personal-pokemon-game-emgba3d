from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest
from unittest.mock import patch
import uuid

from emerald_multiplayer.flash import LAYOUT_ID, inspect_flash
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE
from emerald_multiplayer.ownership_protocol import MAX_SERIAL
from emerald_multiplayer.ownership_storage import OwnershipCheckpointStore
from emerald_multiplayer.storage import CheckpointStore, StorageError
from test_ownership import make_ownership_flash, make_ownership_record
from test_flash import _rewrite

BUILD, RULESET = "ownership-test-ROM-sha256", "baseline-test-rules-v1"


def source_flash(locations=("party:0",), *, personalities=None):
    return make_ownership_flash(records=tuple((location, 0) for location in locations),
                                personalities=personalities, metadata=bytes(4))


def owned_flash(grant, records=None, *, personalities=None, retirements=(), next_serial=None,
                counter=2, with_rtc=False, **metadata_changes):
    values = dict(world_id=grant.world_id, player_id=grant.player_id, grant_id=grant.grant_id,
                  start=grant.start, end_exclusive=grant.end_exclusive,
                  next_serial=next_serial if next_serial is not None else grant.end_exclusive,
                  lease_epoch=grant.lease_epoch, incarnation=grant.incarnation, retirements=retirements)
    metadata = make_ownership_record(**{**values, **metadata_changes})
    return make_ownership_flash(records=records if records is not None else (("party:0", grant.start),),
                                metadata=metadata, personalities=personalities, counter=counter, with_rtc=with_rtc)


class OwnershipStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "owned.sqlite3"
        self.store = OwnershipCheckpointStore(self.path, BUILD, RULESET)
        self.boot = self.store.begin_server_boot()
        self.owner = self.store.create_player("Player A")
        self.lease = self.store.acquire_lease(self.owner.player_id, self.owner.credential)
        self.store.enroll_player(self.owner.player_id, source_flash())

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def reserve(self, count=32, revision=0, incarnation=1, request=None):
        return self.store.reserve_instances(self.owner.player_id, self.lease, request or str(uuid.uuid4()), revision, incarnation, count)

    def commit(self, payload, revision=0, request=None):
        return self.store.commit_checkpoint(self.owner.player_id, self.lease, request or str(uuid.uuid4()), revision,
                                            payload, BUILD, RULESET, OWNERSHIP_PROFILE)

    def assert_code(self, code, function, *args, **kwargs):
        with self.assertRaises(StorageError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def test_explicit_enrollment_and_source_reuse_are_guarded(self):
        enrollment = self.store.enroll_player(self.owner.player_id, source_flash())
        self.assertEqual(enrollment.count, 1)
        other = self.store.create_player("Player B")
        self.assert_code("source_already_enrolled", self.store.enroll_player, other.player_id, source_flash())
        self.assert_code("enrollment_conflict", self.store.enroll_player, self.owner.player_id, source_flash(personalities=(8,)))
        lease = self.store.acquire_lease(other.player_id, other.credential)
        self.assert_code("enrollment_required", self.store.reserve_instances, other.player_id, lease, str(uuid.uuid4()), 0, 1, 1)
        self.assert_code("invalid_enrollment", self.store.enroll_player, other.player_id, make_ownership_flash())

    def test_ranges_burn_before_ack_and_exact_retries_do_not_allocate_twice(self):
        request = str(uuid.uuid4())
        grant = self.reserve(request=request)
        self.assertEqual((grant.start, grant.end_exclusive), (1, 33))
        self.assertEqual(self.reserve(request=request), grant)
        self.assert_code("request_conflict", self.reserve, 33, request=request)
        later = self.reserve(2, incarnation=2)
        self.assertEqual(later.start, 33)
        self.assertEqual(self.store.read_ownership(self.owner.player_id, self.lease), ())
        self.assert_code("revision_conflict", self.reserve, revision=1)
        self.store.integrity_check()

    def test_first_commit_assigns_ids_without_changing_enrolled_content(self):
        grant = self.reserve()
        payload = owned_flash(grant, with_rtc=True)
        checkpoint = self.commit(payload)
        self.assertEqual(checkpoint.payload, payload)
        self.assertEqual(checkpoint.revision, 1)
        membership = self.store.read_ownership(self.owner.player_id, self.lease)
        self.assertEqual([(r["serial"], r["location"]) for r in membership], [(1, "party:0")])
        self.store.integrity_check()

    def test_first_enrollment_requires_exact_source_content_and_location(self):
        grant = self.reserve()
        for records, pids in ((("box:0:0", 1),), None), ((("party:0", 1),), (8,)):
            self.assert_code("enrollment_inventory_mismatch", self.commit, owned_flash(grant, records, personalities=pids))
        self.assertIsNone(self.store.read_checkpoint(self.owner.player_id, self.lease))
        self.assertEqual(self.store.read_ownership(self.owner.player_id, self.lease), ())

    def test_moves_across_pc_daycare_fusion_and_same_pid_distinct_identity(self):
        # A second enrollment fixture deliberately contains two identical PID/OT
        # creatures; no fingerprint deduplication is permitted.
        self.store.close()
        self.path = Path(self.temp.name) / "twins.sqlite3"
        self.store = OwnershipCheckpointStore(self.path, BUILD, RULESET)
        self.store.begin_server_boot()
        self.owner = self.store.create_player("Twins")
        self.lease = self.store.acquire_lease(self.owner.player_id, self.owner.credential)
        self.store.enroll_player(self.owner.player_id, source_flash(("party:0", "box:0:0"), personalities=(7, 7)))
        grant = self.reserve()
        self.commit(owned_flash(grant, (("party:0", 1), ("box:0:0", 2)), personalities=(7, 7)))
        moved = owned_flash(grant, (("daycare:0", 2), ("fusion:0", 1)), personalities=(7, 7))
        self.commit(moved, 1)
        self.assertEqual({r["serial"]: r["location"] for r in self.store.read_ownership(self.owner.player_id, self.lease)},
                         {1: "fusion:0", 2: "daycare:0"})
        self.store.integrity_check()

    def test_duplicate_unknown_foreign_and_changed_origin_reject_atomically(self):
        grant = self.reserve()
        self.commit(owned_flash(grant))
        cases = [
            ("invalid_ownership", owned_flash(grant, (("party:0", 1), ("party:1", 1)))),
            ("unknown_identity", owned_flash(grant, (("party:0", 1), ("party:1", 99)))),
            ("immutable_identity_changed", owned_flash(grant, personalities=(8,))),
            ("ownership_identity_mismatch", owned_flash(grant, world_id=str(uuid.uuid4()))),
            ("allocation_mismatch", owned_flash(grant, lease_epoch=self.lease + 1)),
        ]
        other = self.store.create_player("Other")
        self.store.enroll_player(other.player_id, source_flash(personalities=(9,)))
        other_lease = self.store.acquire_lease(other.player_id, other.credential)
        foreign = self.store.reserve_instances(other.player_id, other_lease, str(uuid.uuid4()), 0, 1, 1)
        cases.append(("foreign_allocation", owned_flash(grant, (("party:0", 1), ("party:1", foreign.start)))))
        for code, payload in cases:
            self.assert_code(code, self.commit, payload, 1)
            self.assertEqual(self.store.read_checkpoint(self.owner.player_id, self.lease).revision, 1)
        self.store.integrity_check()

    def test_explicit_retirement_repeat_and_resurrection(self):
        grant = self.reserve()
        self.commit(owned_flash(grant))
        self.assert_code("retirement_required", self.commit, owned_flash(grant, ()), 1)
        retired = owned_flash(grant, (), retirements=((1, 1),))
        self.commit(retired, 1)
        self.commit(retired, 2)  # persistent ROM journal repeat is harmless
        self.assertEqual(self.store.read_ownership(self.owner.player_id, self.lease), ())
        self.assert_code("retired_identity", self.commit, owned_flash(grant), 3)
        self.assert_code("retirement_conflict", self.commit, owned_flash(grant, (), retirements=((1, 2),)), 3)
        self.assert_code("invalid_retirement", self.commit, owned_flash(grant, (), retirements=((99, 1),)), 3)
        self.store.integrity_check()

    def test_carried_first_seen_ids_from_older_burned_player_range_are_accepted(self):
        old = self.reserve()
        self.commit(owned_flash(old))
        fresh = self.reserve(32, revision=1, incarnation=2)
        self.commit(owned_flash(fresh, (("party:0", 1), ("party:1", 2))), 1)
        self.assertEqual([r["serial"] for r in self.store.read_ownership(self.owner.player_id, self.lease)], [1, 2])
        self.store.integrity_check()

    def test_historic_lost_ack_retry_does_not_rewind_retired_ledger(self):
        grant, request = self.reserve(), str(uuid.uuid4())
        payload = owned_flash(grant)
        original = self.commit(payload, request=request)
        self.commit(owned_flash(grant, (), retirements=((1, 2),)), 1)
        self.store.close()
        self.store = OwnershipCheckpointStore(self.path, BUILD, RULESET)
        self.store.begin_server_boot()
        self.lease = self.store.acquire_lease(self.owner.player_id, self.owner.credential)
        self.assertEqual(self.commit(payload, request=request), original)
        self.assertEqual(self.store.read_checkpoint(self.owner.player_id, self.lease).revision, 2)
        self.assertEqual(self.store.read_ownership(self.owner.player_id, self.lease), ())
        self.assert_code("request_conflict", self.commit, owned_flash(grant, (), retirements=((1, 1),)), request=request)
        self.store.integrity_check()

    def test_failure_after_checkpoint_insert_rolls_back_every_ledger_table(self):
        grant = self.reserve()
        original = self.store._write_checkpoint_extras
        def fail(checkpoint, prepared):
            original(checkpoint, prepared)
            raise RuntimeError("injected interruption before durable COMMIT")
        with patch.object(self.store, "_write_checkpoint_extras", side_effect=fail), self.assertRaises(RuntimeError):
            self.commit(owned_flash(grant))
        self.assertIsNone(self.store.read_checkpoint(self.owner.player_id, self.lease))
        for table in ("checkpoints", "ownership_commits", "ownership_instances", "ownership_memberships", "ownership_events"):
            self.assertEqual(self.store._connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0], 0)
        self.assertEqual(self.store._connection.execute("SELECT next_serial FROM ownership_allocator").fetchone()[0], 33)
        self.commit(owned_flash(grant))
        self.store.integrity_check()

    def test_restart_fences_grant_and_old_lease_without_reusing_range(self):
        grant, old_lease = self.reserve(), self.lease
        self.store.close()
        self.store = OwnershipCheckpointStore(self.path, BUILD, RULESET)
        self.store.begin_server_boot()
        self.lease = self.store.acquire_lease(self.owner.player_id, self.owner.credential)
        self.assert_code("stale_lease", self.store.reserve_instances, self.owner.player_id, old_lease, str(uuid.uuid4()), 0, 1, 1)
        self.assert_code("stale_lease", self.store.commit_checkpoint, self.owner.player_id, old_lease,
                         str(uuid.uuid4()), 0, owned_flash(grant), BUILD, RULESET, OWNERSHIP_PROFILE)
        fresh = self.reserve(1)
        self.assertEqual(fresh.start, 33)
        self.store.integrity_check()

    def test_uncommitted_frozen_old_grant_survives_authenticated_restart(self):
        grant, request = self.reserve(), str(uuid.uuid4())
        payload = owned_flash(grant)
        old_lease = self.lease
        self.store.close()
        self.store = OwnershipCheckpointStore(self.path, BUILD, RULESET)
        self.store.begin_server_boot()
        self.lease = self.store.acquire_lease(self.owner.player_id, self.owner.credential)
        self.assert_code("stale_lease", self.store.commit_checkpoint, self.owner.player_id, old_lease,
                         request, 0, payload, BUILD, RULESET, OWNERSHIP_PROFILE)
        # Immutable old grant fields remain provenance; exact bytes/base/UUID
        # are committed under the fresh authenticated lease, never rewritten.
        self.assert_code("allocation_mismatch", self.commit, owned_flash(grant, incarnation=2), request=request)
        result = self.commit(payload, request=request)
        self.assertEqual(result.payload, payload)
        self.assertEqual(self.commit(payload, request=request), result)
        self.assert_code("revision_conflict", self.commit, payload, 0)
        self.assert_code("revision_conflict", self.commit, payload, 2)
        self.store.integrity_check()

    def test_exhaustion_is_atomic(self):
        # Near-limit synthetic allocator history is tested without allocating a
        # million rows. SQL permits corruption, so this test deliberately does
        # not call integrity_check on the fabricated exhausted fixture.
        self.store._connection.execute("UPDATE ownership_allocator SET next_serial = ?", (MAX_SERIAL,))
        self.assert_code("identity_exhausted", self.reserve, 2)
        self.assertEqual(self.store._connection.execute("SELECT COUNT(*) FROM ownership_grants").fetchone()[0], 0)
        last = self.reserve(1)
        self.assertEqual((last.start, last.end_exclusive), (MAX_SERIAL, MAX_SERIAL + 1))
        self.assert_code("identity_exhausted", self.reserve, 1)

    def test_schema1_preserved_and_wrong_modes_refuse_to_open(self):
        legacy_path = Path(self.temp.name) / "legacy.sqlite3"
        legacy = CheckpointStore(legacy_path, BUILD, RULESET, LAYOUT_ID)
        legacy.close()
        original = legacy_path.read_bytes()
        self.assert_code("schema_incompatible", OwnershipCheckpointStore, legacy_path, BUILD, RULESET)
        self.assertEqual(legacy_path.read_bytes(), original)
        self.assert_code("schema_incompatible", CheckpointStore, self.path, BUILD, RULESET, OWNERSHIP_PROFILE)
        self.assert_code("save_profile_mismatch", OwnershipCheckpointStore, Path(self.temp.name) / "bad.sqlite3", BUILD, RULESET, LAYOUT_ID)

    def test_backup_reopen_and_full_history_detect_tombstone_event_corruption(self):
        grant = self.reserve()
        self.commit(owned_flash(grant))
        self.commit(owned_flash(grant, (), retirements=((1, 1),)), 1)
        backup = self.store.backup(Path(self.temp.name) / "backup.sqlite3")
        copied = OwnershipCheckpointStore(backup, BUILD, RULESET)
        copied.close()
        self.store._connection.execute("UPDATE ownership_instances SET retirement_reason = 2 WHERE serial = 1")
        self.assert_code("storage_corrupt", self.store.integrity_check)
        self.store._connection.execute("UPDATE ownership_instances SET retirement_reason = 1 WHERE serial = 1")
        self.store._connection.execute("UPDATE ownership_events SET reason = 2 WHERE kind = 'retire'")
        self.assert_code("storage_corrupt", self.store.integrity_check)

    def test_integrity_binds_account_trainer_to_enrolled_source(self):
        grant = self.reserve()
        payload = owned_flash(grant)
        self.commit(payload)
        # Mutating the native account trainer leaves the per-mon PID/OT and
        # ownership manifest unchanged. Both ordinary checksums and full SHA are
        # updated to ensure the separate enrollment invariant is what detects it.
        changed = _rewrite(_rewrite(payload, 0, 0, 10, struct.pack("<I", 77)), 1, 0, 10, struct.pack("<I", 77))
        inspect_flash(changed, save_profile=OWNERSHIP_PROFILE)
        self.store._connection.execute("UPDATE checkpoints SET payload = ?, sha256 = ? WHERE player_id = ? AND revision = 1",
                                       (changed, hashlib.sha256(changed).hexdigest(), self.owner.player_id))
        self.assert_code("storage_corrupt", self.store.integrity_check)
