"""The trade proofs' choice of a row (scripts/multiplayer/native_launcher_challenge_proof.py pick) against a scripted
Players menu. Regression for the Mail trade proof of 2026-11-05 on a PC at a load of 30 (mail-freeze-worker30): right
after "Choose your Pokemon" the friend's pick read the screen the game had not replaced yet, chose "Choose your
Pokemon" again, and no Pokemon was ever offered (the trade waited until the proof's time limit). A labelled pick now
waits for a screen that offers its label, and presses the previous choice again only while it is still shown under the
cursor ten seconds on."""
from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT / "src", ROOT / "scripts" / "multiplayer", ROOT / "scripts" / "windows-runtime"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
import native_launcher_challenge_proof as challenge  # noqa: E402

PENDING = ["Choose your Pokemon", "Cancel trade..."]
PARTY = ["Wingull Lv20", "Treecko Lv20", "Back"]


class Menu:
    """The friend's Players menu: `stale` reads of the old screen after an A that the game takes, every A on the old
    screen in `lost` (by order) never taken."""

    def __init__(self, stale=0, lost=()):
        self.screen, self.cursor, self.stale, self.lost, self.presses = PENDING, 0, 0, set(lost), []
        self.pending_stale = stale

    def view(self):
        if self.stale:
            self.stale -= 1
            return PENDING
        return self.screen

    async def shown(self, probe, timeout=60):
        rows = [types.SimpleNamespace(label=label, action=True) for label in self.view()]
        return dict(cursor=self.cursor), types.SimpleNamespace(rows=rows)

    async def press(self, key):
        index = len(self.presses)
        self.presses.append((key, self.screen[self.cursor] if self.cursor < len(self.screen) else None))
        if key == 128:
            self.cursor = (self.cursor + 1) % len(self.screen)
        elif key == 1 and self.screen is PENDING and index not in self.lost:
            self.screen, self.cursor, self.stale = PARTY, 0, self.pending_stale


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        self.now += 1.0           # a second a look: the ten-second retry comes after ten looks
        return self.now


class PickTests(unittest.TestCase):
    def run_pick(self, menu, label, **options):
        original_shown, original_time = challenge.shown, challenge.time
        challenge.shown, challenge.time = menu.shown, Clock()
        original_sleep = asyncio.sleep

        async def no_wait(seconds):
            await original_sleep(0)
        challenge.asyncio = types.SimpleNamespace(sleep=no_wait)
        try:
            return asyncio.run(challenge.pick(menu, label, **options))
        finally:
            challenge.shown, challenge.time, challenge.asyncio = original_shown, original_time, asyncio

    def test_a_label_is_waited_for_while_the_old_screen_still_shows(self):
        menu = Menu(stale=3)
        menu.screen = PENDING
        asyncio.run(menu.press(1))                           # "Choose your Pokemon", taken; the screen lags behind
        self.assertEqual(self.run_pick(menu, "Treecko Lv20", again="Choose your Pokemon"), "Treecko Lv20")
        self.assertEqual(menu.presses[1:], [(128, "Wingull Lv20"), (1, "Treecko Lv20")])

    def test_a_lost_press_on_the_previous_choice_is_pressed_again(self):
        menu = Menu(lost={0})
        asyncio.run(menu.press(1))                           # lost: the screen stays
        self.assertEqual(self.run_pick(menu, "Wingull Lv20", again="Choose your Pokemon"), "Wingull Lv20")
        self.assertEqual(menu.presses, [(1, "Choose your Pokemon"), (1, "Choose your Pokemon"), (1, "Wingull Lv20")])

    def test_without_a_label_the_first_row_is_chosen_at_once(self):
        menu = Menu()
        self.assertEqual(self.run_pick(menu, None), "Choose your Pokemon")

    def test_a_label_that_never_comes_fails_naming_it(self):
        menu = Menu()
        with self.assertRaises(AssertionError) as caught:
            self.run_pick(menu, "Mudkip Lv5", timeout=5)
        self.assertIn("no choice 'Mudkip Lv5'", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
