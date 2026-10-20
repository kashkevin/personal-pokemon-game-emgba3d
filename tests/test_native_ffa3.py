"""Update 32: ABI3 phase 6, the three-player free-for-all (1v1v1); synthetic transport is not game acceptance.

The four-player free-for-all with its fourth place empty: three cores, four battlers (battler 3 has no trainer and no
Pokemon), every trainer alone on a side. Mirrors test_native_ffa.py and test_battle_ffa_desk.py for three trainers: the
envelope (three slots), the controller relay (three renderers, the winner one of the three), the roster, the desk
(three independent consents, results 1-3 or a draw 5, the free-for-all book, never the two-sided PvP archive) and the
Players menu rows.
"""
from dataclasses import replace
import struct
import unittest
from uuid import uuid4

from emerald_multiplayer.battle_controller import ControllerValidator
from emerald_multiplayer.battle_mailbox import BattleBinding, BattleMailboxError
from emerald_multiplayer.battle_protocol import validate_battle_request
from emerald_multiplayer.ffa_results import FfaResultError
from emerald_multiplayer.native_battle import (
    FFA3_PHASE, FFA_PHASE, Kind, NativeBinding, NativeControl, NativeQuery, Opcode, battler_count_for_phase,
    battler_owner, outcomes_for_phase, player_count_for_phase, supports_native_phase,
)
from emerald_multiplayer.protocol import ProtocolError
import test_battle_admission as admission_fixture
import test_battle_desk as fixture
import test_battle_ffa_desk as ffa_desk
import test_battle_roster as roster_fixture
from test_native_battle import query, uid
from test_battle_controller import wire, done, mon_reply


def binding(local=0):
    return NativeBinding(uid(99), tuple(uid(i+10) for i in range(3)), (7, 8, 9), (20, 21, 22), local, mode=FFA3_PHASE)


def control(local=0, **changes):
    bound = binding(local)
    return NativeControl(**{**dict(incarnation=20+local, session_epoch=7+local,
        battle_id=uid(90), sequence=1, opcode=Opcode.BIND, phase=FFA3_PHASE,
        source_slot=local, data=bound.pack()), **changes})


def validator():
    lengths = [None]*721
    lengths[7] = 10
    return ControllerValidator(tuple(lengths), mode=FFA3_PHASE)


