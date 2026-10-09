"""PvP wagers: consent, settlement and exactly-once wallet adjustments."""
from __future__ import annotations

from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from uuid import uuid4

from emerald_multiplayer.wagers import (
    ENCRYPTION_KEY_OFFSET, MONEY_OFFSET, WagerError, Wagers, format_money, money_from_snapshot,
)

WORLD = "33333333-3333-4333-8333-333333333333"
RICH = 50_000


class WagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "wagers.sqlite3"
        self.wagers = Wagers(self.path, WORLD)
        self.a, self.b, self.c, self.d = sorted(str(uuid4()) for _ in range(4))
        self.battle = str(uuid4())

    def tearDown(self):
        self.wagers.close()
        self.temp.cleanup()

    def funds(self, *players, amount=RICH):
        return {player: amount for player in players}

    def agreed(self, players, amount=5000, mode=2):
        self.wagers.propose(self.battle, players[0], list(players), amount, self.funds(*players))
        for player in players[1:]:
            self.wagers.accept(self.battle, player, amount, RICH)
        self.assertTrue(self.wagers.ready(self.battle))
        self.wagers.lock(self.battle, self.funds(*players))

    def apply(self, player, save_seq, *, money):
        """Simulate one game applying its next adjustment; returns (seq, money)."""
        adjustment = self.wagers.next_adjustment(player, save_seq & 0xFF)
        if adjustment is None:
            return save_seq, money, []
        delta = adjustment["delta"]
        moved = min(money, -delta) if delta < 0 else min(delta, 999_999 - money)
        money += moved if delta > 0 else -moved
        credits = self.wagers.applied(player, adjustment["seq"], moved)
        return adjustment["seq"], money, credits

    def test_money_helpers(self):
        block1, block2 = bytearray(0x500), bytearray(0x100)
        struct.pack_into("<I", block2, ENCRYPTION_KEY_OFFSET, 0x12345678)
        struct.pack_into("<I", block1, MONEY_OFFSET, 3052 ^ 0x12345678)
        self.assertEqual(money_from_snapshot(SimpleNamespace(save_block1=bytes(block1), save_block2=bytes(block2))), 3052)
        self.assertEqual(format_money(1234567), "$1,234,567")

    def test_proposal_requires_consent_bounds_and_funds(self):
        players = [self.a, self.b]
        for amount in (99, 100_001, True, "5"):
            with self.subTest(amount=amount), self.assertRaises(WagerError):
                self.wagers.propose(self.battle, self.a, players, amount, self.funds(*players))
        with self.assertRaises(WagerError):
            self.wagers.propose(self.battle, self.c, players, 500, self.funds(*players))
        with self.assertRaises(WagerError) as caught:
            self.wagers.propose(self.battle, self.a, players, 5000, {self.a: RICH, self.b: 4999})
        self.assertEqual(caught.exception.code, "insufficient_funds")
        view = self.wagers.propose(self.battle, self.a, players, 5000, self.funds(*players))
        self.assertEqual((view["amount"], view["accepted"], view["state"]), (5000, [self.a], "proposed"))
        self.assertFalse(self.wagers.ready(self.battle))
        with self.assertRaises(WagerError):
            self.wagers.lock(self.battle, self.funds(*players))
        with self.assertRaises(WagerError) as caught:
            self.wagers.accept(self.battle, self.b, 4000, RICH)
        self.assertEqual(caught.exception.code, "wager_changed")
        self.wagers.accept(self.battle, self.b, 5000, RICH)
        self.assertTrue(self.wagers.ready(self.battle))
        # Removing a wager (amount 0) returns to an ordinary battle.
        self.assertIsNone(self.wagers.propose(self.battle, self.a, players, 0, {}))
        self.assertTrue(self.wagers.ready(self.battle))

    def test_decline_and_cancel_move_no_money(self):
        players = [self.a, self.b]
        self.wagers.propose(self.battle, self.a, players, 5000, self.funds(*players))
        self.wagers.decline(self.battle, self.b)
        self.assertIsNone(self.wagers.view(self.battle))
        self.agreed(players)
        self.wagers.cancel(self.battle)
        self.assertEqual(self.wagers.view(self.battle)["state"], "void")
        self.assertEqual(self.wagers.settle(self.battle, players, 2, 1), [])
        self.assertIsNone(self.wagers.next_adjustment(self.b, 0))

    def test_draw_moves_nothing(self):
        players = [self.a, self.b]
        self.agreed(players)
        self.assertEqual(self.wagers.settle(self.battle, players, 2, 3), [])
        self.assertEqual(self.wagers.view(self.battle)["state"], "settled")
        self.assertIsNone(self.wagers.next_adjustment(self.a, 0))

    def test_singles_loser_pays_winner_exactly_once(self):
        players = [self.a, self.b]
        self.agreed(players)
        self.assertEqual(self.wagers.settle(self.battle, players, 2, 2), [(self.a, 5000)])
        self.assertEqual(self.wagers.settle(self.battle, players, 2, 2), [])  # already settled
        self.assertIsNone(self.wagers.next_adjustment(self.b, 0))  # winner waits for collection
        seq_a, money_a, credits = self.apply(self.a, 0, money=20_000)
        self.assertEqual((seq_a, money_a), (1, 15_000))
        self.assertEqual(credits, [(self.b, 5000, self.battle)])
        seq_b, money_b, _ = self.apply(self.b, 0, money=1000)
        self.assertEqual((seq_b, money_b), (1, 6000))
        # Applied adjustments never apply twice for the same save.
        self.assertIsNone(self.wagers.next_adjustment(self.a, seq_a))
        self.assertIsNone(self.wagers.next_adjustment(self.b, seq_b))
        # A repeated receipt never pays the winner twice.
        self.assertEqual(self.wagers.applied(self.a, 1, 5000), [])

    def test_loser_short_of_money_pays_only_what_is_collected(self):
        players = [self.a, self.b]
        self.agreed(players)
        self.wagers.settle(self.battle, players, 2, 2)
        seq, money, credits = self.apply(self.a, 0, money=1200)  # spent money before the debit applied
        self.assertEqual((seq, money), (1, 0))
        self.assertEqual(credits, [(self.b, 1200, self.battle)])
        self.assertEqual(self.wagers.next_adjustment(self.b, 0), {"seq": 1, "delta": 1200})

    def test_reloaded_older_save_collects_again_but_never_pays_twice(self):
        players = [self.a, self.b]
        self.agreed(players)
        self.wagers.settle(self.battle, players, 2, 1)
        self.apply(self.b, 0, money=10_000)
        # The loser reloads a save from before the debit: it applies again.
        again = self.wagers.next_adjustment(self.b, 0)
        self.assertEqual(again, {"seq": 1, "delta": -5000})
        self.assertEqual(self.wagers.applied(self.b, 1, 5000), [])  # winner already owed in full
        winner = [row for row in self.wagers.pending_for(self.a)]
        self.assertEqual([row["delta"] for row in winner], [5000])

    def test_partial_collection_tops_up_on_reapplication(self):
        players = [self.a, self.b]
        self.agreed(players)
        self.wagers.settle(self.battle, players, 2, 1)
        self.assertEqual(self.wagers.applied(self.b, 1, 2000), [(self.a, 2000, self.battle)])
        self.assertEqual(self.wagers.applied(self.b, 1, 5000), [(self.a, 3000, self.battle)])
        self.assertEqual(sum(row["delta"] for row in self.wagers.pending_for(self.a)), 5000)

    def test_team_battle_pays_slot_opponents(self):
        players = [self.a, self.b, self.c, self.d]  # teams a+c vs b+d
        self.agreed(players, amount=1000, mode=3)
        debits = self.wagers.settle(self.battle, players, 3, 2)
        self.assertEqual(debits, [(self.a, 1000), (self.c, 1000)])
        credits = self.wagers.applied(self.a, 1, 1000) + self.wagers.applied(self.c, 1, 1000)
        self.assertEqual(credits, [(self.b, 1000, self.battle), (self.d, 1000, self.battle)])

    def test_sequences_survive_restored_database_and_low_byte_wraparound(self):
        players = [self.a, self.b]
        # The save reports an applied sequence the host never issued (restored backup).
        self.assertEqual(self.wagers.applied(self.a, 300, 0), [])
        self.agreed(players)
        self.wagers.settle(self.battle, players, 2, 2)
        adjustment = self.wagers.next_adjustment(self.a, 300 & 0xFF)
        self.assertEqual(adjustment, {"seq": 301, "delta": -5000})
        self.assertIsNone(self.wagers.next_adjustment(self.a, 301 & 0xFF))
        for seq, amount in ((0, 0), (0x10000, 0), (1, -1), (1, 1_000_000), ("1", 0)):
            self.assertEqual(self.wagers.applied(self.a, seq, amount), [])

    def test_persistence_and_world_binding(self):
        players = [self.a, self.b]
        self.agreed(players)
        self.wagers.close()
        with self.assertRaises(WagerError):
            Wagers(self.path, str(uuid4()))
        self.wagers = Wagers(self.path, WORLD)
        self.assertEqual(self.wagers.view(self.battle)["state"], "locked")


if __name__ == "__main__":
    unittest.main()
