from __future__ import annotations

import contextlib
import hashlib
import io
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from process_fixture import direct_python

from emerald_multiplayer.protocol import MAX_COUNTER
from emerald_multiplayer.storage import (
    APPLICATION_ID, BUSY_TIMEOUT, CheckpointStore, MAX_CHECKPOINT_BYTES, SCHEMA_VERSION, StorageError,
)


BUILD = "test-build-sha256"
RULESET = "test-ruleset-v1"
PROFILE = "validated-emerald-flash-with-rtc-v1"


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "world.sqlite3"
        self.store = CheckpointStore(self.path, BUILD, RULESET, PROFILE)
        self.boot = self.store.begin_server_boot()
        self.owner = self.store.create_player("Player A")
        self.lease = self.store.acquire_lease(self.owner.player_id, self.owner.credential)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def assert_code(self, code, function, *args, **kwargs):
        with self.assertRaises(StorageError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def commit(self, request="save-one", revision=0, payload=b"validated opaque save", **changes):
        values = dict(player_id=self.owner.player_id, lease_epoch=self.lease,
                      request_id=request, expected_revision=revision, payload=payload,
                      build_id=BUILD, ruleset_id=RULESET, save_profile=PROFILE)
        return self.store.commit_checkpoint(**{**values, **changes})

    def reopen(self):
        self.store.close()
        self.store = CheckpointStore(self.path, BUILD, RULESET, PROFILE)
        return self.store

    def test_server_issued_uuid_secret_and_authentication(self):
        self.assertEqual(str(uuid.UUID(self.owner.player_id)), self.owner.player_id)
        self.assertEqual(len(self.owner.credential), 32)
        self.assertNotIn(self.owner.credential.hex(), repr(self.owner))
        player = self.store.authenticate(self.owner.player_id, self.owner.credential)
        self.assertEqual(player.player_id, self.owner.player_id)
        self.assertEqual(player.display_name, "Player A")
        self.assertFalse(hasattr(player, "credential"))
        row = self.store._connection.execute("SELECT credential_hash FROM players").fetchone()
        self.assertEqual(row[0], hashlib.sha256(self.owner.credential).digest())
        self.assertNotEqual(row[0], self.owner.credential)
        for player_id, secret in ((self.owner.player_id, bytes(32)),
                                  (str(uuid.uuid4()), self.owner.credential),
                                  ("not-a-uuid", self.owner.credential),
                                  (self.owner.player_id, b"short")):
            self.assert_code("credentials_invalid", self.store.authenticate, player_id, secret)
            self.assert_code("credentials_invalid", self.store.acquire_lease, player_id, secret)

    def test_boot_required_and_stable_world_identity(self):
        other = CheckpointStore(Path(self.temp.name) / "other.sqlite3", BUILD, RULESET, PROFILE)
        try:
            owner = other.create_player("New Player")
            self.assertEqual(other.metadata.server_epoch, 0)
            self.assert_code("boot_required", other.acquire_lease, owner.player_id, owner.credential)
            first = other.begin_server_boot()
            second = other.begin_server_boot()
            self.assertEqual(first.world_id, second.world_id)
            self.assertGreater(second.server_epoch, first.server_epoch)
            self.assertGreater(second.session_epoch, first.session_epoch)
        finally:
            other.close()

    def test_one_active_lease_and_fenced_reacquisition(self):
        self.assert_code("lease_active", self.store.acquire_lease, self.owner.player_id, self.owner.credential)
        self.assertFalse(self.store.release_lease(self.owner.player_id, self.lease + 1))
        self.assertTrue(self.store.release_lease(self.owner.player_id, self.lease))
        self.assertFalse(self.store.release_lease(self.owner.player_id, self.lease))
        old = self.lease
        self.lease = self.store.acquire_lease(self.owner.player_id, self.owner.credential)
        self.assertGreater(self.lease, old)
        self.assert_code("stale_lease", self.commit, lease_epoch=old)
        self.assert_code("stale_lease", self.store.read_checkpoint, self.owner.player_id, old)

    def test_lease_is_current_reads_without_waiting_for_a_writer(self):
        # KNOWN_ISSUES MS-17: the team roster checked every connected player's lease with a whole checkpoint read
        # under BEGIN IMMEDIATE, on every world broadcast, on the host's event loop - which waits up to the 5 s busy
        # timeout while another connection writes. The lease check alone is a read-only snapshot.
        self.commit(payload=bytes(range(256)) * 512)
        self.assertTrue(self.store.lease_is_current(self.owner.player_id, self.lease))
        self.assertFalse(self.store.lease_is_current(self.owner.player_id, self.lease + 1))
        self.assertFalse(self.store.lease_is_current(str(uuid.uuid4()), self.lease))
        writer = sqlite3.connect(self.path, isolation_level=None, timeout=5)
        try:
            writer.execute("BEGIN IMMEDIATE")      # another connection in the middle of a write
            writer.execute("UPDATE world_metadata SET singleton = singleton")
            started = time.monotonic()
            self.assertTrue(self.store.lease_is_current(self.owner.player_id, self.lease))
            self.assertLess(time.monotonic() - started, 1)
            self.assert_code("storage_error", self.store.read_checkpoint, self.owner.player_id, self.lease)
        finally:
            writer.execute("ROLLBACK")
            writer.close()
        self.assertTrue(self.store.release_lease(self.owner.player_id, self.lease))
        self.assertFalse(self.store.lease_is_current(self.owner.player_id, self.lease))

    def hold_lock(self, seconds):
        """Another connection in the middle of a write for `seconds` (a thread ends it)."""
        writer = sqlite3.connect(self.path, isolation_level=None, timeout=5, check_same_thread=False)
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("UPDATE world_metadata SET singleton = singleton")

        def release():
            writer.execute("ROLLBACK")
            writer.close()
        timer = threading.Timer(seconds, release)
        timer.start()
        return timer

    def test_a_lock_held_for_a_while_is_waited_for_and_the_wait_reported(self):
        # KNOWN_ISSUES MS-93: the host's first transaction after a long session met a lock another connection still held.
        # Within the busy timeout the transaction waits; a wait of a second or more is reported with the log's size.
        timer = self.hold_lock(1.5)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            started = time.monotonic()
            self.assertEqual(self.store.metadata.world_id, self.boot.world_id)
            waited = time.monotonic() - started
        timer.join()
        self.assertGreaterEqual(waited, 1.2)
        self.assertRegex(stderr.getvalue(), r"checkpoint store: waited \d+\.\d s for the database lock "
                                            r"\(wal \d+ bytes, shm \d+ bytes\)")

    def test_a_lock_held_past_the_busy_timeout_names_the_wait_and_the_log(self):
        # MS-93's failure line said only SQLITE_BUSY; it now says how long the transaction waited and how big the
        # write-ahead log was.
        self.store.set_busy_timeout(0.3)
        timer = self.hold_lock(1.5)
        try:
            with self.assertRaises(StorageError) as caught:
                self.store.metadata
        finally:
            timer.join()
        self.assertEqual(caught.exception.code, "storage_error")
        self.assertRegex(str(caught.exception), r"checkpoint transaction failed \(SQLITE_BUSY after 0\.\d s; "
                                                r"wal \d+ bytes, shm \d+ bytes\)")

    def test_a_store_opened_with_a_longer_busy_timeout_outwaits_a_lock_the_default_does_not(self):
        # A host's start opens its store with STARTUP_BUSY_TIMEOUT (launcher_session), play goes back to BUSY_TIMEOUT.
        self.store.close()
        timer = self.hold_lock(1.5)
        try:
            with self.assertRaises(StorageError):
                CheckpointStore(self.path, BUILD, RULESET, PROFILE, busy_timeout=0.5)
        finally:
            timer.join()
        timer = self.hold_lock(1.5)
        with contextlib.redirect_stderr(io.StringIO()):
            self.store = CheckpointStore(self.path, BUILD, RULESET, PROFILE, busy_timeout=4)
        timer.join()
        self.assertEqual(self.store._connection.execute("PRAGMA busy_timeout").fetchone()[0], 4000)
        self.store.set_busy_timeout(BUSY_TIMEOUT)
        self.assertEqual(self.store._connection.execute("PRAGMA busy_timeout").fetchone()[0], BUSY_TIMEOUT * 1000)
        self.assertEqual(self.store.metadata.world_id, self.boot.world_id)

    def test_an_integrity_check_does_not_hold_the_write_lock(self):
        # KNOWN_ISSUES MS-93's cause: the launcher window checks every world in the background (when it opens and when a
        # game ends), the check reads every checkpoint again (seconds for a 100-floor climb's world), and it held the
        # write lock: the host's own open, starting meanwhile, gave up after its busy timeout. It is a snapshot now.
        self.commit()
        checking, checked = threading.Event(), []

        def slow_extra():
            checking.set()
            time.sleep(1.5)

        def background():
            with CheckpointStore(self.path, BUILD, RULESET, PROFILE) as other:
                other._verified = None
                other._integrity_extra = slow_extra
                other.integrity_check()
                checked.append(True)
        thread = threading.Thread(target=background)
        thread.start()
        try:
            self.assertTrue(checking.wait(10))
            self.store.set_busy_timeout(0.3)
            started = time.monotonic()
            self.commit("save-two", 1)                        # a write while the other connection checks
            CheckpointStore(self.path, BUILD, RULESET, PROFILE, busy_timeout=0.3).close()   # and another open
            self.assertLess(time.monotonic() - started, 1.2)
        finally:
            thread.join()
        self.assertEqual(checked, [True])

    def test_a_repeated_integrity_check_reads_again_only_after_a_change(self):
        # A host's start checked its world four times in a row (the world descriptor's open and its second check, the
        # host store's open, the world server's); with nothing committed in between the answer is the same.
        full = []
        self.store._integrity_extra = lambda: full.append(1)
        self.store.integrity_check()                         # setUp wrote after the open's check
        self.store.integrity_check()
        self.assertEqual(len(full), 1)
        self.commit()                                        # a row changed through this connection
        self.store.integrity_check()
        self.store.integrity_check()
        self.assertEqual(len(full), 2)
        other = sqlite3.connect(self.path, isolation_level=None)
        try:
            other.execute("UPDATE world_metadata SET singleton = singleton")   # a commit by another connection
        finally:
            other.close()
        self.store.integrity_check()
        self.assertEqual(len(full), 3)
        self.store._connection.execute("CREATE TABLE extra (value)")          # a schema change, no row changed
        self.assert_code("schema_incompatible", self.store.integrity_check)
        self.assert_code("schema_incompatible", self.store.integrity_check)   # a failed check is not remembered
        self.store._connection.execute("DROP TABLE extra")
        self.store.integrity_check()
        self.assertEqual(len(full), 4)
        version = self.store._connection.execute("PRAGMA user_version").fetchone()[0]
        self.store._connection.execute(f"PRAGMA user_version = {version + 1}")
        self.assert_code("schema_incompatible", self.store.integrity_check)
        self.store._connection.execute(f"PRAGMA user_version = {version}")
        self.store.integrity_check()                         # exactly as last verified again

    def test_second_live_host_rejected_then_new_boot_fences_old_lease(self):
        newer = CheckpointStore(self.path, BUILD, RULESET, PROFILE)
        try:
            self.assert_code("host_active", newer.begin_server_boot)
            self.assertEqual(newer.metadata.server_epoch, self.boot.server_epoch)
            self.store.close()
            boot = newer.begin_server_boot()
            self.assertEqual(boot.world_id, self.boot.world_id)
            self.assertGreater(boot.server_epoch, self.boot.server_epoch)
            self.assertGreater(boot.session_epoch, self.lease)
            lease = newer.acquire_lease(self.owner.player_id, self.owner.credential)
            self.assertGreater(lease, self.lease)
            self.assert_code("stale_lease", newer.read_checkpoint, self.owner.player_id, self.lease)
            self.assertIsNone(newer.read_checkpoint(self.owner.player_id, lease))
        finally:
            newer.close()

    def test_old_instance_rejects_externally_fenced_server_epoch(self):
        # Defensive check if the database was replaced/modified outside the host.
        self.store._connection.execute("UPDATE world_metadata SET server_epoch=server_epoch+1")
        self.assert_code("server_fenced", self.commit)
        self.assert_code("server_fenced", self.store.acquire_lease, self.owner.player_id, self.owner.credential)

    def test_process_lifetime_host_lock_survives_then_releases_on_crash(self):
        self.store.close()
        child_code = """
import os, sys
from emerald_multiplayer.storage import CheckpointStore
store = CheckpointStore(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
store.begin_server_boot()
print(f'hosting:{os.getpid()}', flush=True)
sys.stdin.readline()
"""
        child = subprocess.Popen([direct_python(), "-u", "-c", child_code,
                                  str(self.path), BUILD, RULESET, PROFILE],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), f"hosting:{child.pid}")
            self.store = CheckpointStore(self.path, BUILD, RULESET, PROFILE)
            old = self.store.metadata
            self.assert_code("host_active", self.store.begin_server_boot)
            child.kill()
            child.wait(timeout=5)
            current = self.store.begin_server_boot()
            self.assertGreater(current.server_epoch, old.server_epoch)
            self.lease = self.store.acquire_lease(self.owner.player_id, self.owner.credential)
            self.assertEqual(self.commit().revision, 1)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
            child.stdin.close()
            child.stdout.close()
            child.stderr.close()

    def test_checkpoint_sha_revision_history_and_exact_retry(self):
        self.assertIsNone(self.store.read_checkpoint(self.owner.player_id, self.lease))
        first = self.commit()
        self.assertEqual(first.revision, 1)
        self.assertEqual(first.sha256, hashlib.sha256(first.payload).hexdigest())
        self.assertEqual(self.commit(), first)
        second = self.commit("save-two", 1, b"new validated save")
        self.assertEqual(second.revision, 2)
        self.assertEqual(self.store.read_checkpoint(self.owner.player_id, self.lease), second)
        self.assertEqual(self.store.read_checkpoint(self.owner.player_id, self.lease, revision=1), first)
        self.assertIsNone(self.store.read_checkpoint(self.owner.player_id, self.lease, revision=3))
        self.assertEqual(self.commit(), first)  # Original acknowledgement after a newer save.
        self.store.integrity_check()

    def test_lost_ack_exact_retry_after_restart_requires_new_lease(self):
        first = self.commit()
        old_lease = self.lease
        old_metadata = self.store.metadata
        self.reopen()
        self.assertEqual(self.store.metadata.world_id, old_metadata.world_id)
        boot = self.store.begin_server_boot()
        self.assertGreater(boot.session_epoch, old_lease)
        self.assert_code("stale_lease", self.commit)  # Matching request cannot authorize a stale session.
        self.lease = self.store.acquire_lease(self.owner.player_id, self.owner.credential)
        self.assertEqual(self.commit(), first)
        self.assertEqual(self.store.read_checkpoint(self.owner.player_id, self.lease), first)
        self.assert_code("request_conflict", self.commit, payload=b"different bytes")

    def test_request_content_and_expected_revision_conflicts_are_atomic(self):
        first = self.commit()
        self.assert_code("request_conflict", self.commit, payload=b"changed")
        self.assert_code("request_conflict", self.commit, revision=1)
        self.assert_code("revision_conflict", self.commit, request="new-request", revision=0)
        self.assert_code("revision_conflict", self.commit, request="future-request", revision=2)
        self.assertEqual(self.store.read_checkpoint(self.owner.player_id, self.lease), first)
        self.assertEqual(self.store._connection.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0], 1)

    def test_independent_characters_and_request_namespaces(self):
        other = self.store.create_player("Player B")
        other_lease = self.store.acquire_lease(other.player_id, other.credential)
        first = self.commit()
        second = self.commit(player_id=other.player_id, lease_epoch=other_lease, payload=b"independent B save")
        self.assertEqual(first.revision, second.revision)
        self.assertNotEqual(first.player_id, second.player_id)
        self.assertEqual(self.store.read_checkpoint(self.owner.player_id, self.lease), first)
        self.assertEqual(self.store.read_checkpoint(other.player_id, other_lease), second)
        self.assert_code("stale_lease", self.commit, player_id=other.player_id)
        self.assert_code("credentials_invalid", self.store.authenticate, other.player_id, self.owner.credential)

    def test_full_flash_and_optional_rtc_container_are_preserved(self):
        container = b"F" * 131_072 + b"R" * 16
        checkpoint = self.commit(payload=container)
        self.assertEqual(len(checkpoint.payload), MAX_CHECKPOINT_BYTES)
        self.assertEqual(checkpoint.sha256, hashlib.sha256(container).hexdigest())
        self.reopen()
        self.store.begin_server_boot()
        self.lease = self.store.acquire_lease(self.owner.player_id, self.owner.credential)
        self.assertEqual(self.store.read_checkpoint(self.owner.player_id, self.lease).payload, container)

    def test_payload_bindings_and_bounds_rejected_before_mutation(self):
        for field, value, code in (("build_id", "other", "build_mismatch"),
                                   ("ruleset_id", "other", "ruleset_mismatch"),
                                   ("save_profile", "other", "save_profile_mismatch")):
            self.assert_code(code, self.commit, **{field: value})
        for changes in ({"payload": b""}, {"payload": b"x" * (MAX_CHECKPOINT_BYTES + 1)},
                        {"payload": bytearray(b"x")}, {"expected_revision": -1},
                        {"expected_revision": True}, {"request_id": ""}, {"lease_epoch": True}):
            self.assert_code("invalid_field", self.commit, **changes)
        self.assertIsNone(self.store.read_checkpoint(self.owner.player_id, self.lease))

    def test_existing_world_bindings_cannot_silently_change(self):
        for build, rules, profile, code in (("other", RULESET, PROFILE, "build_mismatch"),
                                          (BUILD, "other", PROFILE, "ruleset_mismatch"),
                                          (BUILD, RULESET, "other", "save_profile_mismatch")):
            self.assert_code(code, CheckpointStore, self.path, build, rules, profile)
        self.assert_code("payload_limit_mismatch", CheckpointStore, self.path, BUILD, RULESET, PROFILE, max_payload_bytes=100)
        self.assertEqual(self.store.metadata.world_id, self.boot.world_id)

    def test_counter_exhaustion_does_not_wrap_or_fence_current_lease(self):
        self.store._connection.execute("UPDATE world_metadata SET session_epoch = ?", (MAX_COUNTER,))
        other = self.store.create_player("Player B")
        self.assert_code("counter_exhausted", self.store.acquire_lease, other.player_id, other.credential)
        self.assert_code("counter_exhausted", self.store.begin_server_boot)
        self.assertEqual(self.store.metadata.server_epoch, self.boot.server_epoch)
        self.assertEqual(self.commit().revision, 1)

    def test_failed_second_statement_rolls_back_blob_and_revision(self):
        def deny_player_update(action, arg1, arg2, database, source):
            if action == sqlite3.SQLITE_UPDATE and arg1 == "players":
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        self.store._connection.set_authorizer(deny_player_update)
        try:
            self.assert_code("storage_error", self.commit)
        finally:
            self.store._connection.set_authorizer(None)
        self.assertEqual(self.store._connection.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0], 0)
        self.assertIsNone(self.store.read_checkpoint(self.owner.player_id, self.lease))
        self.assertEqual(self.commit().revision, 1)
        self.store.integrity_check()

    def test_killed_uncommitted_writer_recovers_previous_canonical_revision(self):
        first = self.commit()
        self.store.close()
        child_code = """
import hashlib, os, sqlite3, sys
db = sqlite3.connect(sys.argv[1], isolation_level=None)
db.execute('PRAGMA synchronous=FULL')
db.execute('BEGIN IMMEDIATE')
data = b'interrupted new save'
db.execute('INSERT INTO checkpoints VALUES (?,2,?,1,?,?,?,?,?)',
           (sys.argv[2], 'interrupted', data, hashlib.sha256(data).hexdigest(),
            sys.argv[3], sys.argv[4], sys.argv[5]))
db.execute('UPDATE players SET latest_revision=2 WHERE player_id=?', (sys.argv[2],))
print(f'staged:{os.getpid()}', flush=True)
sys.stdin.readline()
"""
        child = subprocess.Popen([direct_python(), "-u", "-c", child_code, str(self.path),
                                  self.owner.player_id, BUILD, RULESET, PROFILE],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), f"staged:{child.pid}")
            child.kill()
            child.wait(timeout=5)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
            child.stdin.close()
            child.stdout.close()
            child.stderr.close()
        self.store = CheckpointStore(self.path, BUILD, RULESET, PROFILE)
        self.store.begin_server_boot()
        self.lease = self.store.acquire_lease(self.owner.player_id, self.owner.credential)
        self.assertEqual(self.store.read_checkpoint(self.owner.player_id, self.lease), first)
        self.assertIsNone(self.store.read_checkpoint(self.owner.player_id, self.lease, revision=2))
        self.assertEqual(self.commit("recovery", 1).revision, 2)

    def test_unknown_version_extra_schema_and_non_database_fail_closed(self):
        unknown = Path(self.temp.name) / "unknown.sqlite3"
        db = sqlite3.connect(unknown)
        try:
            db.execute("CREATE TABLE unrelated(value TEXT)")
            db.commit()
        finally:
            db.close()
        self.assert_code("schema_incompatible", CheckpointStore, unknown, BUILD, RULESET, PROFILE)
        broken = Path(self.temp.name) / "broken.sqlite3"
        original = b"corrupt checkpoint database bytes"
        broken.write_bytes(original)
        self.assert_code("storage_corrupt", CheckpointStore, broken, BUILD, RULESET, PROFILE)
        self.assertEqual(broken.read_bytes(), original)
        self.store._connection.execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")
        self.assert_code("schema_incompatible", CheckpointStore, self.path, BUILD, RULESET, PROFILE)
        self.store._connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        self.store._connection.execute("CREATE TABLE unexpected(value TEXT)")
        self.assert_code("schema_incompatible", self.store.integrity_check)
        self.store._connection.execute("DROP TABLE unexpected")
        # LIKE's underscore wildcard must not hide an unrelated user table.
        self.store._connection.execute("CREATE TABLE sqliteevil(value TEXT)")
        self.assert_code("schema_incompatible", self.store.integrity_check)
        self.store._connection.execute("DROP TABLE sqliteevil")
        self.assertEqual(self.store._connection.execute("PRAGMA application_id").fetchone()[0], APPLICATION_ID)

    def test_corrupt_checkpoint_hash_fails_read_startup_and_backup(self):
        self.commit()
        self.store._connection.execute("UPDATE checkpoints SET payload=?", (b"corrupt bytes",))
        self.assert_code("storage_corrupt", self.store.read_checkpoint, self.owner.player_id, self.lease)
        self.assert_code("storage_corrupt", self.store.integrity_check)
        backup = Path(self.temp.name) / "must-not-create.sqlite3"
        self.assert_code("storage_corrupt", self.store.backup, backup)
        self.assertFalse(backup.exists())
        self.store.close()
        self.assert_code("storage_corrupt", CheckpointStore, self.path, BUILD, RULESET, PROFILE)

    def test_consistent_sqlite_backup_retains_checkpoint_and_world_uuid(self):
        first = self.commit()
        destination = Path(self.temp.name) / "recovery.sqlite3"
        self.assertEqual(self.store.backup(destination), destination)
        self.assert_code("backup_exists", self.store.backup, destination)
        self.assert_code("backup_exists", self.store.backup, self.path)
        second = self.commit("save-two", 1, b"new later save")
        self.assertNotEqual(first, second)
        backup = CheckpointStore(destination, BUILD, RULESET, PROFILE)
        try:
            self.assertEqual(backup.metadata.world_id, self.store.metadata.world_id)
            backup.begin_server_boot()
            lease = backup.acquire_lease(self.owner.player_id, self.owner.credential)
            self.assertEqual(backup.read_checkpoint(self.owner.player_id, lease), first)
            backup.integrity_check()
        finally:
            backup.close()


if __name__ == "__main__":
    unittest.main()
