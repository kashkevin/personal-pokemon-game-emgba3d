import struct
import tempfile
from pathlib import Path
import unittest

from emerald_multiplayer.battle_controller import ControllerValidator, read_string_lengths
from emerald_multiplayer.battle_mailbox import BattleMailboxError
from emerald_multiplayer.native_battle import COOP_PHASE, FFA_PHASE, MULTI_PHASE


def wire(payload, *, role=0, battler=0, attacker=0, target=1, absent=0, effect=0):
    padded = len(payload)-len(payload)%4+4
    return struct.pack("<BBBBHBB", role, battler, attacker, target, padded, absent, effect) + payload + bytes(padded-len(payload))


def done(source, battler=0):
    return wire(bytes((source, 0, 0, 0)), role=2, battler=battler)


def validator():
    lengths = [None]*721
    lengths[7], lengths[8], lengths[9] = 10, 250, 256
    return ControllerValidator(tuple(lengths))


def message(buffer=b"\xff"):
    p = bytearray(80)
    p[0] = 15
    struct.pack_into("<H", p, 2, 7)
    for offset in (26, 44, 62):
        p[offset:offset+18] = buffer.ljust(18, b"\0")
    return bytes(p)


def mon_reply():
    p = bytearray(144)
    p[:4] = bytes((28, 28, 140, 0))
    struct.pack_into("<H", p, 4, 265)
    p[28:36] = bytes((6,)*8)
    struct.pack_into("<H", p, 46, 12)
    p[48] = 7
    struct.pack_into("<H", p, 50, 20)
    p[54], p[68] = 255, 255
    return bytes(p)


def ffa_validator(mode=FFA_PHASE):
    lengths = [None]*721
    lengths[7], lengths[8], lengths[9] = 10, 250, 256
    return ControllerValidator(tuple(lengths), mode=mode)


class FreeForAllControllerTests(unittest.TestCase):
    """Four battlers, four owners; the end-of-battle command carries the winner (the engine's FFA result)."""

    def end(self, outcome, winner):
        return wire(bytes((50, outcome, winner, 0, 0, 0)))

    def test_every_battler_has_its_own_owner_and_only_the_owner_replies(self):
        for battler in range(4):
            v = ffa_validator()
            v.accept(wire(bytes((0, 0, 0, 0)), battler=battler), 0)
            with self.assertRaises(BattleMailboxError):
                v.accept(wire(mon_reply(), role=1, battler=battler), (battler + 1) % 4)
            v.accept(wire(mon_reply(), role=1, battler=battler), battler)
            for source in range(4):
                v.accept(done(source, battler), source)
            self.assertEqual(v.pending, (None, None, None, None))

    def test_the_end_command_names_a_winning_battler_or_a_draw(self):
        for winner in (0, 1, 2, 3, 255):
            with self.subTest(winner=winner):
                ffa_validator().accept(self.end(1, winner), 0)
        for winner in (4, 5, 254):
            with self.subTest(winner=winner), self.assertRaises(BattleMailboxError):
                ffa_validator().accept(self.end(1, winner), 0)

    def test_other_formats_still_refuse_a_winner_byte(self):
        for mode in (MULTI_PHASE, COOP_PHASE):
            with self.subTest(mode=mode):
                ffa_validator(mode).accept(self.end(1, 0), 0)
                with self.assertRaises(BattleMailboxError):
                    ffa_validator(mode).accept(self.end(1, 2), 0)

    def test_nobody_but_the_master_may_end_the_battle(self):
        with self.assertRaises(BattleMailboxError):
            ffa_validator().accept(self.end(2, 1), 1)


