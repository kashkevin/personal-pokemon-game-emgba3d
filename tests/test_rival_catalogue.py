"""Update 31: the rival checkpoint catalogue, the intro post-state table and the battle formats."""
import itertools
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import unittest
from uuid import UUID

from emerald_multiplayer import flash
from emerald_multiplayer.rival_catalogue import BY_ID, CHECKPOINTS, GATES, IDS, checkpoint_at, gate_blocks
from emerald_multiplayer.rival_formats import (MODE_MULTI, MODE_SINGLES, MULTI, ROUND_ROBIN, SINGLES,
                                               PlannedMatch, plan, winners)

ROOT = Path(__file__).resolve().parents[1]
INTRO = json.loads((ROOT / "docs" / "update31" / "intro-post-state.json").read_text())


def ids(count, seed=0):
    rng = random.Random(seed)
    return [str(UUID(int=rng.getrandbits(128), version=4)) for _ in range(count)]


class CatalogueTests(unittest.TestCase):
    def test_five_checkpoints_in_story_order_with_unique_maps(self):
        self.assertEqual(IDS, ("route103", "rustboro", "route110", "route119", "lilycove"))
        self.assertEqual([c.order for c in CHECKPOINTS], [1, 2, 3, 4, 5])
        maps = [m for c in CHECKPOINTS for m in c.maps]
        self.assertEqual(len(maps), len(set(maps)), "a map belongs to two checkpoints")

    def test_map_numbers_are_inside_the_forks_pinned_map_table(self):
        for checkpoint in CHECKPOINTS:
            for group, number in checkpoint.maps:
                self.assertLess(number, flash._MAP_COUNTS[group])

    def test_titles_fit_the_native_menu_and_every_field_is_filled(self):
        for c in CHECKPOINTS:
            self.assertTrue(1 <= len(c.title) <= 16 and all(32 <= ord(ch) <= 126 for ch in c.title))
            self.assertIn(c.gate, GATES)
            self.assertTrue(c.triggers and c.prerequisites and c.cleared_when and c.completion_effects and c.sources)
            self.assertIn(c.canonical_environment, c.battle_environments)

    def test_each_checkpoint_replaces_exactly_its_six_rival_trainers(self):
        seen = set()
        for c in CHECKPOINTS:
            self.assertEqual(len(c.trainers), 6)
            self.assertTrue(all(t.startswith(("TRAINER_BRENDAN_", "TRAINER_MAY_")) for t in c.trainers))
            self.assertFalse(seen & set(c.trainers))
            seen |= set(c.trainers)

    def test_mandatory_gates_and_optional_battles_follow_the_original_story(self):
        self.assertEqual({c.checkpoint_id for c in CHECKPOINTS if c.gate == "trigger_line"}, {"route110", "route119"})
        self.assertEqual({c.checkpoint_id for c in CHECKPOINTS if c.declinable}, {"rustboro", "lilycove"})
        for c in CHECKPOINTS:
            self.assertEqual(c.declinable, c.gate == "none")
            self.assertEqual(c.mandatory, not c.declinable)
        self.assertEqual(BY_ID["route110"].personal_rewards, ("ITEM_DOWSING_MACHINE",))
        self.assertEqual(BY_ID["route119"].personal_rewards, ("ITEM_HM_FLY",))

    def test_checkpoint_at_finds_only_checkpoint_maps(self):
        self.assertEqual(checkpoint_at(0, 18).checkpoint_id, "route103")
        self.assertEqual(checkpoint_at(0, 19).checkpoint_id, "rustboro")  # the Route 104 variant
        self.assertEqual(checkpoint_at(0, 3).checkpoint_id, "rustboro")
        for not_a_checkpoint in ((0, 16), (0, 9), (1, 4), (0, 2), (0, 4), (255, 255)):
            self.assertIsNone(checkpoint_at(*not_a_checkpoint))

    def test_gate_truth_table_never_blocks_cleared_completed_or_ungated(self):
        for c in CHECKPOINTS:
            for world, personal in itertools.product((False, True), repeat=2):
                expected = c.gate == "trigger_line" and not world and not personal
                self.assertEqual(gate_blocks(c, world_completed=world, personally_cleared=personal), expected)
        with self.assertRaises(ValueError):
            gate_blocks("route110", world_completed=False, personally_cleared=False)

    def test_engine_checkout_verification_when_one_is_supplied(self):
        engine = os.environ.get("EMERALD_ENGINE_CHECKOUT")
        if not engine:
            self.skipTest("set EMERALD_ENGINE_CHECKOUT to an engine/upstream checkout to re-derive the catalogue")
        result = subprocess.run([sys.executable, str(ROOT / "scripts/multiplayer/check_rival_catalogue.py"),
                                 "--engine", engine], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class IntroTableTests(unittest.TestCase):
    def names(self, *sections):
        out = []
        for section in sections:
            out += [e["name"] if type(e) is dict else e for e in INTRO.get(section, [])]
        return out

    def test_post_intro_state_is_the_starter_received_state_before_route103(self):
        values = {e["name"]: e["value"] for e in INTRO["vars"]}
        self.assertEqual(values["VAR_BIRCH_LAB_STATE"], 3)
        self.assertEqual(values["VAR_ROUTE101_STATE"], 3)
        self.assertIn("FLAG_SYS_POKEMON_GET", self.names("set_flags"))
        self.assertIn("FLAG_RESCUED_BIRCH", self.names("set_flags"))

    def test_route101_rescue_scene_is_put_away_whole(self):
        # Birch's bag script hides Birch (setflag) and the Zigzagoon (removeobject): both, or a Zigzagoon stays on Route 101.
        sets = set(self.names("set_flags"))
        self.assertTrue({"FLAG_HIDE_ROUTE_101_BIRCH_ZIGZAGOON_BATTLE", "FLAG_HIDE_ROUTE_101_ZIGZAGOON",
                         "FLAG_HIDE_ROUTE_101_BIRCH_STARTERS_BAG"} <= sets)

    def test_earned_items_and_later_story_are_never_granted(self):
        granted = set(self.names("set_flags", "set_flags_male_player", "set_flags_female_player"))
        self.assertFalse(granted & set(INTRO["must_not_be_set"]))
        self.assertEqual(INTRO["items"], [])
        self.assertIn("FLAG_SYS_POKEDEX_GET", INTRO["must_not_be_set"])
        self.assertIn("FLAG_RECEIVED_RUNNING_SHOES", INTRO["must_not_be_set"])
        self.assertIn("FLAG_DEFEATED_RIVAL_ROUTE103", INTRO["must_not_be_set"])

    def test_set_and_clear_lists_do_not_contradict_and_genders_mirror(self):
        sets = set(self.names("set_flags"))
        clears = set(self.names("clear_flags"))
        self.assertFalse(sets & clears)
        male, female = INTRO["set_flags_male_player"], INTRO["set_flags_female_player"]
        self.assertEqual(len(male), len(female))
        def mirror(flag):
            flag = flag.replace("BRENDANS", "\0").replace("MAYS", "BRENDANS").replace("\0", "MAYS")
            if flag.endswith("_HOUSE_MAY"):
                return flag[:-len("MAY")] + "BRENDAN"
            if flag.endswith("_HOUSE_BRENDAN"):
                return flag[:-len("BRENDAN")] + "MAY"
            return flag
        self.assertEqual(sorted(map(mirror, male)), sorted(female))

    def test_spawn_is_littleroot_in_front_of_the_players_own_house(self):
        spawn = INTRO["spawn"]
        self.assertEqual(spawn["map"], "MAP_LITTLEROOT_TOWN")
        self.assertEqual((spawn["male"]["x"], spawn["male"]["y"]), (5, 9))
        self.assertEqual((spawn["female"]["x"], spawn["female"]["y"]), (14, 9))

    def test_existing_characters_are_excluded(self):
        self.assertIn("FLAG_SYS_POKEMON_GET", INTRO["existing_characters"])


class FormatTests(unittest.TestCase):
    def test_two_players_one_singles(self):
        players = ids(2)
        result = plan(players, {}, "seed")
        self.assertEqual(result.format, SINGLES)
        self.assertEqual(len(result.matches), 1)
        self.assertEqual(result.matches[0].mode, MODE_SINGLES)
        self.assertEqual(set(result.matches[0].players), set(players))

    def test_three_players_round_robin_is_fair(self):
        for seed in range(30):
            players = ids(3, seed)
            result = plan(players, {}, f"w{seed}")
            self.assertEqual(result.format, ROUND_ROBIN)
            pairs = [frozenset(m.players) for m in result.matches]
            self.assertEqual(len(set(pairs)), 3, "every pair meets exactly once")
            for player in players:
                self.assertEqual(sum(player in pair for pair in pairs), 2, "every trainer plays twice")
            self.assertTrue(all(m.mode == MODE_SINGLES for m in result.matches))

    def test_four_players_balanced_two_versus_two(self):
        a, b, c, d = ids(4)
        result = plan([a, b, c, d], {a: 50, b: 10, c: 45, d: 15}, "seed")
        self.assertEqual(result.format, MULTI)
        match = result.matches[0]
        self.assertEqual(match.mode, MODE_MULTI)
        totals = sorted(sum({a: 50, b: 10, c: 45, d: 15}[p] for p in team) for team in match.teams)
        self.assertEqual(totals, [60, 60])

    def test_ties_are_broken_by_seed_not_input_order(self):
        players = ids(4, 3)
        layouts = set()
        for seed in range(40):
            first = plan(players, {}, f"s{seed}")
            for order in itertools.permutations(players):
                self.assertEqual(plan(order, {}, f"s{seed}"), first)
            layouts.add(first.matches[0].teams)
        self.assertGreater(len(layouts), 1, "equal strengths should not always pair the same trainers")

    def test_refuses_unsupported_rosters(self):
        for bad in ([], ids(1), ids(5), ids(1) * 2):
            with self.assertRaises(ValueError):
                plan(bad, {}, "seed")
        with self.assertRaises(ValueError):
            plan(ids(2), {}, "")

    def test_winners_follow_native_slots_and_refuse_foreign_sides(self):
        a, b, c, d = sorted(ids(4))
        single = PlannedMatch(0, MODE_SINGLES, ((a,), (b,)))
        self.assertEqual(winners(single, [a, b], 1), (a,))
        self.assertEqual(winners(single, [a, b], 2), (b,))
        self.assertEqual(winners(single, [a, b], 3), ())
        multi = PlannedMatch(0, MODE_MULTI, tuple(sorted(((a, c), (b, d)))))
        self.assertEqual(winners(multi, [a, b, c, d], 1), (a, c))
        self.assertEqual(winners(multi, [b, a, d, c], 1), (b, d))
        with self.assertRaises(ValueError):
            winners(multi, [a, c, b, d], 1)   # sides a+b vs c+d were never planned
        with self.assertRaises(ValueError):
            winners(single, [a, b], 4)
        with self.assertRaises(ValueError):
            winners(single, [a, c], 1)

    def test_describe_fits_the_status_line(self):
        players = ids(4)
        names = {p: "Ä very long trainer name" for p in players}
        for count in (2, 3, 4):
            text = plan(players[:count], {}, "x").describe(names)
            self.assertLessEqual(len(text), 32)
            self.assertTrue(all(32 <= ord(ch) <= 126 for ch in text))

    def test_randomised_plans_are_total_and_deterministic(self):
        rng = random.Random(31)
        for _ in range(300):
            count = rng.choice((2, 3, 4))
            players = ids(count, rng.getrandbits(32))
            strengths = {p: rng.randint(0, 100) for p in players}
            seed = str(rng.getrandbits(64))
            a, b = plan(players, strengths, seed), plan(list(reversed(players)), dict(strengths), seed)
            self.assertEqual(a, b)
            covered = set().union(*(set(m.players) for m in a.matches))
            self.assertEqual(covered, set(players), "nobody present is left out")


if __name__ == "__main__":
    unittest.main()
