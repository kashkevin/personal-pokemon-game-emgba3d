"""The Battle Tower launcher proof's battle driver (scripts/multiplayer/native_launcher_tower_proof.py
play_local_battle) against a scripted stand-in for a game. Regression for tower-solo-4 (2026-10-21): on floor 5, the
first floor whose trainer has two Pokemon, the Shift battle style (a new game's default) asks "Will you change
Pokemon?"; the driver's A answered YES and pressed on in the party screen ("already in battle") until the floor timed
out. The question is answered NO (B) as a player keeping the lead in; a party screen opened from the battle is left
with B; anything else in a battle is A. A Windows game loaded away from its preferred base holds moved code pointers,
compared as the build's own (probe.code)."""
from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT / "src", ROOT / "scripts" / "multiplayer", ROOT / "scripts" / "windows-runtime"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
import native_launcher_tower_proof as proof  # noqa: E402

YES_NO, OTHER, OVERWORLD, BATTLE, PARTY = 0x8100000, 0x8180000, 0x8200000, 0x8300000, 0x8400000
SCREENS = {"battle": BATTLE, "party": PARTY, "overworld": OVERWORLD}


class ScriptedGame:
    """Each press moves the game to its next (screen, battle controller) step; reads see the current one."""

    def __init__(self, steps, delta=0):
        self.steps, self.delta, self.pressed = list(steps), delta, []
        self.symbols = {"gMain": (0x1000, 8), "gBattlerControllerFuncs": (0x2000, 16),
                        "sGlobalScriptContextStatus": (0x3000, 1), "sMultiplayerMenuActive": (0x4000, 1),
                        "PlayerHandleYesNoInput": (YES_NO, 4), "CB2_Overworld": (OVERWORLD, 4),
                        "BattleMainCB2": (BATTLE, 4), "CB2_UpdatePartyMenu": (PARTY, 4)}

    def mem(self, name, size=None, offset=0):
        screen, controller = self.steps[0]
        if name == "gMain":                 # callback1, callback2 as the running game holds them (moved by delta)
            return (0).to_bytes(4, "little") + (SCREENS[screen] + self.delta).to_bytes(4, "little")
        if name == "gBattlerControllerFuncs":
            return (controller + self.delta).to_bytes(4, "little")
        if name == "sGlobalScriptContextStatus":
            return b"\x01"
        if name == "sMultiplayerMenuActive":
            return b"\x00"
        raise KeyError(name)

    def code(self, value):
        return value - self.delta if value else value

    def in_choose_action(self):
        return False

    async def press(self, key, frames=12, release=24):
        self.pressed.append(key)
        if len(self.steps) > 1:
            self.steps.pop(0)


def play(game):
    records = []
    asyncio.run(proof.play_local_battle(game, lambda name, **fields: records.append(name), 0, "floor 5", seconds=30))
    return records


class TowerProofDriverTests(unittest.TestCase):
    def test_the_shift_question_is_answered_no(self):
        game = ScriptedGame([("battle", OTHER), ("battle", YES_NO), ("battle", OTHER), ("overworld", OTHER)])
        records = play(game)
        self.assertEqual(game.pressed, [proof.A, proof.B, proof.A])
        self.assertIn("tower-switch-question-declined", records)
        self.assertIn("tower-local-battle-over", records)

    def test_a_party_screen_from_the_battle_is_left(self):
        game = ScriptedGame([("battle", OTHER), ("party", OTHER), ("battle", OTHER), ("overworld", OTHER)])
        records = play(game)
        self.assertEqual(game.pressed, [proof.A, proof.B, proof.A])
        self.assertIn("tower-party-screen-left", records)

    def test_a_windows_game_moved_from_its_base_reads_the_same(self):
        game = ScriptedGame([("battle", YES_NO), ("overworld", OTHER)], delta=0x10000)
        self.assertTrue(proof.battle_question_up(game))
        records = play(game)
        self.assertEqual(game.pressed, [proof.B])
        self.assertIn("tower-switch-question-declined", records)

    def test_no_question_without_the_yes_no_handler(self):
        game = ScriptedGame([("battle", OTHER)])
        self.assertFalse(proof.battle_question_up(game))
        del game.symbols["PlayerHandleYesNoInput"]          # a symbol table without it: never a question
        self.assertFalse(proof.battle_question_up(game))


if __name__ == "__main__":
    unittest.main()
