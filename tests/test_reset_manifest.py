"""Optional ELF-derived personal admission metadata; synthetic symbol fixtures."""
import struct
import unittest
from emerald_multiplayer.reset_mailbox import validate_reset_manifest
import test_save_manifest as fixtures


class ResetManifestTests(unittest.TestCase):
    tearDown = fixtures.SaveManifestTests.tearDown
    generate = fixtures.SaveManifestTests.generate
    configure = fixtures.SaveManifestTests.configure

    def setUp(self):
        fixtures.SaveManifestTests.setUp(self)
        self.base = ("02021000 00000200 B gMultiplayerSaveMailbox\n"
                     "080000c0 00000004 R gMultiplayerOwnershipAbi\n")
        self.reset = ("080000c4 00000004 R gMultiplayerResetAbiVersion\n"
                      "02023000 00000080 B gMultiplayerResetMailbox\n")
        with self.rom.open("r+b") as rom:
            rom.seek(192); rom.write(struct.pack("<II", 1, 2))

    def test_generated_marker_is_read_from_rom_and_rendered_exactly(self):
        generated = self.generate(self.base + self.reset)
        self.assertEqual(generated["reset_abi_version"], 2)
        self.assertTrue(validate_reset_manifest(generated, self.rom))
        self.assertIn("reset_abi=2, reset_abi_address=134217924", self.configure(generated))
        with self.rom.open("r+b") as rom:
            rom.seek(196); rom.write(struct.pack("<I", 1))
        self.assertEqual(self.generate(self.base + self.reset)["reset_abi_version"], 1)
        with self.assertRaises(ValueError): validate_reset_manifest(generated, self.rom)

    def test_missing_marker_duplicate_allocation_and_wrong_rom_capability_refuse(self):
        marker, mailbox = self.reset.splitlines(keepends=True)
        for symbols in (marker, mailbox, self.reset + marker, self.reset + mailbox,
                        self.reset.replace("00000080", "0000007c"),
                        self.reset.replace("02023000", "02021000")):
            with self.subTest(symbols=symbols), self.assertRaises(ValueError):
                self.generate(self.base + symbols)
        with self.rom.open("r+b") as rom:
            rom.seek(196); rom.write(struct.pack("<I", 3))
        with self.assertRaises(ValueError): self.generate(self.base + self.reset)
