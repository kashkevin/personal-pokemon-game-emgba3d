"""M25: the native battle relay's speed, measured on the real host, server and client session
with a synthetic native core (tests/test_battle_execution.py's fixture).

The synthetic core answers at once, so a run costs the relay's own waiting: the client's polling
sleeps, the journaling and the per-step round trips. ``FRAME`` adds the game's own delay per
native command (the bridge acts once per frame; 16.7 ms at 60 fps, one of the two causes the
diagnosis found). Run with ``-s`` to print the numbers.

What is checked (a regression bound, not a benchmark of a real game): the number of native
round trips per battle start-up and the time with and without the game's frame delay."""
import asyncio
from collections import Counter
import os
import time
import unittest

from emerald_multiplayer import battle_execution, battle_session
from emerald_multiplayer.native_battle import Opcode
import test_battle_execution as fixture  # the module only: its test classes must not be collected twice

FRAME = float(os.environ.get("BATTLE_BENCH_FRAME_MS", "16")) / 1000


class RelayThroughputTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # IsolatedAsyncioTestCase turns asyncio's debug mode on, which records a stack for every
        # callback and more than doubles the cost of a run: measure what production costs.
        asyncio.get_running_loop().set_debug(False)
        await fixture.BattleExecutionNetworkTests.asyncSetUp(self)

    asyncTearDown = fixture.BattleExecutionNetworkTests.asyncTearDown
    actor = fixture.BattleExecutionNetworkTests.actor
    call = fixture.BattleExecutionNetworkTests.call
    enable = fixture.BattleExecutionNetworkTests.enable
    accept = fixture.BattleExecutionNetworkTests.accept
    exchange = fixture.BattleExecutionNetworkTests.exchange
    run_clients = fixture.BattleExecutionNetworkTests.run_clients

    async def measure(self, frame, *, multi=False):
        counts, original = Counter(), fixture.NativeFixture.rpc
        if os.environ.get("BATTLE_BENCH_OLD_POLL"):      # before M25: a fixed 10 ms client poll
            self.addCleanup(setattr, battle_session, "IDLE_POLL_MIN", battle_session.IDLE_POLL_MIN)
            battle_session.IDLE_POLL_MIN = battle_session.IDLE_POLL_MAX
        if os.environ.get("BATTLE_BENCH_KEEP_EVERY_STEP"):  # before the deadline-based KEEP
            self.addCleanup(setattr, battle_execution, "KEEP_BELOW_FRAMES", battle_execution.KEEP_BELOW_FRAMES)
            battle_execution.KEEP_BELOW_FRAMES = 601

        async def counted(model, command):
            counts[Opcode(command.opcode).name] += 1
            if frame:
                await asyncio.sleep(frame)
            return await original(model, command)

        runs, original_run = [], battle_session.NativeBattleSession.run

        profile = None
        if os.environ.get("BATTLE_BENCH_PROFILE"):
            import cProfile
            profile = cProfile.Profile()
        clients = 4 if multi else 2

        async def timed_run(session, challenge):
            start = time.perf_counter()
            if profile is not None and not runs and not getattr(profile, "started", False):
                profile.started = True
                profile.enable()
            try:
                return await original_run(session, challenge)
            finally:
                runs.append((start, time.perf_counter()))
                if profile is not None and len(runs) == clients:
                    profile.disable()
                    import pstats
                    stats = pstats.Stats(profile)
                    stats.sort_stats("tottime").print_stats(18)

        fixture.NativeFixture.rpc = counted
        battle_session.NativeBattleSession.run = timed_run
        try:
            await self.run_clients(multi=multi, use_journal=True)
        finally:
            fixture.NativeFixture.rpc = original
            battle_session.NativeBattleSession.run = original_run
        # Only the relay: from the first client's start to the last client's end (set-up and the
        # store's integrity checks around it are not part of a battle).
        elapsed = max(end for _, end in runs) - min(start for start, _ in runs)
        return elapsed, counts

    def report(self, label, elapsed, counts):
        total = sum(counts.values())
        print(f"\n[M25] {label}: {elapsed:.2f} s, {total} native commands "
              f"({elapsed / total * 1000:.1f} ms each) {dict(sorted(counts.items()))}")

    async def test_two_player_start_up_without_game_delay(self):
        elapsed, counts = await self.measure(0)
        self.report("2 players, instant core", elapsed, counts)
        # M25 regression bound: 76 native commands (96 while KEEP went out on every step; start-up
        # moves a block every step, and an accepted block command already refreshes the watchdog);
        # the time is a loose ceiling for slow machines.
        if not os.environ.get("BATTLE_BENCH_KEEP_EVERY_STEP"):
            self.assertEqual(sum(counts.values()), 76)
            self.assertEqual(counts["KEEP"], 0)
        self.assertLess(elapsed, 4.0)

    async def test_two_player_start_up_with_the_games_frame_delay(self):
        elapsed, counts = await self.measure(FRAME)
        self.report(f"2 players, {FRAME * 1000:.0f} ms game delay", elapsed, counts)

    async def test_four_player_start_up_with_the_games_frame_delay(self):
        elapsed, counts = await self.measure(FRAME, multi=True)
        self.report(f"4 players, {FRAME * 1000:.0f} ms game delay", elapsed, counts)
        if not os.environ.get("BATTLE_BENCH_KEEP_EVERY_STEP"):
            self.assertEqual(sum(counts.values()), 224)   # 264 with a KEEP on every step

    async def test_waiting_for_the_players_sends_a_keep_only_when_the_watchdog_needs_it(self):
        # After START the cores wait 60 queries for their players (no outbound block): most of a
        # real battle. The watchdog (600 frames, 40 per query here) needs a KEEP every 4th step,
        # not every step, and it never runs out (an expired core fails the battle).
        self.addCleanup(setattr, fixture.NativeFixture, "IDLE_QUERIES", 0)
        fixture.NativeFixture.IDLE_QUERIES = 60
        elapsed, counts = await self.measure(FRAME)
        self.report(f"2 players waiting 60 steps, {FRAME * 1000:.0f} ms game delay", elapsed, counts)
        if not os.environ.get("BATTLE_BENCH_KEEP_EVERY_STEP"):
            self.assertLessEqual(counts["KEEP"], counts["QUERY"] // 3)
            self.assertGreater(counts["KEEP"], 0)
