"""Co-op Gym battles (native phase 4): two linked trainers against two AI Gym
trainers run by the master core. Real SQLite/Flash fixtures with correlated
fake native receipts; the actual-core battle is a separate proof."""
from __future__ import annotations

from dataclasses import replace
import struct
import unittest
from uuid import uuid4

from emerald_multiplayer.battle_controller import ControllerValidator
from emerald_multiplayer.battle_mailbox import BattleMailboxError
from emerald_multiplayer.native_battle import (
    COOP_PHASE, MULTI_PHASE, PHASE, NativeBinding, Preparation, battler_count_for_phase, battler_owner,
    player_count_for_phase, supports_native_phase,
)
import test_battle_desk as fixture
from test_battle_controller import mon_reply, wire


class CoopPhaseTests(unittest.TestCase):
    def test_phase_shape(self):
        self.assertEqual((player_count_for_phase(COOP_PHASE), battler_count_for_phase(COOP_PHASE)), (2, 4))
        self.assertEqual((player_count_for_phase(MULTI_PHASE), battler_count_for_phase(MULTI_PHASE)), (4, 4))
        self.assertEqual((player_count_for_phase(PHASE), battler_count_for_phase(PHASE)), (2, 2))
        # Slot 0 (master) owns its own battler and both AI foes; slot 1 owns battler 2.
        self.assertEqual([battler_owner(COOP_PHASE, b) for b in range(4)], [0, 0, 1, 0])
        self.assertEqual([battler_owner(MULTI_PHASE, b) for b in range(4)], [0, 1, 2, 3])
        self.assertTrue(supports_native_phase(3, COOP_PHASE))
        self.assertFalse(supports_native_phase(2, COOP_PHASE))
        for phase in (1, 5, True):
            with self.subTest(phase=phase), self.assertRaises(BattleMailboxError):
                player_count_for_phase(phase)

    def test_preparation_carries_the_gym(self):
        prep = Preparation(1, 2, 3, 4, bytes(range(1, 17)), gym=7)
        self.assertEqual(Preparation.unpack(prep.pack()).gym, 7)


def done(source, battler=0):
    return wire(bytes((source, 0, 0, 0)), role=2, battler=battler)


class CoopControllerTests(unittest.TestCase):
    def validator(self):
        lengths = [None] * 721
        lengths[7], lengths[8], lengths[9] = 10, 250, 256
        return ControllerValidator(tuple(lengths), mode=COOP_PHASE)

    def test_four_battlers_two_cores_and_owner_replies(self):
        v = self.validator()
        self.assertEqual(len(v.pending), 4)
        # The teammate's battler (2) answers from core 1 only.
        v.accept(wire(bytes((0, 0, 0, 0)), battler=2), 0)
        with self.assertRaises(BattleMailboxError):
            v.accept(wire(mon_reply(), role=1, battler=2), 0)
        v.accept(wire(mon_reply(), role=1, battler=2), 1)
        v.accept(done(0, 2), 0)
        self.assertEqual(v.pending[2], 0)  # both cores must finish rendering
        v.accept(done(1, 2), 1)
        self.assertEqual(v.pending, (None, None, None, None))
        # AI foes (1 and 3) answer from the master core.
        for battler in (1, 3):
            v.accept(wire(bytes((0, 0, 0, 0)), battler=battler), 0)
            with self.assertRaises(BattleMailboxError):
                v.accept(wire(mon_reply(), role=1, battler=battler), 1)
            v.accept(wire(mon_reply(), role=1, battler=battler), 0)
            v.accept(done(0, battler), 0).accept(done(1, battler), 1)

    def action_reply(self, battler, source, action, choice, mode=COOP_PHASE):
        lengths = [None] * 721
        lengths[7], lengths[8], lengths[9] = 10, 250, 256
        v = ControllerValidator(tuple(lengths), mode=mode)
        v.accept(wire(bytes((17, 0, 0, 0)), battler=battler), 0)
        try:
            v.validate(wire(struct.pack("<BBI", 32, action, choice), role=1, battler=battler), source)
        except BattleMailboxError:
            return False
        return True

    def test_ai_foes_move_action_carries_its_default_target(self):
        # The two-player launcher proof's refused block (2026-10-13): Norman's
        # partner (battler 3, run by the master's AI) chose a move action with
        # its default Struggle target, the opposing player battler 2.
        self.assertTrue(self.action_reply(3, 0, 0, 2 << 8))
        self.assertTrue(self.action_reply(1, 0, 0, 0 << 8))
        self.assertTrue(self.action_reply(1, 0, 0, 2 << 8))
        for choice in (1 << 8, 3 << 8, 4 << 8, (2 << 8) | 1, 0x80, 0x10200):
            with self.subTest(choice=hex(choice)):
                self.assertFalse(self.action_reply(3, 0, 0, choice))
        self.assertFalse(self.action_reply(3, 0, 2, 2 << 8))  # a target only with a move action
        self.assertFalse(self.action_reply(3, 1, 0, 2 << 8))  # only the master answers for a foe
        # Trainers' own battlers still send no target, in co-op and full Multi.
        self.assertTrue(self.action_reply(2, 1, 0, 0))
        self.assertFalse(self.action_reply(2, 1, 0, 1 << 8))
        self.assertFalse(self.action_reply(0, 0, 0, 1 << 8))
        self.assertFalse(self.action_reply(3, 3, 0, 2 << 8, mode=MULTI_PHASE))
        self.assertTrue(self.action_reply(3, 3, 0, 0, mode=MULTI_PHASE))

    def test_no_third_or_fourth_core(self):
        v = self.validator()
        with self.assertRaises(BattleMailboxError):
            v.accept(wire(bytes((0, 0, 0, 0)), battler=0), 2)
        with self.assertRaises(BattleMailboxError):
            v.accept(done(3, 0), 3)


