"""One launcher at a time on a player's files (launcher_instance.py; KNOWN_ISSUES MS-220): a second launcher - a second click
on the icon - is told the first is open and ends; a lock is never left behind by a launcher that ended, however it ended."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from emerald_multiplayer import launcher_gui, launcher_instance, shell_app
from emerald_multiplayer.launcher_instance import LOCK_NAME, AlreadyOpen, hold_launcher

SRC = Path(__file__).resolve().parents[1] / "src"
# Another launcher process: takes the lock on the folder it is given, says what happened, and with a number of seconds
# keeps it that long.
OTHER = """
import sys, time
sys.path.insert(0, sys.argv[1])
from emerald_multiplayer.launcher_instance import AlreadyOpen, hold_launcher
try:
    lock = hold_launcher(sys.argv[2])
except AlreadyOpen:
    print("already open", flush=True)
    sys.exit(3)
print("held" if lock is not None else "no lock", flush=True)
if lock is not None and len(sys.argv) > 3:
    time.sleep(float(sys.argv[3]))
"""


class LauncherLockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.private = Path(self.temp.name) / "player" / "PokemonPrivate" / "launcher"

    def other_launcher(self, private=None):
        done = subprocess.run([sys.executable, "-c", OTHER, str(SRC), str(private or self.private)], capture_output=True,
                              text=True, timeout=60)
        return done.returncode, done.stdout.strip()

    def hold(self):
        lock = hold_launcher(self.private)
        self.assertIsNotNone(lock)
        self.addCleanup(lock.release)
        return lock

    def test_a_second_launcher_on_the_same_files_is_told_and_ends(self):
        lock = self.hold()
        self.assertTrue(lock.held)
        self.assertTrue((self.private / LOCK_NAME).is_file())
        self.assertEqual(self.other_launcher(), (3, "already open"))
        with self.assertRaises(AlreadyOpen):                # another handle in the same process is refused too
            hold_launcher(self.private)

    def test_the_files_are_free_again_once_the_first_launcher_closes(self):
        self.hold().release()
        self.assertEqual(self.other_launcher(), (0, "held"))
        self.hold()                                         # and again here, the other process having ended

    def test_a_launcher_that_was_ended_leaves_no_lock_behind(self):
        # End task, a crash: the process is gone without closing anything; the operating system lets its lock go.
        holder = subprocess.Popen([sys.executable, "-c", OTHER, str(SRC), str(self.private), "120"], stdout=subprocess.PIPE,
                                  text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), "held")
            with self.assertRaises(AlreadyOpen):
                hold_launcher(self.private)
        finally:
            holder.kill()
            holder.wait(60)
            holder.stdout.close()
        self.assertTrue((self.private / LOCK_NAME).is_file())   # the file stays; it is the lock on it that went
        self.assertTrue(self.hold().held)

    def test_another_players_files_have_a_lock_of_their_own(self):
        self.hold()
        friend = Path(self.temp.name) / "friend" / "PokemonPrivate" / "launcher"
        self.assertEqual(self.other_launcher(friend), (0, "held"))

    def test_a_lock_file_that_cannot_be_used_starts_the_launcher_as_before(self):
        (self.private / LOCK_NAME).mkdir(parents=True)      # a folder where the file should be
        self.assertIsNone(hold_launcher(self.private))

    def test_the_packaged_entry_ends_at_once_when_another_launcher_has_the_files(self):
        self.hold()
        told = []
        with mock.patch.object(launcher_gui, "private_directory", return_value=self.private), \
                mock.patch.object(launcher_instance, "tell_already_open", lambda: told.append(True)), \
                mock.patch.object(shell_app, "_main", side_effect=AssertionError("a second menu opened")), \
                mock.patch.object(sys, "argv", ["EmeraldTogether.exe"]):
            self.assertIsNone(shell_app.main(object(), Path("."), None))
        self.assertEqual(told, [True])

    def test_the_packaged_entry_holds_the_files_while_its_menu_runs_and_lets_them_go_after(self):
        seen = []

        def menu(release, application_directory, import_release):
            try:
                hold_launcher(self.private)
            except AlreadyOpen:
                seen.append("held while the menu runs")
            return "closed"
        with mock.patch.object(launcher_gui, "private_directory", return_value=self.private), \
                mock.patch.object(shell_app, "_main", menu), mock.patch.object(sys, "argv", ["EmeraldTogether.exe"]):
            self.assertEqual(shell_app.main(object(), Path("."), None), "closed")
        self.assertEqual(seen, ["held while the menu runs"])
        self.assertTrue(self.hold().held)                   # let go when the menu ended

    def test_without_a_private_folder_the_entry_starts_as_before(self):
        with mock.patch.object(launcher_gui, "private_directory", side_effect=ValueError("private_storage")), \
                mock.patch.object(shell_app, "_main", return_value="menu"), mock.patch.object(sys, "argv", ["x"]):
            self.assertEqual(shell_app.main(object(), Path("."), None), "menu")

    def test_the_message_says_the_launcher_is_open(self):
        with mock.patch.object(launcher_instance.sys, "stderr") as stderr, mock.patch.object(launcher_instance.os, "name", "posix"):
            launcher_instance.tell_already_open()
        written = "".join(call.args[0] for call in stderr.write.call_args_list)
        self.assertIn("already open", written)


if __name__ == "__main__":
    unittest.main()
