"""Controller operation cancellation; no native battle acceptance claim."""
import asyncio
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


script = Path(__file__).parents[1] / "scripts" / "multiplayer" / "native_resume_proof.py"
spec = importlib.util.spec_from_file_location("qualified_resume_controller", script)
controller = importlib.util.module_from_spec(spec)
with patch.object(sys, "path", [str(script.parent), *sys.path]):
    spec.loader.exec_module(controller)


class ResumeProofOperationDrainTests(unittest.IsolatedAsyncioTestCase):
    async def test_partial_quorum_preserves_failed_operation_instead_of_claiming_completion(self):
        failure = TimeoutError("retained recovery RPC expired while parsing history")
        async def failed():
            raise failure
        task = asyncio.create_task(failed())
        await asyncio.sleep(0)
        with self.assertRaises(TimeoutError) as caught:
            await controller.require_partial_recovery_waiting([task])
        self.assertIs(caught.exception, failure)

    async def test_partial_quorum_rejects_success_and_does_not_cancel_waiting_operation(self):
        waiting = asyncio.create_task(asyncio.Event().wait())
        try:
            await controller.require_partial_recovery_waiting([waiting])
            self.assertFalse(waiting.done())
            done = asyncio.get_running_loop().create_future()
            done.set_result(None)
            with self.assertRaisesRegex(AssertionError, "partial quorum completed"):
                await controller.require_partial_recovery_waiting([waiting, done])
            self.assertFalse(waiting.done())
        finally:
            waiting.cancel()
            await asyncio.gather(waiting, return_exceptions=True)

    async def test_reconnecting_operation_is_canceled_and_drained_without_touching_original_core_or_intent(self):
        with tempfile.TemporaryDirectory() as temporary:
            intent = Path(temporary) / "pending-battle.json"
            original = b"immutable original test admission\n"
            intent.write_bytes(original)
            core = object()
            owned_core = core
            entered, drained = asyncio.Event(), asyncio.Event()
            lifecycle = asyncio.Lock()
            async def reconnecting():
                async with lifecycle:
                    entered.set()
                    try:
                        while True:
                            try:
                                raise ConnectionError("host unavailable")
                            except ConnectionError:
                                await asyncio.sleep(.01)
                    finally:
                        await asyncio.sleep(0)
                        drained.set()
            task = asyncio.create_task(reconnecting())
            await entered.wait()
            await controller.drain_interrupted_operations([task, task], timeout=1)
            self.assertTrue(task.cancelled())
            self.assertTrue(drained.is_set())
            self.assertFalse(lifecycle.locked())
            self.assertIs(owned_core, core)
            self.assertEqual(intent.read_bytes(), original)

    async def test_slow_cleanup_times_out_before_a_new_operation_can_take_ownership(self):
        entered, release = asyncio.Event(), asyncio.Event()
        lifecycle = asyncio.Lock()
        async def slow_cleanup():
            async with lifecycle:
                entered.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    await release.wait()
        task = asyncio.create_task(slow_cleanup())
        await entered.wait()
        try:
            with self.assertRaises(TimeoutError):
                await controller.drain_interrupted_operations([task], timeout=.01)
            self.assertTrue(lifecycle.locked())
            self.assertFalse(task.done())
        finally:
            release.set()
            await task
        self.assertFalse(lifecycle.locked())
