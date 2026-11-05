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


class _Desk:
    """A desk whose processes and windows are a table: {pid: (parent, command, window or None, alive)}."""

    def __init__(self, table):
        self.table = table

    def children(self, pid):
        return [(child, row[1]) for child, row in self.table.items() if row[0] == pid]

    def window(self, pid):
        row = self.table.get(pid)
        return row[2] if row and row[3] else None

    def alive(self, pid):
        row = self.table.get(pid)
        return bool(row and row[3])


class PlayerGameTests(unittest.TestCase):
    """Player.game(): which of the launcher's processes is the game the menu just started (run 262's installation check: the
    friend's game ran and connected, and no window was found for it in 90 s)."""

    LAUNCHER, MENU = 100, 101

    def player(self, table, games):
        import ci_play_check
        from types import SimpleNamespace
        player = ci_play_check.Player.__new__(ci_play_check.Player)
        player.desk, player.name, player.games = _Desk(table), "friend", list(games)
        player.process, player.shell_pid = SimpleNamespace(pid=self.LAUNCHER), self.MENU
        player.screen_log = Path("/nonexistent/friend-screens.jsonl")      # no screens: current() is None
        return player

    def base(self):
        return {self.MENU: (self.LAUNCHER, "EmeraldTogether.exe --shell", "menu-window", True),
                150: (self.LAUNCHER, "pokeemerald-mp-diorama.exe --probe-graphics", None, False)}

    def test_a_new_game_with_an_ended_games_number_is_found(self):
        # Windows gives a new process the number of one that has ended: the friend's earlier game 200 (window w-old) ended,
        # and the new game has the number 200 with its own window.
        table = self.base()
        table[200] = (self.LAUNCHER, "pokeemerald-mp.exe --save new.sav", "w-new", True)
        player = self.player(table, [(200, "w-old")])
        self.assertEqual(player.game(seconds=0), (200, "w-new"))
        self.assertEqual(player.games, [(200, "w-old"), (200, "w-new")])

    def test_an_earlier_game_still_running_with_its_window_is_passed_over(self):
        table = self.base()
        table[200] = (self.LAUNCHER, "pokeemerald-mp.exe --save old.sav", "w-old", True)    # still closing
        table[300] = (self.LAUNCHER, "pokeemerald-mp.exe --save new.sav", "w-new", True)
        self.assertEqual(self.player(table, [(200, "w-old")]).game(seconds=0), (300, "w-new"))

    def test_the_menu_and_the_graphics_check_are_never_the_game(self):
        table = self.base()
        table[150] = (self.LAUNCHER, "pokeemerald-mp-diorama.exe --probe-graphics", "probe-window", True)
        import ci_play_check
        with self.assertRaises(ci_play_check.CheckFailed):
            self.player(table, []).game(seconds=0)

    def test_no_window_names_the_launchers_processes(self):
        table = self.base()
        table[300] = (self.LAUNCHER, "pokeemerald-mp.exe --save new.sav", None, True)      # started, no window yet
        import ci_play_check
        with self.assertRaises(ci_play_check.CheckFailed) as failure:
            self.player(table, [(200, "w-old")]).game(seconds=0)
        message = str(failure.exception)
        self.assertIn("friend: no game window opened (last screen None)", message)
        self.assertIn(f"{self.MENU} (the menu, a window)", message)
        self.assertIn("300 (new, no window): ...pokeemerald-mp.exe --save new.sav", message)
        self.assertIn("150 (new, no window)", message)

    def test_no_child_at_all_says_so(self):
        import ci_play_check
        with self.assertRaises(ci_play_check.CheckFailed) as failure:
            self.player({}, []).game(seconds=0)
        self.assertIn("the launcher's processes: none found", str(failure.exception))


class GraphicsChoiceTests(unittest.TestCase):
    """Player.graphics_choice() after a start: windows-package run 331's update check started the hosted world after the update;
    the launcher showed "Getting the world ready" (the world prepared for this version, a backup first), then "Checking
    graphics", then the 3D question. The check took the first busy screen for a start past the graphics check, waited for a
    game window that the unanswered question held back, and failed ("no game window opened (last screen graphics)")."""

    def player(self, shown):
        import ci_play_check
        from types import SimpleNamespace
        player = ci_play_check.Player.__new__(ci_play_check.Player)
        player.name, player.mark, player.chosen = "host", 0, []
        player.check = SimpleNamespace(report={}, log=lambda text: None)
        calls = {"n": 0}

        def screens():                       # one more screen of the start shown each time the window is read
            calls["n"] += 1
            return shown[:min(len(shown), calls["n"])]
        player.screens = screens
        player.choose = lambda screen, item: player.chosen.append((screen["id"], item))
        return player

    @staticmethod
    def busy(title):
        return {"id": "busy", "title": title, "status": None, "notes": [], "items": []}

    def test_the_3d_question_after_a_prepared_world_is_answered(self):
        question = {"id": "graphics", "title": "3D graphics cannot start", "status": None,
                    "notes": ["Your graphics driver is missing OpenGL features the 3D mode needs."],
                    "items": [["b", "classic", "Play in Classic 2D this time", ""]]}
        player = self.player([self.busy("Getting the world ready"), self.busy("Checking graphics"), question])
        self.assertEqual(player.graphics_choice(seconds=20), "2d")
        self.assertEqual(player.chosen, [("graphics", "classic")])

    def test_a_start_past_the_graphics_check_needs_no_answer(self):
        player = self.player([self.busy("Getting the world ready"), self.busy("Checking graphics"),
                              self.busy("Starting the game")])
        self.assertIsNone(player.graphics_choice(seconds=20))
        self.assertEqual(player.chosen, [])


if __name__ == "__main__":
    unittest.main()
