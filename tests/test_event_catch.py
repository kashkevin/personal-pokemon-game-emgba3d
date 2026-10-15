"""World Event catch ownership (expansion Phase 11): the first valid reported catch wins, decided by the host in the order
reports arrive, recorded durably, replay-safe, and the same across restarts."""
from __future__ import annotations

import json
import random
import sqlite3
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from emerald_multiplayer.balance import BALANCE
from emerald_multiplayer.shared_world import SharedWorld

WORLD = "11111111-1111-4111-8111-111111111111"
CATALOGUE = {
    "rare": [{"name": "ABSOL", "species": 359, "types": ["dark"]}],
    "legendary": [{"name": "GROUDON", "species": 383, "types": ["ground"]}],
    "mega": [{"name": "VENUSAUR", "species": 3, "types": ["grass"], "mega": True, "held_item": 576}],
    "mythical": [], "mega_legendary": [],
}
LOCATIONS = [{"name": "ROUTE 101", "map_group": 0, "map_number": 16, "x": 10, "y": 7, "min_level": 0, "themes": ["normal"]}]


class Clock:
    now = 1000.0

    def __call__(self):
        return self.now


class CatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "w.shared-world.sqlite3"
        self.clock = Clock()
        self.world = self.open()
        self.addCleanup(lambda: self.world.close())
        self.a, self.b, self.c = str(uuid4()), str(uuid4()), str(uuid4())

    def open(self):
        return SharedWorld(self.path, WORLD, clock=self.clock, rng=random.Random(5), event_catalogue=CATALOGUE,
                           locations=LOCATIONS, event_condition_chance=0.0)

    def spawn(self, category="rare"):
        self.world.set_active_players(2)
        return self.world.spawn_event(progression_level=30, category=category)["event_id"]

    def lapse(self, player):
        """The player's claim lapses (a long disconnect) while the event is still on."""
        self.world.player_disconnected(player)
        self.clock.now += BALANCE.event_claim_grace_seconds + 1
        self.world.tick_events(2, lambda: 30)

    def test_the_catcher_is_recorded_with_everything_about_the_pokemon(self):
        event = self.spawn("mega")
        self.world._event.update(shiny=True)
        self.world._save_event("active")
        self.world.claim_event(self.a, event)
        self.assertEqual(self.world.event_result(self.a, event, "caught", "Alice"), "consumed")
        record = self.world.resolutions()[0]
        self.assertEqual((record["event_id"], record["winner"], record["species"], record["shiny"], record["mega"],
                          record["held_item"], record["claimants"], record["category"]),
                         (event, self.a, 3, True, True, 576, [self.a], "mega"))
        self.assertIsNone(self.world.event_view())
        self.assertEqual(self.world.reports(event), [(self.a, "winner")])

    def test_replays_and_repeats_never_make_a_second_catch(self):
        event = self.spawn()
        self.world.claim_event(self.a, event)
        self.assertEqual(self.world.event_result(self.a, event, "caught", "Alice"), "consumed")
        for _ in range(5):                                           # the game's report is re-sent until acknowledged
            self.assertEqual(self.world.event_result(self.a, event, "caught", "Alice"), "consumed")
        self.assertEqual(self.world.event_result(self.b, event, "caught", "Bob"), "gone")
        self.assertEqual(self.world.claim_event(self.b, event), "gone")
        self.assertEqual(len(self.world.resolutions()), 1)
        self.assertEqual(self.world.resolutions()[0]["winner"], self.a)
        self.assertEqual([v for _, v in self.world.reports(event)], ["winner"] + ["replay"] * 5 + ["late"])

    def test_after_a_long_absence_the_first_report_wins_even_though_another_trainer_holds_the_claim(self):
        event = self.spawn()
        self.world.claim_event(self.a, event)
        self.lapse(self.a)                                           # A's game stays in battle offline
        self.assertEqual(self.world.claim_event(self.b, event), "granted")
        self.assertEqual(self.world.event_result(self.a, event, "caught", "Alice"), "consumed")   # A reports first
        self.assertEqual(self.world.event_result(self.b, event, "caught", "Bob"), "gone")         # B's battle ends
        self.assertEqual(self.world.resolutions()[0]["winner"], self.a)
        self.assertEqual(self.world.resolutions()[0]["claimants"], [self.a, self.b])
        self.assertIsNone(self.world.event_view())
        seen = []
        for _ in range(4):
            note = self.world.notice_view()
            if note:
                seen.append((note["text"], note["to"]))
            self.clock.now += BALANCE.notice_seconds + 1
        self.assertTrue(any("caught the" in text and to is None for text, to in seen), seen)       # for everyone
        self.assertTrue(any("caught it first" in text and to == [self.b] for text, to in seen), seen)  # the other battler

    def test_if_the_holder_reports_first_the_holder_wins(self):
        event = self.spawn()
        self.world.claim_event(self.a, event)
        self.lapse(self.a)
        self.world.claim_event(self.b, event)
        self.assertEqual(self.world.event_result(self.b, event, "caught", "Bob"), "consumed")
        self.assertEqual(self.world.event_result(self.a, event, "caught", "Alice"), "gone")
        self.assertEqual(self.world.resolutions()[0]["winner"], self.b)

    def test_a_trainer_who_never_claimed_it_cannot_win_it(self):
        event = self.spawn()
        self.world.claim_event(self.a, event)
        self.assertEqual(self.world.event_result(self.c, event, "caught", "Cy"), "not_claimant")
        self.assertIsNotNone(self.world.event_view())                # still catchable by its claimant
        self.assertEqual(self.world.reports(event), [(self.c, "never_claimed")])
        self.assertEqual(self.world.event_result(self.a, event, "caught", "Alice"), "consumed")

    def test_running_away_and_other_results_stay_the_holders_to_report(self):
        event = self.spawn()
        self.world.claim_event(self.a, event)
        self.assertEqual(self.world.event_result(self.b, event, "ran", "Bob"), "not_claimant")
        self.assertEqual(self.world.event_result(self.a, event, "ran", "Alice"), "released")
        self.assertEqual(self.world.claim_event(self.b, event), "granted")
        self.assertEqual(self.world.resolutions(), [])
        # a past claimant who ran can still win by a late catch
        self.assertEqual(self.world.event_result(self.a, event, "caught", "Alice"), "consumed")

    def test_a_catch_reported_after_the_event_ended_is_logged_and_creates_no_second_owner(self):
        event = self.spawn()
        self.world.claim_event(self.a, event)
        self.clock.now += BALANCE.event_duration_seconds + 5
        self.assertTrue(self.world.tick_events(2, lambda: 30))        # it expired
        self.assertEqual(self.world.event_result(self.a, event, "caught", "Alice"), "gone")
        self.assertEqual(self.world.reports(event), [(self.a, "expired")])
        self.assertEqual(self.world.resolutions(), [])

    def test_the_ledger_survives_a_restart_and_a_stopped_host_closes_a_decided_event(self):
        event = self.spawn()
        self.world.claim_event(self.a, event)
        self.world.event_result(self.a, event, "caught", "Alice")
        second = self.spawn()
        self.world.claim_event(self.b, second)
        self.world._resolve(self.world._event, self.b)                  # decided, then the host stopped before closing it
        self.world._db.close()
        self.world._db = None
        again = self.open()
        self.addCleanup(again.close)
        self.assertEqual([(r["event_id"], r["winner"]) for r in again.resolutions()], [(second, self.b), (event, self.a)])
        self.assertIsNone(again.event_view())                           # the decided event did not come back
        self.assertEqual(again.event_result(self.c, second, "caught", "Cy"), "gone")
        self.assertEqual(again.event_result(self.b, second, "caught", "Bob"), "consumed")
        self.assertEqual([r["seq"] for r in again.resolutions()], [2, 1])

    def test_claimants_are_kept_across_a_restart_so_a_late_report_stays_valid(self):
        event = self.spawn()
        self.world.claim_event(self.a, event)
        self.world.close()
        again = self.open()
        self.addCleanup(again.close)
        again.set_active_players(2)
        self.assertEqual(again.event_result(self.a, event, "caught", "Alice"), "consumed")
        self.assertEqual(again.resolutions()[0]["claimants"], [self.a])

    def test_a_dormant_event_cannot_be_claimed_or_caught(self):
        world = SharedWorld(Path(self.temp.name) / "d.sqlite3", WORLD, clock=self.clock, rng=random.Random(2),
                            event_catalogue=CATALOGUE, locations=LOCATIONS, event_condition_chance=1.0)
        self.addCleanup(world.close)
        world.set_active_players(2)
        event = world.spawn_event(progression_level=30, category="legendary")["event_id"]
        self.assertEqual(world.claim_event(self.a, event), "gone")
        self.assertEqual(world.event_result(self.a, event, "caught", "Alice"), "not_claimant")
        self.assertEqual(world.resolutions(), [])

    def test_old_world_files_gain_the_ledger(self):
        self.world.close()
        db = sqlite3.connect(self.path)
        db.execute("DROP TABLE event_resolutions")
        db.execute("DROP TABLE event_reports")
        db.commit()
        db.close()
        again = self.open()
        self.addCleanup(again.close)
        self.assertEqual(again.resolutions(), [])


if __name__ == "__main__":
    unittest.main()
