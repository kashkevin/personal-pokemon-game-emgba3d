from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4
from emerald_multiplayer.reset_attempts import ResetAttempts, enable_reset_attempts
from emerald_multiplayer.battle_reservations import enable_battle_reservations
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE
from emerald_multiplayer.ownership_storage import OwnershipCheckpointStore
from emerald_multiplayer.trade_storage import TradeCheckpointStore
from emerald_multiplayer.storage import StorageError
from emerald_multiplayer.reset_protocol import validate_reset_request
from emerald_multiplayer.reset_mailbox import ResetRequest, validate_reset_manifest
from emerald_multiplayer.protocol import ProtocolError
from test_ownership_storage import source_flash, owned_flash


def _commit_then_exit_without_closing(path, player, credential):
    import os
    store = TradeCheckpointStore(path, "build", "rules")
    store.begin_server_boot()
    lease = store.acquire_lease(player, credential)
    ResetAttempts(store).begin(player, lease, dict(type="reset_begin", request_id=str(uuid4()),
        session_epoch=lease, incarnation=1, sequence=1, encounter_id=0x1009, observed_count=0))
    os._exit(77)  # Exercise committed WAL recovery without SQLite/store cleanup.


class ResetAttemptTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = TradeCheckpointStore(self.root / "world", "build", "rules")
        enable_reset_attempts(self.store, self.root / "backup")
        self.store.begin_server_boot()
        self.player = self.store.create_player("Owner")
        self.lease = self.store.acquire_lease(self.player.player_id, self.player.credential)
        self.store.enroll_player(self.player.player_id, source_flash())
        grant = self.store.reserve_instances(self.player.player_id, self.lease, str(uuid4()), 0, 1, 32)
        self.head = self.store.commit_checkpoint(self.player.player_id, self.lease, str(uuid4()), 0,
            owned_flash(grant), "build", "rules", OWNERSHIP_PROFILE)
        self.attempts = ResetAttempts(self.store)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def request(self, sequence=1, observed=0):
        return dict(type="reset_begin", request_id=str(uuid4()), session_epoch=self.lease,
            incarnation=1, sequence=sequence, encounter_id=0x1001, observed_count=observed)

    def begin(self, request):
        return self.attempts.begin(self.player.player_id, self.lease, request)

    def test_retry_is_exact_and_does_not_change_checkpoint_owned_bytes(self):
        request = self.request()
        first = self.begin(request)
        self.assertEqual(first["attempt"], 1)
        self.assertEqual(self.begin(request), first)
        self.assertEqual(self.begin(self.request(2, 1))["attempt"], 2)
        self.assertEqual(self.store.read_checkpoint(self.player.player_id, self.lease), self.head)
        self.store.integrity_check()

    def test_same_native_request_cannot_obtain_second_number_via_new_rpc_id(self):
        request = self.request()
        self.begin(request)
        with self.assertRaises(StorageError):
            self.begin({**request, "request_id": str(uuid4())})
        with self.assertRaises(StorageError):
            self.begin({**request, "observed_count": 1})
        self.assertEqual(self.begin(self.request(2, 1))["attempt"], 2)

    def test_stale_leases_and_counter_ahead_are_refused(self):
        with self.assertRaisesRegex(StorageError, "exceeds"):
            self.begin(self.request(observed=1))
        self.store.release_lease(self.player.player_id, self.lease)
        with self.assertRaises(StorageError):
            self.begin(self.request())

    def test_host_restart_retains_count_and_can_reconcile_an_older_native_save(self):
        self.begin(self.request())
        self.store.close()
        self.store = TradeCheckpointStore(self.root / "world", "build", "rules")
        self.store.begin_server_boot()
        self.lease = self.store.acquire_lease(self.player.player_id, self.player.credential)
        self.attempts = ResetAttempts(self.store)
        self.assertEqual(self.begin(self.request())["attempt"], 2)
        self.store.integrity_check()
        self.store.release_lease(self.player.player_id, self.lease)
        self.store.backup(self.root / "retained")
        with TradeCheckpointStore(self.root / "retained", "build", "rules") as restored:
            self.assertTrue(restored.reset_attempts_enabled)
            self.assertEqual(restored._connection.execute("SELECT COUNT(*) FROM personal_reset_attempts").fetchone()[0], 2)

    def test_committed_attempt_survives_abrupt_host_process_exit(self):
        import multiprocessing
        self.store.close()
        process = multiprocessing.get_context("spawn").Process(target=_commit_then_exit_without_closing,
            args=(self.root/"world", self.player.player_id, self.player.credential))
        process.start()
        process.join(20)
        if process.is_alive():
            process.terminate(); process.join(5)
        self.assertEqual(process.exitcode, 77)
        process.close()
        self.store = TradeCheckpointStore(self.root/"world", "build", "rules")
        self.store.begin_server_boot()
        self.lease = self.store.acquire_lease(self.player.player_id, self.player.credential)
        self.attempts = ResetAttempts(self.store)
        self.assertEqual(self.begin({**self.request(), "encounter_id": 0x1009})["attempt"], 2)
        self.assertEqual(self.store.read_checkpoint(self.player.player_id, self.lease), self.head)
        self.store.integrity_check()

    def test_corrupt_counter_receipt_fails_closed_on_reopen(self):
        self.begin(self.request())
        self.store._connection.execute("UPDATE personal_reset_attempts SET sha256=?", ("0"*64,))
        with self.assertRaises(StorageError):
            self.store.integrity_check()

    def test_a_second_player_has_an_independent_count(self):
        self.begin(self.request())
        p = self.store.create_player("Friend")
        lease = self.store.acquire_lease(p.player_id, p.credential)
        self.store.enroll_player(p.player_id, source_flash(personalities=(9,)))
        grant = self.store.reserve_instances(p.player_id, lease, str(uuid4()), 0, 2, 32)
        self.store.commit_checkpoint(p.player_id, lease, str(uuid4()), 0,
            owned_flash(grant, personalities=(9,)), "build", "rules", OWNERSHIP_PROFILE)
        request = {**self.request(), "session_epoch": lease, "incarnation": 2}
        self.assertEqual(self.attempts.begin(p.player_id, lease, request)["attempt"], 1)
        self.assertEqual(self.begin(self.request(2, 1))["attempt"], 2)

    def test_catalogue_sources_keep_separate_durable_histories_for_one_player(self):
        from emerald_multiplayer.reset_protocol import ENCOUNTERS
        for sequence, encounter in enumerate(sorted(ENCOUNTERS), 1):
            request = {**self.request(sequence), "encounter_id": encounter}
            self.assertEqual(self.begin(request)["attempt"], 1)
            self.assertEqual(self.begin(request)["attempt"], 1)
        self.assertEqual(self.begin({**self.request(len(ENCOUNTERS) + 1, 1), "encounter_id": 0x1009})["attempt"], 2)
        self.assertEqual(self.store.read_checkpoint(self.player.player_id, self.lease), self.head)
        self.store.integrity_check()


