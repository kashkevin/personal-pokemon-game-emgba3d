from __future__ import annotations

from dataclasses import replace
import struct
import unittest
from uuid import UUID
import zlib

from emerald_multiplayer.battle_mailbox import (
    BATTLE_ABI_VERSION, BATTLE_MAILBOX_MAGIC, BATTLE_MAILBOX_SIZE, BATTLE_SLOT_SIZE,
    COMMAND_GEN_OFFSET, COMMAND_OFFSET, RESPONSE_GEN_OFFSET, RESPONSE_OFFSET,
    BattleBinding, BattleControl, BattleMailboxError, BattleQuery, DiagnosticBlock,
    Kind, Opcode, Phase, State, Status, capability_packet, command_packet,
    inspect_battle_mailbox, parse_command_packet, parse_response_packet,
    response_packet, validate_capability_packet,
)
from emerald_multiplayer.bridge_protocol import encode_packet
from emerald_multiplayer.protocol import MAX_COUNTER


def uid(number): return str(UUID(int=number))


def binding(count=2, local=0):
    return BattleBinding(uid(99), tuple(uid(2+i) for i in range(count)),
                         tuple(7+i for i in range(count)), tuple(11+i for i in range(count)), local)


def control(**changes):
    values = dict(incarnation=11, session_epoch=7, battle_id=uid(77), sequence=1,
                  opcode=Opcode.BIND, data=binding().pack())
    return BattleControl(**{**values, **changes})


def query(**changes):
    values = dict(flags=1, generation=UUID(uid(99)).bytes, count=2, local=0, mode=1,
        reserved=0, sequence=1, out_seq=0, kind=0, size=0, crc=0, cursor=0,
        received=0, remaining=600, r1=0, r2=0)
    v = {**values, **changes}
    return struct.pack("<I16sBBBB10I", *v.values())


