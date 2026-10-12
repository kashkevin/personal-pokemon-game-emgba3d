"""The launcher's view of the native game's display settings (game-settings.cfg)."""
from pathlib import Path
import tempfile
import unittest

from emerald_multiplayer.game_display_settings import read_display_settings, write_display_settings


class GameDisplaySettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "game-settings.cfg"

    def test_defaults_without_a_file(self):
        self.assertEqual(read_display_settings(self.path),
                         dict(resolution="1920x1080", mode="windowed", quality="high"))

    def test_older_files_as_the_game_reads_them(self):
        # windowScale=4 (1280x720) was every older file's default, not a choice.
        self.path.write_text("fullscreen=1\nwindowScale=4\nvsync=1\n")
        self.assertEqual(read_display_settings(self.path),
                         dict(resolution="1920x1080", mode="borderless", quality="high"))
        self.path.write_text("fullscreen=0\nwindowScale=2\n")
        self.assertEqual(read_display_settings(self.path)["resolution"], "640x360")

    def test_a_file_the_game_wrote(self):
        self.path.write_text("borderBackground=0\nbackgroundOrder=2\nfullscreen=1\nintegerScale=0\nvsync=1\n"
                             "border=1\nvolume=10\ncryVolume=5\nresolution=2560x1440\ndisplayMode=borderless\n"
                             "fullscreenMode=borderless\nquality=ultra\nshadows=high\nlighting=1\neffects=1\n"
                             "antialiasing=4\ncameraStyle=1\ntreeStyle=1\ncameraPitch=0\ncameraZoom=-2\n")
        self.assertEqual(read_display_settings(self.path),
                         dict(resolution="2560x1440", mode="borderless", quality="ultra"))

    def test_writing_keeps_every_other_line(self):
        self.path.write_text("cameraStyle=1\nvolume=7\nfullscreen=0\nwindowScale=4\nquality=low\nshadows=off\n"
                             "cameraZoom=-3\n")
        result = write_display_settings(self.path, resolution="3840x2160", mode="fullscreen", quality="medium")
        self.assertEqual(result, dict(resolution="3840x2160", mode="fullscreen", quality="medium"))
        lines = self.path.read_text().splitlines()
        self.assertEqual(lines[:3], ["cameraStyle=1", "volume=7", "cameraZoom=-3"])
        self.assertIn("displayMode=fullscreen", lines)
        self.assertIn("fullscreenMode=fullscreen", lines)
        self.assertIn("fullscreen=1", lines)
        self.assertNotIn("windowScale=4", lines)
        self.assertNotIn("shadows=off", lines)  # the preset decides its own values
        self.assertEqual(sum(line.startswith("quality=") for line in lines), 1)

    def test_older_game_builds_keep_their_window_size(self):
        write_display_settings(self.path, resolution="1920x1080", mode="windowed", quality="high")
        self.assertIn("windowScale=6", self.path.read_text().splitlines())
        write_display_settings(self.path, resolution="2560x1440", mode="windowed", quality="high")
        self.assertFalse(any(line.startswith("windowScale=") for line in self.path.read_text().splitlines()))

    def test_windowed_keeps_the_fullscreen_kind_f11_uses(self):
        self.path.write_text("displayMode=fullscreen\nfullscreenMode=fullscreen\n")
        write_display_settings(self.path, resolution="1920x1080", mode="windowed", quality="high")
        lines = self.path.read_text().splitlines()
        self.assertIn("displayMode=windowed", lines)
        self.assertIn("fullscreenMode=fullscreen", lines)

    def test_custom_quality_stays_the_games(self):
        self.path.write_text("quality=custom\nshadows=low\nlighting=0\neffects=1\ndetails=0\nantialiasing=2\n")
        self.assertEqual(read_display_settings(self.path)["quality"], "custom")
        write_display_settings(self.path, resolution="1280x720", mode="borderless", quality="custom")
        lines = self.path.read_text().splitlines()
        for line in ("quality=custom", "shadows=low", "lighting=0", "effects=1", "details=0", "antialiasing=2"):
            self.assertIn(line, lines)
        self.path.write_text("shadows=low\n")  # edited by hand, no preset named
        self.assertEqual(read_display_settings(self.path)["quality"], "custom")
        self.path.write_text("details=0\n")  # the 3D view's world details, set in the game's F10 menu
        self.assertEqual(read_display_settings(self.path)["quality"], "custom")
        write_display_settings(self.path, resolution="1920x1080", mode="windowed", quality="high")
        self.assertNotIn("details=0", self.path.read_text().splitlines())  # the preset decides it

    def test_invalid_choices_change_nothing(self):
        self.path.write_text("volume=7\n")
        for options in (dict(resolution="100x100", mode="windowed", quality="high"),
                        dict(resolution="1920x1080", mode="sideways", quality="high"),
                        dict(resolution="1920x1080", mode="windowed", quality="extreme")):
            with self.assertRaises(ValueError):
                write_display_settings(self.path, **options)
        self.assertEqual(self.path.read_text(), "volume=7\n")

    def test_an_oversized_file_is_refused(self):
        self.path.write_bytes(b"x" * 70000)
        with self.assertRaises(ValueError):
            read_display_settings(self.path)


if __name__ == "__main__":
    unittest.main()
