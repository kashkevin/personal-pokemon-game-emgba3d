"""The copies of world saves kept on this PC (save_copies.py; KNOWN_ISSUES MS-216, the owner's choice of 2026-11-17,
docs/owner-decisions.md #72): restoring a character from a kept copy is checked first (character_play.account_save, the
code that brings a world's character back when the game's own save is not that account's), then the newest 40 copies
of each world account kept, the restore giving the same save after the cleanup as before, and the world keeping every
save. The copies are written by the real writer (live_checkpoint's _save_pending and _finish_pending)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from emerald_multiplayer.character_library import CharacterLibrary
from emerald_multiplayer.character_links import profile_directory
from emerald_multiplayer.character_play import account_save, record_after_session
from emerald_multiplayer.flash import OWNERSHIP_LAYOUT_ID
from emerald_multiplayer.live_checkpoint import LiveCheckpointCoordinator
from emerald_multiplayer.ownership_storage import AllocationGrant
from emerald_multiplayer.save_copies import KEEP_SAVE_COPIES, prune_all_accounts, prune_save_copies, save_copies
from test_ownership_storage import owned_flash, source_flash


class Account:
    """A world account's folder on this PC with the saves its world acknowledged."""

    def __init__(self, root, world_id=None, player_id=None):
        self.world_id, self.player_id = world_id or str(uuid4()), player_id or str(uuid4())
        self.folder = profile_directory(root, self.world_id, self.player_id)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.grant = AllocationGrant(self.world_id, self.player_id, str(uuid4()), 1, 33, 1, 1, 0)
        self.writer = object.__new__(LiveCheckpointCoordinator)       # only its files: directory and pending path
        self.writer.directory, self.writer.pending_path = self.folder, self.folder / "pending-export.json"
        self.payloads, self.operations = {}, {}

    def begin(self, revision):
        """The export of the save that becomes ``revision``: its bytes and journal written, not yet acknowledged."""
        payload = owned_flash(self.grant, personalities=(111111,), counter=revision + 1)
        operation = str(uuid4())
        sha256 = hashlib.sha256(payload).hexdigest()
        intent = {"schema": 1, "world_id": self.world_id, "player_id": self.player_id, "build_id": "b" * 64,
                  "ruleset_id": "rules-v1", "save_profile": OWNERSHIP_LAYOUT_ID, "operation_id": operation,
                  "expected_revision": revision - 1, "sha256": sha256, "size": len(payload)}
        self.writer._save_pending(intent, payload)
        self.payloads[revision], self.operations[revision] = payload, operation
        return intent

    def acknowledge(self, intent):
        metadata = {"revision": intent["expected_revision"] + 1, "request_id": intent["operation_id"],
                    "size": intent["size"], "sha256": intent["sha256"], "build_id": intent["build_id"],
                    "ruleset_id": intent["ruleset_id"], "save_profile": intent["save_profile"]}
        self.writer._finish_pending(intent, metadata, outcome="server-acknowledged-and-ROM-released")

    def save(self, *revisions):
        for revision in revisions:
            self.acknowledge(self.begin(revision))

    def flash(self, revision):
        return self.folder / (self.operations[revision] + ".flash")

    def receipt(self, revision):
        return self.folder / (self.operations[revision] + ".export.json")

    def kept(self):
        """The revisions whose copy (bytes and receipt) is in the folder."""
        return sorted(revision for revision in self.operations
                      if self.flash(revision).exists() and self.receipt(revision).exists())

    def restore(self):
        return account_save(self.folder.parents[2], self.world_id, self.player_id)


