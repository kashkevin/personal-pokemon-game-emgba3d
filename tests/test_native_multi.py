"""ABI3 full-party Multi contracts; synthetic transport is not game acceptance."""
from dataclasses import replace
import struct
import unittest
from uuid import uuid4

from emerald_multiplayer.battle_controller import ControllerValidator
from emerald_multiplayer.battle_journal import BattleJournalError, read_battle_intent
from emerald_multiplayer.battle_mailbox import BattleMailboxError
from emerald_multiplayer.native_battle import (
    NativeBinding, NativeControl, NativeQuery, Opcode, Kind, supports_native_phase,
)
import test_battle_bridge as lua_fixture
import test_battle_journal as journal_fixture
import test_battle_admission as admission_fixture
import test_battle_roster as roster_fixture
import test_native_battle_transport as transport_fixture
from test_native_battle import query, uid
from test_battle_controller import wire, done, message, mon_reply


def binding(local=0):
    return NativeBinding(uid(99), tuple(uid(i+10) for i in range(4)),
                         (7, 8, 9, 10), (20, 21, 22, 23), local, mode=3)


def control(local=0, **changes):
    bound = binding(local)
    return NativeControl(**{**dict(incarnation=20+local, session_epoch=7+local,
        battle_id=uid(90), sequence=1, opcode=Opcode.BIND, phase=3,
        source_slot=local, data=bound.pack()), **changes})


def validator():
    lengths = [None]*721
    lengths[7] = 10
    return ControllerValidator(tuple(lengths), mode=3)


class NativeMultiEnvelopeTests(unittest.TestCase):
    def test_four_independent_slots_require_exact_phase_and_count(self):
        for local in range(4):
            bound = binding(local)
            self.assertEqual(NativeBinding.unpack(bound.pack()), bound)
            self.assertEqual(bound.pack()[112:], bytes((4, local, 3, 0)))
            request = control(local)
            request.validate_command(binding=bound, player_id=bound.players[local])
            response = replace(request, data=query(count=4, local=local, mode=3))
            response.validate_response(request)
            for count, mode in ((2, 3), (4, 2), (3, 3), (4, 4)):
                with self.assertRaises(BattleMailboxError):
                    NativeQuery.unpack(query(count=count, mode=mode))
            with self.assertRaises(BattleMailboxError):
                replace(bound, mode=2)
            with self.assertRaises(BattleMailboxError):
                replace(bound, players=bound.players[:2], leases=bound.leases[:2],
                        incarnations=bound.incarnations[:2], local_slot=0)
            wrong = bytearray(bound.pack()); wrong[114] = 2
            with self.assertRaises(BattleMailboxError): NativeBinding.unpack(bytes(wrong))
        for phase in (True, 1, 4):
            with self.assertRaises(BattleMailboxError): replace(binding(), mode=phase)
        for abi, phase, expected in ((1, 2, False), (2, 2, True), (2, 3, False),
                                      (3, 2, True), (3, 3, True), (4, 3, False),
                                      (True, 2, False), (3, True, False)):
            self.assertEqual(supports_native_phase(abi, phase), expected)

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
            for mask in range(16):
                if mask != 15 ^ (1 << local):
                    with self.assertRaises(BattleMailboxError):
                        replace(ack, data=struct.pack("<II", 123, mask)).validate_command(binding=bound)
        NativeQuery.unpack(query(count=4, local=3, mode=3, received=15))
        for changed in (dict(local=4), dict(received=16)):
            with self.assertRaises(BattleMailboxError):
                NativeQuery.unpack(query(count=4, mode=3, **changed))
        with self.assertRaises(BattleMailboxError):
            replace(control(), data=query()).validate_response(control())


class NativeMultiControllerTests(unittest.TestCase):
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

    def test_multi_move_targets_and_full_party_switches_are_owned(self):
        choose = bytes((19, 1))+bytes(42)
        for target in range(4):
            v = validator().accept(wire(choose, battler=3), 0)
            choice = 3 | (target << 8)
            v.accept(wire(bytes((32, 10))+struct.pack("<I", choice), role=1, battler=3), 3)
        for choice in (4, 0x400, 0x80000000, 0x7F):
            v = validator().accept(wire(choose, battler=3), 0)
            with self.assertRaises(BattleMailboxError):
                v.accept(wire(bytes((32, 10))+struct.pack("<I", choice), role=1, battler=3), 3)
        for owner in range(4):
            for slot in (3, 4, 5):
                request = bytes((21, 0, 6, 0, 0x10, 0x32, 0x54, 0, owner))
                v = validator().accept(wire(request, battler=owner), 0)
                v.accept(wire(bytes((33, slot, 0x10, 0x32, 0x54)), role=1, battler=owner), owner)

    def test_multi_bounds_cancel_partner_and_cross_phase_choices_refused(self):
        for kwargs in (dict(battler=4), dict(attacker=4), dict(target=4), dict(effect=4), dict(absent=16)):
            with self.assertRaises(BattleMailboxError): validator().accept(wire(bytes((4,0,0,0)), **kwargs),0)
        for source in (1, 2, 3, 4):
            with self.assertRaises(BattleMailboxError): validator().accept(wire(bytes((4,0,0,0))),source)
        with self.assertRaises(BattleMailboxError): validator().accept(wire(bytes((19,))+bytes(43)),0)
        v = validator().accept(wire(bytes((17,0,0,0)), battler=2),0)
        with self.assertRaises(BattleMailboxError):
            v.accept(wire(bytes((32,12,0,0,0,0)), role=1, battler=2),2)
        v.accept(wire(bytes((32,14,0,0,0,0)), role=1, battler=2),2)
        p = bytearray(message(bytes((253,7,3,5,255))))
        p[12],p[15]=3,3
        validator().accept(wire(bytes(p),target=3,effect=3),0)
        p[12]=4
        with self.assertRaises(BattleMailboxError): validator().accept(wire(bytes(p)),0)


