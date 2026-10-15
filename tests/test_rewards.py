"""Battle Frontier rewards on the wager wallet stream: the word format, the wire validators and the mailbox."""
from __future__ import annotations

import struct
import unittest
from uuid import uuid4

from emerald_multiplayer import rewards
from emerald_multiplayer.protocol import ProtocolError
from emerald_multiplayer.shared_world_protocol import validate_wallet, validate_world_request
from emerald_multiplayer.wagers import WagerError, Wagers
from emerald_multiplayer.world_mailbox import WorldInbound, WorldMailboxError

WORLD = "11111111-1111-4111-8111-111111111111"


class WordTests(unittest.TestCase):
    def test_round_trip_and_the_engines_bit_layout(self):
        self.assertEqual(rewards.encode(rewards.KIND_BP, 12), 0x4100000C)
        self.assertEqual(rewards.encode(rewards.KIND_BP_DEBIT, 16), 0x43000010)
        word = rewards.encode(rewards.KIND_ITEM, rewards.item_payload(102, 2))       # Rare Candy x2
        self.assertEqual(word, 0x42006602)
        self.assertEqual(rewards.decode(word), (rewards.KIND_ITEM, (102 << 8) | 2))
        for delta in (0x4100000C, word, 0x43000010, 0x44000007, 0x45000007):
            self.assertTrue(rewards.is_reward_word(delta) and rewards.valid_wallet_delta(delta))
        self.assertLess(word, 2 ** 31)       # a signed 32-bit wallet delta

    def test_money_is_not_a_reward_and_nonsense_is_refused(self):
        for delta in (1, 999_999, -999_999, 0):
            self.assertFalse(rewards.is_reward_word(delta))
        self.assertTrue(rewards.valid_wallet_delta(175) and rewards.valid_wallet_delta(-999_999))
        for delta in (0, 1_000_000, -1_000_000, 0x40000005, 0x46000005, 0x61000005, 0x41000000, 0x41002710, 0x42000001,
                      0x42006600, 0x42006664, True, 2 ** 31, "5", None):
            self.assertFalse(rewards.valid_wallet_delta(delta), delta)
        for kind, payload in ((0, 1), (6, 1), (rewards.KIND_BP, 0), (rewards.KIND_BP, 10_000), (rewards.KIND_ITEM, 5),
                              (rewards.KIND_ITEM, rewards.item_payload(0, 1)), (rewards.KIND_ITEM, rewards.item_payload(5, 100)),
                              (rewards.KIND_ITEM, rewards.item_payload(5, 0)), (rewards.KIND_BP, True)):
            with self.assertRaises(rewards.RewardError):
                rewards.encode(kind, payload)


class WireTests(unittest.TestCase):
    def test_the_server_to_game_wallet_field_accepts_money_and_rewards_only(self):
        for delta in (175, -50, rewards.encode(rewards.KIND_BP, 3), rewards.encode(rewards.KIND_ITEM, (68 << 8) | 1)):
            self.assertEqual(validate_wallet({"seq": 4, "delta": delta}), {"seq": 4, "delta": delta})
        for delta in (0, 1_000_000, 0x40000005, True, "1"):
            with self.assertRaises(ProtocolError):
                validate_wallet({"seq": 4, "delta": delta})

    def test_the_mailbox_carries_a_reward_word_in_its_signed_delta(self):
        word = rewards.encode(rewards.KIND_BP, 7)
        inbound = WorldInbound(wallet_seq=3, wallet_delta=word)
        raw = inbound.pack()
        self.assertEqual(len(raw), len(WorldInbound().pack()))
        self.assertIn(struct.pack("<IiI", 3, word, 0), raw)
        for bad in (0x40000005, 1_000_000):
            with self.assertRaises(WorldMailboxError):
                WorldInbound(wallet_seq=3, wallet_delta=bad)
        with self.assertRaises(WorldMailboxError):
            WorldInbound(wallet_seq=0, wallet_delta=word)         # still needs both a sequence and a delta

    def test_a_shop_purchase_request_names_a_slot_and_nothing_else_does(self):
        base = dict(type="frontier", session_epoch=3, request_id=str(uuid4()))
        validate_world_request({**base, "op": "shop_buy", "slot": 2}, 3)
        for request in ({**base, "op": "shop_buy"}, {**base, "op": "shop_buy", "slot": -1}, {**base, "op": "shop_buy", "slot": 32},
                        {**base, "op": "shop_buy", "slot": True}, {**base, "op": "status", "slot": 1},
                        {**base, "op": "shop_buy", "slot": 1, "mode": "frontier"}):
            with self.assertRaises(ProtocolError):
                validate_world_request(request, 3)


class WalletTests(unittest.TestCase):
    def setUp(self):
        self.wagers = Wagers(":memory:", WORLD)
        self.addCleanup(self.wagers.close)
        self.player = str(uuid4())

    def test_a_reward_is_queued_once_per_reference_and_numbered_with_the_money(self):
        self.assertEqual(self.wagers.grant(self.player, 500, "battle"), 1)
        self.assertEqual(self.wagers.grant_reward(self.player, rewards.KIND_BP, 3, "battle:bp"), 2)
        self.assertIsNone(self.wagers.grant_reward(self.player, rewards.KIND_BP, 3, "battle:bp"))
        self.assertIsNone(self.wagers.grant(self.player, 500, "battle"))
        self.assertEqual([w["seq"] for w in self.wagers.pending_for(self.player)], [1, 2])
        # the game applies them in order: it is offered each only after the previous receipt
        self.assertEqual(self.wagers.next_adjustment(self.player, 0), {"seq": 1, "delta": 500})
        self.wagers.applied(self.player, 1, 500)
        self.assertEqual(self.wagers.next_adjustment(self.player, 1), {"seq": 2, "delta": rewards.encode(rewards.KIND_BP, 3)})
        self.assertEqual(self.wagers.entry(self.player, "battle:bp")["applied"], None)
        self.wagers.applied(self.player, 2, 3)
        self.assertEqual(self.wagers.entry(self.player, "battle:bp")["applied"], 3)
        self.assertIsNone(self.wagers.next_adjustment(self.player, 2))

    def test_invalid_rewards_are_refused_and_nothing_is_queued(self):
        for kind, payload in ((rewards.KIND_BP, 0), (rewards.KIND_BP, 10_000), (9, 1), (rewards.KIND_ITEM, 1)):
            with self.assertRaises(WagerError):
                self.wagers.grant_reward(self.player, kind, payload, "x")
        with self.assertRaises(WagerError):
            self.wagers.grant_reward(self.player, rewards.KIND_BP, 1, "")
        self.assertEqual(self.wagers.pending_for(self.player), [])


