"""The launcher proofs' way into PLAYERS (scripts/multiplayer/native_launcher_battle_proof.py NativeProbe.open_players)
against a scripted game whose presses can be lost. Regression for the Egg and Mail proofs of 2026-11-05 on a PC at a
load of 30 (other agents' games and builds): the START menu stood open on the player's row and its A came and went
between two of the game's frames, and a cursor press did too; the old steps pressed blind and then waited 15 s for a
menu that never came. Now every A follows a cursor read back from the game and is pressed again only while the same
menu still shows."""
from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT / "src", ROOT / "scripts" / "multiplayer", ROOT / "scripts" / "windows-runtime"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
import native_launcher_battle_proof as harness  # noqa: E402

POKEMON, BAG, SAVE, OPTION, EXIT = 1, 2, 5, 6, 7
TOP = [POKEMON, BAG, harness.PLAYER_OPTIONS, SAVE, OPTION, EXIT]
SUB = [harness.TRAINER_CARD, harness.PLAYERS, 23, 21, 18]
DOWN, A = 128, 1


class LossyGame(harness.NativeProbe):
    """START opens the menu; DOWN moves its cursor; A opens the row under the cursor. The presses listed in `lost`
    (by their order, from 0) never reach the game."""

    def __init__(self, lost=()):
        super().__init__(0, {}, ":0", lambda *a, **k: None)
        self.lost, self.count, self.log = set(lost), 0, []
        self.menu, self.cursor, self.players = None, 0, False

    def read(self):
        actions = self.menu or []
        return dict(frame=0, active=int(self.players), waiting=0, cursor=0, count=len(actions),
                    start_cursor=self.cursor, hold=0, actions=actions + [0] * (16 - len(actions)), screen=b"")

    async def press(self, key, frames=12, release=24):
        index, self.count = self.count, self.count + 1
        self.log.append((key, index in self.lost))
        if index in self.lost:
            return self.read()
        if key == 8:
            self.menu, self.cursor = TOP, 0
        elif key == DOWN and self.menu:
            self.cursor = (self.cursor + 1) % len(self.menu)
        elif key == A and self.menu:
            chosen = self.menu[self.cursor]
            if chosen == harness.PLAYER_OPTIONS:
                self.menu, self.cursor = SUB, 0
            elif chosen == harness.PLAYERS:
                self.menu, self.players = None, True
            else:
                raise AssertionError(f"A opened action {chosen}")
        return self.read()

    async def ready(self, timeout=15):
        class Screen:
            back = False
        return self.read(), Screen()


class OpenPlayersTests(unittest.TestCase):
    def run_it(self, game):
        async def go():
            await game.open_players()
        original = harness.NativeProbe.snapshot

        async def quick(self, predicate=lambda row: True, timeout=15):   # the scripted game answers at once
            return await original(self, predicate, timeout=min(timeout, .3))
        harness.NativeProbe.snapshot = quick
        try:
            asyncio.run(go())
        finally:
            harness.NativeProbe.snapshot = original
        return game

    def test_every_press_taken(self):
        game = self.run_it(LossyGame())
        self.assertTrue(game.players)
        self.assertEqual([key for key, _ in game.log], [8, DOWN, DOWN, A, DOWN, A])

    def test_a_lost_a_on_the_player_row_is_pressed_again(self):
        game = self.run_it(LossyGame(lost={3}))
        self.assertTrue(game.players)
        self.assertEqual(game.log[3:5], [(A, True), (A, False)])

    def test_a_lost_cursor_press_is_made_up_before_any_a(self):
        game = self.run_it(LossyGame(lost={1}))
        self.assertTrue(game.players)
        self.assertEqual([key for key, _ in game.log], [8, DOWN, DOWN, DOWN, A, DOWN, A])

    def test_a_lost_a_on_players_is_pressed_again(self):
        game = self.run_it(LossyGame(lost={5}))
        self.assertTrue(game.players)
        self.assertEqual(game.log[-2:], [(A, True), (A, False)])

    def test_an_a_that_never_lands_fails_naming_the_action(self):
        game = LossyGame(lost=set(range(3, 50)))
        with self.assertRaises(AssertionError) as caught:
            self.run_it(game)
        self.assertIn(f"action {harness.PLAYER_OPTIONS} did not open", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
