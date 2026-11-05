"""The world trades' Egg proof in its Windows mode, without Windows (scripts/multiplayer/native_launcher_newcomers_proof.py
--scenario trade-egg; the windows-package job trade-proof's egg-party and egg-box). It ran on Linux only before
2026-11-05: it read the test build's breed log from the game's runtime.log (on Windows the game's own output may reach no
file) and refused Windows outright. Every game it starts now appends that log to a file of its own (PKMN_TEST_LOG in its
launch folder), read on every platform. Stand-ins here for the launcher's spawn and the harness; the games themselves run
on the runner (the soft reset's Ctrl+R on Windows: tests/test_native_windows_probe.py)."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT / "src", ROOT / "scripts" / "multiplayer", ROOT / "scripts" / "windows-runtime"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
import native_launcher_newcomers_proof as newcomers  # noqa: E402


class EggProofOnWindowsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def adopted(self, scenario):
        """The proof's adopt over a stand-in for the launcher's spawn (restored afterwards), and what it was asked."""
        self.addCleanup(setattr, asyncio, "create_subprocess_exec", asyncio.create_subprocess_exec)
        spawned = []

        async def spawn(program, *arguments, **options):
            spawned.append(dict(program=program, arguments=arguments, **options))
        asyncio.create_subprocess_exec = spawn
        proof = newcomers.NewcomersProof(scenario, "1v1v1v1", 120, 900)
        proof.timeline = object()     # no route timeline: its install wraps the app's classes for good (a real run's)
        proof.adopt(SimpleNamespace(args=SimpleNamespace(display=[":96", ":97"]), output=self.tmp))
        return proof, spawned

    @staticmethod
    def start(directory):
        """The launcher's spawn of the game (player_runtime._open_child): its launch folder is the working directory."""
        asyncio.run(asyncio.create_subprocess_exec("pokeemerald-mp-bfxtest.exe", "--save", "character.sav",
                                                   cwd=directory, stdin=-3))

    def test_each_game_appends_the_test_builds_log_in_its_own_launch_folder(self):
        proof, spawned = self.adopted("trade-egg")
        first, again = self.tmp / "launches" / "first", self.tmp / "launches" / "again"
        self.start(first)                           # an enrollment's, Host Game's or Join Game's start
        proof.thread_slot[threading.get_ident()] = (threading.current_thread(), 1)
        self.start(again)                           # the friend's game started again by its reset, from its worker
        one, two = spawned
        self.assertEqual(one["env"]["PKMN_TEST_LOG"], str(first / newcomers.TEST_LOG))
        self.assertEqual(one["env"].get("DISPLAY"), os.environ.get("DISPLAY"))     # the environment it inherited
        self.assertEqual(two["env"]["PKMN_TEST_LOG"], str(again / newcomers.TEST_LOG))
        self.assertEqual(two["env"]["DISPLAY"], ":97")             # AbandonProof's spawn: the friend's own display
        for call, directory in ((one, first), (two, again)):       # nothing else of the spawn changes
            self.assertEqual((call["program"], call["arguments"], call["cwd"], call["stdin"]),
                             ("pokeemerald-mp-bfxtest.exe", ("--save", "character.sav"), directory, -3))

    def test_another_scenarios_games_start_as_before(self):
        proof, spawned = self.adopted("trade-mail")
        self.start(self.tmp / "launches" / "first")
        proof.thread_slot[threading.get_ident()] = (threading.current_thread(), 0)
        self.start(self.tmp / "launches" / "again")
        self.assertNotIn("env", spawned[0])                        # inherited, as before
        self.assertEqual(spawned[1]["env"]["DISPLAY"], ":96")
        self.assertNotIn("PKMN_TEST_LOG", spawned[1]["env"])

    def test_the_breed_log_is_read_from_the_games_own_test_log(self):
        proof = newcomers.NewcomersProof("trade-egg", "1v1v1v1", 120, 900)
        launch = self.tmp / "launch"
        launch.mkdir()
        # the game's own output (on Linux SDL_Log's copy of each line; on Windows maybe nothing) is not what is read
        (launch / "runtime.log").write_text("INFO: Battle env test: breed moved 9 party Eggs to the PC\n")

        async def log_of(worker):
            return launch / "runtime.log"
        proof.log_of = log_of
        self.assertEqual(asyncio.run(proof.log_lines(None, "breed moved")), [])     # nothing written yet
        (launch / newcomers.TEST_LOG).write_bytes(
            b"Battle env test: breed party 0: species 175 egg 1 level 1\r\n"           # Windows' line ends
            b"Battle env test: breed moved 1 party Eggs to the PC\r\n"
            b"Battle env test: breed pc notice: PC EGG HATCHED!\r\n")
        self.assertEqual(asyncio.run(proof.log_lines(None, "breed moved")), ["breed moved 1 party Eggs to the PC"])
        self.assertEqual(asyncio.run(proof.log_lines(None, "breed pc notice: PC EGG HATCHED!")),
                         ["breed pc notice: PC EGG HATCHED!"])

    def test_trade_egg_runs_on_windows_with_the_breed_log(self):
        started = []

        async def launcher_proof(args, **options):
            started.append((args, options))
        for name in ("trade-egg-a.sav", "trade-egg-b.sav"):
            (self.tmp / name).write_bytes(b"")
        argv = ["native_launcher_newcomers_proof.py", "--scenario", "trade-egg", "--hatch-in", "box",
                "--game", "pokeemerald-mp-bfxtest.exe", "--sdl", "SDL2.dll", "--rom", "pokedev.gba",
                "--manifest", "manifest.json", "--pe-symbols", "pokeemerald-mp-bfxtest.nm.txt",
                "--sizes", "pokeemerald-mp.sizes.txt", "--slow", "1.5", "--source", str(self.tmp / "trade-egg-a.sav"),
                "--source", str(self.tmp / "trade-egg-b.sav"), "--output", str(self.tmp / "multiplayer-proof" / "egg")]
        two = SimpleNamespace(metadata=SimpleNamespace(party_count=2))
        with mock.patch.object(newcomers, "launcher_proof", launcher_proof), \
                mock.patch.object(newcomers, "inspect_flash", lambda data: two), \
                mock.patch.object(newcomers, "WINDOWS", True), mock.patch.object(sys, "argv", argv):
            newcomers.main()
        (args, options), = started
        self.assertEqual(args.display, ["desktop-0", "desktop-1"])
        self.assertEqual(options["environment"]["PKMN_TEST_BREED_LOG"], "1")
        self.assertEqual(options["party_counts"], (2, 2))
        self.assertEqual(args.hatch_in, "box")


if __name__ == "__main__":
    unittest.main()
