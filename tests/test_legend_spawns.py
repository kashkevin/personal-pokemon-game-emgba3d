"""Random Legendary and Mythical shared wild Pokemon (Update 29): the host's roll at the claim.

Exactly 1 in 6000 per claimed Pokemon (one combined chance for the whole pool, not per species), once per Pokemon, the
species from the map's habitat pool, the map's own level and the Pokemon's shiny status kept, nothing multiplied by the
number of players, nothing rerolled by a release, a reconnect or a restart, and none of the Safari-only families picked."""
import json
import math
import random
import unittest

from emerald_multiplayer import legend_pool, legend_rules
from emerald_multiplayer import shared_spawns as ss
from emerald_multiplayer.shared_spawn_catalogue import CATALOGUE
from emerald_multiplayer.shared_spawns import SpawnBoard, SpawnBoards
from emerald_multiplayer.spawn_director import SpawnDirector

ROUTE101 = "0.16"
LEGEND_IDS = {species for species, *_ in legend_pool.SPECIES}


class Clock:
    now = 100.0

    def __call__(self):
        return self.now


def make(seed=1):
    clock = Clock()
    boards = SpawnBoards(clock)
    director = SpawnDirector(CATALOGUE, boards, rng=random.Random(seed), clock=clock)
    board = boards.board(ROUTE101)
    return clock, boards, director, board


def add(board, i=0, *, species=261, level=3, shiny=False):
    spawn_id = board.create(species=species, level=level, personality=1000 + i, shiny=shiny, x=3 + i % 10, y=3 + i // 10,
                            lifetime=10_000_000.0)
    assert spawn_id is not None
    return spawn_id


class PoolTests(unittest.TestCase):
    def test_pool_is_the_games_classification(self):
        self.assertEqual(len(legend_pool.SPECIES), 54)
        for mythical in (151, 251, 385, 386, 489, 490, 491, 492, 493, 494, 647, 648, 649, 719, 720, 721):
            self.assertIn(mythical, LEGEND_IDS, mythical)
        self.assertEqual(legend_pool.ONE_IN_REGULAR, 6000)
        self.assertEqual(legend_pool.ONE_IN_SAFARI, 4000)

    def test_habitat_rules_for_land_areas(self):
        route = legend_rules.eligible(legend_rules.area_tags("MAPSEC_ROUTE_101", "MAP_TYPE_ROUTE", "WEATHER_SUNNY"), False)
        self.assertIn(384, route)            # Rayquaza: outdoor / sky
        self.assertNotIn(382, route)         # Kyogre: ocean only
        self.assertNotIn(144, route)         # Articuno: cold places
        rain = legend_rules.eligible(legend_rules.area_tags("MAPSEC_ROUTE_101", "MAP_TYPE_ROUTE", "WEATHER_RAIN"), False)
        self.assertIn(145, rain)             # Zapdos: storm weather
        cave = legend_rules.eligible(legend_rules.area_tags("MAPSEC_GRANITE_CAVE", "MAP_TYPE_UNDERGROUND", "WEATHER_RAIN"), False)
        self.assertIn(150, cave)             # Mewtwo: caves
        self.assertEqual(cave, legend_rules.eligible(
            legend_rules.area_tags("MAPSEC_GRANITE_CAVE", "MAP_TYPE_UNDERGROUND", "WEATHER_SUNNY"), False))
        night = legend_rules.eligible(legend_rules.area_tags("MAPSEC_ROUTE_101", "MAP_TYPE_ROUTE", "WEATHER_SUNNY"), True)
        self.assertIn(488, night)            # Cresselia: night only
        self.assertNotIn(488, route)
        self.assertNotIn(491, route)

    def test_no_real_catalogue_map_has_an_empty_pool(self):
        for key, entry in CATALOGUE["maps"].items():
            for weather in CATALOGUE["weather"]:
                for night in (False, True):
                    tags = legend_rules.area_tags(entry["mapsec"], entry["map_type"], weather)
                    self.assertTrue(legend_rules.eligible(tags, night), (key, weather, night))

    def test_every_species_is_obtainable_on_some_map(self):
        seen = set()
        for entry in CATALOGUE["maps"].values():
            for weather in CATALOGUE["weather"]:
                for night in (False, True):
                    seen.update(legend_rules.eligible(legend_rules.area_tags(entry["mapsec"], entry["map_type"], weather), night))
        self.assertEqual(seen, LEGEND_IDS)

    def test_empty_pool_and_invalid_inputs(self):
        self.assertIsNone(legend_rules.pick(random.Random(1), 0, True))
        self.assertEqual(legend_rules.eligible(0, True), [])
        # an unknown map section / weather only gets the defaults
        self.assertEqual(legend_rules.area_tags("MAPSEC_NOWHERE", "MAP_TYPE_ROUTE", "WEATHER_NOPE"), legend_pool.LAND_DEFAULT)


