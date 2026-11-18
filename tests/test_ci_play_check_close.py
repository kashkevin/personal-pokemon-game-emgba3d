"""The play check's watch of a normal close (scripts/windows-runtime/ci_play_check.py, KNOWN_ISSUES MS-259).

At a normal close right after a save the menu showed "This save needs recovery..." or "Connection to the host was
lost..." for a moment before "Game closed" (fixed in the app, 707a651). The installation check closes games right after
a save; it now reads every status the menu showed from its screen log, records each close in the report, and fails on
a false warning unless it was told to record only (an installer from before the fix, to compare)."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "windows-runtime"))

import ci_play_check  # noqa: E402

SAVED = ["ok", "Character saved to the host. Your world is running and your game is connected to it."]
RECOVERY = ["error", "This save needs recovery. Close the game and reopen through Host Game or Join Game."]
LOST = ["error", "Connection to the host was lost. Keep the game open while its save or battle recovery status is checked."]
CLOSED = ["ok", "Game closed. Your character is saved (as of your last save)."]


def screen(screen_id, status):
    return dict(id=screen_id, title="", status=status, notes=[], items=[])


class _Desk:
    """The game's window: closing it appends what the menu logs as the game closes."""

    def __init__(self, player, on_close):
        self.player, self.on_close, self.running = player, on_close, True

    def close_game(self, pid, window):
        self.running = False
        self.player.shown.extend(self.on_close)

    def alive(self, pid):
        return self.running


class _Player:
    def __init__(self, name, before, on_close):
        self.name, self.shown, self.logged = name, list(before), []
        self.desk = _Desk(self, on_close)

    def screens(self):
        return list(self.shown)

    def current(self):
        return self.shown[-1] if self.shown else None

    def log(self, text):
        self.logged.append(text)


class CloseWatchTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.report, self.lines = {}, []
        self.check = ci_play_check.PlayCheck(None, Path(self.folder.name), "test", self.report, self.lines)
        patcher = mock.patch.object(ci_play_check.time, "sleep", lambda seconds: None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.printed = mock.patch("builtins.print", lambda *a, **k: None)
        self.printed.start()
        self.addCleanup(self.printed.stop)

    def close(self, on_close, *, normal=True, before=(screen("session", SAVED),)):
        player = _Player("friend", before, on_close)
        self.check.close(player, (1234, "window"), normal=normal)
        return player

    def test_a_clean_close_is_recorded_and_passes(self):
        player = self.close([screen("session", SAVED), screen("join_list", CLOSED)])
        self.assertEqual(self.report["closes"], [dict(player="friend", strict=True, alarms=[],
                                                      statuses=[["session", SAVED[1]], ["join_list", CLOSED[1]]])])
        self.assertIn("as the game closed the menu showed: " + SAVED[1], player.logged[-1])
        self.check.close_summary()                   # does not raise
        self.assertIn("normal closes watched: 1; failing with a false warning: 0", self.lines[-1])

    def test_a_recovery_warning_for_a_moment_fails_the_check(self):
        # the audit's dfh-fix-1 and launcher_real_checks' old-1: the warning between the save and "Game closed"
        self.close([screen("session", RECOVERY), screen("join_list", CLOSED)])
        self.assertEqual(self.report["closes"][0]["alarms"], [["session", RECOVERY[1]]])
        with self.assertRaises(ci_play_check.CheckFailed) as failed:
            self.check.close_summary()
        self.assertIn("MS-259", str(failed.exception))
        self.assertIn("This save needs recovery", str(failed.exception))

    def test_connection_lost_at_a_normal_close_fails_too(self):
        self.close([screen("session", LOST), screen("session", RECOVERY), screen("main", CLOSED)])
        self.assertEqual([row[1] for row in self.report["closes"][0]["alarms"]], [LOST[1], RECOVERY[1]])
        with self.assertRaises(ci_play_check.CheckFailed):
            self.check.close_summary()

    def test_an_installer_from_before_the_fix_is_recorded_not_failed(self):
        self.check.strict_close = False
        player = self.close([screen("session", RECOVERY), screen("join_list", CLOSED)])
        self.assertIn("recorded, not failed", player.logged[-1])
        self.check.strict_close = True               # the updated build's closes after it
        self.close([screen("session", SAVED), screen("join_list", CLOSED)])
        self.check.close_summary()                   # does not raise: the false warning was the earlier build's
        self.assertEqual([c["strict"] for c in self.report["closes"]], [False, True])
        self.assertIn("recorded only (an installer from before the fix): 1 of 1 with one", self.lines[-1])

    def test_a_friends_game_after_its_host_left_is_not_watched(self):
        # host_leaves: the friend's warnings then are real ones
        self.close([screen("session", LOST), screen("join_list", CLOSED)], normal=False)
        self.assertNotIn("closes", self.report)
        self.check.close_summary()

    def test_only_the_screens_after_the_close_count(self):
        # a warning shown before this close (another step's) is not this close's
        before = (screen("session", RECOVERY), screen("session", SAVED))
        self.close([screen("join_list", CLOSED)], before=before)
        self.assertEqual(self.report["closes"][0]["alarms"], [])


if __name__ == "__main__":
    unittest.main()
