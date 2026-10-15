"""Dormant legendary World Events and their wake-up conditions (expansion Phase 10)."""
from __future__ import annotations

from pathlib import Path
import random
import tempfile
import unittest
from uuid import uuid4

from emerald_multiplayer import event_conditions as ec
from emerald_multiplayer.balance import BALANCE
from emerald_multiplayer.shared_world import SharedWorld
from emerald_multiplayer.shared_world_protocol import validate_extras

WORLD = "11111111-1111-4111-8111-111111111111"
CATALOGUE = {
    "rare": [{"name": "ABSOL", "species": 359, "types": ["dark"]}],
    "legendary": [{"name": "GROUDON", "species": 383, "types": ["ground"]}],
    "mega": [], "mythical": [], "mega_legendary": [],
}
LOCATIONS = [{"name": "ROUTE 111", "map_group": 0, "map_number": 27, "x": 10, "y": 7, "min_level": 0, "themes": ["ground"]}]
HERE = {"map_group": 0, "map_number": 27, "activity": "overworld"}
ELSEWHERE = {"map_group": 0, "map_number": 16, "activity": "overworld"}


class FakeClock:
    now = 1000.0

    def __call__(self):
        return self.now


class ConditionRuleTests(unittest.TestCase):
    def test_conditions_follow_the_species_types(self):
        self.assertEqual(ec.condition_for_types(["water"]), "rain")
        self.assertEqual(ec.condition_for_types(["electric", "flying"]), "rain")
        self.assertEqual(ec.condition_for_types(["ground"]), "sand")
        self.assertEqual(ec.condition_for_types(["dragon", "psychic"]), "night")   # the first matching type decides
        self.assertEqual(ec.condition_for_types(["ice", "flying"]), "evening")
        self.assertEqual(ec.condition_for_types(["fire", "flying"]), "day")
        self.assertEqual(ec.condition_for_types(["dragon", "flying"]), "together")
        self.assertEqual(ec.condition_for_types([]), "together")
        self.assertEqual(set(ec.LABELS), ec.KINDS)

    def test_is_met(self):
        def met(kind, tod="day", weather=(), n=0):
            return ec.is_met(kind, time_of_day=tod, weather_names=weather, players_on_map=n)

        self.assertTrue(met("night", "night") and not met("night", "evening"))
        self.assertTrue(met("day", "day") and not met("day", "morning"))
        self.assertTrue(met("evening", "evening"))
        self.assertTrue(met("rain", weather={"WEATHER_DOWNPOUR"}))
        self.assertTrue(met("rain", weather={"WEATHER_RAIN_THUNDERSTORM", "WEATHER_SUNNY"}))
        self.assertFalse(met("rain", weather={"WEATHER_SUNNY"}))
        self.assertTrue(met("sand", weather={"WEATHER_SANDSTORM"}))
        self.assertFalse(met("sand", weather={"WEATHER_RAIN"}))
        self.assertFalse(met("together", n=1))
        self.assertTrue(met("together", n=2))
        with self.assertRaises(ValueError):
            met("snow")


class DormantEventTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "world.shared-world.sqlite3"
        self.clock = FakeClock()
        self.world = self.open()
        self.addCleanup(lambda: self.world.close())
        self.rain = next(v for k, v in self.world.spawn_director.catalogue["weather"].items() if k == "WEATHER_RAIN")
        self.sand = next(v for k, v in self.world.spawn_director.catalogue["weather"].items() if k == "WEATHER_SANDSTORM")

    def open(self, chance=1.0):
        return SharedWorld(self.path, WORLD, clock=self.clock, rng=random.Random(3), event_catalogue=CATALOGUE,
                           locations=LOCATIONS, event_condition_chance=chance)

    def spawn(self, category="legendary"):
        self.world.set_active_players(1)
        return self.world.spawn_event(progression_level=40, category=category)

    def test_a_legendary_event_starts_dormant_and_is_not_offered(self):
        full = self.spawn()
        self.assertEqual(full["species"], 383)                  # the spawn call itself reports the event
        self.assertIsNone(self.world.event_view())              # ... but no game is shown it
        status = self.world.event_status()
        self.assertEqual((status["name"], status["place"]), ("Something stirs", "ROUTE 111"))
        self.assertEqual(status["waiting"], "Wakes in a sandstorm")
        self.assertNotIn("GROUDON", repr(status))               # the species is a surprise
        self.assertEqual(self.world.claim_event(str(uuid4()), full["event_id"]), "gone")
        text = [self.world.notice_view()["text"]]
        self.clock.now += BALANCE.notice_seconds + 1
        text.append(self.world.notice_view()["text"])
        self.assertIn("Something stirs near|ROUTE 111", text[0])
        self.assertIn("It wakes in a sandstorm", text[1])
        nav = self.world.nav_view({})
        validate_extras({"bases": [], "nav": nav})
        self.assertEqual(nav["event"]["waiting"], "Wakes in a sandstorm")

    def test_it_wakes_when_a_player_reports_the_weather_and_stays_awake(self):
        event_id = self.spawn()["event_id"]
        player = str(uuid4())
        self.assertFalse(self.world.tick_event_conditions({player: {**HERE, "weather": self.rain}}))
        self.assertIsNone(self.world.event_view())
        self.clock.now += 100
        self.assertTrue(self.world.tick_event_conditions({player: {**ELSEWHERE, "weather": self.sand}}))  # anywhere
        view = self.world.event_view()
        self.assertEqual((view["event_id"], view["species"]), (event_id, 383))
        self.assertIsNone(self.world.event_status()["waiting"])
        self.assertIn("WORLD EVENT! GROUDON", self.world.notice_view()["text"] + " ".join(
            n["text"] for n in self.world._notice_queue))
        self.assertFalse(self.world.tick_event_conditions({player: {**HERE}}))          # latched: nothing more to do
        self.assertIsNotNone(self.world.event_view())
        self.assertEqual(self.world.claim_event(player, event_id), "granted")

    def test_waking_leaves_time_to_get_there(self):
        self.spawn()
        self.clock.now += BALANCE.event_duration_seconds - 20       # almost expired, still asleep
        self.world.set_active_players(1)
        self.assertTrue(self.world.tick_event_conditions({"p": {**HERE, "weather": self.sand}}))
        self.assertGreaterEqual(self.world.event_view()["seconds_left"], ec.WAKE_GRACE_SECONDS - 1)

    def test_a_dormant_event_gives_no_reminders_and_expires_quietly(self):
        self.spawn()
        self.world.notice_view()
        self.clock.now += BALANCE.notice_seconds + 1
        self.world.notice_view()
        self.clock.now += BALANCE.event_duration_seconds - 100
        self.world.tick_events(1, lambda: 40)
        self.assertIsNone(self.world.notice_view())             # no "10 minutes left" for something nobody sees
        self.clock.now += 200
        self.assertTrue(self.world.tick_events(1, lambda: 40))
        self.assertIsNone(self.world.event_status())
        self.assertIn("slipped away", self.world.notice_view()["text"])

    def test_together_needs_two_players_on_the_map_at_once(self):
        catalogue = {**CATALOGUE, "legendary": [{"name": "RAYQUAZA", "species": 384, "types": ["dragon", "flying"]}]}
        self.world.close()
        self.world = SharedWorld(self.path, WORLD, clock=self.clock, rng=random.Random(3), event_catalogue=catalogue,
                                 locations=LOCATIONS, event_condition_chance=1.0)
        self.spawn()
        self.assertEqual(self.world.event_status()["waiting"], "Wakes when trainers gather")
        a, b = "a", "b"
        self.assertFalse(self.world.tick_event_conditions({a: HERE, b: ELSEWHERE}))
        self.assertFalse(self.world.tick_event_conditions({a: HERE, b: {**HERE, "activity": "unavailable"}}))
        self.assertTrue(self.world.tick_event_conditions({a: HERE, b: {**HERE, "activity": "battle"}}))
        self.assertIsNotNone(self.world.event_view())

    def test_night_uses_the_world_clock(self):
        catalogue = {**CATALOGUE, "legendary": [{"name": "DARKRAI", "species": 491, "types": ["dark"]}]}
        self.world.close()
        self.world = SharedWorld(self.path, WORLD, clock=self.clock, rng=random.Random(3), event_catalogue=catalogue,
                                 locations=LOCATIONS, event_condition_chance=1.0)
        self.spawn()                                             # the world starts at 08:00
        self.assertEqual(self.world.event_status()["waiting"], "Wakes at night")
        self.assertFalse(self.world.tick_event_conditions({}))
        # 08:00 -> night is 12+ world hours = 1+ real hours at x12; the event itself would expire first, so
        # the clock is moved without time passing for the event (nobody was counted).
        self.world._clock.seconds = 23 * 3600
        self.world._clock.running_since = None
        self.assertEqual(self.world.time_of_day(), "night")
        self.assertTrue(self.world.tick_event_conditions({}))
        self.assertIsNotNone(self.world.event_view())

    def test_rare_events_are_never_dormant(self):
        self.spawn("rare")
        self.assertIsNotNone(self.world.event_view())
        self.assertIsNone(self.world.event_status()["waiting"])

    def test_dormant_and_awake_states_survive_a_host_restart(self):
        event_id = self.spawn()["event_id"]
        self.world.close()
        self.world = self.open()
        self.world.set_active_players(1)
        self.assertIsNone(self.world.event_view())
        self.assertEqual(self.world.event_status()["waiting"], "Wakes in a sandstorm")
        self.assertTrue(self.world.tick_event_conditions({"p": {**HERE, "weather": self.sand}}))
        self.world.close()
        self.world = self.open()
        self.assertEqual(self.world.event_view()["event_id"], event_id)

    def test_with_the_chance_at_zero_nothing_changes(self):
        self.world.close()
        self.world = self.open(chance=0.0)
        self.spawn()
        self.assertIsNotNone(self.world.event_view())


if __name__ == "__main__":
    unittest.main()
