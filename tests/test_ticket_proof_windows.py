"""The Legendary Tickets proof in its Windows mode, without Windows (scripts/multiplayer/native_launcher_ticket_proof.py;
the windows-package job tickets-proof). It ran on Linux only before 2026-11-05: it read the games' save blocks through
/proc/PID/mem and killed the friend's game with SIGKILL, and Windows has neither. On Windows a pointer the game holds is
read with ReadProcessMemory as it is, the friend's crash is TerminateProcess, and the players share the runner's one
desktop. Stand-ins here for the probe's memory and the harness; the games themselves run on the runner."""
from __future__ import annotations

import asyncio
import ctypes
import os
from pathlib import Path
import signal
import struct
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT / "src", ROOT / "scripts" / "multiplayer", ROOT / "scripts" / "windows-runtime"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
import native_launcher_abandon_proof as abandon  # noqa: E402
import native_launcher_battle_proof as harness  # noqa: E402
import native_launcher_ticket_proof as ticket  # noqa: E402
from emerald_multiplayer import legendary_tickets as lt  # noqa: E402
from emerald_multiplayer.world_mailbox import WORLD_INBOUND_OFFSET  # noqa: E402

DELTA = 0x10000                       # Windows loaded the game this far above its preferred base (ASLR)
SYMBOLS = {"gSaveBlock1Ptr": (0x500000, 4), "gSaveBlock2Ptr": (0x500004, 4), "gMultiplayerWorldMailbox": (0x500100, 256),
           "sShownNoticeId": (0x500200, 4)}
BLOCK1, BLOCK2 = 0x2A00000, 0x2A40000  # where the running game holds its save blocks (the pointers' values)


class Memory:
    """ReadProcessMemory of one game (native_windows_process.ProcessMemory): a symbol's address moves by the ASLR delta
    (read), an address the game holds is read as it is (_raw)."""

    delta = DELTA

    def __init__(self, space):
        self.space, self.raw = space, []

    def _raw(self, address, size):
        self.raw.append((address, size))
        for base, data in self.space.items():
            if base <= address and address + size <= base + len(data):
                return bytes(data[address - base:address - base + size])
        raise OSError(299, f"cannot read {size} bytes at {address:#x}")     # ERROR_PARTIAL_COPY: a game gone

    def read(self, address, size):
        return self._raw(address + self.delta, size)


def windows_probe(space):
    """The harness's own WindowsProbe (its mem: the symbol plus the delta), on a stand-in for the game's memory."""
    probe = harness.WindowsProbe.__new__(harness.WindowsProbe)
    probe.symbols, probe.memory, probe.pid = SYMBOLS, Memory(space), 4321
    return probe


