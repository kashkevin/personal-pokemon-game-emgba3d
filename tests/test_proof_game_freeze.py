"""The proofs' --freeze game (scripts/multiplayer/native_launcher_newcomers_proof.py; KNOWN_ISSUES MS-165): a player's game
process stopped for a while, then run on, as a PC that does not run the game for a moment. It refused Windows before
2026-11-06 (SIGSTOP and SIGCONT are POSIX only); on Windows it now suspends and resumes the process with ntdll's
NtSuspendProcess and NtResumeProcess (the windows-package job multiplayer-check's game-freeze entry). Here: which call
each platform makes (the Windows calls stood in), a real process stopped and run on (Linux), and the option no longer
refused on Windows while --sample-every (which reads /proc) still is."""
from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT / "src", ROOT / "scripts" / "multiplayer", ROOT / "scripts" / "windows-runtime"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
import native_launcher_newcomers_proof as newcomers  # noqa: E402


class GameFreezeTests(unittest.TestCase):
    def test_posix_stops_and_continues_with_signals(self):
        with mock.patch.object(newcomers, "WINDOWS", False), mock.patch.object(newcomers.os, "kill") as kill:
            newcomers.stop_process(4242)
            newcomers.continue_process(4242)
        self.assertEqual(kill.call_args_list, [mock.call(4242, signal.SIGSTOP), mock.call(4242, signal.SIGCONT)])

    def test_windows_suspends_and_resumes_the_process(self):
        with mock.patch.object(newcomers, "WINDOWS", True), mock.patch.object(newcomers, "_nt_process") as nt, \
                mock.patch.object(newcomers.os, "kill") as kill:
            newcomers.stop_process(4242)
            newcomers.continue_process(4242)
        self.assertEqual(nt.call_args_list, [mock.call(4242, "NtSuspendProcess"), mock.call(4242, "NtResumeProcess")])
        kill.assert_not_called()

    @unittest.skipIf(sys.platform == "win32", "the POSIX path")
    def test_a_real_process_is_stopped_then_runs_on(self):
        child = subprocess.Popen([sys.executable, "-c", "import time\nwhile True: time.sleep(0.05)"])
        try:
            newcomers.stop_process(child.pid)
            time.sleep(0.2)
            state = Path(f"/proc/{child.pid}/stat").read_text().split(") ")[1].split()[0] if Path("/proc").exists() else "T"
            self.assertEqual(state, "T")                          # stopped
            newcomers.continue_process(child.pid)
            time.sleep(0.2)
            if Path("/proc").exists():
                state = Path(f"/proc/{child.pid}/stat").read_text().split(") ")[1].split()[0]
                self.assertNotEqual(state, "T")                   # running (or sleeping) again
            self.assertIsNone(child.poll())
        finally:
            child.kill()
            child.wait()

    def test_freeze_is_no_longer_refused_on_windows_but_sample_every_is(self):
        source = (ROOT / "scripts" / "multiplayer" / "native_launcher_newcomers_proof.py").read_text()
        self.assertNotIn("--freeze and --sample-every: Linux games only", source)
        self.assertIn('require(not args.sample_every or not WINDOWS, "--sample-every: Linux games only (it reads /proc)")',
                      source)
        self.assertIn("stop_process(pid)", source)
        self.assertIn("continue_process(pid)", source)
        self.assertNotIn("signal.SIGSTOP)\n            try:", source)


if __name__ == "__main__":
    unittest.main()
