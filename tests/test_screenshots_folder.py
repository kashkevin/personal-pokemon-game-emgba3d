"""Where the native 3D game puts its F12 pictures (KNOWN_ISSUES MS-241): EmeraldTogether in the player's Pictures
folder, named with --screenshots; nothing when there is no Pictures folder; never an error for a launch. The game's own
handling of --screenshots (the folder made with the first picture, its fallback beside the game) is tested in the
engine."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from emerald_multiplayer import screenshots


class ScreenshotsFolderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_the_folder_is_emeraldtogether_in_the_pictures_folder(self):
        pictures = self.root / "Pictures"
        pictures.mkdir()
        with patch("emerald_multiplayer.screenshots.pictures_folder", return_value=pictures):
            self.assertEqual(screenshots.folder(), pictures / "EmeraldTogether")
            self.assertEqual(screenshots.arguments(), ("--screenshots", str(pictures / "EmeraldTogether")))
        # named only: the game makes it with its first picture
        self.assertEqual(list(pictures.iterdir()), [])

    def test_no_pictures_folder_names_nothing(self):
        with patch("emerald_multiplayer.screenshots.pictures_folder", return_value=None):
            self.assertIsNone(screenshots.folder())
            self.assertEqual(screenshots.arguments(), ())

    def test_a_failure_never_stops_a_launch(self):
        for error in (OSError("denied"), RuntimeError("no home"), ValueError("bad")):
            with self.subTest(error=type(error).__name__), \
                    patch("emerald_multiplayer.screenshots.pictures_folder", side_effect=error):
                self.assertIsNone(screenshots.folder())
                self.assertEqual(screenshots.arguments(), ())

    @unittest.skipIf(os.name == "nt", "the home folder's Pictures is the fallback where the known folder is not asked")
    def test_the_home_pictures_folder_when_it_is_there(self):
        home = self.root / "home"
        home.mkdir()
        with patch("emerald_multiplayer.screenshots.Path.home", return_value=home):
            self.assertIsNone(screenshots.pictures_folder())
            (home / "Pictures").mkdir()
            self.assertEqual(screenshots.pictures_folder(), home / "Pictures")
            (home / "Pictures").rmdir()
            (home / "Pictures").write_text("not a folder")
            self.assertIsNone(screenshots.pictures_folder())

    @unittest.skipUnless(os.name == "nt", "Windows' known folders")
    def test_the_windows_pictures_known_folder(self):
        # SHGetKnownFolderPath(FOLDERID_Pictures) on this Windows user: an absolute folder that is there (the call
        # checks it is; a profile without one names nothing, and then neither is the usual place there)
        found = screenshots._windows_pictures()
        if found is None:
            self.assertFalse((Path(os.environ.get("USERPROFILE", "")) / "Pictures").is_dir())
            self.skipTest("this Windows user has no Pictures folder")
        self.assertTrue(found.is_absolute())
        self.assertTrue(found.is_dir())
        self.assertEqual(screenshots.pictures_folder(), found)
        self.assertEqual(screenshots.folder(), found / "EmeraldTogether")


if __name__ == "__main__":
    unittest.main()
