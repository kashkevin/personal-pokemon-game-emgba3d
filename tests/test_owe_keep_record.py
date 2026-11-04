"""KNOWN_ISSUES MS-145: the kept shiny and Legendary wild Pokemon in the save.

The player's own game keeps a shiny or Legendary wild Pokemon on its map until it is caught or knocked out (MS-79, MS-144).
That list was in the game's memory only; since 2026-11-04 it is a 140-byte record after the co-op result record (engine
struct MPOweKeepRecord, SaveBlock3 bytes 1188-1327), so a game closed and started again puts each one back. The launcher's
save checker reads it like the other records: all zeros (every older save, and every save keeping none) is none; anything
but a sealed record within the game's own bounds is refused, never repaired."""
from __future__ import annotations

import struct
import unittest
import zlib

from emerald_multiplayer.character_transfer import detach_from_world
from emerald_multiplayer.flash import (
    COOP_RESULT_OFFSET, COOP_RESULT_SIZE, LAYOUT_ID, OWE_KEEP_MAGIC, OWE_KEEP_OFFSET, OWE_KEEP_SIZE, OWNERSHIP_LAYOUT_ID,
    SAVE_BLOCK_3_CHUNK_SIZE, SAVE_BLOCK_3_FULL_SIZE, FlashError, inspect_flash, parse_owe_keep,
)
import test_flash
from test_flash import make_flash
from test_ownership import make_ownership_flash

MON, SHINY, FEMALE = 1 << 14, 1 << 13, 1 << 12
ROUTE101 = (0, 16)


def entry(species=263, bits=SHINY, *, where=(17, 20), map_=ROUTE101, elevation=3, movement=2, level=5 | 0x80,
          age=0, spare=0, flag=MON) -> bytes:
    return struct.pack("<Hhh8BH", flag | bits | species, where[0], where[1], map_[0], map_[1], 7, elevation, movement,
                       level, 4, age, spare)


def keep_record(entries=None, *, count=None, magic=OWE_KEEP_MAGIC, version=1, reserved=0, tail=b"") -> bytes:
    entries = [entry(age=1), entry(380, 0, where=(30, 41), map_=(0, 35), age=0, level=40 | 0x80),
               entry(263, SHINY | FEMALE, where=(9, 12), map_=(0, 17), age=2)] if entries is None else entries
    body = struct.pack("<IBBH", magic, version, len(entries) if count is None else count, reserved)
    body += b"".join(entries) + bytes(16 * (8 - len(entries)))
    body = (body[:136 - len(tail)] + tail) if tail else body
    return body + struct.pack("<I", zlib.crc32(body))


def with_keep(record: bytes, data: bytes | None = None) -> bytes:
    return test_flash.FlashTests._put_block3(make_flash() if data is None else data, OWE_KEEP_OFFSET, record)


class KeepRecordTests(unittest.TestCase):
    def test_the_record_follows_the_co_op_result_and_fits_saveblock3(self):
        self.assertEqual((COOP_RESULT_OFFSET + COOP_RESULT_SIZE, OWE_KEEP_OFFSET, OWE_KEEP_SIZE, SAVE_BLOCK_3_FULL_SIZE),
                         (1188, 1188, 140, 1328))
        self.assertLessEqual(SAVE_BLOCK_3_FULL_SIZE, 14 * SAVE_BLOCK_3_CHUNK_SIZE)   # 1624: SaveBlock3's room in a bank
        self.assertEqual(len(keep_record()), OWE_KEEP_SIZE)

    def test_none_kept_and_older_saves(self):
        self.assertEqual(parse_owe_keep(bytes(OWE_KEEP_SIZE)), 0)
        inspect_flash(make_flash())
        inspect_flash(make_ownership_flash(), save_profile=OWNERSHIP_LAYOUT_ID)

    def test_a_sealed_record_is_accepted_in_both_profiles(self):
        self.assertEqual(parse_owe_keep(keep_record()), 3)
        self.assertEqual(parse_owe_keep(keep_record([entry(1572, age=a) for a in range(8)])), 8)   # a full list
        self.assertEqual(parse_owe_keep(keep_record([entry(1, 0, where=(-5, 300), elevation=15, movement=0x58)])), 1)
        inspect_flash(with_keep(keep_record()))
        inspect_flash(with_keep(keep_record(), make_ownership_flash()), save_profile=OWNERSHIP_LAYOUT_ID)

    def test_anything_else_is_refused(self):
        sealed = keep_record()
        cases = {
            "magic": keep_record(magic=OWE_KEEP_MAGIC + 1),
            "version": keep_record(version=2),
            "reserved": keep_record(reserved=1),
            "count zero with entries": keep_record(count=0),
            "count past the entries": keep_record(count=4),
            "count above eight": keep_record([entry()] * 8, count=9),
            "an object that is no Pokemon": keep_record([entry(flag=0)]),
            "no species": keep_record([entry(0)]),
            "a species past the table": keep_record([entry(1573)]),
            "a map group past the game's": keep_record([entry(map_=(75, 0))]),
            "elevation 16": keep_record([entry(elevation=16)]),
            "a movement the game has not": keep_record([entry(movement=0x59)]),
            "age eight": keep_record([entry(age=8)]),
            "a spare byte": keep_record([entry(spare=1)]),
            "a stray byte after the last entry": keep_record(tail=b"\1"),
            "crc": sealed[:136] + b"\0\0\0\0",
            "a changed byte": sealed[:20] + bytes([sealed[20] ^ 4]) + sealed[21:],
        }
        for name, record in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(FlashError):
                    parse_owe_keep(record)
                with self.assertRaises(FlashError):
                    inspect_flash(with_keep(record))
        with self.assertRaisesRegex(FlashError, "wrong size"):
            parse_owe_keep(bytes(139))
        with self.assertRaisesRegex(FlashError, "kept wild Pokemon record"):
            inspect_flash(test_flash.FlashTests._put_block3(make_flash(), OWE_KEEP_OFFSET, b"\1"))
        with self.assertRaisesRegex(FlashError, "padding"):
            inspect_flash(test_flash.FlashTests._put_block3(with_keep(keep_record()), SAVE_BLOCK_3_FULL_SIZE, b"\1"))

    def test_a_character_leaving_its_world_keeps_its_kept_pokemon(self):
        owned = with_keep(keep_record(), make_ownership_flash(records=(("party:0", 1), ("box:3:14", 27))))
        detached = detach_from_world(owned).payload
        snapshot = inspect_flash(detached, save_profile=LAYOUT_ID)
        bank = snapshot.metadata.bank
        sections = {}
        for index in range(14):
            sector = detached[(bank * 14 + index) * 4096:(bank * 14 + index + 1) * 4096]
            sections[struct.unpack_from("<H", sector, 4084)[0]] = sector[3968:3968 + SAVE_BLOCK_3_CHUNK_SIZE]
        full3 = b"".join(sections[i] for i in range(14))
        self.assertEqual(full3[OWE_KEEP_OFFSET:SAVE_BLOCK_3_FULL_SIZE], keep_record())


if __name__ == "__main__":
    unittest.main()
