from __future__ import annotations

import hashlib
from itertools import permutations
import os
from pathlib import Path
import struct
import unittest

from emerald_multiplayer.flash import FlashError, inspect_flash

# Independent synthetic format fixtures. No ROM or real player save is embedded.
_LENGTHS = (3884, 3968, 3968, 3968, 3664,
            3968, 3968, 3968, 3968, 3968, 3968, 3968, 3968, 2400)
_ERASED = b"\xff" * 4096


def _checksum(payload: bytes) -> int:
    total = 0
    for index in range(0, len(payload), 4):
        total = (total + int.from_bytes(payload[index:index + 4], "little")) & 0xFFFFFFFF
    return ((total >> 16) + (total & 0xFFFF)) & 0xFFFF


def _blocks(trainer_id: int) -> tuple[bytes, bytes, bytes]:
    block2 = bytearray(3884)
    block2[:8] = b"\xce\xbf\xcd\xce\xff\xff\xff\xff"  # TEST in game glyphs.
    struct.pack_into("<I", block2, 10, trainer_id)
    block1 = bytearray(15568)
    struct.pack_into("<hh", block1, 0, 6, 11)
    block1[4:8] = b"\0\x09\xff\0"  # Littleroot, no numbered warp.
    struct.pack_into("<H", block1, 0x32, 10)  # Its pinned 20x20 layout.
    return bytes(block1), bytes(block2), bytes(34144)


def _write_bank(flash: bytearray, counter: int, rotation: int, blocks: tuple[bytes, bytes, bytes]) -> None:
    block1, block2, storage = blocks
    pieces = [block2]
    pieces.extend(block1[index:index + 3968] for index in range(0, len(block1), 3968))
    pieces.extend(storage[index:index + 3968] for index in range(0, len(storage), 3968))
    for section_id, payload in enumerate(pieces):
        sector = bytearray(4096)
        sector[:len(payload)] = payload
        struct.pack_into("<HHII", sector, 4084, section_id, _checksum(payload), 0x08012025, counter)
        physical = (counter % 2) * 14 + (section_id + rotation) % 14
        flash[physical * 4096:(physical + 1) * 4096] = sector


def make_flash(*, counter: int = 2, trainer_id: int = 0x12345678,
               with_previous: bool = True, with_rtc: bool = False,
               rotation: int | None = None) -> bytes:
    """Return an independent complete fixture for parser/store/mirror tests."""
    flash = bytearray(b"\xff" * 131072)
    rotation = counter % 14 if rotation is None else rotation
    blocks = _blocks(trainer_id)
    if with_previous:
        _write_bank(flash, (counter - 1) & 0xFFFFFFFF, (rotation - 1) % 14, blocks)
    _write_bank(flash, counter, rotation, blocks)
    footer = b"\x26\x10\x07\x03\x17\x48\x55\x40" + struct.pack("<Q", 1791395335) if with_rtc else b""
    return bytes(flash) + footer


def _sector_offset(data: bytes | bytearray, bank: int, section_id: int) -> int:
    for index in range(14):
        offset = (bank * 14 + index) * 4096
        if struct.unpack_from("<H", data, offset + 4084)[0] == section_id:
            return offset
    raise AssertionError("fixture sector is absent")


def _rewrite(data: bytes, bank: int, section_id: int, offset: int, payload: bytes,
             *, recompute: bool = True) -> bytes:
    changed = bytearray(data)
    start = _sector_offset(changed, bank, section_id)
    changed[start + offset:start + offset + len(payload)] = payload
    if recompute:
        struct.pack_into("<H", changed, start + 4086, _checksum(changed[start:start + _LENGTHS[section_id]]))
    return bytes(changed)


def _mon(*, species: int = 1, personality: int = 7, ot_id: int = 0xABCD1234,
         level: int = 7) -> bytes:
    mon = bytearray(100)
    struct.pack_into("<II", mon, 0, personality, ot_id)
    mon[18:20] = b"\2\2"  # English and occupied.
    order = tuple(permutations(range(4)))[personality % 24]
    secure = bytearray(48)
    struct.pack_into("<H", secure, order.index(0) * 12, species)
    checksum = sum(struct.unpack("<24H", secure)) & 0xFFFF
    struct.pack_into("<H", mon, 28, checksum)
    key = personality ^ ot_id
    for index in range(12):
        value = struct.unpack_from("<I", secure, index * 4)[0]
        struct.pack_into("<I", mon, 32 + index * 4, value ^ key)
    mon[84] = level
    struct.pack_into("<HH", mon, 86, 18, 20)
    return bytes(mon)


