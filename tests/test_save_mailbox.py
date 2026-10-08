from __future__ import annotations

from dataclasses import replace
import struct
import unittest
import uuid
import zlib

from emerald_multiplayer.bridge_protocol import encode_packet
from emerald_multiplayer.save_mailbox import (
    COMMAND_GEN_OFFSET, COMMAND_OFFSET, FLASH_SIZE, Opcode, RESPONSE_GEN_OFFSET,
    RESPONSE_OFFSET, SAVE_ABI_VERSION, SAVE_MAILBOX_MAGIC, SAVE_MAILBOX_SIZE,
    SAVE_SLOT_SIZE, SaveControl, SaveMailboxError, State, Status, TradeHold,
    capability_packet, command_packet, inspect_save_mailbox, parse_command_packet,
    parse_response_packet, response_packet, validate_capability_packet,
)


def control(**changes):
    values = dict(incarnation=1, session_epoch=7, request_id=str(uuid.UUID(int=1)),
                  sequence=1, offset=0, total_size=FLASH_SIZE, revision=0,
                  opcode=Opcode.BIND)
    return SaveControl(**{**values, **changes})


class SaveMailboxTests(unittest.TestCase):
    def test_wire_layout_crc_and_fixed_padding(self):
        value = control(opcode=Opcode.WRITE, data=bytes(range(128)), offset=128,
                        sequence=99, revision=2)
        payload = value.pack()
        self.assertEqual(len(payload), SAVE_SLOT_SIZE)
        self.assertEqual(struct.unpack_from("<II", payload), (1, 7))
        self.assertEqual(payload[8:24], uuid.UUID(value.request_id).bytes)
        self.assertEqual(struct.unpack_from("<IIII", payload, 24), (99, 128, FLASH_SIZE, 2))
        self.assertEqual(struct.unpack_from("<BBHI", payload, 40), (6, 0, 128, zlib.crc32(value.data)))
        self.assertEqual(payload[48:176], value.data)
        self.assertEqual(payload[176:], bytes(64))
        self.assertEqual(SaveControl.unpack(payload), value)
        self.assertEqual(parse_command_packet(command_packet(value)), value)
        self.assertLessEqual(len(encode_packet(command_packet(value))), 260)

    def test_corrupted_fields_crc_and_padding_are_rejected(self):
        payload = control(opcode=Opcode.WRITE, data=bytes(range(128))).pack()
        corruptions = [payload[:-1], bytes(4) + payload[4:],
                       payload[:42] + struct.pack("<H", 193) + payload[44:],
                       payload[:48] + bytes([payload[48] ^ 1]) + payload[49:],
                       payload[:-1] + b"\1", payload[:40] + b"\xff" + payload[41:]]
        for changed in corruptions:
            with self.subTest(length=len(changed)), self.assertRaises(SaveMailboxError):
                SaveControl.unpack(changed)
        for changes in (dict(incarnation=True), dict(session_epoch=0), dict(sequence=0),
                        dict(request_id=str(uuid.UUID(int=0))), dict(data=bytes(193)),
                        dict(opcode=True), dict(status=15), dict(total_size=131088)):
            with self.subTest(field=next(iter(changes))), self.assertRaises(SaveMailboxError):
                control(**changes)

    def test_exact_command_lengths_and_aligned_flash_chunks(self):
        self.assertEqual(control(opcode=Opcode.READ).validate_command().length, 0)
        data = struct.pack("<IIII", 0xAABBCCDD, 5, 13, 0x12345678)
        control(opcode=Opcode.BEGIN_IMPORT, data=data).validate_command()
        for value in (control(opcode=Opcode.READ, data=bytes(128)),
                      control(opcode=Opcode.READ, offset=1),
                      control(opcode=Opcode.READ, offset=FLASH_SIZE),
                      control(opcode=Opcode.WRITE, data=bytes(127)),
                      control(opcode=Opcode.BEGIN_IMPORT, data=bytes(8)),
                      control(opcode=Opcode.BEGIN_IMPORT, data=struct.pack("<IIII", 0, 0, 14, 0)),
                      control(status=Status.BUSY)):
            with self.assertRaises(SaveMailboxError):
                value.validate_command()

    def test_response_shapes_offset_echo_and_error_empty(self):
        for opcode, data in ((Opcode.BIND, b""), (Opcode.BEGIN_EXPORT, bytes(40)),
                             (Opcode.READ, bytes(128)), (Opcode.END, bytes(4)),
                             (Opcode.BEGIN_IMPORT, bytes(8)), (Opcode.WRITE, b""),
                             (Opcode.COMMIT, b""), (Opcode.CANCEL, b""), (Opcode.QUERY, bytes(48))):
            value = control(opcode=opcode, data=data, offset=128)
            self.assertEqual(parse_response_packet(response_packet(value)), value)
        error = control(opcode=Opcode.READ, status=Status.ORDER)
        self.assertEqual(parse_response_packet(response_packet(error)), error)
        with self.assertRaises(SaveMailboxError):
            response_packet(replace(error, data=b"x"))
        with self.assertRaises(SaveMailboxError):
            response_packet(control(opcode=Opcode.END))

    def test_complete_mailbox_header_seqlocks_and_empty_startup(self):
        header = struct.pack("<IHHIIII", SAVE_MAILBOX_MAGIC, SAVE_ABI_VERSION,
                             SAVE_MAILBOX_SIZE, 123, State.BOUND, 0, 0)
        payload = header + struct.pack("<I", 2) + control().pack() + struct.pack("<I", 4) + control().pack()
        self.assertEqual(len(payload), 512)
        value = inspect_save_mailbox(payload)
        self.assertEqual(value.state, State.BOUND)
        self.assertEqual(value.command, control())
        self.assertEqual(value.response, control())
        startup = inspect_save_mailbox(header + bytes(512 - 24))
        self.assertIsNone(startup.command)
        self.assertIsNone(startup.response)
        for offset in (COMMAND_GEN_OFFSET, RESPONSE_GEN_OFFSET):
            changed = payload[:offset] + struct.pack("<I", 3) + payload[offset + 4:]
            with self.assertRaises(SaveMailboxError):
                inspect_save_mailbox(changed)
        self.assertEqual((COMMAND_OFFSET, RESPONSE_OFFSET), (28, 272))
        with self.assertRaises(SaveMailboxError):
            inspect_save_mailbox(payload[:16] + b"\1" + payload[17:])

    def test_capability_keeps_legacy_frame_bound(self):
        self.assertEqual(capability_packet(), b"V" + struct.pack("<HHHH", 1, 512, 240, 192))
        validate_capability_packet(capability_packet())
        with self.assertRaises(SaveMailboxError):
            validate_capability_packet(b"V" + bytes(8))

    def test_trade_controls_preserve_slot_size_and_require_canonical_flash(self):
        for opcode, length in ((Opcode.BEGIN_TRADE_EXPORT, 40), (Opcode.KEEP_TRADE, 48),
                (Opcode.ABORT_TRADE, 0), (Opcode.RELEASE_TRADE, 4),
                (Opcode.REBIND_TRADE, 48), (Opcode.QUERY_TRADE, 48)):
            command = control(opcode=opcode, revision=2)
            self.assertEqual(parse_command_packet(command_packet(command)), command)
            response = replace(command, data=bytes(length))
            self.assertEqual(parse_response_packet(response_packet(response)), response)
            for bad in (replace(command, total_size=0), replace(command, offset=FLASH_SIZE), replace(command, data=b"x")):
                with self.assertRaises(SaveMailboxError):
                    command_packet(bad)
            with self.assertRaises(SaveMailboxError):
                response_packet(replace(response, data=bytes(length+1)))
        with self.assertRaises(SaveMailboxError):
            command_packet(control(opcode=Opcode.REBIND_TRADE, sequence=2))
        for revision in (0, 0x7fffffff):
            with self.assertRaises(SaveMailboxError):
                command_packet(control(opcode=Opcode.BEGIN_TRADE_EXPORT, revision=revision))
        header = struct.pack("<IHHIIII", SAVE_MAILBOX_MAGIC, 1, 512, 123, State.TRADE_HELD, 0, 0)
        self.assertEqual(inspect_save_mailbox(header + bytes(488)).state, State.TRADE_HELD)

    def test_trade_query_reports_actual_binding_without_treating_expiry_as_abort(self):
        def reply(**changes):
            values = dict(flags=7, phase=8, raw_id=uuid.UUID(int=1).bytes, epoch=7,
                          incarnation=3, revision=4, offset=128, crc=123, remaining=0)
            values.update(changes)
            return control(opcode=Opcode.QUERY_TRADE, session_epoch=8, revision=0,
                data=struct.pack("<II16sIIIIII", *values.values()))
        held = TradeHold.parse(reply())
        self.assertTrue(held.active and held.expired and held.import_started)
        self.assertEqual((held.session_epoch, held.revision, held.phase), (7, 4, State.TRADE_HELD))
        idle = TradeHold.parse(reply(flags=0, phase=1, raw_id=bytes(16), remaining=0))
        self.assertIsNone(idle.transaction_id)
        for changes in (dict(flags=8), dict(flags=2), dict(epoch=0), dict(incarnation=0),
                        dict(revision=0), dict(raw_id=bytes(16)), dict(phase=1),
                        dict(offset=3), dict(flags=0), dict(epoch=0xffffffff)):
            with self.subTest(changes=changes), self.assertRaises(SaveMailboxError):
                TradeHold.parse(reply(**changes))


if __name__ == "__main__":
    unittest.main()
