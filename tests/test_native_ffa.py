"""ABI3 phase 5 (four-player free-for-all) contracts; synthetic transport is not game acceptance.

Mirrors test_native_multi.py for the four-core battle where every trainer is alone on a side: the same envelope, owner and
renderer barriers and journal rules, plus the free-for-all's own outcome word (winner slot + 1, or 5 for a draw).
"""
from dataclasses import replace
import struct
import unittest
from uuid import uuid4

from emerald_multiplayer.battle_controller import ControllerValidator
from emerald_multiplayer.battle_journal import BattleJournalError, read_battle_intent
from emerald_multiplayer.battle_mailbox import BattleMailboxError
from emerald_multiplayer.native_battle import (
    FFA_PHASE, NativeBinding, NativeControl, NativeQuery, Opcode, Kind, battler_count_for_phase, battler_owner,
    player_count_for_phase, supports_native_phase,
)
import test_battle_journal as journal_fixture
import test_battle_admission as admission_fixture
import test_battle_roster as roster_fixture
from test_native_battle import query, uid
from test_battle_controller import wire, done, message, mon_reply


def binding(local=0):
    return NativeBinding(uid(99), tuple(uid(i+10) for i in range(4)),
                         (7, 8, 9, 10), (20, 21, 22, 23), local, mode=FFA_PHASE)


def control(local=0, **changes):
    bound = binding(local)
    return NativeControl(**{**dict(incarnation=20+local, session_epoch=7+local,
        battle_id=uid(90), sequence=1, opcode=Opcode.BIND, phase=FFA_PHASE,
        source_slot=local, data=bound.pack()), **changes})


def validator():
    lengths = [None]*721
    lengths[7] = 10
    return ControllerValidator(tuple(lengths), mode=FFA_PHASE)


class NativeFfaEnvelopeTests(unittest.TestCase):
    def test_shape_four_trainers_four_battlers_one_each(self):
        self.assertEqual((player_count_for_phase(FFA_PHASE), battler_count_for_phase(FFA_PHASE)), (4, 4))
        self.assertEqual([battler_owner(FFA_PHASE, b) for b in range(4)], [0, 1, 2, 3])
        for abi, phase, expected in ((1, FFA_PHASE, False), (2, FFA_PHASE, False), (3, FFA_PHASE, True),
                                      (3, 6, False), (True, FFA_PHASE, False), (3, True, False)):
            self.assertEqual(supports_native_phase(abi, phase), expected)

    def test_four_independent_slots_require_exact_phase_and_count(self):
        for local in range(4):
            bound = binding(local)
            self.assertEqual(NativeBinding.unpack(bound.pack()), bound)
            self.assertEqual(bound.pack()[112:], bytes((4, local, FFA_PHASE, 0)))
            request = control(local)
            request.validate_command(binding=bound, player_id=bound.players[local])
            response = replace(request, data=query(count=4, local=local, mode=FFA_PHASE))
            response.validate_response(request)
            for count, mode in ((2, FFA_PHASE), (3, FFA_PHASE), (4, 4)):
                with self.assertRaises(BattleMailboxError):
                    NativeQuery.unpack(query(count=count, mode=mode))
            with self.assertRaises(BattleMailboxError):
                replace(bound, players=bound.players[:2], leases=bound.leases[:2],
                        incarnations=bound.incarnations[:2], local_slot=0)
            wrong = bytearray(bound.pack()); wrong[114] = 6
            with self.assertRaises(BattleMailboxError): NativeBinding.unpack(bytes(wrong))

    def test_a_win_names_the_winner_slot_and_a_draw_is_five_in_every_query(self):
        for outcome in (0, 1, 2, 3, 4, 5):
            flags = 1 if outcome == 0 else 1 | 8 | 16 | 32   # restored+started+result held for a decided battle
            parsed = NativeQuery.unpack(query(count=4, local=2, mode=FFA_PHASE, outcome=outcome, flags=flags, revision=1 if outcome else 0))
            self.assertEqual(parsed.outcome, outcome)
        for outcome in (6, 255):
            with self.assertRaises(BattleMailboxError):
                NativeQuery.unpack(query(count=4, mode=FFA_PHASE, outcome=outcome, flags=1 | 8 | 16 | 32, revision=1))
        for mode in (2, 3):   # the other formats keep their win/loss/draw words
            for outcome in (4, 5):
                with self.assertRaises(BattleMailboxError):
                    NativeQuery.unpack(query(count=4 if mode == 3 else 2, mode=mode, outcome=outcome,
                                             flags=1 | 8 | 16 | 32, revision=1))

    def test_release_carries_the_winner_word_only_in_a_free_for_all(self):
        for local in range(4):
            bound = binding(local)
            for outcome in (1, 2, 3, 4, 5):
                release = control(local, opcode=Opcode.RELEASE, sequence=5,
                                  data=struct.pack("<II", 123, outcome))
                release.validate_command(binding=bound, player_id=bound.players[local])
            for outcome in (0, 6):
                release = control(local, opcode=Opcode.RELEASE, sequence=5, data=struct.pack("<II", 123, outcome))
                with self.assertRaises(BattleMailboxError):
                    release.validate_command(binding=bound, player_id=bound.players[local])
        multi = NativeBinding(uid(99), tuple(uid(i+10) for i in range(4)), (7, 8, 9, 10), (20, 21, 22, 23), 0, mode=3)
        release = NativeControl(incarnation=20, session_epoch=7, battle_id=uid(90), sequence=5, opcode=Opcode.RELEASE,
                                phase=3, source_slot=0, data=struct.pack("<II", 123, 4))
        with self.assertRaises(BattleMailboxError):
            release.validate_command(binding=multi, player_id=multi.players[0])

    def test_receive_from_each_peer_and_ack_requires_all_three(self):
        for local in range(4):
            bound = binding(local)
            for source in range(4):
                receive = control(local, opcode=Opcode.RECEIVE, source_slot=source,
                    kind=Kind.PARTY_2, block_sequence=3, total_size=200, offset=128, data=bytes(72))
                if source == local:
                    with self.assertRaises(BattleMailboxError): receive.validate_command(binding=bound)
                else:
                    receive.validate_command(binding=bound)
            ack = control(local, opcode=Opcode.ACK_OUT, kind=Kind.PARTY_2,
                block_sequence=3, total_size=200, offset=200,
                data=struct.pack("<II", 123, 15 ^ (1 << local)))
            ack.validate_command(binding=bound)
            for mask in (0, 1 << local, 15):
                bad = replace(ack, data=struct.pack("<II", 123, mask))
                with self.assertRaises(BattleMailboxError): bad.validate_command(binding=bound)