class FlashTests(unittest.TestCase):
    def test_complete_latest_bank_and_exact_block_sizes(self):
        data = make_flash(counter=8, rotation=12)
        value = inspect_flash(data)
        self.assertEqual(value.container, data)
        self.assertEqual(value.flash, data)
        self.assertEqual(value.rtc_footer, b"")
        self.assertEqual((value.metadata.bank, value.metadata.counter), (0, 8))
        self.assertEqual((value.metadata.map_group, value.metadata.map_number,
                          value.metadata.x, value.metadata.y), (0, 9, 6, 11))
        self.assertEqual(tuple(map(len, (value.save_block1, value.save_block2,
                                        value.save_block3, value.storage))), (15568, 3884, 4, 34144))
        self.assertEqual(value.container_sha256, hashlib.sha256(data).hexdigest())

    def test_one_complete_bank_and_counter_wrap(self):
        one = inspect_flash(make_flash(counter=1, with_previous=False))
        self.assertEqual((one.metadata.bank, one.metadata.counter), (1, 1))
        wrapped = inspect_flash(make_flash(counter=0, rotation=6))
        self.assertEqual((wrapped.metadata.bank, wrapped.metadata.counter), (0, 0))
        top = inspect_flash(make_flash(counter=0xFFFFFFFF, rotation=9))
        self.assertEqual((top.metadata.bank, top.metadata.counter), (1, 0xFFFFFFFF))

    def test_container_and_normalized_hashes_have_separate_purposes(self):
        raw = inspect_flash(make_flash(counter=2))
        rotated = inspect_flash(make_flash(counter=3, rotation=9))
        rtc = inspect_flash(make_flash(counter=2, with_rtc=True))
        self.assertEqual(raw.state_sha256, rotated.state_sha256)
        self.assertEqual(raw.state_sha256, rtc.state_sha256)
        self.assertNotEqual(raw.container_sha256, rotated.container_sha256)
        self.assertNotEqual(raw.container_sha256, rtc.container_sha256)
        self.assertEqual(raw.sha256, rtc.sha256)
        self.assertEqual(len(rtc.container), 131088)
        self.assertEqual(len(rtc.flash), 131072)
        self.assertEqual(rtc.container[-16:], rtc.rtc_footer)

    def test_identity_binding_and_mixed_owner_banks(self):
        data = make_flash(trainer_id=0xBEEF1234)
        self.assertEqual(inspect_flash(data, expected_trainer_id=0xBEEF1234).metadata.trainer_id, 0xBEEF1234)
        with self.assertRaisesRegex(FlashError, "enrolled owner"):
            inspect_flash(data, expected_trainer_id=0x1234BEEF)
        changed = _rewrite(data, 1, 0, 10, struct.pack("<I", 77))
        with self.assertRaisesRegex(FlashError, "different trainer"):
            inspect_flash(changed)
        for invalid in (True, -1, 0x100000000):
            with self.subTest(invalid=invalid), self.assertRaises(FlashError):
                inspect_flash(data, expected_trainer_id=invalid)

    def test_rejects_blank_truncated_and_unrecognized_containers(self):
        for data in (b"", b"\xff" * 131072, b"\0" * 131072,
                     make_flash()[:-1], make_flash() + b"\0" * 16,
                     make_flash() + b"\xff" * 16, make_flash() + b"x" * 17,
                     bytearray(make_flash())):
            with self.subTest(length=len(data)), self.assertRaises(FlashError):
                inspect_flash(data)

    def test_rejects_newer_partial_instead_of_older_fallback(self):
        data = make_flash(counter=2)
        offset = _sector_offset(data, 0, 7)
        changed = data[:offset] + _ERASED + data[offset + 4096:]
        with self.assertRaisesRegex(FlashError, "partial save bank"):
            inspect_flash(changed)
        # A first-save write interrupted halfway through is also rejected.
        first = make_flash(counter=1, with_previous=False)
        offset = _sector_offset(first, 1, 12)
        with self.assertRaises(FlashError):
            inspect_flash(first[:offset] + _ERASED + first[offset + 4096:])

    def test_section_corruption_and_unfinished_signature(self):
        data = make_flash()
        cases = (
            _rewrite(data, 0, 1, 1500, b"\1", recompute=False),
            _rewrite(data, 0, 3, 4088, struct.pack("<I", 0x080120FF)),
            _rewrite(data, 0, 0, 4084, struct.pack("<H", 14)),
            _rewrite(data, 0, 1, 4084, struct.pack("<H", 0)),
            _rewrite(data, 0, 8, 4092, struct.pack("<I", 4)),
        )
        for changed in cases:
            with self.subTest(case=hashlib.sha256(changed).hexdigest()), self.assertRaises(FlashError):
                inspect_flash(changed)

    def test_rotation_parity_and_nonadjacent_counter_rejection(self):
        data = bytearray(make_flash())
        first, second = _sector_offset(data, 0, 4), _sector_offset(data, 0, 5)
        left, right = bytes(data[first:first + 4096]), bytes(data[second:second + 4096])
        data[first:first + 4096], data[second:second + 4096] = right, left
        with self.assertRaisesRegex(FlashError, "rotation"):
            inspect_flash(bytes(data))
        data = bytearray(make_flash())
        for i in range(14):
            struct.pack_into("<I", data, i * 4096 + 4092, 3)
        with self.assertRaisesRegex(FlashError, "parity"):
            inspect_flash(bytes(data))
        data = bytearray(make_flash())
        for i in range(14):
            struct.pack_into("<I", data, i * 4096 + 4092, 8)
        with self.assertRaisesRegex(FlashError, "adjacent"):
            inspect_flash(bytes(data))

    def test_primary_and_extension_padding_are_layout_checks(self):
        data = make_flash()
        for changed in (_rewrite(data, 0, 0, 3884, b"\1"),
                        _rewrite(data, 0, 4, 3664, b"\1"),
                        _rewrite(data, 0, 13, 2400, b"\1"),
                        _rewrite(data, 0, 0, 3972, b"\1"),
                        _rewrite(data, 0, 9, 3968 + 32, b"\1")):   # SaveBlock3 byte 1076: past the Tower record (1012-1075)
            with self.subTest(case=hashlib.sha256(changed).hexdigest()), self.assertRaisesRegex(FlashError, "padding"):
                inspect_flash(changed)
        # SaveBlock3's four real bytes are not covered by upstream checksum.
        changed = _rewrite(data, 0, 0, 3968, b"\1\2\3\4")
        value = inspect_flash(changed)
        self.assertEqual(value.save_block3, b"\1\2\3\4")
        self.assertNotEqual(value.state_sha256, inspect_flash(data).state_sha256)

    # ---- Update 30: the Day Care egg queue lives in SaveBlock3 after the 600-byte ownership profile (bytes 600..1011)
    @staticmethod
    def _egg_queue(count: int = 2, *, tamper=None) -> bytes:
        import zlib
        eggs = bytearray(5 * 80)
        for index in range(count):
            mon = bytearray(_mon(species=172 + index, personality=0x1000 + index)[:80])
            mon[19] = 2 | 4          # has species, is an Egg
            eggs[index * 80:(index + 1) * 80] = mon
        body = struct.pack("<IBBH", 0x45474751, 1, count, 0) + bytes(eggs)
        if tamper is not None:
            body = tamper(bytearray(body))
        return body + struct.pack("<I", zlib.crc32(body))

    @staticmethod
    def _put_block3(data: bytes, offset: int, payload: bytes) -> bytes:
        for position in range(len(payload)):
            absolute = offset + position
            data = _rewrite(data, 0, absolute // 116, 3968 + absolute % 116, payload[position:position + 1], recompute=False)
        return data

    def test_egg_queue_is_accepted_when_sealed_and_refused_when_not(self):
        data = make_flash()
        self.assertEqual(inspect_flash(data).save_block3, b"\0\0\0\0")             # a save from before: zeros mean no Eggs
        good = self._put_block3(data, 600, self._egg_queue(2))
        inspect_flash(good)                                                    # two waiting Eggs
        inspect_flash(self._put_block3(data, 600, self._egg_queue(5)))         # a full queue
        inspect_flash(self._put_block3(data, 600, self._egg_queue(0)))         # sealed and empty
        # legacy (presence) layout may carry it too, and the ownership profile bytes stay exactly the profile
        self.assertEqual(len(inspect_flash(good).save_block3), 4)
        for name, changed in (
            ("count above five", self._put_block3(data, 600, self._egg_queue(2, tamper=lambda b: (b.__setitem__(5, 6), b)[1]))),
            ("crc", self._put_block3(data, 600, self._egg_queue(2)[:-1] + b"\0")),
            ("a stray byte after the queue", self._put_block3(good, 1012, b"\1")),
            ("an unused slot with data", self._put_block3(data, 600, self._egg_queue(1, tamper=lambda b: (b.__setitem__(8 + 80 * 3, 1), b)[1]))),
            ("a byte between the profile and the queue", self._put_block3(data, 100, b"\1")),
            ("not an Egg", self._put_block3(data, 600, self._egg_queue(1, tamper=lambda b: (b.__setitem__(8 + 19, 2), b)[1]))),
        ):
            with self.subTest(case=name), self.assertRaises(FlashError):
                inspect_flash(changed)

    def test_map_and_count_bounds_even_when_sector_checksum_is_recomputed(self):
        data = make_flash()
        cases = (
            _rewrite(data, 0, 1, 4, b"\xff"),
            _rewrite(data, 0, 1, 5, b"\xff"),
            _rewrite(data, 0, 1, 0, struct.pack("<h", -1)),
            _rewrite(data, 0, 1, 0, struct.pack("<h", 20)),
            _rewrite(data, 0, 1, 0x32, b"\0\0"),
            _rewrite(data, 0, 1, 0x234, b"\7"),
            _rewrite(data, 0, 5, 0, b"\x0e"),
            _rewrite(data, 0, 0, 8, b"\2"),
            _rewrite(data, 0, 0, 16, b"\x3c"),
            _rewrite(data, 0, 0, 0, b"\xff"),
        )
        for changed in cases:
            with self.subTest(case=hashlib.sha256(changed).hexdigest()), self.assertRaises(FlashError):
                inspect_flash(changed)

    def test_saved_remote_actor_rejected_even_if_inactive(self):
        data = make_flash()
        for local_id in (241, 242, 243):
            changed = _rewrite(data, 0, 1, 0xA30 + 8, bytes([local_id]))
            with self.subTest(local_id=local_id), self.assertRaisesRegex(FlashError, "temporary remote"):
                inspect_flash(changed)

    def test_box_checksums_occupancy_and_traded_ot_are_distinct(self):
        data = _rewrite(make_flash(), 0, 1, 0x234, b"\1")
        for personality in range(24):
            mon = _mon(personality=personality, ot_id=0x55667788)
            populated = _rewrite(data, 0, 1, 0x238, mon)
            self.assertEqual(inspect_flash(populated, expected_trainer_id=0x12345678).metadata.party_count, 1)
        populated = _rewrite(data, 0, 1, 0x238, _mon())
        corrupt = _rewrite(populated, 0, 1, 0x238 + 32, b"\xff")
        with self.assertRaisesRegex(FlashError, "Pokémon checksum"):
            inspect_flash(corrupt)
        for mon in (_mon(species=1573), _mon(level=0), _mon(level=101)):
            with self.subTest(case=mon[84]), self.assertRaises(FlashError):
                inspect_flash(_rewrite(data, 0, 1, 0x238, mon))
        with self.assertRaisesRegex(FlashError, "occupancy"):
            inspect_flash(data)
        with self.assertRaisesRegex(FlashError, "occupancy"):
            inspect_flash(_rewrite(make_flash(), 0, 1, 0x238, _mon()))

    def test_rtc_footer_validation_and_preservation(self):
        data = make_flash(with_rtc=True)
        self.assertEqual(inspect_flash(data).container, data)
        for index, value in ((0, 0xFA), (1, 0), (2, 0x32), (3, 7), (4, 0x24),
                             (5, 0x60), (6, 0x60), (7, 1), (15, 0x80)):
            changed = bytearray(data)
            changed[131072 + index] = value
            with self.subTest(index=index), self.assertRaises(FlashError):
                inspect_flash(bytes(changed))
        twelve = data[:131072 + 4] + b"\x11" + data[131072 + 5:131072 + 7] + b"\0" + data[131072 + 8:]
        self.assertEqual(len(inspect_flash(twelve).rtc_footer), 16)

    def test_special_sector_formats_are_not_normal_bank_footers(self):
        data = bytearray(make_flash())
        hof = bytearray(4096)
        struct.pack_into("<I", hof, 0, 0xFEDCBA98)
        struct.pack_into("<HHII", hof, 4084, _checksum(hof[:3968]), 0, 0x08012025, 0)
        data[28 * 4096:29 * 4096] = hof
        special = bytearray(b"\x01" * 4096)
        struct.pack_into("<I", special, 0, 0xB39D)
        data[30 * 4096:31 * 4096] = special
        self.assertEqual(inspect_flash(bytes(data)).flash[30 * 4096:31 * 4096], special)
        data[28 * 4096 + 4] = 1
        with self.assertRaisesRegex(FlashError, "Hall of Fame"):
            inspect_flash(bytes(data))
        data = bytearray(make_flash())
        data[31 * 4096:32 * 4096] = bytes(4096)
        with self.assertRaisesRegex(FlashError, "sentinel"):
            inspect_flash(bytes(data))

    @unittest.skipUnless(os.environ.get("EMERALD_PRIVATE_SAVE_PATHS"), "private save paths are not configured")
    def test_optional_private_saves_read_only(self):
        paths = os.environ["EMERALD_PRIVATE_SAVE_PATHS"].split(os.pathsep)
        for raw_path in paths:
            path = Path(raw_path)
            before = path.read_bytes()
            with self.subTest(filename=path.name):
                parsed = inspect_flash(before)
                self.assertEqual(parsed.container, before)
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(len(parsed.flash), 131072)


if __name__ == "__main__":
    unittest.main()
