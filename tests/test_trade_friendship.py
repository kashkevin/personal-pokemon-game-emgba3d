from dataclasses import replace
from itertools import permutations
import struct
import unittest

from emerald_multiplayer.flash import FlashError
from emerald_multiplayer.trade_friendship import (
    FriendshipHistory, FriendshipPlanError, TrainerIdentity,
    plan_friendship, transform_received_party_record,
)
from test_ownership import make_owned_mon


ALICE = TrainerIdentity(b"ALICE", 0, 0xAABBCCDD, 3)
BOB = TrainerIdentity(b"BOB", 0, 0x12345678, 3)
CAROL = TrainerIdentity(b"CAROL", 1, 0x87654321, 3)
UNTRADED = FriendshipHistory(0xFFFFF, ALICE, 200, None, 0, 0)
WITH_BOB = FriendshipHistory(0xFFFFF, ALICE, 200, BOB, 90, 1)


def decode_fixture(mon):
    """Independent permutation layout, without the production decoder table."""
    pid, ot = struct.unpack_from("<II", mon)
    plain = struct.pack("<12I", *(v ^ pid ^ ot for v in struct.unpack_from("<12I", mon, 32)))
    order = tuple(permutations(range(4)))[pid % 24]
    return [bytearray(plain[order.index(i)*12:order.index(i)*12+12]) for i in range(4)]


def encode_fixture(mon, logical):
    result = bytearray(mon)
    pid, ot = struct.unpack_from("<II", result)
    order = tuple(permutations(range(4)))[pid % 24]
    plain = b"".join(logical[i] for i in order)
    struct.pack_into("<H", result, 28, sum(struct.unpack("<24H", plain)) & 0xFFFF)
    for index, value in enumerate(struct.unpack("<12I", plain)):
        struct.pack_into("<I", result, 32+index*4, value ^ pid ^ ot)
    return bytes(result)


def make_friendship_mon(pid=7, *, friendship=215, moves=(33, 45, 0, 0), serial=0xFFFFF):
    mon = bytearray(make_owned_mon(serial, personality=pid))
    mon[20:27] = b"ALICE\xff\xff"
    mon[80:84] = b"\x08\0\0\0"  # Persisted status and party tail must survive.
    mon[88:100] = struct.pack("<6H", 20, 21, 22, 23, 24, 25)
    logical = decode_fixture(mon)
    logical[0][8:10] = bytes((0xA5, friendship))
    for index, move in enumerate(moves):
        original = struct.unpack_from("<H", logical[1], index*2)[0]
        struct.pack_into("<H", logical[1], index*2, original & 0xF800 | move)
    logical[1][8:12] = bytes((5, 10, 15, 20))
    logical[2][:] = bytes(range(12))
    struct.pack_into("<H", logical[3], 2, 3 << 7 | 5)
    struct.pack_into("<I", logical[3], 4, 0x1ABCDEFF)
    return encode_fixture(mon, logical)


