"""The EmeraldTogether main menu, inside the game's own window (Update 30).

``EmeraldTogether.exe`` opens ``pokeemerald-mp --shell`` - the game's executable showing only its menu - and this module decides what
every screen says and does: Continue Adventure, New Game, Host Server, Join Server, Settings, Exit. There is no separate setup program,
launcher window or second setup step: choosing a saved world or a saved server starts it, and the character that belongs to that
world account loads by itself.

Identity. A world is identified by its stable world ID and an account in it by its stable player ID (both fixed when the host creates
the world). A character lives in ``players/<world_id>/<player_id>/``; a saved server is a shortcut to an account (address, port and
those two IDs). Names, addresses and ports can change or be edited without ever making a different character: removing a shortcut only
removes the shortcut.

The checks the earlier launcher made all still run - the installed game's pins, the host world's certificate and database, the
authenticated connection, closed-game recovery - because the same ``SessionWorker`` and ``LauncherSession`` start the game; this module
only replaces the windows around them.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
import hashlib
from pathlib import Path
import time

from .character_creation import CreationError, create_character, message_for
from .character_links import CharacterLinks, character_state, profile_directory
from .graphics_mode import MODE_2D, MODE_3D, MODE_LABELS, GraphicsPreference, choose_launch, explain_failure, probe_graphics
from .invitations import Invitation, InvitationError
from .invite_code import (InviteCodeError, decode_invite, encode_invite, fetch_certificate, redeem, resolve_address, valid_address,
                          valid_port)
from .launcher_session import SessionState
from .launcher_worlds import lan_addresses
from .saved_servers import InvitationConflict, SavedServers, invitation_path, store_invitation
from .server_check import probe_route
from .shell_migration import migrate
from .shell_protocol import Done, Screen, ShellClosed
from .shell_store import JsonStore, text_ok
from .shell_tasks import BackgroundJob
from .world_registry import LOOPBACK, WorldRegistry, WorldRegistryError, free_port, valid_world_name

TRADE_RULES = {
    "gen6-stable-world-region-v1": ("Shared world region", "A trade keeps the same trainer's friendship (the world is one region)."),
    "gen6-absent-geography-refresh-v1": ("Missing geography", "A trade refreshes the friendship (Emerald has no regions to compare)."),
}
SESSION_WINDOW = (560, 420)
MENU_WINDOW = (1280, 720)
PREFS_FORMAT = "emerald-shell-preferences-v1"


def _prefs_validate(record):
    if set(record) != {"format", "trade_rule"} or not (record["trade_rule"] is None or record["trade_rule"] in TRADE_RULES):
        raise ValueError("invalid preferences")
    return record


def _ago(then, now):
    if then is None:
        return "never played"
    seconds = max(0, int(now - then))
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if seconds >= size:
            count = seconds // size
            return f"{count} {unit}{'s' if count != 1 else ''} ago"
    return "just now"


class ShellApp:
    """One menu session. ``ui`` shows screens (``ShellProcess`` or ``ScriptedShell``); everything else is injectable for tests."""

    def __init__(self, installation, private_root, ui, *, version="Development preview", worker=None, creator=create_character,
                 resolver=resolve_address, fetcher=fetch_certificate, prober=probe_route, lan=lan_addresses, graphics=None,
                 graphics_gate=None, importer=None, clock=time.time, session_window=SESSION_WINDOW, menu_window=MENU_WINDOW):
        self.installation = installation
        self.private_root = Path(private_root)
        self.ui = ui
        self.version = version
        self.worker = worker
        self.creator, self.resolver, self.fetcher, self.prober, self.lan = creator, resolver, fetcher, prober, lan
        self.graphics = graphics if graphics is not None else GraphicsPreference(self.private_root)
        self.graphics_gate = graphics_gate or self._graphics_gate
        self.importer = importer
        self.clock = clock
        self.session_window, self.menu_window = session_window, menu_window
        shell = self.private_root / "shell"
        self.registry = WorldRegistry(self.private_root, shell, clock=clock)
        self.links = CharacterLinks(shell, clock=clock)
        self.servers = SavedServers(shell, clock=clock)
        self.prefs = JsonStore(shell / "preferences.json", PREFS_FORMAT, lambda: {"format": PREFS_FORMAT, "trade_rule": None},
                               _prefs_validate, clock=clock)
        self.notice = None
        self.hosting = {}                  # world id -> (bind address, port) while that world is being hosted
        self.migration = None
        self.game_ok = None
        self.last_error = None             # the last background failure, for diagnostics (never shown to the player)

    # ------------------------------------------------------------------ small helpers

    def window(self, size):
        mover = getattr(self.ui, "window", None)
        if mover is not None:
            mover(size[0], size[1], -1 if size == self.menu_window else 40, -1 if size == self.menu_window else 40)

    def message(self, title, text, kind="info", back="Back", sub=""):
        screen = Screen("message", title, sub)
        for line in text.split("\n"):
            screen.note(line)
        screen.button("back", back, "as")
        self.ui.show(screen)

    def confirm(self, title, text, yes, no="Cancel", *, warn=False):
        screen = Screen("confirm", title)
        for line in text.split("\n"):
            screen.note(line)
        screen.row("yes", yes, "", "w" if warn else "a")
        screen.row("no", no, "", "s")
        return self.ui.show(screen).id == "yes"

    def choose(self, title, options, *, sub="", notes=(), back="Back", status=None):
        """Pick one of ``options`` = [(id, label, detail)]; returns the id, or None for back."""
        screen = Screen("choose", title, sub)
        for note in notes:
            screen.note(note)
        for option in options:
            screen.row(option[0], option[1], option[2] if len(option) > 2 else "", option[3] if len(option) > 3 else "")
        screen.button("back", back)
        if status:
            screen.set_status(*status)
        event = self.ui.show(screen)
        return None if event.kind == "back" or event.id == "back" else event.id

    def busy(self, title, job, text, *, cancel_label="Cancel", texts=None):
        """Show progress until the job is done. Returns the job (done) or None if the player cancelled (the job is cancelled)."""
        def screen_for():
            body = (texts or {}).get(job.status, text) if job.status else text
            screen = Screen("busy", title)
            for line in body.split("\n"):
                screen.note(line)
            screen.set_status("busy", "Working")
            screen.button("cancel", cancel_label)
            return screen

        shown = [None]

        def tick():
            if job.done:
                return Done(job)
            current = job.status
            if current != shown[0]:
                shown[0] = current
                return screen_for()
            return None

        shown[0] = job.status
        try:
            event = self.ui.show(screen_for(), tick=tick)
        except ShellClosed:
            job.cancel()          # the window was closed: stop what was started (private files and recovery data are kept)
            job.wait(10)
            raise
        if event.kind == "tick":
            return job
        job.cancel()
        job.wait(10)
        return None

    def run_job(self, factory, title, text, **options):
        job = BackgroundJob(factory)
        finished = self.busy(title, job, text, **options)
        return finished

    # ------------------------------------------------------------------ start up

    def _game_installed(self):
        if self.installation is None:
            return False
        try:
            self.installation.verify()
            return True
        except Exception:                                              # noqa: BLE001 - any verification failure is "not installed"
            return False

    def run(self):
        """The whole menu session; returns when the player chooses Exit or closes the window."""
        try:
            self.window(self.menu_window)
            self.migration = migrate(self.private_root, self.registry, self.links, self.servers, clock=self.clock)
            for store, label in ((self.registry._store, "worlds"), (self.servers._store, "saved servers"),
                                 (self.links._store, "characters")):
                if not store.available:
                    self.message("A record needs attention",
                                 f"The list of {label} on this PC could not be read, and no backup was usable.\n"
                                 "Nothing was changed or deleted. Close EmeraldTogether and restore the file from your backup,\n"
                                 "or ask for help before continuing.", "error", back="Continue anyway")
            self.game_ok = self._game_installed()
            if self.migration.problems:
                count = len(self.migration.problems)
                self.notice = ("warn", f"{count} item{'s' if count != 1 else ''} from the earlier launcher could not be matched "
                                       "safely and were left untouched. See Settings, Characters.")
            while True:
                if self.main_menu() == "exit":
                    return 0
        except ShellClosed:
            return 0

    # ------------------------------------------------------------------ main menu

    def _continue_target(self):
        """(label, detail, action) for the most recently played adventure, or None."""
        best = None
        for link in self.links.all():
            if link["last_played"] is None or link["stage"] != "enrolled" and character_state(
                    self.private_root, link["world_id"], link["player_id"]) == "none":
                continue
            if link["role"] == "host":
                entry = self.registry.get(link["world_id"])
                if entry is None:
                    continue
                candidate = (link["last_played"], "host", entry, link)
            else:
                server = self.servers.for_account(link["world_id"], link["player_id"])
                if server is None:
                    continue
                candidate = (link["last_played"], "join", server, link)
            if best is None or candidate[0] > best[0]:
                best = candidate
        return best

    def main_menu(self):
        while True:
            target = self._continue_target()
            screen = Screen("main", "Main menu", f"EmeraldTogether {self.version}")
            if target is None:
                screen.row("continue", "Continue Adventure", "no adventure yet", "d")
            else:
                when = _ago(target[0], self.clock())
                if target[1] == "host":
                    detail = f"{target[2].name} - {target[3]['display_name']} - {when}"
                else:
                    detail = f"{target[2]['name']} - {target[3]['display_name']} - {when}"
                screen.row("continue", "Continue Adventure", detail, "s")
            worlds = len(self.registry.entries(default_bind=self._default_bind()))
            screen.row("new", "New Game", "start a new adventure")
            screen.row("host", "Host Server", f"{worlds} world{'s' if worlds != 1 else ''}")
            screen.row("join", "Join Server", f"{len(self.servers.all())} saved")
            screen.row("settings", "Settings")
            screen.row("exit", "Exit")
            if not self.game_ok:
                screen.set_status("warn", "Your game files are not installed yet. Open Settings, Game files.")
            elif self.notice:
                screen.set_status(*self.notice)
            self.notice = None
            event = self.ui.show(screen)
            choice = event.id if event.kind == "select" else "exit" if event.kind == "back" else ""
            if choice == "exit":
                return "exit"
            elif choice == "continue" and target is not None:
                self._continue(target)
            elif choice == "new":
                self.new_game()
            elif choice == "host":
                self.host_menu()
            elif choice == "join":
                self.join_menu()
            elif choice == "settings":
                self.settings_menu()

    def _default_bind(self):
        addresses = self.lan()
        return addresses[0] if addresses else LOOPBACK

    # ------------------------------------------------------------------ Continue / New Game

    def _continue(self, target):
        _, kind, subject, link = target
        if kind == "host":
            self._host_world(subject)
        else:
            self._join_server(subject)

    def new_game(self):
        if not self._need_game():
            return
        existing = [entry for entry in self.registry.entries(default_bind=self._default_bind()) if entry.kind == "adventure"]
        has_character = any(link["stage"] == "enrolled" for link in self.links.all())
        if has_character or existing:
            if not self.confirm("Start a new adventure?",
                                "Your current adventures stay exactly as they are: nothing is overwritten or deleted.\n"
                                "Continue Adventure keeps resuming the one you played last, and you can open any of\n"
                                "them again from Host Server.", "Start a new adventure"):
                return
        rule = self._trade_rule()
        if rule is False:
            return
        names = {entry.name.casefold() for entry in self.registry.entries(default_bind=self._default_bind())}
        number = 1
        while f"adventure {number}" in names:
            number += 1
        entry = self._create_world(f"Adventure {number}", "Player", rule, bind=LOOPBACK, kind="adventure")
        if entry is not None:
            self._host_world(entry)

    def _need_game(self):
        if self._game_installed():
            self.game_ok = True
            return True
        self.game_ok = False
        self.message("Game files needed",
                     "Your game files are not installed on this PC yet, or they changed.\n"
                     "Open Settings, then Game files, to install or check them.")
        return False

    # ------------------------------------------------------------------ the friendship rule (a world-creation choice)

    def _needs_rule(self):
        """Whether this game build asks for a friendship rule when a world is created (the replay-capable builds do)."""
        from .companion import verify_rom_manifest
        try:
            _, manifest = verify_rom_manifest(self.installation.rom_path, self.installation.manifest_path)
        except Exception:                                              # noqa: BLE001
            return True
        return manifest.get("trade_replay_abi_version") == 1

    def _trade_rule(self):
        """The rule for a new world: None when this build has none to choose, False if the player backed out."""
        if not self._needs_rule():
            return None
        saved = self.prefs.record["trade_rule"]
        if saved is not None:
            return saved
        notes = ["Choose how a trade treats the friendship of the traded Pokemon in the worlds you create.",
                 "Emerald has no trainer regions, so there are two documented ways to treat it. This is asked once and",
                 "applies to every world you create from now on; a world keeps the rule it was created with."]
        options = [(key, label, "") for key, (label, _) in TRADE_RULES.items()]
        screen = Screen("trade_rule", "Trade friendship rule")
        for note in notes:
            screen.note(note)
        for key, (label, explanation) in TRADE_RULES.items():
            screen.row(key, label, explanation, "2")
        screen.button("back", "Back")
        event = self.ui.show(screen)
        if event.kind == "back" or event.id not in TRADE_RULES:
            return False
        self.prefs.save({"format": PREFS_FORMAT, "trade_rule": event.id})
        return event.id

    # ------------------------------------------------------------------ creating a world

    def _create_world(self, name, host_name, rule, *, bind, internet=False, address="", port=None, kind="server"):
        """Create the world (and register it). Returns the WorldEntry, or None after telling the player why not."""
        from .launcher_setup import LauncherSetupError, create_world
        registry = self.registry
        taken = registry.used_ports()
        port = port or free_port(taken)
        endpoint = bind
        try:
            import ipaddress
            ipaddress.ip_address(address)
            endpoint = address            # a numeric public address is what invitations point at
        except ValueError:
            pass
        names = (host_name, "Player 2", "Player 3", "Player 4") if host_name != "Player" else ("Player", "Player 2", "Player 3", "Player 4")

        async def make(job):
            job.progress("creating")
            return await asyncio.get_running_loop().run_in_executor(
                None, lambda: create_world(self.installation, self.private_root, player_names=names, endpoint=endpoint, port=port,
                                           trade_effect_policy=rule))

        job = self.run_job(make, "Creating your world", "Creating your world and its private keys. This takes a few seconds.")
        if job is None:
            return None
        if job.error is not None:
            code = getattr(job.error, "code", "")
            self.message("The world could not be created", f"{job.error}\nNothing was changed." if code else
                         "The world could not be created. Nothing was changed.")
            return None
        world = job.result
        registry.register(world, name, kind=kind, bind_address=bind, internet=internet, address=address)
        for slot, account in enumerate(world.accounts):
            if slot == 0:
                self.links.ensure(world.world_id, account.player_id, "host", 0, name, account.display_name)
        return registry.get(world.world_id)

    def create_world_menu(self):
        if not self._need_game():
            return
        needs_rule = self._needs_rule()
        rule = self.prefs.record["trade_rule"] if needs_rule else None
        form = dict(name="", host="", port=str(free_port(self.registry.used_ports())))
        bind = self._default_bind()
        internet, address = False, ""
        status = None
        while True:
            screen = Screen("create_world", "Create New Server World",
                            "A new world with its own saved characters, Pokemon, PC and progress.")
            screen.field("name", "World name", form["name"], "l32s")
            screen.field("host", "Your name", form["host"], "l24")
            screen.field("port", "Port (friends connect to this)", form["port"], "n")
            screen.row("network", "Network", "this PC only" if bind == LOOPBACK else f"local network {bind}", "")
            screen.row("internet", "Internet access", "on" if internet else "off", "")
            screen.row("address", "Public address or host name", address or "not set", "")
            if needs_rule:
                screen.row("rule", "Trade friendship rule", TRADE_RULES[rule][0] if rule else "choose one", "")
            screen.button("create", "Create world", "a")
            screen.button("back", "Back")
            if status:
                screen.set_status(*status)
            event = self.ui.show(screen)
            form.update(name=event.fields.get("name", form["name"]).strip(), host=event.fields.get("host", form["host"]).strip(),
                        port=event.fields.get("port", form["port"]).strip())
            status = None
            if event.kind == "back" or event.id == "back":
                return
            if event.id == "network":
                options = [(LOOPBACK, "This PC only", "only you; friends cannot join")]
                options += [(a, f"Local network {a}", "friends on your network") for a in self.lan()]
                picked = self.choose("Network", options, notes=["Which of this PC's addresses the world listens on."])
                bind = picked or bind
            elif event.id == "internet":
                if internet:
                    internet = False
                elif self.confirm("Allow Internet connections?",
                                  "Internet connections let anyone with an invite code and your public address reach this PC.\n"
                                  "Your router must forward the game's port to it and your firewall must allow it.\n"
                                  "EmeraldTogether does not set that up and there is no relay server.",
                                  "Allow Internet connections", warn=True):
                    internet = True
            elif event.id == "address":
                text = self._ask_text("Public address or host name",
                                      "The address friends outside your network use to reach you (an Internet address or a host name).\n"
                                      "It is only written into invite codes; EmeraldTogether does not look it up or check it.",
                                      address, "Address", allow_empty=True)
                if text is not None:
                    if text and not valid_address(text):
                        status = ("error", "That is not a usable address or host name.")
                    else:
                        address = text
            elif event.id == "rule":
                rule = self._trade_rule_change(rule)
            elif event.id == "create":
                problem = self._world_form_problem(form)
                if problem:
                    status = ("error", problem)
                elif needs_rule and rule is None:
                    status = ("error", "Choose a trade friendship rule first.")
                else:
                    entry = self._create_world(form["name"], form["host"], rule, bind=bind, internet=internet, address=address,
                                               port=int(form["port"]))
                    if entry is not None:
                        if needs_rule:
                            self.prefs.save({"format": PREFS_FORMAT, "trade_rule": rule})
                        self.notice = ("ok", f"World '{entry.name}' created.")
                        self.world_menu(entry)
                        return

    def _trade_rule_change(self, current):
        screen = Screen("trade_rule", "Trade friendship rule")
        for key, (label, explanation) in TRADE_RULES.items():
            screen.row(key, label, explanation, "2" + ("s" if key == current else ""))
        screen.button("back", "Back")
        event = self.ui.show(screen)
        return event.id if event.kind == "select" and event.id in TRADE_RULES else current

    def _world_form_problem(self, form):
        if not valid_world_name(form["name"]):
            return "Give the world a name (up to 32 characters)."
        if self.registry.name_taken(form["name"]):
            return "You already have a world with that name. Choose another."
        if not (1 <= len(form["host"]) <= 24 and form["host"].isprintable()):
            return "Enter your name (up to 24 characters). Friends see it in the Players menu."
        if not form["port"].isdigit() or not valid_port(int(form["port"])):
            return "The port must be a number from 1 to 65535."
        if int(form["port"]) in self.registry.used_ports():
            return "Another of your worlds already uses that port."
        return None

    def _ask_text(self, title, text, value, label, *, allow_empty=False, flags="l253"):
        screen = Screen("ask_text", title)
        for line in text.split("\n"):
            screen.note(line)
        screen.field("value", label, value, flags + "s")
        screen.button("ok", "Save", "a")
        screen.button("back", "Cancel")
        event = self.ui.show(screen)
        if event.kind == "back" or event.id == "back":
            return None
        answer = event.fields.get("value", "").strip()
        return answer if answer or allow_empty else None

    # ------------------------------------------------------------------ Host Server

    def host_menu(self):
        while True:
            entries = self.registry.entries(default_bind=self._default_bind())
            screen = Screen("host_list", "Host Server", "Choose a saved world, or create a new one.")
            screen.row("create", "Create New Server World", "a new world with its own characters", "a")
            for entry in entries:
                host_id = entry.accounts[0][1]
                state = character_state(self.private_root, entry.world_id, host_id)
                detail = (f"{entry.host_name} - {len(entry.accounts)} players - port {entry.port} - "
                          f"{'hosted ' + _ago(entry.last_hosted, self.clock()) if entry.last_hosted else 'never hosted'}")
                screen.row(entry.world_id, entry.name, detail, "2")
            for folder, reason in self.registry.damaged.items():
                screen.row("damaged:" + folder, f"Unusable world folder ({reason})", "left untouched", "2d")
            screen.button("back", "Back")
            if self.notice:
                screen.set_status(*self.notice)
                self.notice = None
            event = self.ui.show(screen)
            if event.kind == "back" or event.id == "back":
                return
            if event.id == "create":
                self.create_world_menu()
            else:
                entry = next((item for item in entries if item.world_id == event.id), None)
                if entry is not None:
                    self.world_menu(entry)

    def world_menu(self, entry):
        while True:
            entry = self.registry.get(entry.world_id) or entry
            host_id = entry.accounts[0][1]
            state = character_state(self.private_root, entry.world_id, host_id)
            who = {"ready": "your saved character loads automatically", "none": "you create your character first",
                   "interrupted": "your first-time setup was interrupted"}[state]
            screen = Screen("world", entry.name, f"{entry.host_name} - port {entry.port} - {who}")
            screen.row("host", "Host This World", "", "as")
            screen.row("info", "Server Information")
            screen.row("codes", "Invite codes for friends")
            screen.row("network", "Network settings")
            screen.row("rename", "Rename world")
            screen.button("back", "Back")
            event = self.ui.show(screen)
            if event.kind == "back" or event.id == "back":
                return
            if event.id == "host":
                self._host_world(entry)
                return
            elif event.id == "info":
                self.server_information(entry)
            elif event.id == "codes":
                self.invite_codes(entry)
            elif event.id == "network":
                self.network_settings(entry)
            elif event.id == "rename":
                name = self._ask_text("Rename world", "A world's name is only a label. Its characters, saves and invite codes do not change.",
                                      entry.name, "World name", flags="l32")
                if name:
                    if not valid_world_name(name):
                        self.notice = ("error", "That is not a usable name.")
                    elif self.registry.name_taken(name, except_world=entry.world_id):
                        self.notice = ("error", "You already have a world with that name.")
                    else:
                        self.registry.configure(entry.world_id, name=name)
                        self.links.rename_world(entry.world_id, name)

    def _bind_for(self, entry):
        """The address to listen on now. A local-network address that is no longer this PC's is replaced (and the host told)."""
        bind = entry.bind_address
        addresses = self.lan()
        if bind == LOOPBACK or bind in addresses:
            return bind, None
        if addresses:
            self.registry.configure(entry.world_id, bind_address=addresses[0])
            return addresses[0], f"This PC's network address changed from {bind} to {addresses[0]}. Friends' saved servers need the new one."
        self.registry.configure(entry.world_id, bind_address=LOOPBACK)
        return LOOPBACK, "No network connection was found, so the world is hosted on this PC only."

    def _host_world(self, entry):
        """Host Server -> this world: its host character loads by itself; a first-time host creates one."""
        if not self._need_game():
            return
        host_id = entry.accounts[0][1]
        self.links.ensure(entry.world_id, host_id, "host", 0, entry.name, entry.accounts[0][2])
        bind, note = self._bind_for(entry)
        from .launcher_gui import LaunchRequest
        request = LaunchRequest("host", entry.folder / "host.json", bind, entry.internet, allow_enrollment=entry.enrollment)
        for attempt in range(2):
            outcome = self._play(request, entry.name, entry.accounts[0][2], world_id=entry.world_id, player_id=host_id,
                                 hosting=(entry.world_id, bind, entry.port), note=note)
            if outcome != "enrollment_required":
                return
            if not self._create_character("host", entry, host_id):
                return
        return

    # ------------------------------------------------------------------ the session (the game runs in its own window)

    def _graphics_gate(self):
        """Which game to start: '3d', '2d' or None (the player backed out). Runs the same 3D check the launcher ran."""
        bundle = self.installation.bundle
        preference = self.graphics.mode
        try:
            executable, _ = bundle.verify(MODE_3D)
        except Exception:                                              # noqa: BLE001
            executable = None
        if preference == MODE_2D or executable is None:
            return MODE_2D if getattr(bundle, "has_classic", lambda: False)() else MODE_3D
        job = BackgroundJob(lambda j: asyncio.get_running_loop().run_in_executor(None, lambda: probe_graphics(executable)))
        finished = self.busy("Checking graphics", job, "Checking that 3D graphics can start on this PC.")
        if finished is None:
            return None
        choice = choose_launch(preference, lambda: job.result)
        if not choice.ask:
            return choice.mode
        has_classic = bool(getattr(bundle, "has_classic", lambda: False)())
        screen = Screen("graphics", "3D graphics cannot start")
        for part in explain_failure(job.result).split("\n\n"):
            screen.note(part)
        if has_classic:
            screen.row("classic", "Play in Classic 2D this time", "your saved mode is unchanged", "as")
        screen.row("back", "Back")
        event = self.ui.show(screen)
        return MODE_2D if event.id == "classic" and has_classic else None

    def _play(self, request, title, character, *, world_id, player_id, hosting=None, note=None):
        """Start a host or join session and show the session window until it ends. Returns the session's result code."""
        from .launcher_gui import status_text
        graphics = self.graphics_gate()
        if graphics is None:
            return "cancelled"
        request = replace(request, graphics=graphics)
        worker = self.worker
        try:
            started = worker.start(request)
        except ValueError as error:
            self.notice = ("error", status_text(error.args[0] if error.args else "session_failed"))
            return "session_failed"
        if not started:
            self.notice = ("warn", "A game is already running.")
            return "busy"
        link = self.links.get(world_id, player_id)
        if hosting:
            self.hosting[hosting[0]] = hosting[1:]
        self.window(self.session_window)
        state = dict(code="installation", state="validating", autosave=None, is_host=request.mode == "host", save=False,
                     battle=False, cleanup=False, restart=False, trade=False, connected=False, complete=None, note=note, flash=None)

        def absorb():
            changed = False
            while True:
                try:
                    event = worker.events.get_nowait()
                except Exception:                                      # noqa: BLE001 - queue.Empty
                    return changed
                if event.kind == "complete":
                    state["complete"] = event.code
                    changed = True
                elif event.kind == "status":
                    state.update(code=event.code, state=event.state, autosave=event.autosave_enabled, save=bool(event.save_available),
                                 battle=event.battle_recovery_available, cleanup=event.admission_cleanup_available,
                                 restart=event.host_restart_available, trade=event.trade_recovery_available,
                                 connected=event.connected, is_host=event.is_host)
                    changed = True

        def session_screen():
            screen = Screen("session", title, f"Playing as {character}")
            running = state["state"] == SessionState.RUNNING.value
            screen.note("Your game is open in its own window. Close that window when you finish." if running else
                        "Starting your game. It opens in its own window when it is ready.")
            if running:
                if state["save"]:
                    screen.row("save", "Save now", "saves your progress to the world", "a")
                if state["autosave"] is not None:
                    screen.row("autosave", "Autosave every 5 minutes", "on - turn off" if state["autosave"] else "off - turn on")
                if state["battle"]:
                    screen.row("recover_battle", "Recover interrupted battle", "", "w")
                if state["cleanup"]:
                    screen.row("cancel_battle", "Cancel battle entry", "", "w")
                if state["restart"]:
                    screen.row("restart_host", "Restart host service", "", "w")
                if state["trade"]:
                    screen.row("trade_recovery", "Check trade recovery", "", "w")
            if state["is_host"] and world_id in self.hosting:
                screen.row("info", "Server Information")
                screen.row("codes", "Invite codes for friends")
            if not running:
                screen.button("cancel", "Cancel start")
            screen.set_status("busy" if not running else "ok", state["flash"] or (state["note"] if running and state["note"] else
                                                                           status_text(state["code"])))
            return screen

        def tick():
            if absorb():
                if state["complete"] is not None:
                    return Done(state["complete"])
                return session_screen()
            return None

        outcome = None
        try:
            while True:
                try:
                    event = self.ui.show(session_screen(), tick=tick)
                except ShellClosed:
                    # The session window was closed while the game runs. Nothing is stopped for that: the game is closed from its own
                    # window, and only then does this program end (closing a game is not a save, so it is never done for the player).
                    while getattr(worker, "busy", False):
                        time.sleep(0.5)
                    raise
                if event.kind == "tick":
                    outcome = event.value
                    break
                state["flash"] = None
                if event.id == "save":
                    state["flash"] = "Saving..." if worker.request_save() else "Saving is not available right now."
                elif event.id == "autosave":
                    worker.request_autosave(not state["autosave"])
                elif event.id == "recover_battle":
                    worker.request_battle_recovery()
                elif event.id == "cancel_battle":
                    worker.request_battle_entry_cancel()
                elif event.id == "restart_host":
                    worker.request_host_restart()
                elif event.id == "trade_recovery":
                    worker.request_trade_recovery()
                elif event.id == "cancel":
                    worker.cancel_startup()
                elif event.id in ("info", "codes") and world_id in self.hosting:
                    entry = self.registry.get(world_id)
                    if entry is not None:
                        (self.server_information if event.id == "info" else self.invite_codes)(entry)
                elif event.kind == "back":
                    state["flash"] = "Close the game window to end your session."
        finally:
            self.hosting.pop(world_id, None)
            self.window(self.menu_window)
        if link is not None and outcome in ("game_closed", "save_recovery_required", "trade_recovery_reopen"):
            try:
                self.links.touch(world_id, player_id)
                if hosting:
                    self.registry.touch_hosted(world_id)
                if request.mode == "join":
                    server = self.servers.for_account(world_id, player_id)
                    if server is not None:
                        self.servers.touch(server["id"])
                if link["stage"] != "enrolled":
                    self.links.set_stage(world_id, player_id, "enrolled")
            except Exception:                                          # noqa: BLE001 - bookkeeping never hides the session's result
                pass
        if outcome == "game_closed":
            self.notice = ("ok", "Game closed. Your progress is saved to the world as of your last save.")
        elif outcome != "enrollment_required":
            self.notice = ("error" if outcome not in ("cancelled", "graphics_failed") else "warn", status_text(outcome))
        return outcome

    # ------------------------------------------------------------------ first-time character creation

    def _create_character(self, role, subject, player_id, *, server=None):
        """The player's New Game, then automatic approval and enrollment. Returns True when the character exists."""
        link = self.links.get(subject.world_id if role == "host" else server["world_id"], player_id)
        draft = None
        if link and link["stage"] == "draft" and link["draft"]:
            from types import SimpleNamespace
            source = Path(link["draft"]["source"])
            if source.is_file():
                draft = SimpleNamespace(source_path=source, sha256=link["draft"]["sha256"], party_count=1)
                try:
                    if hashlib.sha256(source.read_bytes()).hexdigest() != draft.sha256:
                        draft = None
                except OSError:
                    draft = None
        world_id = subject.world_id if role == "host" else server["world_id"]
        screen = Screen("create_character", "Create your character")
        if draft is not None:
            screen.note("You already created a character here but its setup did not finish.")
            screen.note("Continue setting it up: your game opens, choose CONTINUE, and your adventure begins.")
            screen.row("go", "Continue setting up my character", "", "as")
            screen.row("new", "Create a different character instead", "the earlier one is kept in your private folder")
        else:
            screen.note("This is your first time in this world, so you create your character with the game's normal New Game.")
            screen.note("1. Your game opens: choose your name and your starter Pokemon, then SAVE (START menu) and close the game.")
            screen.note("2. It opens once more: choose CONTINUE. It closes by itself when your character is registered.")
            screen.note("3. Your adventure starts. You are never asked to find or import a file.")
            screen.row("go", "Create my character", "", "as")
        screen.button("back", "Back")
        event = self.ui.show(screen)
        if event.kind == "back" or event.id == "back":
            return False
        if event.id == "new":
            draft = None
        texts = {
            "draft_running": "Create your trainer in the game window.\nWhen you are done, SAVE in the game (START menu) and close the game.",
            "draft_ready": "Your character is saved. Getting ready to register it.",
            "connecting": "Connecting to the world...",
            "approving": "Registering your character with the world...",
            "running": "Your game opens on your new character.\nChoose CONTINUE. It closes by itself once your character is registered.",
            "choose_continue": "Your game opens on your new character.\nChoose CONTINUE. It closes by itself once your character is registered.",
            "waiting_safe_place": "Waiting for you to reach a safe place in the game (outside menus and battles).\nChoose CONTINUE if you have not yet.",
            "enrolled": "Your character is registered.",
        }
        if role == "host":
            options = dict(world_directory=subject.folder)
        else:
            invitation = invitation_path(self.private_root, server["world_id"], server["player_id"])
            try:
                host = self.resolver(server["address"], server["port"])
            except Exception as error:                                 # noqa: BLE001
                self.message("Could not find the server", getattr(error, "args", ["The address could not be resolved."])[0])
                return False
            options = dict(invitation_path=invitation, route_host=host, route_port=server["port"])
        holder = {}

        async def make(job):
            def on_status(code):
                job.progress(code)

            def on_draft(result):
                holder["draft"] = result
                try:
                    self.links.set_stage(world_id, player_id, "draft", {"source": str(result.source_path), "sha256": result.sha256})
                except Exception:                                       # noqa: BLE001
                    pass
            return await self.creator(self.installation, self.private_root, role=role, draft=draft, on_status=on_status,
                                      on_draft=on_draft, **options)

        self.window(self.session_window)
        try:
            job = self.run_job(make, "Creating your character", texts["draft_running"], texts=texts)
        finally:
            self.window(self.menu_window)
        if job is None:
            self.notice = ("warn", "Character setup was cancelled. Nothing was lost; you can continue it from the same place.")
            return False
        if job.error is not None:
            self.last_error = job.error
            text = message_for(job.error) if isinstance(job.error, CreationError) else \
                "Setting up your character could not finish. Your files were kept; try again."
            self.message("Your character is not set up yet", text)
            self.notice = ("error", text)
            return False
        self.links.set_stage(world_id, player_id, "enrolled")
        return True

    # ------------------------------------------------------------------ Server Information, invite codes, network

    def _addresses_for(self, entry):
        local = [a for a in self.lan() if a != LOOPBACK]
        return local

    def server_information(self, entry):
        notice = None
        while True:
            entry = self.registry.get(entry.world_id) or entry
            hosting = self.hosting.get(entry.world_id)
            screen = Screen("server_info", f"Server Information - {entry.name}")
            if hosting:
                screen.set_status("ok", f"Hosting now on {hosting[0]}:{entry.port}")
            else:
                screen.set_status("info", "Not hosting right now. Choose Host This World to start it.")
            local = self._addresses_for(entry)
            lines = [f"World: {entry.name}   Port: {entry.port}",
                     f"Listens on: {'this PC only (127.0.0.1)' if entry.bind_address == LOOPBACK else entry.bind_address}",
                     "Local address: " + (", ".join(f"{a}:{entry.port}" for a in local) if local else "none found (no network connection)"),
                     "Public address: " + (f"{entry.address}:{entry.port} (set by you, not checked)" if entry.address else "not set"),
                     f"Internet access: {'on' if entry.internet else 'off'}"]
            for line in lines:
                screen.note(line)
            screen.note("Friends on the same network use the local address. Friends elsewhere need your public address and the port")
            screen.note("opened on your router. EmeraldTogether does not open ports, traverse your router or relay connections.")
            copy_target = entry.address or (local[0] if local and entry.bind_address != LOOPBACK else None)
            if copy_target:
                screen.row("copy", "Copy address", f"{copy_target}:{entry.port}", "a")
            screen.row("codes", "Invite codes for friends")
            screen.row("network", "Network settings")
            screen.button("back", "Back")
            if notice:
                screen.set_status(*notice)
            event = self.ui.show(screen)
            notice = None
            if event.kind == "back" or event.id == "back":
                return
            if event.id == "copy" and copy_target:
                self.ui.copy_text(f"{copy_target}:{entry.port}")
                notice = ("ok", "Address copied.")
            elif event.id == "codes":
                self.invite_codes(entry)
            elif event.id == "network":
                self.network_settings(entry)

    def invite_codes(self, entry):
        """A friend's invite code per account. A code is a credential: shown only after this PC verified the world."""
        if not self._need_game():
            return
        from .host_world import HostWorld
        try:
            world = HostWorld.open(entry.folder, self.installation.rom_path, self.installation.manifest_path)
        except Exception:                                              # noqa: BLE001
            self.message("The world could not be opened", "The world could not be verified, so no invite code was made. Nothing was changed.")
            return
        local = self._addresses_for(entry)
        address = entry.address or (local[0] if local and entry.bind_address != LOOPBACK else world.endpoint)
        notice = None
        while True:
            screen = Screen("codes", f"Invite codes - {entry.name}",
                            "One code per friend. Each lets that friend sign in as their own account in this world.")
            screen.note("Send each code only to that friend (a code is a password for their account).")
            if entry.bind_address == LOOPBACK and not entry.address:
                screen.note("This world listens on this PC only, so friends cannot reach it yet. Change Network settings first.")
            screen.note(f"The codes point at {address}:{entry.port}. A friend can edit the address in their saved server if it changes.")
            for account in world.accounts[1:]:
                screen.row(f"slot{account.slot}", account.display_name, "copy invite code", "")
            screen.button("back", "Back")
            if notice:
                screen.set_status(*notice)
            event = self.ui.show(screen)
            notice = None
            if event.kind == "back" or event.id == "back":
                return
            if event.id.startswith("slot"):
                slot = int(event.id[4:])
                try:
                    code = encode_invite(world.invitation(slot), address, entry.port)
                except (InvitationError, InviteCodeError, ValueError) as error:
                    notice = ("error", f"No code could be made: {error}")
                    continue
                self.ui.copy_text(code)
                notice = ("ok", f"Invite code for {world.accounts[slot].display_name} copied. Paste it to them privately.")

    def network_settings(self, entry):
        notice = None
        while True:
            entry = self.registry.get(entry.world_id) or entry
            screen = Screen("network", f"Network settings - {entry.name}")
            screen.note(f"Port {entry.port} was chosen when the world was created and stays the same, so invite codes keep working.")
            screen.row("bind", "Listen on", "this PC only" if entry.bind_address == LOOPBACK else entry.bind_address)
            screen.row("internet", "Internet access", "on - turn off" if entry.internet else "off - turn on")
            screen.row("address", "Public address or host name", entry.address or "not set")
            screen.row("enrollment", "New players create their character", "on - turn off" if entry.enrollment else "off - turn on")
            screen.note("When on, a friend with an invite code can create their own character over the connection. When off, only this PC can.")
            screen.button("back", "Back")
            if notice:
                screen.set_status(*notice)
            event = self.ui.show(screen)
            notice = None
            if event.kind == "back" or event.id == "back":
                return
            if event.id == "enrollment":
                self.registry.configure(entry.world_id, enrollment=not entry.enrollment)
                notice = ("ok", "Applies the next time you host this world.")
            elif event.id == "bind":
                options = [(LOOPBACK, "This PC only", "")] + [(a, f"Local network {a}", "") for a in self.lan()]
                picked = self.choose("Listen on", options)
                if picked:
                    self.registry.configure(entry.world_id, bind_address=picked)
            elif event.id == "internet":
                if entry.internet:
                    self.registry.configure(entry.world_id, internet=False)
                elif self.confirm("Allow Internet connections?",
                                  "Internet connections let anyone with an invite code and your public address reach this PC.\n"
                                  "Your router must forward the port and your firewall must allow it. EmeraldTogether does not set that up.",
                                  "Allow Internet connections", warn=True):
                    self.registry.configure(entry.world_id, internet=True)
            elif event.id == "address":
                text = self._ask_text("Public address or host name", "Where friends outside your network reach you. Not checked by EmeraldTogether.",
                                      entry.address, "Address", allow_empty=True)
                if text is not None:
                    if text and not valid_address(text):
                        notice = ("error", "That is not a usable address or host name.")
                    else:
                        self.registry.configure(entry.world_id, address=text)

    # ------------------------------------------------------------------ Join Server

    def join_menu(self):
        while True:
            servers = self.servers.all()
            screen = Screen("join_list", "Join Server", "Choose a saved server, or add a new one with an invite code.")
            screen.row("new", "Join New Server", "with an invite code", "a")
            for server in servers:
                state = character_state(self.private_root, server["world_id"], server["player_id"])
                who = {"ready": "your character", "none": "no character yet", "interrupted": "setup interrupted"}[state]
                screen.row(server["id"], server["name"], f"{server['address']}:{server['port']} - {server['display_name']} - {who}", "2")
            screen.button("back", "Back")
            if self.notice:
                screen.set_status(*self.notice)
                self.notice = None
            event = self.ui.show(screen)
            if event.kind == "back" or event.id == "back":
                return
            if event.id == "new":
                self.join_new()
            else:
                server = self.servers.get(event.id)
                if server is not None:
                    self.server_menu(server)

    def server_menu(self, server):
        while True:
            server = self.servers.get(server["id"])
            if server is None:
                return
            state = character_state(self.private_root, server["world_id"], server["player_id"])
            who = {"ready": "your saved character loads automatically", "none": "you create your character on first join",
                   "interrupted": "your first-time setup was interrupted"}[state]
            screen = Screen("server", server["name"], f"{server['address']}:{server['port']} - {server['display_name']} - {who}")
            screen.row("join", "Join", "", "as")
            screen.row("edit", "Edit name or address")
            screen.row("remove", "Remove this shortcut", "your character is kept", "w")
            screen.button("back", "Back")
            event = self.ui.show(screen)
            if event.kind == "back" or event.id == "back":
                return
            if event.id == "join":
                self._join_server(server)
                return
            elif event.id == "edit":
                self.edit_server(server)
            elif event.id == "remove":
                if self.confirm("Remove this saved server?",
                                f"Only the shortcut '{server['name']}' is removed.\n"
                                f"Your character '{server['display_name']}' and everything in it stay on this PC. Paste the same invite\n"
                                "code again (Join New Server) and you are back in the same character.", "Remove the shortcut", warn=True):
                    self.servers.remove(server["id"])
                    self.notice = ("ok", "Shortcut removed. Your character was kept.")
                    return

    def edit_server(self, server):
        status = None
        values = dict(name=server["name"], address=server["address"], port=str(server["port"]))
        while True:
            screen = Screen("edit_server", "Edit saved server",
                            "Changing the address never changes which character this is: it is the same world account.")
            screen.field("name", "Name", values["name"], "l48s")
            screen.field("address", "Address (IP or host name)", values["address"], "l253")
            screen.field("port", "Port", values["port"], "n")
            screen.button("save", "Save", "a")
            screen.button("back", "Cancel")
            if status:
                screen.set_status(*status)
            event = self.ui.show(screen)
            values.update({key: event.fields.get(key, values[key]).strip() for key in values})
            if event.kind == "back" or event.id == "back":
                return
            if not text_ok(values["name"], 48) or not valid_address(values["address"]) or not values["port"].isdigit() \
                    or not valid_port(int(values["port"])):
                status = ("error", "Check the name, the address (an IP or host name) and the port (1-65535).")
                continue
            self.servers.edit(server["id"], name=values["name"], address=values["address"], port=int(values["port"]))
            self.notice = ("ok", "Saved. Same world, same character, new address.")
            return

    def join_new(self):
        """Add a server from an invite code (or an invitation file). The code carries the account and the pinned host identity."""
        if not self._need_game():
            return
        values = dict(code="", name="", address="", port="")
        status = None
        while True:
            screen = Screen("join_new", "Join New Server", "Paste the invite code your host sent you (Ctrl+V).")
            screen.field("code", "Invite code", values["code"], "m")
            screen.field("name", "Name for this server (optional)", values["name"], "l48")
            screen.field("address", "Address (optional: the code has one)", values["address"], "l253")
            screen.field("port", "Port (optional)", values["port"], "n")
            screen.button("join", "Check and join", "a")
            screen.button("back", "Back")
            if status:
                screen.set_status(*status)
            event = self.ui.show(screen)
            for key in values:
                if key in event.fields:
                    values[key] = event.fields[key].strip() if key != "code" else event.fields[key]
            if event.kind == "back" or event.id == "back":
                return
            status = None
            try:
                invitation_source = self._parse_invite(values["code"])
            except (InviteCodeError, InvitationError, OSError, ValueError) as error:
                status = ("error", getattr(error, "args", ["That invite is not usable."])[0] if isinstance(error, InviteCodeError)
                          else "That invite could not be read. Copy it again from the host.")
                continue
            address = values["address"] or invitation_source["address"]
            port = int(values["port"]) if values["port"] else invitation_source["port"]
            if not valid_address(address) or not valid_port(port):
                status = ("error", "The address or port is not usable.")
                continue
            if invitation_source["build_id"] != getattr(self.installation, "rom_sha256", invitation_source["build_id"]):
                status = ("error", "That invite is for a different game version than the one installed here.")
                continue
            result = self._verify_new_server(invitation_source, address, port)
            if isinstance(result, str):
                status = ("error", result)
                continue
            invitation = result
            try:
                store_invitation(self.private_root, invitation)
            except InvitationConflict:
                status = ("error", "A different invite is already stored for this account on this PC. Nothing was changed.")
                continue
            name = values["name"] or f"{invitation.display_name}'s server"
            server, created = self.servers.add(name, address, port, invitation.world_id, invitation.player_id, invitation.slot,
                                               invitation.display_name)
            self.links.ensure(invitation.world_id, invitation.player_id, "friend", invitation.slot, server["name"], invitation.display_name)
            self.notice = ("ok", "Server saved." if created else "That account already had a saved server; its address was updated.")
            self._join_server(server)
            return

    def _parse_invite(self, text):
        """A dict(address, port, build_id, code | invitation) from pasted text: an invite code, or the path of an invitation file."""
        text = text.strip()
        if not text:
            raise InviteCodeError("invite_malformed", "Paste the invite code your host sent you.")
        candidate = Path(text.strip('"'))
        if len(text) < 600 and candidate.is_absolute() and candidate.is_file():
            invitation = Invitation.load(candidate)
            return dict(address=invitation.endpoint, port=invitation.port, build_id=invitation.build_id, invitation=invitation)
        code = decode_invite(text)
        return dict(address=code.address, port=code.port, build_id=code.build_id, code=code)

    def _verify_new_server(self, source, address, port):
        """The invitation for this server once its identity is verified, or a message saying why not."""
        async def check(job):
            job.progress("resolving")
            loop = asyncio.get_running_loop()
            numeric = await loop.run_in_executor(None, lambda: self.resolver(address, port))
            if "invitation" in source:
                invitation = source["invitation"]
                result = await self.prober(invitation, numeric, port, self.private_root / "network-checks")
                if not result.ok:
                    raise InviteCodeError("certificate_unavailable", result.message)
                return invitation
            code = source["code"]
            job.progress("verifying")
            pem = await self.fetcher(numeric, port, code.certificate_sha256, code.world_id)
            return redeem(code, pem, endpoint=numeric)

        job = self.run_job(check, "Checking the server", "Checking that the server is reachable and is the world this invite belongs to.")
        if job is None:
            return "Cancelled."
        if job.error is not None:
            if isinstance(job.error, (InviteCodeError, InvitationError)):
                return str(job.error)
            return "The server could not be reached. Check the address and port, and that the host is running the world."
        return job.result

    def _join_server(self, server):
        """Join a saved server: verify it is that world, start the session; the character loads by itself (or is created once)."""
        if not self._need_game():
            return
        path = invitation_path(self.private_root, server["world_id"], server["player_id"])
        try:
            invitation = Invitation.load(path)
        except (OSError, InvitationError, ValueError):
            self.message("This saved server needs its invite code again",
                         "The private invite for this account could not be read. Your character is untouched.\n"
                         "Paste the invite code your host sent (Join New Server) and you are back in the same character.")
            return
        while True:
            async def check(job):
                job.progress("resolving")
                numeric = await asyncio.get_running_loop().run_in_executor(None, lambda: self.resolver(server["address"], server["port"]))
                job.progress("checking")
                return numeric, await self.prober(invitation, numeric, server["port"], self.private_root / "network-checks")

            job = self.run_job(check, "Connecting", f"Connecting to {server['name']} and checking that it is the right world.")
            if job is None:
                return
            if job.error is not None:
                reason = "The address could not be found. Check it with the host."
                action = self._offline_choice(server, reason)
            else:
                numeric, result = job.result
                if result.ok:
                    break
                action = self._offline_choice(server, result.message)
            if action == "retry":
                continue
            if action == "edit":
                self.edit_server(server)
                server = self.servers.get(server["id"]) or server
                continue
            return
        from .launcher_gui import LaunchRequest
        request = LaunchRequest("join", path, route=(numeric, server["port"]))
        for attempt in range(2):
            outcome = self._play(request, server["name"], server["display_name"], world_id=server["world_id"],
                                 player_id=server["player_id"])
            if outcome != "enrollment_required":
                return
            if not self._create_character("friend", None, server["player_id"], server=server):
                return

    def _offline_choice(self, server, reason):
        screen = Screen("offline", f"Can't join {server['name']}")
        screen.note(reason)
        screen.note("Nothing was created or reset, and your character is untouched.")
        screen.row("retry", "Try again", "", "as")
        screen.row("edit", "Edit the address")
        screen.row("back", "Back")
        event = self.ui.show(screen)
        return event.id if event.kind == "select" else "back"

    # ------------------------------------------------------------------ Settings

    def settings_menu(self):
        notice = None
        while True:
            bundle = getattr(self.installation, "bundle", None)
            has_classic = bool(getattr(bundle, "has_classic", lambda: False)())
            screen = Screen("settings", "Settings", f"EmeraldTogether {self.version}")
            screen.row("graphics", "Graphics mode", MODE_LABELS.get(self.graphics.mode, self.graphics.mode))
            screen.row("display", "Display: window and quality")
            screen.row("audio", "Audio volumes")
            screen.row("controls", "Controls", "keyboard keys")
            screen.row("characters", "Characters on this PC")
            screen.row("multiplayer", "Multiplayer")
            screen.row("files", "Game files", "installed and verified" if self.game_ok else "not installed", "w" if not self.game_ok else "")
            screen.button("back", "Back")
            if notice:
                screen.set_status(*notice)
            event = self.ui.show(screen)
            notice = None
            if event.kind == "back" or event.id == "back":
                return
            if event.id == "graphics":
                notice = self._graphics_setting(has_classic)
            elif event.id == "display":
                notice = self._display_settings()
            elif event.id == "audio":
                notice = self._audio_settings()
            elif event.id == "controls":
                self._controls_info()
            elif event.id == "characters":
                self._characters_screen()
            elif event.id == "multiplayer":
                self._multiplayer_settings()
            elif event.id == "files":
                notice = self._game_files()

    def _graphics_setting(self, has_classic):
        options = [(MODE_3D, "Native 3D", "the default, needs OpenGL 3.3")]
        options.append((MODE_2D, "Classic 2D", "the original look" if has_classic else "not in this package", "" if has_classic else "d"))
        picked = self.choose("Graphics mode", options, notes=["Used the next time a game starts. Your saves, Pokemon and characters do not change."])
        if picked is None:
            return None
        saved = self.graphics.set(picked)
        return ("ok", f"Graphics mode: {MODE_LABELS[picked]}.") if saved else ("warn", "Used for this session; the choice could not be saved.")

    def _settings_path(self):
        from .player_runtime import SETTINGS_NAME
        return self.private_root / SETTINGS_NAME

    def _display_settings(self):
        from .game_display_settings import MODE_LABELS as MODES, QUALITY_LABELS, QUALITIES, RESOLUTION_LABELS, RESOLUTIONS
        from .game_display_settings import read_display_settings, write_display_settings
        path = self._settings_path()
        try:
            current = read_display_settings(path)
        except (OSError, ValueError):
            self.message("Display", "The game settings file cannot be read here. Nothing was changed.")
            return None
        while True:
            screen = Screen("display", "Display", "Used the next time a game starts. In the game, F10 opens the same settings.")
            screen.row("resolution", "Resolution", RESOLUTION_LABELS.get(current["resolution"], current["resolution"]))
            screen.row("mode", "Display mode", MODES.get(current["mode"], current["mode"]))
            screen.row("quality", "Graphics quality", QUALITY_LABELS.get(current["quality"], str(current["quality"])))
            screen.button("back", "Back")
            event = self.ui.show(screen)
            if event.kind == "back" or event.id == "back":
                return None
            table = {"resolution": (RESOLUTIONS, RESOLUTION_LABELS), "mode": (tuple(MODES), MODES), "quality": (QUALITIES, QUALITY_LABELS)}[event.id]
            picked = self.choose("Choose", [(key, table[1].get(key, key), "") for key in table[0]])
            if picked is None:
                continue
            updated = dict(current, **{event.id: picked})
            try:
                write_display_settings(path, resolution=updated["resolution"], mode=updated["mode"], quality=updated["quality"])
            except (OSError, ValueError):
                self.message("Display", "The game settings file could not be written. Nothing changed.")
                continue
            current = updated

    def _audio_settings(self):
        from .game_display_settings import read_audio_settings, write_audio_settings
        path = self._settings_path()
        try:
            current = read_audio_settings(path)
        except (OSError, ValueError):
            self.message("Audio", "The game settings file cannot be read here. Nothing was changed.")
            return None
        while True:
            screen = Screen("audio", "Audio volumes", "Used the next time a game starts. In the game, F10 changes them live.")
            screen.row("volume", "Game volume (music and effects)", f"{current['volume']} of 10")
            screen.row("cry_volume", "Pokemon cry volume", f"{current['cry_volume']} of 10")
            screen.button("back", "Back")
            event = self.ui.show(screen)
            if event.kind == "back" or event.id == "back":
                return None
            picked = self.choose("Volume", [(str(n), f"{n}", "") for n in range(0, 11)])
            if picked is None:
                continue
            current = dict(current, **{event.id: int(picked)})
            try:
                write_audio_settings(path, volume=current["volume"], cry_volume=current["cry_volume"])
            except (OSError, ValueError):
                self.message("Audio", "The game settings file could not be written. Nothing changed.")

    def _controls_info(self):
        """Rebind the keyboard keys of the game's buttons (the same game-settings.cfg lines the game and its F10 menu use)."""
        from . import game_controls as gc
        path = self._settings_path()
        try:
            bindings = gc.read_controls(path)
        except (OSError, ValueError):
            self.message("Controls", "The game settings file cannot be read here. Nothing was changed.")
            return
        notice = None
        while True:
            screen = Screen("controls", "Controls", "Choose a button, then press the key you want for it. Esc cancels.")
            screen.note("F1-F12 and Esc are kept for the menus. A gamepad is not affected. Used the next time a game starts.")
            for action_id, label, _ in gc.ACTIONS:
                screen.row("a_" + action_id, label, gc.key_label(bindings[action_id]), "k")
            screen.row("defaults", "Restore the default keys")
            screen.button("back", "Back")
            if notice:
                screen.set_status(*notice)
            event = self.ui.show(screen)
            notice = None
            if event.kind == "back" or event.id == "back":
                return
            if event.id == "defaults":
                bindings = dict(gc.DEFAULTS)
            elif event.id.startswith("a_") and event.fields.get("key"):
                action = event.id[2:]
                result, other = gc.assign(bindings, action, event.fields["key"])
                if result == gc.CONFLICT:
                    names = {a: l for a, l, _ in gc.ACTIONS}
                    if self.confirm("Key already in use", f"{gc.key_label(gc.canonical_key(event.fields['key']))} is the key for {names[other]}.\n"
                                    "Swap the two keys?", "Swap", "Cancel"):
                        gc.assign(bindings, action, event.fields["key"], swap=True)
                elif result in (gc.INVALID, gc.RESERVED_KEY):
                    notice = ("error", "That key cannot be used for a game button (F1-F12 and Esc are for the menus).")
            else:
                continue
            try:
                gc.write_controls(path, bindings)
            except (OSError, ValueError):
                notice = ("error", "The game settings file could not be written. Nothing changed.")
                bindings = gc.read_controls(path)

    def _characters_screen(self):
        screen = Screen("characters", "Characters on this PC", "Each belongs to one account in one world. Files are kept in your private folder.")
        links = sorted(self.links.all(), key=lambda link: (link["world_name"].casefold(), link["slot"]))
        if not links:
            screen.note("No characters yet.")
        for link in links:
            state = character_state(self.private_root, link["world_id"], link["player_id"])
            label = {"ready": "ready", "none": "not created yet", "interrupted": "setup interrupted"}[state]
            screen.row(link["world_id"] + link["player_id"], f"{link['display_name']} in {link['world_name']}",
                       f"{'host' if link['role'] == 'host' else 'friend'} - {label}", "d")
        screen.note("Folder: " + str(self.private_root / "players"))
        if self.migration is not None and self.migration.problems:
            screen.note("Left untouched because they could not be matched without guessing:")
            for problem in self.migration.problems[:6]:
                screen.note("  - " + problem)
            screen.note("Paste the invite code or the invitation file's path in Join Server, Join New Server to link them.")
        screen.button("back", "Back")
        self.ui.show(screen)

    def _multiplayer_settings(self):
        screen = Screen("multiplayer", "Multiplayer")
        screen.note("Network settings are per world (Host Server, choose a world, Network settings).")
        screen.note("Saved servers are edited in Join Server. Autosave and Save now are in the session window while you play.")
        rule = self.prefs.record["trade_rule"]
        screen.row("rule", "Trade friendship rule for new worlds", TRADE_RULES[rule][0] if rule else "not chosen yet")
        screen.button("back", "Back")
        event = self.ui.show(screen)
        if event.id == "rule":
            self.prefs.save({"format": PREFS_FORMAT, "trade_rule": self._trade_rule_change(rule)})

    def _game_files(self):
        if self._game_installed():
            self.game_ok = True
            self.message("Game files", "Your game files are installed and match this release. This checks the files, not gameplay.")
            return ("ok", "Game files verified.")
        self.game_ok = False
        if self.importer is None:
            self.message("Game files", "The game files are missing or changed, and this package cannot install them.")
            return ("error", "Game files missing.")
        screen = Screen("import", "Install your game",
                        "Enter the full path of your own Pokemon Emerald file. It is checked and kept only on this PC.")
        screen.field("path", "Path to your game file", "", "l1024s")
        screen.button("go", "Install", "a")
        screen.button("back", "Back")
        event = self.ui.show(screen)
        if event.kind == "back" or event.id == "back":
            return None
        source = Path(event.fields.get("path", "").strip().strip('"'))

        async def install(job):
            return await asyncio.get_running_loop().run_in_executor(None, lambda: self.importer.install(source))

        job = self.run_job(install, "Installing", "Checking and installing your game file.")
        if job is None or job.error is not None:
            self.message("Game files", "That file could not be used. Check that it is the supported game file.")
            return ("error", "Game files were not installed.")
        self.game_ok = self._game_installed()
        return ("ok", "Game installed.") if self.game_ok else ("error", "The installed files did not verify.")