class BattleMailboxTests(unittest.TestCase):
    def test_layout_matches_c_header_and_preserves_ipc_bound(self):
        block = DiagnosticBlock(uid(99), 1, 12345, 8, 12)
        value = control(opcode=Opcode.RECEIVE, source_slot=1, block_sequence=9,
                        total_size=40, kind=Kind.DIAGNOSTIC, data=block.pack())
        raw = value.pack()
        self.assertEqual(len(raw), 240)
        self.assertEqual(raw[8:24], UUID(value.battle_id).bytes)
        self.assertEqual(struct.unpack_from("<IIHH", raw, 24), (1, 9, 0, 40))
        self.assertEqual(struct.unpack_from("<6BHI", raw, 36), (6, 0, 1, 1, 1, 0, 40, zlib.crc32(block.pack())))
        self.assertEqual(raw[48:88], block.pack())
        self.assertEqual(raw[88:], bytes(152))
        self.assertEqual(BattleControl.unpack(raw), value)
        self.assertEqual(parse_command_packet(command_packet(value)), value)
        self.assertEqual(len(command_packet(value)), 241)
        self.assertLessEqual(len(encode_packet(command_packet(value))), 260)
        self.assertEqual((COMMAND_GEN_OFFSET, COMMAND_OFFSET, RESPONSE_GEN_OFFSET, RESPONSE_OFFSET), (24, 28, 268, 272))

    def test_control_counters_bools_uuid_and_native_size_bounds(self):
        changes = (dict(incarnation=0), dict(incarnation=True), dict(incarnation=1 << 32),
            dict(session_epoch=0), dict(session_epoch=MAX_COUNTER+1), dict(session_epoch=False),
            dict(sequence=0), dict(sequence=True), dict(block_sequence=-1), dict(offset=True),
            dict(total_size=257), dict(offset=1), dict(source_slot=4), dict(source_slot=True),
            dict(opcode=True), dict(status=False), dict(status=11), dict(phase=2), dict(kind=2),
            dict(battle_id=uid(0)), dict(battle_id=uid(77).upper()), dict(data=bytes(193)),
            dict(data=bytearray(116)))
        for changed in changes:
            with self.subTest(changed=changed), self.assertRaises(BattleMailboxError):
                control(**changed)

    def test_corrupted_crc_reserved_tail_and_committed_lengths_fail(self):
        raw = control().pack()
        cases = (raw[:-1], raw+b"x", bytes(4)+raw[4:], raw[:41]+b"\1"+raw[42:],
            raw[:42]+struct.pack("<H", 193)+raw[44:], raw[:48]+bytes([raw[48]^1])+raw[49:],
            raw[:-1]+b"\1", raw[:38]+b"\2"+raw[39:])
        for changed in cases:
            with self.subTest(size=len(changed)), self.assertRaises(BattleMailboxError):
                BattleControl.unpack(changed)

    def test_binding_roundtrip_and_authenticated_local_match_all_slots(self):
        for count in (2, 4):
            for local in range(count):
                bound = binding(count, local)
                self.assertEqual(len(bound.pack()), 116)
                self.assertEqual(BattleBinding.unpack(bound.pack()), bound)
                value = control(incarnation=11+local, session_epoch=7+local,
                                source_slot=local, data=bound.pack())
                value.validate_command(binding=bound, player_id=bound.players[local])
                with self.assertRaises(BattleMailboxError):
                    value.validate_command(player_id=uid(500))
                with self.assertRaises(BattleMailboxError):
                    replace(value, session_epoch=99).validate_command()

    def test_binding_duplicate_nil_unused_fields_and_mode_are_refused(self):
        for changed in (dict(players=(uid(2), uid(2))), dict(players=(uid(0), uid(3))),
                        dict(players=[uid(2), uid(3)]), dict(leases=(True, 8)),
                        dict(incarnations=(11, 0)), dict(local_slot=True), dict(local_slot=2)):
            values = dict(generation=uid(99), players=(uid(2), uid(3)), leases=(7, 8),
                          incarnations=(11, 12), local_slot=0)
            with self.subTest(changed=changed), self.assertRaises(BattleMailboxError):
                BattleBinding(**{**values, **changed})
        raw = binding().pack()
        for offset in (32+16, 80+8, 96+8, 112, 114, 115):
            changed = raw[:offset]+bytes([raw[offset]^1])+raw[offset+1:]
            with self.subTest(offset=offset), self.assertRaises(BattleMailboxError):
                BattleBinding.unpack(changed)

    def test_only_exact_typed_diagnostic_frames_accept_bound_source(self):
        frame = DiagnosticBlock(uid(99), 1, 0x02000000, 8, 12)
        self.assertEqual(len(frame.pack()), 40)
        self.assertEqual(DiagnosticBlock.unpack(frame.pack()).validate_binding(binding()), frame)
        for changed in (replace(frame, generation=uid(98)), replace(frame, source_slot=3),
                        replace(frame, lease=9), replace(frame, incarnation=13)):
            with self.assertRaises(BattleMailboxError):
                changed.validate_binding(binding())
        for raw in (bytes(40), frame.pack()[:-1], frame.pack()+bytes(160),
                    frame.pack()[:4]+struct.pack("<I", 2)+frame.pack()[8:]):
            with self.assertRaises(BattleMailboxError):
                DiagnosticBlock.unpack(raw)
        with self.assertRaises(BattleMailboxError):
            DiagnosticBlock(uid(99), 1, True, 8, 12)

    def test_operation_lengths_offsets_and_delivery_roles(self):
        frame = DiagnosticBlock(uid(99), 1, 5, 8, 12)
        commands = (
            control(), control(opcode=Opcode.QUERY, data=b""),
            control(opcode=Opcode.EMIT_DIAGNOSTIC, data=struct.pack("<I", 3)),
            control(opcode=Opcode.READ_OUT, block_sequence=1, total_size=40, kind=1, data=b""),
            control(opcode=Opcode.ACK_OUT, block_sequence=1, offset=40, total_size=40, kind=1,
                    data=struct.pack("<II", 123, 2)),
            control(opcode=Opcode.RECEIVE, block_sequence=1, total_size=40, kind=1,
                    source_slot=1, data=frame.pack()),
            control(opcode=Opcode.CLEAR_RX, data=struct.pack("<I", 3)),
            control(opcode=Opcode.CLOSE, data=b""), control(opcode=Opcode.KEEP, data=b""))
        for command in commands:
            self.assertEqual(command.validate_command(binding=binding()), command)
            with self.assertRaises(BattleMailboxError):
                replace(command, data=command.data+b"x").validate_command()
        bad = (replace(commands[1], kind=1), replace(commands[3], block_sequence=0),
               replace(commands[3], offset=1), replace(commands[3], total_size=200),
               replace(commands[4], data=struct.pack("<II", 123, 3)),
               replace(commands[5], source_slot=0), replace(commands[6], data=bytes(4)),
               replace(commands[6], data=struct.pack("<I", 4)))
        for command in bad:
            with self.assertRaises(BattleMailboxError):
                command.validate_command(binding=binding())

    def test_query_validates_closed_unbound_pending_and_expired_states(self):
        self.assertIsNone(BattleQuery.unpack(bytes(64)).generation)
        value = BattleQuery.unpack(query())
        self.assertTrue(value.held); self.assertFalse(value.expired)
        self.assertEqual(value.remaining_frames, 600)
        self.assertFalse(BattleQuery.unpack(query(flags=0, remaining=0)).held)
        self.assertTrue(BattleQuery.unpack(query(flags=3, remaining=0)).expired)
        value = BattleQuery.unpack(query(flags=5, out_seq=1, kind=1, size=40,
                                        crc=123, received=1))
        self.assertTrue(value.outbound_pending)
        for changes in (dict(flags=8), dict(count=3), dict(local=2), dict(mode=0),
                        dict(reserved=1), dict(r1=1), dict(generation=bytes(16)),
                        dict(sequence=0), dict(flags=2, remaining=0), dict(flags=3),
                        dict(flags=0), dict(remaining=601), dict(received=4),
                        dict(size=200), dict(kind=1), dict(crc=1), dict(flags=5),
                        dict(out_seq=1, size=40, kind=1, cursor=1)):
            with self.subTest(changes=changes), self.assertRaises(BattleMailboxError):
                BattleQuery.unpack(query(**changes))

    def test_responses_echo_every_correlation_field_and_errors_are_empty(self):
        request = control()
        response = replace(request, data=query())
        self.assertEqual(response.validate_response(request), response)
        self.assertEqual(parse_response_packet(response_packet(response)), response)
        for changed in (dict(incarnation=12), dict(session_epoch=8), dict(battle_id=uid(78)),
                        dict(sequence=2), dict(opcode=Opcode.KEEP), dict(source_slot=1),
                        dict(block_sequence=1), dict(kind=1), dict(total_size=40)):
            with self.subTest(changed=changed), self.assertRaises(BattleMailboxError):
                replace(response, **changed).validate_response(request)
        error = replace(request, status=Status.BUSY, data=b"")
        self.assertEqual(error.validate_response(request), error)
        with self.assertRaises(BattleMailboxError):
            replace(error, data=b"x").validate_response(request)
        with self.assertRaises(BattleMailboxError):
            replace(response, data=query(generation=UUID(uid(98)).bytes)).validate_response(request)

    def test_outbound_read_cannot_smuggle_remote_frame_or_unsupported_startup(self):
        request = control(opcode=Opcode.READ_OUT, block_sequence=1, total_size=40, kind=1, data=b"")
        frame = DiagnosticBlock(uid(99), 0, 3, 7, 11)
        response = replace(request, data=frame.pack())
        self.assertEqual(response.validate_response(request), response)
        for changed in (replace(frame, source_slot=1), replace(frame, lease=8),
                        replace(frame, incarnation=12)):
            with self.assertRaises(BattleMailboxError):
                replace(response, data=changed.pack()).validate_response(request)
        with self.assertRaises(BattleMailboxError):
            replace(response, data=bytes(128)).validate_response()
        with self.assertRaises(BattleMailboxError):
            replace(response, total_size=200).validate_response()

    def test_atomic_mailbox_and_zero_startup_slots(self):
        header = struct.pack("<IHHIIII", BATTLE_MAILBOX_MAGIC, BATTLE_ABI_VERSION,
                             BATTLE_MAILBOX_SIZE, 123, State.CHANNEL, 0, 0)
        payload = header + struct.pack("<I", 2) + control().pack() + struct.pack("<I", 4) + replace(control(), data=query()).pack()
        parsed = inspect_battle_mailbox(payload)
        self.assertEqual(parsed.state, State.CHANNEL)
        self.assertEqual(parsed.command, control())
        startup = header[:12]+struct.pack("<I", State.UNBOUND)+header[16:]+bytes(488)
        self.assertIsNone(inspect_battle_mailbox(startup).command)
        for offset in (24, 268):
            changed = payload[:offset]+struct.pack("<I", 3)+payload[offset+4:]
            with self.assertRaises(BattleMailboxError):
                inspect_battle_mailbox(changed)
        with self.assertRaises(BattleMailboxError):
            inspect_battle_mailbox(startup[:28]+b"x"+startup[29:])
        with self.assertRaises(BattleMailboxError):
            inspect_battle_mailbox(payload[:16]+b"\1"+payload[17:])

    def test_query_responses_confirm_local_role_and_active_mutators(self):
        for opcode in (Opcode.BIND, Opcode.QUERY, Opcode.EMIT_DIAGNOSTIC, Opcode.KEEP):
            response = control(opcode=opcode, data=query())
            response.validate_response()
            with self.subTest(opcode=opcode), self.assertRaises(BattleMailboxError):
                replace(response, data=query(local=1)).validate_response()
            if opcode != Opcode.QUERY:
                for payload in (query(flags=0, remaining=0), query(flags=3, remaining=0), bytes(64)):
                    with self.subTest(opcode=opcode), self.assertRaises(BattleMailboxError):
                        replace(response, data=payload).validate_response()
        control(opcode=Opcode.QUERY, data=bytes(64)).validate_response()
        control(opcode=Opcode.QUERY, data=query(flags=0, remaining=0)).validate_response()
        control(opcode=Opcode.QUERY, data=query(flags=3, remaining=0)).validate_response()

    def test_capability_and_packet_prefixes_are_separate_from_save(self):
        self.assertEqual(capability_packet(), b"W"+struct.pack("<HHHH", 1, 512, 240, 192))
        validate_capability_packet(capability_packet())
        for packet in (b"V"+capability_packet()[1:], b"W"+bytes(8), capability_packet()+b"x"):
            with self.assertRaises(BattleMailboxError):
                validate_capability_packet(packet)
        for packet in (b"C"+control().pack(), b"D"+bytes(239)):
            with self.assertRaises(BattleMailboxError):
                parse_command_packet(packet)
        with self.assertRaises(BattleMailboxError):
            parse_response_packet(b"R"+replace(control(), data=query()).pack())
