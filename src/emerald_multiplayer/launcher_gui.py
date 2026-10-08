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
    "package_missing": "This launcher preview needs a verified game package before play.",
    "selection_required": "Choose your world or friend invitation first.",
    "address_invalid": "Enter this PC’s local IPv4 or IPv6 address, such as 192.168.1.20.",
    "private_storage": "Your private application folder could not be opened.",
    "enrollment_required": "This character needs first-time setup. This window currently opens existing characters.",
    "pending_battle": "An interrupted battle needs recovery before this character can open.",
    "recovery_required": "Your character needs recovery before the game can open. Its private files have been retained.",
    "connection_timeout": "The host did not respond. Check that the host is running and the invitation is current.",
    "connection_lost": "Connection to the host was lost. Reconnection handling is not enabled in this build.",
    "session_changed": "The host session changed. Close the game before reopening your character.",
    "mirror_active": "This character is already open in another game window.",
    "invalid_invitation": "This invitation could not be verified. Ask the host for a current invitation.",
    "world_invalid": "This private world could not be verified.",
    "certificate_invalid": "The host’s invitation or certificate needs renewal.",
    "build_mismatch": "Your game version does not match the host’s invitation.",
    "installation_changed": "Game files are missing or changed. Reinstall the matching game package.",
    "runtime_hash": "Runtime files are missing or changed. Reinstall the matching game package.",
    "runtime_manifest": "The installed runtime could not be verified.",
    "runtime_path": "The installed runtime could not be verified.",
    "runtime_unlisted": "The installed runtime contains unexpected files.",
    "runtime_size": "The installed runtime could not be verified.",
    "trade_recovery_unavailable": "The host does not support the character recovery required by this build.",
    "session_failed": "The game could not open. Private character and recovery files have been retained.",
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
}


def status_text(code):
    """Never put exception text, credentials, endpoints or paths into status UI."""
    return _TEXT.get(code, _TEXT["session_failed"])


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


class SessionWorker:
    """One session at a time; close requests never abandon live cleanup."""

    def __init__(self, installation, private_root, *, factory=LauncherSession, importer=None):
        self.installation, self.private_root, self.factory = installation, private_root, factory
        self.importer = importer
        self.importing = False
        self.events = queue.SimpleQueue()
        self._lock = threading.Lock()
        self._thread = self._loop = self._task = None
        self._cancel_requested = False
        self._state = SessionState.NEW

    @property
    def busy(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, request):
        options = request.options()
        with self._lock:
            if self.busy:
                return False
            self._cancel_requested = False
            self._state = SessionState.NEW
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

    def _publish(self, status):
        with self._lock:
            self._state = status.state
        if status.state != SessionState.CLOSED:
            code = status.code if status.code in _TEXT else "session_failed"
            self.events.put(UiEvent("status", code, status.state.value))

    async def _session(self, options):
        session = self.factory(self.installation, self.private_root, on_status=self._publish, **options)
        async with session.open():
            current = session.status
            if current.state != SessionState.READY:
                return current.code if current.code in _TEXT else "session_failed"
            play = asyncio.create_task(session.play())
            try:
                observed = None
                while not play.done():
                    status = session.status
                    signature = status.state, status.code, status.connected
                    if signature != observed:
                        self._publish(status)
                        observed = signature
                    await asyncio.wait({play}, timeout=.2)
                exit_code = await play
                return "game_closed" if exit_code == 0 else "session_failed"
            finally:
                if not play.done():
                    play.cancel()
                await asyncio.gather(play, return_exceptions=True)

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
            # asyncio.run has drained its loop before completion becomes visible.
            self.events.put(UiEvent("complete", code))


class LauncherWindow:
    def __init__(self, root, worker=None, *, version="Development preview"):
        import tkinter as tk
        from tkinter import ttk

        self.root, self.worker = root, worker
        self.closing = False
        self.selection = {"host": None, "join": None}
        self.controls = []
        root.title("Emerald Together")
        root.minsize(640, 640)
        root.geometry("700x690")
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.report_callback_exception = lambda *_: self.message.set(status_text("session_failed"))
        body = ttk.Frame(root, padding=24)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Emerald Together", font=("Segoe UI", 25, "bold")).pack(anchor="w")
        ttk.Label(body, text="Your world. Up to four players.", font=("Segoe UI", 11)).pack(anchor="w", pady=(2, 6))
        ttk.Label(body, text=version + " · Existing characters", foreground="#52635c").pack(anchor="w", pady=(0, 18))
        self.import_button = ttk.Button(body, text="Import my game…", command=self.import_game)
        self.import_button.pack(anchor="w", pady=(0, 6))
        if getattr(worker, "importer", None) is None:
            self.import_button.configure(state="disabled")
            ttk.Label(body, text=status_text("import_unavailable"), wraplength=640).pack(anchor="w", pady=(0, 12))
        else:
            ttk.Label(body, text="Select your own game dump once to install this release.",
                      wraplength=640).pack(anchor="w", pady=(0, 12))
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
            action = ttk.Button(page, text=title, command=lambda m=mode: self.start(m))
            action.pack(anchor="w", pady=(16, 0))
            self.controls.append(action)
        self.message = tk.StringVar(value=status_text("idle" if worker else "package_missing"))
        ttk.Separator(body).pack(fill="x", pady=(18, 12))
        self.status_label = ttk.Label(body, textvariable=self.message, wraplength=640)
        self.status_label.pack(fill="x", anchor="w")
        self.cancel = ttk.Button(body, text="Cancel startup", command=self.cancel_startup, state="disabled")
        self.cancel.pack(anchor="e", pady=(10, 0))
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

    def close(self):
        if self.worker is None or not self.worker.busy:
            self._destroy()
            return
        self.closing = True
        self._enable(False)
        cancelled = self.worker.cancel_startup()
        self.cancel.configure(state="disabled")
        code = "closing" if cancelled else "wait_for_game"
        self.message.set(status_text("wait_for_import" if getattr(self.worker, "importing", False) else code))

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
                    self.message.set(status_text(event.code))
                elif not self.closing:
                    self.message.set(status_text(event.code))
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
