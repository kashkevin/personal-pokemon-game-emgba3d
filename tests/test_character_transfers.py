"""A universal character coming back to a world (character_transfers.py) and retried first sources."""
from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest
import uuid

from emerald_multiplayer.character_transfer import detach_from_world
from emerald_multiplayer.character_transfers import (
    RETIRE_LEFT_WORLD, enable_character_transfers, pending_source, transfer_player,
)
from emerald_multiplayer.ownership_protocol import OWNERSHIP_PROFILE
from emerald_multiplayer.storage import StorageError
from emerald_multiplayer.trade_storage import TradeCheckpointStore, TradeSide
from emerald_multiplayer.trade_flash import build_party_swap
from test_ownership_storage import owned_flash, source_flash

BUILD, RULESET = "transfer-test-ROM-sha256", "baseline-test-rules-v1"


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / "world.sqlite3"
        self.store = TradeCheckpointStore(self.path, BUILD, RULESET)
        self.store.begin_server_boot()
        self.player = self.store.create_player("Kev")
        self.other = self.store.create_player("Sam")
        self.lease = self.store.acquire_lease(self.player.player_id, self.player.credential)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def code(self, code, function, *args, **kwargs):
        with self.assertRaises(StorageError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def grant(self, revision, count=32, player=None, lease=None):
        player = player or self.player
        return self.store.reserve_instances(player.player_id, lease or self.lease, str(uuid.uuid4()), revision, 1, count)

    def commit(self, payload, revision, player=None, lease=None):
        player = player or self.player
        return self.store.commit_checkpoint(player.player_id, lease or self.lease, str(uuid.uuid4()), revision, payload,
                                            BUILD, RULESET, OWNERSHIP_PROFILE)

    def first_character(self):
        """Kev enrolls with one Pokémon (pid 7) and makes checkpoint 1."""
        self.store.enroll_player(self.player.player_id, source_flash(("party:0",), personalities=(7,)))
        grant = self.grant(0)
        self.commit(owned_flash(grant, (("party:0", grant.start),), personalities=(7,)), 0)
        return grant


class RetriedFirstSourceTests(Base):
    def test_an_unfinished_first_source_can_be_replaced_only_when_asked_and_only_before_a_checkpoint(self):
        pid = self.player.player_id
        self.store.enroll_player(pid, source_flash(personalities=(7,)))
        self.code("enrollment_conflict", self.store.enroll_player, pid, source_flash(personalities=(8,)))
        replaced = self.store.enroll_player(pid, source_flash(personalities=(8,)), replace_unconsumed=True)
        self.assertEqual(pending_source(self.store, pid), ("enroll", 0, replaced.source_sha256))
        grant = self.grant(0)
        self.code("enrollment_inventory_mismatch", self.commit, owned_flash(grant, personalities=(7,)), 0)
        self.commit(owned_flash(grant, personalities=(8,)), 0)
        self.code("enrollment_conflict", self.store.enroll_player, pid, source_flash(personalities=(9,)), replace_unconsumed=True)
        self.assertIsNone(pending_source(self.store, pid))
        self.store.integrity_check()

    def test_a_replacement_cannot_take_another_accounts_source(self):
        self.store.enroll_player(self.other.player_id, source_flash(personalities=(9,)))
        self.store.enroll_player(self.player.player_id, source_flash(personalities=(7,)))
        self.code("source_already_enrolled", self.store.enroll_player, self.player.player_id, source_flash(personalities=(9,)),
                  replace_unconsumed=True)


class TransferTests(Base):
    def setUp(self):
        super().setUp()
        self.first = self.first_character()
        self.store.release_lease(self.player.player_id, self.lease)          # worlds are prepared before anyone plays
        self.assertTrue(enable_character_transfers(self.store, self.root / "before-transfers.sqlite3"))
        self.lease = self.store.acquire_lease(self.player.player_id, self.player.credential)
        # The character progressed somewhere else: two Pokémon now (pid 7 kept, pid 21 caught elsewhere), serials of that world.
        elsewhere = owned_flash(self.first, (("party:0", 500), ("box:0:3", 501)), personalities=(7, 21),
                                world_id=str(uuid.uuid4()))
        self.detached = detach_from_world(elsewhere).payload

    def test_a_character_coming_back_starts_a_new_generation_and_its_old_pokemon_leave(self):
        pid = self.player.player_id
        transfer = transfer_player(self.store, pid, self.detached)
        self.assertEqual((transfer.base_revision, transfer.count), (1, 2))
        self.assertEqual(pending_source(self.store, pid), ("transfer", 1, transfer.source_sha256))
        self.assertEqual(transfer_player(self.store, pid, self.detached), transfer)          # a retry is the same transfer
        grant = self.grant(1)
        boundary = owned_flash(grant, (("party:0", grant.start), ("box:0:3", grant.start + 1)), personalities=(7, 21))
        cp = self.commit(boundary, 1)
        self.assertEqual(cp.revision, 2)
        old = self.store._connection.execute("SELECT status, retirement_reason FROM ownership_instances WHERE serial = ?",
                                             (self.first.start,)).fetchone()
        self.assertEqual(tuple(old), ("retired", RETIRE_LEFT_WORLD))
        members = self.store.read_ownership(pid, self.lease)
        self.assertEqual(sorted((m["serial"], m["location"]) for m in members),
                         [(grant.start, "party:0"), (grant.start + 1, "box:0:3")])
        self.assertIsNone(pending_source(self.store, pid))
        # Ordinary play continues in the new generation.
        self.commit(owned_flash(grant, (("box:0:4", grant.start), ("party:0", grant.start + 1)), personalities=(7, 21)), 2)
        self.store.integrity_check()
        self.store.close()
        self.store = TradeCheckpointStore(self.path, BUILD, RULESET)       # reopening replays and audits the whole history
        self.assertTrue(self.store.character_transfers_enabled)
        self.store.integrity_check()

    def test_the_first_checkpoint_after_a_transfer_must_be_exactly_the_transferred_save(self):
        transfer_player(self.store, self.player.player_id, self.detached)
        grant = self.grant(1)
        self.code("ownership_conflict", self.commit,
                  owned_flash(grant, (("party:0", self.first.start), ("box:0:3", grant.start)), personalities=(7, 21)), 1)
        self.code("enrollment_inventory_mismatch", self.commit,
                  owned_flash(grant, (("party:0", grant.start),), personalities=(7,)), 1)
        self.code("invalid_retirement", self.commit,
                  owned_flash(grant, (("party:0", grant.start), ("box:0:3", grant.start + 1)), personalities=(7, 21),
                              retirements=((self.first.start, 1),)), 1)
        self.assertEqual(self.store.read_checkpoint(self.player.player_id, self.lease).revision, 1)
        self.store.integrity_check()

    def test_a_pending_transfer_can_be_replaced_by_a_newer_save(self):
        transfer_player(self.store, self.player.player_id, self.detached)
        newer = detach_from_world(owned_flash(self.first, (("party:0", 500),), personalities=(33,), world_id=str(uuid.uuid4()))).payload
        replaced = transfer_player(self.store, self.player.player_id, newer)
        self.assertEqual(pending_source(self.store, self.player.player_id)[2], replaced.source_sha256)
        grant = self.grant(1)
        self.code("enrollment_inventory_mismatch", self.commit,
                  owned_flash(grant, (("party:0", grant.start), ("box:0:3", grant.start + 1)), personalities=(7, 21)), 1)
        self.commit(owned_flash(grant, (("party:0", grant.start),), personalities=(33,)), 1)
        self.store.integrity_check()

    def test_a_copy_of_a_pokemon_another_trainer_owns_here_is_refused(self):
        lease = self.store.acquire_lease(self.other.player_id, self.other.credential)
        self.store.enroll_player(self.other.player_id, source_flash(personalities=(21,)))
        grant = self.grant(0, player=self.other, lease=lease)
        self.commit(owned_flash(grant, personalities=(21,)), 0, player=self.other, lease=lease)
        self.code("pokemon_owned_here", transfer_player, self.store, self.player.player_id, self.detached)
        self.assertIsNone(pending_source(self.store, self.player.player_id))

    def test_another_accounts_save_and_accounts_without_a_checkpoint_are_refused(self):
        self.code("enrollment_required", transfer_player, self.store, self.other.player_id, self.detached)
        transfer_player(self.store, self.player.player_id, self.detached)
        lease = self.store.acquire_lease(self.other.player_id, self.other.credential)
        self.store.enroll_player(self.other.player_id, source_flash(personalities=(40,)))
        grant = self.grant(0, player=self.other, lease=lease)
        self.commit(owned_flash(grant, personalities=(40,)), 0, player=self.other, lease=lease)
        self.code("source_already_enrolled", transfer_player, self.store, self.other.player_id, self.detached)
        self.code("invalid_enrollment", transfer_player, self.store, self.player.player_id, b"\0" * 131072)

    def test_no_trade_before_the_first_checkpoint_of_a_new_generation(self):
        lease = self.store.acquire_lease(self.other.player_id, self.other.credential)
        self.store.enroll_player(self.other.player_id, source_flash(("party:0", "party:1"), personalities=(50, 51)))
        grant_b = self.grant(0, player=self.other, lease=lease)
        head_b = self.commit(owned_flash(grant_b, (("party:0", grant_b.start), ("party:1", grant_b.start + 1)),
                                         personalities=(50, 51)), 0, player=self.other, lease=lease)
        head_a = self.store.read_checkpoint(self.player.player_id, self.lease)
        transfer_player(self.store, self.player.player_id, self.detached)
        post = build_party_swap(head_a.payload, self.first.start, head_b.payload, grant_b.start)
        sides = [TradeSide(self.player.player_id, self.lease, 1, self.first.start, post[0]),
                 TradeSide(self.other.player_id, lease, 1, grant_b.start, post[1])]
        sides.sort(key=lambda s: s.player_id)
        self.code("transfer_pending", self.store.commit_trade, str(uuid.uuid4()), *sides, BUILD, RULESET, OWNERSHIP_PROFILE)

    def test_tampering_with_a_recorded_transfer_is_detected(self):
        transfer_player(self.store, self.player.player_id, self.detached)
        self.store.close()
        with sqlite3.connect(self.path) as raw:
            raw.execute("UPDATE ownership_transfers SET trainer_id = trainer_id + 1")
        with self.assertRaises(StorageError) as caught:
            self.store = TradeCheckpointStore(self.path, BUILD, RULESET)
        self.assertEqual(caught.exception.code, "storage_corrupt")
        self.store = TradeCheckpointStore(self.root / "fresh.sqlite3", BUILD, RULESET)


class MigrationTests(Base):
    def test_an_existing_world_is_prepared_once_with_a_verified_backup_and_keeps_its_history(self):
        self.first_character()
        self.store.release_lease(self.player.player_id, self.lease)
        self.store.close()
        self.store = TradeCheckpointStore(self.path, BUILD, RULESET)     # an older world: no transfer table
        self.assertFalse(self.store.character_transfers_enabled)
        backup = self.root / "before-transfers.sqlite3"
        self.assertTrue(enable_character_transfers(self.store, backup))
        self.assertTrue(backup.is_file())
        self.assertFalse(enable_character_transfers(self.store, self.root / "again.sqlite3"))
        self.store.close()
        self.store = TradeCheckpointStore(self.path, BUILD, RULESET)
        self.assertTrue(self.store.character_transfers_enabled)
        with TradeCheckpointStore(backup, BUILD, RULESET) as old:
            self.assertFalse(old.character_transfers_enabled)
            self.assertEqual(old.metadata.world_id, self.store.metadata.world_id)

    def test_preparing_a_world_is_refused_while_a_character_is_playing(self):
        self.first_character()
        self.code("lease_active", enable_character_transfers, self.store, self.root / "b.sqlite3")


if __name__ == "__main__":
    unittest.main()
