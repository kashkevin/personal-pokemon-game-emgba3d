"""Player-facing cancellation never grants authority or abandons a live core."""
import asyncio
from dataclasses import replace
from pathlib import Path
import queue
import threading
import time
import unittest

from emerald_multiplayer.launcher_gui import LauncherWindow, LaunchRequest, SessionWorker, UiEvent, status_text
from emerald_multiplayer.launcher_session import LauncherSessionError, SessionState, SessionStatus
import test_launcher_gui as fixtures


class CleanupSession(fixtures.ControlledSession):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cleanup_started = threading.Event()
        self.release_admission = threading.Event()
        self.cleanup_calls = 0
        self.cleanup_error = None

    async def cancel_battle_entry(self):
        self.cleanup_calls += 1
        self.cleanup_started.set()
        self.publish(SessionState.RUNNING, "admission_canceling")
        while not self.release_admission.is_set():
            await asyncio.sleep(.005)
        if self.cleanup_error:
            raise self.cleanup_error
        self.publish(SessionState.RUNNING, "admission_canceled")


class AdmissionCleanupWorkerTests(unittest.TestCase):
    launch = fixtures.GuiWorkerTests.launch
    finish_events = fixtures.GuiWorkerTests.finish_events
    drain_events = fixtures.GuiWorkerTests.drain_events

    def setUp(self):
        self.instances = []
        self.created = threading.Event()
        def factory(*args, **kwargs):
            session = CleanupSession(*args, **kwargs)
            self.instances.append(session)
            self.created.set()
            return session
        self.worker = SessionWorker(object(), Path("private"), factory=factory)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for session in self.instances:
            session.release_admission.set()
        fixtures.GuiWorkerTests.cleanup(self)

    def running(self, *, eligible=True):
        session = self.launch()
        session.release_connect.set()
        self.assertTrue(session.played.wait(2))
        session.status = SessionStatus(SessionState.RUNNING, "host_loss_battle_waiting",
            battle_recovery_available=True, admission_cleanup_available=eligible)
        self.worker._publish(session.status)
        return session

    def wait_action(self):
        deadline = time.monotonic() + 2
        while self.worker._battle_recovery_pending and time.monotonic() < deadline:
            time.sleep(.005)
        self.assertFalse(self.worker._battle_recovery_pending)

    def test_only_explicit_available_admission_enables_worker_action(self):
        self.assertFalse(self.worker.request_battle_entry_cancel())
        session = self.running(eligible=False)
        self.assertFalse(self.worker.request_battle_entry_cancel())
        self.assertEqual(session.cleanup_calls, 0)
        for code in ("battle_running", "battle_finished", "admission_cleanup_unsupported"):
            session.status = SessionStatus(SessionState.RUNNING, code)
            self.worker._publish(session.status)
            self.assertFalse(self.worker.request_battle_entry_cancel())

    def test_same_status_availability_change_is_polled_without_new_callback(self):
        session = self.running(eligible=False)
        self.drain_events()
        session.status = replace(session.status, admission_cleanup_available=True)
        deadline = time.monotonic() + 2
        observed = []
        while time.monotonic() < deadline:
            observed.extend(self.drain_events())
            if any(event.admission_cleanup_available for event in observed):
                break
            time.sleep(.01)
        self.assertTrue(any(event.code == "host_loss_battle_waiting"
                            and event.admission_cleanup_available for event in observed))
        self.assertFalse(session.play_cancelled)
        self.assertTrue(self.worker.request_battle_entry_cancel())

    def test_pending_action_fences_recovery_save_settings_and_drains_before_close(self):
        session = self.running()
        self.drain_events()
        self.assertTrue(self.worker.request_battle_entry_cancel())
        self.assertTrue(self.worker.holds_game)
        self.assertFalse(self.worker.request_battle_entry_cancel())
        self.assertFalse(self.worker.request_battle_recovery())
        self.assertFalse(self.worker.request_save())
        self.assertFalse(self.worker.request_autosave(False))
        self.assertFalse(self.worker.cancel_startup())
        self.assertTrue(session.cleanup_started.wait(2))
        self.assertFalse(any(event.code == "admission_canceled" for event in self.drain_events()))
        session.release_game.set()
        time.sleep(.04)
        self.assertTrue(self.worker.busy)
        self.assertFalse(session.closed.is_set())
        self.assertTrue(self.worker.holds_game)
        session.release_admission.set()
        events = self.finish_events()
        self.assertEqual(session.cleanup_calls, 1)
        self.assertTrue(any(event.code == "admission_canceled" for event in events))
        self.assertEqual(events[-1], UiEvent("complete", "game_closed"))
        self.assertFalse(session.play_cancelled)

    def test_save_or_settings_already_in_progress_refuses_cancellation(self):
        session = self.running()
        self.assertTrue(self.worker.request_save())
        self.assertTrue(session.save_started.wait(2))
        self.assertFalse(self.worker.request_battle_entry_cancel())
        session.release_save.set()
        deadline = time.monotonic() + 2
        while self.worker._save_pending and time.monotonic() < deadline:
            time.sleep(.005)
        self.assertFalse(self.worker._save_pending)
        session.status = replace(session.status, admission_cleanup_available=True)
        self.worker._publish(session.status)
        self.assertTrue(self.worker.request_autosave(False))
        self.assertTrue(session.settings_started.wait(2))
        self.assertFalse(self.worker.request_battle_entry_cancel())
        self.assertEqual(session.cleanup_calls, 0)

    def test_failure_is_bounded_retains_game_and_never_reports_success(self):
        session = self.running()
        session.cleanup_error = RuntimeError("secret credential and C:/private/character.sav")
        self.drain_events()
        self.assertTrue(self.worker.request_battle_entry_cancel())
        self.assertTrue(session.cleanup_started.wait(2))
        session.release_admission.set()
        self.wait_action()
        events = self.drain_events()
        self.assertTrue(any(event.code == "admission_cleanup_held" for event in events))
        self.assertFalse(any(event.code == "admission_canceled" for event in events))
        self.assertNotIn("secret", repr(events))
        self.assertTrue(self.worker.holds_game)
        self.assertFalse(session.closed.is_set())
        self.assertFalse(session.play_cancelled)

    def test_stale_availability_can_only_report_unsupported_without_success(self):
        session = self.running()
        session.cleanup_error = LauncherSessionError("admission_cleanup_unsupported")
        self.drain_events()
        self.assertTrue(self.worker.request_battle_entry_cancel())
        self.assertTrue(session.cleanup_started.wait(2))
        session.release_admission.set()
        self.wait_action()
        events = self.drain_events()
        self.assertTrue(any(event.code == "admission_cleanup_unsupported" for event in events))
        self.assertFalse(any(event.admission_cleanup_available for event in events))
        self.assertTrue(self.worker.holds_game)


