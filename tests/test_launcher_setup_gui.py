import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest

from emerald_multiplayer.launcher_setup_gui import SetupEvent, SetupWorker, SetupWindow


class Controller:
    def __init__(self):
        self.opened, self.closed, self.enrolled = threading.Event(), threading.Event(), threading.Event()
        self.cleanup = threading.Event()
        self.cleanup.set()
        self.options = None

    def create_world(self, installation, private_root, **options):
        self.options = options
        class World:
            directory = Path("private/worlds/example")
        return World()

    @asynccontextmanager
    async def host_enrollment(self, installation, private_root, **options):
        self.options = options
        self.opened.set()
        try:
            yield self
        finally:
            while not self.cleanup.is_set():
                await asyncio.sleep(.005)
            self.closed.set()

    async def enroll(self):
        self.enrolled.set()


class SetupWorkerTests(unittest.TestCase):
    def setUp(self):
        self.controller = Controller()
        self.worker = SetupWorker(object(), Path("private"), controller=self.controller)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.controller.cleanup.set()
        self.worker.cancel()
        if self.worker.thread:
            self.worker.thread.join(3)
        self.assertFalse(self.worker.busy)

    def test_creation_returns_private_selection_without_showing_credentials(self):
        self.worker.start("create", player_names=["Host"], endpoint="127.0.0.1", port=8765)
        self.worker.thread.join(3)
        self.assertEqual(self.worker.events.get_nowait(), SetupEvent("complete", "created", Path("private/worlds/example")))
        self.assertEqual(self.controller.options["player_names"], ["Host"])

    def test_enrollment_requires_explicit_finish_and_drains_before_completion(self):
        self.worker.start("enroll", world_directory=Path("world"), slot=0, source_path=Path("source.sav"))
        self.assertTrue(self.controller.opened.wait(2))
        self.assertEqual(self.worker.events.get(timeout=2).kind, "ready")
        self.assertFalse(self.controller.enrolled.is_set())
        self.assertFalse(self.worker.start("create"))
        self.assertTrue(self.worker.finish())
        self.assertFalse(self.worker.finish())
        self.worker.thread.join(3)
        self.assertTrue(self.controller.enrolled.is_set())
        self.assertTrue(self.controller.closed.is_set())
        self.assertEqual(self.worker.events.get_nowait().code, "enrolled")

    def test_cancel_does_not_enroll_or_abandon_cleanup(self):
        self.controller.cleanup.clear()
        self.worker.start("enroll")
        self.assertTrue(self.controller.opened.wait(2))
        self.worker.events.get(timeout=2)
        self.worker.cancel()
        self.worker.cancel()
        self.assertTrue(self.worker.busy)
        self.controller.cleanup.set()
        self.worker.thread.join(3)
        self.assertFalse(self.controller.enrolled.is_set())
        self.assertTrue(self.controller.closed.is_set())
        self.assertEqual(self.worker.events.get_nowait().code, "cancelled")

    def test_draft_source_becomes_selectable_only_after_natural_exit_and_context_close(self):
        exited, closed = threading.Event(), threading.Event()
        class Draft:
            @asynccontextmanager
            async def open(self):
                try:
                    yield self
                finally:
                    closed.set()
            async def wait(self):
                while not exited.is_set():
                    await asyncio.sleep(.005)
            def finish(self):
                self_finished = exited.is_set() and not closed.is_set()
                if not self_finished:
                    raise AssertionError("receipt must be made under the draft lease after game exit")
                return SimpleNamespace(source_path=Path("private/drafts/new/character.sav"))
        self.worker.draft_factory = lambda *_: Draft()
        self.addCleanup(exited.set)
        self.worker.start("draft")
        self.assertEqual(self.worker.events.get(timeout=2).code, "draft_running")
        self.assertFalse(self.worker.finish())  # Enrollment is a separate step.
        self.assertTrue(self.worker.busy)
        exited.set()
        self.worker.thread.join(3)
        event = self.worker.events.get_nowait()
        self.assertTrue(closed.is_set())
        self.assertEqual(event.source_path, Path("private/drafts/new/character.sav"))
        self.assertEqual(event.code, "draft_created")

    def test_safe_native_rejection_waits_for_another_explicit_finish_in_same_context(self):
        from emerald_multiplayer.live_checkpoint import LiveSaveError
        attempts = []
        async def enroll():
            attempts.append(1)
            if len(attempts) == 1:
                raise LiveSaveError("unsafe", "not a field point", safe_to_retry=True)
            self.controller.enrolled.set()
        self.controller.enroll = enroll
        self.worker.start("enroll")
        self.assertEqual(self.worker.events.get(timeout=2).code, "ready")
        self.assertTrue(self.worker.finish())
        self.assertEqual(self.worker.events.get(timeout=2).code, "not_ready")
        self.assertEqual(len(attempts), 1)
        self.assertFalse(self.controller.closed.is_set())
        self.assertTrue(self.worker.finish())
        self.worker.thread.join(3)
        self.assertEqual(len(attempts), 2)
        self.assertTrue(self.controller.closed.is_set())
        self.assertEqual(self.worker.events.get_nowait().code, "enrolled")


class SetupWidgetTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.root = tk.Tk()
        self.root.withdraw()
        self.controller = Controller()
        self.worker = SetupWorker(object(), Path("private"), controller=self.controller)
        self.window = SetupWindow(self.root, object(), Path("private"), worker=self.worker)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.controller.cleanup.set()
        self.worker.cancel()
        if self.worker.thread:
            self.worker.thread.join(3)
        self.window.destroy()
        self.root.destroy()

    def test_host_approval_is_required_and_slot_change_revokes_it(self):
        self.window.world_directory, self.window.source_path = Path("world"), Path("original.sav")
        self.window.enroll()
        self.assertIn("explicitly approve", self.window.status.get())
        self.assertFalse(self.worker.busy)
        self.window.approval.set(True)
        self.window.slot.set("Friend 1")
        self.window.slot_control.event_generate("<<ComboboxSelected>>")
        self.assertFalse(self.window.approval.get())

    def test_blank_port_is_rejected_before_world_creation(self):
        self.window.port.set("")
        self.window.create()
        self.assertFalse(self.worker.busy)
        self.assertIn("Check the player names", self.window.status.get())


if __name__ == "__main__":
    unittest.main()