class FriendshipPlanTests(unittest.TestCase):
    def test_handler_and_exception_transition_table(self):
        # Expected values are explicit Gen6 transition examples, not calculated
        # by a second copy of the implementation.
        returned_to_alice = replace(WITH_BOB, current_handler=0)
        cases = (
            ("first trade", UNTRADED, BOB, 215, 70, 33, False, (215, 70, 1, True, True)),
            ("first Return", UNTRADED, BOB, 215, 70, 216, False, (215, 215, 1, True, True)),
            ("first Frustration", UNTRADED, BOB, 0, 70, 218, False, (0, 0, 1, True, True)),
            ("back to OT", WITH_BOB, ALICE, 160, 35, 33, False, (200, 160, 0, True, False)),
            ("Return back to OT", WITH_BOB, ALICE, 160, 35, 216, False, (160, 160, 0, True, False)),
            ("another HT with Return", WITH_BOB, CAROL, 160, 35, 216, False, (200, 35, 1, False, True)),
            ("unchanged HT", WITH_BOB, BOB, 160, 35, 33, False, (200, 160, 1, False, False)),
            ("HT name gender match", WITH_BOB, replace(BOB, trainer_id=99, version=4), 160, 35, 216,
             False, (200, 160, 1, False, False)),
            ("different HT gender", WITH_BOB, replace(BOB, gender=1), 160, 35, 216,
             False, (200, 35, 1, False, True)),
            ("unchanged OT", UNTRADED, ALICE, 160, 35, 216, False, (160, 0, 0, False, False)),
            ("explicit same HT refresh", WITH_BOB, BOB, 160, 35, 216, True, (200, 35, 1, False, True)),
            ("return to existing HT", returned_to_alice, BOB, 170, 35, 33, False, (170, 90, 1, True, False)),
            ("Return to existing HT", returned_to_alice, BOB, 170, 35, 216,
             False, (170, 170, 1, True, False)),
            ("zero species base", UNTRADED, BOB, 255, 0, 33, False, (255, 0, 1, True, True)),
            ("maximum species base", UNTRADED, BOB, 0, 255, 33, False, (0, 255, 1, True, True)),
        )
        for label, history, recipient, active, base, move, refresh, expected in cases:
            with self.subTest(label=label):
                old = replace(history)
                result = plan_friendship(history, recipient, active_friendship=active, base_friendship=base,
                                         moves=(move, 0, 0, 0), refresh_handler=refresh)
                self.assertEqual((result.history.original_friendship, result.history.handling_friendship,
                                  result.history.current_handler, result.handler_changed,
                                  result.initialized_handler), expected)
                self.assertEqual(result.friendship, expected[expected[2]])
                self.assertEqual(history, old)

    def test_original_matching_uses_every_identity_field(self):
        for recipient in (replace(ALICE, name=b"OTHER"), replace(ALICE, gender=1),
                          replace(ALICE, trainer_id=1), replace(ALICE, version=4)):
            with self.subTest(recipient=recipient):
                result = plan_friendship(WITH_BOB, recipient, active_friendship=160,
                                         base_friendship=70, moves=(0, 0, 0, 0), refresh_handler=False)
                self.assertEqual(result.history.current_handler, 1)
                self.assertEqual(result.friendship, 70)

    def test_unknown_and_incomplete_history_never_invents_opposite_friendship(self):
        for history in (replace(UNTRADED, known=False), replace(UNTRADED, known=1),
                        replace(UNTRADED, original_friendship=None), replace(UNTRADED, handling_friendship=None),
                        replace(UNTRADED, current_handler=None), replace(UNTRADED, current_handler=1),
                        replace(UNTRADED, handling_friendship=1), replace(UNTRADED, serial=0),
                        replace(UNTRADED, original_friendship=True), replace(UNTRADED, handler="BOB")):
            with self.subTest(history=history), self.assertRaises(FriendshipPlanError):
                plan_friendship(history, BOB, active_friendship=160, base_friendship=70,
                                moves=(216, 0, 0, 0), refresh_handler=False)

    def test_native_value_and_adapter_bounds(self):
        valid = dict(active_friendship=0, base_friendship=70, moves=(0, 0, 0, 0), refresh_handler=False)
        for field, values in (
            ("active_friendship", (-1, 256, True, None)), ("base_friendship", (-1, 256, False, None)),
            ("refresh_handler", (0, None, "false")),
            # Owner decision: stored later-generation moves (e.g. 633) trade as-is;
            # only values outside the pinned engine's move table are refused.
            ("moves", ((0, 0, 0), (848, 0, 0, 0), (-1, 0, 0, 0), (True, 0, 0, 0), [0, 0, 0, 0])),
        ):
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(FriendshipPlanError):
                    plan_friendship(UNTRADED, BOB, **(valid | {field: value}))
        for identity in (replace(BOB, name=b""), replace(BOB, name=b"12345678"),
                         replace(BOB, name=b"A\xff"), replace(BOB, gender=2),
                         replace(BOB, trainer_id=-1), replace(BOB, version=16)):
            with self.subTest(identity=identity), self.assertRaises(FriendshipPlanError):
                plan_friendship(UNTRADED, identity, **valid)
        result = plan_friendship(UNTRADED, BOB, **(valid | {"moves": (621, 0, 0, 0)}))
        self.assertEqual(result.friendship, 70)