class ResetMigrationTests(unittest.TestCase):
    def test_migrations_compose_in_both_orders_and_backups_reopen(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for cls, base in ((OwnershipCheckpointStore, 2), (TradeCheckpointStore, 3)):
                for reset_first in (False, True):
                    prefix = root / f"{base}-{reset_first}"
                    with cls(prefix, "build", "rules") as store:
                        first, second = ((enable_reset_attempts, enable_battle_reservations) if reset_first
                            else (enable_battle_reservations, enable_reset_attempts))
                        first(store, str(prefix)+".before1")
                        second(store, str(prefix)+".before2")
                        self.assertEqual(store._schema_version, 300+base)
                        self.assertTrue(store.battle_reservations_enabled)
                        self.assertTrue(store.reset_attempts_enabled)
                    with cls(prefix, "build", "rules") as reopened:
                        reopened.integrity_check()
                    for suffix in (".before1", ".before2"):
                        with cls(str(prefix)+suffix, "build", "rules") as backup:
                            backup.integrity_check()

    def test_legacy_open_does_not_migrate_and_active_character_cannot_migrate(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with TradeCheckpointStore(root/"world", "build", "rules") as store:
                self.assertFalse(store.reset_attempts_enabled)
                store.begin_server_boot()
                p = store.create_player("Owner")
                store.acquire_lease(p.player_id, p.credential)
                with self.assertRaises(StorageError):
                    enable_reset_attempts(store, root/"backup")
                self.assertFalse((root/"backup").exists())


class ResetWireTests(unittest.TestCase):
    def test_wire_refuses_other_sources_bool_padding_and_count_regression(self):
        request = ResetRequest(1, 2, 3, 0x1001, 4)
        self.assertEqual(ResetRequest.unpack(request.pack()), request)
        self.assertEqual(len(request.reply(5)), 32)
        for raw in (request.pack()[:-1], request.pack()[:-1]+b"x"):
            with self.assertRaises(ValueError): ResetRequest.unpack(raw)
        with self.assertRaises(ValueError): request.reply(4)
        with self.assertRaises(ValueError): ResetRequest(True, 2, 3, 0x1001, 0).pack()
        value = dict(type="reset_begin", request_id=str(uuid4()), session_epoch=1,
                     incarnation=1, sequence=1, encounter_id=0xD001, observed_count=0)
        with self.assertRaises(ProtocolError): validate_reset_request(value, 1)

    def test_manifest_rejects_overlap_partial_and_foreign_marker(self):
        manifest = dict(rom_size=1024, mailbox_address=0x02000000, reset_abi_version=1,
            reset_abi_address=0x08000100, reset_mailbox_address=0x02001000, reset_mailbox_size=128,
            ownership_abi_version=1, save_abi_version=1, save_profile=OWNERSHIP_PROFILE)
        self.assertTrue(validate_reset_manifest(manifest))
        for changed in ({"reset_mailbox_address": 0x02000004}, {"reset_abi_version": True}, {"reset_abi_address": 0x08000400}):
            with self.assertRaises(ValueError): validate_reset_manifest({**manifest, **changed})