class NativeFfaControllerTests(unittest.TestCase):
    def test_each_owner_reply_requires_all_four_renderers(self):
        for owner in range(4):
            v = validator().accept(wire(bytes(4), battler=owner, target=3, absent=15), 0)
            for source in range(4):
                if source != owner:
                    with self.assertRaises(BattleMailboxError):
                        v.accept(wire(mon_reply(), role=1, battler=owner), source)
            with self.assertRaises(BattleMailboxError): v.accept(done(owner, owner), owner)
            v.accept(wire(mon_reply(), role=1, battler=owner), owner)
            for source in range(3):
                v.accept(done(source, owner), source)
                self.assertEqual(v.pending[owner], 0)
                with self.assertRaises(BattleMailboxError): v.accept(done(source, owner), source)
            v.accept(done(3, owner), 3)
            self.assertEqual(v.pending, (None,)*4)

    def test_any_of_the_other_three_can_be_targeted_by_every_trainer(self):
        choose = bytes((19, 1))+bytes(42)
        for owner in range(4):
            for target in range(4):
                v = validator().accept(wire(choose, battler=owner), 0)
                choice = 3 | (target << 8)
                v.accept(wire(bytes((32, 10))+struct.pack("<I", choice), role=1, battler=owner), owner)
            for choice in (4, 0x400, 0x80000000, 0x7F):
                v = validator().accept(wire(choose, battler=owner), 0)
                with self.assertRaises(BattleMailboxError):
                    v.accept(wire(bytes((32, 10))+struct.pack("<I", choice), role=1, battler=owner), owner)

    def test_every_trainer_switches_among_their_own_six(self):
        for owner in range(4):
            for slot in range(6):
                request = bytes((21, 0, 6, 0, 0x10, 0x32, 0x54, 0, owner))
                v = validator().accept(wire(request, battler=owner), 0)
                v.accept(wire(bytes((33, slot, 0x10, 0x32, 0x54)), role=1, battler=owner), owner)
            with self.assertRaises(BattleMailboxError):   # nobody answers for another trainer's switch
                request = bytes((21, 0, 6, 0, 0x10, 0x32, 0x54, 0, owner))
                validator().accept(wire(request, battler=owner), 0).accept(
                    wire(bytes((33, 1, 0x10, 0x32, 0x54)), role=1, battler=owner), (owner + 1) % 4)

    def test_bounds_and_the_end_word(self):
        for kwargs in (dict(battler=4), dict(attacker=4), dict(target=4), dict(effect=4), dict(absent=16)):
            with self.assertRaises(BattleMailboxError): validator().accept(wire(bytes((4,0,0,0)), **kwargs),0)
        for source in (1, 2, 3, 4):
            with self.assertRaises(BattleMailboxError): validator().accept(wire(bytes((4,0,0,0))),source)
        for winner in (0, 1, 2, 3, 255):
            validator().accept(wire(bytes((50, 1, winner, 0, 0, 0))), 0)
        for winner in (4, 7, 254):
            with self.assertRaises(BattleMailboxError): validator().accept(wire(bytes((50, 1, winner, 0, 0, 0))), 0)


