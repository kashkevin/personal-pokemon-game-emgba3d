"""Host-authoritative player friendship and Lucky Friends."""
from __future__ import annotations

from pathlib import Path
import random
import tempfile
import unittest
from uuid import uuid4

from emerald_multiplayer.balance import BALANCE
from emerald_multiplayer.friendship import FriendshipError, FriendshipStore, level_for, pair_key

WORLD = "22222222-2222-4222-8222-222222222222"


class Clock:
    def __init__(self):
        self.now = 1_790_000_000.0  # 2026-09-21 UTC

    def __call__(self):
        return self.now


class FixedRandom(random.Random):
    def __init__(self, value):
        super().__init__(0)
        self.value = value

    def random(self):
        return self.value


class FriendshipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "friendships.sqlite3"
        self.clock = Clock()
        self.store = FriendshipStore(self.path, WORLD, clock=self.clock, rng=FixedRandom(0.99))
        self.a, self.b, self.c = sorted(str(uuid4()) for _ in range(3))

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_levels_and_thresholds(self):
        self.assertEqual([level_for(p) for p in (0, 29, 30, 119, 120, 299, 300, 599, 600, 10_000)],
                         [0, 0, 1, 1, 2, 2, 3, 3, 4, 4])
        view = self.store.pair(self.a, self.b)
        self.assertEqual((view["level"], view["name"], view["points"], view["next"]), (0, "New Friends", 0, 30))
        self.assertEqual(view["lucky_chance"], BALANCE.lucky_trade_chance[0])
        with self.assertRaises(FriendshipError):
            pair_key(self.a, self.a)
        self.assertEqual(pair_key(self.b, self.a), (self.a, self.b))

    def test_each_activity_counts_once_and_daily_cap_applies(self):
        first = self.store.record_pair("trade", self.b, self.a, "tx-1")
        self.assertEqual(first["granted"], BALANCE.friendship_points["trade"])
        again = self.store.record_pair("trade", self.a, self.b, "tx-1")
        self.assertEqual(again["granted"], 0)
        total = first["granted"]
        for index in range(10):
            total += self.store.record_pair("battle_together", self.a, self.b, f"battle-{index}")["granted"]
        self.assertEqual(total, BALANCE.friendship_daily_cap)
        self.assertEqual(self.store.pair(self.a, self.b)["points"], BALANCE.friendship_daily_cap)
        # A new real day has a fresh cap.
        self.clock.now += 86_400
        self.assertEqual(self.store.record_pair("gym_together", self.a, self.b, "gym-1")["granted"],
                         BALANCE.friendship_points["gym_together"])
        with self.assertRaises(FriendshipError):
            self.store.record_pair("afk", self.a, self.b, "x")

    def test_level_up_is_reported(self):
        changes = [self.store.record_pair("trade", self.a, self.b, f"t{i}") for i in range(2)]
        self.assertFalse(changes[0]["level_up"])
        self.assertTrue(changes[1]["level_up"])
        self.assertEqual(changes[1]["level"], "Good Friends")

    def test_time_together_is_small_and_separately_capped(self):
        block = BALANCE.friendship_session_minutes * 60
        changes = self.store.add_time_together([self.a, self.b, self.c], block * 10)
        per_pair = {}
        for change in changes:
            per_pair[change["pair"]] = per_pair.get(change["pair"], 0) + change["granted"]
        self.assertEqual(len(per_pair), 3)
        self.assertTrue(all(points == 8 for points in per_pair.values()), per_pair)
        # Partial time is kept for later.
        self.assertEqual(self.store.add_time_together([self.a, self.b], block / 2), [])

    def test_shared_activity_awards_every_pair_with_the_actor(self):
        results = self.store.record_shared("event_together", self.a, [self.a, self.b, self.c], "event-9")
        self.assertEqual(len(results), 2)
        self.assertEqual(self.store.pair(self.b, self.c)["points"], 0)

    def test_lucky_trade_chance_by_level_and_guarantee(self):
        store = FriendshipStore(Path(self.temp.name) / "low.sqlite3", WORLD, clock=self.clock, rng=FixedRandom(0.04))
        try:
            self.assertEqual(store.lucky_trade_decision(self.a, self.b), (True, False))
        finally:
            store.close()
        self.assertEqual(self.store.lucky_trade_decision(self.a, self.b), (False, False))

    def best_friends(self):
        day = 0
        while self.store.pair(self.a, self.b)["level"] < 4:
            for kind in ("trade", "battle_together", "gym_together", "event_together"):
                self.store.record_pair(kind, self.a, self.b, f"{kind}-{day}")
            day += 1
            self.clock.now += 86_400

    def test_lucky_friends_roll_cooldown_guarantee_and_consumption(self):
        self.best_friends()
        self.assertFalse(self.store.pair(self.a, self.b)["lucky_friends"])
        # An unlucky roll (FixedRandom 0.99) starts the cooldown...
        self.assertFalse(self.store.record_pair("trade", self.a, self.b, "after-best-0")["lucky_friends"])
        self.store._rng = FixedRandom(0.05)  # below the 10% Lucky Friends chance
        # ...so repeating activities inside it never rolls again.
        cooldown = self.store.record_pair("battle_together", self.a, self.b, "after-best-1")
        self.assertFalse(cooldown["lucky_friends"])
        self.clock.now += BALANCE.lucky_friends_cooldown_seconds + 1
        rolled = self.store.record_pair("battle_together", self.a, self.b, "after-best-2")
        self.assertTrue(rolled["lucky_friends"])
        view = self.store.pair(self.a, self.b)
        self.assertTrue(view["lucky_friends"])
        self.assertEqual(view["lucky_chance"], 1.0)
        self.assertEqual(self.store.lucky_trade_decision(self.a, self.b), (True, True))
        tx = str(uuid4())
        self.store.commit_trade(tx, self.a, self.b, True, True)
        self.store.commit_trade(tx, self.b, self.a, True, True)  # idempotent
        self.assertFalse(self.store.pair(self.a, self.b)["lucky_friends"])
        self.assertEqual(self.store.lucky_trade_count(self.a, self.b), 1)
        self.assertEqual(self.store.lucky_trade_count(self.b), 1)

    def test_only_best_friends_can_become_lucky_friends(self):
        self.store._rng = FixedRandom(0.0)
        result = self.store.record_pair("trade", self.a, self.b, "tx")
        self.assertFalse(result["lucky_friends"])
        self.assertFalse(self.store.pair(self.a, self.b)["lucky_friends"])

    def test_world_binding_and_persistence(self):
        self.store.record_pair("trade", self.a, self.b, "tx")
        self.store.close()
        with self.assertRaises(FriendshipError):
            FriendshipStore(self.path, str(uuid4()))
        self.store = FriendshipStore(self.path, WORLD, clock=self.clock)
        self.assertEqual(self.store.pair(self.a, self.b)["points"], BALANCE.friendship_points["trade"])
        view = self.store.view_for(self.a, [self.a, self.b, self.c])
        self.assertEqual(set(view), {self.b, self.c})


if __name__ == "__main__":
    unittest.main()