class NativeFfa3EnvelopeTests(unittest.TestCase):
    def test_shape_three_trainers_four_battlers_and_an_empty_place(self):
        self.assertEqual((player_count_for_phase(FFA3_PHASE), battler_count_for_phase(FFA3_PHASE)), (3, 4))
        # Nobody plays battler 3 (the empty place): no core has slot 3.
        self.assertEqual([battler_owner(FFA3_PHASE, b) for b in range(4)], [0, 1, 2, 3])
        for abi, phase, expected in ((1, FFA3_PHASE, False), (2, FFA3_PHASE, False), (3, FFA3_PHASE, True),
                                      (3, 7, False), (True, FFA3_PHASE, False)):
            self.assertEqual(supports_native_phase(abi, phase), expected)
        self.assertEqual(outcomes_for_phase(FFA3_PHASE), (1, 2, 3, 5))
        self.assertEqual(outcomes_for_phase(FFA_PHASE), (1, 2, 3, 4, 5))
        self.assertEqual(outcomes_for_phase(2), (1, 2, 3))

    def test_three_independent_slots_require_exact_phase_and_count(self):
        for local in range(3):
            bound = binding(local)
            self.assertEqual(NativeBinding.unpack(bound.pack()), bound)
            self.assertEqual(bound.pack()[112:], bytes((3, local, FFA3_PHASE, 0)))
            self.assertEqual(bound.pack()[16+48:16+64], bytes(16))   # the fourth player's place stays empty
            request = control(local)
            request.validate_command(binding=bound, player_id=bound.players[local])
            response = replace(request, data=query(count=3, local=local, mode=FFA3_PHASE))
            response.validate_response(request)
            for count, mode in ((2, FFA3_PHASE), (4, FFA3_PHASE), (3, FFA_PHASE), (3, 3)):
                with self.assertRaises(BattleMailboxError):
                    NativeQuery.unpack(query(count=count, mode=mode))
            # four trainers are not a 1v1v1, three are not any other phase
            with self.assertRaises(BattleMailboxError):
                NativeBinding(uid(99), tuple(uid(i+10) for i in range(4)), (7, 8, 9, 10), (20, 21, 22, 23), 0,
                              mode=FFA3_PHASE)
            for mode in (2, 3, 4, FFA_PHASE):
                with self.assertRaises(BattleMailboxError):
                    replace(bound, mode=mode)
            wrong = bytearray(bound.pack()); wrong[114] = FFA_PHASE
            with self.assertRaises(BattleMailboxError): NativeBinding.unpack(bytes(wrong))
        # the diagnostic channel (ABI1) keeps its two or four trainers
        with self.assertRaises(BattleMailboxError):
            BattleBinding(uid(99), tuple(uid(i+10) for i in range(3)), (7, 8, 9), (20, 21, 22), 0)

    def test_a_win_names_one_of_the_three_slots_and_a_draw_is_five(self):
        for outcome in (0, 1, 2, 3, 5):
            flags = 1 if outcome == 0 else 1 | 8 | 16 | 32
            parsed = NativeQuery.unpack(query(count=3, local=1, mode=FFA3_PHASE, outcome=outcome, flags=flags,
                                              revision=1 if outcome else 0))
            self.assertEqual(parsed.outcome, outcome)
        for outcome in (4, 6, 255):     # 4 would name the empty place
            with self.assertRaises(BattleMailboxError):
                NativeQuery.unpack(query(count=3, mode=FFA3_PHASE, outcome=outcome, flags=1 | 8 | 16 | 32, revision=1))

    def test_release_carries_a_three_player_winner_word(self):
        for local in range(3):
            bound = binding(local)
            for outcome in (1, 2, 3, 5):
                release = control(local, opcode=Opcode.RELEASE, sequence=5, data=struct.pack("<II", 123, outcome))
                release.validate_command(binding=bound, player_id=bound.players[local])
            for outcome in (0, 4, 6):
                release = control(local, opcode=Opcode.RELEASE, sequence=5, data=struct.pack("<II", 123, outcome))
                with self.assertRaises(BattleMailboxError):
                    release.validate_command(binding=bound, player_id=bound.players[local])

    def test_receive_from_each_peer_and_ack_names_the_other_two(self):
        for local in range(3):
            bound = binding(local)
            for source in range(4):
                fields = dict(opcode=Opcode.RECEIVE, source_slot=source, kind=Kind.PARTY_2, block_sequence=3,
                              total_size=200, offset=128, data=bytes(72))
                if source == local or source == 3:     # nobody sends from the empty place
                    with self.assertRaises(BattleMailboxError): control(local, **fields).validate_command(binding=bound)
                else:
                    control(local, **fields).validate_command(binding=bound)
            ack = control(local, opcode=Opcode.ACK_OUT, kind=Kind.PARTY_2,
                block_sequence=3, total_size=200, offset=200, data=struct.pack("<II", 123, 7 ^ (1 << local)))
            ack.validate_command(binding=bound)
            for mask in (0, 1 << local, 7, 15 ^ (1 << local)):
                bad = replace(ack, data=struct.pack("<II", 123, mask))
                with self.assertRaises(BattleMailboxError): bad.validate_command(binding=bound)


class NativeFfa3ControllerTests(unittest.TestCase):
    def test_each_owner_reply_requires_all_three_renderers(self):
        for owner in range(3):
            v = validator().accept(wire(bytes(4), battler=owner, target=3, absent=8), 0)
            for source in range(3):
                if source != owner:
                    with self.assertRaises(BattleMailboxError):
                        v.accept(wire(mon_reply(), role=1, battler=owner), source)
            with self.assertRaises(BattleMailboxError): v.accept(done(owner, owner), owner)
            v.accept(wire(mon_reply(), role=1, battler=owner), owner)
            for source in range(2):
                v.accept(done(source, owner), source)
                self.assertEqual(v.pending[owner], 0)
            v.accept(done(2, owner), 2)
            self.assertEqual(v.pending, (None,)*4)

    def test_the_empty_place_is_rendered_by_all_three_and_answered_by_nobody(self):
        v = validator().accept(wire(bytes(4), battler=3), 0)
        for source in range(3):
            with self.assertRaises(BattleMailboxError):
                v.accept(wire(mon_reply(), role=1, battler=3), source)
        for source in range(3):
            v.accept(done(source, 3), source)
        self.assertEqual(v.pending, (None,)*4)

    def test_no_fourth_core_and_the_winner_is_one_of_the_three(self):
        with self.assertRaises(BattleMailboxError): validator().accept(wire(bytes((4, 0, 0, 0))), 3)
        for winner in (0, 1, 2, 255):
            validator().accept(wire(bytes((50, 1, winner, 0, 0, 0))), 0)
        for winner in (3, 4, 254):
            with self.assertRaises(BattleMailboxError): validator().accept(wire(bytes((50, 1, winner, 0, 0, 0))), 0)


