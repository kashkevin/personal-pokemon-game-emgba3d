"""Explicit local-host setup UI; existing-character play stays in LauncherSession."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import queue
import threading

from .tk_threads import start_thread
from .network_diagnostics import ConnectionDetails, inspect_invitation, route_scope


MESSAGES = {
    "idle": "Create a world, or choose an existing world to set up a character.",
    "working": "Checking the game and private world…",
    "created": "World created and selected. Set up each character before play.",
    "world_selected": "World selected. Choose the named player whose character you want to set up.",
    "exported": "Friend invitation saved. Give this file only to that friend.",
    "ready": "In the game window, Continue to a safe place outside menus and battles. Then finish enrollment here.",
    "not_ready": "The game is still busy. Reach a safe place outside menus and battles, then press Finish enrollment again.",
    "enrolled": "Character enrolled. Go back to My Worlds, then use Host Multiplayer or Join Friend.",
    "closing": "Closing setup and retaining private recovery files…",
    "cancelled": "Setup closed. Original source saves were retained.",
    "selection": "Choose the world and original character save first.",
    "approval": "The host must explicitly approve this save for the selected character.",
    "invalid_configuration": "Check the player names, numeric address, port and selected character.",
    "installation_changed": "Install the matching game release before creating a world or enrolling a character.",
    "runtime_path": "The game location could not be used. Choose a shorter installation or private-data path.",
    "enrollment_pending": "This character has an interrupted setup. Its private files were retained for recovery.",
    "source_invalid": "This source cannot be enrolled. Use an ordinary saved character with no assigned multiplayer ownership.",
    "invalid_source": "This source cannot be enrolled. Use an ordinary saved character with no assigned multiplayer ownership.",
    "setup_failed": "Setup could not finish. Existing worlds, original saves and recovery files were retained.",
    "world_invalid": "This private host world could not be verified.",
    "world_active": "Close the running host before setting up a character.",
    "trade_effect_policy_required": "Choose the world's trade friendship rule. An existing world's choice cannot be replaced here.",
    "trade_effect_migration_required": "Select the closed world and use Upgrade world features before hosting this game.",
    "trade_native_replay_failed": "The host could not verify native trade history. Existing saves and recovery records were retained.",
    "trade_effect_replay_required": "This world needs its matching game and native trade replay worker before character setup can continue.",
    "upgraded": "World features upgraded. Verified backups are retained beside the world database.",
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
    "draft_created": "Saved character selected. Friends: export it for your host. Hosts: select the account and explicitly approve enrollment.",
    "source_selected": "Closed, unassigned character verified and selected. The original save is preserved.",
    "character_ready": "Character verified. Choose a new .sav filename for the copy you will give your host.",
    "character_exported": "Character copy saved. Give only this .sav to your host for approval. Wait for enrollment, then use your personal invitation in Join Game. Keep the original as a backup; do not continue playing it.",
    "character_exists": "That file already exists. Choose a new filename; no existing save was replaced.",
    "character_destination": "Choose a new .sav file outside Emerald Together’s private data. Existing saves and world records cannot be replaced.",
    "draft_unsaved": "Save normally after choosing a starter, then close the game. Incomplete drafts are retained privately.",
    "draft_active": "Close the draft game normally before completing character preparation.",
    "save_required": "Create a character, choose a starter and use the game’s Save menu before closing it.",
    "starter_required": "Choose a starter and save through the game’s menu before enrollment.",
    "game_running": "Save through the game’s menu and close the game window first.",
    "game_failed": "The draft game did not close normally. Its private files were retained.",
    "game_closed": "The game was closed before the character was registered. Its private files were retained.",
    "draft_failed": "New-character preparation could not finish. Its private files were retained.",
}


def message(code):
    return MESSAGES.get(code, MESSAGES["setup_failed"])


TRADE_POLICIES = {
    "Shared world region; retain same-handler friendship": "gen6-stable-world-region-v1",
    "Missing geography; refresh handler friendship": "gen6-absent-geography-refresh-v1",
}


@dataclass(frozen=True)
class SetupEvent:
    kind: str
    code: str
    world_directory: Path | None = None
    source_path: Path | None = None
    accounts: tuple | None = None
    invitation_path: Path | None = None
    connection_details: ConnectionDetails | None = None
    character_source: object | None = None


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
            start_thread(self.thread)
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
        return receipt

    def _run(self, operation, options):
        code, world_directory, source_path = "setup_failed", None, None
        accounts = None
        invitation_path, connection_details = None, None
        character_source = None
        try:
            if operation == "create":
                world = self.controller.create_world(self.installation, self.private_root, **options)
                code, world_directory = "created", world.directory
                from .launcher_setup import SetupAccount
                accounts = tuple(SetupAccount(account.slot, account.display_name) for account in world.accounts)
            elif operation == "upgrade":
                world_directory = self.controller.upgrade_world_features(self.installation, **options)
                code = "upgraded"
            elif operation == "inspect":
                # Do not carry HostWorld (and its credentials) across the UI
                # queue; only the bounded roster labels leave this worker.
                accounts = self.controller.world_accounts(self.installation, options["world_directory"])
                code, world_directory = "world_selected", options["world_directory"]
            elif operation == "export":
                exported = self.controller.export_friend_invitation(self.installation, **options)
                code = "exported"
                invitation_path = Path(exported if exported is not None else options["destination"])
                # Export is already durable. A metadata display problem must
                # not claim it failed or encourage overwriting that capability.
                try:
                    connection_details = inspect_invitation(invitation_path,
                        expected_build=getattr(self.installation, "rom_sha256", None))
                except (OSError, ValueError):
                    pass
            elif operation == "enroll":
                asyncio.run(self._enroll(options))
                code = "enrolled"
            elif operation == "draft":
                from .character_handoff import CharacterSource
                receipt = asyncio.run(self._draft())
                source_path = receipt.source_path
                character_source = CharacterSource(source_path, receipt.sha256,
                    self.installation.rom_sha256, self.installation.manifest_sha256, receipt.party_count)
                code = "draft_created"
            elif operation in ("source", "prepare_character_export"):
                from .character_handoff import inspect_character_source
                character_source = inspect_character_source(self.installation, **options)
                source_path = character_source.path
                code = "source_selected" if operation == "source" else "character_ready"
            elif operation == "export_character":
                from .character_handoff import export_character_source
                export_character_source(self.installation, self.private_root, **options)
                code = "character_exported"
        except asyncio.CancelledError:
            code = "cancelled"
        except Exception as error:
            candidate = getattr(error, "code", None)
            code = candidate if candidate in MESSAGES else "setup_failed"
        finally:
            with self.lock:
                self.ready = False
                self.loop = self.task = self.finish_event = None
            self.events.put(SetupEvent("complete", code, world_directory, source_path, accounts,
                                       invitation_path, connection_details, character_source))


class SetupWindow:
    def __init__(self, parent, installation, private_root, *, selected_world=None, on_close=None, worker=None,
                 container=None, start_role=None):
        """A pop-up window by default. With ``container`` (a frame of the main menu's window) the same pages are built inside
        it instead: one window for the whole launcher, and the same worker, checks and messages. ``start_role`` ("host" or
        "friend") opens the matching page directly."""
        import tkinter as tk
        from tkinter import ttk
        self.embedded = container is not None
        if self.embedded:
            self.root = container
        else:
            self.root = tk.Toplevel(parent)
            self.root.title("Set up Emerald Together")
            self.root.geometry("760x750")
            self.root.minsize(740, 720)
            self.root.transient(parent)
            self.root.grab_set()
            self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.worker = worker or SetupWorker(installation, private_root)
        self.on_close, self.closing = on_close, False
        self.world_directory, self.source_path = None, None
        self.character_source = self.pending_character_export = None
        self.exported_details = None
        self.account_slots = {}
        self.controls = []
        body = self.body = ttk.Frame(self.root, padding=20)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="World & character setup", font=("Segoe UI", 20, "bold")).pack(anchor="w")
        ttk.Label(body, text="Prepare your own character. The host approves enrollment and gives each friend a private invitation.",
                  wraplength=710).pack(anchor="w", pady=(4, 12))
        # Reserve status/Close space before the expanding notebook. Long forms
        # scroll instead of pushing their completion actions off the window.
        footer = ttk.Frame(body)
        footer.pack(side="bottom", fill="x")
        tabs = ttk.Notebook(body)
        tabs.pack(fill="both", expand=True)
        self.tabs = tabs
        from .launcher_display import scrollable_frame
        start_page, create_page, character_page = (ttk.Frame(tabs) for _ in range(3))
        tabs.add(start_page, text="Start here")
        tabs.add(create_page, text="Create world")
        tabs.add(character_page, text="Set up character")
        self.create_page, self.character_page = create_page, character_page
        start, create, enroll = (scrollable_frame(page, padding=16)
                                 for page in (start_page, create_page, character_page))
        ttk.Label(start, text="First, use Import my game in the main launcher on every PC.",
                  wraplength=650).pack(anchor="w", pady=(0, 16))
        for title, detail, role in (
                ("I’m hosting", "Create one world with the host and friend names, choose the world’s trade rule, then approve a saved character for each account. Keep the whole world folder private.", "host"),
                ("I’m joining a friend", "Create a character, choose a starter and save normally. Export its .sav here and give it to your host for approval. After the host enrolls it, use your own invitation in Join Game; the host must be running.", "friend")):
            ttk.Label(start, text=detail, wraplength=650).pack(anchor="w", pady=(0, 8))
            button = ttk.Button(start, text=title, command=lambda r=role: self.begin_role(r))
            button.pack(anchor="w", pady=(0, 22))
            self.controls.append(button)
        ttk.Label(start, text="Already enrolled? Go back to the main menu and use Host Multiplayer or Join Friend. Do not export or re-enroll an owned multiplayer save.",
                  wraplength=650).pack(anchor="w")
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
        self.address_guidance = tk.StringVar()
        ttk.Label(create, textvariable=self.address_guidance, wraplength=650).grid(row=7, column=0, columnspan=2, sticky="w", pady=(0, 12))
        self.endpoint.trace_add("write", lambda *_: self.update_address_guidance())
        self.update_address_guidance()
        self.trade_policy = tk.StringVar(value="")
        self.trade_policy_controls = []
        ttk.Label(create, text="Trade friendship rule (choose for a new effects-enabled world)").grid(
            row=8, column=0, columnspan=2, sticky="w", pady=(0, 4))
        policy = ttk.Combobox(create, state="readonly", textvariable=self.trade_policy,
                              values=tuple(TRADE_POLICIES), width=56)
        policy.grid(row=9, column=0, columnspan=2, sticky="w")
        self.controls.append(policy)
        self.trade_policy_controls.append(policy)
        ttk.Label(create, text="Emerald has no trainer geographic history. A shared world region keeps the same handler's friendship; treating geography as missing refreshes it. Missing older handler values start at each species' Gen 6 base.",
                  wraplength=650).grid(row=10, column=0, columnspan=2, sticky="w", pady=8)
        button = ttk.Button(create, text="Create private world", command=self.create)
        button.grid(row=11, column=0, columnspan=2, sticky="w")
        self.controls.append(button)
        self.role = tk.StringVar(value="host")
        roles = ttk.Frame(enroll)
        roles.pack(fill="x", pady=(0, 10))
        for label, value in (("I am the host", "host"), ("I am joining a friend", "friend")):
            control = ttk.Radiobutton(roles, text=label, variable=self.role, value=value,
                                       command=self.update_role)
            control.pack(side="left", padx=(0, 18))
            self.controls.append(control)
        ttk.Label(enroll, text="Create a new character with ordinary New Game, or choose an\nexisting character saved normally after starter selection.",
                  wraplength=650).pack(anchor="w", pady=(0, 10))
        draft = ttk.Button(enroll, text="Create a new character…", command=lambda: self.start("draft"))
        draft.pack(anchor="w", pady=(0, 8))
        self.controls.append(draft)
        self.world_label = tk.StringVar(value="No world selected")
        self.source_label = tk.StringVar(value="No source save selected")
        button = ttk.Button(enroll, text="Choose original character save…", command=self.choose_source)
        button.pack(anchor="w", pady=(4, 0))
        self.controls.append(button)
        ttk.Label(enroll, textvariable=self.source_label, wraplength=650).pack(anchor="w", pady=(4, 8))
        self.friend_frame = ttk.Frame(enroll)
        ttk.Label(self.friend_frame, text="Close the game before exporting. Give only the exported .sav to your host; never ask for host.json or the world folder. Export does not enroll the character. After host approval, join with your personal invitation and stop playing this unassigned source.",
                  wraplength=650).pack(anchor="w", pady=(4, 12))
        button = ttk.Button(self.friend_frame, text="Export character for host approval…", command=self.export_character)
        button.pack(anchor="w")
        self.controls.append(button)
        self.host_frame = ttk.Frame(enroll)
        enroll = self.host_frame
        button = ttk.Button(enroll, text="Choose host world…", command=self.choose_world)
        button.pack(anchor="w", pady=(4, 0))
        self.controls.append(button)
        ttk.Label(enroll, textvariable=self.world_label, wraplength=650).pack(anchor="w", pady=(4, 8))
        self.slot = tk.StringVar(value="")
        slot = ttk.Combobox(enroll, state="readonly", textvariable=self.slot,
                           values=())
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
        self.export_label = tk.StringVar(value="Export a separate invitation for each friend. Never share host.json or the world folder.")
        ttk.Label(enroll, textvariable=self.export_label, wraplength=650).pack(anchor="w", pady=(12, 4))
        self.copy_connection_button = ttk.Button(enroll, text="Copy exported connection details", state="disabled",
                                                 command=self.copy_connection_details)
        self.copy_connection_button.pack(anchor="w")
        upgrade_page = ttk.Frame(tabs)
        tabs.add(upgrade_page, text="Upgrade world features")
        upgrades = scrollable_frame(upgrade_page, padding=16)
        ttk.Label(upgrades, text="Choose the host world on the character tab and close every game and host session first. This upgrades features for the same game release and preserves verified backups. It does not convert a world to another release.",
                  wraplength=650).pack(anchor="w", pady=(0, 12))
        ttk.Label(upgrades, text="Trade friendship rule").pack(anchor="w")
        policy = ttk.Combobox(upgrades, state="readonly", textvariable=self.trade_policy,
                              values=tuple(TRADE_POLICIES), width=56)
        policy.pack(anchor="w", pady=6)
        self.controls.append(policy)
        self.trade_policy_controls.append(policy)
        ttk.Label(upgrades, text="The upgrade retains known friendship values and initializes missing older handler values to each species' Gen 6 base. The chosen geographic rule becomes permanent for this world. Local Soft Reset tracking is added when supported by this game.",
                  wraplength=650).pack(anchor="w", pady=(6, 12))
        self.upgrade_approval = tk.BooleanVar(value=False)
        self.trade_policy.trace_add("write", lambda *_: self.upgrade_approval.set(False))
        approved = ttk.Checkbutton(upgrades, text="I approve this rule and the backed-up upgrade for the selected closed world.", variable=self.upgrade_approval)
        approved.pack(anchor="w", pady=6)
        self.controls.append(approved)
        button = ttk.Button(upgrades, text="Upgrade world features", command=self.upgrade)
        button.pack(anchor="w", pady=6)
        self.controls.append(button)
        self.status = tk.StringVar(value=message("idle"))
        ttk.Separator(footer).pack(fill="x", pady=12)
        ttk.Label(footer, textvariable=self.status, wraplength=700).pack(fill="x")
        ttk.Button(footer, text="Back to My Worlds" if self.embedded else "Close setup", command=self.close).pack(anchor="e", pady=(10, 0))
        self.update_role()
        if not self.embedded:
            self.root.report_callback_exception = lambda *_: self.status.set(message("setup_failed"))
        self.poll_id = self.root.after(80, self.poll)
        if start_role in ("host", "friend"):
            self.begin_role(start_role)
        if selected_world is not None:
            tabs.select(character_page)
            self.start("inspect", world_directory=selected_world)

    def begin_role(self, role):
        self.role.set(role)
        self.update_role()
        self.tabs.select(self.create_page if role == "host" else self.character_page)

    def update_role(self):
        self.approval.set(False)
        self.host_frame.pack_forget()
        self.friend_frame.pack_forget()
        (self.friend_frame if self.role.get() == "friend" else self.host_frame).pack(fill="x", anchor="w")

    def set_enabled(self, enabled):
        for control in self.controls:
            control.configure(state="normal" if enabled else "disabled")
        if enabled:
            self.slot_control.configure(state="readonly")
            for control in self.trade_policy_controls:
                control.configure(state="readonly")

    def update_address_guidance(self):
        try:
            scope = route_scope(self.endpoint.get().strip())
        except ValueError:
            text = "Enter a numeric IPv4 or IPv6 address. Invitations retain this address; do not use a web URL."
        else:
            text = ("127.0.0.1 and ::1 work only on this PC. Use a LAN or public address for friends on another PC."
                    if scope == "loopback" else "Friends must be on your local network for this address."
                    if scope == "lan" else "Use your public address only with the host's explicitly configured Internet port and router forwarding.")
        self.address_guidance.set(text)

    def copy_connection_details(self):
        if self.exported_details is None:
            return
        import tkinter as tk
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.exported_details.copy_text())
        except tk.TclError:
            self.export_label.set("Clipboard unavailable. The exported invitation remains at the destination you selected.")
        else:
            self.export_label.set("Connection details copied without credentials. Send the saved private invitation file separately to its intended friend.")

    def start(self, operation, **options):
        if self.worker.start(operation, **options):
            if operation == "draft":
                self.source_path = self.character_source = None
                self.source_label.set("Preparing a new character…")
                self.approval.set(False)
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
        self.start("create", player_names=names, endpoint=self.endpoint.get().strip(), port=port,
                   trade_effect_policy=TRADE_POLICIES.get(self.trade_policy.get()))

    def upgrade(self):
        policy = TRADE_POLICIES.get(self.trade_policy.get())
        if not self.world_directory or policy is None:
            self.status.set(message("trade_effect_policy_required"))
        elif not self.upgrade_approval.get():
            self.status.set("Review and approve the upgrade for the selected closed world first.")
        else:
            self.upgrade_approval.set(False)
            self.start("upgrade", world_directory=self.world_directory, trade_effect_policy=policy)

    def choose_world(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(parent=self.root, title="Choose private host.json", filetypes=[("Host world", "host.json")])
        if path:
            self.exported_details = None
            self.copy_connection_button.configure(state="disabled")
            self.export_label.set("Export a separate invitation for each friend. Never share host.json or the world folder.")
            self.world_directory = None
            self.world_label.set("Checking selected world…")
            self.account_slots = {}
            self.slot_control.configure(values=())
            self.slot.set("")
            self.approval.set(False)
            self.upgrade_approval.set(False)
            self.start("inspect", world_directory=Path(path).parent)

    def choose_source(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(parent=self.root, title="Choose original saved character", filetypes=[("Character save", "*.sav")])
        if path:
            self.source_path = self.character_source = None
            self.source_label.set("Checking the closed, unassigned source…")
            self.approval.set(False)
            self.start("source", source_path=Path(path))

    def export_character(self):
        if self.worker.busy:
            return
        if self.source_path is None:
            self.status.set(message("source_required"))
            return
        # This check precedes Save As. Export rechecks the same receipt after
        # that dialog, so a later change cannot switch the approved source.
        self.start("prepare_character_export", source_path=self.source_path,
                   expected=self.character_source)

    def choose_character_destination(self, selection):
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(parent=self.root, title="Save a character copy for your host",
            defaultextension=".sav", filetypes=[("Unassigned character save", "*.sav")],
            initialfile="character-for-host.sav", confirmoverwrite=False)
        if path:
            self.start("export_character", selection=selection, destination=Path(path))
        else:
            self.set_enabled(True)
            self.status.set("Character export canceled. The selected source is unchanged.")

    def selected_slot(self):
        return self.account_slots.get(self.slot.get())

    def enroll(self):
        if not self.world_directory or not self.source_path or self.selected_slot() is None:
            self.status.set(message("selection"))
        elif not self.approval.get():
            self.status.set(message("approval"))
        else:
            self.start("enroll", world_directory=self.world_directory, slot=self.selected_slot(),
                       source_path=self.source_path, bind_address="127.0.0.1", host_route="127.0.0.1",
                       expected_source_sha256=self.character_source.sha256 if self.character_source is not None else None)

    def export(self):
        from tkinter import filedialog
        if self.world_directory is None or self.selected_slot() in (None, 0):
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
        if self.embedded:
            self.body.destroy()
        else:
            self.root.grab_release()
            self.root.destroy()
        if self.on_close:
            self.on_close(self.world_directory)

    def poll(self):
        while not self.worker.events.empty():
            event = self.worker.events.get_nowait()
            if event.world_directory is not None:
                if event.world_directory != self.world_directory:
                    self.exported_details = None
                    self.copy_connection_button.configure(state="disabled")
                    self.export_label.set("Export a separate invitation for each friend. Never share host.json or the world folder.")
                self.world_directory = event.world_directory
                self.world_label.set("World selected")
            if event.accounts is not None:
                self.account_slots = {
                    f"{'Host' if account.slot == 0 else 'Friend ' + str(account.slot)} — {account.display_name}": account.slot
                    for account in event.accounts
                }
                labels = tuple(self.account_slots)
                self.slot_control.configure(values=labels)
                self.slot.set(labels[0] if labels else "")
                self.approval.set(False)
            if event.source_path is not None:
                self.source_path = event.source_path
                self.character_source = event.character_source
                self.source_label.set("Saved character selected; original preserved")
                self.approval.set(False)
            if event.invitation_path is not None:
                self.exported_details = event.connection_details
                self.copy_connection_button.configure(state="normal" if self.exported_details is not None else "disabled")
                self.export_label.set("Invitation saved to the destination you chose. Send that file only to "
                    + self.slot.get() + ". Never share host.json or the world folder.")
            if event.kind == "complete":
                if self.closing:
                    self.destroy()
                    return
                self.set_enabled(True)
                self.finish_button.configure(state="disabled")
                self.status.set(message(event.code))
                if event.code in ("created", "world_selected"):
                    self.role.set("host")
                    self.update_role()
                    self.tabs.select(self.character_page)
                if event.code == "character_ready":
                    self.pending_character_export = event.character_source
                    self.set_enabled(False)
                if self.world_directory is None:
                    self.world_label.set("No verified world selected")
            elif event.kind == "ready" and not self.closing:
                self.finish_button.configure(state="normal")
                self.status.set(message(event.code))
            elif event.kind == "status" and not self.closing:
                self.status.set(message(event.code))
        # The complete event can be observed just before the old thread exits.
        # Never lose an export action by starting its successor too early.
        if self.pending_character_export is not None and not self.worker.busy and not self.closing:
            selected, self.pending_character_export = self.pending_character_export, None
            self.choose_character_destination(selected)
        self.poll_id = self.root.after(80, self.poll)
