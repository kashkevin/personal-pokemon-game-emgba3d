"""MS-126: the launcher battle proof's forfeit (native_launcher_battle_proof.py --forfeit): the forfeiting player's
driver presses only the keys to Run on the action menu (never A on Fight), and the probe finds which battler waits on
that menu (a link battle's own player is battler 0 on the master's game, battler 1 on the other's)."""
from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT / "src", ROOT / "scripts" / "multiplayer", ROOT / "scripts" / "windows-runtime"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
import native_launcher_battle_proof as proof  # noqa: E402

SYMBOLS = {"Task_HandleChooseMonInput": (0x08001001, 4), "Task_HandleSelectionMenuInput": (0x08002000, 4),
           "Task_PrintAndWaitForText": (0x08003001, 4)}
CHOOSE = 0x0804_2000


class MenuProbe:
    """A game at its battle: the action menu comes up after `menu_after` reads; each key moves the cursor as the
    game's two-by-two menu does (Fight 0, Bag 1, Pokemon 2, Run 3)."""

    def __init__(self, battler, cursor=0, menu_after=2):
        self.battler, self.cursor, self.menu_after, self.keys = battler, cursor, menu_after, []

    async def battle(self):
        return dict(state=5, active=frozenset(), cursor=0, count=1)

    def choosing_action(self):
        self.menu_after -= 1
        return self.battler if self.menu_after < 0 else None

    def mem(self, name, size=None, offset=0):
        assert (name, size, offset) == ("gActionSelectionCursor", 1, self.battler)
        return bytes([self.cursor])

    async def press(self, key, frames=None, release=None):
        self.keys.append(key)
        moves = {(0, 16): 1, (1, 32): 0, (2, 16): 3, (3, 32): 2, (0, 128): 2, (2, 64): 0, (1, 128): 3, (3, 64): 1}
        self.cursor = moves.get((self.cursor, key), self.cursor)


def views(*rooms):
    values = iter(rooms)

    async def view():
        return next(values)
    return view


class ForfeitDriverTests(unittest.IsolatedAsyncioTestCase):
    async def drive(self, probe, rooms):
        forfeit = {}
        await asyncio.wait_for(proof.drive_battle_input(probe, views(*rooms), SYMBOLS, asyncio.Event(),
                                                        forfeit=forfeit), 1)
        return forfeit

    async def test_run_from_fight_is_right_down_then_a(self):
        probe = MenuProbe(battler=1)
        forfeit = await self.drive(probe, [dict(state="executing", pending=17)] * 5 + [dict(state="closed", pending=None)])
        self.assertEqual(probe.keys, [16, 128, 1])          # nothing while the menu was not up, then RIGHT, DOWN, A
        self.assertEqual(forfeit["battler"], 1)
        self.assertIn("chosen", forfeit)

    async def test_run_from_pokemon_is_right_then_a(self):
        probe = MenuProbe(battler=0, cursor=2, menu_after=0)
        forfeit = await self.drive(probe, [dict(state="executing", pending=17)] * 2 + [dict(state="closed", pending=None)])
        self.assertEqual(probe.keys, [16, 1])
        self.assertEqual(forfeit["battler"], 0)

    async def test_after_run_the_ordinary_policy_takes_over(self):
        # Once Run is chosen, a later request is answered by the ordinary policy (A to confirm a message).
        probe = MenuProbe(battler=1, cursor=3, menu_after=0)
        forfeit = await self.drive(probe, [dict(state="executing", pending=17), dict(state="executing", pending=15),
                                           dict(state="closed", pending=None)])
        self.assertEqual(probe.keys, [1, 1])
        self.assertIn("chosen", forfeit)

    async def test_another_request_is_not_answered_with_run_keys(self):
        # A message (not the action choice) before the first action menu: the ordinary A, no menu keys.
        probe = MenuProbe(battler=1, menu_after=0)
        forfeit = await self.drive(probe, [dict(state="executing", pending=16), dict(state="closed", pending=None)])
        self.assertEqual(probe.keys, [1])
        self.assertEqual(forfeit, {})


class StandbyProbe:
    """A game whose player waits on the other ("Link standby..."): B asks the question (sForfeitAsking 1: printing,
    then 2: the Yes/No box), UP moves to Yes, A answers."""

    def __init__(self, question=True):
        self.question, self.asking, self.cursor, self.keys = question, 0, 1, []

    async def battle(self):
        return dict(state=5, active=frozenset(), cursor=0, count=1)

    def mem(self, name, size=None, offset=0):
        assert name == "sForfeitAsking"
        value = self.asking
        if self.asking == 1:
            self.asking = 2          # the question has printed: the box is up at the next read
        return bytes([value])

    async def press(self, key, frames=None, release=None):
        self.keys.append(key)
        if key == 2 and self.asking == 0 and self.question:
            self.asking = 1
        elif key == 64 and self.asking == 2:
            self.cursor = 0
        elif key == 1 and self.asking == 2:
            self.asking = 0


class GiveUpWhileWaitingTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_move_then_b_up_a_on_the_waiting_screen(self):
        probe = StandbyProbe()
        own = views(*[dict(state="executing", pending=p) for p in (17, 19, None)]
                    + [dict(state="executing", pending=None), dict(state="closed", pending=None)])
        give_up = dict(wait_for=17)
        await asyncio.wait_for(proof.drive_battle_input(probe, own, SYMBOLS, asyncio.Event(), give_up=give_up,
                                                        other_view=views(*[dict(state="executing", pending=17)] * 3)), 2)
        self.assertEqual(probe.keys, [1, 1, 2, 64, 1, 1])     # Fight, a move, then B, UP, A; then A for a message
        self.assertIn("chosen", give_up)
        self.assertEqual(give_up["other_pending"], 17)

    async def test_no_question_yet_means_b_again_later_and_nothing_else(self):
        probe = StandbyProbe(question=False)
        own = views(*[dict(state="executing", pending=p) for p in (19, None, None)] + [dict(state="closed", pending=None)])
        give_up = dict(wait_for=17)
        await asyncio.wait_for(proof.drive_battle_input(probe, own, SYMBOLS, asyncio.Event(), give_up=give_up,
                                                        other_view=views(*[dict(state="executing", pending=17)] * 3)), 3)
        self.assertEqual(probe.keys, [1, 2, 2])                 # never UP or A without the question
        self.assertNotIn("chosen", give_up)
        self.assertEqual(give_up["b_without_question"], 2)


class ChoosingActionTests(unittest.TestCase):
    def probe(self, funcs):
        native = proof.NativeProbe.__new__(proof.NativeProbe)
        native.symbols = {"gBattlerControllerFuncs": (0x0900_0000, 16)}
        native.choose_action = frozenset({CHOOSE})
        native.mem = lambda name, size=None, offset=0: b"".join(f.to_bytes(4, "little") for f in funcs)
        return native

    def test_the_battler_on_the_action_menu(self):
        self.assertEqual(self.probe([0x0805_0000, CHOOSE | 1, 0, 0]).choosing_action(), 1)
        self.assertEqual(self.probe([CHOOSE, 0x0805_0000, 0, 0]).choosing_action(), 0)

    def test_no_battler_on_the_action_menu(self):
        self.assertIsNone(self.probe([0x0805_0000, 0x0805_0004, 0, 0]).choosing_action())


if __name__ == "__main__":
    unittest.main()
