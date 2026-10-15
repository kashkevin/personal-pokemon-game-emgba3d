"""Update 23: databases written by older builds open with the current code, keep their data, and behave.

The fixtures under tests/fixtures/compat are written by tools/compat/ with the code of an older checkout (Update 14, before the
catch verdicts, the Battle Frontier prizes and the free-for-all). Each test copies them to a temporary folder first: the
committed files are never opened for writing, and one test proves their bytes did not change.
"""
from __future__ import annotations

import hashlib
import random
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from emerald_multiplayer.shared_world import SharedWorld

FIXTURES = Path(__file__).parent / "fixtures" / "compat"
U14 = FIXTURES / "shared_world_u14"
DB = "world.sqlite3.shared-world.sqlite3"
WORLD = "11111111-1111-4111-8111-111111111111"
A, B, C = ("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", "cccccccc-cccc-4ccc-8ccc-cccccccccccc")
CATALOGUE = {
    "rare": [{"name": "ABSOL", "species": 359, "types": ["dark"]}],
    "legendary": [{"name": "GROUDON", "species": 383, "types": ["ground"]}],
    "mega": [{"name": "VENUSAUR", "species": 3, "types": ["grass"], "mega": True, "held_item": 576}],
    "mythical": [], "mega_legendary": [],
}
LOCATIONS = [{"name": "ROUTE 101", "map_group": 0, "map_number": 16, "x": 10, "y": 7, "min_level": 0, "themes": ["normal"]}]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Clock:
    now = 5000.0

    def __call__(self):
        return self.now


class SharedWorldFromUpdate14(unittest.TestCase):
    def setUp(self):
        self.original = {p.name: digest(p) for p in U14.iterdir()}
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / "copy"
        shutil.copytree(U14, self.folder)            # the backup the migration test works on
        self.path = self.folder / DB
        self.clock = Clock()

    def tearDown(self):
        # the committed fixture is untouched whatever the test did
        self.assertEqual({p.name: digest(p) for p in U14.iterdir()}, self.original)

    def open(self):
        return SharedWorld(self.path, WORLD, clock=self.clock, rng=random.Random(5), event_catalogue=CATALOGUE,
                           locations=LOCATIONS, event_condition_chance=0.0)

    def rows(self, table):
        with sqlite3.connect(self.path) as db:
            return db.execute(f"SELECT * FROM {table}").fetchall()

    def test_the_old_database_opens_and_its_catches_are_still_recorded(self):
        before = self.rows("event_resolutions")
        world = self.open()
        self.addCleanup(world.close)
        resolutions = world.resolutions()
        self.assertEqual(len(resolutions), 2)
        self.assertEqual({r["winner"] for r in resolutions}, {A, B})
        self.assertEqual(self.rows("event_resolutions")[:len(before)], before)   # nothing rewritten

    def test_a_repeated_report_from_the_old_winner_is_still_consumed_and_nobody_else_wins(self):
        world = self.open()
        self.addCleanup(world.close)
        by_winner = {r["winner"]: r["event_id"] for r in world.resolutions()}
        self.assertEqual(world.event_result(A, by_winner[A], "caught", "A"), "consumed")
        self.assertEqual(world.event_result(C, by_winner[A], "caught", "C"), "gone")
        self.assertEqual(world.event_result(A, by_winner[B], "caught", "A"), "gone")
        self.assertEqual(len(world.resolutions()), 2)                       # still exactly two owners

    def test_the_catch_verdict_tables_appear_and_an_old_catch_gets_exactly_one_keep(self):
        world = self.open()
        self.addCleanup(world.close)
        winner_event = {r["winner"]: r["event_id"] for r in world.resolutions()}[A]
        first = world.catch_verdict(winner_event, A)
        second = world.catch_verdict(winner_event, A)
        self.assertEqual((first, second), ("keep", "keep"))
        self.assertEqual(len([r for r in self.rows("event_verdicts") if r[1] == A]), 1)

    def test_an_event_that_was_claimed_but_not_caught_can_still_be_caught_once_after_the_upgrade(self):
        world = self.open()
        self.addCleanup(world.close)
        with sqlite3.connect(self.path) as db:
            open_events = [r[0] for r in db.execute("SELECT event_id FROM events WHERE state NOT IN ('caught','closed','expired')")]
        self.assertEqual(len(open_events), 1)
        event = open_events[0]
        self.assertEqual(world.event_result(A, event, "caught", "A"), "consumed")      # A claimed it before the upgrade
        self.assertEqual(world.event_result(B, event, "caught", "B"), "gone")
        self.assertEqual(len(world.resolutions()), 3)
        world.close()
        again = self.open()
        self.addCleanup(again.close)
        self.assertEqual(len(again.resolutions()), 3)                                 # a restart repeats the answer
        self.assertEqual(again.event_result(A, event, "caught", "A"), "consumed")

    def test_the_new_tables_are_added_and_no_old_table_is_altered(self):
        with sqlite3.connect(self.path) as db:
            old = dict(db.execute("SELECT name, sql FROM sqlite_master WHERE type='table'"))
        world = self.open()
        world.close()
        with sqlite3.connect(self.path) as db:
            new = dict(db.execute("SELECT name, sql FROM sqlite_master WHERE type='table'"))
        for name, sql in old.items():
            self.assertEqual(new[name], sql, f"table {name} was altered by opening it with the current code")
        added = set(new) - set(old)
        self.assertTrue({"event_verdicts", "frontier_bp", "frontier_rewards", "frontier_purchases", "frontier_bring"} <= added, added)

    def test_reopening_many_times_does_not_grow_the_database_or_change_the_data(self):
        world = self.open()
        world.close()
        size = self.path.stat().st_size
        snapshot = (self.rows("event_resolutions"), self.rows("events"))
        for _ in range(30):
            world = self.open()
            world.close()
        self.assertEqual((self.rows("event_resolutions"), self.rows("events")), snapshot)
        self.assertLessEqual(self.path.stat().st_size, size + 8192)


if __name__ == "__main__":
    unittest.main()
