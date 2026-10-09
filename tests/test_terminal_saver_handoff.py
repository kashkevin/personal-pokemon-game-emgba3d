"""Real saver transfer against SQLite/Flash, with synthetic battle receipts."""
import base64
from dataclasses import replace
import struct
import unittest
from unittest.mock import patch
from uuid import uuid4

from emerald_multiplayer.battle_execution_protocol import encode_control
from emerald_multiplayer.battle_journal import BattleIntent
from emerald_multiplayer.battle_recovery_session import FORMAT, verify_recovery_completion
from emerald_multiplayer.battle_session import BattleCompletion
from emerald_multiplayer.battle_terminal import FORMAT as RETIRE_FORMAT, _control, _release, authenticated_session
from emerald_multiplayer.emergency_save import EmergencySaveController
from emerald_multiplayer.live_checkpoint import _atomic, _json_bytes
from emerald_multiplayer.native_battle import NativeBinding, NativeControl, Opcode as BattleOpcode
from emerald_multiplayer.save_mailbox import Opcode
import test_emergency_save as fixture


class TerminalSaverHandoffTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.EmergencySaveTests.asyncSetUp
    asyncTearDown = fixture.EmergencySaveTests.asyncTearDown
    arm = fixture.EmergencySaveTests.arm

    async def test_same_lease_normal_battle_retires_and_arms_without_replaying_progressed_save_bind(self):
        await self.arm()
        c = self.c
        c.server_epoch = 1
        c.battle_incarnation = c.save_incarnation
        c._live_battle_runtime_id = str(uuid4())
        c._live_battle_owner = None
        head = self.store.read_checkpoint(self.player.player_id, self.lease)
        players = tuple(sorted((self.player.player_id, str(uuid4()))))
        slot = players.index(self.player.player_id)
        binding = NativeBinding(str(uuid4()), players, (self.lease, self.lease),
            (c.save_incarnation, c.save_incarnation), slot, mode=2, resumable=True)
        bind = NativeControl(c.save_incarnation, c.session_epoch, str(uuid4()), 1,
            BattleOpcode.BIND, phase=2, source_slot=slot, data=binding.pack())
        intent = BattleIntent(c.world_id, self.player.player_id, c.config.build_id, c.config.ruleset_id,
            c.save_profile, c.server_epoch, c.session_epoch, c.save_incarnation, c._live_battle_runtime_id,
            binding.generation, bind.battle_id, 1, head.sha256, bind)
        session = authenticated_session(c)
        completion = BattleCompletion(intent.battle_id, intent.generation, 1, head.sha256, renewed_session=session)
        release = replace(bind, opcode=BattleOpcode.RELEASE, sequence=19, data=struct.pack("<II", 123, 1))
        encoded = encode_control(release)
        response = replace(release, data=b"")
        encoded_response = encode_control(response)
        terminal = dict(format=FORMAT, state="closed", intent=intent.value(), renewed_session=session.value(),
            binding_b64=base64.b64encode(binding.pack()).decode("ascii"), stage="route", dispatch_id=19,
            command_b64=encoded, response_b64=encoded_response, route_id=19,
            route_command_b64=encoded, route_response_b64=encoded_response,
            release_command_b64=encoded, release_response_b64=encoded_response)
        _atomic(self.private / (intent.battle_id + ".battle-recovery-complete.json"), _json_bytes(terminal))
        retired = _control(session, intent, _release(release, response, intent), BattleOpcode.RETIRE)
        native_retirement = dict(format=RETIRE_FORMAT, intent=intent.value(), session=session.value(),
            host_closed=True, release_command_b64=encoded, release_response_b64=encoded_response,
            command_b64=encode_control(retired), response_b64=encode_control(retired))
        path = self.private / (intent.battle_id + ".battle-retirement.json")
        _atomic(path, _json_bytes(native_retirement))
        c._live_battle_terminal_pending_path = path
        verify_recovery_completion(c, self.private, completion, intent, c._bridge)
        original_binding, sequence = c._live_binding, c._live_sequence
        await self.controller.retire_after_battle_recovery(completion, intent, c._bridge)
        self.assertIsNone(c._emergency_controller)
        self.assertEqual(c._live_binding, original_binding)
        self.assertEqual(c._live_sequence, sequence)
        self.assertEqual((await self.controller.retire_after_battle_recovery(completion, intent, c._bridge)).state,
            "retired_after_battle")
        original_rpc = c.save_rpc
        commands = []
        async def observe(control, **kwargs):
            commands.append(control.opcode)
            # The pinned native save ABI permits an exact original BIND replay
            # only before any following save command. It must not be reset here.
            self.assertNotEqual(control.opcode, Opcode.BIND)
            return await original_rpc(control, **kwargs)
        successor = EmergencySaveController(c, self.private)
        with patch.object(c, "save_rpc", observe):
            armed = await successor.arm(1)
        self.assertEqual(armed.state, "armed")
        self.assertIn(Opcode.QUERY_OWNERSHIP, commands)
        self.assertIs(c._emergency_controller, successor)
        self.assertEqual(c._live_binding, original_binding)
        self.assertGreater(c._live_sequence, sequence)
        self.assertEqual(path.read_bytes(), _json_bytes(native_retirement))
        self.controller = successor


if __name__ == "__main__":
    unittest.main()
