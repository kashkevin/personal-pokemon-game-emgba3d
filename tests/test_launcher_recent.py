import json
from pathlib import Path
import tempfile
import unittest

from emerald_multiplayer.launcher_recent import (
    FILE_NAME, FORMAT, MAX_INVITATIONS, RecentStore, continue_target, describe_age,
)


class RecentStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.clock = [1_700_000_000.0]

    def store(self):
        return RecentStore(self.root, clock=lambda: self.clock[0])

    def test_nothing_remembered_on_first_launch(self):
        store = self.store()
        self.assertIsNone(store.last)
        self.assertEqual(store.invitations, ())
        self.assertEqual(continue_target(store), (None, "none"))
        self.assertFalse((self.root / FILE_NAME).exists(), "reading must not create the file")

    def test_a_started_host_session_is_remembered_and_survives_a_restart(self):
        world = self.root / "worlds" / "w-1"
        world.mkdir(parents=True)
        (world / "host.json").write_text("{}")
        self.assertTrue(self.store().record_session("host", world / "host.json", "192.168.1.20", True))
        again = self.store()
        last = again.last
        self.assertEqual((last.mode, last.selection, last.address, last.internet), ("host", world / "host.json", "192.168.1.20", True))
        self.assertEqual(last.world_name, "w-1")
        self.assertEqual(again.world_played(world), self.clock[0])
        self.assertEqual(continue_target(again)[0], last)

    def test_a_moved_world_cannot_be_continued_and_says_why(self):
        store = self.store()
        store.record_session("host", self.root / "gone" / "host.json", "127.0.0.1", False)
        self.assertEqual(continue_target(store), (None, "missing"))

    def test_recent_invitations_are_newest_first_without_repeats_and_capped(self):
        store = self.store()
        paths = [self.root / f"friend-{i}.json" for i in range(MAX_INVITATIONS + 3)]
        for path in paths:
            store.record_session("join", path, "127.0.0.1", False)
        store.record_session("join", paths[-2], "127.0.0.1", False)
        listed = self.store().invitations
        self.assertEqual(len(listed), MAX_INVITATIONS)
        self.assertEqual(listed[0], paths[-2])
        self.assertEqual(len(set(listed)), len(listed))

    def test_damaged_files_are_ignored_and_never_overwritten(self):
        path = self.root / FILE_NAME
        for raw in (b"{", b"[]", json.dumps({"format": "other"}).encode(),
                    json.dumps({"format": FORMAT, "last": {"mode": "evil", "selection": "/x", "address": "a", "internet": False, "played": 1},
                                "invitations": [], "worlds": {}}).encode(),
                    b"x" * 20000):
            path.write_bytes(raw)
            store = self.store()
            self.assertFalse(store.available)
            self.assertIsNone(store.last)
            self.assertFalse(store.record_session("host", self.root / "w" / "host.json", "127.0.0.1", False))
            self.assertEqual(path.read_bytes(), raw, "a file that could not be read is kept as it was")

    def test_relative_paths_and_nul_bytes_are_refused(self):
        path = self.root / FILE_NAME
        record = {"format": FORMAT, "last": {"mode": "join", "selection": "relative.json", "address": "127.0.0.1", "internet": False, "played": 5},
                  "invitations": [], "worlds": {}}
        path.write_text(json.dumps(record))
        self.assertFalse(self.store().available)

    def test_forgetting_clears_only_the_last_session(self):
        store = self.store()
        store.record_session("join", self.root / "friend.json", "127.0.0.1", False)
        self.assertTrue(store.forget_last())
        again = self.store()
        self.assertIsNone(again.last)
        self.assertEqual(again.invitations, (self.root / "friend.json",))

    def test_the_file_holds_no_secret_shaped_field(self):
        store = self.store()
        store.record_session("host", self.root / "w" / "host.json", "127.0.0.1", False)
        keys = set(json.loads((self.root / FILE_NAME).read_text()))
        self.assertEqual(keys, {"format", "last", "invitations", "worlds"})

    def test_age_wording(self):
        now = 10 * 86400.0
        self.assertEqual(describe_age(now - 100, now), "today")
        self.assertEqual(describe_age(now - 86400 - 5, now), "yesterday")
        self.assertEqual(describe_age(now - 3 * 86400 - 5, now), "3 days ago")
        self.assertEqual(describe_age(now - 90 * 86400, now), "3 months ago")


if __name__ == "__main__":
    unittest.main()