class AdmissionCleanupWidgetTests(unittest.TestCase):
    setUp = fixtures.WidgetTests.setUp

    def window(self):
        class Worker:
            busy = holds_game = True
            def __init__(self):
                self.events = queue.SimpleQueue()
                self.requested = 0
            def request_battle_entry_cancel(self):
                self.requested += 1
                return True
            def cancel_startup(self):
                raise AssertionError("the retained game must stay open")
        worker = Worker()
        return LauncherWindow(self.root, worker), worker

    def test_cancellation_button_requires_explicit_status_availability(self):
        window, worker = self.window()
        self.assertEqual(str(window.cancel_battle_entry_button.cget("state")), "disabled")
        for code in ("host_loss_battle_waiting", "battle_running", "battle_finished",
                     "admission_cleanup_unsupported"):
            worker.events.put(UiEvent("status", code, "running"))
            window.poll()
            self.assertEqual(str(window.cancel_battle_entry_button.cget("state")), "disabled")
        worker.events.put(UiEvent("status", "host_loss_battle_waiting", "running",
                                 admission_cleanup_available=True))
        window.poll()
        self.assertEqual(str(window.cancel_battle_entry_button.cget("state")), "normal")
        worker.events.put(UiEvent("status", "host_loss_battle_waiting", "ready",
                                 admission_cleanup_available=True))
        window.poll()
        self.assertEqual(str(window.cancel_battle_entry_button.cget("state")), "disabled")

    def test_press_shows_pending_and_close_does_not_abandon_core(self):
        window, worker = self.window()
        worker.events.put(UiEvent("status", "host_loss_battle_waiting", "running", True, True, True))
        window.poll()
        window.cancel_battle_entry_button.invoke()
        self.assertEqual(worker.requested, 1)
        self.assertEqual(window.message.get(), status_text("admission_canceling"))
        for control in (window.cancel_battle_entry_button, window.recover_battle_button,
                        window.save_button, window.autosave_button):
            self.assertEqual(str(control.cget("state")), "disabled")
        window.close()
        self.assertFalse(window.closing)
        self.assertEqual(window.message.get(), status_text("wait_for_recovery"))
        self.assertTrue(self.root.winfo_exists())

    def test_failed_or_unsupported_cleanup_never_enables_save_or_tells_player_to_close(self):
        window, worker = self.window()
        for code in ("admission_cleanup_held", "admission_cleanup_unsupported"):
            worker.events.put(UiEvent("status", code, "running"))
            window.poll()
            self.assertEqual(window.message.get(), status_text(code))
            self.assertEqual(str(window.save_button.cget("state")), "disabled")
            self.assertEqual(str(window.cancel_battle_entry_button.cget("state")), "disabled")
            self.assertIn("Keep", window.message.get())
            self.assertNotIn("Close the game", window.message.get())

    def test_verified_terminal_status_reenables_save_and_disables_cancellation(self):
        window, worker = self.window()
        worker.events.put(UiEvent("status", "admission_canceled", "running", False))
        window.poll()
        self.assertEqual(window.message.get(), status_text("admission_canceled"))
        self.assertEqual(str(window.save_button.cget("state")), "normal")
        self.assertEqual(str(window.cancel_battle_entry_button.cget("state")), "disabled")
        self.assertFalse(window.autosave_value.get())

    def test_hold_during_existing_close_request_revokes_close_instruction(self):
        window, worker = self.window()
        window.closing = True
        worker.events.put(UiEvent("status", "admission_cleanup_held", "running",
                                 admission_cleanup_available=True))
        window.poll()
        self.assertFalse(window.closing)
        self.assertEqual(window.message.get(), status_text("wait_for_recovery"))
        self.assertEqual(str(window.cancel_battle_entry_button.cget("state")), "normal")
        worker.events.put(UiEvent("complete", "game_closed"))
        window.poll()
        self.assertEqual(str(window.cancel_battle_entry_button.cget("state")), "disabled")


if __name__ == "__main__":
    unittest.main()
