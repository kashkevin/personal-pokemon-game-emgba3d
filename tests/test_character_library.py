"""The character library (character_library.py) and bringing earlier characters into it (character_migration.py)."""
from __future__ import annotations

import calendar
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
import unittest.mock
import uuid

from emerald_multiplayer.character_library import CharacterLibrary, LibraryError, read_save, trainer_name
from emerald_multiplayer.character_links import CharacterLinks
from emerald_multiplayer.character_migration import migrate_characters, recover_draft, recoverable_drafts
from test_ownership import PLAYER_ID, WORLD_ID, make_ownership_flash
from test_ownership_storage import source_flash


class Clock:
    def __init__(self):
        self.now = 1_800_000_000.0

    def __call__(self):
        self.now += 1
        return self.now


def tree(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(root).rglob("*")) if p.is_file()}


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.clock = Clock()
        self.library = CharacterLibrary(self.root, clock=self.clock)

    def test_the_trainer_name_reads_like_the_game(self):
        self.assertEqual(trainer_name(bytes([0xCE, 0xBF, 0xCD, 0xCE])), "TEST")
        self.assertEqual(trainer_name(bytes([0xC5, 0xD9, 0xEA, 0x00, 0xA2])), "Kev 1")
        self.assertEqual(trainer_name(b""), "Trainer")

    def test_a_new_character_is_stable_active_and_keeps_its_save(self):
        draft = source_flash(personalities=(7,))
        character = self.library.create(draft)
        self.assertEqual((character.name, character.trainer_id, character.world_id), ("TEST", 0x12345678, None))
        self.assertEqual(self.library.active().character_id, character.character_id)
        self.assertEqual(self.library.save_bytes(character), draft)
        again = CharacterLibrary(self.root, clock=self.clock)              # a restart reads the same character
        self.assertEqual(again.get(character.character_id).sha256, character.sha256)

    def test_a_world_save_becomes_the_latest_and_the_previous_goes_to_history(self):
        character = self.library.create(source_flash(personalities=(7,)))
        owned = make_ownership_flash(records=(("party:0", 1),), personalities=(7,))
        updated = self.library.record_world_save(character.character_id, WORLD_ID, PLAYER_ID, owned)
        self.assertEqual((updated.world_id, updated.player_id, updated.sha256), (WORLD_ID, PLAYER_ID, hashlib.sha256(owned).hexdigest()))
        self.assertEqual(updated.accounts, {WORLD_ID: PLAYER_ID})
        self.assertEqual(self.library.binding(WORLD_ID, PLAYER_ID), (character.character_id, updated.sha256))
        history = self.library.history(updated)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].read_bytes(), source_flash(personalities=(7,)))
        restored = self.library.restore(updated, history[0])
        self.assertIsNone(restored.world_id)
        self.assertEqual(len(self.library.history(restored)), 2)          # restoring keeps the newer save too

    def test_a_save_of_another_world_or_trainer_is_refused(self):
        character = self.library.create(source_flash(personalities=(7,)))
        owned = make_ownership_flash(records=(("party:0", 1),), personalities=(7,))
        with self.assertRaises(LibraryError) as caught:
            self.library.record_world_save(character.character_id, str(uuid.uuid4()), PLAYER_ID, owned)
        self.assertEqual(caught.exception.code, "wrong_world")
        with self.assertRaises(LibraryError):
            self.library.create(b"junk")

    def test_a_changed_save_on_disk_is_reported_and_left_alone(self):
        character = self.library.create(source_flash(personalities=(7,)))
        character.save_path.write_bytes(b"\0" * 131072)
        self.assertEqual(self.library.all(), [])
        self.assertEqual(self.library.damaged, {character.character_id: "save changed"})
        self.assertTrue(character.save_path.exists())

    def test_delete_moves_the_folder_and_never_destroys_it(self):
        character = self.library.create(source_flash(personalities=(7,)))
        target = self.library.delete(character.character_id)
        self.assertTrue((target / "current.sav").is_file())
        self.assertIsNone(self.library.get(character.character_id))
        self.assertIsNone(self.library.active())

    def test_several_characters_and_explicit_choice(self):
        first = self.library.create(source_flash(personalities=(7,)))
        second = self.library.create(source_flash(personalities=(8,)))
        self.assertEqual(self.library.active().character_id, first.character_id)
        self.library.set_active(second.character_id)
        self.assertEqual(CharacterLibrary(self.root, clock=self.clock).active().character_id, second.character_id)
        self.library.rename(first.character_id, "Kev")
        self.assertEqual(self.library.get(first.character_id).name, "Kev")


class SetClock:
    """A PC clock the test sets: a minute passes at every reading, and it can be set back."""

    def __init__(self, now):
        self.now = now

    def __call__(self):
        self.now += 60
        return self.now