class FriendshipRecordTests(unittest.TestCase):
    def test_exact_encrypted_transform_preserves_every_other_field_in_all_24_layouts(self):
        for pid in range(24):
            with self.subTest(pid=pid):
                mon = make_friendship_mon(pid)
                result, transition = transform_received_party_record(mon, UNTRADED, BOB,
                                                                      base_friendship=70, refresh_handler=False)
                old, new = decode_fixture(mon), decode_fixture(result)
                self.assertEqual(transition.friendship, 70)
                self.assertEqual(new[0][9], 70)
                old[0][9] = 70
                self.assertEqual(new, old)
                self.assertEqual(result[:28], mon[:28])
                self.assertEqual(result[30:32], mon[30:32])
                self.assertEqual(result[80:], mon[80:])
                self.assertEqual(struct.unpack_from("<H", result, 28)[0],
                                 sum(struct.unpack("<24H", b"".join(new))) & 0xFFFF)
                changed = [i for i, (left, right) in enumerate(zip(mon, result)) if left != right]
                growth_slot = tuple(permutations(range(4)))[pid].index(0)
                self.assertEqual([i for i in changed if i not in (28, 29)], [32+growth_slot*12+9])
                self.assertEqual(mon, make_friendship_mon(pid))

    def test_return_and_frustration_preserve_identical_record_even_with_uid_bits(self):
        for pid in range(24):
            for moves in ((0, 0, 216, 0), (0, 0, 0, 218)):
                with self.subTest(pid=pid, moves=moves):
                    mon = make_friendship_mon(pid, friendship=219, moves=moves)
                    result, transition = transform_received_party_record(mon, UNTRADED, BOB,
                                                                          base_friendship=70, refresh_handler=False)
                    self.assertEqual(result, mon)
                    self.assertEqual(transition.friendship, 219)
                    self.assertEqual(transition.history.serial, 0xFFFFF)

    def test_unknown_history_wrong_instance_and_origin_refuse_without_mutation(self):
        mon = make_friendship_mon()
        for history in (replace(UNTRADED, serial=5), replace(UNTRADED, original=BOB),
                        replace(UNTRADED, known=False), replace(UNTRADED, original_friendship=None)):
            with self.subTest(history=history), self.assertRaises(FriendshipPlanError):
                transform_received_party_record(mon, history, BOB, base_friendship=70, refresh_handler=False)
        self.assertEqual(mon, make_friendship_mon())

    def test_egg_header_and_secure_hatch_cycles_are_both_refused(self):
        mon = make_friendship_mon()
        header = bytearray(mon)
        header[19] |= 4
        logical = decode_fixture(mon)
        flags = struct.unpack_from("<I", logical[3], 4)[0]
        struct.pack_into("<I", logical[3], 4, flags | 1 << 30)
        for egg in (bytes(header), encode_fixture(mon, logical)):
            with self.subTest(egg=egg[19]), self.assertRaisesRegex(FriendshipPlanError, "eggs"):
                transform_received_party_record(egg, UNTRADED, BOB, base_friendship=70, refresh_handler=False)

    def test_invalid_and_mutable_records_are_refused(self):
        mon = make_friendship_mon()
        corrupt = bytearray(mon)
        corrupt[32] ^= 1
        for record in (bytes(corrupt), bytes(100), mon[:80], bytearray(mon), make_friendship_mon(serial=0)):
            with self.subTest(length=len(record)), self.assertRaises((FriendshipPlanError, FlashError)):
                transform_received_party_record(record, UNTRADED, BOB, base_friendship=70, refresh_handler=False)


if __name__ == "__main__":
    unittest.main()