class NativeMultiRosterTests(unittest.TestCase):
    setUp = roster_fixture.CanonicalBattleRosterTests.setUp
    roster = roster_fixture.CanonicalBattleRosterTests.roster

    def test_multi_descriptor_keeps_separate_canonical_party_and_source_id(self):
        singles = self.roster()
        for source in range(4):
            roster = self.roster(source_slot=source, mode=3)
            self.assertEqual(roster.party, singles.party)
            self.assertEqual(roster.mode, 3)
            self.assertEqual(struct.unpack_from("<IHH", roster.trainer_descriptor, 20), (0x2255, source, 2))
            with self.assertRaises(BattleMailboxError):
                roster.verify_startup(Kind.TRAINER, singles.trainer_descriptor)
        for kwargs in (dict(source_slot=4,mode=3),dict(source_slot=2),dict(mode=True)):
            with self.assertRaises(BattleMailboxError): self.roster(**kwargs)


class NativeMultiLuaTests(unittest.TestCase):
    lua_path = staticmethod(transport_fixture.NativeLuaTests.lua_path)
    run_lua = transport_fixture.NativeLuaTests.run_lua
    command = transport_fixture.NativeLuaTests.command
    response = transport_fixture.NativeLuaTests.response
    fixture = transport_fixture.NativeLuaTests.fixture

    def test_abi3_retains_all_phases_and_exact_capability(self):
        for phase in (1,2,3):
            sources = range(4) if phase == 3 else (0,)
            for source in sources:
                request = lua_fixture.control(phase=phase,source=source)
                response = lua_fixture.control(phase=phase,source=source,data=bytes(64))
                self.run_lua(self.fixture(3)+self.command(request)+self.response(response)+'''
local capability,replied=false,false
for _,p in ipairs(decoded()) do
 if p=="W"..string.pack("<I2I2I2I2",3,512,240,192) then capability=true end
 if p:sub(1,1)=="E" then replied=true end
end
assert(capability and replied and not stopped)
for _,a in ipairs(writes) do
 assert((a>=0x02001024 and a<=0x0200107c) or (a>=0x02003018 and a<=0x02003108))
end
''')

    def test_multi_ack_requires_all_peers_and_abi3(self):
        for source in range(4):
            request = lua_fixture.control(5,phase=3,source=source,block=1,offset=200,size=200,kind=4,
                data=struct.pack("<II",0,15 ^ (1 << source)))
            self.run_lua(self.fixture(3)+self.command(request)+'assert(not stopped)\n')
            for abi in (1,2):
                self.run_lua(self.fixture(abi)+self.command(request)+'assert(stopped)\n')
            for mask in (0,1 << source,15):
                bad = lua_fixture.control(5,phase=3,source=source,block=1,offset=200,size=200,kind=4,
                    data=struct.pack("<II",0,mask))
                self.run_lua(self.fixture(3)+self.command(bad)+'assert(stopped)\n')


class NativeMultiCompanionTests(transport_fixture.NativeCompanionTests):
    abi_version = 3

    def query(self):
        return replace(super().query(),phase=3,source_slot=3)

    async def test_abi2_rejects_multi_before_mailbox_dispatch(self):
        from emerald_multiplayer.companion import Companion
        c = Companion(replace(self.config))
        object.__setattr__(c.config,"battle_abi_version",2)
        with self.assertRaises(ValueError): await c.battle_rpc(self.query())
        self.assertFalse(c._battle_pending)


class NativeMultiJournalTests(unittest.IsolatedAsyncioTestCase):
    tearDown = journal_fixture.BattleJournalTests.tearDown
    context = journal_fixture.BattleJournalTests.context
    write = journal_fixture.BattleJournalTests.write

    def setUp(self):
        journal_fixture.BattleJournalTests.setUp(self)
        self.c.config.battle_abi_version = 3
        local=3
        self.binding=NativeBinding(str(uuid4()),tuple(str(uuid4()) for _ in range(3))+(self.c.config.player_id,),
            (11,12,13,self.c.session_epoch),(31,32,33,self.c.battle_incarnation),local,mode=3)
        self.bind=replace(self.bind,phase=3,source_slot=local,data=self.binding.pack())
        self.canonical=replace(self.canonical,source_slot=local,mode=3)

    async def test_exact_four_party_intent_survives_uncertain_dispatch(self):
        with self.assertRaises(ConnectionError):
            async with self.context() as intent:
                self.assertEqual(read_battle_intent(self.journal.path),intent)
                self.assertEqual(NativeBinding.unpack(intent.bind.data),self.binding)
                raise ConnectionError("lost bind reply")
        raw=self.journal.path.read_bytes()
        await self.write()
        self.assertEqual(self.journal.path.read_bytes(),raw)
        self.c.config.battle_abi_version=2
        with self.assertRaises(BattleJournalError): self.journal.load()
        self.assertEqual(self.journal.path.read_bytes(),raw)

    async def test_wrong_canonical_mode_or_old_rom_cannot_publish(self):
        with self.assertRaises(BattleJournalError):
            async with self.context(canonical=replace(self.canonical,mode=2)):
                self.fail("mismatched canonical mode admitted")
        self.c.config.battle_abi_version=2
        with self.assertRaises(BattleJournalError): await self.write()
        self.assertFalse(self.journal.path.exists())


class NativeMultiAdmissionTests(admission_fixture.CompanionBattleAdmissionTests):
    abi_version = 3
    native_phase = 3