class RestoreTests(unittest.TestCase):
    """What the cleanup must never break: a character comes back from the newest copy (today's code, before any
    cleanup)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.account = Account(self.root)
        self.account.save(*range(1, 46))

    def tearDown(self):
        self.temp.cleanup()

    def test_the_newest_copy_comes_back_when_the_games_save_is_not_this_accounts(self):
        account = self.account
        self.assertEqual(account.restore(), account.payloads[45])
        # the game's own save of another account changes nothing
        other = owned_flash(AllocationGrant(str(uuid4()), str(uuid4()), str(uuid4()), 1, 33, 1, 1, 0),
                            personalities=(111111,), counter=90)
        (account.folder / "character.sav").write_bytes(other)
        self.assertEqual(account.restore(), account.payloads[45])
        # the game's own save of this account is the account's save
        own = owned_flash(account.grant, personalities=(111111,), counter=99)
        (account.folder / "character.sav").write_bytes(own)
        self.assertEqual(account.restore(), own)

    def test_a_newest_copy_damaged_or_gone_gives_way_to_the_one_before(self):
        account = self.account
        damaged = bytearray(account.payloads[45])
        damaged[1000] ^= 0xFF
        account.flash(45).write_bytes(bytes(damaged))
        self.assertEqual(account.restore(), account.payloads[44])
        account.flash(45).unlink()
        self.assertEqual(account.restore(), account.payloads[44])

    def test_the_copy_that_comes_back_becomes_the_characters_latest_save(self):
        library = CharacterLibrary(self.root)
        character = library.create(source_flash(personalities=(111111,)))
        updated = record_after_session(self.root, library, character.character_id, self.account.world_id,
                                       self.account.player_id)
        self.assertEqual(updated.sha256, hashlib.sha256(self.account.payloads[45]).hexdigest())
        self.assertEqual(library.save_bytes(updated), self.account.payloads[45])


class PruneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.account = Account(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def prune(self, account=None, **keywords):
        account = account or self.account
        return prune_save_copies(account.folder, account.world_id, account.player_id, **keywords)

    def others(self):
        """Files of the account's folder the cleanup must leave as they are (trades', recoveries', grants, journals)."""
        folder = self.account.folder
        files = {folder / (str(uuid4()) + ".grant.json"): b"{}",
                 folder / (str(uuid4()) + ".recovery.flash"): b"r" * 131072,
                 folder / (str(uuid4()) + ".recovery-intent.json"): b"{}",
                 folder / (str(uuid4()) + ".live-apply.json"): b"{}",
                 folder / (str(uuid4()) + ".flash"): b"t" * 131072,                 # a trade's frozen save: no receipt
                 folder / (str(uuid4()) + ".applied.flash"): b"a" * 131072,
                 folder / (str(uuid4()) + ".canonical.flash"): b"c" * 131072,
                 folder / "pending-trade.json": b"{}",
                 folder / "previous-saves" / "1" / "character.sav": b"p" * 131072,
                 folder / "closed-recoveries" / str(uuid4()) / "completed.json": b"{}"}
        for path, data in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return files

    def test_the_newest_forty_are_kept_and_the_same_save_comes_back(self):
        account = self.account
        account.save(*range(1, 46))
        others = self.others()
        before = account.restore()
        result = self.prune()
        self.assertEqual(result.reason, "pruned")
        self.assertEqual(result.kept, KEEP_SAVE_COPIES)
        self.assertEqual(result.removed, tuple(account.operations[revision] for revision in range(1, 6)))  # oldest first
        self.assertEqual(account.kept(), list(range(6, 46)))
        for revision in range(1, 6):
            self.assertFalse(account.flash(revision).exists() or account.receipt(revision).exists())
        for revision in range(6, 46):
            self.assertEqual(account.flash(revision).read_bytes(), account.payloads[revision])
        for path, data in others.items():
            self.assertEqual(path.read_bytes(), data, path.name)
        self.assertEqual(account.restore(), before)
        # a second run has nothing to do
        self.assertEqual(self.prune().reason, "nothing_to_remove")
        self.assertEqual(account.kept(), list(range(6, 46)))

    def test_fewer_than_forty_copies_are_all_kept(self):
        self.account.save(*range(1, 13))
        self.assertEqual(self.prune().removed, ())
        self.assertEqual(self.account.kept(), list(range(1, 13)))

    def test_nothing_is_removed_while_an_export_is_pending(self):
        account = self.account
        account.save(*range(1, 46))
        intent = account.begin(46)
        result = self.prune()
        self.assertEqual((result.reason, result.removed), ("pending_export", ()))
        self.assertEqual(account.kept(), list(range(1, 46)))
        self.assertTrue(account.flash(46).exists())
        account.acknowledge(intent)                         # the world acknowledged it: the next run removes six
        self.assertEqual(len(self.prune().removed), 6)
        self.assertEqual(account.kept(), list(range(7, 47)))
        self.assertEqual(account.restore(), account.payloads[46])

    def test_nothing_is_removed_when_the_newest_copy_is_not_whole(self):
        account = self.account
        account.save(*range(1, 46))
        account.flash(45).write_bytes(account.payloads[45][:-1] + b"\x00")
        result = self.prune()
        self.assertEqual((result.reason, result.removed), ("newest_not_whole", ()))
        self.assertEqual(account.kept(), list(range(1, 46)))
        account.flash(45).unlink()
        self.assertEqual(self.prune().reason, "newest_not_whole")
        self.assertEqual(len(list(account.folder.glob("*.flash"))), 44)

    def test_copies_it_cannot_read_are_never_counted_or_removed(self):
        account = self.account
        account.save(*range(1, 46))
        account.receipt(3).write_text("{")                                   # a receipt it cannot read
        damaged = bytearray(account.payloads[30])
        damaged[5] ^= 1
        account.flash(30).write_bytes(bytes(damaged))                         # a damaged copy among the newest
        stranger = account.folder / (str(uuid4()) + ".export.json")           # another account's receipt
        record = json.loads(account.receipt(2).read_text())
        record["intent"]["world_id"] = str(uuid4())
        record["intent"]["operation_id"] = stranger.name[:-len(".export.json")]
        stranger.write_text(json.dumps(record))
        stranger.with_name(stranger.name.replace(".export.json", ".flash")).write_bytes(account.payloads[2])
        result = self.prune()
        # kept: 45..31 and 29..5 (40 whole copies); removed: 4, 2 and 1; the unreadable 3 and the damaged 30 stay
        self.assertEqual(result.kept, 40)
        self.assertEqual(result.removed, tuple(account.operations[revision] for revision in (1, 2, 4)))
        self.assertEqual(account.kept(), [3] + list(range(5, 46)))
        self.assertTrue(stranger.exists() and stranger.with_name(stranger.name.replace(".export.json", ".flash")).exists())
        self.assertEqual(account.restore(), account.payloads[45])

    def test_a_receipt_left_without_its_bytes_is_removed_the_next_time(self):
        account = self.account
        account.save(*range(1, 46))
        account.flash(2).unlink()                                            # an earlier run stopped between the two
        self.assertEqual(len(self.prune().removed), 5)
        self.assertFalse(account.receipt(2).exists())
        self.assertEqual(account.kept(), list(range(6, 46)))

    def test_a_folder_that_grew_before_is_thinned_a_few_at_a_time(self):
        account = self.account
        account.save(*range(1, 56))
        first = self.prune(limit=10)
        self.assertEqual(first.removed, tuple(account.operations[revision] for revision in range(1, 11)))
        self.assertEqual(account.kept(), list(range(11, 56)))
        self.assertEqual(len(self.prune(limit=10).removed), 5)
        self.assertEqual(account.kept(), list(range(16, 56)))
        self.assertEqual(account.restore(), account.payloads[55])

    def test_every_world_account_on_this_pc_at_start_up(self):
        self.account.save(*range(1, 46))
        second = Account(self.root, world_id=self.account.world_id)           # another account of the same world
        second.save(*range(1, 44))
        third = Account(self.root)                                           # another world
        third.save(*range(1, 4))
        (self.root / "players" / "not-a-world" / str(uuid4())).mkdir(parents=True)
        results = prune_all_accounts(self.root)
        self.assertEqual(len(results[(self.account.world_id, self.account.player_id)].removed), 5)
        self.assertEqual(len(results[(second.world_id, second.player_id)].removed), 3)
        self.assertEqual(results[(third.world_id, third.player_id)].removed, ())
        self.assertEqual(len(results), 3)
        self.assertEqual((self.account.kept(), second.kept(), third.kept()),
                         (list(range(6, 46)), list(range(4, 44)), [1, 2, 3]))

    def test_the_receipts_listed_newest_first(self):
        self.account.save(*range(1, 6))
        self.assertEqual([copy.revision for copy in save_copies(self.account.folder, self.account.world_id,
                                                                  self.account.player_id)], [5, 4, 3, 2, 1])

    def test_at_least_one_copy_is_always_kept(self):
        self.account.save(1, 2)
        with self.assertRaises(ValueError):
            self.prune(keep=0)
        self.assertEqual(self.account.kept(), [1, 2])


