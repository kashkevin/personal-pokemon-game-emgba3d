"""Compose the registered saver with cleanup interruption boundaries.

Real save-controller and SQLite/Flash recovery; native commands use the strict
existing mailbox fixture. These are lifecycle tests, not native acceptance.
"""
import unittest
from unittest.mock import patch
from uuid import uuid4

from emerald_multiplayer.cold_start import ColdStartRecovery
from emerald_multiplayer.save_mailbox import Opcode
import test_emergency_save as fixture


class AdmissionCleanupEmergencyTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.EmergencySaveTests.asyncSetUp
    asyncTearDown = fixture.EmergencySaveTests.asyncTearDown
    arm = fixture.EmergencySaveTests.arm
    preserve = fixture.EmergencySaveTests.preserve
    closed = fixture.EmergencySaveTests.closed

    async def test_armed_successor_preserves_and_cold_reconciles_before_or_after_uncertain_handoff(self):
        await self.arm()
        # This is the flag set only after the cleanup successor's native arm,
        # grant, durable receipt and registration have all completed. The old
        # terminal pointer remains until HANDOFF's durable response arrives.
        self.controller._admission_cleanup_successor = True
        terminal = self.private / "retained.admission-cleanup.json"
        terminal.write_bytes(b"opaque old terminal evidence must not be changed")
        self.c._live_battle_terminal_pending_path = terminal
        handoff = self.private / "retained.admission-cleanup-handoff.json"
        handoff.write_bytes(b"opaque pending handoff evidence must not be changed")
        before = (terminal.read_bytes(), handoff.read_bytes(), self.save.read_bytes())
        result = await self.preserve()
        self.assertEqual(result.state, "preserved")
        self.assertTrue(result.can_close)
        self.assertEqual(self.c.emergency_commands[0].opcode, Opcode.BEGIN_EMERGENCY_EXPORT)
        self.assertTrue(any(c.opcode == Opcode.PRESERVE_EMERGENCY for c in self.c.emergency_commands))
        self.assertEqual((terminal.read_bytes(), handoff.read_bytes(), self.save.read_bytes()), before)
        self.assertTrue((self.private / "pending-emergency.json").exists())
        self.assertTrue((self.private / "pending-export.json").exists())
        fresh = self.closed()
        async with ColdStartRecovery(fresh, self.private, self.save).open() as recovered:
            self.assertEqual(recovered.mirror.revision, 2)
            self.assertEqual(self.save.read_bytes(), self.c.rom_flash)
        self.assertFalse((self.private / "pending-emergency.json").exists())
        self.assertFalse((self.private / "pending-export.json").exists())
        self.assertEqual((terminal.read_bytes(), handoff.read_bytes()), before[:2])

    async def test_corrupt_provisional_cleanup_evidence_still_freezes_original_offline_binding(self):
        await self.arm()
        pending = self.private / "pending-battle-admission.json"
        pending.write_bytes(b"corrupt original provisional evidence")
        result = await self.preserve()
        self.assertEqual(result.state, "unsaved_held")
        self.assertFalse(result.can_close)
        self.assertEqual([c.opcode for c in self.c.emergency_commands], [Opcode.BEGIN_EMERGENCY_EXPORT])
        self.assertTrue(self.c.emergency_active)
        self.assertEqual(pending.read_bytes(), b"corrupt original provisional evidence")
        self.assertFalse((self.private / "pending-export.json").exists())

    async def test_real_same_lease_retirement_and_successor_arm_revalidate_without_rebinding_progressed_core(self):
        from emerald_multiplayer.battle_admission_cleanup import (AdmissionCleanupCompletion, FORMAT,
            _command, _ready_control, cleanup_path)
        from emerald_multiplayer.battle_admission_cleanup_protocol import SCOPE as CLEANUP_SCOPE
        from emerald_multiplayer.battle_admission_intent import BattleAdmissionIntent, publish_admission_intent
        from emerald_multiplayer.battle_execution_protocol import encode_control
        from emerald_multiplayer.battle_protocol import SCOPE
        from emerald_multiplayer.battle_terminal import authenticated_session
        from emerald_multiplayer.emergency_save import EmergencySaveController
        from emerald_multiplayer.live_checkpoint import _atomic, _json_bytes
        from emerald_multiplayer.native_battle import NativeControl, Opcode as BattleOpcode
        from emerald_multiplayer.native_battle_resume import Admission
        await self.arm()
        c = self.c
        c.server_epoch = 1
        c.battle_incarnation = c.save_incarnation
        c._live_battle_runtime_id = str(uuid4())
        c._live_battle_owner = None
        battle_id, generation = str(uuid4()), str(uuid4())
        head = self.store.read_checkpoint(self.player.player_id, self.lease)
        players = sorted((self.player.player_id, str(uuid4())))
        challenge = dict(scope=SCOPE, battle_id=battle_id, generation=generation,
            sender=self.player.player_id, mode=2, state="accepted", reason=None,
            players=players, fingerprint="b" * 64, consent=players, outcome=None,
            checkpoints=[dict(player_id=player, source_slot=slot, revision=1, sha256=head.sha256, party_count=1)
                         for slot, player in enumerate(players)])
        intent = BattleAdmissionIntent(c.world_id, self.player.player_id, c.config.build_id,
            c.config.ruleset_id, c.save_profile, c.server_epoch, c.session_epoch, c.save_incarnation,
            c._live_battle_runtime_id, 1, head.sha256, _json_bytes(challenge),
            NativeControl(c.save_incarnation, c.session_epoch, battle_id, 1, BattleOpcode.ADMIT,
                phase=2, source_slot=players.index(self.player.player_id),
                data=Admission(generation, self.player.player_id, c._live_battle_runtime_id).pack()))
        session = authenticated_session(c)
        completion = AdmissionCleanupCompletion(battle_id, generation, 1, head.sha256, session)
        result = dict(scope=CLEANUP_SCOPE, battle_id=battle_id, generation=generation,
            incarnation=intent.incarnation, runtime_id=intent.runtime_id, original_lease=intent.lease_epoch,
            tombstone_sha256="a" * 64, acknowledged=False)
        # The protocol/native receipt itself is a fixture; the old controller
        # retirement and new arm below execute their real checks and native
        # save/ownership mailbox fixture against real SQLite/Flash data.
        held = _command(intent, session, result)
        terminal = dict(format=FORMAT, intent=intent.value(), session=session.value(), cancellation=result,
            ready_b64=encode_control(_ready_control(intent, session)), command_b64=encode_control(held),
            response_b64=encode_control(held), host_ack=True, previous_terminal=None)
        path = cleanup_path(self.private, intent)
        _atomic(path, _json_bytes(terminal))
        publish_admission_intent(self.private / (battle_id + ".canceled-admission-intent.json"), intent)
        c._live_battle_terminal_pending_path = path
        sequence = c._live_sequence
        binding = c._live_binding
        await self.controller.retire_after_admission_cleanup(completion, intent, c._bridge)
        self.assertEqual(c._live_binding, binding)
        self.assertEqual(c._live_sequence, sequence)
        self.assertIsNone(c._emergency_controller)
        original_rpc = c.save_rpc
        commands = []
        async def observe(control, **kwargs):
            commands.append(control.opcode)
            self.assertNotEqual(control.opcode, Opcode.BIND)
            return await original_rpc(control, **kwargs)
        successor = EmergencySaveController(c, self.private)
        with patch.object(c, "save_rpc", observe):
            armed = await successor.arm(1)
        self.assertEqual(armed.state, "armed")
        self.assertIn(Opcode.QUERY_OWNERSHIP, commands)
        self.assertTrue(successor._admission_cleanup_successor)
        self.assertIs(c._emergency_controller, successor)
        self.assertEqual(successor.session, binding)
        self.assertGreater(c._live_sequence, sequence)
        self.assertEqual(path.read_bytes(), _json_bytes(terminal))
        self.controller = successor


if __name__ == "__main__":
    unittest.main()
