"""ELF-derived diagnostic channel metadata; these fixtures are not game ROMs."""
import unittest

from emerald_multiplayer.battle_manifest import BATTLE_FIELDS, validate_battle_manifest
import test_save_manifest as fixtures


class BattleManifestTests(unittest.TestCase):
    tearDown = fixtures.SaveManifestTests.tearDown
    generate = fixtures.SaveManifestTests.generate
    configure = fixtures.SaveManifestTests.configure

    def setUp(self):
        fixtures.SaveManifestTests.setUp(self)
        self.base = ("02021000 00000200 B gMultiplayerSaveMailbox\n"
                     "080000c0 00000004 R gMultiplayerOwnershipAbi\n"
                     "080000c4 00000004 R gMultiplayerTradeAbiVersion\n")
        self.battle = ("080000c8 00000004 R gMultiplayerBattleAbiVersion\n"
                       "02022000 00000200 B gMultiplayerBattleMailbox\n")
        with self.rom.open("r+b") as rom:
            rom.seek(192)
            rom.write(b"\x01\0\0\0" * 3)

    def test_battle_generated_marker_allocation_and_configuration(self):
        generated = self.generate(self.base + self.battle)
        self.assertTrue(validate_battle_manifest(generated, self.rom))
        self.assertEqual(generated["battle_mailbox_address"], 0x02022000)
        self.assertIn("battle_address=33693696, battle_size=512", self.configure(generated))
        self.assertIn("battle_abi=1, battle_abi_address=134217928", self.configure(generated))

    def test_native_version_is_derived_from_rom_marker_and_must_match_it(self):
        with self.rom.open("r+b") as rom:
            rom.seek(200)
            rom.write(b"\x02\0\0\0")
        generated = self.generate(self.base + self.battle)
        self.assertEqual(generated["battle_abi_version"], 2)
        self.assertTrue(validate_battle_manifest(generated, self.rom))
        self.assertIn("battle_abi=2, battle_abi_address=134217928", self.configure(generated))
        for version in (1, 3, True):
            with self.assertRaises(ValueError):
                validate_battle_manifest({**generated, "battle_abi_version": version}, self.rom)
        with self.rom.open("r+b") as rom:
            rom.seek(200)
            rom.write(b"\x03\0\0\0")
        multi = self.generate(self.base + self.battle)
        self.assertEqual(multi["battle_abi_version"], 3)
        self.assertTrue(validate_battle_manifest(multi, self.rom))
        self.assertIn("battle_abi=3, battle_abi_address=134217928", self.configure(multi))
        with self.assertRaises(ValueError):
            validate_battle_manifest({**multi, "battle_abi_version": 2}, self.rom)
        with self.rom.open("r+b") as rom:
            rom.seek(200)
            rom.write(b"\x04\0\0\0")
        with self.assertRaises(ValueError):
            self.generate(self.base + self.battle)

    def test_missing_capability_fields_and_dependencies_refused(self):
        generated = self.generate(self.base + self.battle)
        for key in BATTLE_FIELDS | {"ownership_abi_version", "trade_abi_version", "save_abi_version", "save_profile", "mailbox_address"}:
            broken = dict(generated)
            del broken[key]
            with self.subTest(field=key), self.assertRaises(ValueError):
                validate_battle_manifest(broken, self.rom)

    def test_wrong_types_sizes_alignment_and_overlap_refused(self):
        generated = self.generate(self.base + self.battle)
        for changes in ({"battle_abi_version": True}, {"battle_abi_version": 2},
                        {"battle_mailbox_size": 516}, {"battle_mailbox_address": True},
                        {"battle_mailbox_address": 0x02022001}, {"battle_mailbox_address": 0x0203FE04},
                        {"battle_mailbox_address": 0x0202007C}, {"battle_mailbox_address": 0x020211FC},
                        {"battle_abi_address": True}, {"battle_abi_address": 0x080000CA},
                        {"battle_abi_address": 0x0A000000}, {"rom_size": True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_battle_manifest({**generated, **changes}, self.rom)

    def test_no_invented_constant_even_with_matching_rom_hash(self):
        generated = self.generate(self.base + self.battle)
        with self.assertRaises(ValueError):
            validate_battle_manifest({**generated, "battle_abi_address": 0x080000CC}, self.rom)

    def test_elf_requires_exactly_one_marker_and_allocated_channel(self):
        marker, channel = self.battle.splitlines(keepends=True)
        for extra in (marker, channel, self.battle + marker, self.battle + channel,
                      self.battle.replace("00000004", "00000008"),
                      self.battle.replace("00000200", "000001FC"),
                      self.battle.replace("02022000", "02021000")):
            with self.subTest(symbols=extra), self.assertRaises(ValueError):
                self.generate(self.base + extra)
        with self.assertRaises(ValueError):
            self.generate(self.battle)

    def test_absent_capability_remains_optional(self):
        self.assertFalse(validate_battle_manifest(self.generate(self.base), self.rom))
