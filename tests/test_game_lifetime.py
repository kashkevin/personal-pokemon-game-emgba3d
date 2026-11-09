"""A game ends with the launcher that started it, however the launcher ends (KNOWN_ISSUES MS-221).

Real processes: a stand-in launcher (a Python process) starts a stand-in game (another, sleeping) the way the launcher
starts its games, and is then ended outright - SIGKILL on Linux, TerminateProcess on Windows, as a crash or Task
Manager's End task ends it: no code of its own runs. The game must end too. Without the module the game outlives it
(the fault, shown by the same test's control).
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from emerald_multiplayer import game_lifetime  # noqa: E402

SUPPORTED = sys.platform.startswith("linux") or os.name == "nt"

# The stand-in launcher: starts the game (bound or not), says its number, then waits to be ended.
LAUNCHER = textwrap.dedent("""
    import subprocess, sys, threading, time
    sys.path.insert(0, sys.argv[1])
    from emerald_multiplayer import game_lifetime
    bound, where = sys.argv[2] == "bound", sys.argv[3]
    def start():
        options = game_lifetime.spawn_options() if bound else {}
        game = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], **options)
        joined = game_lifetime.bind(game.pid) if bound else False
        print(game.pid, joined, flush=True)
        if where == "thread":
            time.sleep(120)          # the session's thread waits for its game, as the launcher's does
    if where == "thread":
        threading.Thread(target=start, daemon=True).start()
    else:
        start()
    time.sleep(120)
""")


def alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(0x1000, False, pid)      # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return code.value == 259                             # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except (OSError, IndexError):
        return False
    return state not in ("Z", "X")          # a zombie, or dead while its parent reaps it


def end_outright(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, check=False)
    else:
        import signal
        os.kill(pid, signal.SIGKILL)


@unittest.skipUnless(SUPPORTED, "Windows (the job object) and Linux (PR_SET_PDEATHSIG) only")
class GameEndsWithItsLauncherTests(unittest.TestCase):
    def start_launcher(self, mode, where="main"):
        launcher = subprocess.Popen([sys.executable, "-c", LAUNCHER, str(ROOT / "src"), mode, where],
                                    stdout=subprocess.PIPE, text=True)
        self.addCleanup(self._stop, launcher)
        line = launcher.stdout.readline().split()
        self.assertEqual(len(line), 2, f"the stand-in launcher said {line!r}")
        game, joined = int(line[0]), line[1] == "True"
        self.addCleanup(self._stop_pid, game)
        return launcher, game, joined

    @staticmethod
    def _stop(process):
        if process.poll() is None:
            process.kill()
        process.wait(30)
        process.stdout.close()

    @staticmethod
    def _stop_pid(pid):
        if alive(pid):
            try:
                end_outright(pid)
            except ProcessLookupError:
                pass                        # it ended between the look and the kill: what the cleanup wants

    @staticmethod
    def wait_until_ended(pid, seconds=15.0):
        deadline = time.monotonic() + seconds
        while alive(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        return not alive(pid)

    def test_a_bound_game_ends_when_its_launcher_is_ended_outright(self):
        launcher, game, joined = self.start_launcher("bound")
        self.assertEqual(joined, os.name == "nt", "Windows joins the game to the job; Linux asks at the spawn")
        time.sleep(0.5)
        self.assertTrue(alive(game), "the game runs while its launcher runs")
        end_outright(launcher.pid)
        launcher.wait(30)
        self.assertTrue(self.wait_until_ended(game), "the game outlived its launcher")

    def test_a_game_started_from_a_session_thread_ends_with_the_launcher(self):
        # The launcher starts each game from the thread of the session that waits for it (Linux: the death signal
        # follows the thread that started the game).
        launcher, game, _ = self.start_launcher("bound", "thread")
        time.sleep(0.5)
        self.assertTrue(alive(game), "the game runs while its session's thread waits for it")
        end_outright(launcher.pid)
        launcher.wait(30)
        self.assertTrue(self.wait_until_ended(game), "the game outlived its launcher")

    def test_without_it_the_game_outlives_its_launcher(self):
        # The fault (KNOWN_ISSUES MS-221), and the proof the test above can tell.
        launcher, game, joined = self.start_launcher("unbound")
        self.assertFalse(joined)
        end_outright(launcher.pid)
        launcher.wait(30)
        time.sleep(1.0)
        self.assertTrue(alive(game), "an unbound game ended with its launcher: the check cannot tell the fix")

    def test_a_game_that_ends_first_leaves_the_launcher_running(self):
        launcher, game, _ = self.start_launcher("bound")
        end_outright(game)
        self.assertTrue(self.wait_until_ended(game))
        time.sleep(0.5)
        self.assertIsNone(launcher.poll(), "the launcher ended with its game")


class SpawnOptionsTests(unittest.TestCase):
    def test_linux_asks_at_the_spawn_and_windows_binds_after_it(self):
        options = game_lifetime.spawn_options()
        if sys.platform.startswith("linux"):
            self.assertEqual(set(options), {"preexec_fn"})
            self.assertTrue(callable(options["preexec_fn"]))
        else:
            self.assertEqual(options, {})

    def test_bind_refuses_what_is_not_a_process_number(self):
        for value in (0, -1, None, "12"):
            self.assertFalse(game_lifetime.bind(value))

    @unittest.skipIf(os.name == "nt", "elsewhere than Windows")
    def test_bind_does_nothing_elsewhere_than_windows(self):
        self.assertFalse(game_lifetime.bind(os.getpid()))


if __name__ == "__main__":
    unittest.main()
