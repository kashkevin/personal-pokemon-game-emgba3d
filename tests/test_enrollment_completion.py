"""Enrollment completion at the native child/connection shutdown boundary."""
import asyncio
import json
import unittest
from unittest.mock import patch

from emerald_multiplayer.checkpoint_mirror import MirrorLease, MirrorError
from emerald_multiplayer.player_runtime import _stop
from emerald_multiplayer.save_mailbox import Opcode
import test_enrollment_runtime as fixture


class EnrollmentCompletionTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.EnrollmentRuntimeTests.asyncSetUp
    asyncTearDown = fixture.EnrollmentRuntimeTests.asyncTearDown
    runtime = fixture.EnrollmentRuntimeTests.runtime
    spawn = fixture.EnrollmentRuntimeTests.spawn
    assert_original = fixture.EnrollmentRuntimeTests.assert_original

    def bridge_eof(self):
        self.c._bridge = None
        self.c._disconnect_remote()
        if self.c._remote_writer is not None:
            self.c._remote_writer.close()

    async def test_own_stop_revokes_connection_after_verified_export_but_completes_receipt(self):
        runtime = self.runtime()
        async def stop_and_disconnect(process):
            await _stop(process)
            self.bridge_eof()
        with patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn), \
                patch("emerald_multiplayer.enrollment_runtime._stop", stop_and_disconnect):
            async with runtime.open() as game:
                result = await runtime.enroll()
                self.assertIsNotNone(game.process.returncode)
                self.assertEqual(result.metadata["revision"], 1)
                self.assertFalse(runtime.pending_path.exists())
                receipt = json.loads(runtime.receipt_path.read_text())
                self.assertEqual(receipt["checkpoint"], result.metadata)
                with self.assertRaises(MirrorError):
                    with MirrorLease(self.save): pass
        with MirrorLease(self.save): pass
        self.assert_original()

    async def test_bridge_loss_before_native_completion_retains_both_intents(self):
        runtime = self.runtime()
        async def disconnect(control):
            if control.opcode == Opcode.END:
                self.bridge_eof()
        self.native.hook = disconnect
        with patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn):
            async with runtime.open():
                with self.assertRaises(ConnectionError):
                    await runtime.enroll()
                self.assertTrue(runtime.pending_path.exists())
                self.assertTrue((self.private / "pending-export.json").exists())
                self.assertFalse(runtime.receipt_path.exists())
        self.assert_original()

    async def test_repeated_cancel_during_owned_stop_drains_without_publishing_receipt(self):
        runtime = self.runtime()
        entered, finish = asyncio.Event(), asyncio.Event()
        async def held_stop(process):
            entered.set()
            await finish.wait()
            await _stop(process)
            self.bridge_eof()
        with patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn), \
                patch("emerald_multiplayer.enrollment_runtime._stop", held_stop):
            async with runtime.open() as game:
                task = asyncio.create_task(runtime.enroll())
                try:
                    await asyncio.wait_for(entered.wait(), 10)
                    task.cancel(); await asyncio.sleep(0); task.cancel()
                    await asyncio.sleep(0)
                    self.assertFalse(task.done())
                    with self.assertRaises(MirrorError):
                        with MirrorLease(self.save): pass
                finally:
                    finish.set()
                    with self.assertRaises(asyncio.CancelledError): await task
                self.assertIsNotNone(game.process.returncode)
                self.assertTrue(runtime.pending_path.exists())
                self.assertFalse(runtime.receipt_path.exists())
        self.assert_original()
