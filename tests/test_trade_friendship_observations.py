from dataclasses import replace
import hashlib
from itertools import permutations
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from emerald_multiplayer.battle_reservations import enable_battle_reservations
from emerald_multiplayer.flash import inspect_flash
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE
from emerald_multiplayer.ownership_storage import OwnershipCheckpointStore
from emerald_multiplayer.reset_attempts import enable_reset_attempts
from emerald_multiplayer.storage import Checkpoint, StorageError
from emerald_multiplayer.trade_storage import TradeCheckpointStore
from emerald_multiplayer.trade_friendship_observations import (
    FriendshipObservations, checkpoint_observations, enable_friendship_observations,
)
from test_flash import _rewrite
from test_ownership import PLAYER_ID, make_ownership_flash
from test_ownership_storage import owned_flash
from test_trade_friendship import make_friendship_mon
import test_trade_friendship_flash as pair_fixtures
import test_trade_storage as store_fixtures


def _commit_and_exit(path, player, credential, payload):
    import os
    store = TradeCheckpointStore(path, store_fixtures.BUILD, store_fixtures.RULESET)
    store.begin_server_boot()
    lease = store.acquire_lease(player, credential)
    store.commit_checkpoint(player, lease, str(uuid4()), 1, payload,
                            store_fixtures.BUILD, store_fixtures.RULESET, OWNERSHIP_PROFILE)
    os._exit(79)


class FriendshipObservationDecoderTests(unittest.TestCase):
    def test_native_value_and_origin_decode_all_24_permutations(self):
        for pid in range(24):
            with self.subTest(pid=pid):
                payload = make_ownership_flash(records=(("party:0", 1),), personalities=(pid,))
                payload = _rewrite(payload, 0, 1, 0x238, make_friendship_mon(pid, serial=1, friendship=100+pid))
                cp = Checkpoint(PLAYER_ID, 1, str(uuid4()), payload, hashlib.sha256(payload).hexdigest(),
                                "build", "rules", OWNERSHIP_PROFILE)
                value = json.loads(checkpoint_observations(cp)[0][3])
                self.assertEqual(value["native_value"], 100+pid)
                self.assertEqual(value["original"], {"name": b"ALICE".hex(), "gender": 0,
                                                     "trainer_id": 0xAABBCCDD, "version": 3})

    def test_every_owned_location_and_original_match_remains_unknown(self):
        locations = ([f"party:{i}" for i in range(6)] + [f"box:{b}:{i}" for b in range(14) for i in range(30)]
                     + [f"daycare:{i}" for i in range(2)] + [f"fusion:{i}" for i in range(4)])
        payload = make_ownership_flash(records=tuple((location, index+1) for index, location in enumerate(locations)))
        cp = Checkpoint(PLAYER_ID, 1, str(uuid4()), payload, hashlib.sha256(payload).hexdigest(),
                        "build", "rules", OWNERSHIP_PROFILE)
        rows = checkpoint_observations(cp)
        self.assertEqual(len(rows), 432)
        self.assertEqual([json.loads(row[3])["location"] for row in rows], locations)
        self.assertTrue(all(json.loads(row[3])["handler_history"] == "unknown" for row in rows))
        a, _, _, _ = pair_fixtures.FriendshipFlashTests().sources()
        value = json.loads(next(row[3] for row in checkpoint_observations(a) if row[2] == 2))
        self.assertEqual({k: value["original"][k] for k in ("name", "gender", "trainer_id")}, value["owner"])
        self.assertEqual(value["handler_history"], "unknown")
        self.assertEqual((value["native_value"], value["native_role"]), (215, "friendship"))

    def test_egg_value_is_hatch_cycles_and_source_hash_or_owner_changes_refuse(self):
        a, _, _, _ = pair_fixtures.FriendshipFlashTests().sources()
        snapshot = inspect_flash(a.payload, save_profile=OWNERSHIP_PROFILE)
        offset = 0x238 + 100 + 19
        original = snapshot.save_block1[offset]
        egg = _rewrite(a.payload, snapshot.metadata.bank, 1, offset, bytes([original | 4]))
        egg_cp = replace(a, payload=egg, sha256=hashlib.sha256(egg).hexdigest())
        value = json.loads(next(row[3] for row in checkpoint_observations(egg_cp) if row[2] == 2))
        self.assertEqual((value["native_value"], value["native_role"], value["handler_history"]),
                         (215, "hatch_cycles", "unknown"))
        for changed in (replace(a, sha256="0"*64), replace(a, player_id=str(uuid4())),
                        replace(a, payload=bytearray(a.payload))):
            with self.subTest(changed=changed), self.assertRaises(StorageError):
                checkpoint_observations(changed)