class NativeControllerTests(unittest.TestCase):
    def test_request_reply_and_both_done_barrier(self):
        v = validator()
        request = wire(bytes((0, 0, 0, 0)), battler=1)
        v.accept(request, 0)
        self.assertEqual(v.pending, (None, 0))
        # A nonowner can finish rendering while the owner is still responding.
        v.accept(done(0, 1), 0)
        with self.assertRaises(BattleMailboxError):
            v.accept(done(1, 1), 1)
        reply = wire(mon_reply(), role=1, battler=1)
        with self.assertRaises(BattleMailboxError):
            v.accept(reply, 0)
        v.accept(reply, 1)
        with self.assertRaises(BattleMailboxError):
            v.accept(reply, 1)
        v.accept(done(1, 1), 1)
        self.assertEqual(v.pending, (None, None))
        with self.assertRaises(BattleMailboxError):
            v.accept(done(1, 1), 1)

    def test_master_source_unmatched_and_second_request_are_refused(self):
        v = validator()
        request = wire(bytes((4, 0, 0, 0)))
        with self.assertRaises(BattleMailboxError): v.accept(request, 1)
        with self.assertRaises(BattleMailboxError): v.accept(wire(mon_reply(), role=1), 0)
        self.assertEqual(v.pending, (None, None))
        v.accept(request, 0)
        with self.assertRaises(BattleMailboxError): v.accept(request, 0)
        v.accept(done(0), 0)
        self.assertEqual(v.pending, (4, None))
        v.accept(done(1), 1)
        v.accept(request, 0)

    def test_owner_must_reply_before_done_for_every_choice(self):
        requests = (bytes((17, 0, 0, 0)), bytes((19,))+bytes(43), bytes((21,))+bytes(8))
        replies = (bytes((32, 0, 0, 0, 0, 0)), bytes((32, 10, 0, 1, 0, 0)),
                   bytes((33, 1, 0x10, 0x32, 0x54)))
        for request, reply in zip(requests, replies):
            with self.subTest(command=request[0]):
                v = validator().accept(wire(request), 0)
                with self.assertRaises(BattleMailboxError): v.accept(done(0), 0)
                v.accept(wire(reply, role=1), 0)
                v.accept(done(0), 0).accept(done(1), 1)
                self.assertEqual(v.pending, (None, None))

    def test_raw_dma_unused_capture_bag_xp_and_unmatched_replies_are_refused(self):
        for command in (1, 3, 11, 12, 13, 18, 20, 22, 24, 27, 29, 30, 31, 34, 35, 51, 52):
            with self.subTest(command=command), self.assertRaises(BattleMailboxError):
                validator().accept(wire(bytes((command, 0, 0, 0))), 0)
        for field in (0, 4, 5, 13, 41, 43, 255):
            with self.subTest(field=field), self.assertRaises(BattleMailboxError):
                validator().accept(wire(bytes((2, field, 0, 0, 0))), 0)

    def test_first_turn_action_sentinel_and_ignored_item_are_canonical(self):
        v = validator().accept(wire(bytes((17, 255, 0, 0))), 0)
        # NONE belongs to the request; the owner must provide a real action.
        with self.assertRaises(BattleMailboxError):
            v.accept(wire(bytes((32, 255, 0, 0, 0, 0)), role=1), 0)
        v.accept(wire(bytes((32, 0, 0, 0, 0, 0)), role=1), 0)
        v.accept(done(0), 0).accept(done(1), 1)
        validator().accept(wire(bytes((17, 1, 105, 3))), 0)  # Last item ID873.
        for p in (bytes((17, 255, 28, 140)), bytes((17, 0, 1, 0)),
                  bytes((17, 1, 106, 3)), bytes((17, 254, 0, 0))):
            with self.subTest(payload=p), self.assertRaises(BattleMailboxError):
                validator().accept(wire(p), 0)

    def test_header_padding_masks_and_exact_size_are_checked_before_state(self):
        p = wire(bytes((4, 0, 0, 0)))
        broken = (p[:-1], p+b"\0", p[:-1]+b"\1",
            wire(bytes((4, 0, 0, 0)), battler=2), wire(bytes((4, 0, 0, 0)), attacker=2),
            wire(bytes((4, 0, 0, 0)), target=255), wire(bytes((4, 0, 0, 0)), effect=2),
            wire(bytes((4, 0, 0, 0)), absent=4), wire(bytes((4, 0, 0, 0)), role=3))
        for data in broken:
            v = validator()
            with self.assertRaises(BattleMailboxError): v.accept(data, 0)
            self.assertEqual(v.pending, (None, None))
        for payload in (bytes((0, 0, 3, 0)), bytes((0, 0, 64, 0)), bytes((0, 1, 0, 0))):
            with self.assertRaises(BattleMailboxError): validator().accept(wire(payload), 0)

    def test_text_tokens_have_real_terminators_and_bounded_expansion(self):
        for buffer in (b"\xff", bytes((253, 0, 7, 0, 255)),
                       bytes((253, 1, 4, 10, 1, 2, 3, 4, 255)),
                       bytes((253, 7, 1, 5, 255))):
            validator().accept(wire(message(buffer)), 0)
        bad = (bytes(18), bytes((252, 255)), bytes((253, 0, 6, 0, 255)),
               bytes((253, 0, 10, 0, 255)), bytes((253, 0, 9, 0, 255)),
               bytes((253, 0, 8, 0, 3, 1, 255)), bytes((253, 12, 255)),
               bytes((253, 1, 3, 2, 0, 0, 0, 255)), bytes((253, 7, 2, 5, 255)),
               bytes((253, 7, 1, 6, 255)), bytes((253, 3, 21, 255)),
               bytes((253, 2, 167, 3, 255)))  # Move935 is one beyond valid IDs.
        for buffer in bad:
            with self.subTest(buffer=buffer), self.assertRaises(BattleMailboxError):
                validator().accept(wire(message(buffer)), 0)

    def test_party_indices_status_fields_enum_limits_and_recording_are_bounded(self):
        valid = (bytes((5, 5, 1, 1)), bytes((25, 255, 31, 0, 0)),
                 bytes((41, 34)), bytes((48, 2, 0, 0)), bytes((49, 2)), bytes((50, 3, 0, 0, 0, 0)))
        for p in valid: validator().accept(wire(p), 0)
        bad = (bytes((5, 6, 1, 1)), bytes((6, 2)), bytes((25, 0, 32, 0, 0)),
               bytes((41, 35)), bytes((48, 2, 1, 0)), bytes((49, 3)), bytes((50, 1, 0, 0, 1, 0)))
        for p in bad:
            with self.subTest(command=p[0]), self.assertRaises(BattleMailboxError):
                validator().accept(wire(p), 0)

    def test_null_message_table_entry_and_move_heal_party_index_are_refused(self):
        p = bytearray(message())
        struct.pack_into("<H", p, 2, 10)
        with self.assertRaises(BattleMailboxError): validator().accept(wire(bytes(p)), 0)
        choice = bytearray(44)
        choice[0], choice[28] = 19, 6 << 2
        validator().accept(wire(bytes(choice)), 0)
        choice[28] = 7 << 2
        with self.assertRaises(BattleMailboxError): validator().accept(wire(bytes(choice)), 0)

    def test_animation_pid_is_not_a_timer_and_bitfields_are_bounded(self):
        anim = struct.pack("<IBBBB", 0xFFEEDDCC, 5, 5, 15, 0)
        validator().accept(wire(bytes((47, 1, 0, 0))+anim), 0)
        for changed in (anim[:4]+bytes((6, 5, 15, 0)), anim[:6]+bytes((16, 0)),
                        anim[:6]+bytes((64, 0)), anim[:-1]+b"\1"):
            with self.assertRaises(BattleMailboxError):
                validator().accept(wire(bytes((47, 1, 0, 0))+changed), 0)

    def test_mon_reply_enum_hp_name_and_stats_refused_without_consuming_request(self):
        valid = mon_reply()
        for offset, value in ((4, b"\0\0"), (48, b"\x65"), (28, b"\xff"), (54, b"\xfc"), (46, b"\xff")):
            p = bytearray(valid)
            p[offset:offset+len(value)] = value
            v = validator().accept(wire(bytes(4)), 0)
            with self.subTest(offset=offset), self.assertRaises(BattleMailboxError):
                v.accept(wire(bytes(p), role=1), 0)
            v.accept(wire(valid, role=1), 0)

    def test_reads_string_lengths_only_from_bounded_rom_table(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"fixture.gba"
            rom = bytearray(4096)
            struct.pack_into("<I", rom, 192+7*4, 0x08000F00)
            rom[3840:3844] = b"abc\xff"
            path.write_bytes(rom)
            lengths = read_string_lengths(path, table_address=0x080000C0)
            self.assertEqual(len(lengths), 721)
            self.assertEqual(lengths[7], 3)
            self.assertIsNone(lengths[0])
            ControllerValidator(lengths)
            struct.pack_into("<I", rom, 192+8*4, 0x02000000)
            path.write_bytes(rom)
            with self.assertRaises(BattleMailboxError): read_string_lengths(path, table_address=0x080000C0)
            for address in (0x080000C1, 0x08000F00, True):
                with self.assertRaises(BattleMailboxError): read_string_lengths(path, table_address=address)