class NativeFfa3RosterTests(unittest.TestCase):
    setUp = roster_fixture.CanonicalBattleRosterTests.setUp
    roster = roster_fixture.CanonicalBattleRosterTests.roster

    def test_descriptor_is_the_multi_trainer_block_with_one_of_three_slots(self):
        singles = self.roster()
        for source in range(3):
            roster = self.roster(source_slot=source, mode=FFA3_PHASE)
            self.assertEqual(roster.party, singles.party)
            self.assertEqual(struct.unpack_from("<IHH", roster.trainer_descriptor, 20), (0x2255, source, 2))
        with self.assertRaises(BattleMailboxError): self.roster(source_slot=3, mode=FFA3_PHASE)


class FreeForAll3DeskTests(unittest.TestCase):
    """Three of the fixture's four trainers in a 1v1v1 (trainer 3 stays out of it)."""
    tearDown = fixture.BattleDeskTests.tearDown
    actor = fixture.BattleDeskTests.actor
    call = fixture.BattleDeskTests.call
    descriptor = fixture.BattleDeskTests.descriptor
    control = fixture.BattleDeskTests.control
    query = fixture.BattleDeskTests.query
    bind = fixture.BattleDeskTests.bind
    prepare = fixture.BattleDeskTests.prepare
    start = fixture.BattleDeskTests.start
    parts = fixture.BattleDeskTests.parts
    finish = fixture.BattleDeskTests.finish
    assert_code = fixture.BattleDeskTests.assert_code
    outcome = 1

    def setUp(self):
        fixture.BattleDeskTests.setUp(self)
        self.call("cancel", 0)
        self.battle_id = str(uuid4())
        self.view = self.invite()
        self.generation = self.view["generation"]

    def invite(self, *, opponents=None, battle_id=None):
        return self.desk.invite_ffa3(*self.actor(0), opponents if opponents is not None else
            (self.players[1].player_id, self.players[2].player_id), battle_id or self.battle_id)

    def release(self, index, seq=4):
        request = self.control(index, Opcode.RELEASE, seq,
            data=struct.pack("<II", self.descriptor(index).party_crc32, self.outcome))
        response = replace(request, data=b"")
        return self.call("released", index, request, response), request, response

    def running(self):
        for i in (1, 2): self.call("accept", i, self.view["fingerprint"])
        for i in range(3): self.call("register", i, 100+i)
        for i in range(3): self.prepare(i)
        self.desk.authorize_start(self.battle_id, self.generation)
        for i in range(3): self.start(i); self.parts(i)
        return self.desk.authorize_running(self.battle_id, self.generation)

    def test_three_independent_trainers_and_their_own_consents(self):
        self.assertEqual(self.view["mode"], FFA3_PHASE)
        self.assertEqual(self.view["scope"], "session-local-native-free-for-all-3")
        self.assertEqual(self.view["teams"], [[p] for p in self.view["players"]])
        self.assertEqual(self.view["players"][0], self.players[0].player_id)
        self.assertEqual(sorted(self.view["players"]), sorted(p.player_id for p in self.players[:3]))
        for i in range(3):
            descriptor = self.descriptor(i)
            self.assertEqual(descriptor.mode, FFA3_PHASE)
            self.assertEqual(descriptor.source_slot, self.view["players"].index(self.players[i].player_id))
        self.assert_code("battle_not_participant", self.call, "accept", 3, self.view["fingerprint"])
        self.assertEqual(self.call("accept", 1, self.view["fingerprint"])["state"], "invited")
        self.assert_code("battle_state", self.call, "register", 1, 101)
        self.assertEqual(self.call("accept", 2, self.view["fingerprint"])["state"], "accepted")

    def test_exact_retry_and_wrong_rosters(self):
        ids = [p.player_id for p in self.players[1:3]]
        self.assertEqual(self.invite(opponents=tuple(reversed(ids))), self.view)
        self.assert_code("request_conflict", self.desk.invite_ffa, *self.actor(0),
                         (ids[0], ids[1], self.players[3].player_id), self.battle_id)
        for opponents in ((ids[0],), (ids[0], ids[0]), (self.players[0].player_id, ids[1]),
                          (ids[0], ids[1], self.players[3].player_id), [ids[0], ids[1]]):
            self.assert_code("invalid_battle", self.invite, opponents=opponents, battle_id=str(uuid4()))

    def test_win_draw_and_invalid_outcomes(self):
        for outcome in (0, 4, 6, True, None):
            fresh = type(self)("test_three_independent_trainers_and_their_own_consents")
            fresh.setUp()
            try:
                fresh.running()
                with self.subTest(outcome=outcome), self.assertRaises(Exception):
                    fresh.finish(0, outcome=outcome)
            finally:
                fresh.tearDown()
        for outcome in (1, 2, 3, 5):
            fresh = type(self)("test_three_independent_trainers_and_their_own_consents")
            fresh.setUp()
            try:
                fresh.running()
                for i in range(2):
                    fresh.finish(i, outcome=outcome)
                view, *_ = fresh.finish(2, outcome=outcome)
                self.assertEqual((view["outcome"], view["state"]), (outcome, "release_authorized"))
            finally:
                fresh.tearDown()

    def test_published_once_to_the_free_for_all_book_and_never_to_the_pvp_archive(self):
        published, archive = [], []
        self.desk.on_publish = lambda battle: published.append((next(iter(battle.finished.values())), battle.mode))
        self.desk.results = type("Archive", (), {"_append_closed": lambda self_, *a: archive.append(a),
                                                 "contains": lambda self_, battle_id: False})()
        self.running()
        self.outcome = 3
        for i in range(3):
            self.finish(i, outcome=3)
        for i in range(2):
            self.release(i)
        self.assertEqual(published, [])
        self.release(2)
        self.release(2)                                                    # an exact retry: still once
        self.assertEqual((published, archive), ([(3, FFA3_PHASE)], []))


