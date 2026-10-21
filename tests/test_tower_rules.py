"""Battle Tower: Legends' pure rules (docs/battle-tower-legends.md sections 2-4) and its floor data reader.

The floor table itself is the engine generator's; these tests use a small synthetic table installed through
tower_data.install (``synthetic_data``), never a generated module.
"""
from __future__ import annotations

from itertools import permutations
import random
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from emerald_multiplayer import tower_data, tower_rewards, tower_rules
from emerald_multiplayer.frontier_service import FLAGS_OFFSET
from emerald_multiplayer.tower_data import TowerDataError
from emerald_multiplayer.tower_rules import (CHECKPOINTS, TowerRuleError, after, can_fight, checkpoint, choose_milestone,
                                             default_duo_floor, duo_floor_allowed, exp_cap, is_progression,
                                             max_unlocked, milestone_level, win_reward)

BOSSES = {10: ("Leader", "Brock"), 20: ("Leader", "Misty"), 25: ("Boss", "Giovanni"), 30: ("Leader", "Flannery"),
          40: ("Leader", "Norman"), 50: ("Champion", "Wallace"), 60: ("Leader", "Winona"), 70: ("Champion", "Steven"),
          75: ("Pyramid King", "Brandon"), 80: ("Elite Four", "Drake"), 90: ("Champion", "Blue"), 100: ("Champion", "Red")}


def synthetic_floors():
    floors = []
    for number in range(1, 101):
        kind = ("final" if number == 100 else "special" if number in (25, 50, 75)
                else "boss" if number in BOSSES else "regular")
        klass, name = BOSSES.get(number, ("Ace Trainer", f"Ace{number}"))
        trainer = {"id": 900 + number, "name": name, "class": klass, "pic": "TRAINER_PIC_X", "gender": 0,
                   "encounterMusic": "MUSIC", "ai": ["AI_FLAG_CHECK_BAD_MOVE"],
                   "mons": [{"species": "SPECIES_GEODUDE", "speciesId": 74, "level": number}]}
        floors.append({"floor": number, "level": number, "kind": kind, "checkpoint": number in CHECKPOINTS,
                       "region": "Kanto" if number in (10, 20, 25, 90, 100) else "Hoenn", "difficulty": 1 + number // 10,
                       "music": "MUS_X", "intro": "Hello", "defeat": "Oh", "defeatB": "Ah", "victory": "Ha",
                       "solo": trainer, "duo": [dict(trainer), {**trainer, "name": f"Partner{number}", "class": "Hiker"}]})
    return floors


MILESTONES = ((1, "SPECIES_BULBASAUR", "Bulbasaur", 1), (3, "SPECIES_VENUSAUR", "Venusaur", 32),
              (6, "SPECIES_CHARIZARD", "Charizard", 36), (149, "SPECIES_DRAGONITE", "Dragonite", 55))
LEGENDS = ((380, "SPECIES_LATIAS", "Latias", 30), (381, "SPECIES_LATIOS", "Latios", 30), (150, "SPECIES_MEWTWO", "Mewtwo", 70))
TABLE_HASH = 0x5EED7A61


def synthetic_data(table_hash=TABLE_HASH):
    return tower_data.validate(table_hash, synthetic_floors(), MILESTONES, LEGENDS)


def without_generated_module():
    """The generated module as absent, whether or not this checkout has one (the floors land from the engine)."""
    missing = ModuleNotFoundError(f"No module named {tower_data.MODULE!r}", name=tower_data.MODULE)
    return patch.object(tower_data.importlib, "import_module", side_effect=missing)


