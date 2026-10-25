"""The host's shared wild spawn director (Phase 3) over the generated catalogue."""
import random
import unittest

from emerald_multiplayer import shared_spawns as ss
from emerald_multiplayer.shared_spawn_catalogue import CATALOGUE
from emerald_multiplayer.shared_spawns import SpawnBoards
from emerald_multiplayer.spawn_director import REPEAT_TRIES, SpawnDirector, SpawnTuning, WEATHER_TYPES

ROUTE101 = "0.16"
ROUTE102 = "0.17"


class ActiveClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def presence(x, y, *, map_number=16, activity="overworld", weather=None):
    value = {"map_group": 0, "map_number": map_number, "x": x, "y": y, "activity": activity}
    if weather is not None:
        value["weather"] = weather
    return value


def route101_player_tile(director):
    """A walkable spot in Route 101's main grass, as the habitat shows."""
    tiles = director.habitat(ROUTE101)
    xs = sorted({x for x, _ in tiles})
    ys = sorted({y for _, y in tiles})
    return xs[len(xs) // 2], ys[len(ys) // 2]


class DirectorTestCase(unittest.TestCase):
    def setUp(self):
        self.clock = ActiveClock()
        self.boards = SpawnBoards(self.clock)
        self.director = SpawnDirector(CATALOGUE, self.boards, rng=random.Random(7), clock=self.clock)

    def step(self, presences, seconds=1.0, **kw):
        self.clock.now += seconds
        return self.director.update(presences, night=kw.pop("night", False), **kw)

    def fill(self, presences, seconds=40, **kw):
        for _ in range(seconds):
            self.step(presences, **kw)


class CatalogueTests(unittest.TestCase):
    def test_catalogue_covers_hoenn_routes_and_caves(self):
        names = {entry["constant"] for entry in CATALOGUE["maps"].values()}
        for constant in ("MAP_ROUTE101", "MAP_ROUTE102", "MAP_ROUTE119", "MAP_PETALBURG_WOODS",
                         "MAP_GRANITE_CAVE_1F", "MAP_ROUTE111"):
            self.assertIn(constant, names)
        self.assertEqual(len(CATALOGUE["families"]), 312)

    def test_habitat_tiles_lie_inside_their_maps(self):
        for key, entry in CATALOGUE["maps"].items():
            for y, x0, length, elevation in entry["tiles"]:
                self.assertTrue(0 <= y < entry["height"] and 0 <= x0 and x0 + length <= entry["width"], key)
                self.assertNotIn(elevation, (0, 15), key)


class FillTests(DirectorTestCase):
    def test_nothing_spawns_without_players(self):
        self.assertFalse(self.step({}))
        self.assertFalse(self.step({"p": None}))
        self.assertEqual(self.boards.keys(), [])

    def test_a_visited_map_fills_to_eight_near_the_player(self):
        x, y = route101_player_tile(self.director)
        players = {"p": presence(x, y)}
        self.assertTrue(self.step(players))
        board = self.boards.board(ROUTE101)
        self.assertEqual(board.live_count(), 3)  # the first burst
        self.fill(players)
        self.assertLessEqual(board.live_count(), ss.NORMAL_SLOT_LIMIT)
        self.assertGreaterEqual(board.live_count(), 6)
        habitat = self.director.habitat(ROUTE101)
        for slot in board.live():
            self.assertIn((slot.x, slot.y), habitat)
            self.assertGreater(abs(slot.x - x) + abs(slot.y - y), 0)

    def test_new_spawns_keep_clear_of_players(self):
        x, y = route101_player_tile(self.director)
        players = {"p": presence(x, y)}
        self.step(players)
        tuning = self.director.tuning
        for slot in self.boards.board(ROUTE101).live():
            self.assertGreater(abs(slot.x - x) + abs(slot.y - y), tuning.keep_clear)
            self.assertLessEqual(abs(slot.x - x), tuning.near_x)
            self.assertLessEqual(abs(slot.y - y), tuning.near_y)

    def test_species_and_levels_follow_the_pool_and_the_map(self):
        x, y = route101_player_tile(self.director)
        players = {"p": presence(x, y)}
        levels = {low for low, high in CATALOGUE["maps"][ROUTE101]["levels"]} | \
                 {high for low, high in CATALOGUE["maps"][ROUTE101]["levels"]}
        allowed = {}
        for first, count, tier, habitat, time, type1, type2 in CATALOGUE["families"]:
            if habitat & 1:
                for species, min_level, depth in CATALOGUE["members"][first:first + count]:
                    allowed[species] = min_level
        seen = []
        for _ in range(30):
            self.boards = SpawnBoards(self.clock)
            self.director.boards = self.boards
            self.step(players, seconds=31)
            seen.extend(self.boards.board(ROUTE101).live())
        self.assertGreater(len(seen), 50)
        for slot in seen:
            self.assertIn(slot.species, allowed)
            self.assertLessEqual(allowed[slot.species], slot.level)
            self.assertTrue(min(levels) <= slot.level <= max(levels))
            self.assertTrue(0 <= slot.personality <= 0xFFFFFFFF)

    def test_outbreak_raises_the_limit_to_twelve_and_favours_its_species(self):
        x, y = route101_player_tile(self.director)
        players = {"p": presence(x, y)}
        outbreak = {ROUTE101: {"species": 263, "share": 1.0, "shiny_odds": 4096}}
        self.fill(players, outbreaks=outbreak)
        board = self.boards.board(ROUTE101)
        self.assertEqual(board.limit(), ss.OUTBREAK_SLOT_LIMIT)
        self.assertGreater(board.live_count(), ss.NORMAL_SLOT_LIMIT)
        self.assertLessEqual(board.live_count(), ss.OUTBREAK_SLOT_LIMIT)
        self.assertTrue(all(slot.species == 263 and slot.kind == ss.KIND_OUTBREAK for slot in board.live()))

    def test_shiny_odds_come_from_the_host_roll(self):
        x, y = route101_player_tile(self.director)
        outbreak = {ROUTE101: {"species": 263, "share": 1.0, "shiny_odds": 1}}
        self.fill({"p": presence(x, y)}, outbreaks=outbreak)
        self.assertTrue(all(slot.shiny for slot in self.boards.board(ROUTE101).live()))


class WeightTests(DirectorTestCase):
    def family_index(self, *types):
        for index, (first, count, tier, habitat, time, type1, type2) in enumerate(CATALOGUE["families"]):
            if {type1, type2} == set(types) and habitat & 1 and time == 0 and index not in CATALOGUE.get("safari_only", ()):
                return index, tier
        self.skipTest(f"no land family of type {types}")

    def weight(self, map_key, index, *, night=False, weather=None):
        return dict(self.director.species_weights(map_key, 10, night, weather))[index]

    def test_weights_match_the_engine_rules(self):
        tiers = CATALOGUE["tier_weights"]
        water, tier = self.family_index("TYPE_WATER", "TYPE_WATER")
        base = self.weight(ROUTE101, water)
        self.assertEqual(base, tiers[tier])
        self.assertEqual(self.weight(ROUTE101, water, weather="WEATHER_RAIN"), base * 3)
        self.assertEqual(self.weight(ROUTE101, water, weather="WEATHER_RAIN_THUNDERSTORM"), base * 2)
        fire, tier = self.family_index("TYPE_FIRE", "TYPE_FIRE")
        self.assertEqual(self.weight(ROUTE101, fire, weather="WEATHER_DROUGHT"), tiers[tier] * 3)

    def test_area_boost_applies_on_its_maps(self):
        woods = next(key for key, entry in CATALOGUE["maps"].items() if entry["constant"] == "MAP_PETALBURG_WOODS")
        self.assertIn("TYPE_BUG", CATALOGUE["maps"][woods]["boost"])
        bug, tier = self.family_index("TYPE_BUG", "TYPE_BUG")
        self.assertEqual(self.weight(woods, bug), CATALOGUE["tier_weights"][tier] * 3)

    def timed_family(self, time, *types):
        for index, (first, count, tier, habitat, family_time, type1, type2) in enumerate(CATALOGUE["families"]):
            if (family_time == time and habitat & 1 and index not in CATALOGUE.get("safari_only", ())
                    and (not types or set(types) & {type1, type2})):
                return index, tier
        self.skipTest(f"no land family for time {time} and types {types}")

    def test_time_of_day_only_makes_a_family_less_likely(self):
        # The owner's report of 2026-10-25 ("the same 30 pokemon are spawning"): in its time of day a family is as
        # likely as any other of its tier (no x3), out of it a third as likely.
        tiers = CATALOGUE["tier_weights"]
        day_family, tier = self.timed_family(2)
        self.assertEqual(self.weight(ROUTE101, day_family), tiers[tier])
        self.assertEqual(self.weight(ROUTE101, day_family, night=True), max(1, tiers[tier] // 3))
        night_family, tier = self.timed_family(1)
        self.assertEqual(self.weight(ROUTE101, night_family, night=True), tiers[tier])
        self.assertEqual(self.weight(ROUTE101, night_family), max(1, tiers[tier] // 3))

    def test_time_of_day_and_area_types_never_go_above_three_times_the_tier(self):
        woods = next(key for key, entry in CATALOGUE["maps"].items() if entry["constant"] == "MAP_PETALBURG_WOODS")
        tiers = CATALOGUE["tier_weights"]
        bug, tier = self.timed_family(2, "TYPE_BUG")          # a day Bug family in the Bug and Grass woods
        self.assertEqual(self.weight(woods, bug), tiers[tier] * 3)          # was x9
        self.assertEqual(self.weight(woods, bug, night=True), tiers[tier])  # a third, then the area's x3
        for night in (False, True):
            for index, weight in self.director.species_weights(woods, 10, night, None):
                self.assertLessEqual(weight, tiers[self.director.family_tier(index)] * 3)

    def test_the_most_likely_families_hold_a_smaller_share_by_day(self):
        weights = sorted((w for _, w in self.director.species_weights(ROUTE101, 3, False, None)), reverse=True)
        self.assertLess(sum(weights[:28]) / sum(weights), 0.25)   # 38 % before the change

    def test_underground_maps_ignore_the_weather(self):
        cave = next(key for key, entry in CATALOGUE["maps"].items() if entry["underground"])
        water, _ = self.family_index("TYPE_WATER", "TYPE_WATER")
        self.assertEqual(self.weight(cave, water, weather="WEATHER_RAIN"), self.weight(cave, water))

    def test_weather_table_matches_phase_two(self):
        self.assertEqual(WEATHER_TYPES["WEATHER_SNOW"][0], "TYPE_ICE")
        self.assertEqual(WEATHER_TYPES["WEATHER_SANDSTORM"][:2], ("TYPE_GROUND", "TYPE_ROCK"))
        self.assertTrue(WEATHER_TYPES["WEATHER_DOWNPOUR"][2])

    def test_reported_weather_beats_the_map_default(self):
        players = [presence(1, 1, weather=CATALOGUE["weather"]["WEATHER_RAIN"])]
        self.assertEqual(self.director.weather_for(ROUTE101, players), "WEATHER_RAIN")
        self.assertEqual(self.director.weather_for(ROUTE101, [presence(1, 1)]),
                         CATALOGUE["maps"][ROUTE101]["weather"])


class ScriptedRandom(random.Random):
    """A random source whose next randrange results are given in advance."""

    def __init__(self, rolls):
        super().__init__(5)
        self.rolls = list(rolls)

    def randrange(self, *args, **kw):
        return self.rolls.pop(0) if self.rolls else super().randrange(*args, **kw)


class RepeatTests(DirectorTestCase):
    """No repeats on a map (2026-10-25): a family already there, or among the map's last few spawns, is rolled again."""

    def first_two(self):
        weights = self.director.species_weights(ROUTE101, 3, False, None)
        return weights[0][0], weights[1][0], weights[0][1]

    def species_for(self, rolls, avoid):
        self.director.rng = ScriptedRandom(rolls)
        return self.director.choose_species(ROUTE101, 3, False, None, avoid=avoid)

    def test_an_avoided_family_is_rolled_again(self):
        first, second, first_weight = self.first_two()
        self.assertIn(first, self.director.families_of(self.species_for([0, first_weight], set())))
        got = self.species_for([0, first_weight], {first})
        self.assertEqual(self.director.families_of(got) & {first, second}, {second})

    def test_the_last_try_is_kept_whatever_it_is(self):
        first, _second, _weight = self.first_two()
        got = self.species_for([0] * REPEAT_TRIES + [1], {first})
        self.assertIn(first, self.director.families_of(got))

    def test_the_map_avoids_what_it_shows_and_what_it_spawned_last(self):
        board = self.boards.board(ROUTE101)
        board.create(species=10, level=3, personality=1, shiny=False, x=1, y=1, lifetime=60)   # Caterpie, on the map
        board.recent = [16, 19]                                                                # Pidgey, Rattata
        avoid = self.director.avoided_families(board)
        self.assertEqual(avoid, self.director.families_of(10) | self.director.families_of(16)
                         | self.director.families_of(19))
        self.assertIn(next(iter(self.director.families_of(11))), avoid)   # Metapod is Caterpie's family

    def test_a_long_session_rarely_repeats_a_family(self):
        x, y = route101_player_tile(self.director)
        players = {"p": presence(x, y)}
        board = self.boards.board(ROUTE101)
        repeats = spawns = 0
        seen = set()
        for _ in range(3600):
            avoid = self.director.avoided_families(board)
            self.step(players)
            for slot in board.live():
                if slot.spawn_id not in seen:
                    seen.add(slot.spawn_id)
                    spawns += 1
                    repeats += bool(self.director.families_of(slot.species) & avoid)
            for slot in list(board.live()):
                if slot.state == ss.OPEN and self.clock.now - slot.created_at > 20:
                    board.retire(slot.spawn_id)   # keep new Pokemon coming
        self.assertGreater(spawns, 300)
        self.assertLessEqual(repeats, spawns // 100)


class WanderTests(DirectorTestCase):
    def test_wandering_stays_in_habitat_on_one_elevation(self):
        x, y = route101_player_tile(self.director)
        players = {"p": presence(x, y)}
        self.fill(players)
        habitat = self.director.habitat(ROUTE101)
        board = self.boards.board(ROUTE101)
        moved = 0
        for _ in range(120):
            before = {s.spawn_id: (s.x, s.y) for s in board.live()}
            self.step(players)
            for slot in board.live():
                self.assertIn((slot.x, slot.y), habitat)
                self.assertNotEqual((slot.x, slot.y), (x, y))
                if slot.spawn_id in before and before[slot.spawn_id] != (slot.x, slot.y):
                    old = before[slot.spawn_id]
                    self.assertEqual(abs(old[0] - slot.x) + abs(old[1] - slot.y), 1)
                    self.assertEqual(habitat[old], habitat[(slot.x, slot.y)])
                    moved += 1
            tiles = [(s.x, s.y) for s in board.live()]
            self.assertEqual(len(tiles), len(set(tiles)))
        self.assertGreater(moved, 20)

    def test_a_pokemon_next_to_a_player_holds_still(self):
        x, y = route101_player_tile(self.director)
        board = self.boards.board(ROUTE101)
        habitat = self.director.habitat(ROUTE101)
        neighbour = next(t for t in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)) if t in habitat)
        sid = board.create(species=263, level=3, personality=1, shiny=False, x=neighbour[0], y=neighbour[1],
                           lifetime=10_000)
        for _ in range(50):
            self.step({"p": presence(x, y)})
        self.assertEqual((board.slots[sid].x, board.slots[sid].y), neighbour)

    def test_far_old_pokemon_retire(self):
        x, y = route101_player_tile(self.director)
        players = {"p": presence(x, y)}
        self.step(players)
        board = self.boards.board(ROUTE101)
        ids = [s.spawn_id for s in board.live()]
        far = {"p": presence(x, y, map_number=17)}  # left for Route 102
        far["q"] = presence(x + 40, y + 40)          # someone far away on Route 101
        self.step(far, seconds=self.director.tuning.retire_age + 1)
        self.assertTrue(all(board.slots.get(i) is None or board.slots[i].state == ss.REMOVED for i in ids))


class ShinyStaysDirectorTests(DirectorTestCase):
    """Shiny Pokemon never despawn (the owner's request of 2026-10-24), through the director's own rules."""

    def test_shiny_spawns_outlive_their_lifetime_far_players_and_the_outbreaks_end(self):
        x, y = route101_player_tile(self.director)
        outbreak = {ROUTE101: {"species": 263, "share": 1.0, "shiny_odds": 1}}   # every spawn of this outbreak is shiny
        self.fill({"p": presence(x, y)}, outbreaks=outbreak)
        board = self.boards.board(ROUTE101)
        shinies = {s.spawn_id for s in board.live() if s.shiny}
        self.assertTrue(shinies)
        far = {"p": presence(x, y, map_number=17), "q": presence(x + 40, y + 40)}   # one left, one far away
        longest = self.director.tuning.lifetime[1] + self.director.tuning.retire_age + 60
        for _ in range(int(longest // 30) + 2):
            self.step(far, seconds=30)                                              # the outbreak is over meanwhile
        self.assertTrue(shinies <= {s.spawn_id for s in board.live()})
        self.assertTrue(all(board.slots[i].state == ss.OPEN for i in shinies))


class ClaimCleanupTests(DirectorTestCase):
    def setUp(self):
        super().setUp()
        x, y = route101_player_tile(self.director)
        self.x, self.y = x, y
        self.step({"p": presence(x, y)})
        self.board = self.boards.board(ROUTE101)
        self.sid = self.board.live()[0].spawn_id
        self.assertEqual(self.board.claim("p", self.sid), ss.GRANTED)

    def test_claimant_in_battle_keeps_it(self):
        for _ in range(60):
            self.step({"p": presence(self.x, self.y, activity="battle")})
        self.assertEqual(self.board.get(self.sid).state, ss.CLAIMED)

    def test_disconnected_claimant_keeps_it_for_its_grace(self):
        for _ in range(60):
            self.step({"q": presence(self.x + 3, self.y)})
        self.assertEqual(self.board.get(self.sid).claimant, "p")

    def test_claimant_on_another_map_releases(self):
        self.step({"p": presence(5, 5, map_number=17)})
        self.assertEqual(self.board.get(self.sid).state, ss.OPEN)

    def test_claimant_idle_on_the_overworld_releases_after_a_while(self):
        for _ in range(int(self.director.tuning.stale_claim_seconds) + 2):
            self.step({"p": presence(self.x, self.y)})
        self.assertEqual(self.board.get(self.sid).state, ss.OPEN)


class ViewTests(DirectorTestCase):
    def test_every_player_on_a_map_sees_the_same_pokemon(self):
        x, y = route101_player_tile(self.director)
        players = {"a": presence(x, y), "b": presence(x + 1, y)}
        self.fill(players)
        board = self.boards.board(ROUTE101)
        sid = board.live()[0].spawn_id
        board.claim("a", sid)
        view_a = self.director.view("a", players["a"])
        view_b = self.director.view("b", players["b"])
        strip = lambda view: [{k: v for k, v in s.items() if k not in ("mine", "busy")} for s in view["slots"]]
        self.assertEqual(strip(view_a), strip(view_b))
        mine = {s["spawn_id"]: s["mine"] for s in view_a["slots"]}
        busy = {s["spawn_id"]: s["busy"] for s in view_b["slots"]}
        self.assertTrue(mine[sid] and busy[sid])
        self.assertEqual((view_a["map_group"], view_a["map_number"], view_a["shared"]), (0, 16, True))

    def test_a_player_elsewhere_sees_only_its_own_map(self):
        x, y = route101_player_tile(self.director)
        self.fill({"a": presence(x, y)})
        view = self.director.view("b", presence(3, 3, map_number=17))
        self.assertEqual((view["slots"], view["shared"]), ([], True))
        self.assertIsNone(self.director.view("b", None))

    def test_maps_with_their_own_battle_rules_are_not_shared(self):
        # The Safari Zones and the Pokemon Tower keep the game's own encounters
        # (Safari and ghost battles); towns have no land habitat at all.
        names = {entry["mapsec"] for entry in self.director.catalogue["maps"].values()}
        self.assertFalse(names & {"MAPSEC_SAFARI_ZONE", "MAPSEC_KANTO_SAFARI_ZONE", "MAPSEC_POKEMON_TOWER"})
        for group, number in ((26, 0), (0, 9)):  # Safari Zone northwest, Petalburg City
            view = self.director.view("b", {**presence(5, 5), "map_group": group, "map_number": number})
            self.assertEqual((view["shared"], view["slots"]), (False, []))
        self.director.update({"b": {**presence(5, 5), "map_group": 26, "map_number": 0}}, night=False, force=True)
        self.assertIsNone(self.boards.existing("26.0"))


class TuningTests(unittest.TestCase):
    def test_defaults_are_documented_values(self):
        tuning = SpawnTuning()
        self.assertEqual(tuning.first_burst, 3)
        self.assertLess(tuning.lifetime[0], tuning.lifetime[1])


if __name__ == "__main__":
    unittest.main()