class FriendshipObservationStoreTests(unittest.TestCase):
    def setUp(self):
        self.fixture = store_fixtures.TradeStorageTests()
        self.fixture.setUp()
        self.store = self.fixture.store
        self.root = Path(self.fixture.temp.name)

    def tearDown(self):
        self.fixture.tearDown()

    def migrate(self):
        f = self.fixture
        for player, lease in zip(f.players, f.leases):
            self.store.release_lease(player.player_id, lease)
        self.assertTrue(enable_friendship_observations(self.store, self.root / "friendship-before.sqlite3"))
        f.leases = [self.store.acquire_lease(p.player_id, p.credential) for p in f.players]
        return FriendshipObservations(self.store)

    def counts(self):
        return {table: self.store._connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                for table in self.store._schema}

    def test_legacy_world_never_auto_migrates_and_backfill_is_unknown_after_prior_trade(self):
        self.assertFalse(self.store.friendship_observations_enabled)
        with self.assertRaises(StorageError):
            FriendshipObservations(self.store)
        f = self.fixture
        result = f.trade()
        f.acknowledge(result)
        before = f.current_heads()
        ledger = self.migrate()
        self.assertEqual(self.store._schema_version, 403)
        self.assertEqual(f.current_heads(), before)
        self.assertEqual(self.counts()["pokemon_friendship_observations"], 8)
        observed = ledger.read_current(f.players[0].player_id, f.leases[0], 33)
        self.assertEqual(observed["handler_history"], "unknown")
        self.assertEqual(observed["native_role"], "friendship")
        with TradeCheckpointStore(self.root / "friendship-before.sqlite3", store_fixtures.BUILD,
                                   store_fixtures.RULESET) as backup:
            self.assertFalse(backup.friendship_observations_enabled)
            self.assertEqual(backup._schema_version, 3)
        self.assertFalse(enable_friendship_observations(self.store, self.root / "not-created"))
        self.assertFalse((self.root / "not-created").exists())
        self.store.integrity_check()

    def test_active_lease_and_existing_backup_refuse_without_mutation(self):
        before = self.counts()
        with self.assertRaisesRegex(StorageError, "close characters"):
            enable_friendship_observations(self.store, self.root / "blocked")
        self.assertEqual(before, self.counts())
        self.assertFalse((self.root / "blocked").exists())
        for player, lease in zip(self.fixture.players, self.fixture.leases):
            self.store.release_lease(player.player_id, lease)
        existing = self.root / "existing"
        existing.write_bytes(b"keep this backup")
        with self.assertRaises(StorageError):
            enable_friendship_observations(self.store, existing)
        self.assertEqual(existing.read_bytes(), b"keep this backup")
        self.assertFalse(self.store.friendship_observations_enabled)

    def test_failed_backfill_rolls_back_schema_and_all_rows_but_retains_backup(self):
        for player, lease in zip(self.fixture.players, self.fixture.leases):
            self.store.release_lease(player.player_id, lease)
        enable_reset_attempts(self.store, self.root / "reset-before")
        before, version = self.counts(), self.store._schema_version
        original = FriendshipObservations._append
        calls = []
        def fail_second(ledger, checkpoint):
            original(ledger, checkpoint)
            calls.append(checkpoint)
            if len(calls) == 2:
                raise RuntimeError("interrupt after canonical backfill rows")
        with patch.object(FriendshipObservations, "_append", fail_second), self.assertRaises(RuntimeError):
            enable_friendship_observations(self.store, self.root / "preserved-backup")
        self.assertEqual((self.counts(), self.store._schema_version), (before, version))
        self.assertTrue(self.store.reset_attempts_enabled)
        self.assertFalse(self.store.friendship_observations_enabled)
        self.assertTrue((self.root / "preserved-backup").exists())
        self.store.integrity_check()

    def test_ordinary_checkpoint_and_observations_rollback_together(self):
        self.migrate()
        before, heads = self.counts(), self.fixture.current_heads()
        original = FriendshipObservations._append
        def append_then_fail(ledger, checkpoint):
            original(ledger, checkpoint)
            raise RuntimeError("interrupt after observation insert")
        f = self.fixture
        with patch.object(FriendshipObservations, "_append", append_then_fail), self.assertRaises(RuntimeError):
            self.store.commit_checkpoint(f.players[0].player_id, f.leases[0], str(uuid4()), 1,
                heads[0].payload, store_fixtures.BUILD, store_fixtures.RULESET, OWNERSHIP_PROFILE)
        self.assertEqual((self.counts(), f.current_heads()), (before, heads))
        with self.assertRaises(StorageError):
            FriendshipObservations(self.store)._append(heads[0])
        self.store.integrity_check()

    def test_both_trade_heads_and_observations_are_atomic_and_exact_retry_is_idempotent(self):
        ledger = self.migrate()
        f = self.fixture
        before, heads = self.counts(), f.current_heads()
        sides, transaction = f.sides(), str(uuid4())
        original = FriendshipObservations._append
        calls = []
        def fail_second(ledger, checkpoint):
            original(ledger, checkpoint)
            calls.append(checkpoint)
            if len(calls) == 2:
                raise RuntimeError("interrupt paired observation publication")
        with patch.object(FriendshipObservations, "_append", fail_second), self.assertRaises(RuntimeError):
            f.trade(sides, transaction)
        self.assertEqual((self.counts(), f.current_heads()), (before, heads))
        result = f.trade(sides, transaction)
        after = self.counts()
        self.assertEqual(f.trade(sides, transaction), result)
        self.assertEqual(self.counts(), after)
        self.assertEqual(after["pokemon_friendship_observations"], before["pokemon_friendship_observations"]+4)
        self.assertEqual(ledger.read_current(f.players[0].player_id, f.leases[0], 33)["handler_history"], "unknown")
        with self.assertRaises(StorageError):
            ledger.read_current(f.players[0].player_id, f.leases[0], 1)
        self.store.integrity_check()

    def test_reads_require_current_owner_and_lease_and_retired_rows_remain_historical(self):
        ledger = self.migrate()
        f = self.fixture
        for player, lease, serial in ((f.players[0].player_id, f.leases[0]+99, 1),
                                      (f.players[0].player_id, f.leases[0], 33),
                                      (f.players[0].player_id, f.leases[0], True)):
            with self.subTest(serial=serial, lease=lease), self.assertRaises(StorageError):
                ledger.read_current(player, lease, serial)
        payload = owned_flash(f.grants[0], (("party:0", 1),), personalities=(7,), retirements=((2, 1),))
        self.store.commit_checkpoint(f.players[0].player_id, f.leases[0], str(uuid4()), 1, payload,
                                    store_fixtures.BUILD, store_fixtures.RULESET, OWNERSHIP_PROFILE)
        with self.assertRaises(StorageError):
            ledger.read_current(f.players[0].player_id, f.leases[0], 2)
        self.assertIsNotNone(self.store._connection.execute(
            "SELECT 1 FROM pokemon_friendship_observations WHERE player_id=? AND revision=1 AND serial=2",
            (f.players[0].player_id,)).fetchone())
        self.store.integrity_check()

    def test_tampered_or_missing_observation_blocks_reads_and_replay(self):
        ledger = self.migrate()
        f = self.fixture
        where = (f.players[0].player_id, 1, 1)
        old = tuple(self.store._connection.execute(
            "SELECT * FROM pokemon_friendship_observations WHERE player_id=? AND revision=? AND serial=?", where).fetchone())
        changed = json.loads(old[3])
        changed["handler_history"] = "known"
        self.store._connection.execute("UPDATE pokemon_friendship_observations SET observation=?, sha256=? WHERE player_id=? AND revision=? AND serial=?",
            (json.dumps(changed), hashlib.sha256(json.dumps(changed).encode()).hexdigest(), *where))
        with self.assertRaises(StorageError):
            ledger.read_current(f.players[0].player_id, f.leases[0], 1)
        with self.assertRaises(StorageError):
            self.store.integrity_check()
        self.store._connection.execute("UPDATE pokemon_friendship_observations SET observation=?, sha256=? WHERE player_id=? AND revision=? AND serial=?",
                                       (old[3], old[4], *where))
        self.store.integrity_check()
        self.store._connection.execute("DELETE FROM pokemon_friendship_observations WHERE player_id=? AND revision=? AND serial=?", where)
        with self.assertRaises(StorageError):
            self.store.integrity_check()

    def test_committed_checkpoint_observations_survive_abrupt_host_exit(self):
        import multiprocessing
        self.migrate()
        f = self.fixture
        self.store.close()
        process = multiprocessing.get_context("spawn").Process(target=_commit_and_exit,
            args=(f.path, f.players[0].player_id, f.players[0].credential, f.heads[0].payload))
        process.start()
        process.join(20)
        if process.is_alive():
            process.terminate()
            process.join(5)
            self.fail("isolated committed-exit fixture exceeded its bound")
        self.assertEqual(process.exitcode, 79)
        process.close()
        self.store = f.store = TradeCheckpointStore(f.path, store_fixtures.BUILD, store_fixtures.RULESET)
        self.store.begin_server_boot()
        lease = self.store.acquire_lease(f.players[0].player_id, f.players[0].credential)
        self.assertEqual(self.store.read_checkpoint(f.players[0].player_id, lease).revision, 2)
        self.assertEqual(self.counts()["pokemon_friendship_observations"], 6)
        self.assertEqual(FriendshipObservations(self.store).read_current(f.players[0].player_id, lease, 1)["handler_history"], "unknown")
        self.store.integrity_check()


