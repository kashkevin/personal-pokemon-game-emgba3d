"""A co-op battle's result waiting for its script (docs/owner-decisions.md 4-5, the owner's instruction of 2026-11-04).

When a co-op battle ends, each game keeps its own result (the Gym or ladder, the outcome, and the experience it awards) until
its result script runs; that waiting result is now in the save, in a 76-byte record after the TM record (engine struct
MPCoopResultRecord, SaveBlock3 bytes 1112-1187), so a game that closes before the script runs it after the reload, once.
The launcher's save checker reads it like the Tower and TM records: all zeros (every older save, and every save with nothing
waiting) is no result; anything but a sealed record is refused, never repaired."""
from __future__ import annotations

import struct
import unittest
import zlib

from emerald_multiplayer.character_transfer import detach_from_world
from emerald_multiplayer.flash import (
    COOP_RESULT_MAGIC, COOP_RESULT_OFFSET, COOP_RESULT_SIZE, LAYOUT_ID, OWE_KEEP_OFFSET, OWNERSHIP_LAYOUT_ID, SAVE_BLOCK_3_CHUNK_SIZE,
    SAVE_BLOCK_3_FULL_SIZE, TM_RECORD_OFFSET, TM_RECORD_SIZE, CoopResult, FlashError, inspect_flash, parse_coop_result,
)
import test_flash
from test_flash import make_flash
from test_ownership import make_ownership_flash

WON, LOST = 1, 2
RUSTBORO = 1
LADDER = 0x80000000 | 0x40000000 | (100 << 20) | (200 << 10) | 30   # a ladder code with experience allowed


def coop_result(code=RUSTBORO, outcome=WON, kos=((74, 12, 1, 0x3F), (299, 15, 1, 0x3B), (296, 14, 3, 0x3B)), *,
                cap=0, count=None, magic=COOP_RESULT_MAGIC, version=1, tamper=None) -> bytes:
    """species, level, faced, alive for each defeated Pokemon (Geodude, Nosepass, Makuhita by default)."""
    species = [0] * 12
    levels, faced, alive = bytearray(12), bytearray(12), bytearray(12)
    for index, (kind, level, face, able) in enumerate(kos):
        species[index], levels[index], faced[index], alive[index] = kind, level, face, able
    body = bytearray(struct.pack("<IBBBBI12H12s12s12s", magic, version, outcome, len(kos) if count is None else count,
                                 cap, code, *species, bytes(levels), bytes(faced), bytes(alive)))
    if tamper:
        tamper(body)
    return bytes(body) + struct.pack("<I", zlib.crc32(bytes(body)))


def with_coop_result(record: bytes, data: bytes | None = None) -> bytes:
    return test_flash.FlashTests._put_block3(make_flash() if data is None else data, COOP_RESULT_OFFSET, record)


