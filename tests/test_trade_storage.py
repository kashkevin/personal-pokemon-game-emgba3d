from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

from emerald_multiplayer.ownership_protocol import OWNERSHIP_PROFILE
from emerald_multiplayer.ownership_storage import OwnershipCheckpointStore
from emerald_multiplayer.storage import StorageError
from emerald_multiplayer.trade_flash import build_party_swap
from emerald_multiplayer.trade_storage import TradeCheckpointStore, TradeSide
from test_flash import _rewrite
from test_ownership_storage import source_flash, owned_flash

BUILD, RULESET = "trade-test-ROM-sha256", "baseline-test-rules-v1"


class TradeStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "trades.sqlite3"
        self.store = TradeCheckpointStore(self.path, BUILD, RULESET)
        self.store.begin_server_boot()
        self.players, self.leases, self.grants, self.heads = [], [], [], []
        for index, pids in enumerate(((7, 8), (9, 10))):
            player = self.store.create_player("Player " + str(index))
            lease = self.store.acquire_lease(player.player_id, player.credential)
            self.store.enroll_player(player.player_id, source_flash(("party:0", "party:1"), personalities=pids))
            grant = self.store.reserve_instances(player.player_id, lease, str(uuid.uuid4()), 0, 1, 32)
            data = owned_flash(grant, (("party:0", grant.start), ("party:1", grant.start + 1)), personalities=pids)
            cp = self.store.commit_checkpoint(player.player_id, lease, str(uuid.uuid4()), 0, data, BUILD, RULESET, OWNERSHIP_PROFILE)
            self.players.append(player); self.leases.append(lease); self.grants.append(grant); self.heads.append(cp)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def assert_code(self, code, function, *args, **kwargs):
        with self.assertRaises(StorageError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def sides(self, *, heads=None, serials=None):
        heads = heads or self.heads
        serials = serials or (self.grants[0].start, self.grants[1].start)
        post = build_party_swap(heads[0].payload, serials[0], heads[1].payload, serials[1])
        return tuple(TradeSide(p.player_id, lease, cp.revision, serial, data)
                     for p, lease, cp, serial, data in zip(self.players, self.leases, heads, serials, post))

    def trade(self, sides=None, transaction=None):
        sides = sides or self.sides()
        return self.store.commit_trade(transaction or str(uuid.uuid4()), *sides, BUILD, RULESET, OWNERSHIP_PROFILE)

    def current_heads(self):
        return [self.store.read_checkpoint(p.player_id, lease) for p, lease in zip(self.players, self.leases)]

    def acknowledge(self, result, indices=(0, 1)):
        cps = {cp.player_id: cp for cp in (result.checkpoint_a, result.checkpoint_b)}
        for index in indices:
            cp = cps[self.players[index].player_id]
            self.store.acknowledge_trade(cp.player_id, self.leases[index], result.transaction_id, cp.revision, cp.sha256)

    def test_atomic_swap_preserves_identity_origin_and_all_unrelated_state(self):
        sides = self.sides()
        result = self.trade(sides)
        self.assertEqual(result.sequence, 3)
        self.assertEqual([cp.revision for cp in self.current_heads()], [2, 2])
        for index, expected_serial in enumerate((33, 1)):
            member = self.store.read_ownership(self.players[index].player_id, self.leases[index])
            self.assertEqual([r["serial"] for r in member], sorted((expected_serial, self.grants[index].start + 1)))
            row = self.store._connection.execute("SELECT * FROM ownership_instances WHERE serial = ?", (expected_serial,)).fetchone()
            self.assertEqual(row["player_id"], self.players[index].player_id)
            self.assertEqual(row["birth_player_id"], self.players[1-index].player_id)
            self.assertEqual(row["grant_id"], self.grants[1-index].grant_id)
            self.assertEqual(row["birth_revision"], 1)
            self.assertEqual(row["status"], "active")
            self.assertEqual(self.current_heads()[index].payload, sides[index].payload)
        kinds = [r[0] for r in self.store._connection.execute("SELECT kind FROM ownership_events WHERE transaction_id = ?", (result.transaction_id,))]
        self.assertEqual(sorted(kinds), ["retain", "retain", "transfer_in", "transfer_in", "transfer_out", "transfer_out"])
        self.store.integrity_check()

    def test_failure_after_both_revisions_written_rolls_back_every_table(self):
        counts = {table: self.store._connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                  for table in self.store._schema}
        original = self.store._membership
        calls = 0
        def fail_second(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("synthetic failure after first membership")
            return original(*args)
        with patch.object(self.store, "_membership", fail_second):
            with self.assertRaises(RuntimeError):
                self.trade()
        self.assertEqual(self.current_heads(), self.heads)
        self.assertEqual(counts, {table: self.store._connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                                  for table in self.store._schema})
        self.store.integrity_check()

    def test_revision_lease_identity_and_nontrade_mutations_reject(self):
        sides = self.sides()
        cases = [
            ("stale_lease", (replace(sides[0], lease_epoch=self.leases[1]), sides[1])),
            ("revision_conflict", (replace(sides[0], expected_revision=2), sides[1])),
            ("foreign_ownership", (replace(sides[0], serial=34), sides[1])),
            ("invalid_field", (replace(sides[0], serial=True), sides[1])),
            ("invalid_field", (replace(sides[0], expected_revision=True), sides[1])),
            ("invalid_trade", (sides[0], replace(sides[1], player_id=sides[0].player_id))),
            ("invalid_trade", (replace(sides[0], payload=self.heads[0].payload), sides[1])),
        ]
        # Money/story mutation with valid sector checksum is not an allowed
        # post-image even when ownership membership stays exactly conserved.
        mutated = _rewrite(sides[0].payload, 0, 1, 0x490, b"\x01")
        cases.append(("invalid_trade", (replace(sides[0], payload=mutated), sides[1])))
        for code, offered in cases:
            with self.subTest(code=code):
                self.assert_code(code, self.trade, offered)
                self.assertEqual(self.current_heads(), self.heads)
        self.store.integrity_check()

    def test_committed_exact_retry_survives_restart_fresh_leases_and_new_heads(self):
        sides, transaction = self.sides(), str(uuid.uuid4())
        original = self.trade(sides, transaction)
        self.assertEqual(self.trade(tuple(reversed(sides)), transaction), original)
        self.acknowledge(original)
        for index, cp in enumerate(self.current_heads()):
            self.store.commit_checkpoint(cp.player_id, self.leases[index], str(uuid.uuid4()), cp.revision,
                                         cp.payload, BUILD, RULESET, OWNERSHIP_PROFILE)
        old_leases = self.leases[:]
        self.store.close()
        self.store = TradeCheckpointStore(self.path, BUILD, RULESET)
        self.store.begin_server_boot()
        self.leases = [self.store.acquire_lease(p.player_id, p.credential) for p in self.players]
        self.assert_code("stale_lease", self.trade, sides, transaction)
        fresh = tuple(replace(s, lease_epoch=lease) for s, lease in zip(sides, self.leases))
        self.assertEqual(self.trade(fresh, transaction), original)
        self.assertEqual([cp.revision for cp in self.current_heads()], [3, 3])
        self.assert_code("request_conflict", self.trade, (replace(fresh[0], serial=2), fresh[1]), transaction)
        self.assert_code("request_conflict", self.trade, (replace(fresh[0], payload=self.heads[0].payload), fresh[1]), transaction)
        self.assertNotEqual(old_leases, self.leases)
        self.store.integrity_check()

    def test_pending_apply_barrier_is_player_specific_durable_and_ack_idempotent(self):
        result = self.trade()
        heads = self.current_heads()
        for index in (0, 1):
            recovery = self.store.pending_trade_recovery(self.players[index].player_id, self.leases[index])
            self.assertEqual(len(recovery), 1)
            self.assertEqual(recovery[0].checkpoint, heads[index])
            self.assert_code("trade_recovery_required", self.store.commit_checkpoint,
                             heads[index].player_id, self.leases[index], str(uuid.uuid4()), 2, heads[index].payload,
                             BUILD, RULESET, OWNERSHIP_PROFILE)
            self.assert_code("trade_recovery_required", self.store.reserve_instances,
                             heads[index].player_id, self.leases[index], str(uuid.uuid4()), 2, 1, 1)
        self.assert_code("trade_recovery_required", self.trade, self.sides(heads=heads, serials=(33, 1)))
        self.assert_code("trade_ack_mismatch", self.store.acknowledge_trade,
                         self.players[0].player_id, self.leases[0], result.transaction_id, 2, "0" * 64)
        self.acknowledge(result, (0,)); self.acknowledge(result, (0,))
        self.assertEqual(self.store.pending_trade_recovery(self.players[0].player_id, self.leases[0]), ())
        self.assertEqual(len(self.store.pending_trade_recovery(self.players[1].player_id, self.leases[1])), 1)
        self.store.close()
        self.store = TradeCheckpointStore(self.path, BUILD, RULESET)
        self.store.begin_server_boot()
        self.leases = [self.store.acquire_lease(p.player_id, p.credential) for p in self.players]
        self.assertEqual(len(self.store.pending_trade_recovery(self.players[1].player_id, self.leases[1])), 1)
        self.acknowledge(result)
        self.store.integrity_check()

    def test_transfer_back_and_release_keep_birth_provenance(self):
        first = self.trade()
        self.acknowledge(first)
        reverse = self.trade(self.sides(heads=self.current_heads(), serials=(33, 1)))
        self.acknowledge(reverse)
        self.assertEqual([cp.revision for cp in self.current_heads()], [3, 3])
        row = self.store._connection.execute("SELECT * FROM ownership_instances WHERE serial = 1").fetchone()
        self.assertEqual((row["player_id"], row["birth_player_id"], row["birth_revision"]),
                         (self.players[0].player_id, self.players[0].player_id, 1))
        released = owned_flash(self.grants[0], (("party:0", 2),), personalities=(8,), retirements=((1, 1),))
        self.store.commit_checkpoint(self.players[0].player_id, self.leases[0], str(uuid.uuid4()), 3,
                                     released, BUILD, RULESET, OWNERSHIP_PROFILE)
        row = self.store._connection.execute("SELECT * FROM ownership_instances WHERE serial = 1").fetchone()
        self.assertEqual((row["status"], row["retirement_reason"], row["birth_revision"]), ("retired", 1, 1))
        self.store.integrity_check()

    def test_ordinary_checkpoint_cannot_transfer_and_historical_read_is_not_restore(self):
        sides = self.sides()
        self.assert_code("foreign_ownership", self.store.commit_checkpoint,
                         self.players[0].player_id, self.leases[0], str(uuid.uuid4()), 1, sides[0].payload,
                         BUILD, RULESET, OWNERSHIP_PROFILE)
        result = self.trade(sides)
        self.acknowledge(result)
        old = self.store.read_checkpoint(self.players[0].player_id, self.leases[0], revision=1)
        self.assertEqual(old, self.heads[0])
        self.assert_code("foreign_ownership", self.store.commit_checkpoint,
                         old.player_id, self.leases[0], str(uuid.uuid4()), 2, old.payload,
                         BUILD, RULESET, OWNERSHIP_PROFILE)
        self.store.integrity_check()

    def test_recipient_can_retire_foreign_born_identity_without_rewriting_origin(self):
        result = self.trade(); self.acknowledge(result)
        released = owned_flash(self.grants[0], (("party:0", 2),), personalities=(8,), retirements=((33, 1),))
        self.store.commit_checkpoint(self.players[0].player_id, self.leases[0], str(uuid.uuid4()), 2,
                                     released, BUILD, RULESET, OWNERSHIP_PROFILE)
        row = self.store._connection.execute("SELECT * FROM ownership_instances WHERE serial = 33").fetchone()
        self.assertEqual((row["player_id"], row["birth_player_id"], row["status"], row["retirement_reason"]),
                         (self.players[0].player_id, self.players[1].player_id, "retired", 1))
        self.store.integrity_check()

    def test_birth_revision_belongs_to_origin_even_if_recipient_revision_is_lower(self):
        cp = self.heads[0]
        self.store.commit_checkpoint(cp.player_id, self.leases[0], str(uuid.uuid4()), 1,
                                     cp.payload, BUILD, RULESET, OWNERSHIP_PROFILE)
        new_mon = owned_flash(self.grants[0], (("party:0", 1), ("party:1", 2), ("party:2", 3)), personalities=(7, 8, 11))
        self.store.commit_checkpoint(cp.player_id, self.leases[0], str(uuid.uuid4()), 2,
                                     new_mon, BUILD, RULESET, OWNERSHIP_PROFILE)
        result = self.trade(self.sides(heads=self.current_heads(), serials=(3, 33)))
        self.acknowledge(result)
        row = self.store._connection.execute("SELECT * FROM ownership_instances WHERE serial = 3").fetchone()
        self.assertEqual((row["birth_player_id"], row["birth_revision"], row["player_id"], row["last_revision"]),
                         (self.players[0].player_id, 3, self.players[1].player_id, 2))
        self.store.integrity_check()

    def test_uncommitted_frozen_swap_survives_restart_without_rewriting_bytes(self):
        sides = self.sides()
        self.store.close()
        self.store = TradeCheckpointStore(self.path, BUILD, RULESET)
        self.store.begin_server_boot()
        self.leases = [self.store.acquire_lease(p.player_id, p.credential) for p in self.players]
        self.assert_code("stale_lease", self.trade, sides)
        fresh = tuple(replace(s, lease_epoch=lease) for s, lease in zip(sides, self.leases))
        result = self.trade(fresh)
        self.assertEqual({cp.player_id: cp.payload for cp in (result.checkpoint_a, result.checkpoint_b)},
                         {s.player_id: s.payload for s in sides})
        self.store.integrity_check()

    def test_commit_refuses_corrupt_unoffered_current_owner_before_any_mutation(self):
        sides = self.sides()
        # Offered1/33 remain correctly owned. A third retained mon must not be
        # silently reassigned by applying the otherwise valid full post-image.
        self.store._connection.execute("UPDATE ownership_instances SET player_id = ? WHERE serial = 34", (self.players[0].player_id,))
        self.assert_code("storage_corrupt", self.trade, sides)
        self.assertEqual(self.current_heads(), self.heads)
        self.assertEqual(self.store._connection.execute("SELECT COUNT(*) FROM trade_transactions").fetchone()[0], 0)

    def test_private_recovery_access_and_request_id_collision(self):
        transaction = self.heads[0].request_id
        self.assert_code("request_conflict", self.trade, transaction=transaction)
        result = self.trade()
        self.assertEqual(self.store.read_trade(self.players[0].player_id, self.leases[0], result.transaction_id), result)
        other = self.store.create_player("Other")
        lease = self.store.acquire_lease(other.player_id, other.credential)
        self.assert_code("trade_not_participant", self.store.read_trade, other.player_id, lease, result.transaction_id)
        self.assertEqual(self.store.pending_trade_recovery(other.player_id, lease), ())
        self.assert_code("trade_not_participant", self.store.acknowledge_trade, other.player_id, lease, result.transaction_id, 2, result.checkpoint_a.sha256)
        self.store.integrity_check()

    def test_schema2_remains_explicit_and_backup_reopens_full_trade_history(self):
        legacy_path = Path(self.temp.name) / "schema2.sqlite3"
        legacy = OwnershipCheckpointStore(legacy_path, BUILD, RULESET)
        legacy.close()
        before = legacy_path.read_bytes()
        self.assert_code("schema_incompatible", TradeCheckpointStore, legacy_path, BUILD, RULESET)
        self.assertEqual(legacy_path.read_bytes(), before)
        self.assert_code("schema_incompatible", OwnershipCheckpointStore, self.path, BUILD, RULESET)
        result = self.trade(); self.acknowledge(result)
        backup = self.store.backup(Path(self.temp.name) / "backup.sqlite3")
        with TradeCheckpointStore(backup, BUILD, RULESET) as copy:
            copy.integrity_check()
            self.assertEqual(copy._connection.execute("SELECT COUNT(*) FROM trade_transactions").fetchone()[0], 1)

    def test_integrity_detects_origin_transfer_event_outcome_and_nontrade_corruption(self):
        result = self.trade(); self.acknowledge(result)
        conn = self.store._connection
        mutations = [
            ("UPDATE ownership_instances SET birth_player_id = ? WHERE serial = 1", (self.players[1].player_id,),
             "UPDATE ownership_instances SET birth_player_id = ? WHERE serial = 1", (self.players[0].player_id,)),
            ("UPDATE ownership_events SET kind = 'retain' WHERE kind = 'transfer_in' AND serial = 1", (),
             "UPDATE ownership_events SET kind = 'transfer_in' WHERE transaction_id IS NOT NULL AND serial = 1 AND kind = 'retain'", ()),
            ("UPDATE trade_transactions SET fingerprint = ?", ("0" * 64,),
             "UPDATE trade_transactions SET fingerprint = ?", (result.outcome_fingerprint,)),
            ("UPDATE trade_recovery SET sha256 = ? WHERE player_id = ?", ("0" * 64, self.players[0].player_id),
             "UPDATE trade_recovery SET sha256 = ? WHERE player_id = ?", (self.current_heads()[0].sha256, self.players[0].player_id)),
        ]
        for sql, args, undo, undo_args in mutations:
            with self.subTest(sql=sql):
                conn.execute(sql, args)
                self.assert_code("storage_corrupt", self.store.integrity_check)
                conn.execute(undo, undo_args)
                self.store.integrity_check()
        cp = self.current_heads()[0]
        changed = _rewrite(cp.payload, 0, 1, 0x490, b"\x01")
        conn.execute("UPDATE checkpoints SET payload = ?, sha256 = ? WHERE player_id = ? AND revision = 2",
                     (changed, hashlib.sha256(changed).hexdigest(), cp.player_id))
        self.assert_code("storage_corrupt", self.store.integrity_check)
