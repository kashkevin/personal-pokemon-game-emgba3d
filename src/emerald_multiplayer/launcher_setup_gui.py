"""Explicit local-host setup UI; existing-character play stays in LauncherSession."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import queue
import threading


MESSAGES = {
    "idle": "Create a world, or choose an existing world to set up a character.",
    "working": "Checking the game and private world…",
    "created": "World created and selected. Set up each character before play.",
    "exported": "Friend invitation saved. Give this file only to that friend.",
    "ready": "In the game window, Continue to a safe place outside menus and battles. Then finish enrollment here.",
    "not_ready": "The game is still busy. Reach a safe place outside menus and battles, then press Finish enrollment again.",
    "enrolled": "Character enrolled. Close setup and use Host Game or Join Game.",
    "closing": "Closing setup and retaining private recovery files…",
    "cancelled": "Setup closed. Original source saves were retained.",
    "selection": "Choose the world and original character save first.",
    "approval": "The host must explicitly approve this save for the selected character.",
    "invalid_configuration": "Check the player names, numeric address, port and selected character.",
    "installation_changed": "Install the matching game release before creating a world or enrolling a character.",
    "enrollment_pending": "This character has an interrupted setup. Its private files were retained for recovery.",
    "source_invalid": "This source cannot be enrolled. Use an ordinary saved character with no assigned multiplayer ownership.",
    "invalid_source": "This source cannot be enrolled. Use an ordinary saved character with no assigned multiplayer ownership.",
    "setup_failed": "Setup could not finish. Existing worlds, original saves and recovery files were retained.",
    "world_invalid": "This private host world could not be verified.",
    "world_active": "Close the running host before setting up a character.",
    "invalid_profile": "Choose a character that exists in this world.",
    "invitation_exists": "That file already exists. Choose a new invitation filename.",
    "source_required": "Choose an ordinary saved character after starter selection.",
    "source_changed": "The approved source changed. Setup stopped without replacing it.",
    "source_already_enrolled": "This source was already approved for another character.",
    "already_enrolled": "This character is already enrolled. Use normal Host Game or Join Game.",
    "recovery_required": "A previous setup needs recovery. Its private files were retained.",
    "pending_battle": "An interrupted battle needs recovery before setup can continue.",
    "mirror_active": "This character is already open in another game or controller.",
    "connection_timeout": "The local host did not authenticate this character in time.",
    "connection_lost": "The authenticated host connection was lost.",
    "session_changed": "The authenticated session changed. Setup stopped safely.",
    "draft_running": "In the game: choose New Game, choose a starter, use the normal Save menu, then close the game window.",
    "draft_created": "New saved character selected. The host must now approve and enroll it for the chosen account.",
    "draft_unsaved": "Save normally after choosing a starter, then close the game. Incomplete drafts are retained privately.",
    "draft_active": "Close the draft game normally before completing character preparation.",
    "save_required": "Create a character, choose a starter and use the game’s Save menu before closing it.",
    "starter_required": "Choose a starter and save through the game’s menu before enrollment.",
    "game_running": "Save through the game’s menu and close the game window first.",
    "game_failed": "The draft game did not close normally. Its private files were retained.",
    "draft_failed": "New-character preparation could not finish. Its private files were retained.",
}


def message(code):
    return MESSAGES.get(code, MESSAGES["setup_failed"])


@dataclass(frozen=True)
class SetupEvent:
    kind: str
    code: str
    world_directory: Path | None = None
    source_path: Path | None = None


class SetupWorker:
    """Only fixed events cross threads. The host explicitly requests enrollment."""
    def __init__(self, installation, private_root, *, controller=None, draft_factory=None):
        if controller is None:
            from . import launcher_setup as controller
        self.controller, self.installation, self.private_root = controller, installation, private_root
        self.draft_factory = draft_factory
        self.events = queue.SimpleQueue()
        self.thread = self.loop = self.task = self.finish_event = None
        self.lock = threading.Lock()
        self.cancelled = False
        self.ready = False

    @property
    def busy(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self, operation, **options):
        with self.lock:
            if self.busy:
                return False
            self.cancelled = self.ready = False
            self.thread = threading.Thread(target=self._run, args=(operation, options), daemon=False,
                                           name="emerald-host-setup")
            self.thread.start()
        return True

    def finish(self):
        with self.lock:
            if not self.ready or self.loop is None:
                return False
            self.ready = False
            self.loop.call_soon_threadsafe(self.finish_event.set)
            return True

    def cancel(self):
        with self.lock:
            if not self.cancelled:
                self.cancelled = True
                if self.loop is not None and self.task is not None:
                    self.loop.call_soon_threadsafe(self.task.cancel)

    async def _enroll(self, options):
        with self.lock:
            self.loop, self.task = asyncio.get_running_loop(), asyncio.current_task()
            self.finish_event = asyncio.Event()
            cancelled = self.cancelled
        if cancelled:
            raise asyncio.CancelledError()
        async with self.controller.host_enrollment(self.installation, self.private_root, **options) as runtime:
            code = "ready"
            while True:
                self.finish_event.clear()
                with self.lock:
                    self.ready = True
                self.events.put(SetupEvent("ready", code))
                await self.finish_event.wait()
                try:
                    await runtime.enroll()
                    break
                except Exception as error:
                    # Only the checkpoint coordinator's explicit no-export
                    # decision permits a second user action in the same child.
                    # Never retry automatically or reopen an uncertain export.
                    from .live_checkpoint import LiveSaveError
                    if not isinstance(error, LiveSaveError) or error.safe_to_retry is not True:
                        raise
                    code = "not_ready"

    async def _draft(self):
        factory = self.draft_factory
        if factory is None:
            from .draft_runtime import DraftRuntime
            factory = DraftRuntime
        with self.lock:
            self.loop, self.task = asyncio.get_running_loop(), asyncio.current_task()
            cancelled = self.cancelled
        if cancelled:
            raise asyncio.CancelledError()
        draft = factory(self.installation, self.private_root)
        async with draft.open() as game:
            self.events.put(SetupEvent("status", "draft_running"))
            await game.wait()
            receipt = draft.finish()
        return receipt.source_path

    def _run(self, operation, options):
        code, world_directory, source_path = "setup_failed", None, None
        try:
            if operation == "create":
                world = self.controller.create_world(self.installation, self.private_root, **options)
                code, world_directory = "created", world.directory
            elif operation == "export":
                self.controller.export_friend_invitation(self.installation, **options)
                code = "exported"
            elif operation == "enroll":
                asyncio.run(self._enroll(options))
                code = "enrolled"
            elif operation == "draft":
                source_path = asyncio.run(self._draft())
                code = "draft_created"
        except asyncio.CancelledError:
            code = "cancelled"
        except Exception as error:
            candidate = getattr(error, "code", None)
            code = candidate if candidate in MESSAGES else "setup_failed"
        finally:
            with self.lock:
                self.ready = False
                self.loop = self.task = self.finish_event = None
            self.events.put(SetupEvent("complete", code, world_directory, source_path))


class SetupWindow:
    def __init__(self, parent, installation, private_root, *, selected_world=None, on_close=None, worker=None):
        import tkinter as tk
        from tkinter import ttk
        self.root = tk.Toplevel(parent)
        self.root.title("Set up Emerald Together")
        self.root.geometry("760x750")
        self.root.minsize(740, 720)
        self.root.transient(parent)
        self.root.grab_set()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.worker = worker or SetupWorker(installation, private_root)
        self.on_close, self.closing = on_close, False
        self.world_directory, self.source_path = selected_world, None
        self.controls = []
        body = ttk.Frame(self.root, padding=20)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Private world setup", font=("Segoe UI", 20, "bold")).pack(anchor="w")
        ttk.Label(body, text="The host creates accounts and approves each exact character save.",
                  wraplength=710).pack(anchor="w", pady=(4, 12))
        tabs = ttk.Notebook(body)
        tabs.pack(fill="both", expand=True)
        create, enroll = ttk.Frame(tabs, padding=16), ttk.Frame(tabs, padding=16)
        tabs.add(create, text="Create world")
        tabs.add(enroll, text="Set up character")
        self.names = []
        for index, label in enumerate(("Host name", "Friend 1 name (optional)", "Friend 2 name (optional)", "Friend 3 name (optional)")):
            value = tk.StringVar()
            self.names.append(value)
            ttk.Label(create, text=label).grid(row=index, column=0, sticky="w", pady=5)
            entry = ttk.Entry(create, textvariable=value, width=28)
            entry.grid(row=index, column=1, sticky="w", padx=12)
            self.controls.append(entry)
        self.endpoint, self.port = tk.StringVar(value="127.0.0.1"), tk.StringVar(value="8765")
        for index, label, value in ((4, "Address friends will use", self.endpoint), (5, "Game port", self.port)):
            ttk.Label(create, text=label).grid(row=index, column=0, sticky="w", pady=5)
            entry = ttk.Entry(create, textvariable=value, width=28)
            entry.grid(row=index, column=1, sticky="w", padx=12)
            self.controls.append(entry)
        ttk.Label(create, text="Use your PC’s Wi-Fi address for LAN play. Internet hosting requires\nyour public numeric address and your router’s matching port forward.",
                  wraplength=650).grid(row=6, column=0, columnspan=2, sticky="w", pady=12)
        button = ttk.Button(create, text="Create private world", command=self.create)
        button.grid(row=7, column=0, columnspan=2, sticky="w")
        self.controls.append(button)
        ttk.Label(enroll, text="Create a new character with ordinary New Game, or choose an\nexisting character saved normally after starter selection.",
                  wraplength=650).pack(anchor="w", pady=(0, 10))
        draft = ttk.Button(enroll, text="Create a new character…", command=lambda: self.start("draft"))
        draft.pack(anchor="w", pady=(0, 8))
        self.controls.append(draft)
        self.world_label = tk.StringVar(value="World selected" if selected_world else "No world selected")
        self.source_label = tk.StringVar(value="No source save selected")
        for text, command, variable in (("Choose host world…", self.choose_world, self.world_label),
                                        ("Choose original character save…", self.choose_source, self.source_label)):
            button = ttk.Button(enroll, text=text, command=command)
            button.pack(anchor="w", pady=(4, 0))
            self.controls.append(button)
            ttk.Label(enroll, textvariable=variable).pack(anchor="w", pady=(4, 8))
        self.slot = tk.StringVar(value="Host")
        slot = ttk.Combobox(enroll, state="readonly", textvariable=self.slot,
                           values=("Host", "Friend 1", "Friend 2", "Friend 3"))
        slot.pack(anchor="w")
        self.slot_control = slot
        self.controls.append(slot)
        self.approval = tk.BooleanVar(value=False)
        slot.bind("<<ComboboxSelected>>", lambda _: self.approval.set(False))
        approved = ttk.Checkbutton(enroll, text="I am the host and approve this exact save for this character.", variable=self.approval)
        approved.pack(anchor="w", pady=12)
        self.controls.append(approved)
        for text, command in (("Approve and open character", self.enroll), ("Export this friend’s invitation…", self.export)):
            button = ttk.Button(enroll, text=text, command=command)
            button.pack(anchor="w", pady=4)
            self.controls.append(button)
        self.finish_button = ttk.Button(enroll, text="I’m in the world — finish enrollment", command=self.finish, state="disabled")
        self.finish_button.pack(anchor="w", pady=(12, 0))
        self.status = tk.StringVar(value=message("idle"))
        ttk.Separator(body).pack(fill="x", pady=12)
        ttk.Label(body, textvariable=self.status, wraplength=700).pack(fill="x")
        ttk.Button(body, text="Close setup", command=self.close).pack(anchor="e", pady=(10, 0))
        self.root.report_callback_exception = lambda *_: self.status.set(message("setup_failed"))
        self.poll_id = self.root.after(80, self.poll)

    def set_enabled(self, enabled):
        for control in self.controls:
            control.configure(state="normal" if enabled else "disabled")
        if enabled:
            self.slot_control.configure(state="readonly")

    def start(self, operation, **options):
        if self.worker.start(operation, **options):
            self.set_enabled(False)
            self.status.set(message("working"))

    def create(self):
        names = [value.get().strip() for value in self.names]
        while names and not names[-1]:
            names.pop()
        try:
            port = int(self.port.get())
        except ValueError:
            self.status.set(message("invalid_configuration"))
            return
        self.start("create", player_names=names, endpoint=self.endpoint.get().strip(), port=port)

    def choose_world(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(parent=self.root, title="Choose private host.json", filetypes=[("Host world", "host.json")])
        if path:
            self.world_directory = Path(path).parent
            self.world_label.set("World selected")
            self.approval.set(False)

    def choose_source(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(parent=self.root, title="Choose original saved character", filetypes=[("Character save", "*.sav")])
        if path:
            self.source_path = Path(path)
            self.source_label.set("Original save selected; it will be preserved")
            self.approval.set(False)

    def selected_slot(self):
        return ("Host", "Friend 1", "Friend 2", "Friend 3").index(self.slot.get())

    def enroll(self):
        if not self.world_directory or not self.source_path:
            self.status.set(message("selection"))
        elif not self.approval.get():
            self.status.set(message("approval"))
        else:
            self.start("enroll", world_directory=self.world_directory, slot=self.selected_slot(),
                       source_path=self.source_path, bind_address="127.0.0.1", host_route="127.0.0.1")

    def export(self):
        from tkinter import filedialog
        if self.world_directory is None or self.selected_slot() == 0:
            self.status.set("Choose a world and a friend’s character before exporting an invitation.")
            return
        path = filedialog.asksaveasfilename(parent=self.root, title="Save this friend’s private invitation",
            defaultextension=".json", filetypes=[("Friend invitation", "*.json")], initialfile="friend-invitation.json")
        if path:
            self.start("export", world_directory=self.world_directory, slot=self.selected_slot(), destination=Path(path))

    def finish(self):
        if self.worker.finish():
            self.finish_button.configure(state="disabled")
            self.status.set("Enrolling and saving the verified character…")

    def close(self):
        if self.worker.busy:
            self.closing = True
            self.set_enabled(False)
            self.finish_button.configure(state="disabled")
            self.status.set(message("closing"))
            self.worker.cancel()
        else:
            self.destroy()

    def destroy(self):
        self.root.after_cancel(self.poll_id)
        self.root.grab_release()
        self.root.destroy()
        if self.on_close:
            self.on_close(self.world_directory)

    def poll(self):
        while not self.worker.events.empty():
            event = self.worker.events.get_nowait()
            if event.world_directory is not None:
                self.world_directory = event.world_directory
                self.world_label.set("World selected")
            if event.source_path is not None:
                self.source_path = event.source_path
                self.source_label.set("New saved character selected")
                self.approval.set(False)
            if event.kind == "complete":
                if self.closing:
                    self.destroy()
                    return
                self.set_enabled(True)
                self.finish_button.configure(state="disabled")
                self.status.set(message(event.code))
            elif event.kind == "ready" and not self.closing:
                self.finish_button.configure(state="normal")
                self.status.set(message(event.code))
            elif event.kind == "status" and not self.closing:
                self.status.set(message(event.code))
        self.poll_id = self.root.after(80, self.poll)
