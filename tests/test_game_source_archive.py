"""Import trust and bounded ZIP handling with invented cartridge bytes only."""
import hashlib
import io
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from emerald_multiplayer.game_import import (
    GameImportError, GameImporter, ImportRelease, MAX_ROM, read_game_source,
)
from emerald_multiplayer.game_patch import create_bps


def invented_game():
    data = bytearray(1024)
    data[0xA0:0xAC] = b"TEST FIXTURE"
    data[0xB2] = 0x96
    data[0xBD] = (-sum(data[0xA0:0xBD]) - 0x19) & 255
    return bytes(data)


def archive_bytes(*members, compression=zipfile.ZIP_DEFLATED):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as archive:
        for name, content in members:
            archive.writestr(name, content)
    return output.getvalue()


class SourceArchiveTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.path = self.root / "my-dump.zip"
        self.game = invented_game()

    def read(self, data):
        self.path.write_bytes(data)
        return read_game_source(self.path)

    def test_single_game_roundtrip_is_exact_and_never_extracted(self):
        original = archive_bytes(("nested/my-dump.GBA", self.game), ("notice.txt", b"inert"))
        self.assertEqual(self.read(original), self.game)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_import_pins_the_expanded_dump_and_keeps_original_archive(self):
        original = archive_bytes(("my-dump.gba", self.game))
        self.path.write_bytes(original)
        target = self.game + b"private modified fixture"
        delta = create_bps(self.game, target)
        patch_path = self.root / "game.bps"
        patch_path.write_bytes(delta)
        sha = lambda value: hashlib.sha256(value).hexdigest()
        release = ImportRelease(sha(self.game), sha(delta), sha(target), len(self.game), len(target))
        importer = GameImporter(release, patch_path, self.root / "private")
        self.assertEqual(importer.install(self.path).read_bytes(), target)
        self.assertEqual(self.path.read_bytes(), original)
        wrong = ImportRelease(sha(original), sha(delta), sha(target), len(self.game), len(target))
        with self.assertRaisesRegex(GameImportError, "source_mismatch"):
            GameImporter(wrong, patch_path, self.root / "other").install(self.path)
        self.assertFalse((self.root / "other").exists())

    def test_ambiguous_missing_bad_header_and_corrupt_streams_refused(self):
        invalid = bytearray(self.game)
        invalid[0xA0] ^= 1
        stored = bytearray(archive_bytes(("game.gba", self.game), compression=zipfile.ZIP_STORED))
        # Damage actual member bytes without repairing its CRC.
        offset = 30 + len("game.gba")
        stored[offset + 300] ^= 1
        cases = [archive_bytes(("a.gba", self.game), ("b.gba", self.game)),
                 archive_bytes(("readme.txt", b"no game")),
                 archive_bytes(("game.gba", bytes(invalid))), bytes(stored), b"not a ZIP"]
        for data in cases:
            with self.subTest(size=len(data)), self.assertRaisesRegex(GameImportError, "source_archive"):
                self.read(data)

    def test_directory_limits_checked_before_zipfile_allocates(self):
        valid = bytearray(archive_bytes(("game.gba", self.game)))
        end = valid.rfind(b"PK\x05\x06")
        cases = []
        for offset, format, value in ((8, "<HH", (65, 65)), (12, "<I", (1024 * 1024 + 1,)),
                                      (4, "<H", (1,))):
            bad = bytearray(valid)
            struct.pack_into(format, bad, end + offset, *value)
            cases.append(bytes(bad))
        for data in cases:
            with self.subTest(data=data[-22:]), patch("zipfile.ZipFile") as constructor:
                with self.assertRaisesRegex(GameImportError, "source_archive"):
                    self.read(data)
                constructor.assert_not_called()

    def test_expansion_encryption_and_unsupported_compression_refused(self):
        valid = bytearray(archive_bytes(("game.gba", self.game)))
        central = valid.index(b"PK\x01\x02")
        for offset, format, value in ((24, "<I", MAX_ROM + 1), (8, "<H", 1), (10, "<H", 12)):
            bad = bytearray(valid)
            struct.pack_into(format, bad, central + offset, value)
            with self.subTest(offset=offset), self.assertRaisesRegex(GameImportError, "source_archive"):
                self.read(bad)

    def test_raw_fixture_remains_compatible(self):
        raw = self.root / "raw.gba"
        raw.write_bytes(b"legacy raw-format test vector")
        self.assertEqual(read_game_source(raw), raw.read_bytes())


if __name__ == "__main__":
    unittest.main()
