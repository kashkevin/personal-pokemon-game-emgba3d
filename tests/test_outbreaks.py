"""Mass outbreaks on the shared spawn system (EmeraldTogether Phase 4)."""
from __future__ import annotations

import json
from pathlib import Path
import random
import tempfile
import unittest
from uuid import uuid4

from emerald_multiplayer import shared_spawns as ss
from emerald_multiplayer.outbreaks import DEFAULT_SETTINGS, OutbreakSettings, Outbreaks, load_outbreak_settings
from emerald_multiplayer.shared_spawn_catalogue import CATALOGUE
from emerald_multiplayer.shared_spawns import SpawnBoards
from emerald_multiplayer.shared_world import SharedWorld
from emerald_multiplayer.spawn_director import SpawnDirector, WEATHER_TYPES

ROUTE101 = "0.16"
ZIGZAGOON = 263
WEATHER_RAIN = CATALOGUE["weather"]["WEATHER_RAIN"]


class ActiveClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def route101_tile(director):
    tiles = director.habitat(ROUTE101)
    xs = sorted({x for x, _ in tiles})
    ys = sorted({y for _, y in tiles})
    return xs[len(xs) // 2], ys[len(ys) // 2]


class SettingsTests(unittest.TestCase):
    def test_defaults(self):
        s = DEFAULT_SETTINGS
        self.assertTrue(s.enabled)
        self.assertEqual((s.share, s.shiny_odds, s.regions, s.map_types), (0.7, 4096, ("hoenn",), ("MAP_TYPE_ROUTE",)))
        self.assertLessEqual(s.duration[0], s.duration[1])

    def test_invalid_values_are_refused(self):
        for changes in ({"share": 0}, {"share": 1.5}, {"shiny_odds": 0}, {"duration": [60, 30]},
                        {"cooldown": [0, 10]}, {"tier_weights": {"COMMON": -1}}, {"tier_weights": {"LEGEND": 5}},
                        {"tier_weights": {"COMMON": 0}}, {"species": [0]}, {"species_weights": {"263": -1}},
                        {"enabled": 1}, {"level_margin": -1}, {"reminder_seconds": [0]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                OutbreakSettings(**changes)

    def test_the_worlds_file_overrides_defaults_and_rejects_typos(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "world.sqlite3.outbreaks.json"
            self.assertIs(load_outbreak_settings(path), DEFAULT_SETTINGS)  # no file: the defaults
            path.write_text(json.dumps({"duration": [600, 900], "cooldown": [1200, 1800], "species": [ZIGZAGOON],
                                        "species_weights": {"263": 2.5}, "tier_weights": {"COMMON": 1}}))
            settings = load_outbreak_settings(path)
            self.assertEqual((settings.duration, settings.cooldown, settings.species),
                             ((600.0, 900.0), (1200.0, 1800.0), (ZIGZAGOON,)))
            self.assertEqual(settings.species_weights, {ZIGZAGOON: 2.5})
            path.write_text(json.dumps({"durations": [600, 900]}))
            with self.assertRaisesRegex(ValueError, "unknown outbreak settings"):
                load_outbreak_settings(path)
            path.write_text(json.dumps({"share": 2}))
            with self.assertRaisesRegex(ValueError, "share"):
                load_outbreak_settings(path)


class OutbreakTestCase(unittest.TestCase):
    settings = DEFAULT_SETTINGS

    def setUp(self):
        self.clock = ActiveClock()
        self.boards = SpawnBoards(self.clock)
        self.director = SpawnDirector(CATALOGUE, self.boards, rng=random.Random(7), clock=self.clock)
        self.notices: list[str] = []
        self.outbreaks = Outbreaks(self.director, settings=self.settings, rng=random.Random(5), clock=self.clock,
                                   notice=self.notices.append)


class ChoiceTests(OutbreakTestCase):
    def test_candidates_are_hoenn_routes_the_players_can_reach(self):
        early = self.outbreaks.candidates(10, night=False)
        maps = {key for key, _, _ in early}
        self.assertIn(ROUTE101, maps)
        for key in maps:
            entry = CATALOGUE["maps"][key]
            self.assertEqual((entry["region"], entry["map_type"]), ("hoenn", "MAP_TYPE_ROUTE"))
            self.assertLessEqual(min(min(pair) for pair in entry["levels"]), 15)
        late = {key for key, _, _ in self.outbreaks.candidates(100, night=False)}
        self.assertLess(len(maps), len(late))
        self.assertIn("0.38", late)  # Route 119

    def test_each_species_is_the_most_evolved_one_the_maps_levels_allow(self):
        for key, species, weight in self.outbreaks.candidates(10, night=False):
            low = min(min(pair) for pair in CATALOGUE["maps"][key]["levels"])
            members = [m for m in CATALOGUE["members"] if m[0] == species]
            self.assertTrue(members and all(min_level <= low for _, min_level, _ in members), (key, species))
            self.assertGreater(weight, 0)

    def test_configured_species_and_weights_decide(self):
        only = Outbreaks(self.director, settings=OutbreakSettings(species=(ZIGZAGOON,)), clock=self.clock)
        chosen = only.candidates(100, night=False)
        self.assertTrue(chosen)
        self.assertEqual({species for _, species, _ in chosen}, {ZIGZAGOON})
        never = Outbreaks(self.director, settings=OutbreakSettings(species_weights={ZIGZAGOON: 0}), clock=self.clock)
        self.assertNotIn(ZIGZAGOON, {species for _, species, _ in never.candidates(100, night=False)})

    def test_the_maps_weather_weighs_in(self):
        x, y = route101_tile(self.director)
        rain = {"p": {"map_group": 0, "map_number": 16, "x": x, "y": y, "activity": "overworld",
                      "weather": WEATHER_RAIN}}
        clear = {"p": {**rain["p"], "weather": CATALOGUE["weather"]["WEATHER_NONE"]}}
        wet = {s: w for k, s, w in self.outbreaks.candidates(10, night=False, presences=rain) if k == ROUTE101}
        dry = {s: w for k, s, w in self.outbreaks.candidates(10, night=False, presences=clear) if k == ROUTE101}
        self.assertEqual(set(wet), set(dry))
        self.assertTrue(all(wet[s] >= dry[s] for s in wet))
        self.assertTrue(any(wet[s] == dry[s] * 3 for s in wet))  # the Phase 2 rain boost (Water x3)
        self.assertEqual(WEATHER_TYPES["WEATHER_RAIN"][0], "TYPE_WATER")


class LifecycleTests(OutbreakTestCase):
    settings = OutbreakSettings(first_delay=(300, 300), duration=(600, 600), cooldown=(900, 900))

    def test_first_outbreak_after_its_delay_with_a_notice(self):
        self.clock.now += 299
        self.assertFalse(self.outbreaks.tick(lambda: 10))
        self.assertEqual(self.outbreaks.active(), {})
        self.clock.now += 1
        self.assertTrue(self.outbreaks.tick(lambda: 10))
        view = self.outbreaks.view()
        self.assertEqual(view["seconds_left"], 600)
        key = f"{view['map_group']}.{view['map_number']}"
        self.assertEqual(self.outbreaks.active(), {key: {"species": view["species"], "share": 0.7, "shiny_odds": 4096}})
        self.assertEqual(len(self.notices), 1)
        first, second = self.notices[0].split("|")
        self.assertEqual(first, f"MASS OUTBREAK: {view['name']}!")
        self.assertIn(view["place"], second)
        self.assertLessEqual(max(len(first), len(second)), 32)

    def test_it_ends_after_its_duration_and_the_cooldown_follows(self):
        self.outbreaks.start(10, map_key=ROUTE101, species=ZIGZAGOON)
        self.clock.now += 599
        self.outbreaks.tick(lambda: 10)
        self.assertTrue(self.outbreaks.active())
        self.clock.now += 1
        self.assertTrue(self.outbreaks.tick(lambda: 10))
        self.assertEqual(self.outbreaks.active(), {})
        self.assertEqual(self.notices[-1], "The ZIGZAGOON outbreak|on ROUTE 101 has ended.")
        self.clock.now += 899
        self.assertFalse(self.outbreaks.tick(lambda: 10))
        self.clock.now += 1
        self.assertTrue(self.outbreaks.tick(lambda: 10))
        self.assertTrue(self.outbreaks.active())

    def test_a_reminder_five_minutes_before_the_end(self):
        self.outbreaks.start(10, map_key=ROUTE101, species=ZIGZAGOON)
        self.clock.now += 300
        self.assertTrue(self.outbreaks.tick(lambda: 10))
        self.assertIn("5:00 left", self.notices[-1])
        count = len(self.notices)
        self.clock.now += 10
        self.assertFalse(self.outbreaks.tick(lambda: 10))
        self.assertEqual(len(self.notices), count)

    def test_no_reachable_map_retries_later(self):
        none = Outbreaks(self.director, settings=OutbreakSettings(first_delay=(1, 1), regions=("nowhere",)),
                         clock=self.clock)
        self.clock.now += 1
        self.assertFalse(none.tick(lambda: 10))
        self.assertIsNone(none.view())

    def test_state_keeps_remaining_durations_only(self):
        self.outbreaks.start(10, map_key=ROUTE101, species=ZIGZAGOON)
        self.clock.now += 100
        state = json.loads(json.dumps(self.outbreaks.to_state()))
        self.assertNotIn("expires", state["current"])
        self.assertEqual(state["current"]["remaining"], 500)
        later = ActiveClock()
        later.now = 5.0  # a restarted host: a new process clock
        again = Outbreaks(self.director, settings=self.settings, clock=later, state=state)
        self.assertEqual(again.view()["seconds_left"], 500)
        self.assertEqual((again.view()["species"], again.view()["outbreak_id"]), (ZIGZAGOON, 1))
        self.assertEqual(again.next_id, 2)

    def test_disabled_outbreaks_end_and_never_start(self):
        self.outbreaks.start(10, map_key=ROUTE101, species=ZIGZAGOON)
        off = Outbreaks(self.director, settings=OutbreakSettings(enabled=False, first_delay=(1, 1)),
                        clock=self.clock, state=self.outbreaks.to_state())
        self.assertTrue(off.tick(lambda: 10))
        self.assertIsNone(off.view())
        self.clock.now += 10_000
        self.assertFalse(off.tick(lambda: 10))


class BoardTrimTests(unittest.TestCase):
    def test_end_returns_the_map_to_eight_keeping_claimed_pokemon(self):
        clock = ActiveClock()
        board = ss.SpawnBoard(ROUTE101, clock)
        board.set_outbreak(True)
        ids = []
        for i in range(12):
            clock.now += 1
            kind = ss.KIND_OUTBREAK if i % 2 else ss.KIND_NORMAL
            ids.append(board.create(species=263, level=3, personality=i, shiny=False, x=i, y=0, lifetime=900, kind=kind))
        claimed = [ids[1], ids[3]]  # two outbreak Pokemon somebody is battling
        for i, spawn_id in enumerate(claimed):
            self.assertEqual(board.claim(f"p{i}", spawn_id), ss.GRANTED)
        board.set_outbreak(False)
        retired = board.trim()
        self.assertEqual(len(retired), 4)
        self.assertEqual(board.live_count(), 8)
        self.assertTrue(all(board.get(spawn_id) is not None for spawn_id in claimed))
        # open outbreak Pokemon go first, the oldest first
        self.assertEqual(retired, [ids[5], ids[7], ids[9], ids[11]])
        self.assertEqual(board.trim(), [])
        self.assertIsNone(board.create(species=263, level=3, personality=99, shiny=False, x=40, y=0, lifetime=900))

    def test_claims_alone_can_keep_the_map_above_eight_for_a_while(self):
        clock = ActiveClock()
        board = ss.SpawnBoard(ROUTE101, clock)
        board.set_outbreak(True)
        ids = [board.create(species=263, level=3, personality=i, shiny=False, x=i, y=0, lifetime=900,
                            kind=ss.KIND_OUTBREAK) for i in range(12)]
        for i, spawn_id in enumerate(ids[:10]):
            board.claim(f"p{i}", spawn_id)
        board.set_outbreak(False)
        self.assertEqual(len(board.trim()), 2)  # only the two open ones can go
        self.assertEqual(board.live_count(), 10)


class SharedWorldOutbreakTests(unittest.TestCase):
    """The shared world runs the scheduler on its active clock and saves it."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "world.sqlite3.shared-world.sqlite3"
        self.now = 1000.0
        self.settings = OutbreakSettings(first_delay=(30, 30), duration=(600, 600), cooldown=(1200, 1200))
        self.world = self.open()
        tiles = self.world.spawn_director.habitat(ROUTE101)
        xs = sorted({x for x, _ in tiles})
        ys = sorted({y for _, y in tiles})
        self.spot = (xs[len(xs) // 2], ys[len(ys) // 2])

    def tearDown(self):
        self.world.close()
        self.temp.cleanup()

    def clock(self):
        return self.now

    def open(self):
        return SharedWorld(self.path, "11111111-1111-1111-1111-111111111111", clock=self.clock, rng=random.Random(3),
                           event_catalogue={}, locations=[], spawn_rng=random.Random(11),
                           outbreak_settings=self.settings)

    def presences(self, *players):
        return {player: {"map_group": 0, "map_number": 16, "x": self.spot[0] + i, "y": self.spot[1],
                         "activity": "overworld"} for i, player in enumerate(players)}

    def run_for(self, seconds, presences, watch=None):
        for _ in range(seconds):
            self.now += 1
            self.world.tick_spawns(presences, lambda: 10)
            if watch is not None:
                watch()

    def board(self):
        return self.world.spawn_boards.board(ROUTE101)

    def test_a_disconnected_claimant_lets_go_of_its_spawn_after_the_grace(self):
        # The host's disconnect reached the World Event claim only (the spawn lines sat after another method's
        # return): the shared Pokemon a player left mid-encounter stayed busy for everyone until they came back.
        a, b = str(uuid4()), str(uuid4())
        self.world.set_active_players(2)
        presences = self.presences(a, b)
        self.run_for(60, presences)
        spawn = self.world.spawn_view(a, presences[a])["slots"][0]["spawn_id"]
        self.assertEqual(self.world.spawn_action(a, "claim", spawn, None), ss.GRANTED)
        self.assertEqual(self.world.spawn_action(b, "claim", spawn, None), ss.BUSY)
        self.world.player_disconnected(a)
        self.now += ss.CLAIM_GRACE_SECONDS + 1
        self.world.tick_spawns({b: presences[b]}, lambda: 10)
        # no longer held: back to everyone, or gone with its lifetime (an ordinary spawn's runs out first)
        self.assertIn(self.world.spawn_action(b, "claim", spawn, None), (ss.GRANTED, ss.GONE))

    def test_an_outbreak_fills_exactly_twelve_shared_slots_with_its_species(self):
        a, b = str(uuid4()), str(uuid4())
        self.world.set_active_players(2)
        self.world.outbreaks.start(10, map_key=ROUTE101, species=ZIGZAGOON)
        presences = self.presences(a, b)
        most = []
        self.run_for(120, presences, watch=lambda: most.append(self.board().live_count()))
        self.assertEqual(max(most), 12)  # exactly 12 in total, never 8 + 12
        view_a = self.world.spawn_view(a, presences[a])
        self.assertEqual(view_a, self.world.spawn_view(b, presences[b]))
        self.assertGreaterEqual(len(view_a["slots"]), 10)
        outbreak = [s for s in view_a["slots"] if s["kind"] == "outbreak"]
        self.assertGreaterEqual(len(outbreak), len(view_a["slots"]) // 2)
        self.assertTrue(all(s["species"] == ZIGZAGOON for s in outbreak))

    def test_nothing_happens_while_nobody_is_online_and_a_restart_resumes_it(self):
        a = str(uuid4())
        self.world.set_active_players(1)
        self.run_for(29, self.presences(a))
        self.assertIsNone(self.world.outbreak_view())
        self.world.set_active_players(0)
        self.now += 86_400  # a day with nobody online: the first delay does not run out
        self.world.tick_spawns(self.presences(a), lambda: 10)
        self.assertIsNone(self.world.outbreak_view())
        self.world.set_active_players(1)
        self.run_for(1, self.presences(a))
        started = self.world.outbreak_view()
        self.assertIsNotNone(started)
        self.assertTrue(any("MASS OUTBREAK" in n["text"] for n in self.world._notice_queue + [self.world._notice]
                            if n is not None))
        self.run_for(100, self.presences(a))
        self.world.set_active_players(0)
        self.world.close()
        self.now += 3600  # the host is down for an hour
        self.world = self.open()
        again = self.world.outbreak_view()
        self.assertEqual({k: again[k] for k in ("outbreak_id", "species", "map_group", "map_number")},
                         {k: started[k] for k in ("outbreak_id", "species", "map_group", "map_number")})
        self.assertEqual(again["seconds_left"], started["seconds_left"] - 100)

    def test_the_end_returns_the_map_to_eight_without_duplicates(self):
        a, b = str(uuid4()), str(uuid4())
        self.world.set_active_players(2)
        self.world.outbreaks.start(10, map_key=ROUTE101, species=ZIGZAGOON)
        presences = self.presences(a, b)
        self.run_for(120, presences)
        board = self.board()
        claimed = next(s.spawn_id for s in board.live() if s.kind == ss.KIND_OUTBREAK)
        self.assertEqual(self.world.spawn_action(a, "claim", claimed, None), "granted")
        presences[a] = {**presences[a], "activity": "battle"}  # battling it, so the claim holds
        seen = {s.spawn_id for s in board.live()}
        self.run_for(480, presences)  # past the 600 s duration
        self.assertIsNone(self.world.outbreak_view())
        ids = [s.spawn_id for s in board.live()]
        self.assertLessEqual(len(ids), 9)  # 8, or 9 while the claim holds
        self.assertIn(claimed, ids)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertFalse(board.outbreak_active)
        self.assertEqual(self.world.spawn_action(a, "result", claimed, "caught"), "consumed")
        self.run_for(60, presences)
        self.assertLessEqual(board.live_count(), 8)
        new = {s.spawn_id for s in board.live()} - seen
        self.assertTrue(all(spawn_id > max(seen) for spawn_id in new))  # ids are never reused


if __name__ == "__main__":
    unittest.main()
