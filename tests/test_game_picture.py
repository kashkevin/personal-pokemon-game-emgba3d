"""The launcher proofs' evidence pictures on Windows (native_launcher_battle_proof.game_picture). Regression for
windows-package run 129: the multiplayer Mega proof stopped right after both Charizard had Mega Evolved, on its picture
of the moment - X11 commands (xdotool, ImageMagick's import) given a Windows window handle. On Windows the picture is the
runner's desktop (ci_world_check.screenshot); the proofs that run there take theirs through game_picture."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT / "src", ROOT / "scripts" / "multiplayer", ROOT / "scripts" / "windows-runtime"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
import ci_world_check  # noqa: E402
import native_launcher_battle_proof as proof  # noqa: E402


class Probe:
    environment = {}

    def _window(self):
        return 0x1234                                # a Windows window handle: a number


class GamePictureTests(unittest.TestCase):
    def test_windows_takes_the_desktop_and_runs_no_x11_command(self):
        taken = []
        with mock.patch.object(proof, "WINDOWS", True), \
                mock.patch.object(ci_world_check, "screenshot", lambda path: taken.append(path)), \
                mock.patch.object(subprocess, "run", side_effect=AssertionError("an X11 command on Windows")):
            name = proof.game_picture(Probe(), Path("out") / "mega-evolved-alice.png")
        self.assertEqual(name, "mega-evolved-alice.png")
        self.assertEqual(taken, [str(Path("out") / "mega-evolved-alice.png")])

    def test_the_proofs_that_run_on_windows_take_their_pictures_through_it(self):
        for name in ("native_launcher_mega_proof.py", "native_launcher_tower_proof.py",
                     "native_launcher_three_player_proof.py"):
            text = (ROOT / "scripts" / "multiplayer" / name).read_text()
            self.assertIn("return game_picture(", text, name)
            self.assertNotIn("xdotool", text, name)


if __name__ == "__main__":
    unittest.main()
