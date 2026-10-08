from dataclasses import replace
import struct
import unittest

from emerald_multiplayer.menu_mailbox import MenuRequest, pack_screen, unpack_screen, validate_menu_manifest, FIELDS
from emerald_multiplayer.player_menu import MenuRow, MenuScreen
import test_save_manifest as fixtures


class MenuCodecTests(unittest.TestCase):
    def screen(self):
        return MenuScreen(12, "Players", "Connected: 4/4", tuple(MenuRow(i + 1, f"Choice {i}") for i in range(6)), 7)

    def test_request_and_full_screen_roundtrip(self):
        for request in (MenuRequest(1, 0, 0, 1), MenuRequest(2, 12, 6, 2), MenuRequest(3, 12, 0, 3)):
            self.assertEqual(len(request.pack()), 16)
            self.assertEqual(MenuRequest.unpack(request.pack()), request)
        for close in (False, True):
            payload = pack_screen(2, self.screen(), close=close)
            self.assertEqual(len(payload), 240)
            self.assertEqual(unpack_screen(payload), (2, self.screen(), close))

    def test_malformed_request_never_selects(self):
        valid = MenuRequest(1, 2, 1, 2)
        for changes in (dict(sequence=0), dict(sequence=True), dict(kind=0), dict(action=8),
                        dict(action=0), dict(screen=0), dict(kind=1), dict(kind=3)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(valid, **changes).pack()
        for payload in (valid.pack()[:-1], valid.pack() + b"\0", valid.pack()[:-1] + b"\1"):
            with self.assertRaises(ValueError): MenuRequest.unpack(payload)

    def test_text_control_codes_padding_and_oversized_rows_rejected(self):
        for changes in (dict(title="A" * 24), dict(title="Hi\xff"), dict(status="Hello\n"),
                        dict(rows=(MenuRow(1, "x\0x"),)), dict(rows=(MenuRow(2, "Wrong slot"),)),
                        dict(back=6), dict(revision=False)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                pack_screen(1, replace(self.screen(), **changes))
        raw = pack_screen(1, self.screen())
        for offset, value in ((8, 2), (9, 7), (239, 1), (35, 65), (69, 1)):
            bad = bytearray(raw); bad[offset] = value
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                unpack_screen(bytes(bad))

    def test_disabled_rows_and_home_close_are_explicit(self):
        screen = MenuScreen(1, "Players", "Waiting", (MenuRow(0, "Trainer (6)"),), 0)
        self.assertEqual(unpack_screen(pack_screen(8, screen)), (8, screen, False))
        raw = bytearray(pack_screen(8, screen)); raw[100] = 1
        with self.assertRaises(ValueError): unpack_screen(bytes(raw))


class MenuManifestTests(unittest.TestCase):
    tearDown = fixtures.SaveManifestTests.tearDown
    generate = fixtures.SaveManifestTests.generate
    configure = fixtures.SaveManifestTests.configure

    def setUp(self):
        fixtures.SaveManifestTests.setUp(self)
        self.menu_symbols = "080000c0 00000004 R gMultiplayerMenuAbiVersion\n02022000 00000200 B gMultiplayerMenuMailbox\n"
        with self.rom.open("r+b") as rom:
            rom.seek(192); rom.write(b"\x01\0\0\0")

    def test_elf_allocation_and_rom_marker_are_both_required(self):
        manifest = self.generate(self.menu_symbols)
        self.assertTrue(validate_menu_manifest(manifest, self.rom))
        self.assertIn("menu_abi=1", self.configure(manifest))
        self.assertIn("menu_address=33693696", self.configure(manifest))
        self.assertFalse(validate_menu_manifest(self.generate(""), self.rom))
        for key in FIELDS:
            bad = dict(manifest); del bad[key]
            with self.subTest(key=key), self.assertRaises(ValueError): validate_menu_manifest(bad, self.rom)

    def test_marker_and_every_memory_overlap_fail_closed(self):
        manifest = self.generate(self.menu_symbols)
        for changes in (dict(menu_abi_version=True), dict(menu_mailbox_size=516),
                        dict(menu_mailbox_address=0x02020000), dict(menu_mailbox_address=0x0203FE04),
                        dict(menu_abi_address=0x080000c4), dict(save_mailbox_address=0x02022000),
                        dict(battle_mailbox_address=0x02021f00), dict(save_window_address=0x02021fff)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_menu_manifest(manifest | changes, self.rom)
