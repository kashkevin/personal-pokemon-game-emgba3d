"""Compose real attempt storage/reset/emergency controllers with native fixtures.

These tests cover host-loss ordering, not an ordinary-route authored hunt.
The native endpoint remains the explicitly synthetic emergency Flash fixture.
"""
import asyncio
import struct
import unittest
from unittest.mock import patch
from uuid import uuid4

from emerald_multiplayer.cold_start import ColdStartError, ColdStartRecovery
from emerald_multiplayer.reset_attempts import ResetAttempts, enable_reset_attempts
from emerald_multiplayer.reset_mailbox import ResetRequest
from emerald_multiplayer.reset_session import ResetSession
from emerald_multiplayer.save_mailbox import Opcode
from emerald_multiplayer.trade_storage import TradeCheckpointStore
import test_emergency_save as emergency


class _ResetMailbox:
    def __init__(self, case):
        self.case = case
        self.packets = []
        self.ready = asyncio.Event()
        self.allow_field_return = False

    def receipt(self, state, *, attempt=0, ready=False):
        request = self.case.request
        return struct.pack("<8I", request.sequence, request.session,
                           request.incarnation, request.encounter, attempt,
                           state, int(ready), 0)

    def put_control(self, packet):
        self.packets.append(packet)
        self.ready.set()
        case = self.case
        if packet == b"U" + case.request.cancel():
            # The script has observed cancellation, but cannot yet be saved.
            case.reset.observe(self.receipt(4))
            if self.allow_field_return:
                self.finish_field_return()
        elif packet == b"U" + case.request.reply(1):
            case.reset.observe(self.receipt(2, attempt=1))
        else:
            raise AssertionError("unexpected native reset command")

    def finish_field_return(self):
        self.case.c.unsafe = False
        self.case.reset.observe(self.receipt(4, ready=True))


class ResetEmergencyIntegrationTests(unittest.IsolatedAsyncioTestCase):
    arm = emergency.EmergencySaveTests.arm
    closed = emergency.EmergencySaveTests.closed

    async def asyncSetUp(self):
        def reset_store(path, *args, **kwargs):
            store = TradeCheckpointStore(path, *args, **kwargs)
            enable_reset_attempts(store, path.with_suffix(".before-reset"))
            return store

        # Enable the extension on this new, idle disposable world before the
        # common emergency fixture creates any character or lease.
        with patch.object(emergency, "TradeCheckpointStore", reset_store):
            await emergency.EmergencySaveTests.asyncSetUp(self)
        await self.arm()
        self.c.config.reset_abi_version = 2
        self.outbox = _ResetMailbox(self)
        self.c._bridge.outbox = self.outbox
        self.reset = ResetSession(self.c, self.c._bridge)
        self.c._bridge.reset_session = self.reset
        self.request = ResetRequest(1, self.lease, self.c._bridge.incarnation, 0x1001, 0)
        self.reset_calls = []
        self.lose_ack = False
        self.c.unsafe = True

        async def reset_rpc(**fields):
            self.reset_calls.append(dict(fields))
            reply = ResetAttempts(self.store).begin(self.player.player_id, self.lease,
                dict(type="reset_begin", session_epoch=self.lease, **fields))
            if self.lose_ack:
                self.c.lose_host()
                raise asyncio.TimeoutError()
            return {"result": reply}

        self.c.reset_rpc = reset_rpc

    async def asyncTearDown(self):
        await self.reset.close()
        await emergency.EmergencySaveTests.asyncTearDown(self)

    def count(self):
        return self.store._connection.execute(
            "SELECT COUNT(*) FROM personal_reset_attempts").fetchone()[0]

    async def recover_closed(self, result):
        before = self.save.read_bytes()
        self.assertTrue(result.can_close)
        self.assertEqual(result.state, "preserved")
        self.assertEqual(self.store.read_checkpoint(self.player.player_id, self.lease).revision, 1)
        self.assertEqual(self.save.read_bytes(), before)
        fresh = self.closed()
        async with ColdStartRecovery(fresh, self.private, self.save).open() as recovered:
            self.assertEqual(recovered.mirror.revision, 2)
            self.assertEqual(self.save.read_bytes(), self.c.rom_flash)
        self.store.integrity_check()

    async def test_pending_admission_waits_for_exact_native_field_return_before_save(self):
        async with self.c.live_checkpoint_lock:
            self.reset.feed(self.request.pack())
            self.c.lose_host()
        await asyncio.wait_for(self.outbox.ready.wait(), 2)
        self.assertEqual(self.outbox.packets, [b"U" + self.request.cancel()])
        self.assertEqual(self.c.emergency_commands, [])
        self.assertFalse(self.controller.task.done())
        self.outbox.finish_field_return()
        result = await asyncio.wait_for(self.controller.drain(), 3)
        await self.reset.task
        self.assertEqual(self.reset_calls, [])
        self.assertEqual(self.count(), 0)
        self.assertEqual(self.c.emergency_commands[0].opcode, Opcode.BEGIN_EMERGENCY_EXPORT)
        await self.recover_closed(result)
        self.assertEqual(self.count(), 0)

    async def test_committed_but_lost_ack_keeps_attempt_after_cancel_save_and_rejoin(self):
        self.lose_ack = self.outbox.allow_field_return = True
        self.reset.feed(self.request.pack())
        await self.reset.task
        result = await asyncio.wait_for(self.controller.drain(), 3)
        self.assertEqual(len(self.reset_calls), 1)
        self.assertEqual(self.count(), 1)
        self.assertEqual(self.outbox.packets, [b"U" + self.request.cancel()])
        await self.recover_closed(result)
        # A fresh interaction sees the durable host count despite older local
        # count zero; cancellation never rolls the committed admission back.
        reply = ResetAttempts(self.store).begin(self.player.player_id, self.lease,
            dict(type="reset_begin", request_id=str(uuid4()), session_epoch=self.lease,
                 incarnation=3, sequence=1, encounter_id=0x1001, observed_count=0))
        self.assertEqual(reply["attempt"], 2)
        self.assertEqual(self.count(), 2)
        self.store.integrity_check()

    async def test_generation_ack_wins_loss_race_and_cannot_be_undone_for_saving(self):
        self.reset.feed(self.request.pack())
        await self.reset.task
        self.assertEqual(self.reset.receipt.state, 2)
        self.c.lose_host()
        result = await asyncio.wait_for(self.controller.drain(), 3)
        self.assertEqual(result.state, "unsaved_held")
        self.assertFalse(result.can_close)
        self.assertEqual(self.outbox.packets, [b"U" + self.request.reply(1)])
        self.assertEqual([c.opcode for c in self.c.emergency_commands], [Opcode.BEGIN_EMERGENCY_EXPORT])
        self.assertTrue(self.c.emergency_active)
        self.assertEqual(self.count(), 1)
        self.assertFalse((self.private / "pending-export.json").exists())
        fresh = self.closed()
        with self.assertRaises(ColdStartError):
            async with ColdStartRecovery(fresh, self.private, self.save).open():
                self.fail("a generated encounter cannot be replaced by its older save")


if __name__ == "__main__":
    unittest.main()
