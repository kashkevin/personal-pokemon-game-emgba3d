import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import queue
import threading
import time
import unittest
from unittest.mock import patch

from emerald_multiplayer.launcher_gui import (
    LauncherRelease, LauncherWindow, LaunchRequest, SessionWorker, UiEvent, status_text,
)
from emerald_multiplayer.launcher_session import SessionState, SessionStatus


class ControlledSession:
    def __init__(self, installation, private_root, *, on_status, **options):
        self.on_status = on_status
        self.options = options
        self.status = SessionStatus(SessionState.NEW, "new")
        self.opened = threading.Event()
        self.played = threading.Event()
        self.closed = threading.Event()
        self.release_connect = threading.Event()
        self.release_game = threading.Event()
        self.release_cleanup = threading.Event()
        self.release_cleanup.set()
        self.blocked = False
        self.error = None
        self.play_cancelled = False

    def publish(self, state, code):
        self.status = SessionStatus(state, code, connected=True)
        self.on_status(self.status)

    @asynccontextmanager
    async def open(self):
        self.opened.set()
        self.publish(SessionState.CONNECTING, "authentication")
        try:
            while not self.release_connect.is_set():
                await asyncio.sleep(.005)
            if self.error:
                raise self.error
            self.publish(SessionState.BLOCKED if self.blocked else SessionState.READY,
                         "enrollment_required" if self.blocked else "ready")
            yield self
        finally:
            while not self.release_cleanup.is_set():
                await asyncio.sleep(.005)
            self.closed.set()
            self.publish(SessionState.CLOSED, "closed")

    async def play(self):
        self.played.set()
        self.publish(SessionState.RUNNING, "running")
        try:
            while not self.release_game.is_set():
                await asyncio.sleep(.005)
            self.publish(SessionState.FINISHED, "game_closed")
            return 0
        except asyncio.CancelledError:
            self.play_cancelled = True
            raise


