"""The launcher proofs' Windows mode, without Windows: the executable header it checks a loaded game against, the symbol
tables it reads memory through (saved by the build before the strip, sizes from the Linux build) and the girl's presses
of the short introduction (scripts/multiplayer/make_intro_saves.py)."""
from __future__ import annotations

from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "src", ROOT / "scripts" / "multiplayer", ROOT / "scripts" / "windows-runtime"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import make_intro_saves  # noqa: E402
import native_launcher_battle_proof as harness  # noqa: E402
from native_trade_proof import parse_nm_sizes, parse_pe_symbols  # noqa: E402
import native_windows_process  # noqa: E402
from native_launcher_three_player_proof import ThreePlayerProof  # noqa: E402

PE_ROWS = """\
00401000 T _main
00401200 t _HandleInputChooseAction
00402000 T _CB2_StarterChoose
00405400 t _HandleInputChooseAction
00500000 b _sMultiplayerMenuActive
00500001 b _sMultiplayerMenuWaiting
00500004 b _sMultiplayerMenuScreen
00500104 B _gMain
00500200 B _gTasks
"""
LINUX_SIZES = """\
08100000 00000001 b sMultiplayerMenuActive
08100001 00000001 b sMultiplayerMenuWaiting
08100004 00000100 b sMultiplayerMenuScreen
08100104 00000040 B gMain
08100200 00000280 B gTasks
08048000 00000020 T CB2_StarterChoose
"""


def pe_bytes(base=0x400000, stamp=0x5F5E1000, size=0x200000, magic=0x10B):
    data = bytearray(512)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<I", data, 0x80 + 8, stamp)
    optional = 0x80 + 24
    struct.pack_into("<H", data, optional, magic)
    struct.pack_into("<I", data, optional + 28, base)
    struct.pack_into("<I", data, optional + 56, size)
    return bytes(data)


class WindowsModeTests(unittest.TestCase):
    def test_pe_header_gives_the_preferred_base_time_stamp_and_image_size(self):
        self.assertEqual(native_windows_process.pe_header(pe_bytes()), (0x400000, 0x5F5E1000, 0x200000))
        with self.assertRaises(ValueError):
            native_windows_process.pe_header(b"ELF" + pe_bytes()[3:])
        with self.assertRaises(ValueError):
            native_windows_process.pe_header(pe_bytes(magic=0x20B))       # a 64-bit executable is not the game

    def test_keys_are_the_games_defaults(self):
        self.assertEqual(set(native_windows_process.VK), set(harness.KEYS.values()))
        self.assertTrue({native_windows_process.VK[k] for k in ("Up", "Down", "Left", "Right")}
                        <= native_windows_process.EXTENDED)

    def test_symbols_from_the_saved_tables(self):
        sizes = parse_nm_sizes(LINUX_SIZES)
        self.assertEqual(sizes["gMain"], (0x08100104, 0x40))
        symbols = parse_pe_symbols(PE_ROWS, sizes, ("sMultiplayerMenuScreen", "gMain", "CB2_StarterChoose"))
        self.assertEqual(symbols, {"sMultiplayerMenuScreen": (0x500004, 0x100), "gMain": (0x500104, 0x40),
                                   "CB2_StarterChoose": (0x402000, 0x20)})
        self.assertEqual(harness.function_addresses_in(PE_ROWS, "HandleInputChooseAction"),
                         frozenset((0x401200, 0x405400)))

    def test_a_size_that_does_not_fit_the_windows_layout_is_refused(self):
        sizes = parse_nm_sizes(LINUX_SIZES.replace("00000040 B gMain", "00000200 B gMain"))
        with self.assertRaises(ValueError):
            parse_pe_symbols(PE_ROWS, sizes, ("gMain",))

    def test_the_proofs_extra_names_are_optional_but_needed_ones_are_not(self):
        sizes = parse_nm_sizes(LINUX_SIZES.replace("00000040 B gMain", "00000200 B gMain"))
        table = harness.pe_symbol_table(PE_ROWS, sizes)               # gMain (extra) does not fit: left out
        self.assertNotIn("gMain", table)
        self.assertEqual(table["sMultiplayerMenuScreen"], (0x500004, 0x100))
        self.assertEqual(table["CB2_StarterChoose"], (0x402000, 0x20))
        sizes = parse_nm_sizes(LINUX_SIZES.replace("00000100 b sMultiplayerMenuScreen", "00000200 b sMultiplayerMenuScreen"))
        with self.assertRaises(ValueError):                           # a needed one that does not fit stops the proof
            harness.pe_symbol_table(PE_ROWS, sizes)

    def test_code_pointers_are_read_back_as_the_builds_own_addresses(self):
        # Windows loaded the game 0x10000 above its preferred base (ASLR): a callback the game holds is moved by the
        # same delta as the reads, so it is moved back before it is compared with a symbol (the runner's claims waited
        # for CB2_StarterChoose until they timed out). A Linux game (or Wine) runs where it was linked.
        windows = harness.WindowsProbe.__new__(harness.WindowsProbe)
        windows.memory = SimpleNamespace(delta=0x10000)
        self.assertEqual(windows.code(0x412000), 0x402000)
        self.assertEqual(windows.code(0), 0)
        linux = harness.NativeProbe.__new__(harness.NativeProbe)
        self.assertEqual(linux.code(0x402000), 0x402000)
        gmain = (0x401000).to_bytes(4, "little") + (0x412000).to_bytes(4, "little")
        windows.mem = lambda name, size=None, offset=0: gmain if name == "gMain" else b""
        self.assertEqual(ThreePlayerProof.screen(windows), 0x402000)

    def test_the_girls_short_introduction(self):
        boy = ([f"{f}:A" for f in range(400, 801, 100)] + ["980:A", "1100:START", "1140:A", "1300:A", "1360:A"]
               + [f"{1500 + i * 45}:A" for i in range(24)])
        girl = make_intro_saves.girl(boy)
        self.assertEqual(girl[:5], boy[:5])
        self.assertEqual(girl[5:7], ["970:DOWN", "1010:A"])
        self.assertEqual(girl[7:], boy[6:])
        self.assertNotIn("980:A", girl)


if __name__ == "__main__":
    unittest.main()
