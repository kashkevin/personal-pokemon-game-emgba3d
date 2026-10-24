"""The play check's Linux rehearsal (scripts/windows-runtime/ci_play_check.py LinuxDesk): which X display a game's keys go to.

L rj-1 (2026-10-24): the friend's registration game closed itself while the check held its A key; the key up looked the
display up again from the game's process, which had just ended, and fell back to the first display (the host's). The friend's
A stayed held on its own display and repeated into the friend's menu: it cancelled "Checking graphics", opened "Join with an
invite code" and typed 1,113 characters into the code field."""
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "windows-runtime"))

from ci_play_check import LinuxDesk  # noqa: E402


@unittest.skipUnless(Path("/proc/self/stat").exists(), "reads /proc (Linux)")
class LinuxDeskDisplayTests(unittest.TestCase):
    def test_a_game_keeps_its_players_display_after_it_ends(self):
        import os
        desk = LinuxDesk(None, [":70", ":71"])
        desk.display_of[os.getpid()] = ":71"          # this process stands for the friend's launcher; its child, the game
        game = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            self.assertEqual(desk._display(game.pid), ":71")
        finally:
            game.kill()
            game.wait()
        self.assertEqual(desk._display(game.pid), ":71", "the ended game's keys must still go to the friend's display")
        self.assertEqual(desk._env(game.pid)["DISPLAY"], ":71")

    def test_an_unknown_process_still_falls_back_to_the_first_display(self):
        desk = LinuxDesk(None, [":70", ":71"])
        self.assertEqual(desk._display(2 ** 22 + 12345), ":70")


if __name__ == "__main__":
    unittest.main()
