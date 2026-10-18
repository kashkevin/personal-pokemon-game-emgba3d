"""The EmeraldTogether main menu, inside the game's own window.

``EmeraldTogether.exe`` opens ``pokeemerald-mp --shell`` - the game's executable showing only its menu - and this module decides what
every screen says and does:

* **Continue Adventure** - the last world played, with the character played there;
* **Solo** - play by yourself in one of your worlds (or a new one);
* **Host World** - open one of your worlds to friends (invite codes, server information, network settings);
* **Join Friend** - a friend's world, from an invite code or a saved server;
* **Characters** - your trainers: create one (the game's New Game, once), choose which one plays, back up, restore an earlier
  version, recover an unfinished one from an earlier version, delete (moved aside, never destroyed);
* **Settings** and **Exit**.

Characters are universal (the owner's decision, 2026-10-18): the same trainer plays Solo, hosts, and joins friends, and its
Pokémon, levels, items and progress go with it (``character_library``, ``character_play``, ``character_transfer``). Entering a
world never needs another New Game: the first time a character enters a world (or comes back after playing elsewhere) its own
save is registered there - the game opens once, the player chooses CONTINUE, and it closes by itself when the world has saved
the character. Nothing a player has made is overwritten or deleted without their explicit confirmation; earlier saves are kept.

Identity. A world is identified by its stable world ID and an account in it by its stable player ID. A saved server is a
shortcut to an account (address, port and those two IDs); names, addresses and ports can change without making a different
account, and removing a shortcut only removes the shortcut.

The checks the earlier launcher made all still run - the installed game's pins, the host world's certificate and database, the
authenticated connection, closed-game recovery - because the same ``SessionWorker`` and ``LauncherSession`` start the game.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
import time

from .character_creation import CreationError, create_draft, message_for
from .character_library import CharacterLibrary, LibraryError
from .character_links import CharacterLinks, character_state, profile_directory
from .character_migration import migrate_characters, recover_draft, recoverable_drafts
from .character_play import needs_registration, record_after_session, register_character, sync_from_worlds
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
from .shell_store import JsonStore, StoreUnavailable, is_uuid, text_ok, time_ok
from .shell_tasks import BackgroundJob
from .world_registry import LOOPBACK, WorldRegistry, WorldRegistryError, free_port, valid_world_name

TRADE_RULES = {
    "gen6-stable-world-region-v1": ("Shared world region", "A trade keeps the same trainer's friendship (the world is one region)."),
    "gen6-absent-geography-refresh-v1": ("Missing geography", "A trade refreshes the friendship (Emerald has no regions to compare)."),
}
SESSION_WINDOW = (560, 420)
MENU_WINDOW = (1280, 720)
PREFS_FORMAT = "emerald-shell-preferences-v1"
LAST_FORMAT = "emerald-shell-last-session-v1"
SAFE = "Nothing was deleted, and your character's latest save is safe (Characters)."
DETAILS = "Details for troubleshooting were written to shell/last-error.txt in your private folder."
REGISTER_TEXTS = {
    "connecting": "Connecting to the world...",
    "approving": "The world is taking in your character...",
    "running": "Your game opens on your character.\nChoose CONTINUE. It closes by itself once the world has saved your character.",
    "choose_continue": "Your game opens on your character.\nChoose CONTINUE. It closes by itself once the world has saved your character.",
    "waiting_safe_place": "Waiting for you to stand in the field (outside menus and battles).\nChoose CONTINUE if you have not yet.",
    "enrolled": "Your character is in this world.",
}


def _prefs_validate(record):
    if set(record) != {"format", "trade_rule"} or not (record["trade_rule"] is None or record["trade_rule"] in TRADE_RULES):
        raise ValueError("invalid preferences")
    return record


def _last_validate(record):
    if set(record) != {"format", "kind", "world_id", "server_id", "character_id", "when"}:
        raise ValueError("invalid last session")
    if record["kind"] not in (None, "solo", "host", "join") or not (record["world_id"] is None or is_uuid(record["world_id"])) \
            or not (record["character_id"] is None or is_uuid(record["character_id"])) \
            or not (record["server_id"] is None or type(record["server_id"]) is str) or not (record["when"] is None or time_ok(record["when"])):
        raise ValueError("invalid last session")
    return record


def _empty_last():
    return {"format": LAST_FORMAT, "kind": None, "world_id": None, "server_id": None, "character_id": None, "when": None}


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

    def __init__(self, installation, private_root, ui, *, version="Development preview", worker=None,
                 register=register_character, drafter=create_draft,
                 resolver=resolve_address, fetcher=fetch_certificate, prober=probe_route, lan=lan_addresses, graphics=None,
                 graphics_gate=None, importer=None, clock=time.time, session_window=SESSION_WINDOW, menu_window=MENU_WINDOW):
        self.installation = installation
        self.private_root = Path(private_root)
        self.ui = ui
        self.version = version
        self.worker = worker
        self.register, self.drafter = register, drafter
        self.resolver, self.fetcher, self.prober, self.lan = resolver, fetcher, prober, lan
        self.graphics = graphics if graphics is not None else GraphicsPreference(self.private_root)
        self.graphics_gate = graphics_gate or self._graphics_gate
        self.importer = importer
        self.clock = clock
        self.session_window, self.menu_window = session_window, menu_window
        shell = self.private_root / "shell"
        self.registry = WorldRegistry(self.private_root, shell, clock=clock)
        self.links = CharacterLinks(shell, clock=clock)
        self.servers = SavedServers(shell, clock=clock)
        self.library = CharacterLibrary(self.private_root, clock=clock)
        self.prefs = JsonStore(shell / "preferences.json", PREFS_FORMAT, lambda: {"format": PREFS_FORMAT, "trade_rule": None},
                               _prefs_validate, clock=clock)
        self.last = JsonStore(shell / "last-session.json", LAST_FORMAT, _empty_last, _last_validate, clock=clock)
        self.notice = None
        self.hosting = {}                  # world id -> (bind address, port) while that world is being hosted
        self.migration = None
        self.library_migration = None
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
                                 (self.links._store, "characters"), (self.library._index, "characters")):
                if not store.available:
                    self.message("A record needs attention",
                                 f"The list of {label} on this PC could not be read, and no backup was usable.\n"
                                 "Nothing was changed or deleted. Close EmeraldTogether and restore the file from your backup,\n"
                                 "or ask for help before continuing.", "error", back="Continue anyway")
            try:
                self.library_migration = migrate_characters(self.private_root, self.library, self.links)
                synced = sync_from_worlds(self.private_root, self.library)
            except (OSError, LibraryError, StoreUnavailable) as error:
                self._record_error(error)
                self.library_migration, synced = None, []
            if self.library_migration is not None and self.library_migration.imported:
                names = ", ".join(sorted({name for name, _ in self.library_migration.imported}))
                self.notice = ("ok", f"Your characters from the earlier version are ready: {names}.")
            elif synced:
                self.notice = ("ok", "Your latest progress was picked up: " + ", ".join(synced) + ".")
            self.game_ok = self._game_installed()
            if self.migration.problems:
                count = len(self.migration.problems)
                self.notice = ("warn", f"{count} item{'s' if count != 1 else ''} from the earlier launcher could not be matched "
                                       "safely and were left untouched. See Characters.")
            while True:
                try:
                    if self.main_menu() == "exit":
                        return 0
                except ShellClosed:
                    raise
                except StoreUnavailable:
                    self.message("A record needs attention",
                                 "One of the menu's records is damaged and has no usable backup, so nothing was saved.\n"
                                 "Nothing was changed or deleted. Restore the file from your backup or ask for help.")
                except Exception as error:                              # noqa: BLE001 - a bug never closes the menu under a player
                    self.last_error = error
                    self._record_error(error)
                    self.message("Something went wrong",
                                 "That action could not finish. Nothing was deleted or reset.\n" + DETAILS)
        except ShellClosed:
            return 0

    def _record_error(self, error, *, game=False):
        """The traceback of an unexpected failure, for whoever has to look at it (no credentials are ever in these messages).
        ``game``: also the newest game launch's crash report and output (the launch folder, crash.log, the end of runtime.log;
        never bridge.txt, which holds the launch token)."""
        import traceback
        try:
            text = "".join(traceback.format_exception(error))[-8000:]
            if game:
                text += self._last_launch_report()
            folder = self.private_root / "shell"
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            (folder / "last-error.txt").write_text(text, encoding="utf-8")
        except OSError:
            pass

    def _last_launch_report(self):
        try:
            launches = [p for p in (self.private_root / "launches").iterdir() if p.is_dir()]
        except OSError:
            return "\nGame launch: none found.\n"
        if not launches:
            return "\nGame launch: none found.\n"
        folder = max(launches, key=lambda p: p.stat().st_mtime)
        parts = [f"\nGame launch folder: {folder}\n"]
        for name, limit in (("crash.log", 6000), ("runtime.log", 3000)):
            try:
                body = (folder / name).read_text(encoding="utf-8", errors="replace")
            except OSError:
                parts.append(f"{name}: none\n")
                continue
            parts.append(f"--- {name} (last {limit} characters) ---\n{body[-limit:]}\n")
        return "".join(parts)

    # ------------------------------------------------------------------ main menu

    def _continue_target(self):
        """(label, detail, action) for the last world played, or None."""
        record = self.last.record
        if record["kind"] is None:
            return self._continue_from_links()
        character = self.library.get(record["character_id"]) if record["character_id"] else None
        if character is None:
            return None
        if record["kind"] in ("solo", "host"):
            entry = self.registry.get(record["world_id"]) if record["world_id"] else None
            if entry is None:
                return None
            return (record["when"], record["kind"], entry, character)
        server = self.servers.get(record["server_id"]) if record["server_id"] else None
        if server is None:
            return None
        return (record["when"], "join", server, character)

    def _continue_from_links(self):
        """Before this version kept a last-session record: the most recently played world account whose character is in
        the library (what the earlier menu's Continue Adventure offered)."""
        best = None
        for link in self.links.all():
            binding = self.library.binding(link["world_id"], link["player_id"]) if link["last_played"] is not None else None
            character = self.library.get(binding[0]) if binding else None
            if character is None:
                continue
            if link["role"] == "host":
                entry = self.registry.get(link["world_id"])
                if entry is None:
                    continue
                candidate = (link["last_played"], "solo" if entry.kind == "adventure" and entry.bind_address == LOOPBACK else "host",
                             entry, character)
            else:
                server = self.servers.for_account(link["world_id"], link["player_id"])
                if server is None:
                    continue
                candidate = (link["last_played"], "join", server, character)
            if best is None or candidate[0] > best[0]:
                best = candidate
        return best

    def _remember(self, kind, character, *, world_id=None, server_id=None):
        try:
            self.last.save({"format": LAST_FORMAT, "kind": kind, "world_id": world_id, "server_id": server_id,
                            "character_id": character.character_id, "when": self.clock()})
        except (StoreUnavailable, ValueError):
            pass

    def main_menu(self):
        while True:
            character = self.library.active()
            target = self._continue_target()
            sub = f"Playing as {character.name}" if character else "Start by creating your character"
            screen = Screen("main", "Main menu", f"EmeraldTogether {self.version} - {sub}")
            if target is None:
                screen.row("continue", "Continue Adventure", "nothing played yet", "d")
            else:
                when = _ago(target[0], self.clock())
                place = target[2].name if target[1] != "join" else target[2]["name"]
                how = {"solo": "Solo", "host": "hosting", "join": "with friends"}[target[1]]
                screen.row("continue", "Continue Adventure", f"{place} - {target[3].name} - {how} - {when}", "s")
            worlds = len(self.registry.entries(default_bind=self._default_bind()))
            screen.row("solo", "Solo", "play by yourself" + (f" - {worlds} world{'s' if worlds != 1 else ''}" if worlds else ""))
            screen.row("host", "Host World", "play with friends in one of your worlds")
            screen.row("join", "Join Friend", f"{len(self.servers.all())} saved")
            screen.row("characters", "Characters", character.name if character else "create your character",
                       "" if character else ("s" if target is None else ""))
            screen.row("settings", "Settings")
            screen.row("exit", "Exit")
            if not self.game_ok:
                screen.set_status("warn", "Your game files are not ready. Open Settings, Game files.")
            elif self.notice:
                screen.set_status(*self.notice)
            elif character is None:
                screen.set_status("info", "Create your character once (Characters). It plays Solo and with friends.")
            self.notice = None
            event = self.ui.show(screen)
            choice = event.id if event.kind == "select" else "exit" if event.kind == "back" else ""
            if choice == "exit":
                return "exit"
            elif choice == "continue" and target is not None:
                self._continue(target)
            elif choice == "solo":
                self.solo_menu()
            elif choice == "host":
                self.host_menu()
            elif choice == "join":
                self.join_menu()
            elif choice == "characters":
                self.characters_menu()
            elif choice == "settings":
                self.settings_menu()

    def _default_bind(self):
        addresses = self.lan()
        return addresses[0] if addresses else LOOPBACK

    def _continue(self, target):
        _, kind, subject, character = target
        if self.library.active() is None or self.library.active().character_id != character.character_id:
            try:
                self.library.set_active(character.character_id)
            except (LibraryError, StoreUnavailable):
                pass
        if kind == "join":
            self._join_server(subject)
        else:
            self._enter_own_world(subject, solo=kind == "solo")

    # ------------------------------------------------------------------ characters

    def _require_character(self):
        """The active character, or None after offering to create one."""
        character = self.library.active()
        if character is not None:
            return character
        if not self._need_game():
            return None
        if self.confirm("Create your character first",
                        "You play with one character everywhere: Solo, in your worlds with friends, and in friends' worlds.\n"
                        "Its Pokemon, levels, items and progress go with it. Create it now? (about two minutes in the game)",
                        "Create my character", "Back"):
            return self.create_character_flow()
        return None

    def create_character_flow(self):
        """The game's New Game, once: name, look, starter, Save, close. Returns the new character (now active) or None."""
        if not self._need_game():
            return None
        screen = Screen("create_character", "Create a character")
        screen.note("1. The game opens on a New Game. Choose your name, look and starter Pokemon.")
        screen.note("2. Save the game (START menu, SAVE), then close the game window.")
        screen.note("3. Your character is ready: it plays Solo, hosts your worlds and joins your friends.")
        screen.note("This happens on this PC only; no world or connection is needed.")
        screen.row("go", "Create my character", "", "as")
        screen.button("back", "Back")
        event = self.ui.show(screen)
        if event.kind == "back" or event.id != "go":
            return None
        texts = {"draft_running": "Create your trainer in the game window.\nWhen you are done, SAVE (START menu) and close the game."}

        async def make(job):
            return await self.drafter(self.installation, self.private_root, on_status=job.progress)

        self.window(self.session_window)
        try:
            job = self.run_job(make, "Creating your character", texts["draft_running"], texts=texts)
        finally:
            self.window(self.menu_window)
        if job is None:
            self.notice = ("warn", "Character creation was cancelled. Nothing was created.")
            return None
        if job.error is not None:
            self._explain("Your character was not created", job.error, game=True,
                          safe="Nothing was changed. You can try again from Characters.")
            return None
        try:
            payload = Path(job.result.source_path).read_bytes()
            character = self.library.create(payload, origin="new_game")
            self.library.set_active(character.character_id)
        except (OSError, LibraryError, StoreUnavailable) as error:
            self._explain("Your character could not be kept", error,
                          safe="The game's save is still in the drafts folder; Characters, Recover a character finds it.")
            return None
        self.notice = ("ok", f"{character.name} is ready. Choose Solo, Host World or Join Friend to play.")
        return character

    def characters_menu(self):
        while True:
            characters = self.library.all()
            active = self.library.active()
            screen = Screen("characters", "Characters",
                            "One character plays everywhere: Solo, your worlds with friends, and friends' worlds.")
            screen.row("create", "Create a new character", "the game's New Game, once", "a" if not characters else "")
            for character in characters:
                where = "never played in a world yet" if character.world_id is None else f"last played {_ago(character.last_played, self.clock())}"
                mark = "playing - " if active is not None and character.character_id == active.character_id else ""
                screen.row("c:" + character.character_id, character.name, f"{mark}{where}", "2" + ("s" if mark else ""))
            drafts = recoverable_drafts(self.private_root, self.library)
            if drafts:
                screen.row("recover", "Recover a character", f"{len(drafts)} from earlier attempts")
            for folder, reason in self.library.damaged.items():
                screen.row("damaged:" + folder, f"A character folder could not be read ({reason})", "left untouched", "2d")
            problems = list(self.migration.problems if self.migration is not None else [])
            problems += [f"{Path(path).parent.name}: {reason}" for path, reason in
                         (self.library_migration.problems if self.library_migration is not None else [])]
            if problems:
                screen.note("Some items from the earlier version could not be matched safely. Left untouched (nothing was deleted):")
                for problem in problems[:4]:
                    screen.note("- " + problem)
            screen.button("back", "Back")
            if self.notice:
                screen.set_status(*self.notice)
                self.notice = None
            event = self.ui.show(screen)
            if event.kind == "back" or event.id == "back":
                return
            if event.id == "create":
                self.create_character_flow()
            elif event.id == "recover":
                self._recover_menu(drafts)
            elif event.id.startswith("c:"):
                character = self.library.get(event.id[2:])
                if character is not None:
                    self.character_menu(character)

    def _recover_menu(self, drafts):
        options = [(str(i), draft.trainer_name, time.strftime("%Y-%m-%d %H:%M", time.localtime(draft.modified)))
                   for i, draft in enumerate(drafts)]
        picked = self.choose("Recover a character", options,
                             notes=["Characters created in earlier attempts that never finished setting up.",
                                    "Choose one to keep it as a character. The original files stay where they are."])
        if picked is None:
            return
        try:
            character = recover_draft(self.library, drafts[int(picked)])
        except (OSError, LibraryError, StoreUnavailable) as error:
            self._explain("That character could not be recovered", error, safe="Nothing was changed.")
            return
        self.notice = ("ok", f"{character.name} was recovered. Choose it to play as it.")

    def character_menu(self, character):
        while True:
            character = self.library.get(character.character_id)
            if character is None:
                return
            active = self.library.active()
            playing = active is not None and active.character_id == character.character_id
            where = "has not entered a world yet" if character.world_id is None else f"last played {_ago(character.last_played, self.clock())}"
            screen = Screen("character", character.name, f"Trainer ID {character.trainer_id & 0xFFFF:05d} - {where}")
            if not playing:
                screen.row("play", "Play as this character", "", "as")
            else:
                screen.note("This is the character you play as.")
            screen.row("rename", "Rename")
            screen.row("backup", "Back up now", "keeps a copy of the current save")
            history = self.library.history(character)
            screen.row("restore", "Restore an earlier version", f"{len(history)} kept" if history else "none yet", "" if history else "d")
            screen.row("delete", "Delete this character", "asks first", "w")
            screen.note(f"Folder: {character.folder}")
            screen.button("back", "Back")
            if self.notice:
                screen.set_status(*self.notice)
                self.notice = None
            event = self.ui.show(screen)
            if event.kind == "back" or event.id == "back":
                return
            try:
                if event.id == "play":
                    self.library.set_active(character.character_id)
                    self.notice = ("ok", f"You now play as {character.name}.")
                elif event.id == "rename":
                    name = self._ask_text("Rename", "The name shown in this menu (the trainer's name in the game does not change).",
                                          character.name, "Name", flags="l24")
                    if name:
                        self.library.rename(character.character_id, name)
                elif event.id == "backup":
                    self.library.backup_now(character)
                    self.notice = ("ok", "A copy of the current save was kept.")
                elif event.id == "restore" and history:
                    options = [(str(i), path.name[:16].replace("T", " "), "backup" if "backup" in path.name else "") for i, path in enumerate(history[:20])]
                    picked = self.choose("Restore an earlier version", options,
                                         notes=["The current save is kept too, so you can switch back.",
                                                "The next time this character enters a world, this version goes in."])
                    if picked is not None and self.confirm("Restore this version?", "The current save is kept in the list of earlier versions.",
                                                           "Restore"):
                        self.library.restore(character, history[int(picked)])
                        self.notice = ("ok", "Restored. The next world you enter gets this version.")
                elif event.id == "delete":
                    if self.confirm(f"Delete {character.name}?",
                                    f"{character.name} disappears from this menu. Its saves are moved to the characters-deleted folder\n"
                                    "in your private folder, not destroyed. Its progress stays in the worlds it played in.",
                                    f"Delete {character.name}", warn=True):
                        self.library.delete(character.character_id)
                        self.notice = ("ok", f"{character.name} was moved to characters-deleted.")
                        return
            except (OSError, LibraryError, StoreUnavailable) as error:
                self.notice = ("error", f"That did not work: {error}")

    def _explain(self, title, error, *, safe=SAFE, game=False):
        """A plain message for a failed action: what failed, why if known, whether the player's things are safe. The traceback
        goes to shell/last-error.txt, never on screen."""
        self.last_error = error
        self._record_error(error, game=game)
        if isinstance(error, CreationError):
            reason = message_for(error)
        elif isinstance(error, LibraryError):
            reason = str(error).capitalize() + "."
        else:
            reason = "It could not finish."
        self.message(title, reason + "\n\n" + safe + "\n" + DETAILS)
        self.notice = ("error", title + ".")

    def _registered(self, character, world_name, world_id, player_id, *, role, entry=None, server=None, route=None):
        """Make sure this world account holds ``character``'s latest progress (registering it when needed). True when ready."""
        plan = needs_registration(self.private_root, self.library, character, world_id, player_id)
        if not plan.register:
            return True
        screen = Screen("bring_character", f"{character.name} enters {world_name}")
        if plan.reason == "new_here":
            screen.note(f"This is {character.name}'s first visit to {world_name}. Their Pokemon, items and progress come with them.")
        elif plan.reason == "coming_back":
            screen.note(f"{character.name} has played somewhere else since the last visit here. Their latest progress comes with them;")
            screen.note("their earlier save in this world is kept.")
        else:
            screen.note(f"Another character used this place in {world_name} before. {character.name} takes it over;")
            screen.note("the other character keeps all of their progress in Characters.")
        screen.note("The game opens once: choose CONTINUE. It closes by itself when the world has saved your character.")
        screen.row("go", "Continue", "", "as")
        screen.button("back", "Back")
        event = self.ui.show(screen)
        if event.kind == "back" or event.id != "go":
            return False
        if role == "host":
            options = dict(world_directory=entry.folder)
        else:
            options = dict(invitation_path=invitation_path(self.private_root, world_id, player_id), route_host=route[0], route_port=route[1])

        async def enter(job):
            return await self.register(self.installation, self.private_root, self.library, character, role=role, world_id=world_id,
                                       player_id=player_id, on_status=job.progress, **options)

        self.window(self.session_window)
        try:
            job = self.run_job(enter, f"{character.name} enters {world_name}", REGISTER_TEXTS["choose_continue"], texts=REGISTER_TEXTS)
        finally:
            self.window(self.menu_window)
        if job is None:
            self.notice = ("warn", "Cancelled. Your character was not changed; try again whenever you like.")
            return False
        if job.error is not None:
            self._explain(f"{character.name} could not enter {world_name}", job.error, game=True)
            return False
        return True

    def _after_session(self, character, world_id, player_id, outcome):
        """After a game in a world: the character's latest save is that world's (its previous save stays in its history)."""
        try:
            updated = record_after_session(self.private_root, self.library, character.character_id, world_id, player_id)
        except (OSError, LibraryError, StoreUnavailable) as error:
            self._record_error(error)
            self.notice = ("warn", "Your progress is saved in the world, but your character list could not be updated. "
                                   "It updates the next time you start EmeraldTogether.")
            return
        if updated is not None and outcome == "game_closed":
            self.notice = ("ok", f"Game closed. {character.name}'s progress is saved (as of your last save).")

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
                        self.world_menu(entry, hosting=True)
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

    # ------------------------------------------------------------------ Solo and Host World (the player's own worlds)

    def _world_detail(self, entry):
        when = entry.last_hosted
        return f"{len(entry.accounts)} places - port {entry.port} - {'played ' + _ago(when, self.clock()) if when else 'never played'}"

    def solo_menu(self):
        character = self._require_character()
        if character is None:
            return
        while True:
            entries = self.registry.entries(default_bind=self._default_bind())
            screen = Screen("solo", "Solo", f"Play by yourself as {character.name}. Choose a world, or start a new one.")
            screen.row("new", "New world", "a fresh world from the beginning of the story", "a" if not entries else "")
            for entry in entries:
                screen.row(entry.world_id, entry.name, self._world_detail(entry), "2")
            if entries:
                screen.row("manage", "Manage worlds", "rename, delete, network settings")
            for folder, reason in self.registry.damaged.items():
                screen.row("damaged:" + folder, f"Unusable world folder ({reason})", "left untouched", "2d")
            screen.button("back", "Back")
            if self.notice:
                screen.set_status(*self.notice)
                self.notice = None
            event = self.ui.show(screen)
            if event.kind == "back" or event.id == "back":
                return
            if event.id == "new":
                entry = self._new_solo_world(character)
                if entry is not None and self._enter_own_world(entry, solo=True):
                    return
            elif event.id == "manage":
                self.manage_worlds()
            else:
                entry = next((item for item in entries if item.world_id == event.id), None)
                if entry is not None and self._enter_own_world(entry, solo=True):
                    return

    def _new_solo_world(self, character):
        if not self._need_game():
            return None
        rule = self._trade_rule()
        if rule is False:
            return None
        names = {entry.name.casefold() for entry in self.registry.entries(default_bind=self._default_bind())}
        number = 1
        while f"world {number}" in names:
            number += 1
        name = self._ask_text("New world", "A name for your new world (you can rename it later).", f"World {number}", "World name",
                              flags="l32s")
        if not name:
            return None
        if not valid_world_name(name) or self.registry.name_taken(name):
            self.notice = ("error", "Choose another name (up to 32 characters, not used by another of your worlds).")
            return None
        return self._create_world(name, character.name[:24], rule, bind=LOOPBACK, kind="adventure")

    def manage_worlds(self):
        while True:
            entries = self.registry.entries(default_bind=self._default_bind())
            options = [(entry.world_id, entry.name, self._world_detail(entry)) for entry in entries]
            picked = self.choose("Manage worlds", options, notes=["Your worlds on this PC. Friends' worlds are in Join Friend."])
            if picked is None:
                return
            entry = next((item for item in entries if item.world_id == picked), None)
            if entry is not None:
                self.world_menu(entry)

    def host_menu(self):
        character = self._require_character()
        if character is None:
            return
        while True:
            entries = self.registry.entries(default_bind=self._default_bind())
            screen = Screen("host_list", "Host World", f"Open one of your worlds to friends. You play as {character.name}.")
            screen.row("create", "Create a new world", "with its own story progress and up to three friends", "a" if not entries else "")
            for entry in entries:
                screen.row(entry.world_id, entry.name, self._world_detail(entry), "2")
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
                    self.world_menu(entry, hosting=True)

    def world_menu(self, entry, hosting=False):
        while True:
            entry = self.registry.get(entry.world_id) or entry
            screen = Screen("world", entry.name, self._world_detail(entry))
            if hosting:
                screen.row("host", "Host this world now", "friends can join while you play", "as")
                screen.row("solo", "Play it Solo instead")
            else:
                screen.row("solo", "Play Solo", "", "as")
                screen.row("host", "Host it for friends")
            screen.row("codes", "Invite codes for friends")
            screen.row("info", "Server information")
            screen.row("network", "Network settings")
            screen.row("rename", "Rename world")
            screen.row("delete", "Delete world", "asks first", "w")
            screen.button("back", "Back")
            if self.notice:
                screen.set_status(*self.notice)
                self.notice = None
            event = self.ui.show(screen)
            if event.kind == "back" or event.id == "back":
                return
            if event.id in ("host", "solo"):
                self._enter_own_world(entry, solo=event.id == "solo")
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
            elif event.id == "delete":
                if entry.world_id in self.hosting:
                    self.notice = ("error", "Stop hosting this world first.")
                elif self.confirm(f"Delete {entry.name}?",
                                  f"{entry.name} disappears from your worlds, and friends can no longer join it.\n"
                                  "Its folder is moved to worlds-deleted in your private folder, not destroyed.\n"
                                  "Your characters keep their latest progress (Characters).", f"Delete {entry.name}", warn=True):
                    try:
                        self.registry.remove(entry.world_id)
                    except (OSError, KeyError, StoreUnavailable) as error:
                        self._explain("The world could not be deleted", error, safe="Nothing was changed.")
                        continue
                    self.notice = ("ok", f"{entry.name} was moved to worlds-deleted.")
                    return

    def _enter_own_world(self, entry, *, solo):
        """Play one of the player's own worlds with the active character: Solo (this PC only) or hosted for friends.
        Returns whether the game ran (False when the player backed out or was told why it could not start)."""
        if not self._need_game():
            return False
        character = self._require_character()
        if character is None:
            return False
        host_id = entry.accounts[0][1]
        if not solo:
            job = self.run_job(lambda job: asyncio.get_running_loop().run_in_executor(None, lambda: self._prepare(entry)),
                               "Getting the world ready", "Preparing the world for this version (a backup is made first).")
            if job is None:
                return False
            if job.error is not None:
                self._explain(f"{entry.name} could not be prepared", job.error, safe="The world was not changed.")
                return False
        if not self._registered(character, entry.name, entry.world_id, host_id, role="host", entry=entry):
            return False
        note = None
        if solo:
            bind = LOOPBACK
        else:
            bind, note = self._bind_for(entry)
        from .launcher_gui import LaunchRequest
        request = LaunchRequest("host", entry.folder / "host.json", bind, bool(entry.internet and not solo),
                                allow_enrollment=bool(entry.enrollment and not solo))
        for attempt in range(2):
            outcome = self._play(request, entry.name, character.name, world_id=entry.world_id, player_id=host_id,
                                 hosting=None if solo else (entry.world_id, bind, entry.port), note=note)
            if outcome != "enrollment_required":
                break
            # The world has no character for this account (an older world, or a restored backup): register and start again.
            if not self._registered(character, entry.name, entry.world_id, host_id, role="host", entry=entry):
                return False
        self._after_session(character, entry.world_id, host_id, outcome)
        try:
            self.registry.touch_hosted(entry.world_id)
        except (KeyError, StoreUnavailable):
            pass
        self._remember("solo" if solo else "host", character, world_id=entry.world_id)
        return True

    def _prepare(self, entry):
        from .launcher_setup import prepare_world_for_returning_characters
        return prepare_world_for_returning_characters(self.installation, entry.folder)

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

    # ------------------------------------------------------------------ Join Friend

    def join_menu(self):
        while True:
            servers = self.servers.all()
            screen = Screen("join_list", "Join Friend", "Choose a friend's world you joined before, or join a new one with an invite code.")
            screen.row("new", "Join with an invite code", "your host sends you one", "a" if not servers else "")
            for server in servers:
                when = "played " + _ago(server["last_joined"], self.clock()) if server["last_joined"] else "not played yet"
                screen.row(server["id"], server["name"], f"{server['address']}:{server['port']} - {when}", "2")
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
            character = self.library.active()
            who = f"you play as {character.name}" if character else "create your character first"
            screen = Screen("server", server["name"], f"{server['address']}:{server['port']} - {who}")
            screen.row("join", "Join", "", "as")
            screen.row("edit", "Edit name or address", "if the host's address changed")
            screen.row("remove", "Remove from this list", "your characters are not touched", "w")
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
                if self.confirm(f"Remove {server['name']} from the list?",
                                f"Only this entry is removed. Your characters and their progress are not touched.\n"
                                "To join this world again later, paste the host's invite code again.", "Remove", warn=True):
                    self.servers.remove(server["id"])
                    self.notice = ("ok", "Removed from the list. Your characters were not touched.")
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
            screen = Screen("join_new", "Join with an invite code", "Paste the invite code your host sent you (Ctrl+V).")
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
        """Join a saved server with the active character: verify it is that world, bring the character in if needed, play."""
        if not self._need_game():
            return
        character = self._require_character()
        if character is None:
            return
        path = invitation_path(self.private_root, server["world_id"], server["player_id"])
        try:
            Invitation.load(path)
        except (OSError, InvitationError, ValueError):
            self.message("This saved server needs its invite code again",
                         "The private invite for this account could not be read. Nothing was changed.\n"
                         "Paste the invite code your host sent (Join Friend, Join with an invite code).")
            return
        invitation = Invitation.load(path)
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
        route = (numeric, server["port"])
        if not self._registered(character, server["name"], server["world_id"], server["player_id"], role="friend", server=server,
                                route=route):
            return
        from .launcher_gui import LaunchRequest
        request = LaunchRequest("join", path, route=route)
        for attempt in range(2):
            outcome = self._play(request, server["name"], character.name, world_id=server["world_id"], player_id=server["player_id"])
            if outcome != "enrollment_required":
                break
            # The host's world has no character for this account (a restored world): bring the character in again.
            if not self._registered(character, server["name"], server["world_id"], server["player_id"], role="friend",
                                    server=server, route=route):
                return
        self._after_session(character, server["world_id"], server["player_id"], outcome)
        self._remember("join", character, world_id=server["world_id"], server_id=server["id"])

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
            screen.row("characters", "Characters", "create, choose, back up, restore")
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
                self.characters_menu()
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

    def _multiplayer_settings(self):
        screen = Screen("multiplayer", "Multiplayer")
        screen.note("Network settings are per world (Host World, choose a world, Network settings).")
        screen.note("Friends' worlds are edited in Join Friend. Autosave and Save now are in the session window while you play.")
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
