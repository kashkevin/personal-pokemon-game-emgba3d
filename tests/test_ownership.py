from __future__ import annotations

from dataclasses import replace
from itertools import permutations
import struct
import unittest
import uuid
import zlib

from emerald_multiplayer.flash import FlashError, LAYOUT_ID, inspect_flash
from emerald_multiplayer.ownership import (
    OWNED_SLOT_COUNT, OWNERSHIP_PROFILE, OwnershipError,
    extract_source_inventory, inspect_ownership,
)
from test_flash import _blocks, _rewrite, _sector_offset, _write_bank, make_flash

WORLD_ID = "91f9294e-d509-4023-b055-f940a269aabc"
PLAYER_ID = "8ea3ff34-4567-4cb9-bdfe-6c6f1b399abc"
GRANT_ID = "cd8bfa43-a06a-408f-96e4-12f2cf879abc"


def make_owned_mon(serial: int, *, personality: int = 7, species: int = 265,
                   ot_id: int = 0xAABBCCDD) -> bytes:
    """Independent C ABI fixture; does not use the production decoder."""
    logical = [bytearray(12) for _ in range(4)]
    struct.pack_into("<H", logical[0], 0, species)
    struct.pack_into("<H", logical[0], 2, (serial & 63) << 10)
    struct.pack_into("<I", logical[0], 4, ((serial >> 6) & 7) << 29)
    struct.pack_into("<H", logical[0], 10, ((serial >> 9) & 3) << 14)
    struct.pack_into("<H", logical[1], 4, ((serial >> 11) & 31) << 11)
    struct.pack_into("<H", logical[1], 6, ((serial >> 16) & 7) << 11)
    struct.pack_into("<I", logical[3], 8, ((serial >> 19) & 1) << 28)
    order = tuple(permutations(range(4)))[personality % 24]
    secure = b"".join(logical[index] for index in order)
    mon = bytearray(100)
    struct.pack_into("<II", mon, 0, personality, ot_id)
    mon[18:20] = b"\2\2" if species else b"\0\0"
    struct.pack_into("<H", mon, 28, sum(struct.unpack("<24H", secure)) & 0xFFFF)
    for index in range(12):
        value = struct.unpack_from("<I", secure, index * 4)[0]
        struct.pack_into("<I", mon, 32 + index * 4, value ^ personality ^ ot_id)
    mon[84] = 7
    struct.pack_into("<HH", mon, 86, 18, 20)
    return bytes(mon)


def make_ownership_record(*, world_id: str = WORLD_ID, player_id: str = PLAYER_ID,
                          grant_id: str = GRANT_ID, start: int = 1,
                          end_exclusive: int = 0x100000, next_serial: int = 0x100000,
                          lease_epoch: int = 1, incarnation: int = 1,
                          retirements: tuple[tuple[int, int], ...] = ()) -> bytes:
    record = bytearray(600)
    record[4:8] = b"EMO1"
    struct.pack_into("<HH", record, 8, 1, 596)
    record[12:28], record[28:44], record[44:60] = (
        uuid.UUID(value).bytes for value in (world_id, player_id, grant_id))
    struct.pack_into("<IIIII", record, 60, start, end_exclusive, next_serial, lease_epoch, incarnation)
    struct.pack_into("<H", record, 80, len(retirements))
    for index, (serial, reason) in enumerate(retirements):
        struct.pack_into("<I", record, 84 + index * 4, serial | (reason << 20))
    struct.pack_into("<I", record, 596, zlib.crc32(record[:596]))
    return bytes(record)


def _put_mon(block1: bytearray, storage: bytearray, location: str, mon: bytes) -> None:
    pieces = location.split(":")
    if pieces[0] == "party":
        index = int(pieces[1])
        start = 0x238 + index * 100
        block1[start:start + 100] = mon
        block1[0x234] = max(block1[0x234], index + 1)
    elif pieces[0] == "box":
        start = 4 + (int(pieces[1]) * 30 + int(pieces[2])) * 80
        storage[start:start + 80] = mon[:80]
    elif pieces[0] == "daycare":
        start = 0x3030 + int(pieces[1]) * 140
        block1[start:start + 80] = mon[:80]
    elif pieces[0] == "fusion":
        start = 0x83D0 + int(pieces[1]) * 100
        storage[start:start + 100] = mon
    else:
        raise ValueError("fixture location")


