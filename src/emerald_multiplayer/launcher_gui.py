"""Windows Host/Join window over the verified enrolled-character lifecycle.

Tk stays on its creating thread. A single asyncio worker owns every session,
child and network handle; only bounded status codes cross the UI queue.
Release pins are compiled into the application entry point, never user input.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import os
from pathlib import Path
import queue
import re
import threading

from .launcher_session import GameInstallation, LauncherSession, SessionState
from .player_runtime import RuntimeBundle
from .server import is_local_address


_TEXT = {
    "idle": "Choose Host Game or Join Game to begin.",
    "installation": "Checking your installed game…",
    "authentication": "Connecting to the host…",
    "ready": "Your character is ready.",
    "canonical_recovery": "Restoring your verified character…",
    "running": "Game running. Close the game window when you finish.",
    "game_closed": "Game closed. You can host or join again.",
    "cancelled": "Startup cancelled. Private recovery data is retained.",
    "closing": "Closing the connection…",
    "wait_for_game": "Close the game window to finish. This launcher will then close.",
    "wait_for_recovery": "Keep this game and launcher open until recovery finishes. Closing the game would lose its waiting state.",
    "game_recovery_held": "This game needs recovery. Keep its paused game window open so the waiting state is retained.",
    "package_missing": "This launcher preview needs a verified game package before play.",
    "selection_required": "Choose your world or friend invitation first.",
    "address_invalid": "Enter this PC’s local IPv4 or IPv6 address, such as 192.168.1.20.",
    "private_storage": "Your private application folder could not be opened.",
    "enrollment_required": "This character needs first-time setup. Open Set up a world or character to enroll it.",
    "pending_battle": "An interrupted battle needs recovery before this character can open.",
    "battle_recovery_unavailable": "The host could not check interrupted battles. Use the matching host version before opening this character.",
    "recovery_required": "Your character needs recovery before the game can open. Its private files have been retained.",
    "connection_timeout": "The host did not respond. Check that the host is running and the invitation is current.",
    "connection_lost": "Connection to the host was lost. Reconnection handling is not enabled in this build.",
    "host_loss_preserving": "Host connection lost. Preserving your game locally; keep the game open.",
    "host_loss_preserved": "Host connection lost. Your local save is preserved. Close the game and rejoin when the host returns.",
    "host_loss_unsaved_held": "Host connection lost. Saving could not be verified. Keep this paused game open for recovery.",
    "host_loss_battle_waiting": "Battle interrupted. Keep the game open; the battle is waiting for all players.",
    "host_loss_trade_waiting": "Trade interrupted. Keep the game open while its recorded result awaits recovery.",
    "host_loss_armed": "Host connection lost. Preserving your game locally; keep the game open.",
    "battle_running": "Multiplayer battle in progress.",
    "battle_finished": "Battle finished. Your party has been restored.",
    "battle_cancelled": "The challenge ended before the battle started. Your party is unchanged.",
    "trade_running": "Trading. Choose your Pokemon and confirm the offer in the game.",
    "trade_finished": "Trade completed and saved.",
    "trade_cancelled": "Trade cancelled. Your saved party is unchanged.",
    "session_changed": "The host session changed. Close the game before reopening your character.",
    "mirror_active": "This character is already open in another game window.",
    "invalid_invitation": "This invitation could not be verified. Ask the host for a current invitation.",
    "world_invalid": "This private world could not be verified.",
    "certificate_invalid": "The host’s invitation or certificate needs renewal.",
    "build_mismatch": "Your game version does not match the host’s invitation.",
    "installation_changed": "Game files are missing or changed. Reinstall the matching game package.",
    "runtime_hash": "Runtime files are missing or changed. Reinstall the matching game package.",
    "runtime_manifest": "The installed runtime could not be verified.",
    "runtime_path": "The game location could not be used. Choose a shorter installation or private-data path.",
    "runtime_unlisted": "The installed runtime contains unexpected files.",
    "runtime_size": "The installed runtime could not be verified.",
    "trade_recovery_unavailable": "The host does not support the character recovery required by this build.",
    "session_failed": "The game could not open. Private character and recovery files have been retained.",
    "saving": "Saving your character to the host… Keep the game open until this finishes.",
    "saved": "Character saved to the host. You can keep playing or close the game.",
    "save_not_ready": "Return to a safe place outside menus and battles, then press Save now again.",
    "save_busy": "A character save is already running.",
    "save_recovery_required": "This save needs recovery. Close the game and reopen through Host Game or Join Game.",
    "autosave_on": "Autosave is on: every 5 minutes, when you reach a safe place.",
    "autosave_off": "Autosave is off. Use Save now before closing the game.",
    "autosave_deferred": "Autosave is waiting for a safe place outside menus and battles.",
    "settings_unavailable": "Your character's autosave setting could not be saved or read.",
    "settings_busy": "Finishing the previous settings change…",
    "importing": "Checking your own game dump and installing this release…",
    "imported": "Game installed. Choose Host Game or Join Game.",
    "import_unavailable": "Game import is unavailable: this development package has no release patch.",
    "wait_for_import": "Finishing the game import before closing…",
    "import_file": "The selected game dump or installed patch could not be read.",
    "import_size": "The selected file is not a supported game dump.",
    "source_mismatch": "This game dump does not match this release. Your original file was not changed.",
    "patch_mismatch": "The game patch is missing or changed. Reinstall the matching package.",
    "patch_invalid": "The game patch could not be verified. No game was installed.",
    "target_mismatch": "The patched game does not match this release. No game was installed.",
    "import_destination": "The private game could not be installed. Existing files were retained.",
    "checking_connection": "Checking the invited host’s encrypted connection…",
    "wait_for_connection": "Finishing the connection check before closing…",
    "tls_reachable_loopback": "Host identity verified on this PC. This does not test another PC or the Internet.",
    "tls_reachable_lan": "Host identity verified at the invited LAN address. Gameplay and a separate-PC test are still required.",
    "tls_reachable_public": "Host identity verified at the invited public address. An outside-network gameplay test is still required.",
    "host_identity_invalid": "The host’s certificate does not match this invitation or is no longer valid.",
    "unreachable": "The invited host could not be reached. Check the host, address, port and network setup.",
}


def status_text(code):
    """Never put exception text, credentials, endpoints or paths into status UI."""
    return _TEXT.get(code, _TEXT["session_failed"])


_RETAINS_GAME = frozenset({"host_loss_preserving", "host_loss_unsaved_held",
    "host_loss_battle_waiting", "host_loss_trade_waiting", "host_loss_armed", "game_recovery_held"})


@dataclass(frozen=True)
class LauncherRelease:
    version: str
    rom_sha256: str
    manifest_sha256: str
    runtime_sha256: str

    def __post_init__(self):
        if (type(self.version) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,47}", self.version)
                or any(type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None
                       for value in (self.rom_sha256, self.manifest_sha256, self.runtime_sha256))):
            raise ValueError("invalid application release record")

    def installation(self, application_directory, private_directory):
        application, private = Path(application_directory), Path(private_directory)
        return GameInstallation(private / "games" / self.rom_sha256 / "game.gba",
            application / "game-manifest.json", self.rom_sha256, self.manifest_sha256,
            RuntimeBundle(application / "runtime", self.runtime_sha256))


def private_directory():
    """Use per-user local application storage, never the cwd or download folder."""
    value = os.environ.get("LOCALAPPDATA") if os.name == "nt" else None
    if not value or not Path(value).is_absolute():
        raise ValueError("private_storage")
    root = (Path(value) / "PokemonPrivate" / "launcher").resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


@dataclass(frozen=True)
class LaunchRequest:
    mode: str
    selection: Path
    address: str = "127.0.0.1"
    internet: bool = False

    def options(self):
        if self.mode not in {"host", "join"} or not isinstance(self.selection, Path):
            raise ValueError("selection_required")
        if self.mode == "join":
            return {"invitation_path": self.selection}
        if not is_local_address(self.address, allow_lan=True) or type(self.internet) is not bool:
            raise ValueError("address_invalid")
        return dict(world_directory=self.selection.parent, bind_address=self.address,
                    host_route=self.address, public=self.internet)


@dataclass(frozen=True)
class UiEvent:
    kind: str
    code: str
    state: str = ""
    autosave_enabled: bool | None = None


class SessionWorker:
    """One session at a time; close requests never abandon live cleanup."""

    def __init__(self, installation, private_root, *, factory=LauncherSession, importer=None):
        self.installation, self.private_root, self.factory = installation, private_root, factory
        self.importer = importer
        self.importing = False
        self.checking_connection = False
        self.events = queue.SimpleQueue()
        self._lock = threading.Lock()
        self._thread = self._loop = self._task = None
        self._cancel_requested = False
        self._state = SessionState.NEW
        self._status_code = "new"
        self._active_session = self._save_future = None
        self._save_pending = False
        self._settings_future = None
        self._settings_pending = False

    @property
    def busy(self):
        return self._thread is not None and self._thread.is_alive()

    @property
    def holds_game(self):
        with self._lock:
            return self._status_code in _RETAINS_GAME

    def start(self, request):
        options = request.options()
        with self._lock:
            if self.busy:
                return False
            self._cancel_requested = False
            self._state = SessionState.NEW
            self._status_code = "new"
            self._thread = threading.Thread(target=self._run, args=(options,),
                                            name="emerald-launcher-session", daemon=False)
            self._thread.start()
        return True

    def start_import(self, source):
        with self._lock:
            if self.busy or self.importer is None:
                return False
            self.importing = True
            self._state = SessionState.RUNNING
            self._thread = threading.Thread(target=self._run_import, args=(source,),
                                            name="emerald-game-import", daemon=False)
            self._thread.start()
        return True

    def _run_import(self, source):
        code = "imported"
        try:
            self.importer.install(source)
        except Exception as error:
            candidate = getattr(error, "code", None)
            code = candidate if candidate in _TEXT else "import_destination"
        finally:
            with self._lock:
                self.importing = False
            self.events.put(UiEvent("complete", code))

    def start_probe(self, invitation):
        with self._lock:
            if self.busy:
                return False
            self.checking_connection = True
            self._state = SessionState.RUNNING
            self._thread = threading.Thread(target=self._run_probe, args=(invitation,),
                                            name="emerald-connection-check", daemon=False)
            self._thread.start()
        return True

    def _run_probe(self, invitation):
        code = "unreachable"
        try:
            from .network_diagnostics import probe_invitation
            result = asyncio.run(probe_invitation(invitation, self.private_root / "network-checks"))
            candidate = result.code + "_" + result.route_scope if result.tls_verified else result.code
            code = candidate if candidate in _TEXT else "unreachable"
        except Exception:
            pass
        finally:
            with self._lock:
                self.checking_connection = False
            self.events.put(UiEvent("complete", code))

    def cancel_startup(self):
        with self._lock:
            # Closing the launcher during play waits for ordinary game closure.
            # It does not choose an unsaved-progress/disconnect policy.
            if not self.busy or self._state in {SessionState.RUNNING, SessionState.FINISHED}:
                return False
            if not self._cancel_requested:
                self._cancel_requested = True
                if self._loop is not None and self._task is not None:
                    self._loop.call_soon_threadsafe(self._task.cancel)
            return True

    def request_save(self):
        with self._lock:
            if (not self.busy or self._state is not SessionState.RUNNING or self._loop is None
                    or self._active_session is None or self._save_pending):
                return False
            self._save_pending = True
            self._loop.call_soon_threadsafe(self._begin_save)
            return True

    def _begin_save(self):
        self._save_future = asyncio.create_task(self._save(), name="launcher-save-action")

    async def _save(self):
        try:
            if self._active_session is None:
                return
            await self._active_session.save()
        except Exception as error:
            code = getattr(error, "code", "save_recovery_required")
            self.events.put(UiEvent("status", code if code in _TEXT else "save_recovery_required", "running"))
        finally:
            with self._lock:
                self._save_pending = False

    def request_autosave(self, enabled):
        with self._lock:
            if (type(enabled) is not bool or not self.busy or self._state is not SessionState.RUNNING
                    or self._loop is None or self._active_session is None or self._settings_pending):
                return False
            self._settings_pending = True
            self._loop.call_soon_threadsafe(self._begin_settings, enabled)
            return True

    def _begin_settings(self, enabled):
        self._settings_future = asyncio.create_task(self._set_autosave(enabled), name="launcher-autosave-setting")

    async def _set_autosave(self, enabled):
        try:
            if self._active_session is not None:
                await self._active_session.set_autosave_enabled(enabled)
        except Exception as error:
            code = getattr(error, "code", "settings_unavailable")
            current = self._active_session
            self.events.put(UiEvent("status", code if code in _TEXT else "settings_unavailable", "running",
                                   getattr(current, "autosave_enabled", None)))
        finally:
            with self._lock:
                self._settings_pending = False

    def _publish(self, status):
        with self._lock:
            self._state = status.state
            self._status_code = status.code
        if status.state != SessionState.CLOSED:
            code = status.code if status.code in _TEXT else "session_failed"
            self.events.put(UiEvent("status", code, status.state.value, status.autosave_enabled))

    async def _session(self, options):
        session = self.factory(self.installation, self.private_root, on_status=self._publish, **options)
        async with session.open():
            current = session.status
            if current.state != SessionState.READY:
                return current.code if current.code in _TEXT else "session_failed"
            with self._lock:
                self._active_session = session
            play = asyncio.create_task(session.play())
            try:
                observed = None
                while not play.done():
                    status = session.status
                    signature = status.state, status.code, status.connected, status.autosave_enabled
                    if signature != observed:
                        self._publish(status)
                        observed = signature
                    await asyncio.wait({play}, timeout=.2)
                exit_code = await play
                if session.status.code == "save_recovery_required":
                    return "save_recovery_required"
                return "game_closed" if exit_code == 0 else "session_failed"
            finally:
                if not play.done():
                    play.cancel()
                await asyncio.gather(play, return_exceptions=True)
                with self._lock:
                    self._active_session = None
                canceled = False
                if self._save_future is not None:
                    from .player_runtime import _finish_even_if_cancelled
                    _, interrupted = await _finish_even_if_cancelled(self._save_future)
                    canceled |= interrupted
                if self._settings_future is not None:
                    from .player_runtime import _finish_even_if_cancelled
                    _, interrupted = await _finish_even_if_cancelled(self._settings_future)
                    canceled |= interrupted
                if canceled:
                    raise asyncio.CancelledError()

    async def _execute(self, options):
        with self._lock:
            self._loop = asyncio.get_running_loop()
            self._task = asyncio.current_task()
            cancelled = self._cancel_requested
        if cancelled:
            raise asyncio.CancelledError()
        return await self._session(options)

    def _run(self, options):
        code = "session_failed"
        try:
            code = asyncio.run(self._execute(options))
        except asyncio.CancelledError:
            code = "cancelled"
        except Exception as error:
            candidate = getattr(error, "code", None)
            code = candidate if candidate in _TEXT else "session_failed"
        finally:
            with self._lock:
                self._loop = self._task = None
                self._active_session = self._save_future = None
                self._save_pending = False
                self._settings_future = None
                self._settings_pending = False
            # asyncio.run has drained its loop before completion becomes visible.
            self.events.put(UiEvent("complete", code))


class LauncherWindow:
    def __init__(self, root, worker=None, *, version="Development preview"):
        import tkinter as tk
        from tkinter import ttk

        self.root, self.worker = root, worker
        self.closing = False
        self.setup_window = None
        self.close_after_setup = False
        self.selection = {"host": None, "join": None}
        self.controls = []
        root.title("Emerald Together")
        root.minsize(640, 680)
        root.geometry("700x730")
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.report_callback_exception = lambda *_: self.message.set(status_text("session_failed"))
        body = ttk.Frame(root, padding=24)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Emerald Together", font=("Segoe UI", 25, "bold")).pack(anchor="w")
        ttk.Label(body, text="Your world. Up to four players.", font=("Segoe UI", 11)).pack(anchor="w", pady=(2, 6))
        ttk.Label(body, text=version + " · Private multiplayer preview", foreground="#52635c").pack(anchor="w", pady=(0, 18))
        self.import_button = ttk.Button(body, text="Import my game…", command=self.import_game)
        self.import_button.pack(anchor="w", pady=(0, 6))
        if getattr(worker, "importer", None) is None:
            self.import_button.configure(state="disabled")
            ttk.Label(body, text=status_text("import_unavailable"), wraplength=640).pack(anchor="w", pady=(0, 12))
        else:
            ttk.Label(body, text="Select your own game dump once to install this release.",
                      wraplength=640).pack(anchor="w", pady=(0, 12))
        self.setup_button = ttk.Button(body, text="Set up a world or character…", command=self.open_setup)
        self.setup_button.pack(anchor="w", pady=(0, 12))
        self.controls.append(self.setup_button)
        tabs = ttk.Notebook(body)
        tabs.pack(fill="both", expand=True)
        self.tabs = tabs
        self.address = tk.StringVar(value="127.0.0.1")
        self.internet = tk.BooleanVar(value=False)
        for mode, title, description in (
            ("host", "Host Game", "Open your existing private world on this PC."),
            ("join", "Join Game", "Open the personal invitation your host gave you."),
        ):
            page = ttk.Frame(tabs, padding=20)
            tabs.add(page, text=title)
            ttk.Label(page, text=description, wraplength=570).pack(anchor="w", pady=(0, 14))
            label = tk.StringVar(value="No world selected" if mode == "host" else "No invitation selected")
            setattr(self, mode + "_label", label)
            browse = ttk.Button(page, text="Choose world…" if mode == "host" else "Choose invitation…",
                                command=lambda m=mode: self.browse(m))
            browse.pack(anchor="w")
            self.controls.append(browse)
            ttk.Label(page, textvariable=label, wraplength=570).pack(anchor="w", pady=(7, 16))
            if mode == "host":
                ttk.Label(page, text="Host address on this PC").pack(anchor="w")
                address = ttk.Entry(page, textvariable=self.address, width=32)
                address.pack(anchor="w", pady=(4, 5))
                self.controls.append(address)
                ttk.Label(page, text="Use your Wi-Fi address for friends on your network.\n127.0.0.1 is for this PC only.",
                          wraplength=570).pack(anchor="w")
                internet = ttk.Checkbutton(page, text="Allow Internet connections", variable=self.internet)
                internet.pack(anchor="w", pady=(10, 0))
                self.controls.append(internet)
            else:
                ttk.Label(page, text="Your invitation supplies the host and your character.\nKeep it private; each friend has a separate invitation.",
                          wraplength=570).pack(anchor="w", pady=(0, 15))
                probe = ttk.Button(page, text="Check connection", command=self.check_connection)
                probe.pack(anchor="w", pady=(0, 4))
                self.controls.append(probe)
            action = ttk.Button(page, text=title, command=lambda m=mode: self.start(m))
            action.pack(anchor="w", pady=(16, 0))
            self.controls.append(action)
        self.message = tk.StringVar(value=status_text("idle" if worker else "package_missing"))
        ttk.Separator(body).pack(fill="x", pady=(18, 12))
        self.status_label = ttk.Label(body, textvariable=self.message, wraplength=640)
        self.status_label.pack(fill="x", anchor="w")
        actions = ttk.Frame(body)
        actions.pack(fill="x", pady=(10, 0))
        self.save_button = ttk.Button(actions, text="Save now", command=self.save_now, state="disabled")
        self.save_button.pack(side="left")
        self.autosave_value = tk.BooleanVar(value=True)
        self._autosave_observed = True
        self.autosave_button = ttk.Checkbutton(actions, text="Autosave every 5 minutes",
            variable=self.autosave_value, command=self.toggle_autosave, state="disabled")
        self.autosave_button.pack(side="left", padx=(12, 0))
        self.cancel = ttk.Button(actions, text="Cancel startup", command=self.cancel_startup, state="disabled")
        self.cancel.pack(side="right")
        if worker is None:
            self._enable(False)
        self._poll_id = root.after(80, self.poll)

    def _enable(self, enabled):
        for control in self.controls:
            control.configure(state="normal" if enabled else "disabled")
        self.import_button.configure(state="normal" if enabled and getattr(self.worker, "importer", None) else "disabled")

    def import_game(self):
        from tkinter import filedialog
        if self.worker is None or self.worker.busy or self.worker.importer is None:
            return
        source = filedialog.askopenfilename(parent=self.root, title="Choose your own game dump",
                                           filetypes=[("Game Boy Advance dump", "*.gba")])
        if source and self.worker.start_import(Path(source)):
            self._enable(False)
            self.cancel.configure(state="disabled")
            self.message.set(status_text("importing"))

    def browse(self, mode):
        from tkinter import filedialog
        path = filedialog.askopenfilename(parent=self.root,
            title="Choose your private world" if mode == "host" else "Choose your friend invitation",
            filetypes=[("World record" if mode == "host" else "Friend invitation", "*.json")])
        if path:
            self.selection[mode] = Path(path)
            # File contents, complete paths and credentials never appear here.
            getattr(self, mode + "_label").set("World selected" if mode == "host" else "Invitation selected")

    def open_setup(self):
        if self.worker is None or self.worker.busy or self.setup_window is not None:
            return
        from .launcher_setup_gui import SetupWindow
        selected = self.selection["host"]
        def finished(world_directory):
            self.setup_window = None
            if world_directory is not None:
                self.selection["host"] = world_directory / "host.json"
                self.host_label.set("World selected")
            if self.close_after_setup:
                self._destroy()
            else:
                self._enable(True)
        self._enable(False)
        self.setup_window = SetupWindow(self.root, self.worker.installation, self.worker.private_root,
            selected_world=selected.parent if selected else None, on_close=finished)

    def start(self, mode):
        if self.worker is None or self.worker.busy:
            return
        selected = self.selection[mode]
        if selected is None:
            self.message.set(status_text("selection_required"))
            return
        request = LaunchRequest(mode, selected, self.address.get().strip(), self.internet.get())
        try:
            started = self.worker.start(request)
        except ValueError as error:
            self.message.set(status_text(error.args[0] if error.args else "session_failed"))
            return
        if started:
            self._enable(False)
            self.cancel.configure(state="normal")
            self.message.set(status_text("installation"))

    def cancel_startup(self):
        if self.worker is not None and self.worker.cancel_startup():
            self.cancel.configure(state="disabled")
            self.message.set(status_text("closing"))

    def save_now(self):
        if not self.closing and self.worker is not None and self.worker.request_save():
            self.save_button.configure(state="disabled")
            self.message.set(status_text("saving"))

    def toggle_autosave(self):
        if (self.closing or self.worker is None
                or not self.worker.request_autosave(self.autosave_value.get())):
            self.autosave_value.set(self._autosave_observed)
        else:
            self.autosave_button.configure(state="disabled")

    def check_connection(self):
        if self.worker is None or self.worker.busy:
            return
        selected = self.selection["join"]
        if selected is None:
            self.message.set(status_text("selection_required"))
        elif self.worker.start_probe(selected):
            self._enable(False)
            self.cancel.configure(state="disabled")
            self.message.set(status_text("checking_connection"))

    def close(self):
        if self.setup_window is not None:
            self.close_after_setup = True
            self.setup_window.close()
            return
        if self.worker is None or not self.worker.busy:
            self._destroy()
            return
        if getattr(self.worker, "holds_game", False):
            self.message.set(status_text("wait_for_recovery"))
            return
        self.closing = True
        self._enable(False)
        self.save_button.configure(state="disabled")
        self.autosave_button.configure(state="disabled")
        cancelled = self.worker.cancel_startup()
        self.cancel.configure(state="disabled")
        code = "closing" if cancelled else "wait_for_game"
        if getattr(self.worker, "importing", False):
            code = "wait_for_import"
        elif getattr(self.worker, "checking_connection", False):
            code = "wait_for_connection"
        self.message.set(status_text(code))

    def _destroy(self):
        self.root.after_cancel(self._poll_id)
        self.root.destroy()

    def poll(self):
        if self.worker is not None:
            while True:
                try:
                    event = self.worker.events.get_nowait()
                except queue.Empty:
                    break
                if event.kind == "complete":
                    if self.closing:
                        self._destroy()
                        return
                    self._enable(True)
                    self.cancel.configure(state="disabled")
                    self.save_button.configure(state="disabled")
                    self.autosave_button.configure(state="disabled")
                    self.message.set(status_text(event.code))
                elif self.closing and event.code in _RETAINS_GAME:
                    self.closing = False
                    self.message.set(status_text("wait_for_recovery"))
                elif not self.closing:
                    self.message.set(status_text(event.code))
                    if event.autosave_enabled is not None:
                        self._autosave_observed = event.autosave_enabled
                        self.autosave_value.set(event.autosave_enabled)
                    self.autosave_button.configure(state="normal" if event.state == "running" else "disabled")
                    self.save_button.configure(state="normal" if event.state == "running"
                        and event.code in {"running", "saved", "save_not_ready", "autosave_on", "autosave_off",
                                           "autosave_deferred", "settings_unavailable", "settings_busy",
                                           "trade_finished", "trade_cancelled", "battle_finished", "battle_cancelled"} else "disabled")
                    if event.state in {"running", "finished"}:
                        self.cancel.configure(state="disabled")
        self._poll_id = self.root.after(80, self.poll)


def main(release=None, application_directory=None, import_release=None):
    """Packaged entry supplies compiled release pins; source launch is a preview."""
    import tkinter as tk
    root = tk.Tk()
    worker = None
    private_error = False
    if release is not None:
        try:
            private = private_directory()
            importer = None
            if import_release is not None:
                from .game_import import GameImporter
                if import_release.target_sha256 != release.rom_sha256:
                    raise ValueError("release mismatch")
                importer = GameImporter(import_release, Path(application_directory) / "game.bps", private)
            worker = SessionWorker(release.installation(application_directory, private), private, importer=importer)
        except Exception:
            private_error = True
    window = LauncherWindow(root, worker, version=release.version if release else "Development preview")
    if private_error:
        window.message.set(status_text("private_storage"))
    root.mainloop()


if __name__ == "__main__":
    main()