class GuiWorkerTests(unittest.TestCase):
    def setUp(self):
        self.instances = []
        self.created = threading.Event()
        def factory(*args, **kwargs):
            value = ControlledSession(*args, **kwargs)
            self.instances.append(value)
            self.created.set()
            return value
        self.worker = SessionWorker(object(), Path("private"), factory=factory)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for session in self.instances:
            session.release_connect.set()
            session.release_game.set()
            session.release_cleanup.set()
        self.worker.cancel_startup()
        if self.worker._thread:
            self.worker._thread.join(5)
        self.assertFalse(self.worker.busy)

    def launch(self, mode="host"):
        self.assertTrue(self.worker.start(LaunchRequest(mode, Path("/private/host.json"), "192.168.1.20")))
        self.assertTrue(self.created.wait(2))
        session = self.instances[-1]
        self.assertTrue(session.opened.wait(2))
        return session

    def finish_events(self):
        self.worker._thread.join(3)
        self.assertFalse(self.worker.busy)
        events = []
        while not self.worker.events.empty():
            events.append(self.worker.events.get_nowait())
        return events

    def test_host_composes_fixed_session_options_and_normal_cleanup(self):
        session = self.launch()
        self.assertEqual(session.options, dict(world_directory=Path("/private"),
            bind_address="192.168.1.20", host_route="192.168.1.20", public=False))
        self.assertFalse(self.worker.start(LaunchRequest("join", Path("ignored.json"))))
        session.release_connect.set()
        self.assertTrue(session.played.wait(2))
        self.assertFalse(self.worker.cancel_startup())
        self.assertFalse(session.play_cancelled)
        session.release_game.set()
        self.assertEqual(self.finish_events()[-1], UiEvent("complete", "game_closed"))
        self.assertTrue(session.closed.is_set())

    def test_join_never_inherits_host_flags(self):
        session = self.launch("join")
        self.assertEqual(session.options, {"invitation_path": Path("/private/host.json")})
        session.blocked = True
        session.release_connect.set()
        self.assertEqual(self.finish_events()[-1].code, "enrollment_required")
        self.assertFalse(session.played.is_set())

    def test_repeated_cancel_waits_for_context_cleanup(self):
        session = self.launch()
        session.release_cleanup.clear()
        self.assertTrue(self.worker.cancel_startup())
        self.assertTrue(self.worker.cancel_startup())
        time.sleep(.04)
        self.assertTrue(self.worker.busy)
        self.assertFalse(session.closed.is_set())
        self.assertFalse(any(event.kind == "complete" for event in self.drain_events()))
        session.release_cleanup.set()
        self.assertEqual(self.finish_events()[-1].code, "cancelled")

    def drain_events(self):
        result = []
        while not self.worker.events.empty():
            result.append(self.worker.events.get_nowait())
        return result

    def test_arbitrary_error_details_never_enter_ui_queue(self):
        session = self.launch()
        session.error = RuntimeError("secret credential and C:/private/save.sav")
        session.release_connect.set()
        events = self.finish_events()
        self.assertEqual(events[-1].code, "session_failed")
        self.assertNotIn("secret", repr(events))
        self.assertNotIn("secret", status_text("secret credential"))

    def test_connection_change_is_observed_without_stopping_game(self):
        session = self.launch()
        session.release_connect.set()
        self.assertTrue(session.played.wait(2))
        session.status = SessionStatus(SessionState.RUNNING, "connection_lost")
        deadline = time.monotonic() + 2
        events = []
        while time.monotonic() < deadline:
            events.extend(self.drain_events())
            if any(e.code == "connection_lost" for e in events):
                break
            time.sleep(.02)
        self.assertTrue(any(e.code == "connection_lost" for e in events))
        self.assertFalse(session.play_cancelled)
        self.assertFalse(session.closed.is_set())

    def test_release_pins_determine_installation_and_are_not_self_supplied(self):
        release = LauncherRelease("Private test", "a"*64, "b"*64, "c"*64)
        game = release.installation(Path("app"), Path("private"))
        self.assertEqual(game.rom_path, Path("private/games") / ("a"*64) / "game.gba")
        self.assertEqual(game.manifest_path, Path("app/game-manifest.json"))
        self.assertEqual(game.bundle.manifest_sha256, "c"*64)
        with self.assertRaises(ValueError):
            LauncherRelease("test", "untrusted", "b"*64, "c"*64)
        with self.assertRaisesRegex(ValueError, "address_invalid"):
            LaunchRequest("host", Path("host.json"), "0.0.0.0").options()

    def test_import_is_single_worker_and_finishes_before_completion(self):
        entered, finish = threading.Event(), threading.Event()
        class Importer:
            def install(self, source):
                self.source = source
                entered.set()
                finish.wait(2)
        importer = Importer()
        self.worker.importer = importer
        self.addCleanup(finish.set)
        self.assertTrue(self.worker.start_import(Path("own-dump.gba")))
        self.assertTrue(entered.wait(2))
        self.assertTrue(self.worker.importing)
        self.assertFalse(self.worker.cancel_startup())
        self.assertFalse(self.worker.start(LaunchRequest("join", Path("invitation.json"))))
        self.assertFalse(self.worker.start_import(Path("another.gba")))
        finish.set()
        self.assertEqual(self.finish_events()[-1].code, "imported")
        self.assertFalse(self.worker.importing)
        self.assertEqual(importer.source, Path("own-dump.gba"))

    def test_import_without_release_is_unavailable(self):
        self.assertFalse(self.worker.start_import(Path("own-dump.gba")))
        self.assertFalse(self.worker.busy)

    def test_connection_probe_returns_fixed_invitation_error(self):
        self.assertTrue(self.worker.start_probe(Path("missing-private-invitation.json")))
        self.assertEqual(self.finish_events()[-1].code, "invalid_invitation")
        self.assertFalse(self.worker.checking_connection)


class WidgetTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest("Tk display unavailable: " + str(error))
        self.root.withdraw()
        def destroy_if_open():
            try:
                self.root.destroy()
            except tk.TclError:
                pass  # The tested close path may already have destroyed it.
        self.addCleanup(destroy_if_open)

    def test_preview_disables_play_without_release(self):
        window = LauncherWindow(self.root)
        self.root.update_idletasks()
        self.assertTrue(all(str(widget.cget("state")) == "disabled" for widget in window.controls))
        self.assertIn("verified game package", window.message.get())

    def test_close_during_play_waits_and_finishes_only_after_worker_completion(self):
        class Worker:
            busy = True
            events = queue.SimpleQueue()
            def cancel_startup(self):
                return False
        worker = Worker()
        window = LauncherWindow(self.root, worker)
        window.close()
        self.assertTrue(window.closing)
        self.assertIn("Close the game window", window.message.get())
        self.assertTrue(self.root.winfo_exists())
        worker.events.put(UiEvent("status", "running", "running"))
        window.poll()
        self.assertIn("Close the game window", window.message.get())
        worker.events.put(UiEvent("complete", "game_closed"))
        with patch.object(self.root, "destroy", wraps=self.root.destroy) as destroy:
            window.poll()
            destroy.assert_called_once()

    def test_missing_selection_does_not_start_session(self):
        class Worker:
            busy = False
            events = queue.SimpleQueue()
            def start(self, _):
                raise AssertionError("should not start")
        window = LauncherWindow(self.root, Worker())
        window.start("host")
        self.assertEqual(window.message.get(), status_text("selection_required"))


if __name__ == "__main__":
    unittest.main()