class CatchVerdictTests(unittest.TestCase):
    """The host tells a game that reported a World Event catch to keep its copy or release the duplicate (Update 17)."""

    def setUp(self):
        import random
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from emerald_multiplayer.balance import BALANCE
        from emerald_multiplayer.server import WorldServer
        from emerald_multiplayer.shared_world import SharedWorld
        from test_event_catch import CATALOGUE, LOCATIONS, Clock
        self.BALANCE, self.WorldServer, self.SimpleNamespace = BALANCE, WorldServer, SimpleNamespace
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = Clock()
        self.world = SharedWorld(Path(self.temp.name) / "w.sqlite3", WORLD, clock=self.clock, rng=random.Random(5),
                                 event_catalogue=CATALOGUE, locations=LOCATIONS, event_condition_chance=0.0)
        self.addCleanup(self.world.close)
        self.wagers = Wagers(":memory:", WORLD)
        self.addCleanup(self.wagers.close)
        self.a, self.b = str(uuid4()), str(uuid4())
        self.names = {self.a: "Alice", self.b: "Bob"}
        self.server = SimpleNamespace(wagers=self.wagers, shared_world=self.world, _player_name=lambda p: self.names[p])
        self.sessions = {p: SimpleNamespace(player_id=p, display_name=self.names[p]) for p in (self.a, self.b)}

    def report(self, player, event):
        outcome = self.world.event_result(player, event, "caught", self.names[player])
        self.WorldServer._catch_verdict(self.server, self.sessions[player], event)
        return outcome

    def words(self, player):
        return [(rewards.decode(w["delta"]), w["battle_id"]) for w in self.wagers.pending_for(player)]

    def race(self):
        self.world.set_active_players(2)
        event = self.world.spawn_event(progression_level=30, category="rare")["event_id"]
        self.world.claim_event(self.a, event)
        self.world.player_disconnected(self.a)
        self.clock.now += self.BALANCE.event_claim_grace_seconds + 1
        self.world.tick_events(2, lambda: 30)                       # A's claim lapsed while A's game fought offline
        self.assertEqual(self.world.claim_event(self.b, event), "granted")
        return event

    def test_the_first_report_keeps_and_the_second_claimants_copy_is_released_exactly_once(self):
        event = self.race()
        self.assertEqual(self.report(self.b, event), "consumed")
        self.assertEqual(self.report(self.a, event), "gone")                          # A reports second
        number = rewards.catch_number(event)
        self.assertEqual(self.words(self.b), [((rewards.KIND_CATCH_KEEP, number), f"catch:{event}")])
        self.assertEqual(self.words(self.a), [((rewards.KIND_CATCH_RELEASE, number), f"catch:{event}")])
        for _ in range(4):                                                            # the game keeps reporting until it hears
            self.report(self.a, event)
            self.report(self.b, event)
        self.assertEqual(len(self.words(self.a)), 1)
        self.assertEqual(len(self.words(self.b)), 1)
        # delivered like any wallet adjustment: numbered, in order, and applied once per save
        self.assertEqual(self.wagers.next_adjustment(self.a, 0), {"seq": 1, "delta": rewards.encode(rewards.KIND_CATCH_RELEASE, number)})
        self.wagers.applied(self.a, 1, 1)
        self.assertIsNone(self.wagers.next_adjustment(self.a, 1))
        self.assertEqual(self.wagers.entry(self.a, f"catch:{event}")["applied"], 1)

    def test_the_loser_is_told_who_won_and_the_winner_is_not_told_anything_unusual(self):
        event = self.race()
        self.report(self.b, event)
        self.report(self.a, event)
        seen = []
        for _ in range(6):
            note = self.world.notice_view()
            if note:
                seen.append((note["text"], note["to"]))
            self.clock.now += self.BALANCE.notice_seconds + 1
        self.assertTrue(any("BOB" in text and "caught it first" in text and to == [self.a] for text, to in seen), seen)

    def test_a_catch_number_is_stable_for_huge_event_numbers(self):
        self.assertEqual(rewards.catch_number(1), 1)
        self.assertEqual(rewards.catch_number(0x800000), 0x800000)
        self.assertEqual(rewards.catch_number(0x800001), 1)
        for bad in (0, -1, True, "3", None):
            with self.assertRaises(rewards.RewardError):
                rewards.catch_number(bad)
        self.assertTrue(rewards.valid_wallet_delta(rewards.encode(rewards.KIND_CATCH_KEEP, 0x7FFFFF)))
        for payload in (0, 0x800000):
            with self.assertRaises(rewards.RewardError):
                rewards.encode(rewards.KIND_CATCH_RELEASE, payload)


if __name__ == "__main__":
    unittest.main()