class DataTests(unittest.TestCase):
    def setUp(self):
        tower_data.reset()                     # whatever an earlier test's host read (and cached) is forgotten

    def tearDown(self):
        tower_data.reset()

    def test_without_the_generated_module_the_tower_is_unavailable_and_says_why(self):
        with without_generated_module():
            tower_data.reset()
            self.assertEqual(tower_data.unavailable(), "Tower floor data is missing")
            with self.assertRaises(TowerDataError) as caught:
                tower_data.load()
        self.assertIn("generate.py", str(caught.exception))
        self.assertLessEqual(len(caught.exception.reason), 31)

    def test_installed_data_is_used_and_reset_forgets_it(self):
        data = synthetic_data()
        tower_data.install(data)
        self.assertIsNone(tower_data.unavailable())
        self.assertIs(tower_data.load(), data)
        self.assertEqual(data.trainer(10), "Leader Brock")
        self.assertEqual(data.trainer(12), "Ace Trainer Ace12")
        self.assertEqual(data.trainer(12, "b"), "Hiker Partner12")
        self.assertEqual(data.bosses(), (10, 20, 25, 30, 40, 50, 60, 70, 75, 80, 90, 100))
        self.assertEqual([s.species for s in data.legendary_species], [380, 381, 150])
        tower_data.reset()
        with without_generated_module():
            self.assertEqual(tower_data.unavailable(), "Tower floor data is missing")
        with self.assertRaises(TypeError):
            tower_data.install({"TABLE_HASH": 1})

    def test_the_generators_spelling_reads_as_the_menu_writes_it(self):
        # tools/tower_legends/generate.py writes the game's spelling: a class constant, names in capitals, "kanto".
        floors = synthetic_floors()
        brock = {**floors[9]["solo"], "name": "BROCK", "class": "TRAINER_CLASS_LEADER_FRLG"}
        floors[9].update(region="kanto", solo=brock,
                         duo=[brock, {**brock, "name": "CLIFFORD", "class": "TRAINER_CLASS_HIKER_FRLG"}])
        floors[39]["duo"][1] = {**floors[39]["duo"][1], "name": "WALLY", "class": "TRAINER_CLASS_RIVAL"}
        data = tower_data.validate(TABLE_HASH, floors, MILESTONES, LEGENDS)
        self.assertEqual((data.trainer(10), data.trainer(10, "a"), data.trainer(10, "b")),
                         ("Leader Brock", "Leader Brock", "Hiker Clifford"))
        self.assertEqual((data.trainer(40, "b"), data.region(10), data.region(12)), ("PKMN Trainer Wally", "Kanto", "Hoenn"))
        for constant, shown in (("TRAINER_CLASS_SWIMMER_F_FRLG", "Swimmer"), ("TRAINER_CLASS_TEAM_ROCKET_FRLG", "Team Rocket"),
                                ("TRAINER_CLASS_PKMN_BREEDER", "PKMN Breeder"), ("TRAINER_CLASS_ELITE_FOUR", "Elite Four"),
                                ("TRAINER_CLASS_PKMN_TRAINER_1", "PKMN Trainer"), ("TRAINER_CLASS_PYRAMID_KING", "Pyramid King"),
                                ("Ace Trainer", "Ace Trainer"), (None, "")):
            self.assertEqual(tower_data.display_class(constant), shown)
        self.assertEqual([tower_data.display_name(n) for n in ("MR. BRIGGS", "O'NEIL", "Ace12", " ")],
                         ["Mr. Briggs", "O'Neil", "Ace12", ""])

    def test_a_generated_module_is_read_once_and_checked(self):
        module = SimpleNamespace(TABLE_HASH=TABLE_HASH, FLOORS=synthetic_floors(), MILESTONE_SPECIES=MILESTONES,
                                 LEGENDARY_SPECIES=LEGENDS)
        with patch.object(tower_data.importlib, "import_module", return_value=module) as imported:
            self.assertEqual(tower_data.load().table_hash, TABLE_HASH)
            tower_data.load()
            self.assertEqual(imported.call_count, 1)
        tower_data.reset()
        for broken, detail in ((dict(TABLE_HASH="5eed"), "TABLE_HASH"), (dict(TABLE_HASH=1 << 32), "TABLE_HASH"),
                               (dict(TABLE_HASH=True), "TABLE_HASH"), (dict(TABLE_HASH=-1), "TABLE_HASH"),
                               (dict(LEGENDARY_SPECIES=None), "LEGENDARY_SPECIES")):
            with self.subTest(broken=broken), patch.object(tower_data.importlib, "import_module",
                                                           return_value=SimpleNamespace(**{**vars(module), **broken})):
                tower_data.reset()
                self.assertEqual(tower_data.unavailable(), "Tower floor data is malformed")
                with self.assertRaisesRegex(TowerDataError, detail):
                    tower_data.load()
        partial = SimpleNamespace(TABLE_HASH=1, FLOORS=synthetic_floors())
        with patch.object(tower_data.importlib, "import_module", return_value=partial):
            tower_data.reset()
            with self.assertRaisesRegex(TowerDataError, "MILESTONE_SPECIES, LEGENDARY_SPECIES"):
                tower_data.load()
        failing = ModuleNotFoundError("no module named yaml", name="yaml")
        with patch.object(tower_data.importlib, "import_module", side_effect=failing):
            tower_data.reset()
            self.assertEqual(tower_data.unavailable(), "Tower floor data is malformed")   # not "missing": it is there

    def test_every_malformed_table_is_refused_with_its_reason(self):
        def floors(change):
            value = synthetic_floors()
            change(value)
            return value
        cases = {
            "99 floors": floors(lambda f: f.pop()),
            "out of order": floors(lambda f: f.insert(0, f.pop(5))),
            "level": floors(lambda f: f[11].update(level=13)),
            "kind": floors(lambda f: f[11].update(kind="hard")),
            "checkpoint": floors(lambda f: f[11].update(checkpoint=True)),
            "checkpoint missing": floors(lambda f: f[9].update(checkpoint=False)),
            "region": floors(lambda f: f[3].pop("region")),
            "solo": floors(lambda f: f[3].update(solo={"class": "Hiker"})),
            "duo": floors(lambda f: f[3].update(duo=[f[3]["solo"]])),
            "duo name": floors(lambda f: f[3].update(duo=[f[3]["solo"], {"name": 5}])),
            "floor type": floors(lambda f: f[0].update(floor=True)),
        }
        for name, value in cases.items():
            with self.subTest(case=name), self.assertRaises(TowerDataError):
                tower_data.validate(TABLE_HASH, value, MILESTONES, LEGENDS)
        for pool in ((), ((0, "SPECIES_NONE", "None", 1),), ((1, "BULBASAUR", "Bulbasaur", 1),), ((1, "SPECIES_X", "", 1),),
                     ((1, "SPECIES_X", "X", 0),), ((1, "SPECIES_X", "X", 101),), ((1, "SPECIES_X", "X"),),
                     (MILESTONES[0], MILESTONES[0]), "SPECIES_X"):
            with self.subTest(pool=pool), self.assertRaises(TowerDataError):
                tower_data.validate(TABLE_HASH, synthetic_floors(), pool, LEGENDS)
        self.assertEqual(tower_data.validate(0, synthetic_floors(), MILESTONES, LEGENDS).table_hash, 0)


