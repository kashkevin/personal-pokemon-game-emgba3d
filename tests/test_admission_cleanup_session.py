"""Real Companion binary IPC and durable cleanup files; synthetic native replies.

These tests qualify Python lifecycle authority and crash boundaries only.
"""
import asyncio
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from emerald_multiplayer.battle_admission_cleanup import (AdmissionCleanupSession,
    AdmissionCleanupCompletion, complete_cleanup_handoff, verify_cleanup_completion, cleanup_path)
from emerald_multiplayer.battle_admission_cleanup_protocol import SCOPE
from emerald_multiplayer.battle_admission_intent import FILENAME
from emerald_multiplayer.battle_execution_protocol import decode_control
from emerald_multiplayer.battle_journal import BattleJournalError
from emerald_multiplayer.battle_mailbox import response_packet
from emerald_multiplayer.bridge_protocol import encode_packet, read_packet
from emerald_multiplayer.native_battle import NativeControl, Opcode
import test_battle_recovery_session as fixture


class AdmissionCleanupSessionTests(unittest.IsolatedAsyncioTestCase):
    abi_version = 3
    query = fixture.RetainedBattleRecoveryTests.query
    accepted_challenge = fixture.RetainedBattleRecoveryTests.accepted_challenge
    seed_provisional = fixture.RetainedBattleRecoveryTests.seed_provisional
    successor_fixture = fixture.RetainedBattleRecoveryTests.successor_fixture

    async def asyncSetUp(self):
        await fixture.RetainedBattleRecoveryTests.asyncSetUp(self)
        self.journal.path.unlink()
        (self.directory / "native-battle-execution.json").unlink()
        self.intent, _ = self.seed_provisional()
        self.c.config.battle_admission_cleanup_abi_version = 1
        self.path = self.directory / FILENAME
        self.before = self.path.read_bytes()
        self.host_calls = []
        i = self.intent
        self.view = dict(scope=SCOPE, battle_id=i.battle_id, generation=i.generation,
            incarnation=i.incarnation, runtime_id=i.runtime_id, original_lease=i.lease_epoch,
            tombstone_sha256="a" * 64, acknowledged=False)

    async def host(self, operation, **fields):
        self.assertEqual(operation, "cancel_admission")
        self.host_calls.append(fields)
        ready = decode_control(fields["cleanup_ready_b64"], response=True)
        self.assertEqual(ready.opcode, Opcode.ADMISSION_CANCEL_READY)
        self.assertEqual(ready.session_epoch, self.c.session_epoch)
        return {"result": dict(self.view, acknowledged=fields["cleanup_receipt_b64"] is not None)}

    async def native(self, opcodes, *, refusal=None):
        commands = []
        async with asyncio.timeout(5):
            while len(commands) < len(opcodes):
                packet = await read_packet(self.bridge.reader)
                if packet[:1] != b"D":
                    self.assertEqual(packet[:1], b"S")
                    continue
                command = NativeControl.unpack(packet[1:])
                self.assertEqual(command.opcode, opcodes[len(commands)])
                command.validate_command(player_id=self.intent.player_id)
                commands.append(command)
                reply = replace(command, status=5, data=b"") if command.opcode == refusal else command
                self.bridge.writer.write(encode_packet(response_packet(reply)))
                await self.bridge.writer.drain()
        return commands

    async def run_cleanup(self, opcodes=(Opcode.ADMISSION_CANCEL_READY, Opcode.ADMISSION_CANCEL_HOLD), *, refusal=None):
        native = asyncio.create_task(self.native(opcodes, refusal=refusal)); self.tasks.append(native)
        try:
            with patch.object(self.c, "battle_challenge_rpc", self.host):
                result = await AdmissionCleanupSession(self.c, self.directory, self.intent).run()
            return result, await native
        finally:
            if not native.done():
                native.cancel()
                await asyncio.gather(native, return_exceptions=True)

    async def test_capacity_refusal_precedes_host_tombstone_and_keeps_original_intent(self):
        with self.assertRaises(BattleJournalError):
            await self.run_cleanup((Opcode.ADMISSION_CANCEL_READY,), refusal=Opcode.ADMISSION_CANCEL_READY)
        self.assertEqual(self.host_calls, [])
        self.assertEqual(self.path.read_bytes(), self.before)
        self.assertFalse(cleanup_path(self.directory, self.intent).exists())
        self.assertIsNone(self.c._live_battle_owner)

    async def test_ready_is_read_only_under_exact_other_menu_owner(self):
        owner = asyncio.create_task(asyncio.sleep(10)); self.tasks.append(owner)
        self.c._live_battle_owner = self.c._live_save_owner = owner
        original_executor = self.c._live_battle_executor = object()
        core = asyncio.create_task(self.native((Opcode.ADMISSION_CANCEL_READY,))); self.tasks.append(core)
        session = AdmissionCleanupSession(self.c, self.directory, self.intent)
        try:
            with patch.object(self.c, "battle_challenge_rpc", self.host):
                await session.revoke_before_menu_drain()
            await core
            self.assertIs(self.c._live_save_owner, owner)
            self.assertIs(self.c._live_battle_executor, original_executor)
            self.assertFalse(owner.done())
            self.assertEqual(self.path.read_bytes(), self.before)
            self.assertEqual(len(self.host_calls), 1)
        finally:
            self.c._live_battle_owner = self.c._live_save_owner = self.c._live_battle_executor = None

    async def test_cleanup_receipt_cannot_be_forged_or_used_as_battle_completion(self):
        completion, commands = await self.run_cleanup()
        self.assertIs(type(completion), AdmissionCleanupCompletion)
        self.assertFalse(self.path.exists())
        self.assertEqual((self.directory / (self.intent.battle_id + ".canceled-admission-intent.json")).read_bytes(), self.before)
        self.assertEqual(self.c._live_battle_terminal_pending_path, cleanup_path(self.directory, self.intent))
        value = verify_cleanup_completion(self.c, self.directory, completion, self.intent, self.c._bridge)
        self.assertTrue(value["host_ack"])
        for opcode in (Opcode.ADMISSION_CANCEL_READY, Opcode.ADMISSION_CANCEL_HOLD, Opcode.ADMISSION_CANCEL_HANDOFF):
            command = commands[0] if opcode == Opcode.ADMISSION_CANCEL_READY else replace(commands[1], opcode=opcode)
            with self.assertRaises(ValueError):
                await self.c.battle_rpc(command)
        with self.assertRaises(ValueError):
            verify_cleanup_completion(self.c, self.directory, replace(completion, canonical_revision=99), self.intent, self.c._bridge)

    async def test_lost_hold_receipt_and_host_ack_retries_never_skip_native_hold(self):
        original = self.c.battle_rpc
        async def lost(command, **kwargs):
            response = await original(command, **kwargs)
            if command.opcode == Opcode.ADMISSION_CANCEL_HOLD:
                raise asyncio.TimeoutError()
            return response
        with patch.object(self.c, "battle_rpc", lost), self.assertRaises(asyncio.TimeoutError):
            await self.run_cleanup()
        self.assertEqual(self.path.read_bytes(), self.before)
        value = json.loads(cleanup_path(self.directory, self.intent).read_bytes())
        self.assertIsNone(value["response_b64"])
        completion, _ = await self.run_cleanup()
        # Fully acknowledged retry queries capacity/current phase but never replays HOLD.
        again, commands = await self.run_cleanup((Opcode.ADMISSION_CANCEL_READY,))
        self.assertEqual(again, completion)
        self.assertEqual(len(commands), 1)

    async def test_host_ack_loss_keeps_pending_then_reuses_exact_successful_hold(self):
        original_host = self.host
        async def lost(operation, **fields):
            if fields["cleanup_receipt_b64"] is not None:
                raise ConnectionError("lost terminal ack")
            return await original_host(operation, **fields)
        self.host = lost
        with self.assertRaises(ConnectionError):
            await self.run_cleanup()
        self.assertEqual(self.path.read_bytes(), self.before)
        value = json.loads(cleanup_path(self.directory, self.intent).read_bytes())
        self.assertIsNotNone(value["response_b64"])
        self.assertFalse(value["host_ack"])
        self.host = original_host
        await self.run_cleanup((Opcode.ADMISSION_CANCEL_READY,))
        self.assertFalse(self.path.exists())

    async def test_fresh_saver_handoff_requires_durable_arm_and_preserves_hold_on_lost_reply(self):
        completion, _ = await self.run_cleanup()
        old = self.successor_fixture(completion)
        with self.assertRaises(ValueError):
            await old.retire_after_battle_recovery(completion, self.intent, self.c._bridge)
        result = await old.retire_after_admission_cleanup(completion, self.intent, self.c._bridge)
        self.assertEqual(result.state, "retired_after_admission")
        self.assertIsNone(self.c._emergency_controller)
        successor = self.successor_fixture(completion)
        successor.needs_arm = True
        with self.assertRaises(ValueError):
            await complete_cleanup_handoff(self.c, self.directory, completion, self.intent, self.c._bridge, successor)
        successor.needs_arm = False
        original = self.c.battle_rpc
        async def lost(command, **kwargs):
            await original(command, **kwargs)
            raise asyncio.TimeoutError()
        core = asyncio.create_task(self.native((Opcode.ADMISSION_CANCEL_HANDOFF,))); self.tasks.append(core)
        with patch.object(self.c, "battle_rpc", lost), self.assertRaises(asyncio.TimeoutError):
            await complete_cleanup_handoff(self.c, self.directory, completion, self.intent, self.c._bridge, successor)
        await core
        self.assertIsNotNone(self.c._live_battle_terminal_pending_path)
        core = asyncio.create_task(self.native((Opcode.ADMISSION_CANCEL_HANDOFF,))); self.tasks.append(core)
        await complete_cleanup_handoff(self.c, self.directory, completion, self.intent, self.c._bridge, successor)
        await core
        self.assertIsNone(self.c._live_battle_terminal_pending_path)
        with patch.object(self.c, "battle_rpc", side_effect=AssertionError("replayed completed handoff")):
            await complete_cleanup_handoff(self.c, self.directory, completion, self.intent, self.c._bridge, successor)

    async def test_new_lease_after_unlink_and_old_saver_retirement_keeps_exact_predecessors(self):
        completion, _ = await self.run_cleanup()
        old = self.successor_fixture(completion)
        await old.retire_after_admission_cleanup(completion, self.intent, self.c._bridge)
        self.assertEqual(self.c._live_binding, old.session)
        original_retirement = (self.directory / (self.intent.battle_id + ".admission-emergency-retirement.json")).read_bytes()
        original_lease = self.c.session_epoch
        self.c._disconnect_remote()
        renewed, _ = await self.run_cleanup()
        self.assertGreater(renewed.renewed_session.lease_epoch, original_lease)
        self.assertFalse(self.path.exists())
        value = json.loads(cleanup_path(self.directory, self.intent).read_bytes())
        self.assertEqual(value["previous_terminal"]["lease"], original_lease)
        verify_cleanup_completion(self.c, self.directory, renewed, self.intent, self.c._bridge)
        self.assertEqual((await old.retire_after_admission_cleanup(renewed, self.intent, self.c._bridge)).state,
            "retired_after_admission")
        self.assertIsNone(self.c._live_binding)
        self.assertEqual((self.directory / (self.intent.battle_id + ".admission-emergency-retirement.json")).read_bytes(), original_retirement)

    async def test_same_lease_retirement_preserves_progressed_native_save_binding_and_sequence(self):
        from emerald_multiplayer.live_checkpoint import LiveCheckpointCoordinator
        completion, _ = await self.run_cleanup()
        old = self.successor_fixture(completion)
        self.c._live_sequence = 407
        await old.retire_after_admission_cleanup(completion, self.intent, self.c._bridge)
        self.assertIsNone(self.c._emergency_controller)
        self.assertEqual(self.c._live_binding, old.session)
        self.assertEqual(self.c._live_sequence, 407)
        self.assertEqual((await old.retire_after_admission_cleanup(completion, self.intent, self.c._bridge)).state,
            "retired_after_admission")
        # Same native lease has already progressed. A duplicate BIND would be
        # correctly refused by the real core; the successor must reuse this
        # exact binding while its arm performs fresh head/ownership checks.
        coordinator = LiveCheckpointCoordinator(self.c, self.directory)
        with patch.object(self.c, "save_rpc", side_effect=AssertionError("duplicate progressed BIND")):
            await coordinator._bind(old.session)
        self.assertEqual(self.c._live_sequence, 407)
        self.c._live_binding = None
        with self.assertRaises(ValueError):
            await old.retire_after_admission_cleanup(completion, self.intent, self.c._bridge)

    async def test_host_loss_after_authorized_hold_dispatch_replays_hold_not_admit_or_emergency_export(self):
        # The host reply and original HOLD are durable, but the native receipt
        # is lost before local publication. The real old controller must finish
        # that exact hold offline, without serializing or dropping a candidate.
        original = self.c.battle_rpc
        async def lost(command, **kwargs):
            response = await original(command, **kwargs)
            if command.opcode == Opcode.ADMISSION_CANCEL_HOLD:
                raise asyncio.TimeoutError()
            return response
        with patch.object(self.c, "battle_rpc", lost), self.assertRaises(asyncio.TimeoutError):
            await self.run_cleanup()
        from emerald_multiplayer.battle_terminal import authenticated_session
        completion = AdmissionCleanupCompletion(self.intent.battle_id, self.intent.generation,
            self.intent.canonical_revision, self.intent.canonical_sha256, authenticated_session(self.c))
        old = self.successor_fixture(completion)
        echo = asyncio.create_task(self.native((Opcode.ADMISSION_CANCEL_HOLD,))); self.tasks.append(echo)
        self.c._disconnect_remote()
        result = await old.drain()
        await echo
        self.assertEqual(result.state, "battle_waiting")
        self.assertFalse(result.can_close)
        self.assertEqual(self.path.read_bytes(), self.before)
        self.assertFalse((self.directory / "pending-emergency.json").exists())
        self.assertFalse((self.directory / "pending-export.json").exists())
        self.assertIsNotNone(json.loads(cleanup_path(self.directory, self.intent).read_bytes())["response_b64"])
        await self.run_cleanup((Opcode.ADMISSION_CANCEL_READY, Opcode.ADMISSION_CANCEL_HOLD))


if __name__ == "__main__":
    unittest.main()