class CoopResultRecordTests(unittest.TestCase):
    def test_the_record_follows_the_tm_record_and_fits_saveblock3(self):
        self.assertEqual((TM_RECORD_OFFSET + TM_RECORD_SIZE, COOP_RESULT_OFFSET, COOP_RESULT_SIZE, OWE_KEEP_OFFSET),
                         (1112, 1112, 76, 1188))                     # the kept wild Pokemon follow it (MS-145)
        self.assertLessEqual(SAVE_BLOCK_3_FULL_SIZE, 14 * SAVE_BLOCK_3_CHUNK_SIZE)   # 1624: SaveBlock3's room in a bank
        self.assertEqual(len(coop_result()), COOP_RESULT_SIZE)

    def test_nothing_waiting_and_older_saves_have_none(self):
        self.assertIsNone(parse_coop_result(bytes(COOP_RESULT_SIZE)))
        inspect_flash(make_flash())
        inspect_flash(make_ownership_flash(), save_profile=OWNERSHIP_LAYOUT_ID)

    def test_a_sealed_record_is_accepted_in_both_profiles(self):
        self.assertEqual(parse_coop_result(coop_result()), CoopResult(RUSTBORO, WON, 3))
        self.assertEqual(parse_coop_result(coop_result(outcome=LOST, kos=())), CoopResult(RUSTBORO, LOST, 0))  # a loss
        self.assertEqual(parse_coop_result(coop_result(8, kos=((382, 100, 1, 1),) * 12)), CoopResult(8, WON, 12))
        self.assertEqual(parse_coop_result(coop_result(LADDER, LOST, cap=50)), CoopResult(LADDER, LOST, 3))
        inspect_flash(with_coop_result(coop_result()))
        inspect_flash(with_coop_result(coop_result(), make_ownership_flash()), save_profile=OWNERSHIP_LAYOUT_ID)
        # beside the egg queue
        eggs = test_flash.FlashTests._put_block3(make_flash(), 600, test_flash.FlashTests._egg_queue(2))
        inspect_flash(with_coop_result(coop_result(), eggs))

    def test_anything_else_is_refused(self):
        def flip(offset):
            return lambda body: body.__setitem__(offset, body[offset] ^ 1)
        cases = {
            "magic": coop_result(magic=COOP_RESULT_MAGIC + 1),
            "version": coop_result(version=2),
            "no outcome": coop_result(outcome=0),
            "no battle": coop_result(code=0),
            "not a Gym": coop_result(code=9),
            "count above twelve": coop_result(count=13),
            "count below the Pokemon": coop_result(count=2),
            "count above the Pokemon": coop_result(count=4),
            "no species": coop_result(kos=((0, 12, 1, 1),)),
            "a species past the table": coop_result(kos=((1573, 12, 1, 1),)),
            "level 0": coop_result(kos=((74, 0, 1, 1),)),
            "level 101": coop_result(kos=((74, 101, 1, 1),)),
            "a seventh party slot": coop_result(kos=((74, 12, 64, 1),)),
            "crc": coop_result()[:72] + b"\0\0\0\0",
            "a changed byte": (lambda r: r[:40] + bytes([r[40] ^ 2]) + r[41:])(coop_result()),
            "a stray byte": bytes(75) + b"\1",
        }
        cases["the cap changed after sealing"] = coop_result(tamper=None)[:7] + b"\1" + coop_result()[8:]
        for name, record in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(FlashError):
                    parse_coop_result(record)
                with self.assertRaises(FlashError):
                    inspect_flash(with_coop_result(record))
        with self.assertRaisesRegex(FlashError, "wrong size"):
            parse_coop_result(bytes(75))
        # a stray byte where the record lives is refused as a damaged record, not read as one
        with self.assertRaisesRegex(FlashError, "co-op result record"):
            inspect_flash(test_flash.FlashTests._put_block3(make_flash(), COOP_RESULT_OFFSET, b"\1"))
        # what follows the record is the kept wild Pokemon record (a stray byte there is a damaged one), then padding
        with self.assertRaisesRegex(FlashError, "kept wild Pokemon"):
            inspect_flash(test_flash.FlashTests._put_block3(with_coop_result(coop_result()), OWE_KEEP_OFFSET, b"\1"))
        with self.assertRaisesRegex(FlashError, "padding"):
            inspect_flash(test_flash.FlashTests._put_block3(with_coop_result(coop_result()), SAVE_BLOCK_3_FULL_SIZE, b"\1"))

    def test_a_character_leaving_its_world_keeps_its_waiting_result(self):
        owned = with_coop_result(coop_result(), make_ownership_flash(records=(("party:0", 1), ("box:3:14", 27))))
        detached = detach_from_world(owned).payload
        snapshot = inspect_flash(detached, save_profile=LAYOUT_ID)
        bank = snapshot.metadata.bank
        sections = {}
        for index in range(14):
            sector = detached[(bank * 14 + index) * 4096:(bank * 14 + index + 1) * 4096]
            sections[struct.unpack_from("<H", sector, 4084)[0]] = sector[3968:3968 + SAVE_BLOCK_3_CHUNK_SIZE]
        full3 = b"".join(sections[i] for i in range(14))
        self.assertEqual(parse_coop_result(full3[COOP_RESULT_OFFSET:OWE_KEEP_OFFSET]), CoopResult(RUSTBORO, WON, 3))


if __name__ == "__main__":
    unittest.main()
