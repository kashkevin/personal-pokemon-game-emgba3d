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

    def test_a_new_process_with_a_kept_number_is_looked_up_again(self):
        # Process numbers come round again: a kept display whose start time is not the running process's is not used.
        import os
        desk = LinuxDesk(None, [":70", ":71"])
        desk.display_of[os.getpid()] = ":71"
        game = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            desk.found[game.pid] = (":70", "an earlier process's start time")
            self.assertEqual(desk._display(game.pid), ":71")
            self.assertEqual(desk.found[game.pid][0], ":71")
        finally:
            game.kill()
            game.wait()

    def test_an_unknown_process_still_falls_back_to_the_first_display(self):
        desk = LinuxDesk(None, [":70", ":71"])
        self.assertEqual(desk._display(2 ** 22 + 12345), ":70")

    def test_looking_up_the_hosts_menu_does_not_use_up_the_friends_display(self):
        # launch() hands the displays out in launch order; a kept lookup of the host's menu between the two launches
        # must not count as a player (L rj-2, a first try of the change above: IndexError for the friend's display).
        import os
        from types import SimpleNamespace
        from unittest import mock
        import ci_play_check
        desk = LinuxDesk(Path("app"), [":70", ":71"])
        menu = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])   # the host's menu window
        launched = iter([SimpleNamespace(pid=os.getpid()), SimpleNamespace(pid=os.getpid() + 1)])
        try:
            with mock.patch.object(ci_play_check.subprocess, "Popen", lambda *a, **k: next(launched)):
                host = desk.launch(Path("host"), Path("host.jsonl"))       # this process stands for the host's launcher
                self.assertEqual(desk._display(menu.pid), ":70")
                friend = desk.launch(Path("friend"), Path("friend.jsonl"))
        finally:
            menu.kill()
            menu.wait()
        self.assertEqual((desk.display_of[host.pid], desk.display_of[friend.pid]), (":70", ":71"))


if __name__ == "__main__":
    unittest.main()