def _write_record(data: bytearray, bank: int, record: bytes) -> None:
    for section in range(14):
        start = _sector_offset(data, bank, section)
        chunk = record[section * 116:(section + 1) * 116]
        data[start + 3968:start + 4084] = chunk + bytes(116 - len(chunk))


def make_ownership_flash(*, counter: int = 2,
                         records: tuple[tuple[str, int], ...] = (("party:0", 1),),
                         legacy_previous: bool = False, with_previous: bool = True,
                         unassigned_previous: bool = False,
                         metadata: bytes | None = None,
                         personalities: tuple[int, ...] | None = None,
                         with_rtc: bool = False) -> bytes:
    """Synthetic full Flash for parser and ownership-store integration tests."""
    first, second, storage = _blocks(0x12345678)
    block1, pc = bytearray(first), bytearray(storage)
    old_block1, old_pc = bytearray(first), bytearray(storage)
    for index, (location, serial) in enumerate(records):
        pid = personalities[index] if personalities else index + 7
        _put_mon(block1, pc, location, make_owned_mon(serial, personality=pid))
        _put_mon(old_block1, old_pc, location, make_owned_mon(0 if legacy_previous or unassigned_previous else serial, personality=pid))
    flash = bytearray(b"\xff" * 131072)
    rotation = counter % 14
    if with_previous:
        previous = (counter - 1) & 0xFFFFFFFF
        _write_bank(flash, previous, (rotation - 1) % 14, (bytes(old_block1), second, bytes(old_pc)))
        if not legacy_previous:
            _write_record(flash, previous % 2, metadata or make_ownership_record())
    _write_bank(flash, counter, rotation, (bytes(block1), second, bytes(pc)))
    _write_record(flash, counter % 2, metadata or make_ownership_record())
    footer = make_flash(with_rtc=True)[131072:] if with_rtc else b""
    return bytes(flash) + footer


def _change_record(data: bytes, offset: int, payload: bytes, *, bank: int = 0,
                   recompute: bool = True) -> bytes:
    result = bytearray(data)
    record = bytearray(b"".join(result[_sector_offset(result, bank, i) + 3968:
                                     _sector_offset(result, bank, i) + 4084] for i in range(14))[:600])
    record[offset:offset + len(payload)] = payload
    if recompute:
        struct.pack_into("<I", record, 596, zlib.crc32(record[:596]))
    _write_record(result, bank, bytes(record))
    return bytes(result)


