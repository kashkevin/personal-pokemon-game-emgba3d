from dataclasses import replace
import struct
import unittest
from uuid import UUID
import zlib

from emerald_multiplayer.battle_mailbox import BattleControl, BattleMailboxError, BattleQuery
from emerald_multiplayer.native_battle import (
    NativeBinding, NativeControl, NativeQuery, Preparation, Kind, Opcode,
    validate_block_size,
)


def uid(n): return str(UUID(int=n))


def binding(local=0):
    return NativeBinding(uid(99), (uid(10), uid(11)), (7, 8), (20, 21), local)


def control(**changes):
    return NativeControl(**{**dict(incarnation=20, session_epoch=7,
        battle_id=uid(90), sequence=1, opcode=Opcode.BIND, data=binding().pack()), **changes})


def query(**changes):
    fields = dict(flags=1, generation=UUID(uid(99)).bytes, count=2, local=0,
        mode=2, reserved=0, seq=1, out_seq=0, kind=0, size=0, crc=0, cursor=0,
        received=0, remaining=600, revision=0, outcome=0)
    fields.update(changes)
    return struct.pack("<I16sBBBB10I", *fields.values())


class NativeEnvelopeTests(unittest.TestCase):
    def test_two_person_immutable_binding_and_pinned_identity(self):
        for local in (0, 1):
            bound = binding(local)
            self.assertEqual(len(bound.pack()), 116)
            self.assertEqual(bound.pack()[112:], bytes((2, local, 2, 0)))
            self.assertEqual(NativeBinding.unpack(bound.pack()), bound)
            request = control(incarnation=20+local, session_epoch=7+local,
                              source_slot=local, data=bound.pack())
            request.validate_command(binding=bound, player_id=bound.players[local])
            for bad in (replace(request, session_epoch=9), replace(request, incarnation=25),
                        replace(request, source_slot=1-local)):
                with self.assertRaises(BattleMailboxError):
                    bad.validate_command(binding=bound)
            with self.assertRaises(BattleMailboxError):
                request.validate_command(binding=bound, player_id=uid(50))
        with self.assertRaises(BattleMailboxError):
            NativeBinding(uid(99), tuple(uid(i+1) for i in range(4)), (1, 2, 3, 4), (1, 2, 3, 4), 0)
        with self.assertRaises(BattleMailboxError):
            NativeBinding(uid(99), (uid(1), uid(1)), (1, 2), (1, 2), 0)
        for offset in (48, 88, 104, 114):
            raw = bytearray(binding().pack())
            raw[offset] ^= 1
            with self.assertRaises(BattleMailboxError):
                NativeBinding.unpack(bytes(raw))
        raw = bytearray(binding().pack()); raw[115] = 2
        with self.assertRaises(BattleMailboxError):
            NativeBinding.unpack(bytes(raw))

    def test_preparation_exact_counter_rng_and_reserved_fields(self):
        prep = Preparation(7, 0xFFFFFFFF, 0, 0, bytes(range(16)))
        self.assertEqual(len(prep.pack()), 36)
        self.assertEqual(Preparation.unpack(prep.pack()), prep)
        self.assertEqual(struct.unpack_from("<4I", prep.pack()), (7, 0xFFFFFFFF, 0, 0))
        for changed in (dict(checkpoint_revision=0), dict(checkpoint_revision=True),
                        dict(native_counter=-1), dict(trainer_id=1 << 32),
                        dict(party_crc32=False), dict(rng=bytes(16)),
                        dict(rng=bytes(15)), dict(rng=bytearray(16))):
            with self.subTest(changed=changed), self.assertRaises(BattleMailboxError):
                replace(prep, **changed)
        with self.assertRaises(BattleMailboxError):
            Preparation.unpack(prep.pack()[:-4]+struct.pack("<I", 1))

    def test_binary_envelope_crc_zero_tail_and_diagnostic_separation(self):
        value = control()
        raw = value.pack()
        self.assertEqual(len(raw), 240)
        self.assertEqual(raw[36:42], bytes((1, 0, 2, 0, 0, 0)))
        self.assertEqual(struct.unpack_from("<I", raw, 44)[0], zlib.crc32(value.data))
        self.assertEqual(NativeControl.unpack(raw).validate_command(), value)
        for offset in (41, 44, 239):
            broken = bytearray(raw)
            broken[offset] ^= 1
            with self.assertRaises(BattleMailboxError):
                NativeControl.unpack(bytes(broken))
        with self.assertRaises(BattleMailboxError):
            BattleControl.unpack(raw)
        for changed in (dict(phase=1), dict(source_slot=2), dict(opcode=3),
                        dict(opcode=7), dict(opcode=8), dict(kind=1),
                        dict(sequence=True), dict(total_size=257), dict(data=bytes(193))):
            with self.subTest(changed=changed), self.assertRaises(BattleMailboxError):
                replace(value, **changed)

    def test_party_and_controller_chunks_have_exact_boundaries_and_lengths(self):
        for kind, size in ((Kind.TRAINER, 28), (Kind.START_HEADER, 32),
                           (Kind.PARTY_0, 200), (Kind.PARTY_1, 200), (Kind.PARTY_2, 200),
                           (Kind.RNG, 16), (Kind.CONTROLLER, 156)):
            for offset in range(0, size, 128):
                length = min(128, size-offset)
                received = control(opcode=Opcode.RECEIVE, kind=kind, total_size=size,
                    offset=offset, block_sequence=1, source_slot=1, data=bytes(length))
                received.validate_command(binding=binding())
                read = replace(received, opcode=Opcode.READ_OUT, source_slot=0, data=b"")
                read.validate_command(binding=binding())
                replace(read, data=bytes(length)).validate_response(read)
                for bad in (replace(received, data=bytes(length-1)),
                            replace(received, data=bytes(length+1)),
                            replace(received, offset=1), replace(received, source_slot=0)):
                    with self.assertRaises(BattleMailboxError):
                        bad.validate_command(binding=binding())
                with self.assertRaises(BattleMailboxError):
                    replace(read, data=bytes(length-1)).validate_response(read)
        for kind, size in ((Kind.NONE, 0), (Kind.PARTY_0, 100), (Kind.RNG, 32),
                           (Kind.CONTROLLER, 128), (Kind.CONTROLLER, 256)):
            with self.assertRaises(BattleMailboxError):
                validate_block_size(kind, size)

    def test_ack_requires_full_read_offset_and_only_other_trainer(self):
        for local in (0, 1):
            bound = binding(local)
            ack = control(incarnation=20+local, session_epoch=7+local,
                source_slot=local, opcode=Opcode.ACK_OUT, kind=Kind.PARTY_0,
                total_size=200, offset=200, block_sequence=2,
                data=struct.pack("<II", 123, 1 << (1-local)))
            ack.validate_command(binding=bound)
            replace(ack, data=b"").validate_response(ack)
            for bad in (replace(ack, offset=128), replace(ack, block_sequence=0),
                        replace(ack, data=struct.pack("<II", 123, 3)),
                        replace(ack, data=struct.pack("<II", 123, 1 << local))):
                with self.assertRaises(BattleMailboxError):
                    bad.validate_command(binding=bound)

    def test_all_response_correlations_and_empty_error_payloads(self):
        request = control()
        response = replace(request, data=query())
        response.validate_response(request)
        for changed in (dict(incarnation=21), dict(session_epoch=8), dict(battle_id=uid(2)),
                        dict(sequence=2), dict(opcode=Opcode.KEEP), dict(block_sequence=1),
                        dict(total_size=200), dict(source_slot=1), dict(kind=Kind.PARTY_0)):
            with self.subTest(changed=changed), self.assertRaises(BattleMailboxError):
                replace(response, **changed).validate_response(request)
        error = replace(request, data=b"", status=1)
        error.validate_response(request)
        with self.assertRaises(BattleMailboxError):
            replace(error, data=b"x").validate_response(request)
        with self.assertRaises(BattleMailboxError):
            replace(response, data=query(generation=UUID(uid(5)).bytes)).validate_response(request)

    def test_prepare_and_start_responses_confirm_exact_revision_and_state(self):
        prep = Preparation(3, 5, 7, 9, bytes(range(16)))
        request = control(opcode=Opcode.PREPARE, data=prep.pack())
        request.validate_command(binding=binding())
        response = replace(request, data=query(flags=9, revision=3))
        response.validate_response(request)
        for payload in (query(), query(flags=9, revision=4), query(flags=25, revision=3),
                        query(flags=11, revision=3, remaining=0), query(seq=2, flags=9, revision=3)):
            with self.assertRaises(BattleMailboxError):
                replace(response, data=payload).validate_response(request)
        start = control(opcode=Opcode.START, data=b"")
        start.validate_command(binding=binding())
        replace(start, data=query(flags=25, revision=3)).validate_response(start)
        with self.assertRaises(BattleMailboxError):
            replace(start, data=query(flags=9, revision=3)).validate_response(start)

    def test_query_validates_hold_cursor_lifecycle_and_native_only_fields(self):
        self.assertIsNone(NativeQuery.unpack(bytes(64)).generation)
        NativeQuery.unpack(query(flags=0, remaining=0))
        live = NativeQuery.unpack(query(flags=29, revision=3, out_seq=4,
            kind=4, size=200, crc=123, cursor=128, received=3))
        self.assertTrue(live.prepared and live.started and live.outbound_pending)
        NativeQuery.unpack(query(flags=91, revision=3, remaining=0))
        NativeQuery.unpack(query(flags=57, revision=3, outcome=1))
        for changed in (dict(flags=128), dict(count=4), dict(local=2), dict(mode=1),
                        dict(reserved=1), dict(seq=0), dict(received=4), dict(remaining=601),
                        dict(flags=3), dict(flags=64), dict(flags=17), dict(flags=9),
                        dict(flags=41, revision=3), dict(flags=57, revision=3),
                        dict(revision=3), dict(outcome=1), dict(outcome=4),
                        dict(out_seq=1), dict(kind=4, size=200, out_seq=1, cursor=129)):
            with self.subTest(changed=changed), self.assertRaises(BattleMailboxError):
                NativeQuery.unpack(query(**changed))
        with self.assertRaises(BattleMailboxError):
            BattleQuery.unpack(query())

    def test_abort_release_and_other_operations_reject_extraneous_data(self):
        for op in (Opcode.QUERY, Opcode.KEEP, Opcode.START, Opcode.ABORT_PRE_START):
            request = control(opcode=op, data=b"")
            request.validate_command()
            with self.assertRaises(BattleMailboxError):
                replace(request, data=b"x").validate_command()
            with self.assertRaises(BattleMailboxError):
                replace(request, block_sequence=1).validate_command()
        for outcome in (1, 2, 3):
            request = control(opcode=Opcode.RELEASE, data=struct.pack("<II", 0, outcome))
            request.validate_command()
            replace(request, data=b"").validate_response(request)
        for outcome in (0, 4, 0xFFFFFFFF):
            with self.assertRaises(BattleMailboxError):
                control(opcode=Opcode.RELEASE, data=struct.pack("<II", 0, outcome)).validate_command()


if __name__ == "__main__":
    unittest.main()