class HistoryClockTests(unittest.TestCase):
    """KNOWN_ISSUES MS-218: the earlier versions kept when the PC's clock goes back (set back by hand, a flat clock battery).

    The history is pruned and listed by name, and names start with the clock's UTC time: a clock set back named every new
    entry before the ones already there, so the newest versions, and a copy the player had just made with Back up now, were
    the first ones deleted."""

    LIMIT = 5

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        limit = unittest.mock.patch("emerald_multiplayer.character_library.HISTORY_LIMIT", self.LIMIT)
        limit.start()
        self.addCleanup(limit.stop)
        self.clock = SetClock(1_800_000_000.0)                             # 2027-01-15
        self.library = CharacterLibrary(Path(self.temp.name), clock=self.clock)
        self.previous = source_flash(personalities=(7,))
        self.character = self.library.create(self.previous)
        self.written = []                                                   # each history entry's save, in writing order

    def save(self, counter):
        payload = make_ownership_flash(counter=counter, records=(("party:0", 1),), personalities=(7,))
        self.character = self.library.record_world_save(self.character.character_id, WORLD_ID, PLAYER_ID, payload)
        self.written.append(self.previous)
        self.previous = payload

    def kept(self):
        """The history's saves as the restore list shows them (newest first)."""
        return [path.read_bytes() for path in self.library.history(self.character)]

    def test_versions_written_after_the_clock_went_back_are_kept_newest_first(self):
        for counter in range(2, 2 + self.LIMIT + 2):                        # the history full, its oldest pruned
            self.save(counter)
        self.assertEqual(self.kept(), self.written[::-1][:self.LIMIT])
        self.clock.now -= 365 * 86400                                       # the clock set back a year
        for counter in range(100, 103):
            self.save(counter)
        self.assertEqual(self.kept(), self.written[::-1][:self.LIMIT])     # the three newest kept, the oldest pruned
        names = [path.name for path in self.library.history(self.character)]
        self.assertEqual(names, sorted(names, reverse=True))

    def test_a_copy_made_with_back_up_now_after_the_clock_went_back_survives_the_next_saves(self):
        for counter in range(2, 2 + self.LIMIT + 2):
            self.save(counter)
        self.clock.now -= 30 * 86400                                        # the clock set back a month
        backup = self.library.backup_now(self.character)
        backed_up = self.previous
        for counter in range(100, 100 + self.LIMIT - 1):                    # the copy is not yet among the oldest
            self.save(counter)
        self.assertTrue(backup.exists())
        self.assertEqual(backup.read_bytes(), backed_up)
        self.save(200)                                                      # now it is the oldest of the five: pruned
        self.assertFalse(backup.exists())

    def test_back_up_now_pressed_twice_keeps_one_copy(self):
        self.save(2)
        first = self.library.backup_now(self.character)
        second = self.library.backup_now(self.character)
        self.assertEqual(first, second)
        self.assertEqual([path.name.endswith("-backup.sav") for path in self.library.history(self.character)], [True, False])
        self.save(3)                                                        # a new save: Back up now copies that one
        third = self.library.backup_now(self.character)
        self.assertNotEqual(third, first)
        self.assertEqual(third.read_bytes(), self.previous)

    def test_names_follow_the_clock_while_it_goes_forward(self):
        for counter in range(2, 6):
            self.save(counter)
        seconds = [calendar.timegm(time.strptime(path.name[:16], "%Y%m%dT%H%M%SZ"))
                   for path in self.library.history(self.character)]
        # each name is a reading of this clock (whole minutes from its start), none moved past the one before it
        self.assertEqual([second % 60 for second in seconds], [0] * 4)
        self.assertEqual(seconds, sorted(seconds, reverse=True))
        self.assertLessEqual(seconds[0], self.clock.now)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.clock = Clock()

    def account(self, world=WORLD_ID, player=PLAYER_ID, payload=None):
        folder = self.root / "players" / world / player
        folder.mkdir(parents=True)
        (folder / "character.sav").write_bytes(payload or make_ownership_flash(records=(("party:0", 1),), personalities=(7,)))
        (folder / "invitation.json").write_text("{}")
        return folder

    def draft(self, personality, name="d"):
        folder = self.root / "drafts" / str(uuid.uuid4())
        folder.mkdir(parents=True)
        (folder / "character.sav").write_bytes(source_flash(personalities=(personality,)))
        return folder / "character.sav"

    def test_world_characters_and_the_recorded_draft_are_imported_and_originals_untouched(self):
        self.account()
        recorded = self.draft(11)
        self.draft(12)
        self.draft(13)
        links = CharacterLinks(self.root, clock=self.clock)
        other_world, other_player = str(uuid.uuid4()), str(uuid.uuid4())
        links.ensure(other_world, other_player, "friend", 1, "Sam's server", "Player 2")
        links.set_stage(other_world, other_player, "draft",
                        {"source": str(recorded), "sha256": hashlib.sha256(recorded.read_bytes()).hexdigest()})
        before = tree(self.root / "players"), tree(self.root / "drafts")
        library = CharacterLibrary(self.root, clock=self.clock)
        result = migrate_characters(self.root, library, links)
        self.assertEqual(len(result.imported), 2)
        characters = library.all()
        world_character = next(c for c in characters if c.world_id == WORLD_ID)
        self.assertEqual(library.binding(WORLD_ID, PLAYER_ID)[0], world_character.character_id)
        recovered = next(c for c in characters if c.world_id is None)
        self.assertEqual(recovered.accounts, {other_world: other_player})
        self.assertEqual((tree(self.root / "players"), tree(self.root / "drafts")), before)
        self.assertEqual(migrate_characters(self.root, library, links).imported, [])          # once only
        drafts = recoverable_drafts(self.root, library)
        self.assertEqual(len(drafts), 2)                                                       # the other attempts wait
        recover_draft(library, drafts[0])
        self.assertEqual(len(recoverable_drafts(self.root, library)), 1)

    def test_an_unreadable_world_save_is_reported_not_imported(self):
        self.account(payload=b"\0" * 1000)
        library = CharacterLibrary(self.root, clock=self.clock)
        result = migrate_characters(self.root, library, None)
        self.assertEqual(result.imported, [])
        self.assertEqual(len(result.problems), 1)


if __name__ == "__main__":
    unittest.main()