class Ffa3BookTests(ffa_desk.FfaBookTests):
    def test_three_trainers_are_recorded_and_the_empty_place_never_wins(self):
        players = [str(uuid4()) for _ in range(3)]
        self.assertEqual(self.book.record("b1", 3, players), players[2])
        self.assertIsNone(self.book.record("b2", 5, players))
        with self.assertRaises(FfaResultError): self.book.record("b3", 4, players)
        with self.assertRaises(FfaResultError): self.book.record("b4", 1, players[:2])
        with self.assertRaises(FfaResultError): self.book.record("b5", 1, [players[0], players[0], players[1]])
        self.assertEqual(self.book.record_of(players[2]), dict(played=2, won=1, drawn=1, lost=0))


class Ffa3ProtocolTests(unittest.TestCase):
    def request(self, opponents):
        return dict(type="battle_invite_ffa3", request_id=str(uuid4()), session_epoch=3,
                    opponents=opponents, battle_id=str(uuid4()))

    def test_the_invitation_names_exactly_two_distinct_other_trainers(self):
        a, b, c = (str(uuid4()) for _ in range(3))
        self.assertEqual(validate_battle_request(self.request([a, b]), 3)["opponents"], [a, b])
        for opponents in ([a], [a, a], [a, b, c], "ab", [a, 7]):
            with self.assertRaises(ProtocolError):
                validate_battle_request(self.request(opponents), 3)


class NativeFfa3AdmissionTests(admission_fixture.CompanionBattleAdmissionTests):
    """The companion's native admission paths with a three-trainer binding (a game with the 1v1v1 marker)."""
    abi_version = 3
    native_phase = FFA3_PHASE

    async def asyncSetUp(self):
        await super().asyncSetUp()
        object.__setattr__(self.c.config, "battle_ffa3_enabled", True)

    async def test_an_older_game_without_the_1v1v1_never_gets_a_phase_6_command(self):
        object.__setattr__(self.c.config, "battle_ffa3_enabled", False)
        with self.assertRaisesRegex(ValueError, "matching ABI control"):
            await self.c.battle_rpc(replace(self.bind, opcode=Opcode.QUERY, data=b"", sequence=2))


if __name__ == "__main__":
    unittest.main()