class FriendshipObservationMigrationTests(unittest.TestCase):
    def test_all_six_migration_orders_reopen_and_each_backup_keeps_prior_capabilities(self):
        operations = (enable_battle_reservations, enable_reset_attempts, enable_friendship_observations)
        with TemporaryDirectory() as temp:
            root = Path(temp)
            for case, order in enumerate(permutations(operations)):
                path = root / str(case)
                with self.subTest(order=[f.__name__ for f in order]):
                    with TradeCheckpointStore(path, "build", "rules") as store:
                        for index, operation in enumerate(order):
                            prior_schema = set(store._schema)
                            backup = root / f"{case}-{index}-backup"
                            self.assertTrue(operation(store, backup))
                            with TradeCheckpointStore(backup, "build", "rules") as restored:
                                self.assertEqual(set(restored._schema), prior_schema)
                        self.assertEqual(store._schema_version, 703)
                    with TradeCheckpointStore(path, "build", "rules") as reopened:
                        self.assertTrue(reopened.battle_reservations_enabled)
                        self.assertTrue(reopened.reset_attempts_enabled)
                        self.assertTrue(reopened.friendship_observations_enabled)
                        reopened.integrity_check()

    def test_ownership_only_world_keeps_its_existing_extensions_and_refuses_friendship_migration(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            with OwnershipCheckpointStore(root / "owned", "build", "rules") as store:
                enable_battle_reservations(store, root / "battle-before")
                enable_reset_attempts(store, root / "reset-before")
                with self.assertRaises(StorageError):
                    enable_friendship_observations(store, root / "unsupported")
                self.assertEqual(store._schema_version, 302)
                self.assertFalse(store.friendship_observations_enabled)
            with OwnershipCheckpointStore(root / "owned", "build", "rules") as reopened:
                self.assertTrue(reopened.battle_reservations_enabled)
                self.assertTrue(reopened.reset_attempts_enabled)


if __name__ == "__main__":
    unittest.main()
