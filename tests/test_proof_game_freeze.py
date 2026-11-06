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

    def test_freeze_at_peek_stops_the_game_while_its_launcher_has_a_peek_out(self):
        # KNOWN_ISSUES MS-165's update of 2026-11-06 (Windows run 349): the window where the game stops with its launcher's
        # battle observer waiting on a PEEK, no host command held
        source = (ROOT / "scripts" / "multiplayer" / "native_launcher_newcomers_proof.py").read_text()
        self.assertIn('parser.add_argument("--freeze-at-peek", action="store_true"', source)
        self.assertIn("sequence = await self.peek_out(slot, limit=60.0 if attempt == 1 else 20.0, required=attempt == 1)",
                      source)
        self.assertIn("commands_during_the_stop=handed", source)          # whether the window was met, each stop
        self.assertIn('"--freeze-at-peek: with --freeze game:PLAYER:battle:SECONDS"', source)

    def test_the_commands_handed_during_a_stop_are_read_from_the_route_timeline(self):
        import json
        import tempfile
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "route-timeline.jsonl"
            events = [dict(t=99.0, ev="handed", who="host-id", command=151),
                      dict(t=100.004, ev="handed", who="host-id", command=152),
                      dict(t=100.5, ev="execute", who="host-id", command=152),
                      dict(t=101.0, ev="handed", who="friend-id", command=88),
                      dict(t=109.9, ev="handed", who="New Host", command=153),
                      dict(t=110.2, ev="handed", who="host-id", command=154)]
            path.write_text("".join(json.dumps(e) + "\n" for e in events) + '{"t": 110.3, "ev": "hand')   # a line being written
            proof = SimpleNamespace(timeline=SimpleNamespace(path=path))
            handed = newcomers.NewcomersProof.handed_during(proof, {"host-id", "New Host"}, 100.0, 110.0)
            self.assertEqual(handed, [[0.004, 152], [9.9, 153]])
            self.assertIsNone(newcomers.NewcomersProof.handed_during(SimpleNamespace(), {"host-id"}, 100.0, 110.0))

    def test_peek_out_waits_for_a_peek_alone(self):
        import asyncio
        from types import SimpleNamespace
        import uuid
        from emerald_multiplayer.native_battle import NativeControl, Opcode
        battle = str(uuid.uuid4())
        peek = NativeControl(100, 1, battle, 7, Opcode.PEEK)
        deliver = NativeControl(100, 1, battle, 7, Opcode.DELIVER)
        companion = SimpleNamespace(_battle_pending={7: (deliver, None)})
        proof = SimpleNamespace(current={0: object()}, harness=SimpleNamespace(names=["New Host"]))

        async def companion_of(worker):
            return companion
        proof.companion_of = companion_of

        async def scenario():
            waiting = asyncio.create_task(newcomers.NewcomersProof.peek_out(proof, 0, limit=5))
            await asyncio.sleep(.05)
            self.assertFalse(waiting.done())                # a host command held: not yet
            companion._battle_pending = {}
            await asyncio.sleep(.05)
            self.assertFalse(waiting.done())                # nothing out: not yet
            companion._battle_pending = {7: (peek, None)}
            return await asyncio.wait_for(waiting, 2)
        self.assertEqual(asyncio.run(scenario()), 7)


if __name__ == "__main__":
    unittest.main()
