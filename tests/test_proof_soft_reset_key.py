"""The proofs' soft reset key (native_launcher_soft_reset_proof.open_reset_page), pressed again when nothing opened.

windows-package run 347's busy-4 pressed the reset key 0.1 s after a trade applied; the game takes the key only on the
free field (the engine's multiplayer_soft_reset.h) and dropped it, and the proof waited 60 s for a page that a single
press never asked for. Now a press that opened nothing within its wait is made again (up to three presses), a window
that opened and waits for its launcher is waited for without another press, and reset_once waits for the field first.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT / "src", ROOT / "scripts" / "multiplayer", ROOT / "scripts" / "windows-runtime"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
import native_launcher_soft_reset_proof as soft_reset  # noqa: E402

QUESTION = SimpleNamespace(title="Reset the game?", rows=[SimpleNamespace(label="No, keep playing"),
                                                          SimpleNamespace(label="Yes, reset now")])


class Probe:
    """A game: each press of the reset key is taken or dropped in turn (`taken`); `active` once one was taken."""

    def __init__(self, taken, waits=False):
        self.taken, self.waits = list(taken), waits
        self.presses = 0
        self.active = False

    async def press_reset_key(self):
        self.presses += 1
        if self.taken and self.taken.pop(0):
            self.active = True

    def read(self):
        return {"active": self.active}


def fake_shown(probe, timeouts):
    """shown(): the screen once a window is active and no longer waits for its launcher; TimeoutError otherwise."""
    async def shown(p, timeout=60):
        timeouts.append(timeout)
        if p.active and not p.waits:
            return {"active": True}, QUESTION
        if p.active and p.waits:
            p.waits = False            # its launcher answers within the longer wait
            raise TimeoutError
        raise TimeoutError
    return shown


class SoftResetKeyTests(unittest.TestCase):
    def open(self, probe, **options):
        timeouts = []
        with mock.patch.object(soft_reset, "shown", fake_shown(probe, timeouts)):
            screen = asyncio.run(soft_reset.SoftResetProof.open_reset_page(None, probe, **options))
        return screen, timeouts

    def test_a_dropped_press_is_made_again(self):
        probe = Probe([False, True])
        screen, timeouts = self.open(probe)
        self.assertIs(screen, QUESTION)
        self.assertEqual(probe.presses, 2)
        self.assertEqual(timeouts, [10, 10])

    def test_a_window_waiting_for_its_launcher_gets_no_second_press(self):
        probe = Probe([True], waits=True)
        screen, timeouts = self.open(probe)
        self.assertIs(screen, QUESTION)
        self.assertEqual(probe.presses, 1)
        self.assertEqual(timeouts, [10, 60])

    def test_three_presses_that_open_nothing_fail(self):
        probe = Probe([False, False, False])
        with self.assertRaises(AssertionError) as caught:
            self.open(probe)
        self.assertEqual(probe.presses, 3)
        self.assertIn("the reset key opened nothing in 3 presses 10 s apart", str(caught.exception))

    def test_reset_once_waits_for_the_field_first(self):
        source = (ROOT / "scripts" / "multiplayer" / "native_launcher_newcomers_proof.py").read_text()
        self.assertIn("await self.on_field(current[n])      # the key is taken on the free field only", source)


if __name__ == "__main__":
    unittest.main()