class CoopDeskTests(unittest.TestCase):
    setUp = fixture.BattleDeskTests.setUp
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
    release = fixture.BattleDeskTests.release
    assert_code = fixture.BattleDeskTests.assert_code

    def coop(self, gym=1, battle_id=None, actor=0, teammate=2):
        self.call("cancel", 0)
        self.battle_id = battle_id or str(uuid4())
        self.view = self.desk.invite_coop(*self.actor(actor), self.players[teammate].player_id, gym, self.battle_id)
        self.generation = self.view["generation"]
        return self.view

    def test_view_slots_and_consent(self):
        view = self.coop(gym=7)
        self.assertEqual((view["mode"], view["gym"]), (4, 7))
        self.assertEqual(view["players"], [self.players[0].player_id, self.players[2].player_id])
        self.assertEqual(view["teams"], [view["players"]])
        self.assertEqual(view["consent"], [self.players[0].player_id])
        for index, slot in ((0, 0), (2, 1)):
            descriptor = self.descriptor(index)
            self.assertEqual((descriptor.mode, descriptor.source_slot), (4, slot))
            # Co-op links two trainers: the ordinary two-player link type.
            self.assertEqual(struct.unpack_from("<H", descriptor.trainer_descriptor, 20)[0], 0x2211)
        accepted = self.call("accept", 2, view["fingerprint"])
        self.assertEqual(accepted["state"], "accepted")

    def test_consent_names_the_exact_gym(self):
        first = self.coop(gym=1)
        self.assert_code("request_conflict", self.desk.invite_coop, *self.actor(0),
                         self.players[2].player_id, 2, self.battle_id)
        self.assertEqual(self.desk.invite_coop(*self.actor(0), self.players[2].player_id, 1, self.battle_id), first)
        for gym in (0, 9, True, "1"):
            with self.subTest(gym=gym):
                self.assert_code("invalid_battle", self.desk.invite_coop, *self.actor(1),
                                 self.players[3].player_id, gym, str(uuid4()))
        self.assert_code("invalid_battle", self.desk.invite_coop, *self.actor(1),
                         self.players[1].player_id, 1, str(uuid4()))
        self.assert_code("battle_offer_changed", self.call, "accept", 2, "0" * 64)

    def test_preparation_binding_and_full_lifecycle_without_results_archive(self):
        self.coop(gym=3)
        self.call("accept", 2, self.view["fingerprint"])
        for index in (0, 2):
            self.call("register", index, 100 + index)
        for index in (0, 2):
            binding = self.call("authorize_bind", index)
            raw = binding.pack()
            self.assertEqual(raw[114], COOP_PHASE)
            self.assertEqual(NativeBinding.unpack(raw), binding)
            request = self.control(index, fixture.Opcode.BIND, 1, data=raw)
            self.call("bound", index, request, replace(request, data=self.query(index, 1)))
            preparation = self.call("preparation", index)
            self.assertEqual(preparation.gym, 3)
            request = self.control(index, fixture.Opcode.PREPARE, 2, data=preparation.pack())
            self.call("prepared", index, request, replace(request, data=self.query(index, 2, 9, revision=1)),
                      self.descriptor(index).trainer_descriptor)
        self.desk.authorize_start(self.battle_id, self.generation)
        for index in (0, 2):
            self.start(index)
            self.parts(index)
        self.desk.authorize_running(self.battle_id, self.generation)
        for index in (0, 2):
            self.finish(index, outcome=1)
        for index in (0, 2):
            result, _, _ = self.release(index)
        self.assertEqual(result["state"], "closed")
        # Co-op Gym battles are not PvP records.
        if self.desk.results is not None:
            self.assertFalse(self.desk.results.contains(self.battle_id))


if __name__ == "__main__":
    unittest.main()
