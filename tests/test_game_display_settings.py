"""The launcher's view of the native game's display settings (game-settings.cfg)."""
from pathlib import Path
import tempfile
import unittest

from emerald_multiplayer.game_display_settings import (
    AUDIO_DEFAULTS, AUDIO_KEYS, AUDIO_LABELS, read_audio_settings, read_display_settings, volume_percent,
    write_audio_settings, write_display_settings,
)


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


class AudioSettingsTests(unittest.TestCase):
    """The four volumes (the owner's decision of 2026-11-05: music at 70% by default, sound effects at 100%), read and
    written as the game does (engine include/platform/audio_volume.h; its --selftest-audio-volumes checks the same files)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "game-settings.cfg"

    def volumes(self, volume, music, sfx, cry):
        return dict(volume=volume, music_volume=music, sfx_volume=sfx, cry_volume=cry)

    def test_the_games_own_defaults_without_a_file(self):
        self.assertEqual(read_audio_settings(self.path), self.volumes(10, 7, 10, 10))
        self.assertEqual(AUDIO_DEFAULTS, self.volumes(10, 7, 10, 10))

    def test_a_file_this_game_wrote_is_read_as_written(self):
        self.path.write_text("border=1\nvolume=8\nmusicVolume=3\nsfxVolume=6\ncryVolume=5\nresolution=1920x1080\n")
        self.assertEqual(read_audio_settings(self.path), self.volumes(8, 3, 6, 5))      # a chosen 5 is kept here
        self.path.write_text("volume=0\nmusicVolume=10\nsfxVolume=0\ncryVolume=0\n")
        self.assertEqual(read_audio_settings(self.path), self.volumes(0, 10, 0, 0))
        self.path.write_text("sfxVolume=9\n")                                           # one new key is enough
        self.assertEqual(read_audio_settings(self.path), self.volumes(10, 7, 9, 10))

    def test_an_older_file_gets_the_new_defaults_and_its_unapplied_cry_default_reads_as_full(self):
        # Every game before musicVolume= wrote volume= and cryVolume=5 (the cries' default, never applied).
        self.path.write_text("border=1\nvolume=10\ncryVolume=5\nresolution=1920x1080\n")
        self.assertEqual(read_audio_settings(self.path), self.volumes(10, 7, 10, 10))
        self.path.write_text("volume=4\ncryVolume=5\n")                                # the master is kept as it was
        self.assertEqual(read_audio_settings(self.path), self.volumes(4, 7, 10, 10))
        self.path.write_text("volume=6\ncryVolume=2\n")                                # a cry volume chosen: kept, now applied
        self.assertEqual(read_audio_settings(self.path), self.volumes(6, 7, 10, 2))
        self.path.write_text("volume=6\ncryVolume=0\n")
        self.assertEqual(read_audio_settings(self.path)["cry_volume"], 0)
        self.path.write_text("volume=6\n")
        self.assertEqual(read_audio_settings(self.path), self.volumes(6, 7, 10, 10))

    def test_junk_is_ignored(self):
        self.path.write_text("volume=7\ncryVolume=eleven\n")
        self.assertEqual(read_audio_settings(self.path), self.volumes(7, 7, 10, 10))
        self.path.write_text("volume=11\ncryVolume=3\nmusicVolume=-1\nsfxVolume=12\n")
        self.assertEqual(read_audio_settings(self.path), self.volumes(10, 7, 10, 3))
        self.path.write_text("musicVolume=\nvolume=2\n")                               # a new key, even empty: as written
        self.assertEqual(read_audio_settings(self.path), self.volumes(2, 7, 10, 10))

    def test_writing_keeps_every_other_line_and_replaces_only_the_four_volumes(self):
        self.path.write_text("border=1\nvolume=10\nkey.a=Q\ncryVolume=5\nresolution=1920x1080\nmusicVolume=2\n")
        self.assertEqual(write_audio_settings(self.path, volume=4, music_volume=5, sfx_volume=6, cry_volume=0),
                         self.volumes(4, 5, 6, 0))
        lines = self.path.read_text().splitlines()
        self.assertEqual(lines[:3], ["border=1", "key.a=Q", "resolution=1920x1080"])
        self.assertEqual(lines[3:], ["volume=4", "musicVolume=5", "sfxVolume=6", "cryVolume=0"])

    def test_writing_an_older_file_keeps_what_it_meant(self):
        # Only the master and the cries given (an older caller): music and effects as the file reads (its defaults), and
        # the file is then of the new kind, so a cry volume of 5 chosen now stays 5.
        self.path.write_text("volume=9\ncryVolume=5\n")
        self.assertEqual(write_audio_settings(self.path, volume=9, cry_volume=5), self.volumes(9, 7, 10, 5))
        self.assertEqual(self.path.read_text().splitlines(), ["volume=9", "musicVolume=7", "sfxVolume=10", "cryVolume=5"])
        self.assertEqual(write_audio_settings(self.path, volume=3, cry_volume=8), self.volumes(3, 7, 10, 8))

    def test_out_of_range_values_are_refused_and_nothing_is_written(self):
        self.path.write_text("volume=7\n")
        for options in (dict(volume=11, cry_volume=1), dict(volume=-1, cry_volume=1), dict(volume=1.5, cry_volume=1),
                        dict(volume="5", cry_volume=1), dict(volume=True, cry_volume=1),
                        dict(volume=5, cry_volume=1, music_volume=11), dict(volume=5, cry_volume=1, sfx_volume=-1),
                        dict(volume=5, cry_volume=1, music_volume=7.0), dict(volume=5, cry_volume=None)):
            with self.assertRaises(ValueError):
                write_audio_settings(self.path, **options)
        self.assertEqual(self.path.read_text(), "volume=7\n")

    def test_percentages_and_labels(self):
        self.assertEqual([volume_percent(n) for n in (0, 7, 10)], ["0%", "70%", "100%"])
        self.assertEqual([AUDIO_LABELS[key] for key, _ in AUDIO_KEYS],
                         ["Master volume", "Music", "Sound effects", "Pokemon cries"])
        self.assertEqual([file_key for _, file_key in AUDIO_KEYS], ["volume", "musicVolume", "sfxVolume", "cryVolume"])


if __name__ == "__main__":
    unittest.main()
