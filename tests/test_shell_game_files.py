"""The in-game menu when the game file is not installed: what a package without game import shows (the CI full package when the
owner's dump is not supplied), and how Settings, Game files installs it in a package with import (BPS from the player's own file)."""
from dataclasses import replace
import hashlib
import random
import unittest

from emerald_multiplayer.game_import import GameImporter, ImportRelease
from emerald_multiplayer.game_patch import create_bps
from shell_fixture import BACK, Driver, FakeWorker, World, select


def sha(data):
    return hashlib.sha256(data).hexdigest()


def row(screen, identifier):
    return next(item for item in screen.items if item.id == identifier)


class GameFilesTests(unittest.TestCase):
    def setUp(self):
        self.world = World(self)
        self.rom = self.world.rom.read_bytes()
        # Where a package looks for the game: the private folder, by the release's ROM hash (LauncherRelease.installation).
        self.target = self.world.private / "games" / sha(self.rom) / "game.gba"
        self.installation = replace(self.world.installation, rom_path=self.target)

    def _app(self, driver, **options):
        from emerald_multiplayer.shell_app import ShellApp
        from emerald_multiplayer.shell_protocol import ScriptedShell
        worker = options.pop("worker", FakeWorker())
        app = ShellApp(self.installation, self.world.private, ScriptedShell(driver), worker=worker, lan=lambda: ["192.168.1.20"],
                       graphics_gate=lambda: "3d", version="test", **options)
        return app, worker

    def test_without_the_game_file_and_without_import_the_menu_explains_and_starts_nothing(self):
        seen = {}

        def main(screen):
            seen["status"] = screen.status
            return select("new")

        def files_row(screen):
            seen["files"] = row(screen, "files").detail
            return select("files")

        def cannot_install(screen):
            seen["files_message"] = " ".join(screen.notes)
            return BACK
        driver = Driver(("main", main),
                        ("message", lambda screen: seen.update(new_game=screen.title) or BACK),
                        ("main", select("settings")), ("settings", files_row), ("message", cannot_install),
                        ("settings", BACK), ("main", select("exit")))
        app, worker = self._app(driver)
        self.assertEqual(app.run(), 0)
        self.assertTrue(driver.done(), driver.steps)
        self.assertEqual(seen["status"][0], "warn")
        self.assertIn("not installed yet", seen["status"][1])
        self.assertEqual(seen["new_game"], "Game files needed")
        self.assertEqual(seen["files"], "not installed")
        self.assertIn("cannot install them", seen["files_message"])
        self.assertEqual(worker.requests, [])                       # no game was started
        self.assertEqual(app.registry.entries(), [])                # and no world was created
        self.assertFalse(self.target.exists())

    def test_import_installs_the_players_own_file_and_then_the_game_is_verified(self):
        base = bytes(random.Random(31).getrandbits(8) for _ in range(4096))   # a stand-in for the player's own dump
        patch = create_bps(base, self.rom)
        patch_path = self.world.root / "game.bps"
        patch_path.write_bytes(patch)
        importer = GameImporter(ImportRelease(sha(base), sha(patch), sha(self.rom), len(base), len(self.rom)),
                                patch_path, self.world.private)
        own, other = self.world.root / "my-emerald.gba", self.world.root / "something-else.gba"
        own.write_bytes(base)
        other.write_bytes(base[:-1] + bytes([base[-1] ^ 1]))
        seen = {}

        def settings_after(screen):
            seen["status"], seen["files"] = screen.status, row(screen, "files").detail
            return BACK
        driver = Driver(("main", select("settings")), ("settings", select("files")),
                        ("import", select("go", path=str(other))),
                        ("message", lambda screen: seen.update(refused=" ".join(screen.notes)) or BACK),
                        ("settings", select("files")), ("import", select("go", path=f'"{own}"')),
                        ("settings", settings_after),
                        ("main", lambda screen: seen.update(main=screen.status) or select("exit")))
        app, _ = self._app(driver, importer=importer)
        self.assertEqual(app.run(), 0)
        self.assertTrue(driver.done(), driver.steps)
        self.assertIn("could not be used", seen["refused"])
        self.assertEqual(seen["status"], ("ok", "Game installed."))
        self.assertEqual(seen["files"], "installed and verified")
        self.assertNotEqual((seen["main"] or ("",))[0], "warn")
        self.assertEqual(self.target.read_bytes(), self.rom)
        self.installation.verify()                                  # the launcher's own check before every start


if __name__ == "__main__":
    unittest.main()