class ProgressTests(unittest.TestCase):
    def test_the_designs_examples_lose_back_to_the_checkpoint(self):
        # lose on 18 -> 11, on 48 -> 41, on 73 -> 71, on 79 -> 76, on 7 -> 1 (a fresh climb: H = P - 1)
        for floor, expected in ((18, 11), (48, 41), (73, 71), (79, 76), (7, 1)):
            for outcome in ("lost", "drew"):
                with self.subTest(floor=floor, outcome=outcome):
                    self.assertEqual(after(floor, floor - 1, floor, outcome), (expected, floor - 1))

    def test_checkpoints(self):
        self.assertEqual(CHECKPOINTS, (10, 20, 25, 30, 40, 50, 60, 70, 75, 80, 90, 100))
        self.assertEqual([checkpoint(h) for h in (0, 9, 10, 24, 25, 26, 74, 75, 99, 100)],
                         [0, 0, 10, 20, 25, 25, 70, 75, 90, 100])

    def test_a_win_climbs_and_a_checkpoint_is_never_lost(self):
        self.assertEqual(after(1, 0, 1, "won"), (2, 1))
        self.assertEqual(after(12, 11, 12, "won"), (13, 12))
        self.assertEqual(after(100, 99, 100, "won"), (101, 100))
        # a re-climb after a loss: P below H; a win moves P only, a loss falls back to the same checkpoint
        self.assertEqual(after(41, 48, 41, "won"), (42, 48))
        self.assertEqual(after(45, 48, 45, "lost"), (41, 48))
        self.assertEqual(after(32, 35, 32, "lost"), (31, 35))       # checkpoint 30 kept: back to 31
        self.assertEqual(after(26, 25, 26, "lost"), (26, 25))       # checkpoint 25 kept: back to 26
        self.assertEqual(after(10, 9, 10, "won"), (11, 10))
        self.assertEqual(after(11, 10, 11, "lost"), (11, 10))

    def test_replays_never_change_progress(self):
        for outcome in ("won", "lost", "drew"):
            self.assertEqual(after(18, 17, 5, outcome), (18, 17))
            self.assertEqual(after(41, 48, 47, outcome), (41, 48))
            self.assertEqual(after(101, 100, 100, outcome), (101, 100))   # after floor 100 every floor is a replay
            self.assertEqual(after(101, 100, 1, outcome), (101, 100))
        self.assertFalse(is_progression(101, 100))
        self.assertTrue(is_progression(100, 100) and is_progression(41, 41))
        self.assertFalse(is_progression(41, 40))

    def test_no_skipping(self):
        self.assertTrue(can_fight(12, 11, 12) and can_fight(12, 11, 11) and can_fight(12, 11, 1))
        for floor in (13, 50, 0, 101, -1, True, 12.0):
            self.assertFalse(can_fight(12, 11, floor), floor)
            if floor != 12.0:
                with self.assertRaises(TowerRuleError):
                    after(12, 11, floor, "won")
        self.assertTrue(can_fight(41, 48, 48) and can_fight(41, 48, 41))
        self.assertFalse(can_fight(41, 48, 49))
        for bad in ((0, 0, 1), (102, 100, 1), (5, 101, 1), (True, 0, 1)):
            with self.subTest(state=bad), self.assertRaises(TowerRuleError):
                after(*bad, "won")
        with self.assertRaises(TowerRuleError):
            after(12, 11, 12, "refused")

    def test_duo_floors(self):
        self.assertEqual(default_duo_floor(12, 50), 12)
        self.assertEqual(default_duo_floor(101, 50), 50)
        self.assertEqual(default_duo_floor(101, 101), 100)
        self.assertEqual(max_unlocked(12, 11), 12)
        self.assertEqual(max_unlocked(41, 48), 48)
        self.assertEqual(max_unlocked(101, 100), 100)
        a, b = (12, 11), (50, 49)
        self.assertTrue(duo_floor_allowed(12, a, b))                       # progression for A, a replay for B
        self.assertTrue(is_progression(12, 12) and not is_progression(50, 12) and can_fight(50, 49, 12))
        self.assertTrue(duo_floor_allowed(3, a, b))                        # a replay for both
        self.assertFalse(duo_floor_allowed(13, a, b))                      # beyond A's unlocked floors
        self.assertFalse(duo_floor_allowed(0, a, b) or duo_floor_allowed(101, (101, 100), (101, 100)))
        self.assertTrue(duo_floor_allowed(100, (101, 100), (101, 100)))