class NativeFfaRosterTests(unittest.TestCase):
    setUp = roster_fixture.CanonicalBattleRosterTests.setUp
    roster = roster_fixture.CanonicalBattleRosterTests.roster

    def test_descriptor_is_the_multi_trainer_block_with_its_own_source_slot(self):
        singles = self.roster()
        for source in range(4):
            roster = self.roster(source_slot=source, mode=FFA_PHASE)
            self.assertEqual(roster.party, singles.party)
            self.assertEqual(roster.mode, FFA_PHASE)
            self.assertEqual(struct.unpack_from("<IHH", roster.trainer_descriptor, 20), (0x2255, source, 2))
            with self.assertRaises(BattleMailboxError):
                roster.verify_startup(Kind.TRAINER, singles.trainer_descriptor)
            multi = self.roster(source_slot=source, mode=3)
            self.assertNotEqual(multi.mode, roster.mode)
        for kwargs in (dict(source_slot=4, mode=FFA_PHASE), dict(source_slot=0, mode=6)):
            with self.assertRaises(BattleMailboxError): self.roster(**kwargs)


class NativeFfaJournalTests(unittest.IsolatedAsyncioTestCase):
    tearDown = journal_fixture.BattleJournalTests.tearDown
    context = journal_fixture.BattleJournalTests.context
    write = journal_fixture.BattleJournalTests.write

    def setUp(self):
        journal_fixture.BattleJournalTests.setUp(self)
        self.c.config.battle_abi_version = 3
        local = 3
        self.binding = NativeBinding(str(uuid4()), tuple(str(uuid4()) for _ in range(3))+(self.c.config.player_id,),
            (11, 12, 13, self.c.session_epoch), (31, 32, 33, self.c.battle_incarnation), local, mode=FFA_PHASE)
        self.bind = replace(self.bind, phase=FFA_PHASE, source_slot=local, data=self.binding.pack())
        self.canonical = replace(self.canonical, source_slot=local, mode=FFA_PHASE)

    async def test_exact_four_trainer_intent_survives_uncertain_dispatch(self):
        with self.assertRaises(ConnectionError):
            async with self.context() as intent:
                self.assertEqual(read_battle_intent(self.journal.path), intent)
                self.assertEqual(NativeBinding.unpack(intent.bind.data), self.binding)
                raise ConnectionError("lost bind reply")
        raw = self.journal.path.read_bytes()
        await self.write()
        self.assertEqual(self.journal.path.read_bytes(), raw)
        self.c.config.battle_abi_version = 2
        with self.assertRaises(BattleJournalError): self.journal.load()
        self.assertEqual(self.journal.path.read_bytes(), raw)

    async def test_a_different_format_or_old_rom_cannot_publish_a_free_for_all(self):
        for mode in (2, 3):
            with self.assertRaises(BattleJournalError):
                async with self.context(canonical=replace(self.canonical, mode=mode)):
                    self.fail("mismatched canonical mode admitted")
        self.c.config.battle_abi_version = 2
        with self.assertRaises(BattleJournalError): await self.write()
        self.assertFalse(self.journal.path.exists())


class NativeFfaAdmissionTests(admission_fixture.CompanionBattleAdmissionTests):
    abi_version = 3
    native_phase = FFA_PHASE