class WorldKeepsEverySaveTests(unittest.IsolatedAsyncioTestCase):
    """The real export lifecycle (live_checkpoint with the strict in-memory game and the real world store of
    test_live_checkpoint): the PC keeps the newest copies, the world every save."""

    async def test_the_world_keeps_every_save_while_the_pc_keeps_the_newest(self):
        from test_flash import make_flash
        from test_live_checkpoint import FakeCompanion
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            companion = FakeCompanion(directory)
            try:
                coordinator = LiveCheckpointCoordinator(companion, directory / "live")
                companion.pending_journal = coordinator.pending_path
                saves = {}
                for counter in range(10, 18):
                    companion.rom_flash = make_flash(counter=counter)
                    result = await coordinator.checkpoint(expected_revision=companion.head().revision)
                    saves[result.metadata["revision"]] = (result.operation_id, companion.rom_flash)
                pruned = prune_save_copies(coordinator.directory, companion.world_id, companion.config.player_id, keep=5)
                self.assertEqual(len(pruned.removed), 3)
                kept = sorted(saves)[-5:]
                for revision, (operation, payload) in saves.items():
                    present = (coordinator.directory / (operation + ".flash")).exists()
                    self.assertEqual(present, revision in kept, revision)
                    if present:
                        self.assertEqual((coordinator.directory / (operation + ".flash")).read_bytes(), payload)
                    # the world still holds every save, whatever this PC keeps
                    stored = companion.store.read_checkpoint(companion.config.player_id, companion.session_epoch,
                                                            revision=revision)
                    self.assertEqual(stored.payload, payload)
                self.assertEqual(companion.head().revision, 9)
            finally:
                companion.close()


if __name__ == "__main__":
    unittest.main()
