"""The launcher proofs' rough connection (scripts/multiplayer/proof_network.py RoughLink): late by the latency plus a
random share of the jitter, held through a stall, and never out of order (owner priority 2026-10-24: trades and
battles between two real PCs, where a friend's connection jitters and stalls)."""
from __future__ import annotations

from pathlib import Path
import random
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT / "src", ROOT / "scripts" / "multiplayer"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
from proof_network import RoughLink  # noqa: E402


class RoughLinkTests(unittest.TestCase):
    def test_a_steady_link_is_late_by_its_latency(self):
        link = RoughLink(40)
        self.assertAlmostEqual(link.delay(10.0, "a"), 0.040)
        self.assertAlmostEqual(link.delay(10.5, "a"), 0.040)

    def test_jitter_stays_in_its_range_and_never_reorders_a_direction(self):
        link = RoughLink(100, 80, rng=random.Random(5))
        now, arrivals = 0.0, {"a": [], "b": []}
        for step in range(2000):
            now += 0.002                                  # a message every 2 ms, faster than the jitter
            key = "a" if step % 3 else "b"
            wait = link.delay(now, key)
            self.assertGreaterEqual(wait, 0.0)
            arrivals[key].append(now + wait)
        for key, times in arrivals.items():
            self.assertEqual(times, sorted(times), key)   # in order, as on TCP
        spaced = RoughLink(100, 80, rng=random.Random(5))
        waits = [spaced.delay(t * 1.0, "c") for t in range(500)]   # one a second: no queueing
        self.assertTrue(all(0.100 <= w <= 0.180 for w in waits))
        self.assertGreater(max(waits) - min(waits), 0.05)  # it really jitters

    def test_a_stall_holds_every_message_until_it_ends(self):
        link = RoughLink(50, stall_every=30, stall_ms=3000, start=0.0)
        self.assertAlmostEqual(link.delay(1.0, "a"), 2.0)   # arrives at 1.05, inside 0-3 s: delivered at 3.0
        self.assertAlmostEqual(link.delay(10.0, "a"), 0.05)  # between stalls
        self.assertAlmostEqual(link.delay(31.0, "b"), 2.0)   # the next stall (30-33 s)
        self.assertAlmostEqual(link.delay(33.0, "b"), 0.05)

    def test_messages_held_by_a_stall_are_delivered_in_order_by_an_event_loop(self):
        # Run 214's trade-rough: the save's chunks sent during a stall were all due at the stall's end, and the loop ran
        # them in another order ("chunks must be sequential"). Each now has its own later time.
        import asyncio

        async def run():
            loop = asyncio.get_running_loop()
            link = RoughLink(0, stall_every=10, stall_ms=200, start=loop.time())
            delivered = []
            for n in range(200):
                loop.call_at(link.arrival(loop.time(), "up"), delivered.append, n)
            await asyncio.sleep(0.35)
            return delivered
        self.assertEqual(asyncio.run(run()), list(range(200)))

    def test_no_settings_means_no_delay(self):
        self.assertEqual(RoughLink().delay(5.0, "a"), 0.0)
        self.assertEqual(RoughLink(stall_every=30).delay(1.0, "a"), 0.0)   # a stall needs its length too


class LateBattleMessagesTests(unittest.TestCase):
    """proof_network.delay_battle_messages_to (the newcomers proof's give-up-mid-turn, KNOWN_ISSUES MS-126): one
    player's battle messages from the host late, the rest at once; after `resume` none overtakes one still held."""

    def test_one_players_battle_messages_are_late_in_order_and_never_overtaken(self):
        import asyncio
        from types import SimpleNamespace
        from emerald_multiplayer.server import WorldServer
        from proof_network import delay_battle_messages_to

        original = WorldServer._control
        self.addCleanup(setattr, WorldServer, "_control", original)
        sent = []
        WorldServer._control = lambda self, session, message: sent.append((session.player_id, message["n"]))
        giver, other = SimpleNamespace(player_id="giver"), SimpleNamespace(player_id="other")

        async def run():
            resume, end = delay_battle_messages_to("giver", 200)
            control = WorldServer._control
            control(None, giver, dict(type="battle_result", n=1))
            control(None, giver, dict(type="pong", n=2))            # not a battle message: at once
            control(None, other, dict(type="battle_result", n=3))   # another player's: at once
            await asyncio.sleep(0.05)
            resume()
            control(None, giver, dict(type="battle_result", n=4))   # after resume, but behind the held one
            await asyncio.sleep(0.05)
            held = list(sent)
            await asyncio.sleep(0.25)
            control(None, giver, dict(type="battle_result", n=5))   # nothing held any more: at once
            end()
            return held, WorldServer._control
        held, after = asyncio.run(run())
        self.assertEqual(held, [("giver", 2), ("other", 3)])
        self.assertEqual(sent, [("giver", 2), ("other", 3), ("giver", 1), ("giver", 4), ("giver", 5)])
        self.assertIsNot(after, original)   # end() restores the method the patch found (the recorder here)


if __name__ == "__main__":
    unittest.main()
