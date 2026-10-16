from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from emerald_multiplayer import launcher_worlds
from emerald_multiplayer.launcher_worlds import (
    STATUS_INVALID, STATUS_NEEDS_GAME, STATUS_READY, lan_addresses, scan_worlds, worlds_directory,
)


class Installation:
    rom_path, manifest_path = Path("rom.gba"), Path("manifest.json")

    def __init__(self, ok=True):
        self.ok = ok

    def verify(self):
        if not self.ok:
            raise ValueError("installation_changed")


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def world(self, name, mtime=None):
        directory = worlds_directory(self.root) / name
        directory.mkdir(parents=True)
        record = directory / "host.json"
        record.write_text("{}")
        if mtime is not None:
            import os
            os.utime(record, (mtime, mtime))
        return directory

    def test_no_worlds_directory_is_an_empty_list(self):
        self.assertEqual(scan_worlds(Installation(), self.root), [])

    def test_a_world_lists_its_players_and_is_ready(self):
        directory = self.world("a")
        accounts = [SimpleNamespace(display_name=n) for n in ("Ash", "Misty")]
        with patch.object(launcher_worlds.HostWorld, "open", return_value=SimpleNamespace(accounts=accounts)) as opened:
            entries = scan_worlds(Installation(), self.root)
        self.assertEqual(len(entries), 1)
        self.assertEqual((entries[0].names, entries[0].status, entries[0].players), (("Ash", "Misty"), STATUS_READY, 2))
        self.assertEqual(entries[0].title, "Ash's world with Misty")
        self.assertEqual(entries[0].host_json, directory / "host.json")
        opened.assert_called_once()

    def test_a_solo_world_says_so(self):
        self.world("a")
        with patch.object(launcher_worlds.HostWorld, "open", return_value=SimpleNamespace(accounts=[SimpleNamespace(display_name="Red")])):
            self.assertEqual(scan_worlds(Installation(), self.root)[0].title, "Red's world (solo)")

    def test_a_world_that_does_not_open_is_listed_as_invalid_not_raised(self):
        self.world("a")
        with patch.object(launcher_worlds.HostWorld, "open", side_effect=ValueError("world_invalid")):
            entries = scan_worlds(Installation(), self.root)
        self.assertEqual((entries[0].status, entries[0].names), (STATUS_INVALID, ()))
        self.assertTrue(entries[0].title.startswith("World "))

    def test_without_the_game_installed_worlds_are_listed_but_not_opened(self):
        self.world("a")
        with patch.object(launcher_worlds.HostWorld, "open") as opened:
            entries = scan_worlds(Installation(ok=False), self.root)
        self.assertEqual(entries[0].status, STATUS_NEEDS_GAME)
        opened.assert_not_called()

    def test_newest_first_and_folders_without_a_record_are_skipped(self):
        self.world("old", mtime=1_000_000)
        self.world("new", mtime=2_000_000)
        (worlds_directory(self.root) / "empty").mkdir()
        (worlds_directory(self.root) / "note.txt").write_text("x")
        with patch.object(launcher_worlds.HostWorld, "open", side_effect=ValueError()):
            names = [entry.directory.name for entry in scan_worlds(Installation(), self.root)]
        self.assertEqual(names, ["new", "old"])

    def test_scanning_never_changes_the_world(self):
        directory = self.world("a")
        before = sorted(p.name for p in directory.iterdir())
        with patch.object(launcher_worlds.HostWorld, "open", side_effect=ValueError()):
            scan_worlds(Installation(), self.root)
        self.assertEqual(sorted(p.name for p in directory.iterdir()), before)


class RealWorldTests(unittest.TestCase):
    """The catalogue against worlds made and opened by the real setup code (real TLS, storage and roster checks)."""

    def setUp(self):
        import hashlib
        import socket
        from emerald_multiplayer.launcher_session import GameInstallation
        from emerald_multiplayer.launcher_setup import create_world
        from test_host_world import make_trade_files
        from test_player_runtime import write_bundle
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        rom, manifest = make_trade_files(self.root)
        bundle = self.root / "bundle"
        bundle.mkdir()
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        self.installation = GameInstallation(rom, manifest, digest(rom), digest(manifest), write_bundle(bundle))
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            self.port = listener.getsockname()[1]
        self.create_world = create_world

    def test_created_worlds_are_listed_with_their_players_and_nothing_is_changed(self):
        private = self.root / "private"
        first = self.create_world(self.installation, private, player_names=("Ash", "Misty", "Brock"), endpoint="127.0.0.1", port=self.port)
        second = self.create_world(self.installation, private, player_names=("Red",), endpoint="127.0.0.1", port=self.port)
        before = {path: path.stat().st_mtime_ns for path in private.rglob("*") if path.is_file()}
        entries = scan_worlds(self.installation, private)
        self.assertEqual(sorted(entry.title for entry in entries), ["Ash's world with Misty, Brock", "Red's world (solo)"])
        self.assertTrue(all(entry.status == STATUS_READY for entry in entries))
        self.assertEqual({entry.directory for entry in entries}, {first.directory, second.directory})
        after = {path: path.stat().st_mtime_ns for path in private.rglob("*") if path.is_file()}
        self.assertEqual({p: t for p, t in after.items() if p in before}, before, "listing a world must not write to it")
        self.assertEqual(set(after), set(before), "and must not add files")

    def test_a_damaged_world_is_flagged_while_the_others_still_list(self):
        private = self.root / "private"
        good = self.create_world(self.installation, private, player_names=("Ash",), endpoint="127.0.0.1", port=self.port)
        bad = self.create_world(self.installation, private, player_names=("Gary",), endpoint="127.0.0.1", port=self.port)
        (bad.directory / "world.sqlite3").unlink()
        entries = {entry.directory: entry for entry in scan_worlds(self.installation, private)}
        self.assertEqual(entries[good.directory].status, STATUS_READY)
        self.assertEqual(entries[bad.directory].status, STATUS_INVALID)

    def test_a_changed_installation_marks_worlds_as_needing_the_game(self):
        private = self.root / "private"
        self.create_world(self.installation, private, player_names=("Ash",), endpoint="127.0.0.1", port=self.port)
        self.installation.rom_path.write_bytes(b"changed")
        self.assertEqual([entry.status for entry in scan_worlds(self.installation, private)], [STATUS_NEEDS_GAME])


class LanTests(unittest.TestCase):
    def test_only_private_non_loopback_addresses_and_no_repeats(self):
        class FakeSocket:
            def __init__(self, *a): pass
            def connect(self, address): self.address = address
            def getsockname(self): return ("192.168.1.20", 5555)
            def close(self): pass
        infos = [(2, 1, 6, "", (a, 0)) for a in ("127.0.0.1", "192.168.1.20", "169.254.3.4", "8.8.8.8", "10.0.0.5")]
        with patch.object(launcher_worlds.socket, "socket", FakeSocket), patch.object(launcher_worlds.socket, "getaddrinfo", return_value=infos):
            self.assertEqual(lan_addresses(), ["192.168.1.20", "10.0.0.5"])

    def test_no_network_is_an_empty_list(self):
        with patch.object(launcher_worlds.socket, "socket", side_effect=OSError), \
                patch.object(launcher_worlds.socket, "getaddrinfo", side_effect=OSError):
            self.assertEqual(lan_addresses(), [])


if __name__ == "__main__":
    unittest.main()
