"""The host's clock for the times it measures across a battle (steady_clock.py; KNOWN_ISSUES MS-219): the PC's clock, less
the changes made to it while the program runs, found against a clock that never jumps but counts the time the PC sleeps."""
from __future__ import annotations

import inspect
import sys
import time
import unittest

from emerald_multiplayer.championship8 import EightChampionships
from emerald_multiplayer.shared_world import SharedWorld
from emerald_multiplayer.steady_clock import CHANGE_SECONDS, STEADY_WALL_CLOCK, SteadyWallClock, sleeping_clock


class Clocks:
    """The PC's clock (``wall``) and the clock that never jumps (``steady``), set by the test."""

    def __init__(self):
        self.wall, self.steady = 1_800_000_000.0, 5_000.0

    def clock(self):
        return SteadyWallClock(wall=lambda: self.wall, steady=lambda: self.steady)

    def wait(self, seconds):
        self.wall += seconds
        self.steady += seconds


class SteadyWallClockTests(unittest.TestCase):
    def setUp(self):
        self.clocks = Clocks()
        self.clock = self.clocks.clock()

    def test_it_reads_the_pcs_clock_while_nobody_changes_it(self):
        self.assertEqual(self.clock(), self.clocks.wall)
        self.clocks.wait(30)
        self.assertEqual(self.clock(), self.clocks.wall)
        self.clocks.wait(8 * 3600)                                  # the PC asleep for the night: both clocks count it
        self.assertEqual(self.clock(), self.clocks.wall)
        self.assertEqual(self.clock.offset, 0)

    def test_the_pcs_clock_set_forward_is_not_time_passed(self):
        start = self.clock()
        self.clocks.wall += 86400 + 3600                            # set a day and an hour forward
        self.clocks.wait(5)
        self.assertEqual(self.clock(), start + 5)
        self.clocks.wait(10)
        self.assertEqual(self.clock(), start + 15)                  # and from then on
        self.assertEqual(self.clock.offset, 86400 + 3600)

    def test_the_pcs_clock_set_back_is_not_time_undone(self):
        start = self.clock()
        self.clocks.wall -= 86400                                   # set a day back
        self.clocks.wait(121)
        self.assertEqual(self.clock(), start + 121)
        self.assertEqual(self.clock.offset, -86400)

    def test_a_small_step_is_the_pcs_clock_as_it_reads(self):
        start = self.clock()
        self.clocks.wall += CHANGE_SECONDS                          # a time sync's step of a minute: not a change
        self.assertEqual(self.clock(), start + CHANGE_SECONDS)
        self.clocks.wall += CHANGE_SECONDS + 1                      # over it: one
        self.assertEqual(self.clock(), start + CHANGE_SECONDS)

    def test_several_changes_add_up(self):
        start = self.clock()
        self.clocks.wall += 7200
        self.clock()
        self.clocks.wall -= 3 * 86400
        self.clock()
        self.clocks.wait(60)
        self.assertEqual(self.clock(), start + 60)

    def test_this_platform_has_a_clock_that_counts_sleep(self):
        source = sleeping_clock()
        if sys.platform == "win32" or hasattr(time, "CLOCK_BOOTTIME"):
            self.assertIsNotNone(source)                            # Windows' tick count, Linux's boot time
            first = source()
            self.assertGreater(first, 0)
            self.assertGreaterEqual(source(), first)
        # the host's clock reads the PC's clock (no test here changes it)
        self.assertLess(abs(STEADY_WALL_CLOCK() - time.time()), CHANGE_SECONDS)

    def test_the_tower_and_the_eight_place_championships_use_it(self):
        world = SharedWorld(":memory:", "11111111-1111-4111-8111-111111111111")
        self.addCleanup(world.close)
        self.assertIs(world.tower._now, STEADY_WALL_CLOCK)
        self.assertIs(inspect.signature(EightChampionships.__init__).parameters["clock"].default, STEADY_WALL_CLOCK)


if __name__ == "__main__":
    unittest.main()