class CapAndMilestoneTests(unittest.TestCase):
    def test_experience_caps_by_badges_and_the_champion(self):
        self.assertEqual([exp_cap(n, False) for n in range(9)], [15, 20, 25, 30, 40, 45, 50, 55, 60])
        self.assertEqual(exp_cap(3, True), 100)
        self.assertEqual(exp_cap(8, True), 100)

    def test_the_cap_is_read_from_the_saves_flags(self):
        block = bytearray(0x4000)

        def set_flag(flag):
            block[FLAGS_OFFSET + flag // 8] |= 1 << flag % 8
        self.assertEqual(tower_rules.save_cap(bytes(block)), (0, False, 15))
        for flag in range(0x867, 0x86A):
            set_flag(flag)
        self.assertEqual(tower_rules.save_cap(bytes(block)), (3, False, 30))
        set_flag(0x87F)                                                    # FLAG_IS_CHAMPION is not the Tower's champion
        self.assertEqual(tower_rules.save_cap(bytes(block)), (3, False, 30))
        set_flag(0x864)                                                    # FLAG_SYS_GAME_CLEAR: the Hall of Fame entered
        self.assertEqual(tower_rules.save_cap(bytes(block)), (3, True, 100))

    def test_milestone_levels(self):
        self.assertEqual(milestone_level(25, 15), 15)                      # never above the cap at the claim
        self.assertEqual(milestone_level(25, 100), 25)                     # never above the floor
        self.assertEqual(milestone_level(50, 45), 45)
        self.assertEqual(milestone_level(75, 60), 60)
        self.assertEqual(milestone_level(100, 100), 70)                    # a legendary at most 70
        self.assertEqual(milestone_level(100, 60), 60)

    def test_the_species_is_a_random_legal_choice(self):
        data = synthetic_data()
        for level, legal in ((15, {1}), (32, {1, 3}), (40, {1, 3, 6}), (60, {1, 3, 6, 149})):
            picks = {choose_milestone(data.milestone_species, level, random.Random(seed)).species for seed in range(60)}
            self.assertEqual(picks, legal, level)
        self.assertEqual({choose_milestone(data.legendary_species, 60, random.Random(s)).species for s in range(40)},
                         {380, 381})
        self.assertIsNone(choose_milestone(data.legendary_species, 20, random.Random(1)))
        self.assertEqual(choose_milestone(data.milestone_species, 40, random.Random(7)),
                         choose_milestone(data.milestone_species, 40, random.Random(7)))


class RewardTests(unittest.TestCase):
    def test_first_clear_battle_points_and_money(self):
        self.assertEqual(tower_rewards.first_clear_bp(1), 1)
        self.assertEqual(tower_rewards.first_clear_bp(9), 1)
        self.assertEqual(tower_rewards.first_clear_bp(12), 2)
        self.assertEqual(tower_rewards.first_clear_bp(10), 6)              # (1 + 1) x 3
        self.assertEqual(tower_rewards.first_clear_bp(25), 12)             # (1 + 2) x 4
        self.assertEqual(tower_rewards.first_clear_bp(50), 24)
        self.assertEqual(tower_rewards.first_clear_bp(75), 32)
        self.assertEqual(tower_rewards.first_clear_bp(90), 30)
        self.assertEqual(tower_rewards.first_clear_bp(100), 55)            # (1 + 10) x 5
        self.assertEqual(tower_rewards.first_clear_bp(99), 10)
        self.assertEqual(win_reward(12, 11, 11, 0), (True, 2, 1200, (), 0, None))

    def test_a_prize_floors_first_clear_pays_the_prize_instead_of_the_floors_money(self):
        expected = {
            10: (10_000, ((102, 10),), None), 20: (20_000, ((133, 5),), None), 25: (0, (), 0), 30: (30_000, ((102, 15),), None),
            40: (40_000, ((134, 1),), None), 50: (50_000, (), 1), 60: (60_000, ((102, 20),), None),
            70: (70_000, ((134, 2),), None), 75: (0, (), 2), 80: (80_000, ((80, 1),), None),
            90: (90_000, ((80, 1), (134, 3)), None), 100: (100_000, (), 3)}
        for index, (floor, (money, items, milestone)) in enumerate(expected.items()):
            reward = win_reward(floor, floor - 1, floor - 1, 0)
            self.assertEqual(reward, (True, tower_rewards.first_clear_bp(floor), money, items, 1 << index, milestone), floor)
        self.assertEqual(tower_rewards.describe_items(((80, 1), (134, 3))), "1 Ability Patch + 3 Gold Bottle Cap")

    def test_a_prize_is_paid_once_per_player_ever(self):
        claimed = tower_rewards.claim_bit(10)
        self.assertEqual(win_reward(10, 9, 9, claimed), (True, 6, 1000, (), 0, None))   # already claimed: the floor's money
        self.assertEqual(win_reward(10, 30, 30, 0).claim, 0)                             # not a first clear

    def test_later_wins_pay_a_third_near_the_top_and_little_below_it(self):
        self.assertEqual(win_reward(41, 48, 48, 0), (False, 5 // 3, 41 * 30, (), 0, None))
        self.assertEqual(win_reward(40, 48, 48, 0), (False, 15 // 3, 40 * 30, (), 0, None))
        self.assertEqual(win_reward(28, 48, 48, 0), (False, 1, 28 * 30, (), 0, None))      # exactly 20 below: still near
        self.assertEqual(win_reward(27, 48, 48, 0), (False, 1, 27 * 10, (), 0, None))
        self.assertEqual(win_reward(100, 100, 100, 0xFFFF), (False, 18, 3000, (), 0, None))
        self.assertEqual(win_reward(5, 100, 100, 0), (False, 1, 50, (), 0, None))

    def test_a_floor_cleared_before_an_import_is_not_a_first_clear(self):
        self.assertFalse(win_reward(12, 5, 30, 0).first_clear)
        self.assertTrue(win_reward(31, 5, 30, 0).first_clear)

    def test_claim_bits(self):
        self.assertEqual([tower_rewards.claim_bit(f) for f in tower_rewards.PRIZE_FLOORS], [1 << n for n in range(12)])
        self.assertEqual([tower_rewards.delivered_bit(m) for m in range(4)], [1 << 12, 1 << 13, 1 << 14, 1 << 15])
        self.assertEqual(tower_rewards.MILESTONE_FLOORS, tuple(f for f, p in tower_rewards.PRIZES.items()
                                                               if p.milestone is not None))

    def test_the_shop_catalogue(self):
        prices = {entry.name: entry.price for entry in tower_rewards.SHOP}
        self.assertEqual(prices, {"Bottle Cap": 48, "Gold Bottle Cap": 192, "Ability Patch": 200, "Ability Capsule": 50,
                                  "Rare Candy": 24, "PP Up": 24, "PP Max": 64, "HP Up": 16, "Protein": 16, "Iron": 16,
                                  "Calcium": 16, "Zinc": 16, "Carbos": 16, "Leftovers": 48, "Choice Band": 64,
                                  "Choice Specs": 64, "Choice Scarf": 64, "Life Orb": 64, "Focus Sash": 48,
                                  "Assault Vest": 64, "Rocky Helmet": 48, "Expert Belt": 48, "Weakness Policy": 48,
                                  "Lum Berry": 16, "Sitrus Berry": 8})
        self.assertTrue(all(entry.quantity == 1 and len(entry.name) <= 15 for entry in tower_rewards.SHOP))
        self.assertLessEqual(len(tower_rewards.SHOP), 32)                  # the request's slot field


def party_mon(species, ivs, trained=(0,) * 6, *, personality=0x1234567, ot_id=0x89ABCDEF, level=30, egg=False):
    """A party Pokemon (100 bytes) with these natural IVs and Hyper Training bits, encrypted as the game stores it."""
    order = tuple(permutations(range(4)))[personality % 24]
    secure = bytearray(48)                                               # logical substructs 0-3, 12 bytes each
    struct.pack_into("<H", secure, 0, species)
    move4 = 33 | trained[0] << 14 | trained[1] << 15
    struct.pack_into("<H", secure, 12 + 6, move4)
    for index, bit in zip(range(20, 24), trained[2:]):
        secure[index] = 10 | bit << 7
    packed = sum(value << (5 * index) for index, value in enumerate(ivs)) | (egg << 30)
    struct.pack_into("<I", secure, 40, packed)
    physical = bytearray(48)
    for logical in range(4):
        physical[order.index(logical) * 12:order.index(logical) * 12 + 12] = secure[logical * 12:logical * 12 + 12]
    mon = bytearray(100)
    struct.pack_into("<II", mon, 0, personality, ot_id)
    mon[18:20] = bytes((2, 2 | (4 if egg else 0)))
    struct.pack_into("<H", mon, 28, sum(struct.unpack("<24H", bytes(physical))) & 0xFFFF)
    for index in range(12):
        struct.pack_into("<I", mon, 32 + index * 4, struct.unpack_from("<I", physical, index * 4)[0] ^ personality ^ ot_id)
    mon[84] = level
    struct.pack_into("<HH", mon, 86, 50, 60)
    return bytes(mon)


class TrainingTests(unittest.TestCase):
    def test_the_partys_natural_ivs_and_hyper_training_are_read_from_the_save(self):
        from emerald_multiplayer.flash import SAVED_PARTY_COUNT_OFFSET, SAVED_PARTY_OFFSET
        block = bytearray(15568)
        block[SAVED_PARTY_COUNT_OFFSET] = 2
        block[SAVED_PARTY_OFFSET:SAVED_PARTY_OFFSET + 100] = party_mon(258, (31, 5, 20, 0, 31, 12), (0, 1, 0, 1, 0, 1))
        block[SAVED_PARTY_OFFSET + 100:SAVED_PARTY_OFFSET + 200] = party_mon(25, (1, 2, 3, 4, 5, 6), (1, 0, 1, 0, 1, 0),
                                                                             personality=0x7777, level=12)
        party = tower_rules.party_training(bytes(block))
        self.assertEqual([(m["species"], m["level"], m["egg"]) for m in party], [(258, 30, False), (25, 12, False)])
        self.assertEqual(party[0]["ivs"], [31, 5, 20, 0, 31, 12])
        self.assertEqual(party[0]["trained"], [False, True, False, True, False, True])
        self.assertEqual(party[1]["ivs"], [1, 2, 3, 4, 5, 6])
        self.assertEqual(party[1]["trained"], [True, False, True, False, True, False])


if __name__ == "__main__":
    unittest.main()