class RollTests(unittest.TestCase):
    def test_one_in_6000_converges(self):
        rng = random.Random(0x2900)
        total = 6_000_000
        hits = sum(1 for _ in range(total) if legend_rules.roll_hits(rng))
        expected = total / 6000
        self.assertLess(abs(hits - expected), 4.5 * math.sqrt(expected), (hits, expected))

    def test_combined_not_per_species(self):
        # One roll for the whole pool: a small area's pool and the biggest pool are rolled with the same 1/6000.
        small = legend_rules.eligible(legend_pool.LAND_DEFAULT, False)
        big = legend_rules.eligible(0xFFF, True)
        self.assertLess(len(small), len(big))
        self.assertEqual(len(big), 54)
        rng = random.Random(77)
        draws = [legend_rules.pick(rng, 0xFFF, True) for _ in range(54 * 400)]
        self.assertEqual(set(draws), LEGEND_IDS)         # every species of the pool is reachable

    def test_claims_converge_and_keep_level_and_shiny(self):
        clock, boards, director, board = make(11)
        total, legends = 600_000, 0
        pool = set(legend_rules.eligible(legend_rules.area_tags("MAPSEC_ROUTE_101", "MAP_TYPE_ROUTE", "WEATHER_SUNNY"), False))
        for i in range(total):
            shiny = i % 4096 == 0
            slot = ss.Slot(spawn_id=i + 1, species=261, level=2 + i % 2, personality=i, shiny=shiny, kind=ss.KIND_NORMAL,
                           x=1, y=1, facing=1, expires_at=1e12, created_at=0.0)
            board.slots[slot.spawn_id] = slot
            changed = director.roll_legend_on_claim(board, slot.spawn_id, night=False)
            if changed:
                legends += 1
                self.assertIn(slot.species, pool)
                self.assertEqual(slot.level, 2 + i % 2)      # the map's own level: never raised
                self.assertEqual(slot.shiny, shiny)
                self.assertTrue(slot.legend)
            else:
                self.assertEqual(slot.species, 261)
            del board.slots[slot.spawn_id]
        expected = total / 6000
        self.assertLess(abs(legends - expected), 4.5 * math.sqrt(expected), (legends, expected))

    def test_forced_hit_uses_the_map_pool(self):
        clock, boards, director, board = make(3)
        director.rng = random.Random(1)
        director.rng.randrange = lambda n, _o=director.rng.randrange: 0 if n == 6000 else _o(n)
        counts = {}
        for i in range(2000):
            spawn_id = add(board, i % 40)
            slot = board.get(spawn_id)
            director.roll_legend_on_claim(board, spawn_id, night=False)
            counts[slot.species] = counts.get(slot.species, 0) + 1
            board.slots.pop(spawn_id)
        self.assertEqual(set(counts), set(legend_rules.eligible(legend_rules.area_tags("MAPSEC_ROUTE_101", "MAP_TYPE_ROUTE", "WEATHER_SUNNY"), False)))
        self.assertLess(max(counts.values()), 2000 / len(counts) * 1.5)      # uniform pick

    def test_rolls_once_per_pokemon_no_reroll_by_release_reclaim_or_reconnect(self):
        clock, boards, director, board = make(9)
        director.rng.randrange = lambda n: 1               # never a hit
        spawn_id = add(board)
        self.assertFalse(director.roll_legend_on_claim(board, spawn_id, night=False))
        slot = board.get(spawn_id)
        self.assertTrue(slot.legend_rolled)
        director.rng.randrange = lambda n: 0               # now every roll would hit
        for _ in range(5):
            self.assertEqual(board.claim("alice", spawn_id), ss.GRANTED)
            self.assertFalse(director.roll_legend_on_claim(board, spawn_id, night=False))   # claimed: no roll
            board.release("alice", spawn_id)
            self.assertFalse(director.roll_legend_on_claim(board, spawn_id, night=False))   # open again: already rolled
        self.assertEqual(slot.species, 261)
        self.assertFalse(slot.legend)

    def test_a_legend_stays_one_when_released(self):
        clock, boards, director, board = make(2)
        director.rng.randrange = lambda n: 0
        spawn_id = add(board)
        self.assertTrue(director.roll_legend_on_claim(board, spawn_id, night=False))
        species = board.get(spawn_id).species
        board.claim("alice", spawn_id)
        board.release("alice", spawn_id)
        self.assertFalse(director.roll_legend_on_claim(board, spawn_id, night=False))
        self.assertEqual(board.get(spawn_id).species, species)

    def test_busy_claim_does_not_roll(self):
        clock, boards, director, board = make(4)
        director.rng.randrange = lambda n: 1
        spawn_id = add(board)
        director.roll_legend_on_claim(board, spawn_id, night=False)
        board.claim("alice", spawn_id)
        director.rng.randrange = lambda n: 0
        self.assertEqual(board.claim("bob", spawn_id), ss.BUSY)
        self.assertFalse(director.roll_legend_on_claim(board, spawn_id, night=False))
        self.assertEqual(board.get(spawn_id).species, 261)

    def test_state_survives_a_restart_without_a_new_roll(self):
        clock, boards, director, board = make(6)
        director.rng.randrange = lambda n: 0
        spawn_id = add(board)
        director.roll_legend_on_claim(board, spawn_id, night=False)
        species = board.get(spawn_id).species
        state = json.loads(json.dumps(board.to_state()))
        again = SpawnBoard.from_state(state, clock)
        slot = again.get(spawn_id)
        self.assertEqual((slot.species, slot.legend_rolled, slot.legend), (species, True, True))
        # an older save without the field loads as "not rolled yet"
        for item in state["slots"]:
            item.pop("legend_rolled"), item.pop("legend")
        old = SpawnBoard.from_state(state, clock)
        self.assertFalse(old.get(spawn_id).legend_rolled)

    def test_no_server_wide_multiplication(self):
        # four players claiming their own Pokemon: the rate per claim is the same as for one player
        clock, boards, director, board = make(21)
        total, hits = 600_000, 0
        for i in range(total):
            slot = ss.Slot(spawn_id=i + 1, species=261, level=3, personality=i, shiny=False, kind=ss.KIND_NORMAL,
                           x=1, y=1, facing=1, expires_at=1e12, created_at=0.0)
            board.slots[slot.spawn_id] = slot
            player = f"p{i % 4}"
            if director.roll_legend_on_claim(board, slot.spawn_id, night=False):
                hits += 1
            board.claim(player, slot.spawn_id)
            board.slots.pop(slot.spawn_id)
        expected = total / 6000
        self.assertLess(abs(hits - expected), 4.5 * math.sqrt(expected))


class SafariOnlyTests(unittest.TestCase):
    def test_safari_only_families_are_never_shared_spawns(self):
        clock, boards, director, board = make(1)
        self.assertEqual(len(CATALOGUE["safari_only"]), 8)
        indexes = {index for index, _w in director.species_weights(ROUTE101, 3, False, None)}
        self.assertFalse(indexes & set(CATALOGUE["safari_only"]))
        # the rest of the pool is unchanged: 312 families, minus 8, minus the ones without land habitat
        self.assertGreater(len(indexes), 150)

    def test_safari_only_species_never_chosen(self):
        clock, boards, director, board = make(8)
        banned = set()
        for index in CATALOGUE["safari_only"]:
            first, count = CATALOGUE["families"][index][:2]
            banned.update(m[0] for m in CATALOGUE["members"][first:first + count])
        for _ in range(60_000):
            self.assertNotIn(director.choose_species(ROUTE101, 25, False, None), banned)


if __name__ == "__main__":
    unittest.main()