def classic_launcher(release, application_directory, import_release):
    """The earlier launcher window: used only when the in-game menu cannot open (no display, a game that failed its check)."""
    from .launcher_gui import main as launcher_main
    launcher_main(release, application_directory, import_release)


def main(release=None, application_directory=None, import_release=None):
    """The packaged entry. Opens the menu inside the game's own window; the earlier launcher window is only the fallback."""
    import sys
    from .launcher_gui import SessionWorker, private_directory, windows_dpi_awareness
    from .shell_protocol import ShellProcess
    if release is None or "--classic-launcher" in sys.argv[1:]:                          # the earlier window, on request
        return classic_launcher(release, application_directory, import_release)          # a source preview has no game to host it
    try:
        private = private_directory()
        installation = release.installation(application_directory, private)
        bundle = installation.bundle
        executable, _ = bundle.verify(MODE_2D if bundle.has_classic() else MODE_3D)      # the classic game needs no 3D from the PC
        shell = ShellProcess([str(executable), "--shell"], cwd=private)
    except Exception:                                                                    # noqa: BLE001 - any failure: use the launcher
        return classic_launcher(release, application_directory, import_release)
    importer = None
    try:
        if import_release is not None:
            from .game_import import GameImporter
            if import_release.target_sha256 != release.rom_sha256:
                raise ValueError("release mismatch")
            importer = GameImporter(import_release, Path(application_directory) / "game.bps", private)
    except Exception:                                                                    # noqa: BLE001
        importer = None
    worker = SessionWorker(installation, private, importer=importer)
    app = ShellApp(installation, private, shell, version=release.version, worker=worker, importer=importer)
    try:
        return app.run()
    finally:
        shell.close()
