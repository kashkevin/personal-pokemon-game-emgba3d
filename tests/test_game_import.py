"""Format vectors are synthetic bytes, never game or player data."""
import hashlib
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from emerald_multiplayer.game_import import (
    GameImporter, GameImportError, ImportRelease, MAX_ROM, apply_bps,
)


def number(value):
    output = bytearray()
    while value >= 128:
        output.append(value & 127)
        value = (value >> 7) - 1
    return bytes(output + bytes([value | 128]))


def patch(source, target, actions, *, target_size=None, metadata=b""):
    data = b"BPS1" + number(len(source)) + number(len(target) if target_size is None else target_size)
    data += number(len(metadata)) + metadata + actions
    data += struct.pack("<II", zlib.crc32(source), zlib.crc32(target))
    return data + struct.pack("<I", zlib.crc32(data))


def crc_repair(data):
    return data[:-4] + struct.pack("<I", zlib.crc32(data[:-4]))


class BpsTests(unittest.TestCase):
    def test_all_commands_signed_relative_offsets_and_overlap(self):
        source = b"abcdefghijklmnop"
        target = b"abXYklab!!!XYXYXY"
        # SourceRead 2; TargetRead XY; SourceCopy 2 from +10, then 2
        # from -12; TargetRead !; overlapping TargetCopy two !; then
        # TargetCopy XY from -8, repeating the already-written XY region.
        actions = bytes([0x84, 0x85]) + b"XY" + bytes([0x86, 0x94, 0x86, 0x99,
                  0x81]) + b"!" + bytes([0x87, 0x90, 0x87, 0x91, 0x8f, 0x8e])
        # After !! the target cursor is 10; -8 => 2 copies XY (cursor4),
        # then +7 => 11 copies XYXY with overlap in the newly appended period.
        self.assertEqual(apply_bps(source, patch(source, target, actions)), target)

    def test_empty_and_metadata_are_supported_but_metadata_is_inert(self):
        self.assertEqual(apply_bps(b"", patch(b"", b"", b"")), b"")
        self.assertEqual(apply_bps(b"a", patch(b"a", b"a", b"\x80", metadata=b"<not-xml>")), b"a")

    def test_corruption_and_wrong_source_are_rejected(self):
        valid = patch(b"abc", b"abc", b"\x88")
        for bad in (valid[:-1], b"BPS2" + valid[4:], valid[:-4] + b"\0\0\0\0"):
            with self.assertRaises(GameImportError):
                apply_bps(b"abc", bad)
        with self.assertRaisesRegex(GameImportError, "source_mismatch"):
            apply_bps(b"xyz", valid)
        damaged = bytearray(valid)
        damaged[-8] ^= 1
        with self.assertRaises(GameImportError):
            apply_bps(b"abc", crc_repair(damaged))

    def test_malformed_sizes_commands_and_offsets_rejected(self):
        cases = [
            patch(b"a", b"a", b"", target_size=MAX_ROM + 1),
            patch(b"a", b"a", b"\x84"),  # output overrun
            patch(b"a", b"ab", b"\x84"),  # source read past source
            patch(b"a", b"a", b"\x81"),  # missing literal
            patch(b"a", b"a", b"\x82\x83"),  # source offset -1
            patch(b"a", b"a", b"\x83\x80"),  # unwritten target copy
            patch(b"a", b"a", b"\0" * 11),  # unterminated integer
            patch(b"a", b"a", b""),  # output underrun
            patch(b"a", b"a", b"\x80\x80"),  # trailing command
        ]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(GameImportError):
                apply_bps(b"a", value)

    def test_large_overlapping_run_has_exact_length(self):
        target = b"Z" * (2 * 1024 * 1024)
        actions = b"\x81Z" + number(((len(target) - 2) << 2) | 3) + b"\x80"
        self.assertEqual(apply_bps(b"", patch(b"", target, actions)), target)


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source, self.target = b"original", b"changed!"
        self.patch = patch(self.source, self.target, number(((len(self.target)-1) << 2) | 1) + self.target)
        sha = lambda value: hashlib.sha256(value).hexdigest()
        self.release = ImportRelease(sha(self.source), sha(self.patch), sha(self.target), 8, 8)
        self.dump = self.root / "my-own-dump.gba"
        self.dump.write_bytes(self.source)
        self.patch_path = self.root / "game.bps"
        self.patch_path.write_bytes(self.patch)
        self.importer = GameImporter(self.release, self.patch_path, self.root / "private")

    def test_install_is_exact_private_atomic_and_original_unchanged(self):
        target = self.importer.install(self.dump)
        self.assertEqual(target, self.root / "private/games" / self.release.target_sha256 / "game.gba")
        self.assertEqual(target.read_bytes(), self.target)
        self.assertEqual(self.dump.read_bytes(), self.source)
        self.assertEqual(self.importer.install(self.dump), target)
        self.assertEqual(list(target.parent.glob(".import-*")), [])

    def test_wrong_source_patch_or_target_pin_cannot_publish(self):
        self.dump.write_bytes(b"different")
        with self.assertRaisesRegex(GameImportError, "source_mismatch"):
            self.importer.install(self.dump)
        self.dump.write_bytes(self.source)
        self.patch_path.write_bytes(self.patch + b"x")
        with self.assertRaisesRegex(GameImportError, "patch_mismatch"):
            self.importer.install(self.dump)
        self.patch_path.write_bytes(self.patch)
        wrong = ImportRelease(self.release.source_sha256, self.release.patch_sha256, "a"*64, 8, 8)
        with self.assertRaisesRegex(GameImportError, "target_mismatch"):
            GameImporter(wrong, self.patch_path, self.root / "private").install(self.dump)
        self.assertFalse(self.importer.target_path.exists())

    def test_existing_changed_file_is_preserved(self):
        destination = self.importer.target_path
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b"retain me")
        with self.assertRaisesRegex(GameImportError, "import_destination"):
            self.importer.install(self.dump)
        self.assertEqual(destination.read_bytes(), b"retain me")

    def test_release_pins_are_strict(self):
        for size in (0, True, MAX_ROM + 1):
            with self.assertRaises(GameImportError):
                ImportRelease("a"*64, "b"*64, "c"*64, size, 1)
        with self.assertRaises(GameImportError):
            ImportRelease("A"*64, "b"*64, "c"*64, 1, 1)


if __name__ == "__main__":
    unittest.main()
