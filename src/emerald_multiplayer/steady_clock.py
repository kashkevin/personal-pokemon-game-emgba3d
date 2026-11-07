"""The host's clock for the times it measures across a battle: the PC's clock, less the changes made to it meanwhile.

The Battle Tower's solo commands and the eight-place championships' computer matches are settled by time on the host: a
command the game never started is void after two minutes, a started battle that never reports is a loss after a day
(tower_service.py, championship8.py). Those times were read from the PC's clock, so a change to that clock - set forward
or back by hand, as players do for the game's time-based events, or corrected by Windows' time sync after a flat clock
battery - counted as time passed: set a day forward, a battle in progress was counted as a loss; set a day back, a command
no game started kept the player's Tower closed a day longer (KNOWN_ISSUES MS-219).

This clock reads the PC's clock and a clock that never jumps but keeps counting while the PC sleeps (Windows' tick count,
Linux's boot time). Between two readings both move by the time that passed; a difference over a minute is a change made
to the PC's clock, and it is left out from then on. Time asleep still counts, as on the PC's clock. A change made while
the program was closed is not seen: after a restart the clock is the PC's again, as before.
"""
from __future__ import annotations

import sys
import threading
import time
from typing import Callable

CHANGE_SECONDS = 60.0       # between two readings, a difference of the two clocks over this is a change of the PC's clock


def sleeping_clock() -> Callable[[], float] | None:
    """Seconds from a clock that never jumps and counts the time the PC sleeps, or None where there is none."""
    if sys.platform == "win32":
        try:
            import ctypes
            ticks = ctypes.windll.kernel32.GetTickCount64      # milliseconds since Windows started, sleep included
            ticks.restype = ctypes.c_ulonglong
            ticks.argtypes = []
            ticks()
        except (AttributeError, OSError):
            return None
        return lambda: ticks() / 1000.0
    boottime = getattr(time, "CLOCK_BOOTTIME", None)        # Linux: CLOCK_MONOTONIC with suspend included
    if boottime is None:
        return None
    try:
        time.clock_gettime(boottime)
    except OSError:
        return None
    return lambda: time.clock_gettime(boottime)


class SteadyWallClock:
    """Seconds since the epoch: the PC's clock less the changes made to it while this clock was read (see the module)."""

    def __init__(self, wall: Callable[[], float] | None = None, steady: Callable[[], float] | None = None):
        self._wall = wall or (lambda: time.time())
        self._steady = steady or sleeping_clock() or time.monotonic
        self._lock = threading.Lock()
        self._last: tuple[float, float] | None = None
        self.offset = 0.0           # the changes seen so far (seconds the PC's clock was moved forward; back is negative)

    def __call__(self) -> float:
        with self._lock:
            wall, steady = self._wall(), self._steady()
            if self._last is not None:
                change = (wall - self._last[0]) - (steady - self._last[1])
                if abs(change) > CHANGE_SECONDS:
                    self.offset += change
            self._last = (wall, steady)
            return wall - self.offset


STEADY_WALL_CLOCK = SteadyWallClock()
