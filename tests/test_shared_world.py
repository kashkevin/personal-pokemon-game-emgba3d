"""Host-owned shared world: clock, appearances, notices and World Events."""
from __future__ import annotations

from pathlib import Path
import random
import tempfile
import unittest
from uuid import uuid4

from emerald_multiplayer.balance import BALANCE
from emerald_multiplayer.event_settings import EventSettings
from emerald_multiplayer.protocol import ProtocolError
from emerald_multiplayer.shared_world import (
    SharedWorld, SharedWorldError, _banner, load_event_catalogue,
)
from emerald_multiplayer.shared_world_protocol import (
    validate_clock, validate_event, validate_notice, validate_teammate, validate_wallet,
    validate_world_reply, validate_world_request,
)

WORLD = "11111111-1111-4111-8111-111111111111"
CATALOGUE = {
    "rare": [{"name": "ABSOL", "species": 359, "types": ["dark"]}],
    "legendary": [{"name": "GROUDON", "species": 383, "types": ["ground"]}],
    "mega": [], "mythical": [], "mega_legendary": [],
}
LOCATIONS = [
    {"name": "Route 101", "map_group": 0, "map_number": 16, "x": 10, "y": 7, "min_level": 0, "themes": ["normal"]},
    {"name": "Fiery Path", "map_group": 24, "map_number": 14, "x": 5, "y": 5, "min_level": 30, "themes": ["ground"]},
]


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class SharedWorldTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "world.sqlite3.shared-world.sqlite3"
        self.clock = FakeClock()
        self.world = self.open()

    def tearDown(self):
        self.world.close()
        self.temp.cleanup()

    def open(self, world_id=WORLD, seed=7):
        return SharedWorld(self.path, world_id, clock=self.clock, rng=random.Random(seed),
                           event_catalogue=CATALOGUE, locations=LOCATIONS, event_condition_chance=0.0)

    # --------------------------------------------------------------- clock
    def test_clock_runs_twelve_times_real_time_only_while_players_are_online(self):
        start = self.world.world_seconds()
        self.assertEqual(start, BALANCE.clock_start_seconds)
        self.assertEqual(start, 12 * 3600)                    # a new world starts at 12:00 noon (owner, 2026-10-17)
        self.assertEqual(self.world.time_of_day(), "day")
        self.clock.now += 100
        self.assertEqual(self.world.world_seconds(), start)  # nobody online: paused
        self.world.set_active_players(2)
        self.clock.now += 100
        self.assertEqual(self.world.world_seconds(), start + 1200)
        self.assertEqual(self.world.clock_view(), {"seconds": start + 1200, "running": True})
        self.world.set_active_players(0)
        self.clock.now += 1000
        self.assertEqual(self.world.clock_view(), {"seconds": start + 1200, "running": False})
        # Two real hours are one world day.
        self.world.set_active_players(1)
        self.clock.now += 7200
        self.assertEqual(self.world.world_seconds(), start + 1200 + 86400)

    def test_clock_persists_across_host_restart(self):
        self.world.set_active_players(1)
        self.clock.now += 50
        self.world.set_active_players(0)
        expected = self.world.world_seconds()
        self.world.close()
        self.world = self.open()
        self.assertEqual(self.world.world_seconds(), expected)

    def test_a_whole_day_and_night_takes_two_real_hours(self):
        """The owner's clock (confirmed 2026-10-17): 12x - 1 real minute = 12 world minutes, 5 real minutes = 1 world hour,
        a whole day and night = 2 real hours - from 12:00 noon, simulated (the clock is injected)."""
        self.assertEqual(BALANCE.clock_rate, 12)
        start = self.world.world_seconds()
        self.assertEqual(start, 12 * 3600)
        self.world.set_active_players(1)
        began = self.clock.now
        self.clock.now += 60
        self.assertEqual(self.world.world_seconds() - start, 12 * 60)            # 1 real minute = 12 world minutes
        seen = []
        for step in range(1, 25):                                                # 24 steps of 5 real minutes
            self.clock.now = began + step * 300
            seconds = self.world.world_seconds()
            self.assertEqual(seconds - start, step * 3600)                       # 5 real minutes = 1 world hour
            seen.append(((seconds // 3600) % 24, self.world.time_of_day()))
        self.assertEqual(self.world.world_seconds() - start, 86400)              # 2 real hours = one world day
        self.assertEqual((self.world.world_seconds() // 3600) % 24, 12)          # noon again, the next day
        names = [name for _, name in seen]
        # day 13-17, evening 18-20, night 21-3, morning (sunrise) 4-10, day again 11-12 - each at the game's hours
        self.assertEqual(names, ["day"] * 5 + ["evening"] * 3 + ["night"] * 7 + ["morning"] * 7 + ["day"] * 2)
        self.assertEqual(seen[0][0], 13)

    def test_damaged_clock_data_is_repaired_and_a_valid_clock_is_kept(self):
        import sqlite3
        from emerald_multiplayer.shared_world import MAX_CLOCK_SECONDS
        for bad in (-5, "noon", 1.5, MAX_CLOCK_SECONDS + 1):
            with self.subTest(bad=bad):
                self.world.close()
                db = sqlite3.connect(str(self.path), isolation_level=None)
                db.execute("UPDATE clock SET seconds=? WHERE id=1", (bad,))
                db.close()
                self.world = self.open()
                self.assertTrue(self.world.clock_repaired)
                self.assertEqual(self.world.world_seconds(), BALANCE.clock_start_seconds)
                kept = self.world._db.execute("SELECT value FROM metadata WHERE key='clock_repaired_from'").fetchone()[0]
                self.assertEqual(kept, repr(bad))
        for good in (0, 5 * 86400 + 7, MAX_CLOCK_SECONDS):
            with self.subTest(good=good):
                self.world.close()
                db = sqlite3.connect(str(self.path), isolation_level=None)
                db.execute("UPDATE clock SET seconds=? WHERE id=1", (good,))
                db.close()
                self.world = self.open()
                self.assertFalse(self.world.clock_repaired)
                self.assertEqual(self.world.world_seconds(), good)

    def test_an_existing_worlds_clock_is_never_moved_to_the_new_start(self):
        # A world made when new worlds began at 08:00 keeps its own time: only a world without a clock gets the start.
        import sqlite3
        self.world.close()
        db = sqlite3.connect(str(self.path), isolation_level=None)
        db.execute("UPDATE clock SET seconds=? WHERE id=1", (8 * 3600 + 5,))
        db.close()
        self.world = self.open()
        self.assertEqual(self.world.world_seconds(), 8 * 3600 + 5)

    def test_time_of_day_buckets(self):
        for hour, name in ((5, "morning"), (12, "day"), (18, "evening"), (22, "night"), (2, "night")):
            self.world._clock.seconds = hour * 3600
            self.assertEqual(self.world.time_of_day(), name)

    def test_time_of_day_follows_the_games_hours(self):
        # The engine's Gen 6 hours (include/constants/rtc.h): morning 4-10,
        # day 11-17, evening 18-20, night 21-3. The host once started the
        # evening (and the night weights of shared wild Pokemon) at 17.
        game = {hour: "night" for hour in range(24)}
        game.update({hour: "morning" for hour in range(4, 11)})
        game.update({hour: "day" for hour in range(11, 18)})
        game.update({hour: "evening" for hour in range(18, 21)})
        for hour, name in game.items():
            self.world._clock.seconds = 3 * 86400 + hour * 3600 + 1799
            self.assertEqual(self.world.time_of_day(), name, hour)
            self.assertEqual(self.world._night(), name in ("evening", "night"), hour)

    def test_world_identity_is_bound(self):
        self.world.close()
        with self.assertRaises(SharedWorldError):
            self.world = self.open(world_id=str(uuid4()))
        self.world = self.open()

    # ------------------------------------------------------------ appearance
    def test_appearance_validation_and_persistence(self):
        player = str(uuid4())
        self.assertIsNone(self.world.appearance(player))
        self.assertEqual(self.world.set_appearance(player, "0102030405060700"), "0102030405060700")
        for bad in ("0102030405060701", "01020304050607", "0102030405060G00", "0002000000000000", 5):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.world.set_appearance(player, bad)
        self.world.close()
        self.world = self.open()
        self.assertEqual(self.world.appearance(player), "0102030405060700")

    # --------------------------------------------------------------- notices
    def test_notices_queue_rotate_and_are_addressed(self):
        a, b = str(uuid4()), str(uuid4())
        self.assertIsNone(self.world.notice_view())
        self.world.post_notice("FIRST|line two")
        self.world.post_notice("SECOND", to=[b, a])
        first = self.world.notice_view()
        self.assertEqual((first["text"], first["to"]), ("FIRST|line two", None))
        self.clock.now += BALANCE.notice_seconds + 1
        second = self.world.notice_view()
        self.assertEqual((second["text"], second["to"]), ("SECOND", sorted([a, b])))
        self.assertGreater(second["id"], first["id"])
        self.clock.now += BALANCE.notice_seconds + 1
        self.assertIsNone(self.world.notice_view())
        validate_notice(second)

    def test_banner_lines_are_bounded(self):
        text = _banner("A" * 50 + "|x", "B" * 50)
        first, second = text.split("|")
        self.assertEqual((len(first), len(second)), (32, 31))
        self.assertEqual(_banner("ONLY"), "ONLY")

    # ---------------------------------------------------------------- events
    def test_scheduler_spawns_reachable_event_with_announcement(self):
        self.world.set_active_players(1)
        self.assertFalse(self.world.tick_events(1, lambda: 12))
        self.clock.now += BALANCE.event_first_delay[1] + 1
        self.assertTrue(self.world.tick_events(1, lambda: 12))
        view = self.world.event_view()
        validate_event(view)
        # Only Route 101 is reachable at progression level 12 (Fiery Path needs 30).
        self.assertEqual((view["map_group"], view["map_number"]), (0, 16))
        self.assertIn(view["species"], (359, 383))
        self.assertGreaterEqual(view["level"], BALANCE.event_level_min)
        self.assertEqual(view["seconds_left"], BALANCE.event_duration_seconds)
        self.assertIn("near Route 101", self.world.notice_view()["text"])

    def test_event_timer_pauses_while_nobody_is_online(self):
        self.world.set_active_players(1)
        event = self.world.spawn_event(progression_level=20, category="rare")
        self.assertIsNotNone(event)
        self.world.tick_events(1, lambda: 20)
        self.clock.now += 60  # online: counts down
        self.world.tick_events(1, lambda: 20)
        left_online = self.world.event_view()["seconds_left"]
        self.world.set_active_players(0)  # the last player leaves (server calls this at the moment)
        self.clock.now += 3600  # an hour with nobody online
        self.world.tick_events(0, lambda: 20)
        self.world.tick_events(0, lambda: 20)
        self.assertEqual(self.world.event_view()["seconds_left"], left_online)
        self.world.set_active_players(1)
        self.clock.now += 10
        self.world.tick_events(1, lambda: 20)
        self.assertEqual(self.world.event_view()["seconds_left"], left_online - 10)

    def test_presence_transitions_between_ticks_are_counted_exactly(self):
        # Phase 11 fix: the pause starts when the last player leaves and ends
        # when one joins, not at the next tick.
        self.world.set_active_players(1)
        self.world.spawn_event(progression_level=20, category="rare")
        start = self.world.event_view()["seconds_left"]
        self.world.tick_events(1, lambda: 20)
        self.clock.now += 5            # 5 s online
        self.world.set_active_players(0)
        self.clock.now += 5            # 5 s offline, then a tick sees nobody
        self.world.tick_events(0, lambda: 20)
        self.clock.now += 5            # 5 s more offline
        self.world.set_active_players(1)
        self.clock.now += 5            # 5 s online, then a tick sees one player
        self.world.tick_events(1, lambda: 20)
        self.assertEqual(self.world.event_view()["seconds_left"], start - 10)
        self.assertAlmostEqual(self.world.active_seconds(), 10.0)

    def test_tick_reporting_presence_without_set_active_players_still_pauses(self):
        self.world.tick_events(1, lambda: 20)  # safety net starts active time here
        self.world.spawn_event(progression_level=20, category="rare")
        start = self.world.event_view()["seconds_left"]
        self.clock.now += 30
        self.world.tick_events(0, lambda: 20)  # nobody online from here
        self.clock.now += 900
        self.world.tick_events(0, lambda: 20)
        self.assertEqual(self.world.event_view()["seconds_left"], start - 30)

    def test_restart_keeps_remaining_time_and_scheduler_wait_with_nobody_online(self):
        self.world.set_active_players(1)
        self.world.tick_events(1, lambda: 20)
        self.clock.now += 20
        wait = self.world._next_event_at - self.world.active_seconds()
        self.world.set_active_players(0)
        self.world.close()
        self.clock.now += 86400  # host down for a day: nothing ages
        self.world = self.open()
        self.assertAlmostEqual(self.world._next_event_at - self.world.active_seconds(), wait, places=3)
        self.world.set_active_players(1)
        self.clock.now += wait - 1
        self.assertFalse(self.world.tick_events(1, lambda: 20))
        self.clock.now += 2
        self.assertTrue(self.world.tick_events(1, lambda: 20))
        self.assertIsNotNone(self.world.event_view())

    def test_restart_keeps_the_claim_so_nothing_is_caught_twice(self):
        a, b = str(uuid4()), str(uuid4())
        self.world.set_active_players(2)
        event_id = self.world.spawn_event(progression_level=20, category="rare")["event_id"]
        self.assertEqual(self.world.claim_event(a, event_id), "granted")
        self.world.close()  # host restarts while A is in the battle
        self.world = self.open()
        self.assertEqual(self.world.event_view()["claimant"], a)
        self.world.set_active_players(1)  # B is back first
        self.assertEqual(self.world.claim_event(b, event_id), "busy")
        self.assertEqual(self.world.event_result(a, event_id, "caught", "Alice"), "consumed")
        self.assertEqual(self.world.claim_event(b, event_id), "gone")

    def test_restored_claim_is_released_after_its_grace_in_active_time(self):
        a, b = str(uuid4()), str(uuid4())
        self.world.set_active_players(2)
        event_id = self.world.spawn_event(progression_level=20, category="rare")["event_id"]
        self.world.claim_event(a, event_id)
        self.world.close()
        self.world = self.open()
        self.clock.now += 10 * BALANCE.event_claim_grace_seconds  # nobody online: grace waits
        self.world.tick_events(0, lambda: 20)
        self.assertEqual(self.world.claim_event(b, event_id), "busy")
        self.world.set_active_players(1)
        self.clock.now += BALANCE.event_claim_grace_seconds + 1
        self.assertTrue(self.world.tick_events(1, lambda: 20))
        self.assertEqual(self.world.claim_event(b, event_id), "granted")

    def test_older_event_records_load_safely(self):
        import json
        record = {"event_id": 7, "category": "rare", "species": 359, "name": "ABSOL", "level": 30,
                  "shiny": False, "mega": False, "held_item": 0, "perfect_ivs": 1, "map_group": 0,
                  "map_number": 16, "x": 10, "y": 7, "place": "Route 101", "reminded": [],
                  "expires": 123456789.0, "remaining": 100}
        self.world.close()
        import sqlite3
        db = sqlite3.connect(str(self.path))
        db.execute("INSERT INTO events VALUES (?, ?, 'active', NULL, 0)", (7, json.dumps(record)))
        db.commit()
        db.close()
        self.world = self.open()
        view = self.world.event_view()
        self.assertEqual(view["event_id"], 7)
        self.assertEqual(view["seconds_left"], 100)
        self.assertIsNone(view["claimant"])

    def test_no_event_spawns_while_nobody_is_online(self):
        self.clock.now += BALANCE.event_first_delay[1] + 1
        self.assertFalse(self.world.tick_events(0, lambda: 12))
        self.assertIsNone(self.world.event_view())

    def test_first_catch_wins_and_running_away_leaves_it_for_others(self):
        a, b = str(uuid4()), str(uuid4())
        event = self.world.spawn_event(progression_level=20, category="rare")
        event_id = event["event_id"]
        finished = []
        self.world.on_event_finished = lambda players, eid: finished.append((players, eid))
        self.assertEqual(self.world.claim_event(a, event_id), "granted")
        self.assertEqual(self.world.claim_event(b, event_id), "busy")
        self.assertEqual(self.world.event_view()["claimant"], a)
        self.assertEqual(self.world.event_result(b, event_id, "caught", "Bob"), "not_claimant")
        self.assertEqual(self.world.event_result(a, event_id, "ran", "Alice"), "released")
        self.assertIsNone(self.world.event_view()["claimant"])
        self.assertEqual(self.world.claim_event(b, event_id), "granted")
        self.assertEqual(self.world.event_result(b, event_id, "caught", "Bob"), "consumed")
        self.assertIsNone(self.world.event_view())
        self.clock.now += BALANCE.notice_seconds + 1  # the announcement had its turn
        self.assertIn("BOB caught the", self.world.notice_view()["text"])
        self.assertEqual(self.world.claim_event(a, event_id), "gone")
        self.assertEqual(finished, [(sorted([a, b]), event_id)])

    def test_disconnected_claimant_releases_after_grace(self):
        a, b = str(uuid4()), str(uuid4())
        self.world.set_active_players(1)  # B is still online, so the grace counts
        event_id = self.world.spawn_event(progression_level=20, category="rare")["event_id"]
        self.world.claim_event(a, event_id)
        self.world.player_disconnected(a)
        self.assertEqual(self.world.claim_event(b, event_id), "busy")
        self.clock.now += BALANCE.event_claim_grace_seconds + 1
        self.assertTrue(self.world.tick_events(1, lambda: 20))
        self.assertEqual(self.world.claim_event(b, event_id), "granted")

    # Audit 2026-10-13 (KNOWN_ISSUES M16, M20)
    def test_a_claimant_who_reconnects_in_its_grace_keeps_the_event(self):
        a, b = str(uuid4()), str(uuid4())
        self.world.set_active_players(1)
        event_id = self.world.spawn_event(progression_level=20, category="rare")["event_id"]
        self.world.claim_event(a, event_id)
        self.world.player_disconnected(a)
        self.clock.now += BALANCE.event_claim_grace_seconds - 5
        self.world.player_connected(a)  # back in time; the battle goes on
        self.clock.now += BALANCE.event_claim_grace_seconds + 60  # past the deadline, within the event's 15 minutes
        self.world.tick_events(2, lambda: 20)
        self.assertEqual(self.world.claim_event(b, event_id), "busy")
        self.assertEqual(self.world.event_result(a, event_id, "caught", "Alice"), "consumed")

    def test_a_claim_is_durable_at_once(self):
        a, b = str(uuid4()), str(uuid4())
        self.world.set_active_players(2)
        event_id = self.world.spawn_event(progression_level=20, category="rare")["event_id"]
        self.assertEqual(self.world.claim_event(a, event_id), "granted")
        # The host crashes right after the claim (no close(), no 30 s persist).
        crashed = self.open()
        try:
            self.assertEqual(crashed.event_view()["claimant"], a)
            crashed.set_active_players(1)
            self.assertEqual(crashed.claim_event(b, event_id), "busy")
        finally:
            crashed._db.close()
            crashed._db = None

    def test_a_late_catch_from_the_last_claimant_is_not_caught_again(self):
        a, b = str(uuid4()), str(uuid4())
        self.world.set_active_players(1)
        event_id = self.world.spawn_event(progression_level=20, category="rare")["event_id"]
        self.world.claim_event(a, event_id)
        self.world.player_disconnected(a)
        self.clock.now += BALANCE.event_claim_grace_seconds + 1
        self.world.tick_events(1, lambda: 20)
        self.assertIsNone(self.world.event_view()["claimant"])  # the grace ran out mid-battle
        self.world.player_connected(a)
        self.assertEqual(self.world.event_result(b, event_id, "caught", "Bob"), "not_claimant")
        self.assertEqual(self.world.event_result(a, event_id, "caught", "Alice"), "consumed")
        self.assertIsNone(self.world.event_view())
        self.assertEqual(self.world.claim_event(b, event_id), "gone")

    def test_a_late_catch_while_another_player_holds_the_claim_waits_and_the_holder_keeps_it(self):
        # Owner, 2026-11-05 (G3, no duplicate claims; replaces Update 11's "whoever holds the claim"): the first valid
        # reported catch still wins, but not over a claim another trainer holds. The full matrix is in test_event_catch.py.
        a, b = str(uuid4()), str(uuid4())
        self.world.set_active_players(1)
        event_id = self.world.spawn_event(progression_level=20, category="rare")["event_id"]
        self.world.claim_event(a, event_id)
        self.world.player_disconnected(a)
        self.clock.now += BALANCE.event_claim_grace_seconds + 1
        self.world.tick_events(1, lambda: 20)
        self.assertEqual(self.world.claim_event(b, event_id), "granted")
        self.assertEqual(self.world.event_result(a, event_id, "caught", "Alice"), "busy")    # B's claim stands
        self.assertEqual(self.world.event_view()["claimant"], b)
        self.assertEqual(self.world.event_result(b, event_id, "caught", "Bob"), "consumed")
        self.assertIsNone(self.world.event_view())
        self.assertEqual(self.world.event_result(a, event_id, "caught", "Alice"), "gone")    # A's copy is the duplicate
        self.assertEqual(self.world.catch_verdict(event_id, a), "release")

    def test_the_last_claimant_survives_a_restart(self):
        a = str(uuid4())
        self.world.set_active_players(1)
        event_id = self.world.spawn_event(progression_level=20, category="rare")["event_id"]
        self.world.claim_event(a, event_id)
        self.assertEqual(self.world.event_result(a, event_id, "ran", "Alice"), "released")
        self.world.close()
        self.world = self.open()
        self.assertIsNone(self.world.event_view()["claimant"])
        self.assertEqual(self.world.event_result(a, event_id, "caught", "Alice"), "consumed")

    def test_a_connected_claimant_on_another_map_lets_the_event_go(self):
        a, b = str(uuid4()), str(uuid4())
        self.world.set_active_players(2)
        event = self.world.spawn_event(progression_level=20, category="rare")
        event_id = event["event_id"]
        here = {"map_group": event["map_group"], "map_number": event["map_number"]}
        away = {"map_group": event["map_group"], "map_number": event["map_number"] + 1}
        self.world.claim_event(a, event_id)
        self.assertFalse(self.world.tick_event_claim({a: here, b: here}))
        self.assertFalse(self.world.tick_event_claim({a: away, b: here}))  # the game was reset elsewhere
        self.clock.now += BALANCE.event_claim_away_seconds - 1
        self.assertFalse(self.world.tick_event_claim({a: away, b: here}))
        self.assertEqual(self.world.claim_event(b, event_id), "busy")
        self.clock.now += 2
        self.assertTrue(self.world.tick_event_claim({a: away, b: here}))
        self.assertEqual(self.world.claim_event(b, event_id), "granted")
        # Coming back resets the count; a disconnected claimant is left to its grace.
        self.assertFalse(self.world.tick_event_claim({b: away}))
        self.clock.now += BALANCE.event_claim_away_seconds // 2
        self.assertFalse(self.world.tick_event_claim({b: here}))
        self.clock.now += BALANCE.event_claim_away_seconds
        self.assertFalse(self.world.tick_event_claim({b: away}))
        self.assertEqual(self.world.event_view()["claimant"], b)
        self.clock.now += 10 * BALANCE.event_claim_away_seconds
        self.assertFalse(self.world.tick_event_claim({}))
        self.assertEqual(self.world.event_view()["claimant"], b)

    def test_event_expires_with_notice_and_survives_restart_with_remaining_time(self):
        self.world.set_active_players(1)
        event_id = self.world.spawn_event(progression_level=40, category="legendary")["event_id"]
        self.clock.now += 300
        left = self.world.event_view()["seconds_left"]
        self.world.close()  # close() saves the remaining time itself
        self.clock.now += 5000  # host offline: event time does not pass
        self.world = self.open()
        self.assertEqual(self.world.event_view()["event_id"], event_id)
        self.assertEqual(self.world.event_view()["seconds_left"], left)
        self.world.set_active_players(1)
        self.clock.now += left + 1
        self.assertTrue(self.world.tick_events(1, lambda: 40))
        self.assertIsNone(self.world.event_view())
        self.assertIn("has disappeared", self.world.notice_view()["text"])

    def test_reminders_before_expiry(self):
        self.world.set_active_players(1)
        self.world.spawn_event(progression_level=20, category="rare")
        self.world.notice_view()
        self.clock.now += BALANCE.notice_seconds + 1
        self.assertIsNone(self.world.notice_view())
        self.clock.now += self.world.event_view()["seconds_left"] - 299
        self.assertTrue(self.world.tick_events(1, lambda: 20))
        self.assertIn("left", self.world.notice_view()["text"])

    def test_generated_catalogue_is_complete_and_locations_are_bounded(self):
        catalogue = load_event_catalogue()
        if not catalogue:
            self.skipTest("generated catalogue unavailable")
        for name in BALANCE.event_category_weights:
            self.assertTrue(catalogue.get(name), name)
            for entry in catalogue[name]:
                stages = entry.get("stages") or [entry]
                for stage in stages:
                    self.assertTrue(1 <= stage["species"] <= catalogue["engine_counts"]["species"], stage)
                    # Names go into 32-character banner lines.
                    self.assertTrue(stage["name"].isascii() and 1 <= len(stage["name"]) <= 24, stage)
        self.assertGreaterEqual(len(catalogue["locations"]), 10)
        for location in catalogue["locations"]:
            self.assertTrue({"name", "map_group", "map_number", "x", "y", "min_level"} <= set(location), location)
            self.assertTrue(0 <= location["x"] < 256 and 0 <= location["y"] < 256, location)
        self.assertTrue(any(location.get("min_level", 0) == 0 for location in catalogue["locations"]))


class EventReservationTests(unittest.TestCase):
    """G3, decided by the owner on 2026-11-05: a World Event Pokemon is reserved for five minutes after its claimant
    disconnects; the claimant may reconnect and reclaim it meanwhile; it is released afterwards; never two claims.

    The calls follow the host's order (server.py): a joining session is counted (set_active_players), then
    player_connected; a leaving one gets player_disconnected, then the count. The five minutes are active time: they count
    only while somebody is online (nobody can take the Pokemon while nobody is), and they survive a host restart."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.number = 0
        self.clock = FakeClock()
        self.a, self.b, self.c = (str(uuid4()) for _ in range(3))
        self.world = None
        self.fresh()

    def tearDown(self):
        self.world.close()
        self.temp.cleanup()

    def open(self):
        settings = EventSettings(shiny_chance=0.0, condition_chance=0.0)   # an ordinary event, out at once
        return SharedWorld(self.path, WORLD, clock=self.clock, rng=random.Random(7), event_catalogue=CATALOGUE,
                           locations=LOCATIONS, event_settings=settings)

    def fresh(self):
        """A new world file with nobody online (one per subtest), its clock back at a round number so that a deadline
        300 s later is exactly 300 s later."""
        if self.world is not None:
            self.world.close()
        self.clock.now = 1000.0
        self.number += 1
        self.path = Path(self.temp.name) / f"world{self.number}.sqlite3.shared-world.sqlite3"
        self.online: set[str] = set()
        self.world = self.open()

    def connect(self, *players):
        for player in players:
            self.online.add(player)
            self.world.set_active_players(len(self.online))
            self.world.player_connected(player)

    def disconnect(self, *players):
        for player in players:
            self.online.discard(player)
            self.world.player_disconnected(player)
            self.world.set_active_players(len(self.online))

    def restart(self):
        """The host stops cleanly (every session ends first, then the timers are saved) and starts again."""
        self.disconnect(*sorted(self.online))
        self.world.close()
        self.world = self.open()

    def crash(self):
        """The host process dies: nothing more is saved; a new one opens the same file."""
        crashed, self.online = self.world, set()
        self.world = self.open()
        crashed._db.close()
        crashed._db = None

    def tick(self):
        """One pass of the host's loop (server.py _monitor)."""
        event = self.world.event_view()
        here = {} if event is None else {"map_group": event["map_group"], "map_number": event["map_number"]}
        changed = self.world.tick_events(len(self.online), lambda: 20)
        return self.world.tick_event_claim({player: dict(here) for player in self.online}) or changed

    def wait(self, seconds):
        self.clock.now += seconds
        return self.tick()

    def holder(self):
        view = self.world.event_view()
        return None if view is None else view["claimant"]

    def a_left_with_it(self, *others):
        """A and the others are online; A claims the event and its link drops: A's five minutes start now."""
        self.connect(self.a, *(others or (self.b,)))
        event_id = self.world.spawn_event(progression_level=20, category="rare")["event_id"]
        self.assertEqual(self.world.claim_event(self.a, event_id), "granted")
        self.disconnect(self.a)
        self.assertEqual(self.holder(), self.a)
        return event_id

    # ------------------------------------------------------------------ the window
    def test_the_reservation_is_five_minutes_and_shared_wild_pokemon_keep_ten(self):
        from emerald_multiplayer.shared_spawns import CLAIM_GRACE_SECONDS
        self.assertEqual(BALANCE.event_claim_grace_seconds, 5 * 60)
        self.assertEqual(CLAIM_GRACE_SECONDS, 600)                   # the shared spawns' grace is not this decision's

    def test_reconnecting_at_299_seconds_keeps_the_claim(self):
        event_id = self.a_left_with_it()
        self.wait(299)
        self.assertEqual(self.holder(), self.a)
        self.assertEqual(self.world.claim_event(self.b, event_id), "busy")
        self.connect(self.a)                                         # back with a second to spare: A reclaims it
        self.wait(BALANCE.event_claim_grace_seconds)                 # long past the deadline, within the event's timer
        self.assertEqual(self.holder(), self.a)
        self.assertEqual(self.world.claim_event(self.b, event_id), "busy")
        self.assertEqual(self.world.claim_event(self.a, event_id), "granted")   # an explicit reclaim is the same claim
        self.assertEqual(self.world.event_result(self.a, event_id, "caught", "Alice"), "consumed")
        self.assertEqual(self.world.resolutions()[0]["winner"], self.a)

    def test_the_claim_is_released_at_300_seconds_exactly_and_durably(self):
        import json
        event_id = self.a_left_with_it()
        self.clock.now += 299.5                                      # no tick in between: every path sees the deadline
        self.assertEqual(self.holder(), self.a)
        self.assertEqual(self.world.claim_event(self.b, event_id), "busy")
        self.clock.now += 0.5
        self.assertIsNone(self.holder())
        self.world.persist_timers()                                  # a reservation that ran out is never saved
        row = self.world._db.execute("SELECT record FROM events WHERE event_id=?", (event_id,)).fetchone()
        self.assertNotIn("claim", json.loads(row[0]))
        self.assertTrue(self.tick())                                 # the host's loop releases it and says so
        self.crash()
        self.connect(self.b)
        self.assertIsNone(self.holder())
        self.assertEqual(self.world.claim_event(self.b, event_id), "granted")
        # The release is saved the moment it happens, whichever call notices it first (here A's reconnection, a moment
        # late, between two of the host's timer saves), so a crash right after it cannot hand the claim back.
        self.fresh()
        event_id = self.a_left_with_it()
        self.wait(299.5)                                             # the host's timers were saved with 0.5 s left
        self.clock.now += 0.5
        self.connect(self.a)
        self.assertIsNone(self.holder())
        self.crash()
        self.connect(self.a, self.b)
        self.assertIsNone(self.holder())
        self.assertEqual(self.world.claim_event(self.b, event_id), "granted")

    def test_a_reconnection_in_the_same_tick_as_the_release(self):
        for offset, kept in ((299.9, True), (300, False), (300.1, False)):
            for tick_first in (True, False):
                with self.subTest(offset=offset, tick_first=tick_first):
                    self.fresh()
                    event_id = self.a_left_with_it()
                    self.clock.now += offset
                    if tick_first:
                        self.tick()
                    self.connect(self.a)
                    if not tick_first:
                        self.tick()
                    self.assertEqual(self.holder(), self.a if kept else None)
                    self.assertEqual(self.world.claim_event(self.b, event_id), "busy" if kept else "granted")
                    self.assertEqual(self.world.claim_event(self.a, event_id), "granted" if kept else "busy")
                    self.assertEqual(self.holder(), self.a if kept else self.b)

    def test_after_the_release_another_player_claims_it_and_the_late_catch_waits(self):
        event_id = self.a_left_with_it()
        self.wait(300)
        self.assertIsNone(self.holder())
        self.assertEqual(self.world.claim_event(self.b, event_id), "granted")
        self.connect(self.a)                                         # A is back after its five minutes: B holds it
        self.assertEqual(self.holder(), self.b)
        self.assertEqual(self.world.claim_event(self.a, event_id), "busy")
        for _ in range(3):                                           # A's game caught it offline, reports it again
            self.assertEqual(self.world.event_result(self.a, event_id, "caught", "Alice"), "busy")
            self.assertIsNone(self.world.catch_verdict(event_id, self.a))
            self.wait(20)
        self.assertEqual(self.holder(), self.b)
        self.assertEqual(self.world.resolutions(), [])
        self.assertEqual(self.world.event_result(self.b, event_id, "caught", "Bob"), "consumed")
        self.assertEqual(self.world.event_result(self.a, event_id, "caught", "Alice"), "gone")
        self.assertEqual([(r["winner"], r["claimants"]) for r in self.world.resolutions()], [(self.b, [self.a, self.b])])
        self.assertEqual((self.world.catch_verdict(event_id, self.a), self.world.catch_verdict(event_id, self.b)),
                         ("release", "keep"))

    def test_the_new_holders_own_reservation_protects_it_from_the_earlier_claimant(self):
        event_id = self.a_left_with_it(self.b, self.c)
        self.wait(300)
        self.assertEqual(self.world.claim_event(self.b, event_id), "granted")
        self.disconnect(self.b)                                      # now B's link drops: B's five minutes
        self.connect(self.a)
        self.wait(299)
        self.assertEqual(self.world.event_result(self.a, event_id, "caught", "Alice"), "busy")
        self.assertEqual(self.world.claim_event(self.c, event_id), "busy")
        self.wait(1)                                                 # B's reservation ran out: nobody holds it
        self.assertEqual(self.world.event_result(self.a, event_id, "caught", "Alice"), "consumed")
        self.assertEqual(self.world.resolutions()[0]["winner"], self.a)
        self.connect(self.b)
        self.assertEqual(self.world.event_result(self.b, event_id, "caught", "Bob"), "gone")
        self.assertEqual(self.world.catch_verdict(event_id, self.b), "release")

    def test_two_claims_arriving_together(self):
        for first, second in ((self.b, self.c), (self.c, self.b)):
            with self.subTest(first=first == self.b and "B" or "C"):
                self.fresh()
                event_id = self.a_left_with_it(self.b, self.c)
                self.clock.now += 299
                self.assertEqual((self.world.claim_event(first, event_id), self.world.claim_event(second, event_id)),
                                 ("busy", "busy"))
                self.clock.now += 1                                  # the deadline; the host has not ticked yet
                self.assertEqual((self.world.claim_event(first, event_id), self.world.claim_event(second, event_id)),
                                 ("granted", "busy"))
                self.connect(self.a)
                self.tick()
                self.assertEqual(self.holder(), first)
                self.assertEqual(self.world.claim_event(second, event_id), "busy")

    # ------------------------------------------------------------- pause and restart
    def test_the_five_minutes_pause_while_nobody_is_online(self):
        # A is the last player online when its link drops: nobody can take the Pokemon, so nothing counts.
        self.connect(self.a)
        event_id = self.world.spawn_event(progression_level=20, category="rare")["event_id"]
        self.world.claim_event(self.a, event_id)
        self.disconnect(self.a)
        self.clock.now += 3 * 3600
        self.connect(self.b)                                         # B arrives hours later: five minutes are still ahead
        self.wait(299)
        self.assertEqual(self.world.claim_event(self.b, event_id), "busy")
        self.wait(1)
        self.assertEqual(self.world.claim_event(self.b, event_id), "granted")
        # B online when A left, then B leaves for a while: only the time somebody was online counts.
        self.fresh()
        event_id = self.a_left_with_it()
        self.wait(100)
        self.disconnect(self.b)
        self.clock.now += 1000
        self.tick()
        self.connect(self.b)
        self.wait(199)
        self.assertEqual(self.holder(), self.a)
        self.wait(1)
        self.assertIsNone(self.holder())
        # The claimant is the first one back after a pause: it reclaims the Pokemon.
        self.fresh()
        self.connect(self.a)
        event_id = self.world.spawn_event(progression_level=20, category="rare")["event_id"]
        self.world.claim_event(self.a, event_id)
        self.disconnect(self.a)
        self.clock.now += 86400
        self.connect(self.a)
        self.connect(self.b)
        self.wait(BALANCE.event_claim_grace_seconds + 10)
        self.assertEqual(self.holder(), self.a)

    def test_a_host_restart_mid_window_keeps_what_is_left_of_it(self):
        for back in (self.a, self.b):
            with self.subTest(back=back == self.a and "A" or "B"):
                self.fresh()
                event_id = self.a_left_with_it()
                self.wait(100)
                self.restart()
                self.clock.now += 3600                               # the host is up with nobody online: nothing counts
                self.connect(self.c)
                self.wait(199)
                self.assertEqual(self.holder(), self.a)
                self.assertEqual(self.world.claim_event(self.c, event_id), "busy")
                if back == self.a:
                    self.connect(self.a)                             # A is back within what was left: A keeps it
                    self.wait(BALANCE.event_claim_grace_seconds)
                    self.assertEqual(self.holder(), self.a)
                    self.assertEqual(self.world.event_result(self.a, event_id, "caught", "Alice"), "consumed")
                else:
                    self.wait(1)
                    self.assertEqual(self.world.claim_event(self.c, event_id), "granted")

    def test_a_host_restart_near_the_deadline(self):
        for back in (self.a, self.b):
            with self.subTest(back=back == self.a and "A" or "B"):
                self.fresh()
                event_id = self.a_left_with_it()
                self.wait(299.5)
                self.restart()
                self.connect(back)
                self.clock.now += 0.25
                self.assertEqual(self.holder(), self.a)              # a quarter second left
                if back == self.a:
                    self.assertEqual(self.world.claim_event(self.a, event_id), "granted")
                    self.wait(BALANCE.event_claim_grace_seconds)
                    self.assertEqual(self.holder(), self.a)
                else:
                    self.assertEqual(self.world.claim_event(self.b, event_id), "busy")
                    self.clock.now += 0.25
                    self.assertEqual(self.world.claim_event(self.b, event_id), "granted")
                    self.connect(self.a)
                    self.assertEqual(self.holder(), self.b)

    def test_a_host_crash_never_hands_the_claim_to_two_players(self):
        # Right after A's link dropped, before the host's timers were saved again: A's claim comes back as a connected
        # claimant's, with the whole five minutes (a crash gives the claimant at most the time since that save).
        event_id = self.a_left_with_it()
        self.crash()
        self.connect(self.b)
        self.wait(299)
        self.assertEqual(self.world.claim_event(self.b, event_id), "busy")
        self.wait(1)
        self.assertEqual(self.world.claim_event(self.b, event_id), "granted")
        # Right after B took it: B holds it after the restart, and A's late catch still waits.
        self.crash()
        self.connect(self.a, self.c)
        self.assertEqual(self.holder(), self.b)
        self.assertEqual(self.world.event_result(self.a, event_id, "caught", "Alice"), "busy")
        # Right after B ran from the battle: nobody holds it after the restart (it was not handed back to B).
        self.connect(self.b)
        self.assertEqual(self.world.event_result(self.b, event_id, "ran", "Bob"), "released")
        self.crash()
        self.connect(self.c)
        self.assertIsNone(self.holder())
        self.assertEqual(self.world.claim_event(self.c, event_id), "granted")
        # Right after A reclaimed it by reconnecting: A was connected when the host died, so A has the whole window again.
        self.fresh()
        event_id = self.a_left_with_it()
        for _ in range(20):
            self.wait(10)                                            # the host's timers are saved every 30 s meanwhile
        self.connect(self.a)
        self.crash()
        self.connect(self.b)
        self.wait(299)
        self.assertEqual(self.world.claim_event(self.b, event_id), "busy")
        self.wait(1)
        self.assertEqual(self.world.claim_event(self.b, event_id), "granted")
        # Mid-window, with the host's timers saved every 30 s: the restored reservation errs only towards the claimant.
        self.fresh()
        event_id = self.a_left_with_it()
        for _ in range(10):
            self.wait(10)
        self.crash()
        self.connect(self.b)
        left = self.world._claim["released_at"] - self.world.active_seconds()
        self.assertGreaterEqual(left, 200)
        self.assertLessEqual(left, 230)

    def test_a_claim_saved_under_the_old_two_minute_rule_loads_with_the_five_minutes(self):
        import json
        import sqlite3
        cases = (
            ({"grace_remaining": None}, 300),                        # its claimant was connected: the whole window
            ({"grace_remaining": 30.0}, 210),                        # 90 s into the old 120 s: 210 s of the five minutes
            ({"grace_remaining": 0.0}, 180),                         # the old window had just run out: 3 minutes are left
            ({"grace_remaining": 120.0}, 300),
            ({"grace_remaining": 250.0, "grace_window": 300}, 250),  # a record written by this rule
            ({"grace_remaining": "soon"}, 300),                      # unreadable: the whole window
        )
        for fields, left in cases:
            with self.subTest(fields=fields):
                self.fresh()
                self.world.close()
                record = {"event_id": 7, "category": "rare", "species": 359, "name": "ABSOL", "level": 30,
                          "shiny": False, "mega": False, "held_item": 0, "perfect_ivs": 1, "map_group": 0,
                          "map_number": 16, "x": 10, "y": 7, "place": "Route 101", "reminded": [], "remaining": 800,
                          "claimants": [self.a], "last_claimant": self.a, "claim": {"player_id": self.a, **fields}}
                db = sqlite3.connect(str(self.path))
                db.execute("INSERT INTO events VALUES (?, ?, 'active', NULL, 0)", (7, json.dumps(record)))
                db.commit()
                db.close()
                self.world = self.open()
                self.connect(self.b)
                self.wait(left - 0.5)
                self.assertEqual(self.holder(), self.a)
                self.assertEqual(self.world.claim_event(self.b, 7), "busy")
                self.wait(0.5)
                self.assertEqual(self.world.claim_event(self.b, 7), "granted")
                stored = json.loads(self.world._db.execute("SELECT record FROM events WHERE event_id=7").fetchone()[0])
                self.assertEqual(stored["claim"], {"player_id": self.b, "grace_remaining": None,
                                                   "grace_window": BALANCE.event_claim_grace_seconds})

    # ------------------------------------------------------------------- the races
    def test_never_two_holders_whatever_the_order(self):
        """Random interleavings of joins, leaves, claims, catches, runs, host ticks and clean host restarts, many of them
        landing exactly on a deadline or in the same instant, checked step by step against the rule: at most one holder; a
        disconnected holder keeps the claim for exactly five minutes of time somebody is online and keeps it by coming
        back within them; a catch is accepted only from the holder or, while nobody holds the claim, from an earlier
        claimant; one owner per event."""
        from collections import Counter
        grace = BALANCE.event_claim_grace_seconds
        players = (self.a, self.b, self.c)
        seen = Counter()
        for seed in range(5):
            rng = random.Random(20261105 + seed)
            self.fresh()
            model = {"event": None, "left": 0.0, "holder": None, "away": 0.0, "claimants": set()}
            owners = {}

            def effective():
                holder = model["holder"]
                if holder is not None and holder not in self.online and model["away"] >= grace:
                    model["holder"] = None                       # its five minutes ran out
                    seen["lapsed"] += 1
                return model["holder"]

            def sync():
                view = self.world.event_view()
                if view is None:
                    model.update(event=None, holder=None)
                elif view["event_id"] != model["event"]:
                    model.update(event=view["event_id"], left=float(BALANCE.event_duration_seconds), holder=None,
                                 away=0.0, claimants=set())

            for step in range(600):
                where = f"seed {seed}, step {step}"
                roll = rng.random()
                if roll < 0.40:
                    # Time passes (only while somebody is online does it count), sometimes exactly to the deadline.
                    holder = model["holder"]
                    choices = [0, 0.5, 1, 7, 30, 120, 299, 300, 301]
                    if holder is not None and holder not in self.online and model["away"] < grace:
                        to_deadline = grace - model["away"]
                        choices += [to_deadline, to_deadline, max(0.0, to_deadline - 0.5)]
                    dt = rng.choice(choices)
                    self.clock.now += dt
                    if self.online:
                        model["left"] -= dt
                        if holder is not None and holder not in self.online:
                            model["away"] += dt
                    if (model["event"] is not None and model["left"] <= 0) or rng.random() < 0.6:
                        self.tick()                              # an event's own timer ends at the host's tick
                        if model["event"] is not None and model["left"] <= 0:
                            model.update(event=None, holder=None)
                        sync()
                elif roll < 0.60:
                    player = rng.choice(players)
                    effective()
                    if player in self.online:
                        self.disconnect(player)
                        if model["holder"] == player:
                            model["away"] = 0.0                  # its five minutes start now
                    else:
                        self.connect(player)
                        if model["holder"] == player:
                            model["away"] = 0.0                  # back in time: it holds the claim again
                            seen["reclaimed"] += 1
                elif roll < 0.97 and self.online:
                    if model["event"] is None:
                        self.world.spawn_event(progression_level=20, category="rare")
                        sync()
                        continue
                    player = rng.choice(sorted(self.online))
                    holder = effective()
                    self.assertEqual(self.holder(), holder, where)
                    event_id = model["event"]
                    action = rng.choice(("claim", "claim", "caught", "ran"))
                    if action == "caught" and player == holder and rng.random() < 0.75:
                        action = "claim"                         # the holder's battle goes on (a claim again: the same)
                    earlier = sorted(p for p in self.online if p in model["claimants"] and holder not in (None, p))
                    if earlier and rng.random() < 0.5:
                        player, action = rng.choice(earlier), "caught"   # an earlier claimant's catch made offline
                    if action == "claim":
                        outcome = self.world.claim_event(player, event_id)
                        self.assertEqual(outcome, "granted" if holder in (None, player) else "busy", where)
                        seen["claim " + outcome] += 1
                        if outcome == "granted":
                            model["holder"] = player
                            model["claimants"].add(player)
                    elif action == "caught":
                        outcome = self.world.event_result(player, event_id, "caught", "X")
                        if player != holder and player not in model["claimants"]:
                            self.assertEqual(outcome, "not_claimant", where)
                        elif holder not in (None, player):
                            self.assertEqual(outcome, "busy", where)          # never over another trainer's claim
                            self.assertIsNone(self.world.catch_verdict(event_id, player), where)
                            seen["catch waited"] += 1
                        else:
                            self.assertEqual(outcome, "consumed", where)
                            self.assertNotIn(event_id, owners, where)
                            owners[event_id] = player
                            seen["caught by the holder" if player == holder else "caught while nobody held it"] += 1
                            model.update(event=None, holder=None)
                    else:
                        outcome = self.world.event_result(player, event_id, "ran", "X")
                        self.assertEqual(outcome, "released" if holder == player else "not_claimant", where)
                        if outcome == "released":
                            model["holder"] = None
                elif roll >= 0.97:
                    holder = effective()
                    if holder is not None and holder in self.online:
                        model["away"] = 0.0                      # the stop ends its session: its five minutes start
                    self.restart()
                    seen["restart"] += 1
                    sync()
                self.assertEqual(self.holder(), effective(), where)
                self.assertEqual({r["event_id"]: r["winner"] for r in self.world.resolutions(100)}, owners, where)
        # The walk really went through the races it is meant to cover.
        for case in ("lapsed", "reclaimed", "claim granted", "claim busy", "catch waited", "caught by the holder",
                     "caught while nobody held it", "restart"):
            self.assertGreater(seen[case], 0, (case, dict(seen)))


class ShinyEventTests(unittest.TestCase):
    """A shiny World Event has no timer: only a catch or a knockout ends it (owner request, Oct 24, 2026)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "world.sqlite3.shared-world.sqlite3"
        self.clock = FakeClock()
        self.world = self.open()
        self.world.set_active_players(1)

    def tearDown(self):
        self.world.close()
        self.temp.cleanup()

    def open(self, shiny_chance=1.0):
        # condition_chance 1.0: a legendary would always start dormant, but a shiny never does.
        settings = EventSettings(shiny_chance=shiny_chance, condition_chance=1.0)
        return SharedWorld(self.path, WORLD, clock=self.clock, rng=random.Random(7),
                           event_catalogue=CATALOGUE, locations=LOCATIONS, event_settings=settings)

    def notices(self):
        texts = []
        while (notice := self.world.notice_view()) is not None:
            texts.append(notice["text"])
            self.clock.now += BALANCE.notice_seconds + 1
        return texts

    def wait(self, seconds, step=60):
        """Let active time pass in ticks, as the host does."""
        for _ in range(int(seconds // step)):
            self.clock.now += step
            self.world.tick_events(1, lambda: 40)

    def test_a_shiny_event_is_out_at_once_and_has_no_timer(self):
        event = self.world.spawn_event(progression_level=40, category="legendary")
        self.assertTrue(event["shiny"])
        self.assertIsNotNone(self.world.event_view())                 # never dormant
        self.assertNotIn("awake", self.world._event)
        self.assertEqual(event["seconds_left"], 0)
        texts = self.notices()
        self.assertTrue(texts[0].startswith("WORLD EVENT! SHINY GROUDON"), texts)
        self.assertNotIn("left", texts[0])
        self.assertEqual(texts[1], "It stays until someone|catches or beats it!")
        self.assertEqual(self.world.event_status(), {"name": "SHINY GROUDON", "place": self.world._event["place"],
                                                     "seconds_left": 0, "waiting": None})

    def test_a_shiny_event_outlasts_its_duration_running_away_losing_and_a_restart(self):
        a = str(uuid4())
        event_id = self.world.spawn_event(progression_level=40, category="legendary")["event_id"]
        self.notices()
        self.wait(3 * BALANCE.event_duration_seconds)
        self.assertEqual(self.world.event_view()["event_id"], event_id)
        self.assertEqual(self.notices(), [])                          # no "10:00 left" and no "has disappeared"
        for result in ("ran", "lost", "cancelled"):
            self.assertEqual(self.world.claim_event(a, event_id), "granted")
            self.assertEqual(self.world.event_result(a, event_id, result, "Alice"), "released")
            self.assertEqual(self.world.event_view()["event_id"], event_id, result)
        self.world.close()
        self.clock.now += 99_999
        self.world = self.open()
        self.world.set_active_players(1)
        self.wait(2 * BALANCE.event_duration_seconds)
        self.assertEqual(self.world.event_view()["event_id"], event_id)
        self.assertEqual(self.world.event_view()["seconds_left"], 0)
        self.assertEqual(self.world.claim_event(a, event_id), "granted")
        self.assertEqual(self.world.event_result(a, event_id, "caught", "Alice"), "consumed")
        self.assertIsNone(self.world.event_view())
        self.assertIn("ALICE caught the|SHINY GROUDON!", self.notices())

    def test_a_knockout_ends_a_shiny_event_for_everybody(self):
        a, b, c = str(uuid4()), str(uuid4()), str(uuid4())
        event_id = self.world.spawn_event(progression_level=40, category="legendary")["event_id"]
        self.notices()
        self.assertEqual(self.world.claim_event(b, event_id), "granted")
        self.assertEqual(self.world.event_result(b, event_id, "ran", "Bob"), "released")
        self.assertEqual(self.world.claim_event(a, event_id), "granted")
        self.assertEqual(self.world.event_result(c, event_id, "defeated", "Carol"), "not_claimant")   # never claimed it
        self.assertIsNotNone(self.world.event_view())
        self.assertEqual(self.world.event_result(a, event_id, "defeated", "Alice"), "defeated")
        self.assertIsNone(self.world.event_view())
        self.assertIn("ALICE knocked out the|SHINY GROUDON!", self.notices())
        self.assertEqual(self.world.claim_event(b, event_id), "gone")
        self.assertEqual(self.world.event_result(a, event_id, "defeated", "Alice"), "gone")    # a repeat changes nothing
        self.assertEqual(self.world.reports(event_id), [(a, "defeated")])
        # A claimant still in a battle of its own may catch it after all: the first report of a catch still decides.
        self.assertEqual(self.world.event_result(b, event_id, "caught", "Bob"), "consumed")
        self.assertEqual(self.world._resolution(event_id)["winner"], b)
        # The next World Event comes as usual.
        self.wait(BALANCE.event_interval[1] + 60)
        self.assertIsNotNone(self.world.event_view())
        self.assertNotEqual(self.world.event_view()["event_id"], event_id)

    def test_a_knockout_while_another_trainer_battles_it_tells_that_trainer(self):
        a, b = str(uuid4()), str(uuid4())
        event_id = self.world.spawn_event(progression_level=40, category="legendary")["event_id"]
        self.notices()
        self.world.claim_event(a, event_id)
        self.world.player_disconnected(a)
        self.clock.now += BALANCE.event_claim_grace_seconds + 1
        self.world.tick_events(1, lambda: 40)
        self.assertEqual(self.world.claim_event(b, event_id), "granted")
        self.assertEqual(self.world.event_result(a, event_id, "defeated", "Alice"), "defeated")
        self.assertIsNone(self.world.event_view())
        texts = [n["text"] for n in self.world._notice_queue] + [self.world.notice_view()["text"]]
        self.assertTrue(any(t == "ALICE beat it first!|Your battle ends here." for t in texts), texts)

    def test_a_shiny_event_that_restarts_dormant_from_an_older_host_keeps_the_old_timer(self):
        event_id = self.world.spawn_event(progression_level=40, category="legendary")["event_id"]
        self.world._event.update(awake=False, condition="sand")
        self.world._save_event("active")
        self.assertIsNone(self.world.event_view())
        self.assertGreater(self.world.event_status()["seconds_left"], 0)
        self.wait(BALANCE.event_duration_seconds + 120)
        self.assertIsNone(self.world.event_status())                 # slipped away before it woke, as before
        self.assertEqual(self.world.claim_event(str(uuid4()), event_id), "gone")

    def test_an_ordinary_event_keeps_its_timer_and_a_knockout_leaves_it(self):
        self.world.close()
        self.world = self.open(shiny_chance=0.0)
        self.world.set_active_players(1)
        a = str(uuid4())
        event = self.world.spawn_event(progression_level=20, category="rare")
        self.assertFalse(event["shiny"])
        self.assertGreater(event["seconds_left"], 0)
        self.world.claim_event(a, event["event_id"])
        self.assertEqual(self.world.event_result(a, event["event_id"], "defeated", "Alice"), "released")
        self.assertIsNotNone(self.world.event_view())
        self.wait(BALANCE.event_duration_seconds + 60)
        self.assertIsNone(self.world.event_view())


class ProtocolTests(unittest.TestCase):
    def request(self, kind, **fields):
        return dict(type=kind, session_epoch=3, request_id=str(uuid4()), **fields)

    def test_world_requests(self):
        battle = str(uuid4())
        valid = [
            self.request("world_action", action="claim", event_id=1, result=None, seq=1),
            self.request("world_action", action="result", event_id=1, result="caught", seq=2),
            self.request("appearance_get"), self.request("friendship_get"),
            self.request("appearance_set", appearance="0102030405060700"),
            self.request("wager_get", battle_id=battle), self.request("wager_decline", battle_id=battle),
            self.request("wager_set", battle_id=battle, amount=5000),
            self.request("wager_accept", battle_id=battle, amount=5000),
            self.request("wallet_applied", seq=1, amount=0), self.request("gym_coop", gym=8),
            self.request("gym_coop", gym=8, incarnation=1, runtime_id=str(uuid4())),
        ]
        for message in valid:
            with self.subTest(message=message["type"]):
                self.assertIs(validate_world_request(message, 3), message)
        invalid = [
            self.request("world_action", action="claim", event_id=1, result="caught", seq=1),
            self.request("world_action", action="result", event_id=1, result="won", seq=1),
            self.request("world_action", action="steal", event_id=1, result=None, seq=1),
            self.request("appearance_set", appearance="0002000000000000"),
            self.request("wager_set", battle_id="nope", amount=5),
            self.request("wager_set", battle_id=battle, amount=1_000_000),
            self.request("wallet_applied", seq=0, amount=0),
            self.request("wallet_applied", seq=1, amount=-1),
            self.request("gym_coop", gym=0), self.request("gym_coop", gym=9),
            self.request("gym_coop", gym=1, extra=True),
            self.request("gym_coop", gym=1, incarnation=1),
            self.request("gym_coop", gym=1, incarnation=0, runtime_id=str(uuid4())),
            self.request("gym_coop", gym=1, incarnation=1, runtime_id="not-a-uuid"),
            self.request("teleport"),
            {**self.request("appearance_get"), "session_epoch": 4},
        ]
        for message in invalid:
            with self.subTest(message=message), self.assertRaises(ProtocolError):
                validate_world_request(message, 3)

    def test_world_fields(self):
        validate_clock({"seconds": 0, "running": True})
        validate_wallet({"seq": 65535, "delta": -999_999})
        self.assertIsNone(validate_wallet(None))
        self.assertIsNone(validate_teammate(None))
        validate_teammate(str(uuid4()))
        for check, value in ((validate_clock, {"seconds": -1, "running": True}),
                             (validate_clock, {"seconds": 1, "running": 1}),
                             (validate_wallet, {"seq": 1, "delta": 0}),
                             (validate_wallet, {"seq": 65536, "delta": 1}),
                             (validate_wallet, {"seq": 1, "delta": 1, "x": 1}),
                             (validate_teammate, "x"),
                             (validate_notice, {"id": 1, "text": "é", "to": None}),
                             (validate_notice, {"id": 1, "text": "a", "to": ["x"]}),
                             (validate_event, {"event_id": 1})):
            with self.subTest(check=check.__name__, value=value), self.assertRaises(ProtocolError):
                check(value)

    def test_replies(self):
        request_id = str(uuid4())
        validate_world_reply({"type": "world_result", "request_id": request_id, "result": {}})
        validate_world_reply({"type": "world_error", "request_id": request_id, "code": "x", "message": "y"})
        for bad in ({"type": "world_result", "request_id": request_id, "result": []},
                    {"type": "world_error", "request_id": request_id, "code": "x"},
                    {"type": "other", "request_id": request_id}):
            with self.subTest(bad=bad), self.assertRaises(ProtocolError):
                validate_world_reply(bad)


if __name__ == "__main__":
    unittest.main()


class SharedWorldSpawnTests(unittest.TestCase):
    """Phase 3: the shared world owns the spawn boards, their active-time
    clock and their persistence."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "world.sqlite3.shared-world.sqlite3"
        self.clock = FakeClock()
        self.world = self.open()
        from emerald_multiplayer.spawn_director import SpawnDirector  # noqa: F401 - import check
        tiles = self.world.spawn_director.habitat("0.16")
        xs = sorted({x for x, _ in tiles})
        ys = sorted({y for _, y in tiles})
        self.spot = (xs[len(xs) // 2], ys[len(ys) // 2])

    def tearDown(self):
        self.world.close()
        self.temp.cleanup()

    def open(self):
        return SharedWorld(self.path, WORLD, clock=self.clock, rng=random.Random(3), event_catalogue=CATALOGUE,
                           locations=LOCATIONS, spawn_rng=random.Random(11))

    def presences(self, *players):
        return {player: {"map_group": 0, "map_number": 16, "x": self.spot[0] + i, "y": self.spot[1],
                         "activity": "overworld"} for i, player in enumerate(players)}

    def run_for(self, seconds, presences):
        for _ in range(seconds):
            self.clock.now += 1
            self.world.tick_spawns(presences)

    def test_nothing_spawns_or_ages_while_nobody_is_online(self):
        self.assertFalse(self.world.tick_spawns(self.presences("a")))
        self.assertEqual(self.world.spawn_boards.keys(), [])

    def test_players_on_one_map_see_the_same_wild_pokemon(self):
        a, b = str(uuid4()), str(uuid4())
        self.world.set_active_players(2)
        presences = self.presences(a, b)
        self.run_for(30, presences)
        view_a = self.world.spawn_view(a, presences[a])
        view_b = self.world.spawn_view(b, presences[b])
        self.assertGreater(len(view_a["slots"]), 0)
        self.assertEqual(view_a, view_b)

    def test_first_claim_wins_and_a_catch_is_durable_at_once(self):
        a, b = str(uuid4()), str(uuid4())
        self.world.set_active_players(2)
        presences = self.presences(a, b)
        self.run_for(5, presences)
        spawn_id = self.world.spawn_view(a, presences[a])["slots"][0]["spawn_id"]
        self.assertEqual(self.world.spawn_action(a, "claim", spawn_id, None), "granted")
        self.assertEqual(self.world.spawn_action(b, "claim", spawn_id, None), "busy")
        self.assertEqual(self.world.spawn_action(a, "result", spawn_id, "caught"), "consumed")
        # A crash right after the catch (no close()): the record is already saved.
        crashed = SharedWorld(self.path, WORLD, clock=self.clock, rng=random.Random(3), event_catalogue=CATALOGUE,
                              locations=LOCATIONS, spawn_rng=random.Random(5))
        try:
            self.assertEqual(crashed.spawn_action(b, "claim", spawn_id, None), "gone")
        finally:
            crashed._db.close()
            crashed._db = None

    def test_restart_keeps_pokemon_their_remaining_time_and_claims(self):
        a = str(uuid4())
        self.world.set_active_players(1)
        presences = self.presences(a)
        self.run_for(10, presences)
        view = self.world.spawn_view(a, presences[a])
        spawn_id = view["slots"][0]["spawn_id"]
        self.world.spawn_action(a, "claim", spawn_id, None)
        self.world.set_active_players(0)
        self.world.close()
        self.clock.now += 86400  # the host is down for a day: nothing ages
        self.world = self.open()
        again = self.world.spawn_view(a, presences[a])
        self.assertEqual([(s["spawn_id"], s["species"], s["personality"], s["x"], s["y"]) for s in again["slots"]],
                         [(s["spawn_id"], s["species"], s["personality"], s["x"], s["y"]) for s in view["slots"]])
        before = {s["spawn_id"]: s["seconds_left"] for s in view["slots"]}
        for slot in again["slots"]:
            self.assertEqual(slot["seconds_left"], before[slot["spawn_id"]])
        self.assertTrue(next(s for s in again["slots"] if s["spawn_id"] == spawn_id)["mine"])

    def test_zero_player_period_freezes_spawn_timers(self):
        a = str(uuid4())
        self.world.set_active_players(1)
        presences = self.presences(a)
        self.run_for(10, presences)
        left = {s["spawn_id"]: s["seconds_left"] for s in self.world.spawn_view(a, presences[a])["slots"]}
        self.world.set_active_players(0)
        self.clock.now += 7200
        self.world.tick_spawns({})
        now = {s["spawn_id"]: s["seconds_left"] for s in self.world.spawn_view(a, presences[a])["slots"]}
        self.assertEqual(now, left)

    def test_disconnected_claimant_keeps_the_pokemon_and_reports_once(self):
        a, b = str(uuid4()), str(uuid4())
        self.world.set_active_players(2)
        presences = self.presences(a, b)
        self.run_for(5, presences)
        spawn_id = self.world.spawn_view(a, presences[a])["slots"][0]["spawn_id"]
        self.world.spawn_action(a, "claim", spawn_id, None)
        self.world.player_disconnected(a)
        self.world.set_active_players(1)
        self.run_for(60, {b: presences[b]})
        self.assertEqual(self.world.spawn_action(b, "claim", spawn_id, None), "busy")
        self.world.player_connected(a)
        self.assertEqual(self.world.spawn_action(a, "result", spawn_id, "caught"), "consumed")
        self.assertEqual(self.world.spawn_action(a, "result", spawn_id, "caught"), "gone")
