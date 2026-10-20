"""ELF-derived diagnostic channel metadata; these fixtures are not game ROMs."""
import unittest
from unittest.mock import patch

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

    def test_execution_uses_only_exact_compiler_string_table_and_complete_optional_metadata(self):
        with self.rom.open("r+b") as rom:
            rom.seek(200); rom.write(b"\x03\0\0\0")
            rom.seek(0x300); rom.write(bytes(721 * 4))
        symbol = "08000300 00000b44 R gBattleStringsTable\n"
        generated = self.generate(self.base + self.battle + symbol)
        self.assertEqual(generated["battle_string_table_address"], 0x08000300)
        self.assertEqual(generated["battle_execution_abi_version"], 1)
        self.assertTrue(validate_battle_manifest(generated, self.rom))
        for changes in ({"battle_string_table_size": 4}, {"battle_string_table_address": True},
                        {"battle_string_table_address": 0x09000000}, {"battle_execution_abi_version": True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_battle_manifest({**generated, **changes}, self.rom)
        for key in ("battle_execution_abi_version", "battle_string_table_address", "battle_string_table_size"):
            broken = dict(generated); del broken[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_battle_manifest(broken, self.rom)
        with self.assertRaises(ValueError):
            self.generate(self.base + self.battle + symbol + symbol)
        with self.rom.open("r+b") as rom:
            rom.seek(0x300); rom.write(b"\xff\xff\xff\xff")
        with self.assertRaises(ValueError):
            validate_battle_manifest(generated, self.rom)


class CoopAndWorldManifestTests(unittest.TestCase):
    """Co-op Gym (native phase 4) and EMW1 shared-world markers from the ELF."""
    tearDown = fixtures.SaveManifestTests.tearDown
    generate = fixtures.SaveManifestTests.generate
    configure = fixtures.SaveManifestTests.configure

    def setUp(self):
        BattleManifestTests.setUp(self)
        with self.rom.open("r+b") as rom:
            rom.seek(200)
            rom.write(b"\x03\0\0\0")  # native ABI3 channel
            rom.write(b"\x01\0\0\0")  # 204: co-op Gym marker
            rom.write(b"\x01\0\0\0")  # 208: EMW1 marker
        self.coop = "080000cc 00000004 R gMultiplayerBattleCoopAbiVersion\n"
        self.world = ("080000d0 00000004 R gMultiplayerWorldAbiVersion\n"
                      "02023000 00000100 B gMultiplayerWorldMailbox\n")

    def test_coop_marker_requires_abi3_channel_and_exact_rom_value(self):
        from emerald_multiplayer.battle_manifest import COOP_FIELDS
        generated = self.generate(self.base + self.battle + self.coop)
        self.assertEqual({key: generated[key] for key in COOP_FIELDS},
                         {"battle_coop_abi_version": 1, "battle_coop_abi_address": 0x080000CC})
        self.assertTrue(validate_battle_manifest(generated, self.rom))
        for changes in ({"battle_coop_abi_version": 2}, {"battle_coop_abi_address": 0x080000CE},
                        {"battle_coop_abi_address": 0x080000C8}, {"battle_abi_version": 2}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_battle_manifest({**generated, **changes}, self.rom)
        partial = dict(generated)
        del partial["battle_coop_abi_address"]
        with self.assertRaises(ValueError):
            validate_battle_manifest(partial, self.rom)
        with self.assertRaises(ValueError):
            self.generate(self.base + self.coop)  # no native battle channel

    def generate_native(self, extra, native):
        with patch.object(fixtures.generator.subprocess, "check_output", return_value=self.symbols + extra):
            return fixtures.generator.generate(self.rom, self.elf, "fixture-nm", "b" * 40, native_symbols=native)

    def test_free_for_all_marker_comes_from_the_native_executable_and_needs_the_abi3_channel(self):
        from emerald_multiplayer.battle_manifest import FFA_FIELDS
        native = "00bd2770 00000004 R gMultiplayerBattleFfaAbiVersion\n"
        plain = self.generate(self.base + self.battle)
        generated = self.generate_native(self.base + self.battle, native)
        self.assertFalse(FFA_FIELDS & set(plain))                   # the GBA ELF alone never advertises it
        self.assertEqual({key: generated[key] for key in FFA_FIELDS}, {"battle_ffa_abi_version": 1})
        self.assertTrue(validate_battle_manifest(generated, self.rom))
        for changes in ({"battle_ffa_abi_version": 2}, {"battle_ffa_abi_version": True}, {"battle_abi_version": 2}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_battle_manifest({**generated, **changes}, self.rom)
        with self.assertRaises(ValueError):
            self.generate_native(self.base, native)                  # a marker without the native battle channel
        for bad in ("00bd2770 00000008 R gMultiplayerBattleFfaAbiVersion\n", native + native):
            with self.assertRaises(ValueError):
                self.generate_native(self.base + self.battle, bad)

    def test_the_1v1v1_marker_comes_from_the_native_executable_and_needs_the_free_for_all(self):
        """Update 32: the three-player free-for-all (phase 6) is the free-for-all with its fourth place empty."""
        from emerald_multiplayer.battle_manifest import FFA3_FIELDS
        ffa = "00bd2770 00000004 R gMultiplayerBattleFfaAbiVersion\n"
        ffa3 = "00bd2774 00000004 R gMultiplayerBattleFfa3AbiVersion\n"
        generated = self.generate_native(self.base + self.battle, ffa + ffa3)
        self.assertEqual({key: generated[key] for key in FFA3_FIELDS}, {"battle_ffa3_abi_version": 1})
        self.assertTrue(validate_battle_manifest(generated, self.rom))
        self.assertFalse(FFA3_FIELDS & set(self.generate_native(self.base + self.battle, ffa)))
        for changes in ({"battle_ffa3_abi_version": 2}, {"battle_ffa3_abi_version": True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_battle_manifest({**generated, **changes}, self.rom)
        without_ffa = dict(generated); del without_ffa["battle_ffa_abi_version"]
        with self.assertRaises(ValueError):
            validate_battle_manifest(without_ffa, self.rom)
        for bad in (ffa3, ffa + "00bd2774 00000008 R gMultiplayerBattleFfa3AbiVersion\n", ffa + ffa3 + ffa3):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.generate_native(self.base + self.battle, bad)

    def test_the_windows_games_markers_are_read_from_mingw_nm_which_prints_no_size(self):
        """windows-package.yml generates the Windows manifest from `i686-w64-mingw32-nm --print-size` of the Windows game. For a
        PE executable that prints no size column (these are its real lines, engine 3f06fd20), and requiring one dropped the
        free-for-all, rival and presence-detail markers from every Windows manifest: the companion then refused the game's pose
        whenever it was off the field and closed its link (the installed play check, run 39298566536)."""
        mingw = ("00c0449c R _gMultiplayerBattleFfaAbiVersion\n"
                 "00c04b28 R _gMultiplayerPresenceDetailAbiVersion\n"
                 "00c04e94 R _gMultiplayerRivalAbiVersion\n")
        generated = self.generate_native(self.base + self.battle + self.world, mingw)
        self.assertEqual({key: generated.get(key) for key in ("battle_ffa_abi_version", "rival_abi_version",
                                                              "presence_detail_abi_version")},
                         {"battle_ffa_abi_version": 1, "rival_abi_version": 1, "presence_detail_abi_version": 1})
        linux = ("0882468c 00000004 R gMultiplayerBattleFfaAbiVersion\n08824b5c 00000004 R gMultiplayerPresenceDetailAbiVersion\n"
                 "08824c4c 00000004 R gMultiplayerRivalAbiVersion\n")
        self.assertEqual(self.generate_native(self.base + self.battle + self.world, linux), generated)
        for bad in (mingw + "00c0449c R _gMultiplayerBattleFfaAbiVersion\n",               # two markers
                    "00c0449c 00000008 R _gMultiplayerBattleFfaAbiVersion\n"):            # a size, and not four bytes
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.generate_native(self.base + self.battle + self.world, bad)
        self.assertNotIn("battle_ffa_abi_version",                                      # code, not data: not a marker
                         self.generate_native(self.base + self.battle, "00c0449c T _gMultiplayerBattleFfaAbiVersion\n"))

    def test_world_marker_and_mailbox_are_generated_and_verified(self):
        from emerald_multiplayer.world_mailbox import validate_world_manifest
        generated = self.generate(self.base + self.battle + self.world)
        self.assertEqual((generated["world_abi_version"], generated["world_abi_address"],
                          generated["world_mailbox_address"], generated["world_mailbox_size"]),
                         (1, 0x080000D0, 0x02023000, 256))
        self.assertTrue(validate_world_manifest(generated, self.rom))
        with self.assertRaises(ValueError):
            self.generate(self.base + self.battle + "080000d0 00000004 R gMultiplayerWorldAbiVersion\n")
        with self.assertRaises(ValueError):
            self.generate(self.base + self.battle + "080000d0 00000004 R gMultiplayerWorldAbiVersion\n"
                          "02021100 00000100 B gMultiplayerWorldMailbox\n")  # overlaps the save mailbox
