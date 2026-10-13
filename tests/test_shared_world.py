"""Host-owned shared world: clock, appearances, notices and World Events."""
from __future__ import annotations

from pathlib import Path
import random
import tempfile
import unittest
from uuid import uuid4

from emerald_multiplayer.balance import BALANCE
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
                           event_catalogue=CATALOGUE, locations=LOCATIONS)

    # --------------------------------------------------------------- clock
    def test_clock_runs_twelve_times_real_time_only_while_players_are_online(self):
        start = self.world.world_seconds()
        self.assertEqual(start, BALANCE.clock_start_seconds)
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