class OwnershipTests(unittest.TestCase):
    def parse(self, data: bytes):
        return inspect_ownership(inspect_flash(data, save_profile=OWNERSHIP_PROFILE))

    def test_explicit_profile_and_legacy_defaults(self):
        legacy = inspect_flash(make_flash())
        self.assertEqual(legacy.save_profile, LAYOUT_ID)
        self.assertEqual(len(legacy.save_block3), 4)
        owned = make_ownership_flash(with_rtc=True)
        with self.assertRaises(FlashError):
            inspect_flash(owned)
        parsed = inspect_flash(owned, save_profile=OWNERSHIP_PROFILE)
        self.assertEqual(parsed.save_profile, OWNERSHIP_PROFILE)
        self.assertEqual(parsed.container, owned)
        self.assertEqual(len(parsed.save_block3), 600)
        self.assertEqual(len(parsed.rtc_footer), 16)
        with self.assertRaisesRegex(FlashError, "profile"):
            inspect_flash(make_flash(), save_profile="unrecognized")
        with self.assertRaises(OwnershipError):
            inspect_ownership(legacy)
        with self.assertRaisesRegex(FlashError, "missing"):
            inspect_flash(make_flash(), save_profile=OWNERSHIP_PROFILE)

    def test_uid_bits_and_all_24_substructure_permutations(self):
        for serial in (1, 1 << 6, 1 << 9, 1 << 11, 1 << 16, 1 << 19, 0xFFFFF):
            for personality in range(24):
                with self.subTest(serial=serial, personality=personality):
                    parsed = self.parse(make_ownership_flash(records=(("party:0", serial),),
                                                           personalities=(personality,)))
                    self.assertEqual(parsed.records[0].serial, serial)
                    self.assertEqual(parsed.records[0].personality, personality)
                    self.assertEqual(parsed.records[0].ot_id, 0xAABBCCDD)

    def test_every_retained_slot_including_daycare_and_fusion(self):
        locations = ([f"party:{i}" for i in range(6)] +
                     [f"box:{b}:{i}" for b in range(14) for i in range(30)] +
                     [f"daycare:{i}" for i in range(2)] + [f"fusion:{i}" for i in range(4)])
        data = make_ownership_flash(records=tuple((location, index + 1) for index, location in enumerate(locations)))
        parsed = self.parse(data)
        self.assertEqual(OWNED_SLOT_COUNT, 432)
        self.assertEqual(tuple(record.location for record in parsed.records), tuple(locations))
        self.assertEqual(tuple(record.serial for record in parsed.records), tuple(range(1, 433)))
        snapshot = inspect_flash(data, save_profile=OWNERSHIP_PROFILE)
        self.assertEqual(snapshot.metadata.stored_pokemon_count, 420)
        self.assertEqual(snapshot.metadata.fusion_count, 4)

    def test_explicit_legacy_migration_preserves_content_hash(self):
        data = make_ownership_flash(legacy_previous=True,
                                    records=(("party:0", 1), ("box:3:14", 27), ("daycare:1", 55), ("fusion:2", 100)))
        parsed = self.parse(data)
        legacy = bytearray(data)
        for i in range(14):
            legacy[i * 4096:(i + 1) * 4096] = b"\xff" * 4096
        source = extract_source_inventory(inspect_flash(bytes(legacy)))
        self.assertEqual(tuple(record.serial for record in source), (0, 0, 0, 0))
        self.assertEqual(tuple(record.content_sha256 for record in source),
                         tuple(record.content_sha256 for record in parsed.records))
        self.assertEqual(tuple(record.location for record in source), tuple(record.location for record in parsed.records))

    def test_previous_ownership_identity_and_corruption_are_rejected(self):
        data = make_ownership_flash()
        for offset, payload in ((12, uuid.uuid4().bytes), (28, uuid.uuid4().bytes)):
            with self.subTest(offset=offset), self.assertRaisesRegex(FlashError, "different world or player"):
                self.parse(_change_record(data, offset, payload, bank=1))
        with self.assertRaisesRegex(FlashError, "CRC32"):
            self.parse(_change_record(data, 100, b"x", bank=1, recompute=False))
        with self.assertRaisesRegex(FlashError, "magic"):
            self.parse(_change_record(data, 4, bytes(596), bank=0))

    def test_previous_ordinary_save_allows_unassigned_owned_creatures(self):
        # A capture followed by ordinary Save can precede frozen ID assignment.
        data = make_ownership_flash(unassigned_previous=True,
                                    records=(("party:0", 7), ("party:1", 8), ("daycare:0", 9)))
        self.assertEqual(tuple(record.serial for record in self.parse(data).records), (7, 8, 9))
        with self.assertRaisesRegex(FlashError, "missing its instance"):
            self.parse(make_ownership_flash(records=(("party:0", 0),)))
        duplicate = _rewrite(data, 1, 1, 0x238, make_owned_mon(7))
        duplicate = _rewrite(duplicate, 1, 1, 0x238 + 100, make_owned_mon(7))
        with self.assertRaisesRegex(FlashError, "duplicate instance"):
            self.parse(duplicate)
        retired = _rewrite(data, 1, 1, 0x238, make_owned_mon(7))
        retired = _change_record(retired, 80, struct.pack("<H", 1), bank=1)
        retired = _change_record(retired, 84, struct.pack("<I", 7 | (1 << 20)), bank=1)
        with self.assertRaisesRegex(FlashError, "retired instance"):
            self.parse(retired)

    def test_metadata_magic_version_size_uuid_range_and_crc(self):
        data = make_ownership_flash()
        cases = ((4, b"BAD!"), (8, struct.pack("<H", 2)), (10, struct.pack("<H", 595)),
                 (12, bytes(16)), (28, bytes(16)), (44, bytes(16)),
                 (60, struct.pack("<I", 0)), (64, struct.pack("<I", 1)),
                 (64, struct.pack("<I", 0x100001)), (68, struct.pack("<I", 0)),
                 (72, bytes(4)), (76, bytes(4)), (82, b"\1\0"))
        for offset, payload in cases:
            with self.subTest(offset=offset, payload=payload), self.assertRaises(FlashError):
                self.parse(_change_record(data, offset, payload))
        with self.assertRaisesRegex(FlashError, "CRC32"):
            self.parse(_change_record(data, 0, b"\1", recompute=False))
        # UUIDs are opaque exact bytes; native ABI has no RFC variant rule.
        opaque = _change_record(_change_record(data, 12, b"\x01" * 16), 12, b"\x01" * 16, bank=1)
        self.assertEqual(self.parse(opaque).world_id, str(uuid.UUID(bytes=b"\x01" * 16)))

    def test_padding_outside_600_is_rejected(self):
        data = bytearray(make_ownership_flash())
        offset = _sector_offset(data, 0, 5) + 3968 + 20
        data[offset] = 1  # 5*116+20 = first byte after logical 600.
        with self.assertRaisesRegex(FlashError, "padding"):
            self.parse(bytes(data))

    def test_retirement_intents_and_invalid_journals(self):
        data = make_ownership_flash(metadata=make_ownership_record(retirements=((17, 1), (19, 2))))
        self.assertEqual(tuple((item.serial, item.reason) for item in self.parse(data).retirements), ((17, 1), (19, 2)))
        cases = ((80, struct.pack("<H", 129)), (84, struct.pack("<I", 1 << 20)),
                 (84, struct.pack("<I", 17)), (84, struct.pack("<I", 17 | (3 << 20))),
                 (84, struct.pack("<I", 17 | (1 << 24) | (1 << 20))),
                 (88, struct.pack("<I", 17 | (2 << 20))), (92, b"\1\0\0\0"),
                 (84, struct.pack("<I", 1 | (1 << 20))))
        for offset, payload in cases:
            with self.subTest(offset=offset, payload=payload), self.assertRaises(FlashError):
                self.parse(_change_record(data, offset, payload))

    def test_missing_duplicate_and_unconsumed_serials(self):
        for records in ((("party:0", 0),), (("party:0", 17), ("box:13:29", 17)),
                        (("daycare:0", 18), ("fusion:3", 18))):
            with self.subTest(records=records), self.assertRaises(FlashError):
                self.parse(make_ownership_flash(records=records))
        with self.assertRaisesRegex(FlashError, "unconsumed"):
            self.parse(make_ownership_flash(metadata=make_ownership_record(start=1, end_exclusive=20, next_serial=1)))
        with self.assertRaisesRegex(FlashError, "unconsumed"):
            self.parse(make_ownership_flash(records=(), metadata=make_ownership_record(
                start=1, end_exclusive=20, next_serial=5, retirements=((5, 1),))))
        self.assertEqual(self.parse(make_ownership_flash(records=(), metadata=make_ownership_record(
            start=10, end_exclusive=20, next_serial=10))).records, ())

    def test_daycare_checksum_and_bad_empty_records(self):
        data = make_ownership_flash(records=(("daycare:0", 1),))
        snapshot = inspect_flash(data, save_profile=OWNERSHIP_PROFILE)
        damaged = bytearray(snapshot.save_block1)
        damaged[0x3030 + 32] ^= 1
        with self.assertRaisesRegex(FlashError, "checksum"):
            inspect_ownership(replace(snapshot, save_block1=bytes(damaged)))
        damaged = bytearray(snapshot.storage)
        damaged[4:84] = make_owned_mon(2, personality=0, ot_id=0, species=0)[:80]
        with self.assertRaisesRegex(FlashError, "empty"):
            inspect_ownership(replace(snapshot, storage=bytes(damaged)))

    def test_source_inventory_rejects_wrong_profile_and_nonzero_legacy_bits(self):
        with self.assertRaises(OwnershipError):
            extract_source_inventory(inspect_flash(make_ownership_flash(), save_profile=OWNERSHIP_PROFILE))
        data = bytearray(make_ownership_flash())
        for bank in range(2):
            _write_record(data, bank, bytes(4))
        with self.assertRaisesRegex(OwnershipError, "nonzero identity"):
            extract_source_inventory(inspect_flash(bytes(data)))
        previous = bytearray(make_ownership_flash())
        _write_record(previous, 1, bytes(4))
        with self.assertRaisesRegex(FlashError, "nonzero identity"):
            self.parse(bytes(previous))

    def test_profile_normalized_hash_ignores_rotation_and_rtc(self):
        a = inspect_flash(make_ownership_flash(counter=2), save_profile=OWNERSHIP_PROFILE)
        b = inspect_flash(make_ownership_flash(counter=3, with_rtc=True), save_profile=OWNERSHIP_PROFILE)
        self.assertEqual(a.state_sha256, b.state_sha256)
        self.assertNotEqual(a.container_sha256, b.container_sha256)
        self.assertEqual(inspect_ownership(a).manifest_sha256, inspect_ownership(b).manifest_sha256)
        self.assertEqual(len(inspect_ownership(a).manifest_sha256), 64)


if __name__ == "__main__":
    unittest.main()
