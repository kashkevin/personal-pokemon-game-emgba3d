"""The co-op battle proofs' wait for the game's experience award (scripts/multiplayer/native_launcher_coop_proof.py
award_done) against scripted memory. Regression for tower-duo-2 (2026-10-22): a Tower Duo of level-100 parties wins
and nobody gains experience, so the award (multiplayer_coop.c MultiplayerCoop_ExpBegin) ends at its first stage and
never reaches its last; the proof waited for that last stage until it gave up. Nothing to award counts as done once the
battle's experience is consumed; an award still to come or under way does not."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT / "src", ROOT / "scripts" / "multiplayer", ROOT / "scripts" / "windows-runtime"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
import native_launcher_coop_proof as coop  # noqa: E402

GAINED, TEAM, DONE = coop.COOP_EXP_STAGE_GAINED, 1, coop.COOP_EXP_STAGE_DONE


class Memory:
    """sCoopAward (stage, slot, level, firstMove, participants, sharers, leveled, tried) and sCoopExp (tracking,
    pending) as the game holds them."""

    def __init__(self, stage, *, pending=False, participants=0, sharers=0, leveled=0):
        self.award = bytes([stage, 0, 0, 0, participants, sharers, leveled, 0])
        self.exp = bytes([0, int(pending)])

    def mem(self, name, size=None, offset=0):
        data = {"sCoopAward": self.award, "sCoopExp": self.exp}[name]
        return data[offset:offset + size] if size is not None else data


class CoopAwardWaitTests(unittest.TestCase):
    def test_the_last_stage_is_done(self):
        self.assertTrue(coop.award_done(Memory(DONE)))

    def test_nothing_to_award_is_done(self):
        # level-100 parties: the result script consumed the experience and nobody gained any
        self.assertTrue(coop.award_done(Memory(GAINED)))

    def test_an_award_still_to_come_is_not_done(self):
        self.assertFalse(coop.award_done(Memory(GAINED, pending=True)))

    def test_an_award_under_way_is_not_done(self):
        self.assertFalse(coop.award_done(Memory(GAINED, participants=0b1)))
        self.assertFalse(coop.award_done(Memory(GAINED, sharers=0b10)))
        self.assertFalse(coop.award_done(Memory(GAINED, leveled=0b100)))
        self.assertFalse(coop.award_done(Memory(TEAM, participants=0b1)))


if __name__ == "__main__":
    unittest.main()
