"""The TM catalogue's save record (docs/owner-decisions.md 26-29, 2026-10-31).

The PC game keeps TM01-TM50 and the HMs in the save's 64 TM pocket slots (SaveBlock1, pinned) and TM51-TM168 as one bit
each in a 36-byte record after the Battle Tower record (engine struct MPTmRecord, SaveBlock3 bytes 1076-1111). The
launcher's save checker reads it like the egg queue and the Tower record: all zeros (every older save) is no TM past TM50;
anything but a sealed record is refused, never repaired."""
from __future__ import annotations

import struct
import unittest
import zlib

from emerald_multiplayer.character_transfer import detach_from_world
from emerald_multiplayer.flash import (
    COOP_RESULT_OFFSET, LAYOUT_ID, OWNERSHIP_LAYOUT_ID, SAVE_BLOCK_3_CHUNK_SIZE, SAVE_BLOCK_3_FULL_SIZE, TM_RECORD_MAGIC, TM_RECORD_OFFSET,
    TM_RECORD_SIZE, TOWER_RECORD_OFFSET, TOWER_RECORD_SIZE, FlashError, inspect_flash, parse_tm_record,
)
import test_flash
from test_flash import make_flash
from test_ownership import make_ownership_flash


def tm_record(tms=(51, 100, 168), *, count=None, version=1, reserved=0, magic=TM_RECORD_MAGIC, tamper=None) -> bytes:
    owned = bytearray(24)
    for tm in tms:
        owned[(tm - 51) // 8] |= 1 << ((tm - 51) % 8)
    body = bytearray(struct.pack("<IBBH24s", magic, version, len(set(tms)) if count is None else count, reserved,
                                 bytes(owned)))
    if tamper:
        tamper(body)
    return bytes(body) + struct.pack("<I", zlib.crc32(bytes(body)))


def with_tm_record(record: bytes, data: bytes | None = None) -> bytes:
    return test_flash.FlashTests._put_block3(make_flash() if data is None else data, TM_RECORD_OFFSET, record)


class TmRecordTests(unittest.TestCase):
    def test_the_record_follows_the_tower_record_and_fits_saveblock3(self):
        self.assertEqual((TOWER_RECORD_OFFSET + TOWER_RECORD_SIZE, TM_RECORD_OFFSET, TM_RECORD_SIZE),
                         (1076, 1076, 36))
        self.assertEqual(COOP_RESULT_OFFSET, TM_RECORD_OFFSET + TM_RECORD_SIZE)   # a co-op battle's result follows it
        self.assertLessEqual(SAVE_BLOCK_3_FULL_SIZE, 14 * SAVE_BLOCK_3_CHUNK_SIZE)   # 1624: SaveBlock3's room in a bank
        self.assertEqual(len(tm_record()), TM_RECORD_SIZE)

    def test_older_saves_have_none(self):
        self.assertEqual(parse_tm_record(bytes(36)), frozenset())
        inspect_flash(make_flash())
        inspect_flash(make_ownership_flash(), save_profile=OWNERSHIP_LAYOUT_ID)

    def test_a_sealed_record_is_accepted_in_both_profiles(self):
        self.assertEqual(parse_tm_record(tm_record()), frozenset({51, 100, 168}))
        self.assertEqual(parse_tm_record(tm_record(range(51, 169))), frozenset(range(51, 169)))   # every TM it can hold
        self.assertEqual(parse_tm_record(tm_record((52,))), frozenset({52}))
        inspect_flash(with_tm_record(tm_record()))
        owned = with_tm_record(tm_record(), make_ownership_flash())
        inspect_flash(owned, save_profile=OWNERSHIP_LAYOUT_ID)
        # beside the egg queue and the Tower record
        eggs = test_flash.FlashTests._put_block3(make_flash(), 600, test_flash.FlashTests._egg_queue(2))
        inspect_flash(with_tm_record(tm_record(range(60, 80)), eggs))

    def test_anything_else_is_refused(self):
        cases = {
            "magic": tm_record(magic=0x314D5451),
            "version": tm_record(version=2),
            "reserved": tm_record(reserved=1),
            "count too high": tm_record(count=4),
            "count too low": tm_record(count=2),
            "count without TMs": tm_record((), count=0),
            "TM169 (past the last TM)": tm_record((51, 169)),
            "the last bit (TM242)": tm_record((242,)),
            "crc": tm_record()[:32] + b"\0\0\0\0",
            "a changed bit": (lambda r: r[:8] + bytes([r[8] ^ 2]) + r[9:])(tm_record()),
            "a stray byte": bytes(35) + b"\1",
        }
        for name, record in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(FlashError):
                    parse_tm_record(record)
                with self.assertRaises(FlashError):
                    inspect_flash(with_tm_record(record))
        with self.assertRaisesRegex(FlashError, "wrong size"):
            parse_tm_record(bytes(35))
        # a stray byte where the record lives is refused as a damaged record, not read as one
        with self.assertRaisesRegex(FlashError, "TM record"):
            inspect_flash(test_flash.FlashTests._put_block3(make_flash(), 1076, b"\1"))
        # what follows the record is the co-op result record (a stray byte there is a damaged one), then padding
        with self.assertRaisesRegex(FlashError, "co-op result"):
            inspect_flash(test_flash.FlashTests._put_block3(with_tm_record(tm_record()), 1112, b"\1"))
        with self.assertRaisesRegex(FlashError, "padding"):
            inspect_flash(test_flash.FlashTests._put_block3(with_tm_record(tm_record()), SAVE_BLOCK_3_FULL_SIZE, b"\1"))

    def test_a_character_leaving_its_world_keeps_its_tms(self):
        owned = with_tm_record(tm_record((51, 60, 168)),
                               make_ownership_flash(records=(("party:0", 1), ("box:3:14", 27))))
        detached = detach_from_world(owned).payload
        snapshot = inspect_flash(detached, save_profile=LAYOUT_ID)
        bank = snapshot.metadata.bank
        sections = {}
        for index in range(14):
            sector = detached[(bank * 14 + index) * 4096:(bank * 14 + index + 1) * 4096]
            sections[struct.unpack_from("<H", sector, 4084)[0]] = sector[3968:3968 + SAVE_BLOCK_3_CHUNK_SIZE]
        full3 = b"".join(sections[i] for i in range(14))
        self.assertEqual(parse_tm_record(full3[TM_RECORD_OFFSET:COOP_RESULT_OFFSET]), frozenset({51, 60, 168}))


if __name__ == "__main__":
    unittest.main()
