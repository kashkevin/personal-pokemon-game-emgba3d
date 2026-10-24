import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import queue
import shutil
import tempfile
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
        self.exit_code = 0
        self.play_cancelled = False
        self.save_started = threading.Event()
        self.release_save = threading.Event()
        self.save_count = 0
        self.autosave_enabled = True
        self.settings_started = threading.Event()
        self.release_settings = threading.Event()
        self.settings_calls = []

    def publish(self, state, code):
        self.status = SessionStatus(state, code, connected=True, autosave_enabled=self.autosave_enabled)
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
            return self.exit_code
        except asyncio.CancelledError:
            self.play_cancelled = True
            raise

    async def save(self):
        self.save_count += 1
        self.save_started.set()
        self.publish(SessionState.RUNNING, "saving")
        while not self.release_save.is_set():
            await asyncio.sleep(.005)
        self.publish(SessionState.RUNNING, "saved")

    async def set_autosave_enabled(self, enabled):
        self.settings_calls.append(enabled)
        self.settings_started.set()
        while not self.release_settings.is_set():
            await asyncio.sleep(.005)
        self.autosave_enabled = enabled
        self.publish(SessionState.RUNNING, "autosave_on" if enabled else "autosave_off")


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
            session.release_save.set()
            session.release_settings.set()
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

    def test_explicit_save_is_single_flight_and_drained_before_session_cleanup(self):
        self.assertFalse(self.worker.request_save())
        session = self.launch()
        self.assertFalse(self.worker.request_save())
        session.release_connect.set()
        self.assertTrue(session.played.wait(2))
        self.assertTrue(self.worker.request_save())
        self.assertFalse(self.worker.request_save())
        self.assertTrue(session.save_started.wait(2))
        session.release_game.set()
        time.sleep(.05)
        self.assertFalse(session.closed.is_set())
        session.release_save.set()
        self.assertEqual(self.finish_events()[-1].code, "game_closed")
        self.assertEqual(session.save_count, 1)

    def test_trade_close_review_action_is_exclusive_and_drained(self):
        session = self.launch()
        started, finish = threading.Event(), threading.Event()
        self.addCleanup(finish.set)
        async def prepare():
            started.set()
            while not finish.is_set():
                await asyncio.sleep(.005)
            session.publish(SessionState.RUNNING, "trade_recovery_close")
        session.prepare_trade_recovery = prepare
        session.release_connect.set()
        self.assertTrue(session.played.wait(2))
        self.worker._publish(SessionStatus(SessionState.RUNNING, "host_loss_trade_waiting",
                                           trade_recovery_available=True))
        self.assertTrue(self.worker.request_trade_recovery())
        self.assertTrue(started.wait(2))
        self.assertFalse(self.worker.request_trade_recovery())
        self.assertFalse(self.worker.request_save())
        self.assertFalse(self.worker.request_autosave(False))
        session.release_game.set()
        time.sleep(.04)
        self.assertFalse(session.closed.is_set())
        finish.set()
        self.assertTrue(any(e.code == "trade_recovery_close" for e in self.finish_events()))

    def test_autosave_setting_is_single_flight_and_drained_before_completion(self):
        self.assertFalse(self.worker.request_autosave(False))
        session = self.launch()
        session.release_connect.set()
        self.assertTrue(session.played.wait(2))
        self.assertTrue(self.worker.request_autosave(False))
        self.assertFalse(self.worker.request_autosave(True))
        self.assertTrue(session.settings_started.wait(2))
        session.release_game.set()
        time.sleep(.04)
        self.assertFalse(session.closed.is_set())
        session.release_settings.set()
        events = self.finish_events()
        self.assertEqual(session.settings_calls, [False])
        self.assertTrue(any(e.code == "autosave_off" and e.autosave_enabled is False for e in events))
        self.assertEqual(events[-1].code, "game_closed")

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

    def test_a_failure_names_its_class_and_code_and_keeps_its_message_off_the_queue(self):
        # A friend who could not join back was told only "The game could not open" (2026-10-24): the menu now also gets the
        # failure's class and stable code, and the whole line (with its message) stays on the worker for the private file.
        class StartupProblem(ValueError):
            def __init__(self, code, message):
                self.code = code
                super().__init__(message)
        session = self.launch()
        session.error = StartupProblem("pending_conflict", "secret credential and C:/private/save.sav")
        session.release_connect.set()
        events = self.finish_events()
        self.assertEqual((events[-1].code, events[-1].failure), ("session_failed", "StartupProblem pending_conflict"))
        self.assertNotIn("secret", repr(events))
        self.assertEqual(self.worker.last_failure_detail,
                         "StartupProblem pending_conflict: secret credential and C:/private/save.sav")

    def test_a_session_error_carries_the_cause_it_replaced(self):
        from emerald_multiplayer.launcher_session import LauncherSessionError, _safe_error
        safe = _safe_error(KeyError("journal"))
        self.assertEqual((safe.code, safe.cause_name, safe.cause), ("session_failed", "KeyError", "KeyError: 'journal'"))
        self.assertEqual(_safe_error(safe).cause, safe.cause)
        session = self.launch()
        session.error = safe
        session.release_connect.set()
        events = self.finish_events()
        self.assertEqual(events[-1].failure, "KeyError")
        self.assertEqual(self.worker.last_failure_detail, "KeyError: 'journal'")
        self.assertIsNone(LauncherSessionError("session_failed").cause_name)

    def test_a_game_that_crashes_says_so(self):
        session = self.launch()
        session.exit_code = 0xC0000005
        session.release_connect.set()
        self.assertTrue(session.played.wait(2))
        session.release_game.set()
        events = self.finish_events()
        self.assertEqual((events[-1].code, events[-1].failure),
                         ("session_failed", "the game ended with exit code 0xC0000005: a crash (access violation)"))

    def test_a_closed_game_has_no_failure(self):
        session = self.launch()
        session.release_connect.set()
        self.assertTrue(session.played.wait(2))
        session.release_game.set()
        events = self.finish_events()
        self.assertEqual((events[-1].code, events[-1].failure, self.worker.last_failure_detail), ("game_closed", None, None))

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

    def test_recovery_status_retains_game_until_a_verified_preserved_result(self):
        for code in ("host_loss_preserving", "host_loss_unsaved_held", "host_loss_battle_waiting",
                     "host_loss_trade_waiting", "game_recovery_held"):
            with self.subTest(code=code):
                self.worker._publish(SessionStatus(SessionState.RUNNING, code))
                self.assertTrue(self.worker.holds_game)
        self.worker._publish(SessionStatus(SessionState.RUNNING, "host_loss_preserved"))
        self.assertFalse(self.worker.holds_game)

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

    def test_footer_is_visible_at_default_and_shorter_actual_tk_sizes(self):
        window = LauncherWindow(self.root)
        window.show_view("session")   # Update 28: the recovery actions live on the page of the running game
        window.message.set(status_text("trade_recovery_close"))
        window.restart_host_button.pack(side="left", padx=(12, 0))
        self.root.deiconify()
        for size in ("800x780", "700x680"):
            self.root.geometry(size); self.root.update(); self.root.update_idletasks()
            left, top = self.root.winfo_rootx(), self.root.winfo_rooty()
            width, height = self.root.winfo_width(), self.root.winfo_height()
            for widget in (window.status_label, window.recover_trade_button, window.recover_battle_button,
                           window.cancel_battle_entry_button, window.restart_host_button, window.cancel):
                self.assertGreater(widget.winfo_height(), 1, str(widget))
                self.assertGreaterEqual(widget.winfo_rootx(), left)
                self.assertGreaterEqual(widget.winfo_rooty(), top)
                self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(), left + width, str(widget))
                self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(), top + height, str(widget))

    def test_help_names_the_native_game_keys_for_a_native_runtime(self):
        import tkinter as tk
        from types import SimpleNamespace

        def help_text(native):
            window = LauncherWindow(self.root)
            bundle = SimpleNamespace(is_native=lambda: native)
            window.worker = SimpleNamespace(installation=SimpleNamespace(bundle=bundle), importer=None)
            before = set(self.root.winfo_children())
            window.show_help()
            texts = []
            def walk(widget):
                try:
                    texts.append(str(widget.cget("text")))
                except tk.TclError:
                    pass
                for child in widget.winfo_children():
                    walk(child)
            for child in set(self.root.winfo_children()) - before:
                walk(child)
                child.destroy()
            return "\n".join(texts)
        native = help_text(True)
        self.assertIn("Z: A/confirm", native)
        self.assertIn("F7: camera", native)
        self.assertNotIn("mGBA", native)
        self.assertIn("mGBA", help_text(False))

    def test_game_display_tab_writes_the_native_games_settings(self):
        import tkinter as tk
        from tkinter import ttk
        from types import SimpleNamespace
        from emerald_multiplayer.game_display_settings import read_display_settings

        private = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, private)
        settings = private / "game-settings.cfg"
        settings.write_text("cameraStyle=1\nvolume=7\n")
        window = LauncherWindow(self.root)
        bundle = SimpleNamespace(is_native=lambda: True)
        window.worker = SimpleNamespace(installation=SimpleNamespace(bundle=bundle), importer=None,
                                        private_root=private, busy=True)
        before = set(self.root.winfo_children())
        window.show_help()
        widgets = []
        def walk(widget):
            widgets.append(widget)
            for child in widget.winfo_children():
                walk(child)
        for child in set(self.root.winfo_children()) - before:
            walk(child)
        notebook = next(w for w in widgets if isinstance(w, ttk.Notebook))
        self.assertIn("Game display", [notebook.tab(tab, "text") for tab in notebook.tabs()])
        boxes = [w for w in widgets if isinstance(w, ttk.Combobox) and "1920 x 1080 (default)" in w.cget("values")]
        self.assertEqual(len(boxes), 1)
        resolution = boxes[0]
        mode = next(w for w in widgets if isinstance(w, ttk.Combobox) and "Borderless fullscreen" in w.cget("values"))
        quality = next(w for w in widgets if isinstance(w, ttk.Combobox) and "High (default)" in w.cget("values"))
        self.assertEqual((resolution.get(), mode.get(), quality.get()),
                         ("1920 x 1080 (default)", "Windowed", "High (default)"))
        save = next(w for w in widgets if isinstance(w, ttk.Button) and w.cget("text") == "Save display settings")
        resolution.set("2560 x 1440")
        mode.set("Borderless fullscreen")
        quality.set("Low (fastest)")
        save.invoke()  # a game is running: nothing is written
        self.assertEqual(settings.read_text(), "cameraStyle=1\nvolume=7\n")
        window.worker.busy = False
        save.invoke()
        self.assertEqual(read_display_settings(settings),
                         dict(resolution="2560x1440", mode="borderless", quality="low"))
        self.assertTrue(settings.read_text().startswith("cameraStyle=1\nvolume=7\n"))
        for child in set(self.root.winfo_children()) - before:
            child.destroy()

    def test_game_keys_tab_rebinds_and_saves_the_native_games_keys(self):
        import tkinter as tk
        from tkinter import ttk
        from types import SimpleNamespace
        from emerald_multiplayer.game_controls import DEFAULTS, read_controls

        private = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, private)
        settings = private / "game-settings.cfg"
        settings.write_text("volume=7\nkey.b=E\n")
        window = LauncherWindow(self.root)
        bundle = SimpleNamespace(is_native=lambda: True)
        window.worker = SimpleNamespace(installation=SimpleNamespace(bundle=bundle), importer=None,
                                        private_root=private, busy=True)
        before = set(self.root.winfo_children())
        self.root.deiconify()   # the help window is transient for the root: a key press needs it on screen
        window.show_help()
        self.root.update()
        widgets = []
        def walk(widget):
            widgets.append(widget)
            for child in widget.winfo_children():
                walk(child)
        for child in set(self.root.winfo_children()) - before:
            walk(child)
        notebook = next(w for w in widgets if isinstance(w, ttk.Notebook))
        self.assertIn("Game keys", [notebook.tab(tab, "text") for tab in notebook.tabs()])
        def button(text):
            return next(w for w in widgets if isinstance(w, ttk.Button) and str(w.cget("text")) == text)
        def label(text):
            return next(w for w in widgets if isinstance(w, ttk.Label) and str(w.cget("text")).startswith(text))
        def feedback():
            return " ".join(str(w.cget("text")) or self.root.getvar(str(w.cget("textvariable")))
                            for w in widgets if isinstance(w, ttk.Label) and str(w.cget("textvariable")))
        keys_tab = next(tab for tab in notebook.tabs() if notebook.tab(tab, "text") == "Game keys")
        notebook.select(keys_tab)   # a key press reaches only a window that is on screen
        self.root.update()
        def press(keysym):
            capture = button("Press a key...")
            capture.focus_force()
            self.root.update()
            capture.event_generate("<KeyPress>", keysym=keysym)
            self.root.update()
        # The current keys are shown: the defaults, and B from the file (with its default beside it).
        shown = sorted(str(w.cget("text")) for w in widgets if isinstance(w, ttk.Button))
        self.assertIn("Z", shown)
        self.assertIn("E", shown)
        self.assertTrue(any(str(w.cget("text")) == "default: X" for w in widgets if isinstance(w, ttk.Label)))
        # Rebind A: click, then press a key.
        button("Z").invoke()
        press("q")
        self.assertIn("A button is now Q", feedback())
        # A wants E, which B has: a conflict the player settles; nothing changes until then.
        button("Q").invoke()
        press("e")
        self.assertIn("already the key for B button", feedback())
        button("Keep things as they were").invoke()
        self.assertIn("E", [str(w.cget("text")) for w in widgets if isinstance(w, ttk.Button)])
        # Reserved keys are refused and the page keeps waiting.
        button("Q").invoke()
        press("F10")
        self.assertIn("can't be a game button", feedback())
        press("Escape")
        button("Save controls").invoke()   # a game is running: nothing is written
        self.assertEqual(settings.read_text(), "volume=7\nkey.b=E\n")
        window.worker.busy = False
        button("Save controls").invoke()
        saved = read_controls(settings)
        self.assertEqual((saved["a"], saved["b"]), ("Q", "E"))
        self.assertTrue(settings.read_text().startswith("volume=7\n"))
        button("Restore default keys").invoke()
        button("Save controls").invoke()
        self.assertEqual(read_controls(settings), DEFAULTS)
        self.assertEqual(settings.read_text(), "volume=7\n")
        for child in set(self.root.winfo_children()) - before:
            child.destroy()

    def test_dpi_awareness_only_on_windows(self):
        from unittest.mock import patch
        from emerald_multiplayer import launcher_gui
        import types
        with patch.object(launcher_gui.os, "name", "posix"):
            self.assertFalse(launcher_gui.windows_dpi_awareness())
        calls = []
        shcore = types.SimpleNamespace(SetProcessDpiAwareness=lambda level: calls.append(level) or 0)
        fake = types.SimpleNamespace(windll=types.SimpleNamespace(shcore=shcore))
        with patch.object(launcher_gui.os, "name", "nt"), patch.dict("sys.modules", {"ctypes": fake}):
            self.assertTrue(launcher_gui.windows_dpi_awareness())
        self.assertEqual(calls, [1])

    def test_fine_timer_only_on_windows(self):
        # KNOWN_ISSUES MS-62: the battle loops' few-millisecond waits are 15.6 ms on Windows without timeBeginPeriod(1).
        from unittest.mock import patch
        from emerald_multiplayer import launcher_gui
        import types
        with patch.object(launcher_gui.os, "name", "posix"):
            self.assertFalse(launcher_gui.windows_timer_resolution())
        calls = []
        winmm = types.SimpleNamespace(timeBeginPeriod=lambda period: calls.append(period) or 0)
        fake = types.SimpleNamespace(WinDLL=lambda name: winmm if name == "winmm" else None)
        with patch.object(launcher_gui.os, "name", "nt"), patch.dict("sys.modules", {"ctypes": fake}):
            self.assertTrue(launcher_gui.windows_timer_resolution())
        self.assertEqual(calls, [1])

    def test_preview_disables_play_without_release(self):
        window = LauncherWindow(self.root)
        self.root.update_idletasks()
        self.assertTrue(all(str(widget.cget("state")) == "disabled" for widget in window.controls))
        self.assertIn("verified game package", window.message.get())
        self.assertEqual(str(window.autosave_button.cget("state")), "disabled")

    def test_toggle_reflects_profile_and_keeps_manual_save_available_when_off(self):
        class Worker:
            busy = True
            events = queue.SimpleQueue()
            requests = []
            def request_autosave(self, enabled):
                self.requests.append(enabled)
                return True
        worker = Worker()
        window = LauncherWindow(self.root, worker)
        worker.events.put(UiEvent("status", "running", "running", False))
        window.poll()
        self.assertFalse(window.autosave_value.get())
        self.assertEqual(str(window.save_button.cget("state")), "normal")
        window.autosave_value.set(True)
        window.toggle_autosave()
        self.assertEqual(worker.requests, [True])
        self.assertEqual(str(window.autosave_button.cget("state")), "disabled")
        worker.events.put(UiEvent("status", "autosave_off", "running", False))
        window.poll()
        self.assertFalse(window.autosave_value.get())
        self.assertEqual(str(window.save_button.cget("state")), "normal")
        self.assertIn("Save now", window.message.get())

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

    def test_close_during_unpreserved_recovery_keeps_launcher_available(self):
        class Worker:
            busy = holds_game = True
            events = queue.SimpleQueue()
            def cancel_startup(self):
                raise AssertionError("must retain the paused game owner")
        window = LauncherWindow(self.root, Worker())
        window.close()
        self.assertFalse(window.closing)
        self.assertEqual(window.message.get(), status_text("wait_for_recovery"))
        self.assertTrue(self.root.winfo_exists())

    def test_hold_reported_while_waiting_to_close_revokes_close_instruction(self):
        class Worker:
            busy = True
            events = queue.SimpleQueue()
            def cancel_startup(self): return False
        worker = Worker()
        window = LauncherWindow(self.root, worker)
        window.close()
        self.assertTrue(window.closing)
        worker.events.put(UiEvent("status", "host_loss_battle_waiting", "running"))
        window.poll()
        self.assertFalse(window.closing)
        self.assertEqual(window.message.get(), status_text("wait_for_recovery"))


if __name__ == "__main__":
    unittest.main()
