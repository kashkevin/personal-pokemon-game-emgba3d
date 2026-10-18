"""Windows Host/Join window over the verified enrolled-character lifecycle.

Tk stays on its creating thread. A single asyncio worker owns every session,
child and network handle; only fixed status codes and bounded public summaries
cross the UI queue.
Release pins are compiled into the application entry point, never user input.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
import os
from pathlib import Path
import queue
import re
import threading

from .tk_threads import start_thread
from .graphics_mode import EXIT_GRAPHICS_UNAVAILABLE, GraphicsPreference, MODE_3D, probe_graphics
from .launcher_session import GameInstallation, LauncherSession, SessionState
from .network_diagnostics import ConnectionDetails
from .player_runtime import RuntimeBundle
from .server import is_local_address


_TEXT = {
    "idle": "Choose Continue Adventure, or open My Worlds, Host Multiplayer or Join Friend.",
    "back_busy": "Close the game window first (or wait for the startup to finish), then return to the main menu.",
    "game_not_installed": "Your game is not installed on this PC yet. Open Settings, Game files, and choose Import my game.",
    "game_found": "The game files are in place. Check installed game files verifies them against this release.",
    "continue_none": "There is nothing to continue yet. Create or choose a world in My Worlds, or join a friend.",
    "continue_missing": "The world or invitation you last played could not be found. Choose one in My Worlds or Join Friend.",
    "exit_busy": "A game or startup is still running. Closing now asks it to stop; its save and recovery files are kept. Close anyway?",
    "internet_confirm": "Internet connections let anyone with your invitation and your public address reach this PC. Your router must forward the game's TCP port to it, and your firewall must allow it; this launcher does not set those up and there is no relay server. Host with Internet connections turned on?",
    "lan_found": "Filled in this PC's network address. Friends on your network use it in their invitations.",
    "lan_found_many": "Filled in one of this PC's network addresses (the likeliest). Change it if friends use a different network.",
    "lan_none": "No network address was found. Connect to your network, or type this PC's address.",
    "installation": "Checking your installed game…",
    "authentication": "Connecting to the host…",
    "ready": "Your character is ready.",
    "canonical_recovery": "Restoring your verified character…",
    "running": "Game running. Close the game window when you finish.",
    "game_closed": "Game closed. You can host or join again.",
    "graphics_checking": "Checking that 3D graphics can start on this PC…",
    "graphics_fallback": "Starting in Classic 2D this time. Your saved graphics mode is unchanged.",
    "graphics_cancelled": "Nothing was started. Choose Classic 2D under Help > Game display, or try 3D again.",
    "graphics_failed": "The game's graphics could not start, and the game said why. Your save is untouched. Start again and choose Launch in Classic 2D, or set Graphics mode to Classic 2D under Help > Game display.",
    "cancelled": "Startup cancelled. Private recovery data is retained.",
    "closing": "Closing the connection…",
    "wait_for_game": "Close the game window to finish. This launcher will then close.",
    "wait_for_recovery": "Keep this game and launcher open until recovery finishes. Closing the game would lose its waiting state.",
    "game_recovery_held": "This game needs recovery. Keep its paused game window open so the waiting state is retained.",
    "package_missing": "This launcher preview needs a verified game package before play.",
    "selection_required": "Choose your world or friend invitation first.",
    "address_invalid": "Enter this PC’s local IPv4 or IPv6 address, such as 192.168.1.20.",
    "private_storage": "Your private application folder could not be opened.",
    "enrollment_required": "This character needs first-time setup. Open My Worlds, then Set up characters, to enroll it.",
    "pending_battle": "An interrupted battle needs recovery before this character can open.",
    "battle_recovery_unavailable": "The host could not check interrupted battles. Use the matching host version before opening this character.",
    "recovery_required": "Your character needs recovery before the game can open. Its private files have been retained.",
    "connection_timeout": "Could not connect to the host in time. The world may not be hosted right now, or a router, firewall or the Internet provider blocks the connection.",
    "version_mismatch": "The host runs a different EmeraldTogether version. Install the same version on both PCs.",
    "wrong_world": "The server at that address is not the world from your invite. Nothing was sent to it. Ask the host for the current address.",
    "rejected_public_exposure_disabled": "The host's world accepts only players on the host's own network. The host can turn on Internet access in Network settings.",
    "rejected_player_already_connected": "This character is already connected to the world. Close the other game using it, or wait half a minute and try again.",
    "rejected_invalid_credentials": "The host did not accept this invite. Ask the host for a new invite code.",
    "rejected_enrollment_disabled": "The host has turned off creating new characters. Ask the host to allow new characters in Network settings.",
    "rejected_server_full": "The world is full. Try again when someone leaves.",
    "rejected_busy": "The host is busy. Try again in a few seconds.",
    "rejected": "The host refused the connection. Try again; if it keeps happening, ask the host for a new invite code.",
    "connection_lost": "Connection to the host was lost. Keep the game open while its save or battle recovery status is checked.",
    "host_loss_preserving": "Host connection lost. Preserving your game locally; keep the game open.",
    "host_loss_preserved": "Host connection lost. Your local save is preserved. Close the game and rejoin when the host returns.",
    "host_loss_unsaved_held": "Host connection lost. Saving could not be verified. Keep this paused game open for recovery.",
    "host_loss_battle_waiting": "Battle interrupted. Keep the game open; the battle is waiting for all players.",
    "host_loss_trade_waiting": "Trade interrupted. Keep this game open. Once the host is back, Resolve interrupted trade cancels an unfinished exchange or verifies an already committed result.",
    "trade_recovery_checking": "Checking the exact trade and saved bytes. An unfinished trade will be canceled. Keep the original game open.",
    "trade_recovery_held": "Trade recovery is not verified. Keep the original game and its files, restore the host, then try Resolve interrupted trade again.",
    "trade_recovery_close": "Trade fate and saved bytes verified. Close this game window normally, then choose the same Host Game or Join Game identity. Recovery runs before Continue.",
    "trade_recovery_reopen": "Original game closed. Choose the same Host Game or Join Game identity to load the verified trade result before Continue.",
    "trade_recovered": "Your committed trade was recovered. The verified received Pokemon are loaded.",
    "trade_aborted_recovered": "The unfinished trade was canceled. Your verified pre-trade Pokemon are loaded.",
    "host_loss_armed": "Host connection lost. Preserving your game locally; keep the game open.",
    "battle_running": "Multiplayer battle in progress.",
    "battle_finished": "Battle finished. Your party has been restored.",
    "battle_cancelled": "The challenge ended before the battle started. Your party is unchanged.",
    "battle_recovering": "Recovering the waiting battle. Keep the game open; every original player must reconnect.",
    "battle_recovery_held": "Battle recovery could not finish. Keep this game open, restore the host connection, then try Recover battle again.",
    "battle_recovery_not_ready": "This waiting battle cannot recover yet. Keep its original game window open.",
    "battle_recovered": "Battle finished after recovery. Your party is restored and saving is available again.",
    "host_service_restarting": "Restarting this world's host service. Keep every original game and launcher open.",
    "host_service_restarted": "Host service restarted. Keep original games open. Use Recover battle for a waiting battle, or Resolve interrupted trade to verify or cancel a waiting trade.",
    "host_restart_failed": "The host service is unavailable. Keep every original game open, restore the host configuration, then try Restart host service again.",
    "host_restart_not_ready": "Host restart requires the host's interrupted battle or prepared trade, with other operations finished.",
    "admission_canceling": "Canceling battle entry… Keep the game open until cancellation is verified.",
    "admission_canceled": "Battle entry canceled. Your party is unchanged and you can keep playing.",
    "admission_cleanup_held": "Battle entry could not be canceled safely. Keep the game open; reconnect to the host and try again when cancellation is available.",
    "admission_cleanup_unsupported": "This game version cannot safely cancel a paused battle entry. Keep the original game open for recovery.",
    "trade_running": "Trading. Choose your Pokemon and confirm the offer in the game.",
    "trade_finished": "Trade completed and saved.",
    "trade_cancelled": "Trade cancelled. Your saved party is unchanged.",
    "session_changed": "The host session changed. Keep the game open until its save or waiting interaction has a verified recovery outcome.",
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
    "imported": "Game installed. Choose Continue Adventure, or open My Worlds.",
    "import_unavailable": "Game import is unavailable: this development package has no release patch.",
    "wait_for_import": "Finishing the game import before closing…",
    "import_file": "The selected game dump or installed patch could not be read.",
    "import_size": "The selected file is not a supported game dump.",
    "source_mismatch": "This game dump does not match this release. Your original file was not changed.",
    "source_archive": "Choose a raw supported .gba dump or an unencrypted ZIP containing exactly one valid .gba file. The archive is never extracted or modified.",
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
    "connection_timed_out": "The connection check timed out. Ask the host to keep Host Game open, then check the address, game port and network path.",
    "connection_refused": "The connection to the game port was refused. Ask the host to start Host Game and check the invitation's port and network access.",
    "network_unavailable": "Your PC has no working route to the invited address. Check your network connection and whether this invitation is for LAN or Internet play.",
    "connection_blocked": "This PC's network permissions blocked the connection. Review its security settings with the host; nothing was changed automatically.",
    "invitation_ready": "Invitation checked. Review the connection details, then check the host connection or join.",
    "checking_invitation": "Checking the selected invitation and game version…",
    "details_copied": "Connection details copied. They contain no sign-in credential; give each friend their own invitation file separately.",
    "clipboard_unavailable": "The clipboard is unavailable. Read the connection address and port from this window instead.",
    "action_unavailable": "That action is not available yet. Wait for the current operation and check the recovery status.",
    "checking_installation": "Checking this installed game's pinned ROM, manifest and runtime files… No game or character is opened.",
    "installation_ready": "Installed game and runtime match this package's pins. This verifies files, not gameplay or network acceptance.",
    "installation_missing": "The installed game or required runtime file is missing. Import your own supported game if this package supplies a release patch.",
    "wait_for_installation_check": "Finishing the read-only installation check before closing…",
}


def status_text(code):
    """Never put exception text, credentials, endpoints or paths into status UI."""
    return _TEXT.get(code, _TEXT["session_failed"])


_RETAINS_GAME = frozenset({"host_loss_preserving", "host_loss_unsaved_held",
    "host_loss_battle_waiting", "host_loss_trade_waiting", "host_loss_armed", "game_recovery_held",
    "battle_recovering", "battle_recovery_held", "battle_recovery_not_ready",
    "host_service_restarting", "host_service_restarted", "host_restart_failed", "host_restart_not_ready",
    "admission_canceling", "admission_cleanup_held", "admission_cleanup_unsupported",
    "trade_recovery_checking", "trade_recovery_held"})


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
    graphics: str = "3d"  # which game to start: "3d" or "2d" (graphics_mode.py decides)
    route: tuple | None = None  # join only: (numeric address, port) to connect to instead of the invitation's own
    allow_enrollment: bool = True  # host only: whether friends may create their character over the network

    def options(self):
        if self.mode not in {"host", "join"} or not isinstance(self.selection, Path):
            raise ValueError("selection_required")
        if self.mode == "join":
            return {"invitation_path": self.selection, **({"server_route": self.route} if self.route is not None else {})}
        if not is_local_address(self.address, allow_lan=True) or type(self.internet) is not bool:
            raise ValueError("address_invalid")
        return dict(world_directory=self.selection.parent, bind_address=self.address,
                    host_route=self.address, public=self.internet,
                    **({} if self.allow_enrollment else {"allow_enrollment": False}))


@dataclass(frozen=True)
class UiEvent:
    kind: str
    code: str
    state: str = ""
    autosave_enabled: bool | None = None
    battle_recovery_available: bool = False
    admission_cleanup_available: bool = False
    is_host: bool = False
    host_restart_available: bool = False
    connected: bool = False
    revision: int | None = None
    connection_details: ConnectionDetails | None = None
    save_available: bool | None = None
    player_snapshot: dict | None = None
    championship_snapshot: dict | None = None
    championship_available: bool = False
    player_actions_available: bool = False
    battle_snapshot: dict | None = None
    archive_snapshot: dict | None = None
    reset_snapshot: dict | None = None
    trade_recovery_available: bool = False
    detail: str | None = None             # connection_diagnostics code behind a connection failure (describe() explains it)


class SessionWorker:
    """One session at a time; close requests never abandon live cleanup."""

    def __init__(self, installation, private_root, *, factory=LauncherSession, importer=None):
        self.installation, self.private_root, self.factory = installation, private_root, factory
        self._launch_installation = installation
        self.importer = importer
        self.importing = False
        self.checking_connection = False
        self.checking_installation = False
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
        self._battle_recovery_future = None
        self._battle_recovery_pending = self._battle_recovery_available = False
        self._trade_recovery_available = False
        self._admission_cleanup_available = False
        self._host_restart_future = None
        self._host_restart_pending = self._host_restart_available = False
        self._is_host = False
        self._player_snapshot_future = None
        self._player_snapshot_pending = False
        self._championship_future = None
        self._championship_pending = False

    @property
    def busy(self):
        return self._thread is not None and self._thread.is_alive()

    @property
    def holds_game(self):
        with self._lock:
            return self._battle_recovery_pending or self._host_restart_pending or self._status_code in _RETAINS_GAME

    def installation_for(self, graphics):
        """The installation whose runtime bundle returns the chosen game; the ROM,
        manifest and runtime pins are the same for both."""
        if graphics == "2d":
            return replace(self.installation, bundle=replace(self.installation.bundle, graphics="2d"))
        return self.installation

    def start(self, request):
        options = request.options()
        installation = self.installation_for(request.graphics)
        with self._lock:
            if self.busy:
                return False
            self._launch_installation = installation
            self._cancel_requested = False
            self._state = SessionState.NEW
            self._status_code = "new"
            self._is_host = request.mode == "host"
            self._thread = threading.Thread(target=self._run, args=(options,),
                                            name="emerald-launcher-session", daemon=False)
            start_thread(self._thread)
        return True

    def start_import(self, source):
        with self._lock:
            if self.busy or self.importer is None:
                return False
            self.importing = True
            self._state = SessionState.RUNNING
            self._thread = threading.Thread(target=self._run_import, args=(source,),
                                            name="emerald-game-import", daemon=False)
            start_thread(self._thread)
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

    def start_probe(self, invitation, *, inspect_only=False):
        with self._lock:
            if self.busy:
                return False
            self.checking_connection = True
            self._state = SessionState.RUNNING
            self._thread = threading.Thread(target=self._run_probe, args=(invitation, inspect_only),
                                            name="emerald-connection-check", daemon=False)
            start_thread(self._thread)
        return True

    def _run_probe(self, invitation, inspect_only=False):
        code = "unreachable"
        details = None
        try:
            from .network_diagnostics import inspect_invitation, probe_invitation
            expected_build = getattr(self.installation, "rom_sha256", None)
            if inspect_only:
                details = inspect_invitation(invitation, expected_build=expected_build)
                code = "invitation_ready"
            else:
                result = asyncio.run(probe_invitation(invitation, self.private_root / "network-checks",
                                                      expected_build=expected_build))
                details = result.details
                candidate = (result.code + "_" + result.route_scope if result.tls_verified
                             else result.failure_reason or result.code)
                code = candidate if candidate in _TEXT else "unreachable"
        except Exception as error:
            candidate = getattr(error, "code", "invalid_invitation")
            code = candidate if candidate in _TEXT else "invalid_invitation"
        finally:
            with self._lock:
                self.checking_connection = False
            self.events.put(UiEvent("complete", code, connection_details=details))

    def start_installation_check(self):
        with self._lock:
            if self.busy:
                return False
            self.checking_installation = True
            self._thread = threading.Thread(target=self._run_installation_check,
                                            name="emerald-installation-check", daemon=False)
            start_thread(self._thread)
            return True

    def _run_installation_check(self):
        code = "installation_changed"
        try:
            self.installation.verify()
            code = "installation_ready"
        except FileNotFoundError:
            code = "installation_missing"
        except Exception as error:
            candidate = getattr(error, "code", None)
            code = candidate if candidate in _TEXT else "installation_changed"
        finally:
            with self._lock:
                self.checking_installation = False
            self.events.put(UiEvent("complete", code))

    def request_player_snapshot(self, snapshot_id=None, action_id=None):
        if ((snapshot_id is None) != (action_id is None)
                or (snapshot_id is not None and (type(snapshot_id) is not str or type(action_id) is not str))):
            return False
        with self._lock:
            if (not self.busy or self._state is not SessionState.RUNNING or self._loop is None
                    or self._active_session is None or self._player_snapshot_pending
                    or self._save_pending or self._settings_pending or self._battle_recovery_pending
                    or self._host_restart_pending or self._championship_pending):
                return False
            current = self._active_session
            self._player_snapshot_pending = True
            self._loop.call_soon_threadsafe(self._begin_player_snapshot, current, snapshot_id, action_id)
            return True

    def _begin_player_snapshot(self, current, snapshot_id, action_id):
        self._player_snapshot_future = asyncio.create_task(
            self._read_player_snapshot(current, snapshot_id, action_id), name="launcher-player-action")

    async def _read_player_snapshot(self, current, snapshot_id, action_id):
        code, snapshot = "unavailable", None
        mutating = action_id is not None
        try:
            if current is not self._active_session:
                code = "connection_lost"
                return
            # Status + mutation + card/version fallback + fresh team status
            # each retain their normal five-second RPC bound.
            async with asyncio.timeout(30):
                snapshot = await current.player_panel_action(snapshot_id, action_id)
            if current is self._active_session:
                code = "ready"
            else:
                snapshot = None
                code = "uncertain" if mutating else "connection_lost"
        except asyncio.TimeoutError:
            code = "uncertain" if mutating else "unavailable"
        except asyncio.CancelledError:
            code = "uncertain" if mutating else "connection_lost"
            raise
        except Exception as error:
            candidate = getattr(error, "code", None)
            code = candidate if candidate in {"unsupported", "teams_unsupported", "unavailable", "connection_lost",
                "peer_offline", "stale", "busy", "not_ready", "uncertain", "applied_refresh_required", "refused"} else (
                "uncertain" if mutating else "unavailable")
        finally:
            with self._lock:
                self._player_snapshot_pending = False
            self.events.put(UiEvent("player_snapshot", code, player_snapshot=snapshot))

    def request_battle_panel(self, snapshot_id=None, action_id=None):
        if ((snapshot_id is None) != (action_id is None)
                or snapshot_id is not None and (type(snapshot_id) is not str or type(action_id) is not str)):
            return False
        return self._request_player_extension("battle_panel", (snapshot_id, action_id), action_id is not None)

    def request_reset_panel(self, snapshot_id=None, action_id=None):
        if ((snapshot_id is None) != (action_id is None)
                or snapshot_id is not None and (type(snapshot_id) is not str or type(action_id) is not str)):
            return False
        return self._request_player_extension("reset_panel", (snapshot_id, action_id), action_id is not None)

    def request_record_archive(self, kind, filters=None, snapshot_id=None, action_id=None):
        from copy import deepcopy
        if (kind not in {"battle", "hunt", "trade"} or (snapshot_id is None) != (action_id is None)
                or snapshot_id is not None and (type(snapshot_id) is not str or type(action_id) is not str)
                or filters is not None and type(filters) is not dict):
            return False
        return self._request_player_extension("record_archive", (kind, deepcopy(filters), snapshot_id, action_id), False)

    def _request_player_extension(self, kind, arguments, mutating):
        # Reuse the player-action lane, so saves, recovery, settings and bracket
        # actions retain the existing exclusion and completion-drain fences.
        with self._lock:
            if (not self.busy or self._state is not SessionState.RUNNING or self._loop is None
                    or self._active_session is None or self._player_snapshot_pending
                    or self._save_pending or self._settings_pending or self._battle_recovery_pending
                    or self._host_restart_pending or self._championship_pending):
                return False
            current = self._active_session
            self._player_snapshot_pending = True
            self._loop.call_soon_threadsafe(self._begin_player_extension, current, kind, arguments, mutating)
            return True

    def _begin_player_extension(self, current, kind, arguments, mutating):
        self._player_snapshot_future = asyncio.create_task(
            self._player_extension(current, kind, arguments, mutating), name="launcher-" + kind)

    async def _player_extension(self, current, kind, arguments, mutating):
        code, snapshot = "unavailable", None
        try:
            if current is not self._active_session:
                code = "connection_lost"
                return
            async with asyncio.timeout(12 if kind == "record_archive" else 30):
                method = {"battle_panel": current.battle_panel_action, "record_archive": current.record_archive_action,
                          "reset_panel": current.reset_panel_action}[kind]
                snapshot = await method(*arguments)
            if current is not self._active_session:
                snapshot = None
                code = "uncertain" if mutating else "connection_lost"
            else:
                code = "ready"
        except asyncio.CancelledError:
            code = "uncertain" if mutating else "connection_lost"
            raise
        except Exception as error:
            candidate = getattr(error, "code", None)
            code = candidate if candidate in {"unsupported", "unavailable", "connection_lost", "uncertain",
                "stale", "roster_changed", "busy", "not_ready", "refused", "native_required",
                "applied_refresh_required", "invalid_filter", "battle_archive_unsupported", "reset_history_unsupported", "trade_archive_unsupported"} else (
                    "uncertain" if mutating else "unavailable")
        finally:
            with self._lock:
                self._player_snapshot_pending = False
            fields = {{"battle_panel": "battle_snapshot", "record_archive": "archive_snapshot", "reset_panel": "reset_snapshot"}[kind]: snapshot}
            self.events.put(UiEvent(kind, code, **fields))

    def request_championship(self, snapshot_id=None, action_id=None):
        if ((snapshot_id is None) != (action_id is None)
                or (snapshot_id is not None and (type(snapshot_id) is not str or type(action_id) is not str))):
            return False
        with self._lock:
            if (not self.busy or self._state is not SessionState.RUNNING or self._loop is None
                    or self._active_session is None or self._championship_pending
                    or self._player_snapshot_pending or self._save_pending or self._settings_pending
                    or self._battle_recovery_pending or self._host_restart_pending):
                return False
            current = self._active_session
            self._championship_pending = True
            self._loop.call_soon_threadsafe(self._begin_championship, current, snapshot_id, action_id)
            return True

    def _begin_championship(self, current, snapshot_id, action_id):
        self._championship_future = asyncio.create_task(
            self._championship(current, snapshot_id, action_id), name="launcher-championship-action")

    async def _championship(self, current, snapshot_id, action_id):
        code, snapshot = "unavailable", None
        mutating = action_id is not None
        try:
            if current is not self._active_session:
                code = "connection_lost"
                return
            async with asyncio.timeout(12):
                snapshot = await current.championship_action(snapshot_id, action_id)
            if current is self._active_session:
                code = "ready"
            else:
                snapshot = None
                code = "uncertain" if mutating else "connection_lost"
        except asyncio.TimeoutError:
            code = "uncertain" if mutating else "unavailable"
        except asyncio.CancelledError:
            code = "uncertain" if mutating else "connection_lost"
            raise
        except Exception as error:
            candidate = getattr(error, "code", None)
            code = candidate if candidate in {"unsupported", "unavailable", "connection_lost", "uncertain",
                "stale", "roster_changed", "busy", "cancel_pending", "not_ready", "refused"} else "unavailable"
        finally:
            with self._lock:
                self._championship_pending = False
            self.events.put(UiEvent("championship", code, championship_snapshot=snapshot))

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
                    or self._active_session is None or self._save_pending or self._battle_recovery_pending
                    or self._host_restart_pending or self._championship_pending or self._player_snapshot_pending):
                return False
            self._save_pending = True
            self._loop.call_soon_threadsafe(self._begin_save)
            return True

    def _begin_save(self):
        self._save_future = asyncio.create_task(self._save(), name="launcher-save-action")

    def _report_running_error(self, code):
        # An action error must not erase the host identity or recovery actions
        # until another unrelated status change happens to reach the window.
        current = self._active_session
        status = current.status if current is not None else None
        self.events.put(UiEvent("status", code, "running",
            getattr(status, "autosave_enabled", None),
            getattr(status, "battle_recovery_available", False),
            getattr(status, "admission_cleanup_available", False),
            getattr(status, "is_host", self._is_host),
            getattr(status, "host_restart_available", False),
            connected=getattr(status, "connected", False), revision=getattr(status, "revision", None),
            connection_details=getattr(status, "connection_details", None),
            save_available=getattr(status, "save_available", None),
            championship_available=getattr(status, "championship_available", False),
            player_actions_available=getattr(status, "player_actions_available", False),
            trade_recovery_available=getattr(status, "trade_recovery_available", False)))

    async def _save(self):
        try:
            if self._active_session is None:
                return
            await self._active_session.save()
        except Exception as error:
            code = getattr(error, "code", "save_recovery_required")
            self._report_running_error(code if code in _TEXT else "save_recovery_required")
        finally:
            with self._lock:
                self._save_pending = False

    def request_autosave(self, enabled):
        with self._lock:
            if (type(enabled) is not bool or not self.busy or self._state is not SessionState.RUNNING
                    or self._loop is None or self._active_session is None or self._settings_pending
                    or self._battle_recovery_pending or self._host_restart_pending or self._championship_pending
                    or self._player_snapshot_pending):
                return False
            self._settings_pending = True
            self._loop.call_soon_threadsafe(self._begin_settings, enabled)
            return True

    def request_battle_recovery(self):
        with self._lock:
            if (not self.busy or self._state is not SessionState.RUNNING or self._loop is None
                    or self._active_session is None or not self._battle_recovery_available
                    or self._battle_recovery_pending or self._save_pending or self._settings_pending
                    or self._host_restart_pending or self._championship_pending or self._player_snapshot_pending):
                return False
            self._battle_recovery_pending = True
            self._loop.call_soon_threadsafe(self._begin_battle_recovery)
            return True

    def _begin_battle_recovery(self):
        self._battle_recovery_future = asyncio.create_task(self._recover_battle(), name="launcher-battle-recovery-action")

    def request_battle_entry_cancel(self):
        with self._lock:
            if (not self.busy or self._state is not SessionState.RUNNING or self._loop is None
                    or self._active_session is None or not self._admission_cleanup_available
                    or self._battle_recovery_pending or self._save_pending or self._settings_pending
                    or self._host_restart_pending or self._championship_pending or self._player_snapshot_pending):
                return False
            # Both actions own the retained core and share the same drain fence.
            self._battle_recovery_pending = True
            self._loop.call_soon_threadsafe(self._begin_battle_entry_cancel)
            return True

    def _begin_battle_entry_cancel(self):
        self._battle_recovery_future = asyncio.create_task(self._cancel_battle_entry(),
                                                          name="launcher-battle-entry-cancel-action")

    async def _cancel_battle_entry(self):
        try:
            if self._active_session is not None:
                await self._active_session.cancel_battle_entry()
        except Exception as error:
            code = ("admission_cleanup_unsupported" if getattr(error, "code", None)
                    == "admission_cleanup_unsupported" else "admission_cleanup_held")
            with self._lock:
                self._status_code = code
                self._admission_cleanup_available = self._battle_recovery_available = False
            self._report_running_error(code)
        finally:
            with self._lock:
                self._battle_recovery_pending = False

    async def _recover_battle(self):
        try:
            if self._active_session is not None:
                await self._active_session.recover_battle()
        except Exception:
            # A failed operation never suggests closing the retained core or
            # exposes private transport/store exception text in the window.
            self._report_running_error("battle_recovery_held")
        finally:
            with self._lock:
                self._battle_recovery_pending = False

    def request_host_restart(self):
        with self._lock:
            if (not self.busy or self._state is not SessionState.RUNNING or self._loop is None
                    or self._active_session is None or not self._is_host or not self._host_restart_available
                    or self._host_restart_pending or self._battle_recovery_pending
                    or self._save_pending or self._settings_pending or self._championship_pending or self._player_snapshot_pending):
                return False
            self._host_restart_pending = True
            self._loop.call_soon_threadsafe(self._begin_host_restart)
            return True

    def _begin_host_restart(self):
        self._host_restart_future = asyncio.create_task(self._restart_host_service(),
                                                       name="launcher-host-restart-action")

    def request_trade_recovery(self):
        # Reuse the existing exclusive recovery lane and its cleanup draining.
        with self._lock:
            if (not self.busy or self._state is not SessionState.RUNNING or self._loop is None
                    or self._active_session is None or not self._trade_recovery_available
                    or self._host_restart_pending or self._battle_recovery_pending
                    or self._save_pending or self._settings_pending or self._championship_pending or self._player_snapshot_pending):
                return False
            self._battle_recovery_pending = True
            self._loop.call_soon_threadsafe(self._begin_trade_recovery)
            return True

    def _begin_trade_recovery(self):
        self._battle_recovery_future = asyncio.create_task(self._recover_trade(), name="launcher-trade-close-review")

    async def _recover_trade(self):
        try:
            if self._active_session is not None:
                await self._active_session.prepare_trade_recovery()
        except Exception:
            self._report_running_error("trade_recovery_held")
        finally:
            with self._lock:
                self._battle_recovery_pending = False

    async def _restart_host_service(self):
        try:
            if self._active_session is not None:
                await self._active_session.restart_host_service()
        except Exception as error:
            code = "host_restart_not_ready" if getattr(error, "code", None) == "host_restart_not_ready" else "host_restart_failed"
            self._report_running_error(code)
        finally:
            with self._lock:
                self._host_restart_pending = False

    def _begin_settings(self, enabled):
        self._settings_future = asyncio.create_task(self._set_autosave(enabled), name="launcher-autosave-setting")

    async def _set_autosave(self, enabled):
        try:
            if self._active_session is not None:
                await self._active_session.set_autosave_enabled(enabled)
        except Exception as error:
            code = getattr(error, "code", "settings_unavailable")
            self._report_running_error(code if code in _TEXT else "settings_unavailable")
        finally:
            with self._lock:
                self._settings_pending = False

    def _publish(self, status):
        with self._lock:
            self._state = status.state
            self._status_code = status.code
            self._battle_recovery_available = getattr(status, "battle_recovery_available", False)
            self._admission_cleanup_available = getattr(status, "admission_cleanup_available", False)
            self._is_host = getattr(status, "is_host", False)
            self._host_restart_available = getattr(status, "host_restart_available", False)
            self._trade_recovery_available = getattr(status, "trade_recovery_available", False)
        if status.state != SessionState.CLOSED:
            code = status.code if status.code in _TEXT else "session_failed"
            self.events.put(UiEvent("status", code, status.state.value, status.autosave_enabled,
                                   self._battle_recovery_available, self._admission_cleanup_available,
                                   self._is_host, self._host_restart_available,
                                   connected=getattr(status, "connected", False), revision=getattr(status, "revision", None),
                                   connection_details=getattr(status, "connection_details", None),
                                   save_available=getattr(status, "save_available", None),
                                   championship_available=getattr(status, "championship_available", False),
                                   player_actions_available=getattr(status, "player_actions_available", False),
                                   trade_recovery_available=self._trade_recovery_available,
                                   detail=getattr(status, "detail", None)))

    async def _session(self, options):
        session = self.factory(self._launch_installation, self.private_root, on_status=self._publish, **options)
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
                    signature = (status.state, status.code, status.connected, status.autosave_enabled,
                                 getattr(status, "battle_recovery_available", False),
                                 getattr(status, "admission_cleanup_available", False),
                                 getattr(status, "is_host", False),
                                 getattr(status, "host_restart_available", False),
                                 getattr(status, "save_available", None), getattr(status, "revision", None),
                                 getattr(status, "championship_available", False),
                                 getattr(status, "player_actions_available", False),
                                 getattr(status, "trade_recovery_available", False))
                    if signature != observed:
                        self._publish(status)
                        observed = signature
                    await asyncio.wait({play}, timeout=.2)
                exit_code = await play
                if session.status.code == "save_recovery_required":
                    return "save_recovery_required"
                if exit_code == 0 and session.status.code == "trade_recovery_reopen":
                    return "trade_recovery_reopen"
                if exit_code == EXIT_GRAPHICS_UNAVAILABLE:
                    return "graphics_failed"  # the game showed its own message first
                return "game_closed" if exit_code == 0 else "session_failed"
            finally:
                if not play.done():
                    play.cancel()
                await asyncio.gather(play, return_exceptions=True)
                with self._lock:
                    self._active_session = None
                canceled = False
                if self._championship_future is not None:
                    from .player_runtime import _finish_even_if_cancelled
                    _, interrupted = await _finish_even_if_cancelled(
                        asyncio.gather(self._championship_future, return_exceptions=True))
                    canceled |= interrupted
                if self._player_snapshot_future is not None:
                    from .player_runtime import _finish_even_if_cancelled
                    _, interrupted = await _finish_even_if_cancelled(
                        asyncio.gather(self._player_snapshot_future, return_exceptions=True))
                    canceled |= interrupted
                if self._battle_recovery_future is not None:
                    from .player_runtime import _finish_even_if_cancelled
                    _, interrupted = await _finish_even_if_cancelled(
                        asyncio.gather(self._battle_recovery_future, return_exceptions=True))
                    canceled |= interrupted
                if self._host_restart_future is not None:
                    from .player_runtime import _finish_even_if_cancelled
                    _, interrupted = await _finish_even_if_cancelled(
                        asyncio.gather(self._host_restart_future, return_exceptions=True))
                    canceled |= interrupted
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
        detail = None
        try:
            code = asyncio.run(self._execute(options))
        except asyncio.CancelledError:
            code = "cancelled"
        except Exception as error:
            candidate = getattr(error, "code", None)
            code = candidate if candidate in _TEXT else "session_failed"
            reason = getattr(error, "reason", None)
            detail = reason if type(reason) is str and len(reason) <= 64 else None
        finally:
            with self._lock:
                self._loop = self._task = None
                self._active_session = self._save_future = None
                self._save_pending = False
                self._settings_future = None
                self._settings_pending = False
                self._battle_recovery_future = None
                self._battle_recovery_pending = self._battle_recovery_available = False
                self._trade_recovery_available = False
                self._admission_cleanup_available = False
                self._host_restart_future = None
                self._host_restart_pending = self._host_restart_available = False
                self._is_host = False
                self._player_snapshot_future = None
                self._player_snapshot_pending = False
                self._championship_future = None
                self._championship_pending = False
            # asyncio.run has drained its loop before completion becomes visible.
            self.events.put(UiEvent("complete", code, detail=detail))


class LauncherWindow:
    def __init__(self, root, worker=None, *, version="Development preview"):
        import tkinter as tk
        from tkinter import ttk

        self.root, self.worker = root, worker
        from .launcher_display import DisplayPreferences
        self.display_preferences = DisplayPreferences(getattr(worker, "private_root", None))
        from .launcher_graphics import GraphicsGate
        self.graphics_preference = GraphicsPreference(getattr(worker, "private_root", None))
        self.graphics_gate = GraphicsGate(
            root, self.graphics_preference, lambda: self.worker.installation.bundle,
            message=lambda code: self.message.set(status_text(code)), busy=lambda value: self._enable(not value))
        from .launcher_recent import RecentStore
        self.recent = RecentStore(getattr(worker, "private_root", None))
        self.worlds = []
        self._scanning = False
        self._scan_results = queue.Queue()
        self.closing = False
        self.setup_window = None
        self.close_after_setup = False
        self.selection = {"host": None, "join": None}
        self.connection_details = {"host": None, "join": None}
        self.detail_labels, self.detail_feedback, self.copy_buttons = {}, {}, {}
        self.controls = []
        self.version = version
        root.title("Emerald Together")
        root.minsize(700, 680)
        root.geometry("800x780")
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.report_callback_exception = lambda *_: self.message.set(status_text("session_failed"))
        from .launcher_display import scrollable_frame
        from .launcher_menu import ConfirmBar, MainMenu, PageHeader, apply_theme
        apply_theme(root)
        self.message = tk.StringVar(value=status_text("idle" if worker else "package_missing"))
        # One status line under every page: what the launcher is doing, or why it refused.
        bottom = ttk.Frame(root)
        bottom.pack(side="bottom", fill="x")
        ttk.Separator(bottom).pack(fill="x")
        self.status_label = ttk.Label(bottom, textvariable=self.message, wraplength=730, padding=(24, 8))
        self.status_label.pack(fill="x", anchor="w")
        self.stack = ttk.Frame(root)
        self.stack.pack(fill="both", expand=True)
        self.views, self.page_headers = {}, {}
        self.current_view = "home"

        def view(name, title):
            frame = ttk.Frame(self.stack)
            frame.place(relx=0, rely=0, relwidth=1, relheight=1)
            self.views[name] = frame
            self.page_headers[name] = PageHeader(frame, title, self.go_home)
            return frame

        # ---- Main menu
        self.menu = MainMenu(self.stack, {
            "continue": self.continue_adventure, "worlds": lambda: self.show_view("worlds"), "host": lambda: self.show_view("host"),
            "join": lambda: self.show_view("join"), "settings": lambda: self.show_view("settings"), "exit": self.exit_game},
            version=version)
        self.menu.frame.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.views["home"] = self.menu.frame

        # ---- My Worlds
        worlds = view("worlds", "My Worlds")
        page = ttk.Frame(worlds, padding=(24, 16))
        page.pack(fill="both", expand=True)
        ttk.Label(page, text=("Each world holds up to four characters: the host's and three friends'. Choose one to host or set up, "
                              "or create a new one. Worlds and characters stay on this PC; nothing here deletes or changes them."),
                  wraplength=700, style="Muted.TLabel").pack(anchor="w", pady=(0, 10))
        columns = ("players", "status")
        tree = ttk.Treeview(page, columns=columns, height=7, selectmode="browse")
        tree.heading("#0", text="World")
        tree.heading("players", text="Players")
        tree.heading("status", text="Status / last played")
        tree.column("#0", width=300)
        tree.column("players", width=70, anchor="center")
        tree.column("status", width=250)
        tree.pack(fill="x")
        tree.bind("<<TreeviewSelect>>", lambda _: self._world_selected())
        tree.bind("<Double-1>", lambda _: self.host_selected_world())
        self.world_tree = tree
        self.world_empty = ttk.Label(page, text="", wraplength=700, style="Muted.TLabel")
        self.world_empty.pack(anchor="w", pady=(6, 8))
        row = ttk.Frame(page)
        row.pack(fill="x", pady=(4, 0))
        self.world_host_button = ttk.Button(row, text="Host this world", style="Accent.TButton", command=self.host_selected_world,
                                            state="disabled")
        self.world_host_button.pack(side="left")
        self.world_setup_button = ttk.Button(row, text="Set up characters…", state="disabled",
                                             command=lambda: self.open_setup(world=self._selected_world()))
        self.world_setup_button.pack(side="left", padx=8)
        self.world_new_button = ttk.Button(row, text="Create a new world…", command=lambda: self.open_setup(role="host"))
        self.world_new_button.pack(side="left")
        self.setup_button = self.world_new_button
        self.controls.append(self.world_new_button)
        row = ttk.Frame(page)
        row.pack(fill="x", pady=(8, 0))
        self.world_friend_button = ttk.Button(row, text="Prepare a character to join a friend…", command=lambda: self.open_setup(role="friend"))
        self.world_friend_button.pack(side="left")
        self.controls.append(self.world_friend_button)
        browse_world = ttk.Button(row, text="Choose a world file…", command=lambda: self.browse("host", then="worlds"))
        browse_world.pack(side="left", padx=8)
        self.controls.append(browse_world)
        ttk.Button(row, text="Refresh", command=self._rescan_worlds).pack(side="left")
        ttk.Label(page, wraplength=700, style="Muted.TLabel", text=(
            "New characters are made in the game itself (New Game, choose a starter, Save), then the host approves them. "
            "Setup walks you through each step and keeps your original saves untouched.")).pack(anchor="w", pady=(16, 0))
        self.setup_view = view("setup", "World & character setup")
        self.setup_host = ttk.Frame(self.setup_view)
        self.setup_host.pack(fill="both", expand=True)

        # ---- Host Multiplayer and Join Friend
        self.address = tk.StringVar(value="127.0.0.1")
        self.internet = tk.BooleanVar(value=False)
        for mode, title, description in (
            ("host", "Host Multiplayer", "Start one of your worlds on this PC. Friends join it with their own invitation files."),
            ("join", "Join Friend", "Open the personal invitation file your host gave you, then join their world."),
        ):
            frame = view(mode, title)
            container = ttk.Frame(frame)
            container.pack(fill="both", expand=True)
            page = scrollable_frame(container, padding=24)
            ttk.Label(page, text=description, wraplength=700).pack(anchor="w", pady=(0, 12))
            label = tk.StringVar(value="No world selected" if mode == "host" else "No invitation selected")
            setattr(self, mode + "_label", label)
            if mode == "host":
                ttk.Label(page, text="World").pack(anchor="w")
                self.host_choice = tk.StringVar()
                chooser = ttk.Combobox(page, textvariable=self.host_choice, state="readonly", width=58, values=())
                chooser.pack(anchor="w", pady=(4, 4))
                chooser.bind("<<ComboboxSelected>>", lambda _: self._host_choice_changed())
                self.host_chooser = chooser
                self.controls.append(chooser)
                browse = ttk.Button(page, text="Choose a world file…", command=lambda: self.browse("host"))
                browse.pack(anchor="w")
                self.controls.append(browse)
                ttk.Label(page, textvariable=label, wraplength=700, style="Muted.TLabel").pack(anchor="w", pady=(6, 14))
                ttk.Label(page, text="Host address on this PC").pack(anchor="w")
                addr_row = ttk.Frame(page)
                addr_row.pack(anchor="w", pady=(4, 5))
                address = ttk.Entry(addr_row, textvariable=self.address, width=32)
                address.pack(side="left")
                self.controls.append(address)
                lan = ttk.Button(addr_row, text="Use this PC's network address", command=self.use_lan_address)
                lan.pack(side="left", padx=8)
                self.controls.append(lan)
                ttk.Label(page, text="Use your Wi-Fi/LAN address for friends on your network.\n127.0.0.1 is for this PC only (playing alone).",
                          wraplength=700, style="Muted.TLabel").pack(anchor="w")
                internet = ttk.Checkbutton(page, text="Allow Internet connections", variable=self.internet)
                internet.pack(anchor="w", pady=(10, 0))
                self.controls.append(internet)
                ttk.Label(page, wraplength=700, style="Muted.TLabel", text=(
                    "Internet play needs your router to forward the game's TCP port to this PC and your firewall to allow it, and the "
                    "invitation must carry your public address. This launcher does not set up port forwarding and there is no relay "
                    "server: friends outside your network cannot connect until you do that.")).pack(anchor="w", pady=(2, 0))
                self.host_confirm = ConfirmBar(page)
            else:
                browse = ttk.Button(page, text="Choose invitation…", command=lambda: self.browse("join"))
                browse.pack(anchor="w")
                self.controls.append(browse)
                ttk.Label(page, textvariable=label, wraplength=700, style="Muted.TLabel").pack(anchor="w", pady=(6, 8))
                ttk.Label(page, text="Recent invitations").pack(anchor="w")
                self.recent_choice = tk.StringVar()
                recent = ttk.Combobox(page, textvariable=self.recent_choice, state="readonly", width=58, values=())
                recent.pack(anchor="w", pady=(4, 8))
                recent.bind("<<ComboboxSelected>>", lambda _: self._recent_invitation_changed())
                self.recent_chooser = recent
                self.controls.append(recent)
                ttk.Label(page, wraplength=700, style="Muted.TLabel", text=(
                    "Your invitation file supplies the host's address and your character. Keep it private; each friend has their own. "
                    "This version joins by invitation file only: there are no invite codes and no automatic discovery of games.")).pack(anchor="w", pady=(0, 10))
                probe = ttk.Button(page, text="Check connection", command=self.check_connection)
                probe.pack(anchor="w", pady=(0, 4))
                self.controls.append(probe)
            action = ttk.Button(page, text="Host Game" if mode == "host" else "Join Game", style="Accent.TButton",
                                command=(self.begin_host if mode == "host" else lambda: self.start("join")))
            action.pack(anchor="w", pady=(16, 0))
            setattr(self, mode + "_button", action)
            self.controls.append(action)
            details = tk.StringVar(value="Connection details will appear after checking the invitation or opening the host world.")
            self.detail_labels[mode] = details
            ttk.Label(page, textvariable=details, wraplength=700).pack(anchor="w", pady=(12, 4))
            copy_button = ttk.Button(page, text="Copy connection details", state="disabled",
                                     command=lambda m=mode: self.copy_connection_details(m))
            copy_button.pack(anchor="w")
            self.copy_buttons[mode] = copy_button
            self.detail_feedback[mode] = tk.StringVar()
            ttk.Label(page, textvariable=self.detail_feedback[mode], wraplength=700).pack(anchor="w", pady=(4, 0))

        # ---- Settings
        settings = view("settings", "Settings")
        self.settings_tabs = ttk.Notebook(settings)
        self.settings_tabs.pack(fill="both", expand=True, padx=16, pady=12)
        self.settings_pages = {}
        for key, text in (("display", "Display & graphics"), ("audio", "Audio"), ("keys", "Game keys"), ("files", "Game files"),
                          ("launcher", "Launcher")):
            holder = ttk.Frame(self.settings_tabs)
            self.settings_tabs.add(holder, text=text)
            self.settings_pages[key] = holder
        files = scrollable_frame(self.settings_pages["files"], padding=24)
        ttk.Label(files, text="Install your own game once", style="Heading.TLabel").pack(anchor="w", pady=(0, 6))
        self.import_button = ttk.Button(files, text="Import my game…", command=self.import_game)
        self.import_button.pack(anchor="w", pady=(0, 6))
        self.installation_button = ttk.Button(files, text="Check installed game files", command=self.check_installation)
        self.installation_button.pack(anchor="w", pady=(0, 6))
        self.controls.append(self.installation_button)
        if getattr(worker, "importer", None) is None:
            self.import_button.configure(state="disabled")
            ttk.Label(files, text=status_text("import_unavailable"), wraplength=680).pack(anchor="w", pady=(0, 12))
        else:
            ttk.Label(files, text="Select your own game dump once to install this release.", wraplength=680).pack(anchor="w", pady=(0, 12))
        self.game_state = tk.StringVar()
        ttk.Label(files, textvariable=self.game_state, wraplength=680, style="Muted.TLabel").pack(anchor="w")
        launcher = scrollable_frame(self.settings_pages["launcher"], padding=24)
        ttk.Label(launcher, text="Launcher text size", style="Heading.TLabel").pack(anchor="w", pady=(0, 6))
        size = tk.StringVar(value=self.display_preferences.value["text_size"])
        choice = ttk.Combobox(launcher, textvariable=size, values=("Standard", "Larger", "Largest"), state="readonly", width=12)
        choice.pack(anchor="w")
        size_feedback = tk.StringVar()
        choice.bind("<<ComboboxSelected>>", lambda _: size_feedback.set(
            "Saved locally." if self.set_text_size(size.get()) else "Applied for this window; existing preference file retained."))
        ttk.Label(launcher, textvariable=size_feedback).pack(anchor="w", pady=(4, 12))
        ttk.Button(launcher, text="Controls & connection help", command=self.show_help).pack(anchor="w")

        # ---- The running game: status, saving and recovery (the earlier launcher window's lower half)
        session = view("session", "Your game")
        self.session_view = session
        body = ttk.Frame(session, padding=(24, 12))
        body.pack(fill="both", expand=True)
        footer = ttk.Frame(body)
        footer.pack(side="bottom", fill="x")
        tabs = ttk.Notebook(body)
        tabs.pack(fill="both", expand=True)
        self.tabs = tabs
        from .launcher_player_panel import PlayerPanel
        player_page = ttk.Frame(tabs, padding=20)
        tabs.add(player_page, text="Trainer Card & Players")
        self.player_panel = PlayerPanel(player_page, worker, preferences=self.display_preferences)
        from .launcher_battle_panel import BattlePanel
        battle_page = ttk.Frame(tabs, padding=8)
        tabs.add(battle_page, text="Challenges")
        self.battle_panel = BattlePanel(battle_page, worker)
        from .launcher_record_archive import RecordArchivePanel
        archive_page = ttk.Frame(tabs, padding=8)
        tabs.add(archive_page, text="Archive")
        self.archive_panel = RecordArchivePanel(archive_page, worker)
        from .launcher_reset_panel import ResetPanel
        reset_page = ttk.Frame(tabs, padding=8)
        tabs.add(reset_page, text="Local Reset")
        self.reset_panel = ResetPanel(reset_page, worker)
        from .launcher_championship_panel import ChampionshipPanel
        championship_page = ttk.Frame(tabs, padding=8)
        tabs.add(championship_page, text="Championship")
        self.championship_panel = ChampionshipPanel(championship_page, worker)
        ttk.Separator(footer).pack(fill="x", pady=(10, 8))
        self.connection_state = tk.StringVar(value="Host connection: not connected")
        self.checkpoint_state = tk.StringVar(value="Host checkpoint: not yet opened")
        ttk.Label(footer, textvariable=self.connection_state).pack(anchor="w")
        ttk.Label(footer, textvariable=self.checkpoint_state).pack(anchor="w", pady=(0, 6))
        actions = ttk.Frame(footer)
        actions.pack(fill="x", pady=(4, 0))
        self.save_button = ttk.Button(actions, text="Save now", command=self.save_now, state="disabled")
        self.save_button.pack(side="left")
        self.autosave_value = tk.BooleanVar(value=True)
        self._autosave_observed = True
        self.autosave_button = ttk.Checkbutton(actions, text="Autosave every 5 minutes",
            variable=self.autosave_value, command=self.toggle_autosave, state="disabled")
        self.autosave_button.pack(side="left", padx=(12, 0))
        battle_actions = ttk.Frame(footer)
        battle_actions.pack(fill="x", pady=(8, 0))
        self.recover_battle_button = ttk.Button(battle_actions, text="Recover battle", command=self.recover_battle,
                                              state="disabled")
        self.recover_battle_button.pack(side="left")
        self.cancel_battle_entry_button = ttk.Button(battle_actions, text="Cancel battle entry",
            command=self.cancel_battle_entry, state="disabled")
        self.cancel_battle_entry_button.pack(side="left", padx=(12, 0))
        trade_actions = ttk.Frame(footer)
        trade_actions.pack(fill="x", pady=(8, 0))
        self.recover_trade_button = ttk.Button(trade_actions, text="Resolve interrupted trade",
            command=self.recover_trade, state="disabled")
        self.recover_trade_button.pack(side="left")
        self.restart_host_button = ttk.Button(battle_actions, text="Restart host service",
            command=self.restart_host_service, state="disabled")
        # Only a running host session displays this action. Joining players
        # restore their original core with Recover battle after the host returns.
        self.cancel = ttk.Button(actions, text="Cancel startup", command=self.cancel_startup, state="disabled")
        self.cancel.pack(side="right")
        ttk.Button(footer, text="Controls & connection help", command=self.show_help).pack(anchor="e", pady=(8, 0))

        self._apply_text_size(self.display_preferences.value["text_size"])
        root.bind("<F1>", lambda _: self.show_help())
        root.bind("<Escape>", lambda _: self._escape())
        root.bind("<Control-plus>", lambda _: self.change_text_size(1))
        root.bind("<Control-equal>", lambda _: self.change_text_size(1))
        root.bind("<Control-minus>", lambda _: self.change_text_size(-1))
        root.bind("<Control-0>", lambda _: self.set_text_size("Standard"))
        if worker is None:
            self._enable(False)
        self.show_view("home")
        self._rescan_worlds()      # so Continue Adventure can name the world it will start
        self._poll_id = root.after(80, self.poll)

    # ------------------------------------------------------------------ the main menu's pages

    def _can_leave(self):
        """Back to the main menu: never while a game or a startup is running, a setup is open, or the window is closing."""
        return not self.closing and self.setup_window is None and not (self.worker is not None and self.worker.busy)

    def _update_back_buttons(self):
        for header in self.page_headers.values():
            header.set_back_enabled(self._can_leave())

    def show_view(self, name):
        if name not in self.views:
            raise ValueError(name)
        self.current_view = name
        self.views[name].tkraise()
        if name == "home":
            self._refresh_home()
            self.menu.focus_first()
        elif name in {"worlds", "host"}:
            self._refresh_world_lists()
            self._rescan_worlds(force=False)
        elif name == "join":
            self._refresh_recent_invitations()
        elif name == "settings":
            self._refresh_settings()
        self._update_back_buttons()

    def go_home(self):
        if not self._can_leave():
            if self.worker is not None and self.worker.busy:
                self.message.set(status_text("back_busy"))
            return
        self.show_view("home")

    def _escape(self):
        if self.current_view == "home":
            if self.menu.confirm.visible:
                self.menu.confirm.cancel()
            return
        if self.current_view == "host" and self.host_confirm.visible:
            self.host_confirm.cancel()
            return
        if self.current_view == "setup":
            return      # leaving setup goes through its own button, which finishes or cancels what it is doing
        self.go_home()

    def _game_installed(self):
        installation = getattr(self.worker, "installation", None)
        rom = getattr(installation, "rom_path", None)
        try:
            return rom is not None and Path(rom).is_file()
        except OSError:
            return False

    def _refresh_home(self):
        from .launcher_recent import continue_target, describe_age
        import time
        card = self.menu.cards["continue"]
        banner = None
        if self.worker is None:
            banner = status_text("package_missing")
        elif not self._game_installed():
            banner = status_text("game_not_installed")
        target, reason = continue_target(self.recent)
        if self.worker is not None and not self._game_installed():
            # First launch: the one thing to do is install your own game, so the top choice takes you there
            card.set("Set Up Your Game", "Your game is not installed on this PC yet. Import your own game once, then play.", True)
        elif banner is not None or target is None:
            subtitle = {"none": "Nothing to continue yet. Create or choose a world in My Worlds, or join a friend.",
                        "missing": "The world or invitation you last played has moved or been deleted. Choose one in My Worlds."
                        }.get(reason, "")
            if banner is not None and reason == "":
                subtitle = ""
            card.set("Continue Adventure", subtitle or "Install your game first (Settings, Game files).", False)
        else:
            when = describe_age(target.played, time.time())
            if target.mode == "host":
                entry = next((w for w in self.worlds if w.host_json == target.selection), None)
                name = entry.title if entry is not None else "your last world"
                card.set("Continue Adventure", f"Host {name} · last played {when}", True)
            else:
                card.set("Continue Adventure", f"Rejoin {target.selection.stem} · last played {when}", True)
        self.menu.show_banner(banner)
        self.game_state.set(status_text("game_found") if self._game_installed() else status_text("game_not_installed"))

    def _refresh_settings(self):
        from .launcher_display import scrollable_frame
        installation = getattr(self.worker, "installation", None)
        native = bool(installation is not None and getattr(getattr(installation, "bundle", None), "is_native", lambda: False)())
        for key in ("display", "audio", "keys"):
            holder = self.settings_pages[key]
            for child in holder.winfo_children():
                child.destroy()
            tab = str(holder)
            self.settings_tabs.tab(tab, state="normal" if native else "hidden")
            if native:
                page = scrollable_frame(holder, padding=24)
                {"display": self._game_display_page, "audio": self._game_audio_page, "keys": self._game_controls_page}[key](page)
        self.game_state.set(status_text("game_found") if self._game_installed() else status_text("game_not_installed"))

    # --- worlds

    def _rescan_worlds(self, force=True):
        """List the worlds on this PC in the background (opening one checks its database and certificate, and the installed
        game is verified once per scan). Visiting a page rescans at most every 10 seconds; Refresh and a finished game or
        setup rescan at once."""
        import time
        if self.worker is None or self._scanning or self.closing or self.worker.busy:
            return
        if not force and time.monotonic() - getattr(self, "_last_scan", -1e9) < 10:
            return
        installation, private = getattr(self.worker, "installation", None), getattr(self.worker, "private_root", None)
        if installation is None or private is None:
            return
        self._last_scan = time.monotonic()
        self._scanning = True
        results = self._scan_results

        def run():
            from .launcher_worlds import scan_worlds
            try:
                results.put(scan_worlds(installation, private))
            except Exception:
                results.put(None)
        start_thread(threading.Thread(target=run, name="world-scan", daemon=True))

    def _apply_worlds(self, entries):
        self._scanning = False
        if entries is None:
            return
        self.worlds = entries
        self._refresh_world_lists()
        if self.current_view == "home":
            self._refresh_home()

    def _world_label(self, entry):
        from .launcher_recent import describe_age
        import time
        played = self.recent.world_played(entry.directory)
        extra = {"ready": "", "invalid": "needs attention: cannot be opened",
                 "needs_game": "install the game to check it"}[entry.status]
        text = extra or ("played " + describe_age(played, time.time()) if played is not None else "not played yet")
        return text

    def _refresh_world_lists(self):
        tree = self.world_tree
        tree.delete(*tree.get_children())
        for index, entry in enumerate(self.worlds):
            tree.insert("", "end", iid=str(index), text=entry.title, values=(entry.players or "–", self._world_label(entry)))
        self.world_empty.configure(text="" if self.worlds else "No worlds on this PC yet. Choose Create a new world to start one, "
                                   "or Join Friend if a friend hosts.")
        titles = []
        for entry in self.worlds:
            title = entry.title
            if titles.count(title) or any(other.title == title for other in self.worlds if other is not entry):
                title += f" ({entry.directory.name[:6]})"
            titles.append(title)
        self.host_chooser.configure(values=titles)
        selected = self.selection["host"]
        match = next((i for i, w in enumerate(self.worlds) if w.host_json == selected), None)
        if match is None and selected is None and self.worlds:
            last = self.recent.last
            preferred = next((i for i, w in enumerate(self.worlds) if last is not None and last.mode == "host" and w.host_json == last.selection), None)
            match = preferred if preferred is not None else (0 if len(self.worlds) == 1 else None)
            if match is not None:
                self.selection["host"] = self.worlds[match].host_json
                self.host_label.set("World selected")
        if match is not None:
            self.host_choice.set(titles[match])
        elif selected is None:
            self.host_choice.set("")
        self._world_selected()

    def _selected_world(self):
        chosen = self.world_tree.selection()
        if chosen and chosen[0].isdigit() and int(chosen[0]) < len(self.worlds):
            return self.worlds[int(chosen[0])]
        return None

    def _world_selected(self):
        entry = self._selected_world()
        idle = self.worker is not None and not self.worker.busy
        self.world_host_button.configure(state="normal" if entry is not None and entry.status == "ready" and idle else "disabled")
        self.world_setup_button.configure(state="normal" if entry is not None and entry.status == "ready" and idle else "disabled")

    def host_selected_world(self):
        entry = self._selected_world()
        if entry is None or entry.status != "ready" or self.worker is None or self.worker.busy:
            return
        self._select_host_world(entry)
        self.show_view("host")

    def _select_host_world(self, entry):
        self.selection["host"] = entry.host_json
        self.connection_details["host"] = None
        self.copy_buttons["host"].configure(state="disabled")
        self.detail_feedback["host"].set("")
        self.detail_labels["host"].set("Connection details appear after opening this host world.")
        self.host_label.set("World selected")
        index = self.worlds.index(entry) if entry in self.worlds else None
        if index is not None:
            self.host_chooser.current(index)

    def _host_choice_changed(self):
        index = self.host_chooser.current()
        if 0 <= index < len(self.worlds):
            self._select_host_world(self.worlds[index])

    def _refresh_recent_invitations(self):
        paths = [path for path in self.recent.invitations if path.is_file()]
        self._recent_paths = paths
        self.recent_chooser.configure(values=[path.stem for path in paths])
        selected = self.selection["join"]
        if selected in paths:
            self.recent_choice.set(selected.stem)

    def _recent_invitation_changed(self):
        index = self.recent_chooser.current()
        paths = getattr(self, "_recent_paths", [])
        if 0 <= index < len(paths):
            self.choose_selection("join", paths[index])

    def use_lan_address(self):
        from .launcher_worlds import lan_addresses
        found = lan_addresses()
        if found:
            self.address.set(found[0])
            self.message.set(status_text("lan_found") if len(found) == 1 else status_text("lan_found_many"))
        else:
            self.message.set(status_text("lan_none"))

    # --- the menu's choices

    def continue_adventure(self):
        """Start the session that was started last, with the same choices (the same checks as choosing it by hand)."""
        from .launcher_recent import continue_target
        if self.worker is None or self.worker.busy:
            return
        if not self._game_installed():
            self.message.set(status_text("game_not_installed"))
            self.show_view("settings")
            self.settings_tabs.select(str(self.settings_pages["files"]))
            return
        target, reason = continue_target(self.recent)
        if target is None:
            self.message.set(status_text("continue_missing" if reason == "missing" else "continue_none"))
            return
        self.selection[target.mode] = target.selection
        if target.mode == "host":
            self.address.set(target.address)
            self.internet.set(target.internet)
        self.start(target.mode)

    def exit_game(self):
        if self.worker is not None and self.worker.busy:
            self.menu.confirm.ask(status_text("exit_busy"), self.close, yes="Close anyway")
            return
        self.close()

    def begin_host(self):
        """Start hosting; turning on Internet connections asks first, because it exposes the host to the Internet."""
        if self.worker is None or self.worker.busy:
            return
        if self.internet.get() and self.selection["host"] is not None:
            self.host_confirm.ask(status_text("internet_confirm"), lambda: self.start("host"), yes="Host with Internet connections")
            return
        self.start("host")

    def choose_selection(self, mode, path):
        self.selection[mode] = Path(path)
        self.connection_details[mode] = None
        self.copy_buttons[mode].configure(state="disabled")
        self.detail_feedback[mode].set("")
        self.detail_labels[mode].set("Checking invitation…" if mode == "join" else "Connection details appear after opening this host world.")
        # File contents, complete paths and credentials never appear here.
        getattr(self, mode + "_label").set("World selected" if mode == "host" else "Invitation selected")
        if mode == "join" and self.worker is not None and self.worker.start_probe(Path(path), inspect_only=True):
            self._enable(False)
            self.message.set(status_text("checking_invitation"))

    def _enable(self, enabled):
        for control in self.controls:
            control.configure(state="normal" if enabled else "disabled")
        self.import_button.configure(state="normal" if enabled and getattr(self.worker, "importer", None) else "disabled")
        self._world_selected()
        self._update_back_buttons()

    def import_game(self):
        from tkinter import filedialog
        if self.worker is None or self.worker.busy or self.worker.importer is None:
            return
        source = filedialog.askopenfilename(parent=self.root, title="Choose your own game dump",
                                           filetypes=[("Game Boy Advance dump or single-game ZIP", "*.gba *.zip")])
        if source and self.worker.start_import(Path(source)):
            self._enable(False)
            self.cancel.configure(state="disabled")
            self.message.set(status_text("importing"))

    def browse(self, mode, then=None):
        from tkinter import filedialog
        if self.worker is None or self.worker.busy:
            return
        path = filedialog.askopenfilename(parent=self.root,
            title="Choose your private world" if mode == "host" else "Choose your friend invitation",
            filetypes=[("World record" if mode == "host" else "Friend invitation", "*.json")])
        if path:
            self.choose_selection(mode, path)
            if mode == "host":
                match = next((i for i, w in enumerate(self.worlds) if w.host_json == Path(path)), None)
                if match is not None:
                    self.host_chooser.current(match)
                else:
                    self.host_choice.set("")
                    self.host_label.set("World file selected")
            if then == "worlds" and mode == "host":
                self.show_view("host")

    def _show_connection_details(self, mode, details):
        if not isinstance(details, ConnectionDetails):
            return
        self.connection_details[mode] = details
        self.detail_labels[mode].set(f"Friends connect to {details.destination} ({details.route_scope}).\n{details.guidance}")
        self.detail_feedback[mode].set("")
        self.copy_buttons[mode].configure(state="normal")

    def copy_connection_details(self, mode):
        details = self.connection_details.get(mode)
        if details is None:
            return
        import tkinter as tk
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(details.copy_text())
        except tk.TclError:
            code = "clipboard_unavailable"
        else:
            code = "details_copied"
        # Clipboard feedback never replaces a held-save or recovery warning.
        self.detail_feedback[mode].set(status_text(code))

    def _apply_text_size(self, size):
        import tkinter.font as font
        from tkinter import ttk
        points = {"Standard": 10, "Larger": 12, "Largest": 14}[size]
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            font.nametofont(name, root=self.root).configure(size=points)
        ttk.Style(self.root).configure("Treeview", rowheight=points * 2 + 6)

    def set_text_size(self, size):
        saved = self.display_preferences.update(text_size=size)
        self._apply_text_size(size)
        # Never replace a live recovery warning with display-only feedback.
        return saved

    def change_text_size(self, change):
        sizes = ("Standard", "Larger", "Largest")
        index = sizes.index(self.display_preferences.value["text_size"])
        self.set_text_size(sizes[max(0, min(2, index + change))])
        return "break"

    def check_installation(self):
        if self.worker is not None and self.worker.start_installation_check():
            self._enable(False)
            self.message.set(status_text("checking_installation"))

    def show_help(self):
        import tkinter as tk
        from tkinter import ttk
        help_window = tk.Toplevel(self.root)
        help_window.title("Controls & connection help")
        help_window.geometry("710x620")
        help_window.minsize(520, 420)
        help_window.transient(self.root)
        body = ttk.Frame(help_window, padding=20)
        body.pack(fill="both", expand=True)
        from .launcher_display import scrollable_frame
        tabs = ttk.Notebook(body)
        tabs.pack(fill="both", expand=True)
        installation = getattr(self.worker, "installation", None)
        native = bool(installation is not None and installation.bundle.is_native())
        keys = (("Default keyboard controls (PC game, no emulator)\n"
            "Arrows: move · Z: A/confirm · X: B/back\nEnter: Start/menu · Backslash (\\): Select · A/S: L/R\n"
            "F10: display & graphics settings (resolution, display mode, quality) and Controls · F11: fullscreen\n"
            "F4: 3D or classic view · F7: camera (Adventure or Diorama) · F8: trees · F9: photo mode · F12: picture\n"
            "Mouse wheel or -/=: zoom · comma/period: tilt\n"
            "Ctrl+R: the A+B+Select+Start chord (Local Soft Reset only, see below). Click the game window before using the keyboard.\n"
            "You can change the game's keyboard keys on the Game keys tab here, or on the Controls page of the game's F10 menu (3D game). The gamepad is not affected.\n\n")
            if native else ("Default keyboard controls\n"
            "Arrows: move · X: A/confirm · Z: B/back\nEnter: Start/menu · Backspace: Select · A/S: L/R\n"
            "Click the game window before using the keyboard. Existing custom mGBA mappings may override these defaults.\n\n"))
        topics = (("Controls", (keys +
            "Local Soft Reset\n"
            "For a supported personal encounter, use Select before your first action. The classic A+B+Select+Start combination works only in a compatible enabled build. Confirming resets that eligible encounter; it does not restart the game or reset other players. Wild encounters and shared events are excluded.\n\n"
            "Launcher keyboard access\nTab / Shift+Tab move between controls; Space activates a focused button. F1 opens this help. Ctrl++ / Ctrl+- change launcher text size; Ctrl+0 restores Standard. A focused page scrollbar/canvas supports Page Up, Page Down, Home and End. These launcher shortcuts do not remap the game.")),
            ("Connection", ("Host and join\n"
            "Keep Host Game open and the host PC awake. Each friend needs their own invitation file. A 127.0.0.1 invitation works on the host PC only. For LAN play, use the host's local network address. Internet play also needs the host's explicitly configured game port, router forwarding and firewall rule. This launcher does not change those settings.\n\n"
            "Use Copy connection details for address/port help without a sign-in credential. Send each friend's private invitation separately. A connection check verifies the invited host's identity, not character enrollment, Internet routing from another network or playable multiplayer.")),
            ("Recovery", ("Saving and interruptions\n"
            "Use Save now at a safe field point before closing. Wait for host acknowledgment. Autosave can wait while a menu, battle or trade is busy. In-game Save alone does not confirm a canonical host checkpoint.\n\n"
            "Keep the original game window open when battle/trade recovery is waiting. Recover battle reconnects the original core and waits for all original participants; it does not replace a player or forfeit. Cancel battle entry is available only for its verified pre-match cleanup path. Fully accepted proposals may need this native path rather than an ordinary challenge cancellation.\n\n"
            "Resolve interrupted trade explicitly cancels an unfinished trade or verifies its already committed result. Keep the original window open until the launcher verifies it is safe to close, then close normally and open the same Host/Join character. The disconnected trade core never resumes; the fresh game verifies the canonical result before Continue.\n\n"
            "Restart host service is offered only to the surviving host session when its state permits. It does not resume other clients automatically. If the status says a local save was preserved, rejoin through the same Host/Join identity and let normal recovery verify it. Do not copy an offline branch over it.\n\nCurrent status snapshot:\n" + self.message.get())),
            ("Installation", ("Import and file readiness\n"
            + ("This package supplies an import operation for your own supported game dump." if getattr(self.worker, "importer", None) is not None else "This package has no configured game-import patch. Import is unavailable.")
            + "\n\nCheck installed game files compares the ROM, manifest and runtime with this package's embedded pins. It does not install files, open a game, read character saves or test gameplay. A missing import patch is not supplied or bypassed by that check.\n\nUse your own game dump. A private development package with no release patch is not a tested download for friends.")))
        for title, text in topics:
            container = ttk.Frame(tabs)
            tabs.add(container, text=title)
            page = scrollable_frame(container)
            ttk.Label(page, text=text, wraplength=570, justify="left").pack(anchor="w")
        if native:
            container = ttk.Frame(tabs)
            tabs.add(container, text="Game display")
            self._game_display_page(scrollable_frame(container))
            container = ttk.Frame(tabs)
            tabs.add(container, text="Game keys")
            self._game_controls_page(scrollable_frame(container))
        options = ttk.Frame(body)
        options.pack(fill="x", pady=(10, 0))
        ttk.Label(options, text="Launcher text size").pack(side="left")
        size = tk.StringVar(value=self.display_preferences.value["text_size"])
        choice = ttk.Combobox(options, textvariable=size, values=("Standard", "Larger", "Largest"), state="readonly", width=12)
        choice.pack(side="left", padx=8)
        feedback = tk.StringVar()
        def selected(_):
            feedback.set("Saved locally." if self.set_text_size(size.get()) else "Applied for this window; existing preference file retained.")
        choice.bind("<<ComboboxSelected>>", selected)
        ttk.Label(body, textvariable=feedback).pack(anchor="w")
        ttk.Button(body, text="Close", command=help_window.destroy).pack(anchor="e", pady=(12, 0))

    def _game_display_page(self, page):
        """The native game's resolution, display mode and quality (game-settings.cfg;
        F10 in the game changes the same settings while playing)."""
        import tkinter as tk
        from tkinter import ttk
        from .game_display_settings import (MODE_LABELS, QUALITY_LABELS, QUALITIES, RESOLUTION_LABELS,
                                            RESOLUTIONS, read_display_settings, write_display_settings)
        from .player_runtime import SETTINGS_NAME
        private = getattr(self.worker, "private_root", None)
        path = Path(private) / SETTINGS_NAME if private is not None else None
        try:
            current = read_display_settings(path) if path is not None else None
        except (OSError, ValueError):
            current = None
        from .launcher_graphics import graphics_page
        bundle = getattr(getattr(self.worker, "installation", None), "bundle", None)
        graphics_page(page, self.graphics_preference,
                      has_classic=bool(getattr(bundle, "has_classic", lambda: False)()),
                      running=lambda: bool(self.worker is not None and self.worker.busy),
                      probe_now=self._test_3d_now)
        ttk.Label(page, text=("The 3D view is drawn at the resolution chosen here; menus and text boxes "
                              "stay sharp pixel art at any size. Used the next time the game starts. While "
                              "playing, F10 opens the same settings in the game."), wraplength=570,
                  justify="left").pack(anchor="w", pady=(0, 10))
        if current is None:
            ttk.Label(page, text="The game settings file cannot be read here.").pack(anchor="w")
            return
        resolutions = list(RESOLUTIONS) + ([current["resolution"]] if current["resolution"] not in RESOLUTIONS else [])
        qualities = list(QUALITIES) + (["custom"] if current["quality"] == "custom" else [])
        rows = (("Resolution", resolutions, RESOLUTION_LABELS, current["resolution"]),
                ("Display mode", list(MODE_LABELS), MODE_LABELS, current["mode"]),
                ("Graphics quality", qualities, QUALITY_LABELS, current["quality"]))
        choices = {}
        grid = ttk.Frame(page)
        grid.pack(anchor="w")
        for row, (label, keys, labels, value) in enumerate(rows):
            ttk.Label(grid, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=4)
            shown = [labels.get(key, key.replace("x", " x ")) for key in keys]
            variable = tk.StringVar(value=shown[keys.index(value)])
            ttk.Combobox(grid, textvariable=variable, values=shown, state="readonly", width=40).grid(
                row=row, column=1, sticky="w", pady=4)
            choices[label] = (variable, keys, shown)
        feedback = tk.StringVar()

        def save():
            if self.worker is None or self.worker.busy:
                feedback.set("Close the game first: it keeps these settings in the same file while it runs.")
                return
            picked = {label: keys[shown.index(variable.get())] for label, (variable, keys, shown) in choices.items()}
            try:
                write_display_settings(path, resolution=picked["Resolution"], mode=picked["Display mode"],
                                       quality=picked["Graphics quality"])
            except (OSError, ValueError):
                feedback.set("The game settings file could not be written; nothing changed.")
                return
            feedback.set("Saved. The game uses these the next time it starts.")
        ttk.Button(page, text="Save display settings", command=save).pack(anchor="w", pady=(10, 4))
        ttk.Label(page, textvariable=feedback, wraplength=570, justify="left").pack(anchor="w")

    def _game_audio_page(self, page):
        """The native game's volume and Pokemon cry volume (game-settings.cfg ``volume=`` and ``cryVolume=``; the game's F10
        menu changes the same two while playing)."""
        import tkinter as tk
        from tkinter import ttk
        from .game_display_settings import read_audio_settings, write_audio_settings
        from .player_runtime import SETTINGS_NAME
        private = getattr(self.worker, "private_root", None)
        path = Path(private) / SETTINGS_NAME if private is not None else None
        try:
            current = read_audio_settings(path) if path is not None else None
        except (OSError, ValueError):
            current = None
        ttk.Label(page, text="Sound", style="Heading.TLabel").pack(anchor="w", pady=(0, 6))
        if current is None:
            ttk.Label(page, text="The game settings file cannot be read here.").pack(anchor="w")
            return
        feedback = tk.StringVar()
        scales = {}
        grid = ttk.Frame(page)
        grid.pack(anchor="w")
        for row, (label, key) in enumerate((("Game volume (music and effects)", "volume"), ("Pokemon cry volume", "cry_volume"))):
            ttk.Label(grid, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=6)
            variable = tk.IntVar(value=current[key])
            ttk.Scale(grid, from_=0, to=10, orient="horizontal", length=240, variable=variable,
                      command=lambda value, v=variable: v.set(round(float(value)))).grid(row=row, column=1, pady=6)
            ttk.Label(grid, textvariable=variable, width=3).grid(row=row, column=2)
            scales[key] = variable

        def save():
            if self.worker is None or self.worker.busy:
                feedback.set("Close the game first: it keeps these settings in the same file while it runs.")
                return
            try:
                write_audio_settings(path, volume=int(scales["volume"].get()), cry_volume=int(scales["cry_volume"].get()))
            except (OSError, ValueError):
                feedback.set("The game settings file could not be written; nothing changed.")
                return
            feedback.set("Saved. The game uses these volumes the next time it starts (in the game, F10 changes them live).")
        ttk.Button(page, text="Save audio settings", command=save).pack(anchor="w", pady=(10, 4))
        ttk.Label(page, textvariable=feedback, wraplength=570, justify="left").pack(anchor="w")
        page.audio_scales = scales    # for tests
        page.audio_save = save

    def _game_controls_page(self, page):
        """The native game's keyboard keys (game-settings.cfg ``key.*`` lines; the 3D game's F10 menu
        has a Controls page for the same bindings). Used the next time the game starts."""
        import tkinter as tk
        from tkinter import ttk
        from .game_controls import ACTIONS, DEFAULTS, ControlsEditor, key_label, read_controls, write_controls
        from .player_runtime import SETTINGS_NAME
        private = getattr(self.worker, "private_root", None)
        path = Path(private) / SETTINGS_NAME if private is not None else None
        try:
            editor = ControlsEditor(read_controls(path) if path is not None else None)
        except (OSError, ValueError):
            editor = None
        ttk.Label(page, text=("Choose the keyboard key for each game button. Click a key, then press the new "
                              "one; Esc cancels. F1-F12 and Esc are kept for the menus and cannot be game "
                              "buttons, so the settings can always be reached. Menus in the game and this "
                              "launcher keep working whatever you choose; a gamepad is not affected. Used the "
                              "next time the game starts."), wraplength=570, justify="left").pack(anchor="w", pady=(0, 10))
        if editor is None:
            ttk.Label(page, text="The game settings file cannot be read here.").pack(anchor="w")
            return
        grid = ttk.Frame(page)
        grid.pack(anchor="w")
        buttons, defaults = {}, {}
        feedback = tk.StringVar()
        choices = ttk.Frame(page)

        def refresh():
            for action, button in buttons.items():
                waiting = editor.capturing == action
                button.configure(text="Press a key..." if waiting else key_label(editor.bindings[action]))
                defaults[action].configure(text="" if editor.bindings[action] == DEFAULTS[action]
                                           else "default: " + key_label(DEFAULTS[action]))
            feedback.set(editor.message)
            if editor.pending is not None:
                choices.pack(anchor="w", pady=(6, 0))
            else:
                choices.pack_forget()

        def capture(action):
            editor.start_capture(action)
            refresh()
            buttons[action].focus_set()

        def key_pressed(event):
            if editor.press(event.keysym):
                refresh()
            return "break"

        for row, (action, label, _) in enumerate(ACTIONS):
            ttk.Label(grid, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=3)
            button = ttk.Button(grid, text="", width=16, command=lambda action=action: capture(action))
            button.grid(row=row, column=1, sticky="w", pady=3)
            button.bind("<KeyPress>", key_pressed)
            buttons[action] = button
            defaults[action] = ttk.Label(grid, text="")
            defaults[action].grid(row=row, column=2, sticky="w", padx=8)
        ttk.Button(choices, text="Swap the two keys", command=lambda: (editor.confirm_swap(), refresh())).pack(side="left")
        ttk.Button(choices, text="Keep things as they were", command=lambda: (editor.cancel(), refresh())).pack(side="left", padx=8)
        ttk.Label(page, textvariable=feedback, wraplength=570, justify="left").pack(anchor="w", pady=(8, 0))
        actions = ttk.Frame(page)
        actions.pack(anchor="w", pady=(8, 4))

        def restore():
            editor.restore_defaults()
            refresh()

        def save():
            if self.worker is None or self.worker.busy:
                editor.message = "Close the game first: it keeps these settings in the same file while it runs."
                refresh()
                return
            try:
                write_controls(path, editor.bindings)
            except (OSError, ValueError):
                editor.message = "The game settings file could not be written; nothing changed."
                refresh()
                return
            editor.mark_saved()
            editor.message = "Saved. The game uses these keys the next time it starts."
            refresh()
        ttk.Button(actions, text="Restore default keys", command=restore).pack(side="left")
        ttk.Button(actions, text="Save controls", command=save).pack(side="left", padx=8)
        page.controls_editor = editor     # for tests
        page.controls_buttons = buttons
        refresh()

    def _test_3d_now(self):
        """Settings page button: the same check a start makes, shown as text."""
        from .graphics_mode import explain_failure
        try:
            executable = self.worker.installation.bundle.verify(MODE_3D)[0]
        except Exception:
            return "The package could not be checked here."
        result = probe_graphics(executable)
        if result.supported:
            return "3D graphics can start on this PC" + (f" ({result.renderer})." if result.renderer else ".")
        return explain_failure(result)

    def open_setup(self, role=None, world=None):
        """World and character setup, inside this window: the same pages, worker and checks as before."""
        if self.worker is None or self.worker.busy or self.setup_window is not None:
            return
        from .launcher_setup_gui import SetupWindow
        selected = world.directory if world is not None else (self.selection["host"].parent if self.selection["host"] else None)
        if world is None and role is not None:
            selected = None
        def finished(world_directory):
            self.setup_window = None
            if world_directory is not None:
                self.selection["host"] = world_directory / "host.json"
                self.host_label.set("World selected")
                self.connection_details["host"] = None
                self.copy_buttons["host"].configure(state="disabled")
                self.detail_labels["host"].set("Connection details appear after opening this host world.")
            if self.close_after_setup:
                self._destroy()
            else:
                self._enable(True)
                self.show_view("worlds")
        # First-time setup starts a game too, so it follows the same graphics choice.
        def open_window(graphics):
            self._enable(False)
            self.show_view("setup")
            self.setup_window = SetupWindow(self.root, self.worker.installation_for(graphics),
                self.worker.private_root, selected_world=selected, on_close=finished, container=self.setup_host, start_role=role)
        self.graphics_gate.resolve(open_window, cancelled=lambda: self._enable(True))

    def start(self, mode):
        if self.worker is None or self.worker.busy:
            return
        selected = self.selection[mode]
        if selected is None:
            self.message.set(status_text("selection_required"))
            return
        request = LaunchRequest(mode, selected, self.address.get().strip(), self.internet.get())
        try:
            request.options()
        except ValueError as error:
            self.message.set(status_text(error.args[0] if error.args else "session_failed"))
            return
        # The 3D check (when 3D is wanted) comes before anything starts.
        self.graphics_gate.resolve(lambda graphics: self._launch(replace(request, graphics=graphics)),
                                   cancelled=lambda: self._enable(True))

    def _launch(self, request):
        if self.worker is None or self.worker.busy or self.closing:
            return
        try:
            started = self.worker.start(request)
        except ValueError as error:
            self.message.set(status_text(error.args[0] if error.args else "session_failed"))
            return
        if started:
            # Remembered for Continue Adventure (a path, the address and times only; never a credential)
            self.recent.record_session(request.mode, request.selection, request.address, request.internet)
            self.show_view("session")
            self.connection_state.set("Host connection: connecting")
            self.checkpoint_state.set("Host checkpoint: checking this character")
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
        elif not self.closing and self.worker is not None and not getattr(self.worker, "holds_game", False):
            self.message.set(status_text("action_unavailable"))

    def recover_battle(self):
        if not self.closing and self.worker is not None and self.worker.request_battle_recovery():
            self.recover_battle_button.configure(state="disabled")
            self.cancel_battle_entry_button.configure(state="disabled")
            self.restart_host_button.configure(state="disabled")
            self.save_button.configure(state="disabled")
            self.autosave_button.configure(state="disabled")
            self.message.set(status_text("battle_recovering"))
        elif not self.closing and self.worker is not None:
            self.message.set(status_text("battle_recovery_not_ready"))

    def cancel_battle_entry(self):
        if not self.closing and self.worker is not None and self.worker.request_battle_entry_cancel():
            self.cancel_battle_entry_button.configure(state="disabled")
            self.recover_battle_button.configure(state="disabled")
            self.restart_host_button.configure(state="disabled")
            self.save_button.configure(state="disabled")
            self.autosave_button.configure(state="disabled")
            self.message.set(status_text("admission_canceling"))
        elif not self.closing and self.worker is not None:
            self.message.set(status_text("admission_cleanup_held"))

    def restart_host_service(self):
        if not self.closing and self.worker is not None and self.worker.request_host_restart():
            self.restart_host_button.configure(state="disabled")
            self.recover_battle_button.configure(state="disabled")
            self.cancel_battle_entry_button.configure(state="disabled")
            self.save_button.configure(state="disabled")
            self.autosave_button.configure(state="disabled")
            self.message.set(status_text("host_service_restarting"))
        elif not self.closing and self.worker is not None:
            self.message.set(status_text("host_restart_not_ready"))

    def recover_trade(self):
        if self.closing or self.worker is None:
            return
        from tkinter import messagebox
        if not messagebox.askokcancel("Resolve interrupted trade",
                "This cancels this exact exchange if it has not committed. An already committed trade is kept and verified.\n\n"
                "Keep the original game open until the launcher verifies the saved bytes and explicitly tells you to close it.\n\n"
                "Resolve this interrupted trade?", parent=self.root):
            return
        if self.worker.request_trade_recovery():
            for button in (self.recover_trade_button, self.restart_host_button, self.recover_battle_button,
                           self.cancel_battle_entry_button, self.save_button, self.autosave_button):
                button.configure(state="disabled")
            self.message.set(status_text("trade_recovery_checking"))
        else:
            self.message.set(status_text("trade_recovery_held"))

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
        self.championship_panel.set_closing(True)
        self.player_panel.set_closing(True)
        self.battle_panel.set_closing(True)
        self.archive_panel.set_closing(True)
        self.reset_panel.set_closing(True)
        self._enable(False)
        self.save_button.configure(state="disabled")
        self.autosave_button.configure(state="disabled")
        self.recover_battle_button.configure(state="disabled")
        self.cancel_battle_entry_button.configure(state="disabled")
        self.restart_host_button.configure(state="disabled")
        self.recover_trade_button.configure(state="disabled")
        cancelled = self.worker.cancel_startup()
        self.cancel.configure(state="disabled")
        code = "closing" if cancelled else "wait_for_game"
        if getattr(self.worker, "importing", False):
            code = "wait_for_import"
        elif getattr(self.worker, "checking_connection", False):
            code = "wait_for_connection"
        elif getattr(self.worker, "checking_installation", False):
            code = "wait_for_installation_check"
        self.message.set(status_text(code))

    def _destroy(self):
        self.player_panel.close()
        self.championship_panel.close()
        self.battle_panel.close()
        self.archive_panel.close()
        self.reset_panel.close()
        self.root.after_cancel(self._poll_id)
        self.root.destroy()

    def poll(self):
        if self.worker is not None:
            while True:
                try:
                    event = self.worker.events.get_nowait()
                except queue.Empty:
                    break
                if self.player_panel.handle_event(event):
                    continue
                if self.championship_panel.handle_event(event):
                    continue
                if self.battle_panel.handle_event(event):
                    continue
                if self.archive_panel.handle_event(event):
                    continue
                if self.reset_panel.handle_event(event):
                    continue
                if event.connection_details is not None:
                    mode = "host" if event.is_host else "join"
                    self._show_connection_details(mode, event.connection_details)
                if event.kind == "complete":
                    self.connection_state.set("Host connection: not connected")
                elif event.state:
                    self.connection_state.set("Host connection: authenticated" if event.connected else "Host connection: unavailable")
                if type(event.revision) is int and event.revision >= 0:
                    self.checkpoint_state.set(f"Host checkpoint: revision {event.revision} (last verified)")
                self.recover_trade_button.configure(state="normal" if not self.closing
                    and event.kind != "complete" and event.state == "running"
                    and event.trade_recovery_available else "disabled")
                if event.kind != "complete" and event.is_host and event.state == "running":
                    if not self.restart_host_button.winfo_manager():
                        self.restart_host_button.pack(side="left", padx=(12, 0))
                    self.restart_host_button.configure(state="normal" if not self.closing
                        and event.host_restart_available else "disabled")
                else:
                    self.restart_host_button.configure(state="disabled")
                    self.restart_host_button.pack_forget()
                if event.kind == "complete":
                    if self.closing:
                        self._destroy()
                        return
                    self._enable(True)
                    self.cancel.configure(state="disabled")
                    self.save_button.configure(state="disabled")
                    self.autosave_button.configure(state="disabled")
                    self.recover_battle_button.configure(state="disabled")
                    self.cancel_battle_entry_button.configure(state="disabled")
                    self.message.set(status_text(event.code))
                    self._rescan_worlds()
                elif self.closing and event.code in _RETAINS_GAME:
                    self.closing = False
                    self.championship_panel.set_closing(False)
                    self.player_panel.set_closing(False)
                    self.battle_panel.set_closing(False)
                    self.archive_panel.set_closing(False)
                    self.reset_panel.set_closing(False)
                    self.restart_host_button.configure(state="normal" if event.host_restart_available else "disabled")
                    self.recover_battle_button.configure(state="normal" if event.battle_recovery_available else "disabled")
                    self.cancel_battle_entry_button.configure(state="normal" if event.admission_cleanup_available else "disabled")
                    self.message.set(status_text("wait_for_recovery"))
                elif not self.closing:
                    self.message.set(status_text(event.code))
                    if event.autosave_enabled is not None:
                        self._autosave_observed = event.autosave_enabled
                        self.autosave_value.set(event.autosave_enabled)
                    self.autosave_button.configure(state="normal" if event.state == "running"
                        and event.code not in {"battle_recovering", "admission_canceling", "host_service_restarting",
                                               "trade_recovery_checking"} else "disabled")
                    self.recover_battle_button.configure(state="normal" if event.state == "running"
                        and event.battle_recovery_available else "disabled")
                    self.cancel_battle_entry_button.configure(state="normal" if event.state == "running"
                        and event.admission_cleanup_available else "disabled")
                    self.save_button.configure(state="normal" if event.state == "running"
                        and (event.save_available if event.save_available is not None else event.code in {"running", "saved", "save_not_ready", "autosave_on", "autosave_off",
                                           "autosave_deferred", "settings_unavailable", "settings_busy",
                                           "trade_finished", "trade_cancelled", "battle_finished", "battle_cancelled",
                                           "battle_recovered", "admission_canceled"}) else "disabled")
                    if event.state in {"running", "finished"}:
                        self.cancel.configure(state="disabled")
        while True:
            try:
                scanned = self._scan_results.get_nowait()
            except queue.Empty:
                break
            self._apply_worlds(scanned)
        self._poll_id = self.root.after(80, self.poll)


def windows_dpi_awareness():
    """Sharp launcher text on high-DPI Windows displays: without it Windows draws
    the window at 96 DPI and stretches it (blurred) at 125-200% scaling. Before
    any window exists; nothing to do elsewhere or if already set."""
    if os.name != "nt":
        return False
    import ctypes
    try:
        return ctypes.windll.shcore.SetProcessDpiAwareness(1) == 0  # system DPI aware
    except (AttributeError, OSError):
        try:
            return bool(ctypes.windll.user32.SetProcessDPIAware())
        except (AttributeError, OSError):
            return False


def main(release=None, application_directory=None, import_release=None):
    """Packaged entry supplies compiled release pins; source launch is a preview."""
    import tkinter as tk
    windows_dpi_awareness()
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