def friends_game(notice_id=1, shown=1, text=ticket.BANNER):
    """The friend's game after the word: one Old Sea Map in the Bag, its ship and received flags, the game clear, the
    three Regis, wallet sequence 1; the banner in its world mailbox, shown."""
    block1, block2 = bytearray(lt.SAVE_BLOCK_1_SIZE), bytearray(lt.SAVE_BLOCK_2_SIZE)
    key = 0x5A3C9E71
    struct.pack_into("<I", block2, ticket.ENCRYPTION_KEY, key)
    struct.pack_into("<HH", block1, ticket.BAG + 4 * 3, ticket.TICKET.item, 1 ^ (key & 0xFFFF))
    for flag in (ticket.TICKET.ship_flag, ticket.TICKET.received_flag, lt.FLAG_SYS_GAME_CLEAR, *lt.REGI_FLAGS):
        block1[lt.FLAGS_OFFSET + flag // 8] |= 1 << flag % 8
    struct.pack_into("<H", block1, ticket.WALLET_SEQ, 1)
    mailbox = bytearray(256)
    struct.pack_into("<I", mailbox, WORLD_INBOUND_OFFSET + ticket.NOTICE_ID, notice_id)
    encoded = text.encode("ascii")
    mailbox[WORLD_INBOUND_OFFSET + ticket.NOTICE_TEXT.start:WORLD_INBOUND_OFFSET + ticket.NOTICE_TEXT.start + len(encoded)] \
        = encoded
    return {0x500000 + DELTA: struct.pack("<II", BLOCK1, BLOCK2), 0x500100 + DELTA: bytes(mailbox),
            0x500200 + DELTA: struct.pack("<I", shown), BLOCK1: bytes(block1), BLOCK2: bytes(block2)}


class TicketProofOnWindowsTests(unittest.TestCase):
    def test_a_pointer_the_game_holds_is_read_where_it_points(self):
        probe = windows_probe({BLOCK1: b"\x01\x02\x03\x04"})
        self.assertEqual(ticket.read_at(probe, BLOCK1 + 1, 2), b"\x02\x03")
        self.assertEqual(probe.memory.raw, [(BLOCK1 + 1, 2)])          # as it is: no ASLR delta added to a pointer

    def test_the_friends_ticket_and_banner_are_read_through_read_process_memory(self):
        probe = windows_probe(friends_game())
        self.assertEqual(ticket.live_tickets(probe), dict(bag=1, pc=0, ship=True, received=True, game_clear=True,
                                                          regis=3, wallet_seq=1))
        self.assertIn((BLOCK1, lt.SAVE_BLOCK_1_SIZE), probe.memory.raw)
        self.assertIn((BLOCK2, lt.SAVE_BLOCK_2_SIZE), probe.memory.raw)
        self.assertEqual(ticket.world_notice(probe), dict(id=1, text=ticket.BANNER, shown=1))

    def test_a_game_that_has_ended_stops_its_watcher(self):
        # the friend's game killed (TerminateProcess): ReadProcessMemory fails, and the watcher of its start returns
        proof = ticket.TicketProof(SimpleNamespace())
        proof.harness = SimpleNamespace(started=0.0)
        gone = windows_probe({})
        asyncio.run(asyncio.wait_for(proof.watch("rejoin", 1, gone), 5))
        self.assertEqual(proof.seen[1], [])

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux reads a game's memory through /proc/PID/mem")
    def test_linux_reads_through_proc_mem_as_before(self):
        # A NativeProbe has no ReadProcessMemory: the address is read from /proc/PID/mem (this very process here).
        data = ctypes.create_string_buffer(b"Old Sea Map\0", 12)
        probe = harness.NativeProbe.__new__(harness.NativeProbe)
        probe.pid = os.getpid()
        self.assertEqual(ticket.read_at(probe, ctypes.addressof(data), 12), b"Old Sea Map\0")

    def test_the_friends_crash_is_terminate_process_on_windows_and_sigkill_on_linux(self):
        killed = []
        stand_in = SimpleNamespace(kill=lambda pid, sig: killed.append((pid, sig)))
        with mock.patch.object(abandon, "os", stand_in), mock.patch.object(abandon, "WINDOWS", True):
            ticket.kill_hard(4321)
        self.assertEqual(killed, [(4321, signal.SIGTERM)])          # os.kill on Windows: TerminateProcess
        if hasattr(signal, "SIGKILL"):
            with mock.patch.object(abandon, "os", stand_in), mock.patch.object(abandon, "WINDOWS", False):
                ticket.kill_hard(4321)
            self.assertEqual(killed[1:], [(4321, signal.SIGKILL)])
        source = Path(ticket.__file__).read_text(encoding="utf-8")
        self.assertIn("kill_hard(game.process.pid)", source)        # step 3, the only kill
        self.assertNotIn("os.kill(", source)
        self.assertNotIn("signal.SIGKILL", source)

    def test_windows_needs_no_display_and_linux_two(self):
        started = []

        async def launcher_proof(args, **options):
            started.append(list(args.display))

        def args(display):
            return SimpleNamespace(display=display, source_a=Path("tickets-a.sav"), source_b=Path("tickets-b.sav"))
        with mock.patch.object(ticket, "launcher_proof", launcher_proof):
            with mock.patch.object(ticket, "WINDOWS", True):
                asyncio.run(ticket.run(args(None)))
            self.assertEqual(started, [["desktop-0", "desktop-1"]])  # the runner's one desktop: names for the records
            with mock.patch.object(ticket, "WINDOWS", False):
                for display in (None, [":96"]):
                    with self.subTest(display=display), self.assertRaises(AssertionError):
                        asyncio.run(ticket.run(args(display)))
                asyncio.run(ticket.run(args([":96", ":97"])))
        self.assertEqual(started[1:], [[":96", ":97"]])

    def test_the_windows_harness_arguments_are_taken(self):
        seen = []
        argv = ["native_launcher_ticket_proof.py", "--game", "pokeemerald-mp.exe", "--sdl", "SDL2.dll", "--rom",
                "pokedev.gba", "--manifest", "manifest.json", "--pe-symbols", "pokeemerald-mp.nm.txt", "--sizes",
                "pokeemerald-mp.sizes.txt", "--slow", "1.5", "--source-a", "a.sav", "--source-b", "b.sav", "--output",
                "out/multiplayer-proof/tickets"]
        with mock.patch.object(ticket, "run", seen.append), mock.patch.object(ticket.asyncio, "run", lambda value: None), \
                mock.patch.object(sys, "argv", argv):
            ticket.main()
        (args,) = seen
        self.assertEqual((args.pe_symbols, args.sizes, args.sdl, args.display, args.slow),
                         (Path("pokeemerald-mp.nm.txt"), Path("pokeemerald-mp.sizes.txt"), Path("SDL2.dll"), None, 1.5))


if __name__ == "__main__":
    unittest.main()
