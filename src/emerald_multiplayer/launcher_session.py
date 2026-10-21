"""Development Host/Join orchestration for already enrolled characters.

No UI, enrollment, patching, offline policy or battle settlement lives
here. The application supplies trusted installation pins and private storage.
The existing runtime remains the only owner of native startup and save leases.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import inspect
import json
import math
from pathlib import Path
import re
import secrets
import time

from .battle_journal import pending_battle
from .autosave import AutosaveScheduler, AutosaveState
from .checkpoint_client import CheckpointClient
from .companion import Companion, verify_rom_manifest
from .game_facts import is_game_facts, load_facts as load_game_facts
from .host_world import HostWorld
from .invitations import Invitation
from .launcher_settings import AUTOSAVE_INTERVAL, LauncherSettings
from .network_diagnostics import ConnectionDetails
from .player_runtime import PlayerRuntime, RuntimeBundle, _finish_even_if_cancelled
from .server import WILDCARD, ServerConfig, WorldServer, is_local_address


_MESSAGES = {
    "invalid_configuration": "The development launcher configuration is invalid.",
    "installation_changed": "The installed game differs from its application pins.",
    "runtime_hash": "The bundled runtime differs from its application pin.",
    "runtime_manifest": "The bundled runtime manifest is invalid.",
    "runtime_path": "The game or character location is unsupported; use a shorter installation or private-data location.",
    "runtime_unlisted": "The bundle contains an unexpected runtime component.",
    "runtime_size": "A runtime component exceeds its size limit.",
    "world_invalid": "The private host world could not be verified.",
    "reset_migration_required": "Close the world and run its backed-up Local Soft Reset ledger upgrade before hosting this game build.",
    "trade_effect_migration_required": "Close the world and run its backed-up trade history upgrade before enabling trade effects.",
    "trade_effect_policy_required": "Choose this world's Gen 6 handler geography policy in setup before enabling trade effects.",
    "trade_native_replay_failed": "The host could not verify native trade effects; nothing new was committed.",
    "trade_effect_replay_required": "This world needs its matching game and native trade replay worker before it can host.",
    "certificate_invalid": "The host certificate is invalid or expired.",
    "build_mismatch": "The invitation requires a different installed game.",
    "invalid_invitation": "The friend invitation could not be verified.",
    "enrollment_required": "This character needs the separate first-enrollment workflow.",
    "pending_battle": "An unresolved battle requires explicit recovery before launch.",
    "battle_abandoning": "Abandoning the interrupted battle: nobody wins or loses it.",
    "battle_abandoned": "The interrupted battle was abandoned with no result. Your game continues from your last save.",
    "battle_abandon_unavailable": "There is no interrupted battle to abandon right now.",
    "battle_abandon_unsupported": "The host's version cannot abandon an interrupted battle.",
    "battle_abandon_failed": "The interrupted battle could not be abandoned now. Check the connection to the host and try again.",
    "battle_still_running": "The battle is still running on the host; it can be abandoned once it is interrupted.",
    "battle_result_final": "The battle had already finished on the host; its result stands. Use Recover battle.",
    "battle_recovery_unavailable": "This host could not verify interrupted-battle admission.",
    "trade_recovery_unavailable": "This host does not provide authenticated trade recovery.",
    "trade_recovery_held": "Retain this interrupted trade's original game and records until its exact canonical fate is verified.",
    "trade_recovery_checking": "Checking the exact trade; an unfinished trade will be canceled, never guessed or completed for the other player.",
    "trade_recovery_close": "Trade fate and canonical bytes verified. Close this game window normally, then use the same Host Game or Join Game identity to recover before Continue.",
    "trade_recovery_reopen": "The original game is closed. Use the same Host Game or Join Game identity; canonical trade recovery runs before Continue.",
    "trade_recovered": "Your committed trade was recovered and its saved result is loaded.",
    "trade_aborted_recovered": "The interrupted trade was canceled; your verified pre-trade character is loaded.",
    "mirror_active": "Another game or controller owns this character's save.",
    "connection_timeout": "The game could not connect to the host before the time limit.",
    "version_mismatch": "The host runs a different game version.",
    "wrong_world": "The server at this address is not the world of this invitation; nothing was sent to it.",
    "rejected_public_exposure_disabled": "The host's world accepts only players on the host's own network.",
    "rejected_player_already_connected": "This character is already connected to the world.",
    "rejected_invalid_credentials": "The host did not accept this invitation's sign-in.",
    "rejected_enrollment_disabled": "The host has turned off creating new characters over the network.",
    "rejected_server_full": "The world is full.",
    "rejected_busy": "The host is busy setting up other connections.",
    "rejected": "The host refused this connection.",
    "connection_lost": "The authenticated host connection is unavailable.",
    "session_changed": "The authenticated session changed; reopen after verified recovery.",
    "session_active": "This launcher session is already open or has already closed.",
    "game_active": "This launcher session already owns a game operation.",
    "already_played": "Open a new launcher session before another game launch.",
    "session_closed": "Open the launcher session before requesting a game operation.",
    "recovery_required": "Character recovery must complete before this game can launch.",
    "session_failed": "The launcher session could not complete; private recovery data is retained.",
    "save_not_ready": "Return to a safe place outside menus and battles, then request Save again.",
    "save_busy": "A character save is already running.",
    "save_recovery_required": "This character's save needs recovery before another save can start.",
    "settings_unavailable": "This character's launcher settings could not be saved or read.",
    "settings_busy": "A settings change is already finishing.",
    "battle_recovery_not_ready": "Keep the original game open until its interrupted battle can recover.",
    "battle_recovery_held": "Battle recovery remains incomplete; retain the original game and its recovery records.",
    "admission_cleanup_unsupported": "This installed game does not support neutral battle entry cleanup; retain the original game.",
    "admission_cleanup_held": "Battle entry cleanup remains incomplete; retain the original game and its recovery records.",
    "battle_entry_refused": "The game could not enter the battle; PLAYERS shows why. Nothing changed and saving still works.",
    "soft_resetting": "Resetting the game: it starts again from this character's last host save.",
    "soft_reset_done": "The game was reset to this character's last host save. Progress after it was discarded.",
    "soft_reset_refused": "The game could not reset now; the game says why. Nothing changed.",
    "host_restart_not_ready": "Host restart requires this host's disconnected, retained original battle or prepared trade with no other operation running.",
    "host_restart_failed": "The host service could not restart; retain every original game and retry after restoring the host configuration.",
}


class LauncherSessionError(ValueError):
    """``code`` is the stable session code; ``reason`` (a connection_diagnostics code) says why a connection could not be made,
    when that is known (for example connection_timeout with reason "refused")."""

    def __init__(self, code, reason=None):
        self.code = code if code in _MESSAGES else "session_failed"
        self.reason = reason if type(reason) is str and len(reason) <= 64 else None
        super().__init__(_MESSAGES[self.code])


def _safe_error(error):
    if isinstance(error, LauncherSessionError):
        return LauncherSessionError(error.code, error.reason)
    code = getattr(error, "code", None)
    if code == "trade_disabled":
        code = "trade_recovery_unavailable"
    elif code == "game_changed":
        code = "installation_changed"
    elif code in {"pending_export", "pending_trade", "invalid_journal", "revision_conflict",
                  "journal_changed", "trade_conflict", "mirror_changed"}:
        code = "recovery_required"
    elif isinstance(error, ConnectionError):
        code = "connection_lost"
    return LauncherSessionError(code)


@dataclass(frozen=True)
class GameInstallation:
    """Pins come from the application release record, never from an invitation.

    ``rom_path`` is what the Python side checks the game manifest against: the GBA ROM
    (development setups, the mGBA runtime, a package that imported the player's own game), or in
    a packaged native installation the game facts its pinned runtime bundle lists (game_facts.py,
    runtime.json "game_facts"), which stand in for the ROM. The native game reads neither. The
    build id is the ROM SHA-256 in both cases, so worlds, invitations and saves are unchanged.
    """

    rom_path: Path
    manifest_path: Path
    rom_sha256: str
    manifest_sha256: str
    bundle: RuntimeBundle

    @property
    def uses_game_facts(self):
        """Whether this installation checks the package's pinned game facts instead of a GBA ROM."""
        return is_game_facts(self.rom_path)

    def _pinned_manifest(self):
        with Path(self.manifest_path).open("rb") as source:
            raw = source.read(131073)
        if len(raw) > 131072 or hashlib.sha256(raw).hexdigest() != self.manifest_sha256:
            raise LauncherSessionError("installation_changed")
        return raw

    def verify(self):
        if (not isinstance(self.bundle, RuntimeBundle)
                or any(type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None
                       for value in (self.rom_sha256, self.manifest_sha256))):
            raise LauncherSessionError("invalid_configuration")
        self._pinned_manifest()
        if self.uses_game_facts:
            # The facts stand in for the ROM only as the very file the pinned runtime record
            # lists: verify() hashes it with the executables before it is read.
            self.bundle.verify()
            if self.bundle.game_facts_path() != Path(self.rom_path).resolve():
                raise LauncherSessionError("installation_changed")
        build, _ = verify_rom_manifest(Path(self.rom_path), Path(self.manifest_path))
        if build != self.rom_sha256:
            raise LauncherSessionError("installation_changed")
        if not self.uses_game_facts:
            self.bundle.verify()

    def battle_string_lengths(self, table_address):
        """The host's battle-message bounds for ``table_address``: read from the ROM, or recorded
        from it in the package's game facts when the package was built."""
        if not self.uses_game_facts:
            from .battle_controller import read_string_lengths
            return read_string_lengths(self.rom_path, table_address=table_address)
        raw = self._pinned_manifest()
        try:
            facts = load_game_facts(self.rom_path, raw, json.loads(raw.decode("utf-8")))
        except (OSError, ValueError) as error:
            raise LauncherSessionError("installation_changed") from error
        if facts.battle_string_lengths is None or facts.battle_string_table_address != table_address:
            raise LauncherSessionError("installation_changed")
        return facts.battle_string_lengths


class SessionState(str, Enum):
    NEW = "new"
    VALIDATING = "validating"
    CONNECTING = "connecting"
    READY = "ready"
    BLOCKED = "blocked"
    RECOVERING = "recovering"
    RUNNING = "running"
    FINISHED = "finished"
    FAILED = "failed"
    CLOSED = "closed"


@dataclass(frozen=True)
class SessionStatus:
    state: SessionState
    code: str
    connected: bool = False
    revision: int | None = None
    exit_code: int | None = None
    autosave_enabled: bool = True
    battle_recovery_available: bool = False
    admission_cleanup_available: bool = False
    battle_abandon_available: bool = False
    is_host: bool = False
    host_restart_available: bool = False
    connection_details: ConnectionDetails | None = None
    save_available: bool = False
    championship_available: bool = False
    player_actions_available: bool = False
    trade_recovery_available: bool = False
    detail: str | None = None          # connection_diagnostics code behind a connection failure (refused, timeout, ...)
    router: object | None = None       # host: port_mapping.MappingResult of automatic router setup (None: not attempted)
    relay: object | None = None        # host: relay.RelayAgentStatus of the world's relay connection (None: no relay)


class LauncherSession:
    """Single-use session; ``async with session.open(): await session.play()``.

    Call ``readiness()`` for an observational check. A reported revision never
    authorizes a write: PlayerRuntime performs closed recovery again. A running
    game's emergency controller retains exact native recovery bytes on host
    loss. Unresolved battles keep their native process and recovery journal.
    """

    def __init__(self, installation, private_directory, *, world_directory=None,
                 invitation_path=None, bind_address=None, host_route=None,
                 public=False, development_trades=False, connection_timeout=10,
                 on_status=None, server_route=None, allow_enrollment=True, overlay=False, network=None,
                 port_mapper_factory=None):
        if (not isinstance(installation, GameInstallation)
                or (world_directory is None) == (invitation_path is None)
                or type(public) is not bool or type(development_trades) is not bool or type(overlay) is not bool
                or type(connection_timeout) not in (int, float)
                or not math.isfinite(connection_timeout) or not 0 < connection_timeout <= 60
                or on_status is not None and not callable(on_status)):
            raise LauncherSessionError("invalid_configuration")
        if world_directory is not None:
            # "0.0.0.0" (every IPv4 interface) only for a world open to the Internet or hosted on a VPN/overlay address; the
            # host's own game then needs a specific route (loopback by default).
            wildcard = bind_address == WILDCARD and (public or overlay)
            if wildcard and host_route is None:
                host_route = "127.0.0.1"
            if (type(bind_address) is not str
                    or host_route is not None and type(host_route) is not str
                    or not (wildcard or is_local_address(bind_address, allow_lan=True))
                    or not is_local_address(host_route or bind_address, allow_lan=True)):
                raise LauncherSessionError("invalid_configuration")
            from .network_settings import WorldNetwork
            if network is not None and not isinstance(network, WorldNetwork):
                raise LauncherSessionError("invalid_configuration")
        elif bind_address is not None or host_route is not None or public or development_trades or overlay or network is not None:
            raise LauncherSessionError("invalid_configuration")
        if type(allow_enrollment) is not bool or (not allow_enrollment and world_directory is None):
            raise LauncherSessionError("invalid_configuration")
        if server_route is not None:
            # Join only: where to connect now (a saved server's current address). The invitation's world, account, credential
            # and pinned certificate decide who the server must be; the route is only where to knock.
            from .invite_code import valid_port
            from .secure_transport import is_numeric_unicast_address
            if (invitation_path is None or type(server_route) is not tuple or len(server_route) != 2
                    or type(server_route[0]) is not str or not is_numeric_unicast_address(server_route[0])
                    or not valid_port(server_route[1])):
                raise LauncherSessionError("invalid_configuration")
        self.installation = installation
        self.private_root = Path(private_directory).resolve()
        self._world_directory = world_directory
        self._invitation_path = invitation_path
        self._bind_address = bind_address
        self._host_route = host_route or bind_address
        self._server_route = server_route
        self._allow_enrollment = allow_enrollment
        self._public = public
        self._overlay = overlay
        self._network = network          # network_settings.WorldNetwork; None: read this world's saved settings at start
        self._port_mapper_factory = port_mapper_factory
        self._port_mapper = self._router_task = self._router = None
        self._relay_agent = self._relay_status = None
        self._development_trades = development_trades
        self._timeout = connection_timeout
        self._on_status = on_status
        self.observer_errors = 0
        self._status = SessionStatus(SessionState.NEW, "new")
        self._store = self._server = self._companion = self._runtime = None
        self._binding = None
        self._profile_directory = None
        self._entered = self._open = self._closing = self._played = False
        self._play_task = None
        self._game = self._save_task = None
        self._revision = self._save_incarnation = None
        self._save_failed = False
        self._idle_save_disconnect = self._autosave_dispatched = False
        self._settings = LauncherSettings()
        self._settings_busy = False
        self._autosave = self._autosave_task = None
        self._autosave_due = None
        self._autosave_wake = asyncio.Event()
        self._autosave_clock = lambda: asyncio.get_running_loop().time()
        self._manifest = {}
        self._interaction = None
        self._emergency = self._emergency_task = None
        self._battle_recovery_task = None
        self._battle_recovery_failed = False
        self._battle_retained = None
        self._battle_recovery_intent = None
        self._battle_handoff_successor = None
        self._battle_menu_preparation = None
        # Abandoning an interrupted battle (battle_abandonment.py): the running request, the host's answers once the
        # held game is closed (the session then starts the game again), and a watcher that follows an abandonment
        # decided elsewhere.
        self._abandon_task = None
        self._battle_abandoned = None
        self._battle_watch_task = None
        self._resolved_at_start = ()
        # START > PLAYER > RESET (Update 32): the task closing the game, then play() opens it again from the host
        # save; and when the host last saved this character in this game (the Players page shows how long ago).
        self._soft_reset_task = None
        self._soft_reset_pending = self._reset_at_start = False
        self._saved_at = self._saved_revision = None
        self._trade_retained = self._trade_close_review = None
        self._trade_recovery_task = None
        self._host_world = None
        self._host_restart_task = None
        self._entry_cleanup_task = None
        self._host_restart_notice = None
        self._connection_details = None
        self._championship_controller = None
        self._player_panel_controller = None
        self._battle_panel_controller = None
        self._record_archive_controller = None
        self._reset_panel_controller = None

    @property
    def companion(self):
        """The existing session-owned transport; use only on its owning loop."""
        return self._companion

    async def championship_action(self, snapshot_id=None, action_id=None):
        """Use one session-bound controller; no caller supplies RPC parameters."""
        from .launcher_championship_panel import ChampionshipPanelController
        if self._championship_controller is None:
            self._championship_controller = ChampionshipPanelController(self)
        return await self._championship_controller.dispatch(snapshot_id, action_id)

    async def player_panel_action(self, snapshot_id=None, action_id=None):
        """Retain roster/card/team choices on this original session's loop."""
        from .launcher_player_panel import PlayerPanelController
        if self._player_panel_controller is None:
            self._player_panel_controller = PlayerPanelController(self)
        return await self._player_panel_controller.dispatch(snapshot_id, action_id)

    async def battle_panel_action(self, snapshot_id=None, action_id=None):
        """Only proposal/consent actions; native admission remains in Players."""
        from .launcher_battle_panel import BattlePanelController
        if self._battle_panel_controller is None:
            self._battle_panel_controller = BattlePanelController(self)
        return await self._battle_panel_controller.dispatch(snapshot_id, action_id)

    async def record_archive_action(self, kind, filters=None, snapshot_id=None, action_id=None):
        """Read this actor's bounded archive on its original authenticated loop."""
        from .launcher_record_archive import RecordArchiveController
        if self._record_archive_controller is None:
            self._record_archive_controller = RecordArchiveController(self)
        return await self._record_archive_controller.dispatch(kind, filters, snapshot_id, action_id)

    async def reset_panel_action(self, snapshot_id=None, action_id=None):
        from .launcher_reset_panel import ResetPanelController
        if self._reset_panel_controller is None:
            self._reset_panel_controller = ResetPanelController(self)
        return await self._reset_panel_controller.dispatch(snapshot_id, action_id)

    @property
    def profile_directory(self):
        """Private world/player directory, available after identity validation."""
        return self._profile_directory

    @property
    def autosave_enabled(self):
        return self._settings.autosave_enabled

    def _signature(self):
        c = self._companion
        if c is None or not c.connected:
            return None
        return (c.world_id, c.server_epoch, c.session_epoch, c.save_profile,
                c.config.player_id, c.config.build_id, c.config.ruleset_id)

    @property
    def status(self):
        current = self._signature()
        value = replace(self._status, connected=current is not None, router=self._router, relay=self._relay_status,
                        autosave_enabled=self.autosave_enabled,
                        battle_recovery_available=self.can_recover_battle,
                        admission_cleanup_available=self.can_cancel_battle_entry,
                        battle_abandon_available=self.can_abandon_battle,
                        is_host=self._world_directory is not None,
                        host_restart_available=self.can_restart_host_service,
                        connection_details=self._connection_details,
                        save_available=self.can_save,
                        championship_available=self.can_manage_championship,
                        player_actions_available=self.can_manage_players,
                        trade_recovery_available=self.can_prepare_trade_recovery)
        if self._trade_recovery_task is not None:
            return replace(value, state=SessionState.RUNNING, code="trade_recovery_checking")
        if self._trade_close_review is not None:
            return replace(value, code="trade_recovery_close" if self._game is not None else "trade_recovery_reopen",
                           trade_recovery_available=False)
        if self._host_restart_task is not None:
            return replace(value, state=SessionState.RUNNING, code="host_service_restarting")
        if self._abandon_task is not None:
            return replace(value, state=SessionState.RUNNING, code="battle_abandoning")
        if self._battle_abandoned is not None:
            # Abandoned on the host and its held game closed; the session is starting the game again.
            return replace(value, state=SessionState.RUNNING, code="battle_abandoned")
        if self._soft_reset_pending:
            return replace(value, state=SessionState.RUNNING, code="soft_resetting")
        if self._battle_recovery_task is not None:
            return replace(value, state=SessionState.RUNNING, code=("admission_canceling"
                if self._status.code == "admission_canceling" else "battle_recovering"))
        if self._terminal_successor_preserved():
            return replace(value, code="host_loss_preserved", battle_recovery_available=False)
        if (self._host_restart_notice is not None and self._game is not None
                and self._game.process.returncode is None):
            notice = self._host_restart_notice
            if notice == "host_service_restarted" and not getattr(self._server, "is_serving", False):
                notice = "host_restart_failed"
            return replace(value, state=SessionState.RUNNING, code=notice)
        if self._battle_recovery_failed and self._game is not None and self._game.process.returncode is None:
            return replace(value, state=SessionState.RUNNING, code=("admission_cleanup_held"
                if self._status.code == "admission_cleanup_held" else "battle_recovery_held"))
        emergency = self._emergency
        if emergency is not None and emergency.lost.is_set():
            return replace(value, code="host_loss_" + emergency.result.state)
        if self._save_failed:
            # A missing connection is not evidence that an uncertain save
            # completed. Keep this warning through game and session closure.
            return replace(value, code="game_recovery_held" if self._retain_interrupted_core()
                           else "save_recovery_required")
        if self._open and self._binding is not None and current != self._binding:
            # Observation only. No offline-play or post-disconnect action follows.
            code = "connection_lost" if current is None else "session_changed"
            state = value.state if value.state in {SessionState.RUNNING, SessionState.RECOVERING} else SessionState.BLOCKED
            return replace(value, state=state, code=code)
        return value

    def _publish(self, state, code, *, revision=None, exit_code=None, detail=None):
        if self._game is not None and revision is not None and revision != self._saved_revision:
            # The canonical save moved on (a save, a trade, a battle's result): what a soft reset now returns to.
            self._saved_revision, self._saved_at = revision, time.monotonic()
        self._status = SessionStatus(state, code, revision=revision, exit_code=exit_code, detail=detail)
        self._emit()

    def _emit(self):
        if self._on_status is not None:
            try:
                result = self._on_status(self.status)
                if inspect.isawaitable(result):
                    if inspect.iscoroutine(result):
                        result.close()
                    raise ValueError("status observers must be synchronous")
            except (Exception, asyncio.CancelledError):
                self.observer_errors += 1

    def _assert_session(self):
        if not self._open or self._closing:
            raise LauncherSessionError("session_closed")
        current = self._signature()
        if current != self._binding:
            raise LauncherSessionError("connection_lost" if current is None else "session_changed")

    async def _prepare(self):
        self._publish(SessionState.VALIDATING, "installation")
        game = self.installation
        game.verify()
        _, self._manifest = verify_rom_manifest(game.rom_path, game.manifest_path)
        if self._world_directory is not None:
            host = HostWorld.open(self._world_directory, game.rom_path, game.manifest_path)
            self._host_world = host
            world_id, player_id = host.world_id, host.accounts[0].player_id
            if self._network is None:
                from .network_settings import NetworkSettings, WorldNetwork
                try:
                    self._network = NetworkSettings(self.private_root).get(world_id)
                except Exception:                                      # noqa: BLE001 - unreadable settings: the defaults
                    self._network = WorldNetwork()
        else:
            host = None
            identity = Invitation.load(self._invitation_path)
            world_id, player_id = identity.world_id, identity.player_id
        self._profile_directory = self.private_root / "players" / world_id / player_id
        self._settings = LauncherSettings.load(self._profile_directory)
        configure = host.host_companion_config if host is not None else identity.companion_config
        config = configure(game.rom_path, game.manifest_path, token=secrets.token_bytes(32),
                           private_directory=self._profile_directory, ipc_port=0)
        self._connection_details = ConnectionDetails.from_identity(host if host is not None else identity)
        if self._manifest.get("battle_execution_abi_version") == 1:
            config = replace(config, development_battle_channel=True)
        if host is None and self._server_route is not None:
            config = replace(config, server_host=self._server_route[0], server_port=self._server_route[1])
        if host is not None:
            # Advertised WAN address remains in invitations. The local host
            # route changes only the socket destination, preserving its TLS pin.
            config = replace(config, server_host=self._host_route)
            await self._start_host_service(host)
            await self._start_reachability(host)
        self._companion = Companion(config)
        from . import privacy
        self._companion.share_location = privacy.load(self._profile_directory)
        self._companion._privacy_directory = self._profile_directory
        if (self._manifest.get("battle_execution_abi_version") == 1
                or self._manifest.get("menu_abi_version") == 2):
            self._companion._native_menu_handoff = self._native_menu_handoff
        if (self._manifest.get("battle_resume_abi_version") == 1
                and self._manifest.get("emergency_save_abi_version") == 2):
            self._companion._native_menu_capture_battle = self._native_menu_capture_battle
            self._companion._native_menu_prepare_battle = self._native_menu_prepare_battle
            self._companion._native_menu_abandon_battle_preparation = self._native_menu_abandon_battle_preparation
            self._companion._native_menu_refused_battle = self._native_menu_refused_battle
            self._companion._native_menu_battle_blocker = self._native_menu_battle_blocker
            self._companion._native_menu_trade_blocker = self._native_menu_trade_blocker
        if (getattr(self._companion.config, "menu_open_page_abi_version", 0) == 1
                and self._manifest.get("menu_abi_version") == 2):
            # START > PLAYER > RESET (Update 32): the Players page asks this session, which then restarts the game.
            self._companion._native_menu_reset_blocker = self._native_menu_reset_blocker
            self._companion._native_menu_last_save = self._native_menu_last_save
        self._publish(SessionState.CONNECTING, "authentication")
        await self._companion.start()
        await self._await_authentication()
        self._binding = self._signature()
        self._runtime = PlayerRuntime(self._companion, game.bundle, self._profile_directory,
                                      self._profile_directory / "character.sav",
                                      launch_root=self.private_root / "launches",
                                      role="host" if self._world_directory is not None else "join")
        self._open = True
        await self.readiness()

    async def _await_authentication(self):
        """Wait for the companion's completed hello/welcome (``connected`` is set only after the server's welcome was validated).
        A permanent refusal ends the wait with its own code at once; a refusal that may clear by itself (this character's stale
        session, a full world) is reported with its own code when time runs out; anything else is connection_timeout with the
        last failure as its reason."""
        companion = self._companion
        try:
            async with asyncio.timeout(self._timeout):
                while not companion.connected:
                    if companion.stopped is not None:
                        raise LauncherSessionError(companion.stopped, companion.stopped)
                    await asyncio.sleep(.025)
        except TimeoutError:
            failure = companion.failure
            if failure in _MESSAGES and failure.startswith("rejected"):
                raise LauncherSessionError(failure, failure) from None
            raise LauncherSessionError("connection_timeout", failure) from None

    async def _start_host_service(self, host):
        """The session owns the real service/store on its original event loop."""
        if self._server is not None or self._store is not None:
            raise LauncherSessionError("host_restart_failed")
        self._store = host.open_store()
        from .reset_attempts import require_reset_ledger
        require_reset_ledger(self._store, self._manifest)
        from .ownership_protocol import OWNERSHIP_PROFILE
        from .trade_storage import TradeCheckpointStore
        ordinary_trades = (self._manifest.get("trade_abi_version") == 1
            and self._manifest.get("menu_abi_version") == 2
            and self._manifest.get("save_profile") == OWNERSHIP_PROFILE
            and isinstance(self._store, TradeCheckpointStore))
        battles = bool(self._manifest.get("battle_execution_abi_version") == 1
                       and self._store.battle_reservations_enabled)
        from .trade_native_replay import host_trade_effect_options
        effects = host_trade_effect_options(self.installation, self._store, self._manifest)
        self._server = WorldServer(ServerConfig(host.build_id, host.ruleset_id, allow_enrollment=self._allow_enrollment),
            store=self._store, development_trades=self._development_trades or ordinary_trades,
            development_teams=battles, development_battles=battles, **effects)
        if battles:
            lengths = self.installation.battle_string_lengths(self._manifest["battle_string_table_address"])
            self._server.enable_battle_execution(lengths, host.directory / "native-battle-execution",
                resume_enabled=self._manifest.get("battle_resume_abi_version") == 1)
            if self._manifest.get("rival_abi_version") == 1:
                self._server.enable_rival_battle_environment()  # Update 31: rival battles use the checkpoint's environment
        from .bridge_config import tower_enabled
        if tower_enabled(self._manifest):
            self._server.enable_tower()     # Battle Tower: Legends: the installed game has it (its solo battles need no desk)
        await self._server.start(self._bind_address, host.port, allow_lan=True,
                                 public=self._public, tls=host.server_tls, wildcard=self._bind_address == WILDCARD,
                                 relay=self._network is not None and self._network.relay_enabled)

    async def _start_reachability(self, host):
        """Automatic router setup (only while the world allows Internet connections and the host did not turn it off) and the
        world's relay connection. Both run in the background and report through ``status.router`` / ``status.relay``; neither
        can stop hosting."""
        network = self._network
        if self._public and network.router_setup:
            from .port_mapping import PortMapper
            factory = self._port_mapper_factory or PortMapper
            self._port_mapper = factory(host.port, description="EmeraldTogether " + host.world_id[:8],
                                        on_change=self._router_changed)
            self._router = self._port_mapper.result
            self._router_task = asyncio.create_task(self._port_mapper.start(), name="launcher-router-setup")
        if network.relay is not None:
            from .relay import RelayHostAgent

            def target():
                return self._server.relay_address
            self._relay_agent = RelayHostAgent(network.relay_address, network.relay_port, host.world_id, network.relay_secret,
                                               target, on_status=self._relay_changed)
            self._relay_status = self._relay_agent.status
            await self._relay_agent.start()

    def _router_changed(self, result):
        self._router = result
        self._emit()

    def _relay_changed(self, status):
        self._relay_status = status
        self._emit()

    async def _stop_reachability(self):
        agent, self._relay_agent = self._relay_agent, None
        if agent is not None:
            try:
                await agent.close()
            except Exception:                                          # noqa: BLE001 - closing continues
                pass
        task, self._router_task = self._router_task, None
        if task is not None and not task.done():
            # Let a mapping in progress finish so it can be removed; a router that does not answer is not waited for long
            # (an unremoved mapping expires with its lease).
            await asyncio.wait({task}, timeout=3)
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        mapper, self._port_mapper = self._port_mapper, None
        if mapper is not None:
            try:
                await mapper.close()
            except Exception:                                          # noqa: BLE001
                pass

    async def _close_host_service(self):
        # Retain an owner if its shutdown raises, so retry/final cleanup can
        # finish it. Never put a second service over a still-owned store.
        if self._server is not None:
            await self._server.close()
            self._server = None
        if self._store is not None:
            self._store.close()
            self._store = None

    @property
    def can_restart_host_service(self):
        if (self._world_directory is None or self._host_world is None
                or self._host_restart_task is not None or self._companion is None
                or self._trade_close_review is not None
                or self._companion.connected
                or self._host_restart_notice == "host_service_restarted"
                and getattr(self._server, "is_serving", False)):
            return False
        try:
            if self._trade_retained is not None:
                self._retained_trade()
            else:
                self._retained_battle()
            return True
        except (ValueError, OSError, AttributeError, ConnectionError):
            return False

    async def restart_host_service(self):
        """Restart this surviving host's service, then await explicit recovery.

        This does not recreate an exited game or resume any participant. Battle
        originals still need full-roster recovery; interrupted trades use the
        separate verified-close action and normal cold startup.
        """
        if not self.can_restart_host_service:
            raise LauncherSessionError("host_restart_not_ready")
        trade = self._trade_retained is not None
        retained = self._retained_trade() if trade else self._retained_battle()
        companion = self._companion
        self._save_failed = True
        self._host_restart_notice = None
        task = asyncio.create_task(self._restart_host_service(retained, companion, trade=trade),
                                   name="launcher-retained-host-service")
        self._host_restart_task = self._interaction = task
        self._autosave_wake.set()
        self._publish(SessionState.RUNNING, "host_service_restarting", revision=self._revision)
        try:
            result, canceled = await _finish_even_if_cancelled(task)
        finally:
            if self._interaction is task:
                self._interaction = None
            if self._host_restart_task is task:
                self._host_restart_task = None
            self._autosave_wake.set()
        if canceled:
            raise asyncio.CancelledError()
        return result

    async def _restart_host_service(self, retained, companion, *, trade=False):
        if trade:
            game, runtime, bridge = retained[:3]
        else:
            intent, game, bridge, runtime = retained
        closed_original = False

        def same_original():
            if trade:
                if (self._companion is not companion or self._interaction is not asyncio.current_task()
                        or self._retained_trade(allow_owner=asyncio.current_task()) != retained):
                    raise LauncherSessionError("host_restart_not_ready")
                return
            if (not self._open or self._closing or self._game is not game
                    or game.process.returncode is not None or self._runtime is not runtime
                    or self._companion is not companion or companion._bridge is not bridge
                    or bridge.incarnation != intent.incarnation
                    or companion._live_battle_runtime_id != intent.runtime_id
                    or companion.connected or self._read_retained_battle_intent() != intent
                    or self._interaction is not asyncio.current_task()):
                raise LauncherSessionError("host_restart_not_ready")

        def verified_host():
            host = HostWorld.open(self._world_directory, self.installation.rom_path,
                                  self.installation.manifest_path)
            # Includes the exact world, address/port, certificate pin, roster
            # and credentials. No edited descriptor can retarget this game.
            if host != self._host_world:
                raise LauncherSessionError("host_restart_failed")
            return host

        try:
            self.installation.verify()
            same_original()
            verified_host()  # Reject changed installation/world before closure.
            await self._stop_autosave()
            if self._autosave_task is not None:
                await self._autosave_task
            same_original()
            await self._close_host_service()
            closed_original = True
            same_original()
            host = verified_host()
            await self._start_host_service(host)
            same_original()
            self._host_restart_notice = "host_service_restarted"
            self._publish(SessionState.RUNNING, "host_service_restarted", revision=self._revision)
        except (Exception, asyncio.CancelledError) as error:
            # If replacement setup partly succeeded, retain its owner until
            # cleanup completes. A retry can finish a failed shutdown safely.
            if closed_original:
                try:
                    await self._close_host_service()
                except Exception:
                    pass
            self._host_restart_notice = "host_restart_failed"
            self._publish(SessionState.RUNNING, "host_restart_failed", revision=self._revision)
            if isinstance(error, asyncio.CancelledError):
                raise
            raise LauncherSessionError("host_restart_failed") from None

    def _retained_trade(self, *, allow_owner=None, check_bytes=True):
        """This original remains disconnected and receives no native commands."""
        from .trade_close_recovery import read_original_trade
        c, retained = self._companion, self._trade_retained
        if (not self._open or self._closing or retained is None or c is None or c.connected
                or self._interaction is not allow_owner or self._settings_busy
                or self._save_task is not None and not self._save_task.done()
                or self._autosave_dispatched or getattr(c, "_live_save_owner", None) is not None
                or getattr(c, "_live_battle_owner", None) is not None
                or self._battle_retained is not None or pending_battle(c, self._profile_directory)):
            raise LauncherSessionError("trade_recovery_held")
        game, runtime, bridge, binding, identity, menu, launch_revision = retained
        emergency = self._emergency
        if (self._game is not game or game.process.returncode is not None or self._runtime is not runtime
                or c._bridge is not bridge or bridge.incarnation != identity[3]
                or getattr(c, "_live_trade_runtime_id", None) != identity[4]
                or self._binding != binding or self._revision != launch_revision
                or not c._reconnect_blocked or menu is not getattr(bridge, "menu_session", None)
                or menu._task is not None and not menu._task.done() and menu._task is not allow_owner
                or emergency is None or emergency.bridge is not bridge
                or emergency.session != (binding[0], binding[2], identity[3])
                or not emergency.lost.is_set() or emergency.task is None or not emergency.task.done()
                or emergency.task.cancelled() or emergency.task.exception() is not None
                or emergency.task.result() != emergency.result
                or emergency.result.state != "trade_waiting"
                or any((self._profile_directory / name).exists() for name in
                       ("pending-export.json", "pending-emergency.json"))):
            raise LauncherSessionError("trade_recovery_held")
        if check_bytes:
            read_original_trade(c, self._profile_directory, binding, identity)
        elif not (self._profile_directory / "pending-trade.json").exists():
            raise LauncherSessionError("trade_recovery_held")
        return retained

    @property
    def can_prepare_trade_recovery(self):
        if self._trade_recovery_task is not None or self._host_restart_task is not None or self._trade_close_review is not None:
            return False
        try:
            self._retained_trade(check_bytes=False)
            return True
        except (ValueError, OSError, AttributeError, ConnectionError):
            return False

    async def prepare_trade_recovery(self):
        """Explicitly cancel an unfinished trade or verify its committed fate.

        Success authorizes normal closure only. The original never reconnects,
        rebinds or resumes; a fresh Host/Join must pass the closed recovery gate.
        """
        from .trade_close_recovery import review_interrupted_trade
        if not self.can_prepare_trade_recovery:
            raise LauncherSessionError("trade_recovery_held")
        retained = self._retained_trade()
        c, owner = self._companion, asyncio.current_task()
        self._trade_recovery_task = self._interaction = owner
        self._host_restart_notice = None
        self._save_failed = True
        self._autosave_wake.set()
        self._publish(SessionState.RUNNING, "trade_recovery_checking", revision=self._revision)
        def same_original():
            if self._companion is not c or self._retained_trade(allow_owner=owner, check_bytes=False) != retained:
                raise LauncherSessionError("trade_recovery_held")
        try:
            await self._stop_autosave()
            if self._autosave_task is not None:
                await self._autosave_task
            self.installation.verify()
            same_original()
            review = await review_interrupted_trade(c, self._profile_directory, retained[3], retained[4],
                check_original=same_original, timeout=self._timeout)
            same_original()
            self._trade_close_review = review
            self._publish(SessionState.RUNNING, "trade_recovery_close", revision=self._revision)
            return review
        except (Exception, asyncio.CancelledError) as error:
            self._publish(SessionState.RUNNING, "trade_recovery_held", revision=self._revision)
            if isinstance(error, asyncio.CancelledError):
                raise
            raise LauncherSessionError("trade_recovery_held") from error
        finally:
            self._trade_recovery_task = None
            if self._interaction is owner:
                self._interaction = None
            self._autosave_wake.set()

    async def _ready(self):
        self._assert_session()
        from .battle_admission_cleanup import publish_cleanup_handoffs
        await publish_cleanup_handoffs(self._companion, self._profile_directory)
        self._assert_session()
        resolved = await self._resolve_interrupted_battles()
        if resolved:
            self._resolved_at_start = tuple(resolved)
        self._assert_session()
        if pending_battle(self._companion, self._profile_directory):
            raise LauncherSessionError("pending_battle")
        head = await CheckpointClient(self._companion).info()
        self._assert_session()
        if head is None:
            raise LauncherSessionError("enrollment_required")
        # Observational capability check; cold recovery still resolves exact
        # journals and authoritative fates before it can authorize a core.
        await self._companion.trade_rpc("pending")
        self._assert_session()
        try:
            waiting = await self._companion.battle_challenge_rpc("waiting")
        except ConnectionError:
            raise
        except Exception:
            raise LauncherSessionError("battle_recovery_unavailable") from None
        self._assert_session()
        if waiting["result"]:
            # The host's durable reservation survives restart and cannot be
            # bypassed by a missing/copied local battle journal. Observing it
            # supplies no authority to clear or resume a native battle.
            raise LauncherSessionError("pending_battle")
        return head["revision"]

    async def readiness(self):
        if not self._open or self._closing:
            raise LauncherSessionError("session_closed")
        if self._play_task is not None:
            raise LauncherSessionError("game_active")
        if self._played:
            return self.status
        try:
            revision = await self._ready()
        except Exception as error:
            safe = _safe_error(error)
            self._publish(SessionState.BLOCKED, safe.code)
        else:
            self._publish(SessionState.READY, "ready", revision=revision)
        return self.status

    async def play(self):
        self._assert_session()
        if self._play_task is not None:
            raise LauncherSessionError("game_active")
        if self._played:
            raise LauncherSessionError("already_played")
        self._play_task = asyncio.current_task()
        try:
            revision = await self._ready()
            while True:
                self.installation.verify()
                self._assert_session()
                self._publish(SessionState.RECOVERING, "canonical_recovery", revision=revision)
                async with self._runtime.open() as game:
                    self._played = True
                    self._game = game
                    self._revision = game.startup.mirror.revision
                    self._saved_revision, self._saved_at = self._revision, None
                    recovered_trade = getattr(game.startup, "trade_result", None)
                    code = (("trade_recovered" if recovered_trade["state"] == "applied" else "trade_aborted_recovered")
                            if recovered_trade else "battle_abandoned" if self._resolved_at_start
                            else "soft_reset_done" if self._reset_at_start else "running")
                    self._resolved_at_start, self._reset_at_start = (), False
                    self._publish(SessionState.RUNNING, code, revision=self._revision)
                    self._autosave_task = asyncio.create_task(self._schedule_autosave(), name="launcher-autosave")
                    if getattr(self._companion.config, "emergency_save_abi_version", 0) == 2:
                        from .emergency_save import EmergencySaveController
                        self._emergency = EmergencySaveController(self._companion, self._profile_directory,
                                                                  on_status=self._emergency_status)
                        self._emergency_task = asyncio.create_task(self._watch_emergency(), name="launcher-host-loss")
                    self._battle_watch_task = asyncio.create_task(self._watch_interrupted_battle(),
                                                                  name="launcher-interrupted-battle")
                    try:
                        result = await self._wait_game(game)
                    finally:
                        # Stop accepting new requests before draining the one
                        # already dispatched, while the native file lease remains
                        # owned by PlayerRuntime. Closing a game is not a save.
                        self._game = None
                        self._autosave_wake.set()
                        if self._battle_recovery_task is not None and not self._battle_recovery_task.done():
                            self._battle_recovery_task.cancel()
                        interrupted = False
                        if self._abandon_task is not None:
                            # An abandonment closed this game: it still retires the battle's local intents.
                            _, canceled = await _finish_even_if_cancelled(
                                asyncio.gather(self._abandon_task, return_exceptions=True))
                            interrupted |= canceled
                        if self._soft_reset_task is not None:
                            _, canceled = await _finish_even_if_cancelled(
                                asyncio.gather(self._soft_reset_task, return_exceptions=True))
                            interrupted |= canceled
                        if self._battle_recovery_task is not None:
                            _, canceled = await _finish_even_if_cancelled(
                                asyncio.gather(self._battle_recovery_task, return_exceptions=True))
                            interrupted |= canceled
                        if self._host_restart_task is not None:
                            _, canceled = await _finish_even_if_cancelled(
                                asyncio.gather(self._host_restart_task, return_exceptions=True))
                            interrupted |= canceled
                        if self._trade_recovery_task is not None:
                            _, canceled = await _finish_even_if_cancelled(
                                asyncio.gather(self._trade_recovery_task, return_exceptions=True))
                            interrupted |= canceled
                        watch = self._battle_watch_task
                        if watch is not None and not watch.done():
                            watch.cancel()
                        for pending in (self._emergency_task, self._autosave_task, self._save_task, watch):
                            if pending is not None:
                                _, canceled = await _finish_even_if_cancelled(
                                    asyncio.gather(pending, return_exceptions=True))
                                interrupted |= canceled
                        if interrupted:
                            raise asyncio.CancelledError()
                if self._battle_abandoned is None and not self._soft_reset_pending:
                    break
                # The interrupted battle was abandoned and its held game closed, or the player chose RESET (Update
                # 32): this session starts the game again from the character's canonical save, with the world (and,
                # for a host, its server) still running.
                await self._restart_after_abandon()
                revision = await self._ready()
            if result == 0 and self._idle_save_disconnect and self._save_is_idle():
                # IPC can close before process exit is observed. Only confirmed
                # normal exit clears an idle-only loss; this does not save.
                self._save_failed = self._idle_save_disconnect = False
            self._publish(SessionState.FINISHED, "trade_recovery_reopen" if self._trade_close_review is not None
                          else "save_recovery_required" if self._save_failed else "game_closed", revision=self._revision,
                          exit_code=result)
            return result
        except asyncio.CancelledError:
            self._publish(SessionState.BLOCKED, "cancelled")
            raise
        except Exception as error:
            safe = _safe_error(error)
            self._publish(SessionState.BLOCKED, safe.code)
            raise safe from None
        finally:
            self._play_task = None
            self._soft_reset_pending = False      # a reset this session no longer restarts says nothing more

    # Interrupted battles (KNOWN_ISSUES MS-16, battle_abandonment.py) ---------------------------------------------
    async def _resolve_interrupted_battles(self):
        """Before this character's game starts, a battle it was part of can never go on: its game from then is gone
        (a crash, a closed window, a restart). Abandon it on the host, or adopt the host's terminal answer (abandoned,
        aborted, or closed with its result), keep that answer and retire the local intents. An older host that cannot
        abandon leaves everything as it was (the launch then stops at pending_battle, as before)."""
        from .battle_abandonment import local_battle_targets, resolve_battle, retire_local_battle
        from .battle_journal import BattleJournalError
        c = self._companion
        try:
            targets = local_battle_targets(self._profile_directory)
        except (BattleJournalError, OSError):
            raise LauncherSessionError("pending_battle") from None
        try:
            waiting = (await c.battle_challenge_rpc("waiting"))["result"]
        except ConnectionError:
            raise
        except Exception:
            waiting = []                  # the readiness check below reports an unreadable host answer
        for view in waiting:
            if (view["battle_id"], view["generation"]) not in targets:
                targets.append((view["battle_id"], view["generation"]))
        resolved = []
        for battle_id, generation in targets:
            try:
                view = await resolve_battle(c, battle_id, generation)
            except ConnectionError:
                raise
            except Exception as error:
                # A host that cannot abandon (an older version, battles turned off) keeps the earlier answer.
                code = getattr(error, "code", None)
                raise LauncherSessionError("battle_result_final" if code == "battle_result_final"
                                           else "pending_battle") from None
            self._assert_session()
            if view["state"] == "unresolved":
                raise LauncherSessionError("pending_battle")
            retire_local_battle(self._profile_directory, view)
            resolved.append(view)
        return resolved

    def _abandon_targets(self):
        """(battle_id, generation) of the interrupted battle this session's running game is held in, if any."""
        from .battle_abandonment import local_battle_targets
        if (not self._open or self._closing or self._game is None or self._game.process.returncode is not None
                or self._abandon_task is not None or self._battle_abandoned is not None
                or self._profile_directory is None or self._companion is None):
            return []
        held = (self._battle_recovery_failed or self._battle_recovery_task is not None
                or self._save_failed and self._battle_retained is not None)
        if not held:
            return []
        targets = local_battle_targets(self._profile_directory)
        if not targets and self._battle_retained is not None:
            targets = [(self._battle_retained[3], self._battle_retained[4])]
        return targets

    @property
    def can_abandon_battle(self):
        try:
            return bool(self._abandon_targets())
        except (ValueError, OSError, AttributeError):
            return False

    async def abandon_battle(self):
        """Abandon the interrupted battle this game is held in: no result for anybody, then the game starts again.

        The host decides (or has already decided: another player abandoned, or the host restarted and resolved it).
        Only then is the held game closed; its battle intents are kept with the host's answer and removed, and play()
        starts the game again in this session from the canonical save, which the battle never changed.
        """
        from .battle_abandonment import resolve_battle, retire_local_battle
        targets = self._abandon_targets()
        if not targets:
            raise LauncherSessionError("battle_abandon_unavailable")
        game, c = self._game, self._companion
        self._abandon_task = asyncio.current_task()
        self._publish(SessionState.RUNNING, "battle_abandoning", revision=self._revision)
        try:
            recovery = self._battle_recovery_task
            if recovery is not None and not recovery.done():
                recovery.cancel()                    # a recovery waiting for every original game stops here
                await asyncio.gather(recovery, return_exceptions=True)
            if not c.connected:
                c.resume_world_connection()          # the reconnect fence only kept this core for recovery
                await self._await_authentication()
            views = [await resolve_battle(c, battle_id, generation) for battle_id, generation in targets]
            if any(view["state"] == "unresolved" for view in views):
                raise LauncherSessionError("battle_abandon_failed")
            self._battle_abandoned = views
            await self._stop_autosave()
            await self._release_battle_core(game)
            for view in views:
                retire_local_battle(self._profile_directory, view)
            self._publish(SessionState.RUNNING, "battle_abandoned", revision=self._revision)
            return views
        except (Exception, asyncio.CancelledError) as error:
            if self._battle_abandoned is None:
                code = getattr(error, "code", None)
                code = code if code in ("battle_still_running", "battle_result_final", "battle_abandon_unsupported",
                                        "connection_timeout", "connection_lost") else "battle_abandon_failed"
                self._publish(SessionState.RUNNING, code, revision=self._revision)
                if isinstance(error, asyncio.CancelledError):
                    raise
                raise LauncherSessionError(code) from None
            raise
        finally:
            self._abandon_task = None

    async def _release_battle_core(self, game):
        """Close the held game; nothing of it is kept (no result, and the save is the canonical one)."""
        from .player_runtime import _stop
        c = self._companion
        emergency, watcher = self._emergency, self._emergency_task
        if watcher is not None and not watcher.done() and watcher is not asyncio.current_task():
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
        if emergency is not None and getattr(c, "_emergency_controller", None) is emergency:
            c._emergency_controller = None       # it guarded this core's unsaved field; the core holds none
        c._emergency_authority = None
        await _stop(game.process)

    async def _restart_after_abandon(self):
        """Fresh per-game state for the next game of this session, and the world connection back (after an abandoned
        battle, or a soft reset)."""
        c = self._companion
        if self._battle_abandoned is not None:
            self._resolved_at_start = tuple(self._battle_abandoned)   # the next game's first status says so
        self._reset_at_start, self._soft_reset_pending = self._soft_reset_pending, False
        self._soft_reset_task = None
        self._battle_abandoned = None
        self._save_failed = self._idle_save_disconnect = self._autosave_dispatched = False
        self._battle_recovery_failed = False
        self._battle_retained = self._battle_recovery_intent = self._battle_handoff_successor = None
        self._battle_menu_preparation = None
        self._interaction = None
        self._save_incarnation = None
        self._emergency = self._emergency_task = None
        self._autosave = self._autosave_task = self._save_task = None
        self._battle_watch_task = None
        self._autosave_due = None
        c._live_battle_runtime_id = None              # a new game is a new native runtime
        c._live_battle_terminal_pending_path = None
        c._emergency_controller = c._emergency_authority = None   # the next game arms its own saver
        async with asyncio.timeout(30):
            while c._bridge is not None:                 # the closed game's bridge winds down
                await asyncio.sleep(.05)
        if not c.connected:
            # Closing a game cuts its world session (companion._accept_bridge); with no battle intent left nothing
            # fences the reconnection, which authenticates this character again.
            c.resume_world_connection()
            await self._await_authentication()
        self._binding = self._signature()

    async def _watch_interrupted_battle(self):
        """While this game is held in an interrupted battle, follow a decision made elsewhere: once the host reports
        the battle resolved (another player abandoned it, or the host did after a restart), abandon here too. This
        never decides anything itself: an unresolved battle is left to the player (Recover or Abandon)."""
        from .battle_abandonment import resolve_battle
        while self._game is not None and not self._closing:
            await asyncio.sleep(2)
            if self._abandon_task is not None or not self._battle_recovery_failed or not self._companion.connected:
                continue
            try:
                targets = self._abandon_targets()
                views = [await resolve_battle(self._companion, battle_id, generation, abandon=False)
                         for battle_id, generation in targets]
            except Exception:  # noqa: BLE001 - an unanswered question is asked again later
                continue
            if views and all(view["state"] != "unresolved" for view in views):
                try:
                    await self.abandon_battle()
                except Exception:  # noqa: BLE001 - the player can still choose
                    pass
                return

    @property
    def can_save(self):
        return (self._game is not None and self._game.process.returncode is None
                and self._open and not self._closing and not self._save_failed
                and self._interaction is None
                and self._signature() == self._binding
                and (self._save_task is None or self._save_task.done())
                and (self._autosave is None or self._autosave.status.state is not AutosaveState.SAVING))

    @property
    def can_manage_championship(self):
        """Bracket choices require the ordinary live lifecycle, never recovery."""
        return (self.can_save and not self._settings_busy
                and self._battle_recovery_task is None and self._host_restart_task is None
                and self._battle_menu_preparation is None
                and getattr(self._companion, "_live_battle_owner", None) is None)

    @property
    def can_manage_players(self):
        """Team changes use the same ordinary lifecycle gate as bracket choices."""
        return self.can_manage_championship

    def _retain_interrupted_core(self):
        if self._game is None or self._game.process.returncode is not None:
            return False
        if getattr(self, "_battle_abandoned", None) is not None:
            return False                          # its battle is abandoned on the host: the core holds nothing
        if (getattr(self, "_battle_recovery_task", None) is not None
                or getattr(self, "_host_restart_task", None) is not None):
            return True
        if self._terminal_successor_preserved():
            return False
        if getattr(self, "_battle_recovery_failed", False):
            return True
        if self._emergency is not None and self._emergency.lost.is_set() and not self._emergency.result.can_close:
            return True
        try:
            return bool(self._profile_directory is not None and
                        pending_battle(self._companion, self._profile_directory))
        except (ValueError, OSError):
            return True

    def _terminal_successor_preserved(self):
        """A finished successor receipt can close a retired battle's original core."""
        from .battle_journal import BattleIntent
        from .battle_admission_intent import BattleAdmissionIntent
        from .emergency_save import EmergencySaveController, EmergencyResult
        s = getattr(self, "_battle_handoff_successor", None)
        if type(s) is not EmergencySaveController:
            return False
        try:
            c, retained, intent = self._companion, self._battle_retained, self._battle_recovery_intent
            if (s is not self._emergency or s is not getattr(c, "_emergency_controller", None)
                    or s.companion is not c or type(intent) not in (BattleIntent, BattleAdmissionIntent) or retained is None
                    or retained[0] is not self._game or retained[1] is not self._runtime
                    or retained[2] is not c._bridge or s.bridge is not retained[2]
                    or retained[3:] != (intent.battle_id, intent.generation, intent.canonical_revision,
                                        intent.canonical_sha256, intent.incarnation, intent.runtime_id)
                    or c._bridge.incarnation != intent.incarnation
                    or getattr(c, "_live_battle_runtime_id", None) != intent.runtime_id
                    or s.base_revision != intent.canonical_revision or self._revision != intent.canonical_revision
                    or s.session[0] != intent.world_id or s.session[2] != intent.incarnation
                    or s.session[1] < intent.lease_epoch or not s.lost.is_set()
                    or s.identity != dict(world_id=intent.world_id, player_id=intent.player_id,
                        build_id=intent.build_id, ruleset_id=intent.ruleset_id, save_profile=intent.save_profile)
                    or type(s.result) is not EmergencyResult or s.result.state != "preserved" or not s.result.can_close
                    or s.task is None or not s.task.done() or s.task.cancelled() or s.task.exception() is not None
                    or s.task.result() != s.result or pending_battle(c, self._profile_directory)
                    or getattr(c, "_live_save_owner", None) is not None
                    or getattr(c, "_live_battle_owner", None) is not None):
                return False
            return True
        except (ValueError, OSError, AttributeError, TypeError, IndexError):
            return False

    def _retained_battle(self, *, allow_admission_owner=False):
        """Read exact local identity; visibility never grants native authority."""
        from .battle_journal import path_present
        from .native_battle import NativeBinding
        from .battle_admission_intent import BattleAdmissionIntent
        c = self._companion
        prepared = self._battle_menu_preparation
        menu_owner = (allow_admission_owner and prepared is not None
            and type(prepared[2]) is BattleAdmissionIntent
            and self._interaction in (prepared[0], prepared[1])
            and getattr(prepared[1], "_admission_identity", None) == (prepared[2].battle_id, prepared[2].generation)
            and getattr(prepared[1], "_battle_latched", False)
            and (prepared[0] is None or prepared[0] is getattr(prepared[1], "_task", None)))
        permitted_owner = prepared[0] if menu_owner else None
        if (not self._open or self._closing or self._game is None or self._game.process.returncode is not None
                or self._runtime is None or self._interaction is not None and not menu_owner or self._battle_recovery_task is not None
                or self._settings_busy or self._save_task is not None and not self._save_task.done()
                or self._autosave_dispatched or self._manifest.get("battle_resume_abi_version") != 1
                or c is None or getattr(c.config, "battle_resume_abi_version", 0) != 1
                or self._manifest.get("emergency_save_abi_version") != 2
                or getattr(c.config, "emergency_save_abi_version", 0) != 2
                or c._bridge is None or not getattr(c._bridge, "battle_capable", False)
                or getattr(c, "_live_battle_owner", None) not in (None, permitted_owner)
                or getattr(c, "_live_save_owner", None) not in (None, permitted_owner)):
            raise LauncherSessionError("battle_recovery_not_ready")
        if any(path_present(self._profile_directory / name) for name in
               ("pending-export.json", "pending-trade.json", "pending-emergency.json")):
            raise LauncherSessionError("battle_recovery_not_ready")
        intent = self._read_retained_battle_intent()
        expected = (intent.world_id, intent.server_epoch, intent.lease_epoch, intent.save_profile,
                    intent.player_id, intent.build_id, intent.ruleset_id)
        retained = self._battle_retained
        if (not isinstance(intent, BattleAdmissionIntent) and not NativeBinding.unpack(intent.bind.data).resumable
                or retained is None or retained[0] is not self._game or retained[1] is not self._runtime
                or retained[2] is not c._bridge
                or retained[3:] != (intent.battle_id, intent.generation, intent.canonical_revision,
                                    intent.canonical_sha256, intent.incarnation, intent.runtime_id)
                or self._binding != expected or intent.canonical_revision != self._revision
                or (intent.player_id, intent.build_id, intent.ruleset_id) !=
                   (c.config.player_id, c.config.build_id, c.config.ruleset_id)
                or intent.runtime_id != getattr(c, "_live_battle_runtime_id", None)
                or intent.incarnation != c._bridge.incarnation
                or self._save_incarnation not in (None, intent.incarnation)):
            raise LauncherSessionError("battle_recovery_not_ready")
        return intent, self._game, c._bridge, self._runtime

    def _read_retained_battle_intent(self):
        """A partial admission keeps its original identity until verified conversion."""
        from .battle_admission_intent import BattleAdmissionIntent, FILENAME, read_admission_intent
        from .battle_admission_session import verify_admission_conversion
        from .battle_journal import read_battle_intent, path_present
        directory, previous = self._profile_directory, self._battle_recovery_intent
        provisional, full = directory / FILENAME, directory / "pending-battle.json"
        if path_present(provisional):
            intent = read_admission_intent(provisional)
        elif path_present(full):
            intent = read_battle_intent(full)
        else:
            intent = previous
            if intent is None or not (path_present(directory / (intent.battle_id + ".battle-recovery-complete.json"))
                    or type(intent) is BattleAdmissionIntent and path_present(directory / (intent.battle_id + ".admission-cleanup.json"))):
                raise LauncherSessionError("battle_recovery_not_ready")
        if previous is not None and previous != intent:
            if not isinstance(previous, BattleAdmissionIntent) or isinstance(intent, BattleAdmissionIntent):
                raise LauncherSessionError("battle_recovery_not_ready")
            verify_admission_conversion(directory, previous, intent)
        return intent

    @property
    def can_recover_battle(self):
        try:
            self._retained_battle()
            return True
        except (ValueError, OSError, AttributeError, ConnectionError):
            return False

    async def recover_battle(self):
        """Explicit same-core recovery; one call waits for the original roster."""
        from .battle_recovery_session import NativeBattleRecoverySession
        from .battle_admission_intent import BattleAdmissionIntent
        from .battle_admission_session import verify_admission_conversion
        intent, game, bridge, runtime = self._retained_battle()
        self._host_restart_notice = None
        if isinstance(intent, BattleAdmissionIntent):
            from .battle_admission_cleanup import cleanup_path
            if cleanup_path(self._profile_directory, intent).exists():
                return await self.cancel_battle_entry()
        c = self._companion
        self._battle_recovery_intent = intent
        self._battle_recovery_task = self._interaction = asyncio.current_task()
        self._save_failed = True
        self._autosave_wake.set()
        self._publish(SessionState.RUNNING, "battle_recovering", revision=self._revision)
        try:
            await self._stop_autosave()
            if self._autosave_task is not None:
                await self._autosave_task
            self.installation.verify()
            if (self._game is not game or game.process.returncode is not None or self._runtime is not runtime
                    or c._bridge is not bridge or self._read_retained_battle_intent() != intent):
                raise LauncherSessionError("battle_recovery_held")
            executor = NativeBattleRecoverySession(c, self._profile_directory, original_intent=intent)
            result = await executor.run()
            if isinstance(intent, BattleAdmissionIntent):
                intent = verify_admission_conversion(self._profile_directory, intent, executor.intent)
                self._battle_recovery_intent = intent
            await self._adopt_battle_completion(result, intent, game, bridge, runtime)
            self._publish(SessionState.RUNNING, "battle_recovered", revision=self._revision)
            return result
        except (Exception, asyncio.CancelledError) as error:
            self._save_failed = self._battle_recovery_failed = True
            self._publish(SessionState.RUNNING, "battle_recovery_held", revision=self._revision)
            if isinstance(error, asyncio.CancelledError):
                raise
            raise LauncherSessionError("battle_recovery_held") from None
        finally:
            self._battle_recovery_task = self._interaction = None
            self._autosave_wake.set()

    @property
    def can_cancel_battle_entry(self):
        from .battle_admission_intent import BattleAdmissionIntent
        try:
            intent, _, _, _ = self._retained_battle(allow_admission_owner=True)
            return (type(intent) is BattleAdmissionIntent
                and self._manifest.get("battle_admission_cleanup_abi_version") == 1
                and getattr(self._companion.config, "battle_admission_cleanup_abi_version", 0) == 1)
        except (ValueError, OSError, AttributeError, ConnectionError):
            return False

    async def cancel_battle_entry(self):
        from .battle_admission_cleanup import AdmissionCleanupSession
        from .battle_admission_intent import BattleAdmissionIntent
        if (self._manifest.get("battle_admission_cleanup_abi_version") != 1
                or getattr(self._companion.config, "battle_admission_cleanup_abi_version", 0) != 1):
            raise LauncherSessionError("admission_cleanup_unsupported")
        intent, game, bridge, runtime = self._retained_battle(allow_admission_owner=True)
        if type(intent) is not BattleAdmissionIntent:
            raise LauncherSessionError("admission_cleanup_held")
        self._host_restart_notice = None
        self._battle_recovery_intent = intent
        old_interaction, prepared = self._interaction, self._battle_menu_preparation
        previous_failures = self._save_failed, self._battle_recovery_failed
        cleanup_session = None
        self._battle_recovery_task = asyncio.current_task()
        if old_interaction is None:
            self._save_failed = True
        self._autosave_wake.set()
        self._publish(SessionState.RUNNING, "admission_canceling", revision=self._revision)
        try:
            await self._stop_autosave()
            if old_interaction is None and self._autosave_task is not None:
                await self._autosave_task
            self.installation.verify()
            if (self._game is not game or game.process.returncode is not None or self._runtime is not runtime
                    or self._companion._bridge is not bridge or self._read_retained_battle_intent() != intent):
                raise LauncherSessionError("admission_cleanup_held")
            cleanup_session = AdmissionCleanupSession(self._companion, self._profile_directory, intent)
            if old_interaction is not None:
                await cleanup_session.revoke_before_menu_drain()
                current_prepared = self._battle_menu_preparation
                task = None if prepared is None else prepared[1]._task
                # Revocation may itself finish the original polling task with
                # battle_admission_canceled. That is still the exact task to drain.
                still_owned = (current_prepared is not None and current_prepared[1:] == prepared[1:]
                    and self._interaction in (prepared[1], task)) if prepared is not None else False
                already_drained = (task is not None and task.done() and current_prepared is None and self._interaction is None)
                if (prepared is None or not (still_owned or already_drained) or prepared[2] != intent
                        or getattr(bridge, "menu_session", None) is not prepared[1]):
                    raise LauncherSessionError("admission_cleanup_held")
                if task is None or task is asyncio.current_task():
                    raise LauncherSessionError("admission_cleanup_held")
                if not task.done():
                    task.cancel()
                from .player_runtime import _finish_even_if_cancelled
                _, interrupted = await _finish_even_if_cancelled(asyncio.gather(task, return_exceptions=True))
                if interrupted:
                    raise asyncio.CancelledError()
                if self._interaction is not None or self._battle_menu_preparation is not None:
                    raise LauncherSessionError("admission_cleanup_held")
            self._interaction = asyncio.current_task()
            self._save_failed = True
            self._autosave_wake.set()
            if self._autosave_task is not None:
                await self._autosave_task
            completion = await cleanup_session.run()
            await self._adopt_battle_completion(completion, intent, game, bridge, runtime, cleanup=True)
            self._publish(SessionState.RUNNING, "admission_canceled", revision=self._revision)
            return completion
        except (Exception, asyncio.CancelledError) as error:
            self._save_failed = self._battle_recovery_failed = True
            if old_interaction is not None and cleanup_session is not None and not cleanup_session.revocation_requested:
                # READY refusal (including capacity) changed no host consent or
                # native state. Let the untouched original battle task continue.
                self._save_failed, self._battle_recovery_failed = previous_failures
            self._publish(SessionState.RUNNING, "admission_cleanup_held", revision=self._revision)
            if isinstance(error, asyncio.CancelledError):
                raise
            raise LauncherSessionError("admission_cleanup_held") from error
        finally:
            self._battle_recovery_task = None
            if self._interaction is asyncio.current_task():
                self._interaction = None
            self._autosave_wake.set()

    def _schedule_entry_cleanup(self):
        """The battle ended before it started (another trainer could not enter or cancelled, the challenge expired)
        while this game held its admitted entry and no BIND: cancel that entry neutrally, as "Cancel battle entry"
        does, instead of leaving the game frozen until a restart (the owner's report of 2026-10-20). The host's
        cancel_admission refuses anything reserved or bound; then the session window still offers the button."""
        async def run():
            # The failed handoff releases its menu ownership in the same task, before this one runs.
            for _ in range(100):
                if self._interaction is None and self._battle_menu_preparation is None:
                    break
                await asyncio.sleep(.05)
            try:
                if self.can_cancel_battle_entry:
                    await self.cancel_battle_entry()
            except (LauncherSessionError, ValueError, OSError, ConnectionError):
                pass   # cancel_battle_entry published admission_cleanup_held
        if self._entry_cleanup_task is None or self._entry_cleanup_task.done():
            self._entry_cleanup_task = asyncio.create_task(run(), name="launcher-unstarted-entry-cleanup")

    async def _adopt_battle_completion(self, result, intent, game, bridge, runtime, *, cleanup=False):
        """Transfer terminal native ownership before making this character writable."""
        from .battle_session import BattleCompletion, RenewedBattleSession
        from .battle_recovery_session import verify_recovery_completion
        from .battle_terminal import complete_battle_handoff
        if cleanup:
            from .battle_admission_cleanup import AdmissionCleanupCompletion as Completion
            from .battle_admission_cleanup import verify_cleanup_completion as verify_completion
            from .battle_admission_cleanup import complete_cleanup_handoff as complete_handoff
        else:
            Completion, verify_completion, complete_handoff = BattleCompletion, verify_recovery_completion, complete_battle_handoff
        from .battle_journal import path_present
        c, emergency = self._companion, self._emergency
        if (self._manifest.get("emergency_save_abi_version") != 2
                or getattr(c.config, "emergency_save_abi_version", 0) != 2):
            raise LauncherSessionError("battle_recovery_held")
        retained = self._battle_retained
        if (retained is None or retained[0] is not game or retained[1] is not runtime or retained[2] is not bridge
                or retained[3:] != (intent.battle_id, intent.generation, intent.canonical_revision,
                                    intent.canonical_sha256, intent.incarnation, intent.runtime_id)
                or self._revision != intent.canonical_revision
                or self._binding != (intent.world_id, intent.server_epoch, intent.lease_epoch, intent.save_profile,
                                     intent.player_id, intent.build_id, intent.ruleset_id)):
            raise LauncherSessionError("battle_recovery_held")
        self._battle_recovery_intent = intent
        self._save_failed = True
        self._autosave_wake.set()
        await self._stop_autosave()
        if self._autosave_task is not None:
            await self._autosave_task
        renewed = getattr(result, "renewed_session", None)
        if (type(result) is not Completion or not isinstance(renewed, RenewedBattleSession)
                or result.state != ("admission_canceled" if cleanup else "closed")
                or (result.battle_id, result.generation, result.canonical_revision, result.canonical_sha256) !=
                   (intent.battle_id, intent.generation, intent.canonical_revision, intent.canonical_sha256)
                or (renewed.world_id, renewed.player_id, renewed.build_id, renewed.ruleset_id, renewed.save_profile,
                    renewed.incarnation, renewed.runtime_id) !=
                   (intent.world_id, intent.player_id, intent.build_id, intent.ruleset_id, intent.save_profile,
                    intent.incarnation, intent.runtime_id)
                or renewed.lease_epoch < intent.lease_epoch or renewed.server_epoch < intent.server_epoch
                or renewed.lease_epoch == intent.lease_epoch and renewed.server_epoch != intent.server_epoch):
            raise LauncherSessionError("battle_recovery_held")
        binding = (renewed.world_id, renewed.server_epoch, renewed.lease_epoch, renewed.save_profile,
                   renewed.player_id, renewed.build_id, renewed.ruleset_id)
        def same_released_core():
            return (self._game is game and game.process.returncode is None and self._runtime is runtime
                    and c._bridge is bridge and bridge.incarnation == intent.incarnation
                    and getattr(c, "_live_battle_runtime_id", None) == intent.runtime_id
                    and self._signature() == binding and c.save_incarnation == intent.incarnation
                    and not pending_battle(c, self._profile_directory)
                    and not any(path_present(self._profile_directory / name) for name in
                                ("pending-export.json", "pending-trade.json", "pending-emergency.json")))
        if not same_released_core():
            raise LauncherSessionError("battle_recovery_held")
        verify_completion(c, self._profile_directory, result, intent, bridge)
        successor = self._battle_handoff_successor
        if successor is not None and self._emergency is not successor:
            raise LauncherSessionError("battle_recovery_held")
        if successor is None and emergency is not None:
            unarmed = (getattr(c, "_emergency_controller", None) is None and emergency.session is None
                       and emergency.bridge is None and emergency.task is None
                       and emergency.result.state == "unarmed" and not emergency.lost.is_set())
            if not unarmed:
                if cleanup:
                    await emergency.retire_after_admission_cleanup(result, intent, bridge)
                else:
                    await emergency.retire_after_battle_recovery(result, intent, bridge)
            # The previous watcher must not arm or publish after replacement.
            if self._emergency_task is not None and not self._emergency_task.done():
                self._emergency_task.cancel()
                await asyncio.gather(self._emergency_task, return_exceptions=True)
        if not same_released_core():
            raise LauncherSessionError("battle_recovery_held")
        if successor is None:
            from .emergency_save import EmergencySaveController
            successor = EmergencySaveController(c, self._profile_directory, on_status=self._emergency_status)
            self._battle_handoff_successor = successor
            self._emergency, self._emergency_task = successor, None
        if successor.lost.is_set():
            raise LauncherSessionError("battle_recovery_held")
        if successor.result.state != "armed" or successor.needs_arm:
            await successor.arm(intent.canonical_revision)
        await complete_handoff(c, self._profile_directory, result, intent, bridge, successor)
        if not same_released_core():
            raise LauncherSessionError("battle_recovery_held")
        menu_session = getattr(bridge, "menu_session", None)
        if menu_session is not None:
            menu_session.finish_battle_admission(intent.battle_id, intent.generation)
        self._binding = binding
        self._save_incarnation = intent.incarnation
        self._battle_retained = None
        self._battle_recovery_intent = None
        self._battle_handoff_successor = None
        self._save_failed = self._idle_save_disconnect = self._battle_recovery_failed = False
        self._autosave_due = self._autosave_clock() + AUTOSAVE_INTERVAL
        self._emergency_task = asyncio.create_task(self._watch_emergency(), name="launcher-host-loss")
        self._autosave_task = asyncio.create_task(self._schedule_autosave(), name="launcher-autosave")

    async def _wait_game(self, game):
        # Context cancellation must not kill an unresolved battle or an
        # emergency core whose bytes have not been durably preserved. Keep the
        # runtime lease until the player explicitly closes that game window.
        waiting = asyncio.create_task(game.wait(), name="launcher-owned-game")
        interrupted = False
        try:
            while True:
                try:
                    result = await asyncio.shield(waiting)
                    break
                except asyncio.CancelledError:
                    if not self._retain_interrupted_core():
                        raise
                    interrupted = True
            if interrupted:
                raise asyncio.CancelledError()
            return result
        finally:
            if not waiting.done():
                waiting.cancel()
            await asyncio.gather(waiting, return_exceptions=True)

    async def set_autosave_enabled(self, enabled):
        """Persist this character's preference; disabling drains an active save."""
        if not self._open or self._closing or self._profile_directory is None:
            raise LauncherSessionError("session_closed")
        if type(enabled) is not bool:
            raise LauncherSessionError("invalid_configuration")
        if self._settings_busy or self._host_restart_task is not None:
            raise LauncherSessionError("settings_busy")
        self._settings_busy = True
        try:
            await self._set_autosave_enabled(enabled)
        finally:
            self._settings_busy = False

    async def _set_autosave_enabled(self, enabled):
        settings = LauncherSettings(enabled)
        try:
            settings.save(self._profile_directory)
        except Exception as error:
            raise _safe_error(error) from None
        changed = enabled != self.autosave_enabled
        self._settings = settings
        if changed and enabled:
            self._autosave_due = self._autosave_clock() + AUTOSAVE_INTERVAL
        self._autosave_wake.set()
        if not enabled:
            await self._stop_autosave()
        if self._game is not None and not self._save_failed:
            code = "saving" if self._save_task is not None and not self._save_task.done() else (
                "autosave_on" if enabled else "autosave_off")
            self._publish(SessionState.RUNNING, code,
                          revision=self._revision)

    def _autosave_safe(self):
        return (self._game is not None and self._game.process.returncode is None
                and self.autosave_enabled and not self._closing and not self._save_failed
                and self._interaction is None
                and (self._save_task is None or self._save_task.done())
                and getattr(self._companion, "_live_battle_owner", None) is None
                and not pending_battle(self._companion, self._profile_directory))

    def _save_is_idle(self):
        try:
            return (not self._autosave_dispatched
                    and (self._save_task is None or self._save_task.done())
                    and self._profile_directory is not None
                    and not (self._profile_directory / "pending-export.json").exists())
        except OSError:
            return False

    def _fail_save(self, *, idle_disconnect=False):
        # An idle disconnect still forbids saving/restarting the scheduler in
        # this live core. It may be ordinary IPC shutdown, but only a later
        # zero process exit can establish that. Never downgrade an earlier
        # dispatched, journaled, malformed or otherwise uncertain operation.
        idle = idle_disconnect and self._save_is_idle()
        self._idle_save_disconnect = idle and (not self._save_failed or self._idle_save_disconnect)
        self._save_failed = True
        self._publish(SessionState.RUNNING, "save_recovery_required", revision=self._revision)

    def _autosave_status(self, status):
        if status.state is AutosaveState.RECOVERY_REQUIRED:
            self._fail_save(idle_disconnect=status.code in {"connection_lost", "session_changed"})
        elif status.state is AutosaveState.SAVING:
            self._autosave_dispatched = True
            self._publish(SessionState.RUNNING, "saving", revision=self._revision)
        elif status.state is AutosaveState.DEFERRED:
            self._autosave_dispatched = False
            self._publish(SessionState.RUNNING, "autosave_deferred", revision=self._revision)
        elif status.state is AutosaveState.WAITING:
            # AutosaveScheduler has verified the typed exact completed result.
            if status.expected_revision not in {self._revision, self._revision + 1}:
                self._fail_save()
            elif status.expected_revision != self._revision:
                self._autosave_dispatched = False
                self._revision = status.expected_revision
                self._autosave_due = self._autosave_clock() + AUTOSAVE_INTERVAL
                self._publish(SessionState.RUNNING, "saved", revision=self._revision)
        self._autosave_wake.set()

    async def _stop_autosave(self):
        scheduler = self._autosave
        if scheduler is not None:
            try:
                await scheduler.stop()
            finally:
                if self._autosave is scheduler:
                    self._autosave = None

    async def _schedule_autosave(self):
        from .live_checkpoint import LiveCheckpointCoordinator
        try:
            while self._game is not None and not self._closing:
                self._autosave_wake.clear()
                self._assert_session()
                if (not self.autosave_enabled or self._save_failed
                        or self._interaction is not None
                        or self._save_task is not None and not self._save_task.done()):
                    await self._stop_autosave()
                else:
                    c = self._companion
                    if self._autosave is None and c._bridge is not None and c._bridge.save_capable:
                        incarnation = c.save_incarnation
                        if self._save_incarnation is not None and incarnation != self._save_incarnation:
                            raise LauncherSessionError("save_recovery_required")
                        self._save_incarnation = incarnation
                        if self._autosave_due is None:
                            self._autosave_due = self._autosave_clock() + AUTOSAVE_INTERVAL
                        self._autosave = AutosaveScheduler(
                            LiveCheckpointCoordinator(c, self._profile_directory),
                            expected_revision=self._revision, interval=AUTOSAVE_INTERVAL,
                            safe_point=self._autosave_safe, on_status=self._autosave_status,
                            clock=self._autosave_clock)
                        await self._autosave.start()
                    if (self._autosave is not None and self._autosave_due is not None
                            and self._autosave_clock() >= self._autosave_due):
                        # Preserve an already due save across safe manual refusals.
                        # The scheduler still coalesces and applies its own interval gate.
                        self._autosave.request()
                if self._save_failed:
                    break
                try:
                    await asyncio.wait_for(self._autosave_wake.wait(), .25)
                except TimeoutError:
                    pass
        except Exception as error:
            if self._game is not None:
                self._fail_save(idle_disconnect=getattr(error, "code", None)
                                in {"connection_lost", "session_changed"})
        finally:
            await self._stop_autosave()

    def _emergency_status(self, result):
        self._autosave_wake.set()
        if result.state != "armed":
            self._publish(SessionState.RUNNING, "host_loss_" + result.state, revision=self._revision)

    async def _watch_emergency(self):
        from .live_checkpoint import LiveSaveError
        controller, c = self._emergency, self._companion
        while self._game is not None and not self._closing:
            if controller.lost.is_set():
                await controller.drain()
                return
            # Ordinary Continue must load a safe field before binding its
            # ownership grant. Startup/title screens provide no save authority.
            pose = getattr(c, "_local_pose", None)
            if ((controller.session is None or controller.needs_arm) and self._interaction is None and not self._save_failed
                    and c.connected and c._bridge is not None
                    and getattr(c._bridge, "emergency_save_capable", False)
                    and pose is not None and pose.network_fields(True)["activity"] == "overworld"
                    and asyncio.get_running_loop().time() - c._last_pose_time <= c.config.pause_timeout
                    and not c.live_checkpoint_lock.locked()):
                try:
                    await controller.arm(self._revision)
                except LiveSaveError as error:
                    if error.code not in {"rom_unsafe", "rom_busy", "save_not_ready"}:
                        self._fail_save()
                        return
                except Exception:
                    self._fail_save()
                    return
            try:
                await asyncio.wait_for(controller.lost.wait(), .25)
            except TimeoutError:
                pass
        if controller.task is not None:
            await controller.drain()

    def _native_menu_battle_blocker(self, descriptor, *, entering=False):
        """Why this launcher would refuse Enter battle for `descriptor` now, or None; synchronous, no I/O beyond
        checking for recovery records. PLAYERS asks before it offers Enter, so the game never latches an Enter that
        cannot be admitted (the owner's report of 2026-10-20). `entering`: the Enter itself, whose connection and
        binding checks (including a host loss that is still draining) are check_battle_admission's."""
        c = self._companion
        if c is None or not self._open or self._closing or self._game is None or self._game.process.returncode is not None:
            return "game_active"
        if self._save_failed and not self._idle_save_disconnect:
            return "save_recovery_required"
        if self._interaction is not None or self._save_task is not None and not self._save_task.done():
            return "character_busy"
        if not entering and (not c.connected or self._binding is None or self._signature() != self._binding):
            return "session_changed"
        accepted = next((cp for cp in descriptor.get("checkpoints", ()) if cp.get("player_id") == c.config.player_id), None)
        if accepted is None or accepted.get("revision") != self._revision:
            return "save_not_ready"
        try:
            from .battle_journal import BattleJournal
            BattleJournal(c, self._profile_directory)._other_recovery()
        except ValueError as error:
            return getattr(error, "code", "character_recovery_pending")
        except OSError:
            return "character_recovery_pending"
        return None

    def _native_menu_trade_blocker(self):
        """Why a trade could not start in this game now, or None (PLAYERS hides its trade rows and says why)."""
        from .battle_journal import path_present
        c = self._companion
        if c is None or not self._open or self._closing or self._game is None or self._game.process.returncode is not None:
            return "game_active"
        if self._save_failed:
            return "save_recovery_required"
        if self._interaction is not None or self._save_task is not None and not self._save_task.done():
            return "character_busy"
        if any(path_present(self._profile_directory / name) for name in
               ("pending-export.json", "pending-trade.json", "pending-battle.json", "pending-battle-admission.json")):
            return "character_recovery_pending"
        return None

    async def _settle_failed_trade(self, trade_menu, menu_session, descriptor, error):
        """A trade that failed part way (a refused offer, a lost reply, its window's time limit) used to leave the
        field frozen with saving disabled until a restart (the owner's report of 2026-10-20). With the host still
        connected it is settled here: the coordinator's cancel asks the host, whose answer is authoritative, and then
        applies a trade the host committed or aborts it (the game's hold ends, the pre-trade party stays). Either way
        both players end with the same outcome and no Pokemon is lost or duplicated. Without a journal nothing was
        held or written: the proposal is cancelled so the other player is not left waiting; returns None then."""
        from .companion import TradeError
        coordinator, c = trade_menu.coordinator, self._companion
        if not coordinator.trade_path.exists():
            try:
                await c.trade_rpc("cancel", transaction_id=descriptor["transaction_id"], generation=descriptor["generation"])
            except (TradeError, ConnectionError, OSError, asyncio.TimeoutError, ValueError):
                pass
            menu_session.menu.notice("Trade did not start: try again")
            return None
        if not c.connected:
            raise error
        menu_session.abandon_trade_dialog()
        try:
            result = await asyncio.wait_for(coordinator.cancel(), 120)
        except (Exception, asyncio.CancelledError):
            raise error from None
        trade_menu._completion(result)
        if isinstance(result, dict) and result.get("state") == "aborted":
            menu_session.menu.notice("Trade cancelled: nothing changed")
        return result

    def _native_menu_refused_battle(self, menu_session):
        """An Enter refused before any ADMIT (BattleAdmissionRefused): forget its Python ownership. Nothing native or
        durable was left for it, so saving and later challenges stay available (no save recovery is required)."""
        prepared = self._battle_menu_preparation
        if prepared is not None and prepared[1] is menu_session:
            self._battle_menu_preparation = None
            if self._interaction in (menu_session, prepared[0]):
                self._interaction = None
        elif self._interaction is menu_session:
            self._interaction = None
        retained = self._battle_retained
        if retained is not None and self._companion is not None and retained[2] is self._companion._bridge:
            self._battle_retained = None
        self._battle_recovery_intent = None
        self._autosave_wake.set()
        if self._game is not None and not self._save_failed:
            self._publish(SessionState.RUNNING, "battle_entry_refused", revision=self._revision)

    def _native_menu_capture_battle(self, descriptor, menu_session):
        """Publish the exact native Enter event before creating any async work."""
        from .battle_admission_intent import BattleAdmissionIntent
        from .battle_admission_session import BattleAdmissionRefused, check_battle_admission, publish_battle_admission
        from .battle_session import RenewedBattleSession
        from .battle_journal import BattleJournalError
        c = self._companion
        try:
            blocker = self._native_menu_battle_blocker(descriptor, entering=True)
            if blocker is not None:
                raise BattleJournalError(blocker, "this game cannot enter the battle now")
            self._capture_checks(descriptor, menu_session)
            check_battle_admission(c, self._profile_directory, descriptor, RenewedBattleSession(
                self._binding[0], self._binding[4], self._binding[5], self._binding[6], self._binding[3],
                self._binding[1], self._binding[2], c.save_incarnation, getattr(c, "_live_battle_runtime_id", None)),
                c._bridge)
        except Exception as error:
            # Nothing durable or native names this Enter yet: a refusal, never a save failure.
            raise BattleAdmissionRefused(getattr(error, "code", None) or "game_active", str(error)) from error
        return self._capture_battle(descriptor, menu_session)

    def _capture_checks(self, descriptor, menu_session):
        c = self._companion
        if (not self._open or self._closing or self._binding is None or c is None
                or self._manifest.get("battle_resume_abi_version") != 1
                or self._manifest.get("emergency_save_abi_version") != 2
                or self._manifest.get("battle_execution_abi_version") != 1
                or getattr(c.config, "battle_resume_abi_version", 0) != 1
                or getattr(c.config, "emergency_save_abi_version", 0) != 2
                or self._game is None or self._game.process.returncode is not None
                or self._runtime is None or self._interaction is not None
                or self._save_failed and not self._idle_save_disconnect
                or self._save_task is not None and not self._save_task.done()
                or c._bridge is not menu_session.bridge
                or not getattr(menu_session, "_battle_preparing", False)):
            raise LauncherSessionError("game_active")
        accepted = next((cp for cp in descriptor["checkpoints"] if cp["player_id"] == c.config.player_id), None)
        if accepted is None or accepted["revision"] != self._revision:
            raise LauncherSessionError("save_not_ready")

    def _capture_battle(self, descriptor, menu_session):
        from .battle_admission_intent import BattleAdmissionIntent
        from .battle_admission_session import publish_battle_admission
        from .battle_session import RenewedBattleSession
        c = self._companion
        accepted = next(cp for cp in descriptor["checkpoints"] if cp["player_id"] == c.config.player_id)
        self._battle_retained = retained = (self._game, self._runtime, c._bridge,
            descriptor["battle_id"], descriptor["generation"], self._revision,
            accepted["sha256"], c.save_incarnation, getattr(c, "_live_battle_runtime_id", None))
        self._interaction = menu_session
        self._battle_menu_preparation = (None, menu_session, None)
        self._autosave_wake.set()
        try:
            original = RenewedBattleSession(self._binding[0], self._binding[4], self._binding[5],
                self._binding[6], self._binding[3], self._binding[1], self._binding[2], retained[7], retained[8])
            intent = publish_battle_admission(c, self._profile_directory, descriptor, original, retained[2])
            if (not isinstance(intent, BattleAdmissionIntent) or intent.challenge != descriptor
                    or self._game is not retained[0] or self._runtime is not retained[1]
                    or c._bridge is not retained[2]
                    or retained[3:] != (intent.battle_id, intent.generation, intent.canonical_revision,
                                        intent.canonical_sha256, intent.incarnation, intent.runtime_id)):
                raise LauncherSessionError("battle_recovery_held")
            self._battle_recovery_intent = intent
            self._battle_menu_preparation = (None, menu_session, intent)
            return intent
        except (Exception, asyncio.CancelledError):
            self._native_menu_abandon_battle_preparation(menu_session)
            raise

    async def _native_menu_prepare_battle(self, descriptor, menu_session):
        """Consume only this menu's synchronously published Enter event."""
        from .battle_admission_session import BattleAdmissionRefused, prepare_battle_admission
        prepared, c = self._battle_menu_preparation, self._companion
        if (prepared is None or prepared[0] is not None or prepared[1] is not menu_session
                or prepared[2] is None or prepared[2].challenge != descriptor
                or self._interaction is not menu_session or c._bridge is not menu_session.bridge
                or not getattr(menu_session, "_battle_preparing", False)):
            raise LauncherSessionError("game_active")
        owner = asyncio.current_task()
        self._interaction = owner
        self._battle_menu_preparation = (owner, menu_session, prepared[2])
        try:
            await self._stop_autosave()
            retained = self._battle_retained
            if (self._game is not retained[0] or self._game.process.returncode is not None
                    or self._runtime is not retained[1] or c._bridge is not retained[2]
                    or self._revision != retained[5]):
                raise LauncherSessionError("battle_recovery_held")
            intent = await prepare_battle_admission(c, self._profile_directory, descriptor)
            if intent != prepared[2]:
                raise LauncherSessionError("battle_recovery_held")
            return intent
        except BattleAdmissionRefused:
            # The host refused the claim before recording it and no ADMIT was sent (prepare_battle_admission retired
            # the intent): the window is released, saving stays available.
            raise
        except (Exception, asyncio.CancelledError):
            self._native_menu_abandon_battle_preparation(menu_session)
            raise

    def _native_menu_abandon_battle_preparation(self, menu_session):
        """An uncertain menu transfer releases Python ownership, never its live core."""
        prepared = self._battle_menu_preparation
        if prepared is None:
            # The native latch may already exist when Python preflight refuses
            # admission. Retain it even when no durable intent was published.
            if (getattr(menu_session, "_battle_preparing", False) and self._companion is not None
                    and self._companion._bridge is menu_session.bridge and self._game is not None):
                self._battle_recovery_failed = True
                self._fail_save()
            return
        if (prepared[1] is not menu_session or prepared[0] is not None and prepared[0] is not asyncio.current_task()):
            return
        self._battle_menu_preparation = None
        if self._interaction is prepared[0] or prepared[0] is None and self._interaction is menu_session:
            self._interaction = None
        self._battle_recovery_failed = True
        self._fail_save()
        self._autosave_wake.set()

    async def _native_menu_handoff(self, kind, descriptor, menu_session):
        """Exclusive live operation after an acknowledged native menu CLOSE."""
        if kind in ("soft_reset", "host_save"):
            return await self._native_menu_reset_handoff(kind, menu_session)
        self._assert_session()
        prepared = self._battle_menu_preparation
        prepared_battle = (prepared is not None and kind == "battle"
            and prepared[0] is asyncio.current_task() and prepared[1] is menu_session
            and prepared[2] is not None and prepared[2].challenge == descriptor
            and self._interaction is prepared[0])
        if (self._game is None or self._game.process.returncode is not None
                or self._interaction is not None and not prepared_battle or self._save_failed
                or kind == "battle" and self._manifest.get("battle_resume_abi_version") == 1 and not prepared_battle
                or self._save_task is not None and not self._save_task.done()
                or self._companion._bridge is not menu_session.bridge):
            raise LauncherSessionError("game_active")
        self._interaction = asyncio.current_task()
        self._autosave_wake.set()
        try:
            await self._stop_autosave()
            self._assert_session()
            if self._save_failed:
                raise LauncherSessionError("save_recovery_required")
            c, base = self._companion, self._revision
            incarnation = c.save_incarnation
            if kind == "battle":
                from .battle_session import NativeBattleSession, BattleCompletion
                if self._manifest.get("battle_execution_abi_version") != 1:
                    raise LauncherSessionError("recovery_required")
                accepted = next((cp for cp in descriptor["checkpoints"] if cp["player_id"] == c.config.player_id), None)
                if accepted is None or accepted["revision"] != base:
                    raise LauncherSessionError("save_not_ready")
                self._publish(SessionState.RUNNING, "battle_running", revision=base)
                executor = NativeBattleSession(c, self._profile_directory)
                retained = (self._game, self._runtime, c._bridge, descriptor["battle_id"],
                            descriptor["generation"], base, accepted["sha256"], incarnation,
                            getattr(c, "_live_battle_runtime_id", None))
                if prepared_battle:
                    original = self._battle_retained
                    if (original is None or any(original[index] is not retained[index] for index in range(3))
                            or original[3:] != retained[3:]):
                        raise LauncherSessionError("battle_recovery_held")
                else:
                    self._battle_retained = retained
                result = await executor.run(descriptor)
                if (not isinstance(result, BattleCompletion) or result.state not in {"closed", "aborted"}
                        or (result.battle_id, result.generation, result.canonical_revision, result.canonical_sha256) !=
                        (descriptor["battle_id"], descriptor["generation"], base, accepted["sha256"])):
                    raise LauncherSessionError("recovery_required")
                code = "battle_finished" if result.state == "closed" else "battle_cancelled"
                if result.state == "closed" and self._manifest.get("battle_resume_abi_version") == 1:
                    if prepared_battle:
                        from .battle_admission_session import verify_admission_conversion
                        verify_admission_conversion(self._profile_directory, prepared[2], executor.intent)
                    retained = self._battle_retained
                    self._battle_recovery_intent = executor.intent
                    await self._adopt_battle_completion(result, executor.intent, retained[0], retained[2], retained[1])
                else:
                    self._battle_retained = None
            elif kind == "trade":
                from .trade_menu import NativeTradeMenu
                from .checkpoint_client import validate_metadata
                self._publish(SessionState.RUNNING, "trade_running", revision=base)
                trade_menu = NativeTradeMenu(c, self._profile_directory, menu_session)
                original_base = (trade_menu.coordinator._load(trade_menu.coordinator._session())["expected_revision"]
                                 if trade_menu.coordinator.trade_path.exists() else base)
                self._trade_retained = (self._game, self._runtime, c._bridge, self._binding,
                    (descriptor["transaction_id"], descriptor["generation"], original_base, incarnation,
                     c._live_trade_runtime_id), menu_session, base)
                try:
                    result = await trade_menu.run(descriptor, base)
                except Exception as error:
                    result = await self._settle_failed_trade(trade_menu, menu_session, descriptor, error)
                    if result is None:
                        # Nothing was held or written: the trade did not start; saving stays available.
                        self._trade_retained = None
                        self._publish(SessionState.RUNNING, "trade_cancelled", revision=self._revision)
                        return
                checkpoint = validate_metadata(result["checkpoint"], c.config, c.save_profile)
                original_base = result.get("expected_revision")
                if (result["transaction_id"] != descriptor["transaction_id"] or checkpoint is None
                        or result.get("generation") != descriptor["generation"]
                        or type(original_base) is not int or original_base not in {base, base - 1}
                        or result["state"] not in {"applied", "aborted"}
                        or checkpoint["revision"] != original_base + (2 if result["state"] == "applied" else 1)
                        or (self._profile_directory / "pending-trade.json").exists()):
                    raise LauncherSessionError("recovery_required")
                code = "trade_finished" if result["state"] == "applied" else "trade_cancelled"
            else:
                raise LauncherSessionError("invalid_configuration")
            self._assert_session()
            if c.save_incarnation != incarnation:
                raise LauncherSessionError("recovery_required")
            if kind == "trade":
                self._revision = checkpoint["revision"]
                self._trade_retained = None
            self._autosave_due = self._autosave_clock() + AUTOSAVE_INTERVAL
            self._publish(SessionState.RUNNING, code, revision=self._revision)
        except (Exception, asyncio.CancelledError) as error:
            # A dispatched native operation must preserve every recovery
            # journal. Querying the newest server head cannot certify it.
            self._fail_save()
            if kind == "battle" and getattr(error, "code", None) == "battle_entry_unstarted":
                self._schedule_entry_cleanup()
            raise
        finally:
            if prepared_battle:
                self._battle_menu_preparation = None
            self._interaction = None
            self._autosave_wake.set()

    # Soft reset (Update 32: START > PLAYER > RESET in a world) --------------------------------------------------
    # The game starts again from the character's canonical save on the host, in this session: the world, a host's
    # server and the other players carry on. It is the same as closing the game window and choosing Continue (nothing
    # of the closed game is kept), so no Pokemon, item or money can be duplicated, and a committed trade or battle
    # result stays (both live in the canonical save). The game's own RESET without a world is its usual soft reset.
    def _native_menu_reset_blocker(self):
        """Why the game could not reset now, or None; synchronous, no I/O beyond looking for recovery records. The
        player's open challenges and trades are the Players page's (the host's lists)."""
        from .battle_journal import path_present
        c = self._companion
        if c is None or not self._open or self._closing or self._game is None or self._game.process.returncode is not None:
            return "game_active"
        if self._save_failed:
            return "save_recovery_required"
        if (self._interaction is not None or self._soft_reset_task is not None or self._abandon_task is not None
                or self._save_task is not None and not self._save_task.done()
                or self._autosave is not None and self._autosave.status.state is AutosaveState.SAVING):
            return "character_busy"
        if not c.connected or self._binding is None or self._signature() != self._binding:
            return "session_changed"
        if (self._battle_retained is not None or self._battle_menu_preparation is not None
                or self._battle_recovery_task is not None or self._battle_recovery_failed
                or getattr(c, "_live_battle_owner", None) is not None):
            return "battle_pending"
        try:
            if (pending_battle(c, self._profile_directory) or self._trade_retained is not None
                    or any(path_present(self._profile_directory / name)
                           for name in ("pending-export.json", "pending-trade.json"))):
                return "character_recovery_pending"
        except OSError:
            return "character_recovery_pending"
        return None

    def _native_menu_last_save(self):
        """Seconds since the host last saved this character in this game; None: not since the game started."""
        return None if self._saved_at is None else max(0.0, time.monotonic() - self._saved_at)

    async def _native_menu_reset_handoff(self, kind, menu_session):
        """The soft reset page's choices, once the Players menu has closed. "host_save" saves on the host, as Save now
        does; "soft_reset" closes this game, and play() opens it again from the host save. A refusal is said (here and
        in the game's banner), never raised: raising from a handoff would stop saving."""
        from .player_menu import soft_reset_refusal
        c = self._companion
        notice = getattr(c, "show_local_notice", None)
        say = notice if callable(notice) else (lambda text: None)
        if kind == "host_save":
            try:
                saved = await self.save()
            except LauncherSessionError as error:
                self._publish(SessionState.RUNNING, error.code, revision=self._revision)
                saved = False
            say("Saved on the host.|RESET goes back to here." if saved else "Could not save on the host.|See the launcher window.")
            return
        reason = self._native_menu_reset_blocker()
        if reason is None:
            # The Players page showed none; one may have been made since.
            try:
                challenges = (await c.battle_challenge_rpc("pending"))["result"]
                trades = (await c.trade_rpc("proposals"))["proposals"] if getattr(c.config, "trade_enabled", False) else []
            except Exception:  # noqa: BLE001 - an unreadable host list is a refusal, never a reset
                reason = "session_changed"
            else:
                reason = ("challenge_pending" if challenges else "trade_pending" if trades
                          else self._native_menu_reset_blocker())
        if reason is not None or menu_session.bridge is not c._bridge:
            self._publish(SessionState.RUNNING, "soft_reset_refused", revision=self._revision)
            say("Cannot reset now:|" + soft_reset_refusal(reason or "game_active"))
            return
        game = self._game
        task = asyncio.create_task(self._soft_reset(game), name="launcher-soft-reset")
        # Synchronous with the checks above: no trade, battle or save can start in between.
        self._interaction = self._soft_reset_task = task

    async def _soft_reset(self, game):
        try:
            self._autosave_wake.set()
            await self._stop_autosave()               # an autosave under way finishes first; its save stands
            if self._save_failed or not self._save_is_idle() or self._game is not game:
                self._soft_reset_task = None
                if not self._save_failed:
                    self._publish(SessionState.RUNNING, "soft_reset_refused", revision=self._revision)
                return
            self._soft_reset_pending = True
            self._publish(SessionState.RUNNING, "soft_resetting", revision=self._revision)
            notice = getattr(self._companion, "show_local_notice", None)
            if callable(notice):
                notice("Reset to your last host save.|Later progress was discarded.")
            await self._release_battle_core(game)     # nothing of the closed game is kept
        finally:
            if self._interaction is asyncio.current_task():
                self._interaction = None
            self._autosave_wake.set()

    async def save(self):
        """One explicit canonical checkpoint; never an automatic retry/merge."""
        self._assert_session()
        if self._save_task is not None and not self._save_task.done():
            raise LauncherSessionError("save_busy")
        if self._autosave is not None and self._autosave.status.state is AutosaveState.SAVING:
            raise LauncherSessionError("save_busy")
        if self._save_failed:
            raise LauncherSessionError("save_recovery_required")
        if not self.can_save:
            raise LauncherSessionError("save_not_ready")
        c = self._companion
        try:
            incarnation = c.save_incarnation
        except ConnectionError:
            if self._save_incarnation is not None:
                self._fail_save()
            else:
                self._publish(SessionState.RUNNING, "save_not_ready", revision=self._revision)
            return False
        if type(incarnation) is not int or incarnation < 1:
            self._publish(SessionState.RUNNING, "save_not_ready", revision=self._revision)
            return False
        if self._save_incarnation is not None and self._save_incarnation != incarnation:
            self._fail_save()
            return False
        self._save_incarnation = incarnation
        expected = c.world_id, c.session_epoch, incarnation
        self._save_task = asyncio.create_task(self._manual_save(expected), name="launcher-explicit-checkpoint")
        result, canceled = await _finish_even_if_cancelled(self._save_task)
        if canceled:
            raise asyncio.CancelledError()
        return result

    async def _manual_save(self, expected):
        try:
            await self._stop_autosave()
            if self._save_failed:
                return False
            return await self._save_now(expected)
        finally:
            self._autosave_wake.set()

    async def _save_now(self, expected):
        from .checkpoint_client import validate_metadata
        from .flash import FLASH_SIZE
        from .live_checkpoint import LiveCheckpointCoordinator, LiveSaveError, LiveExportResult
        self._publish(SessionState.RUNNING, "saving", revision=self._revision)
        try:
            self._assert_session()
            c = self._companion
            # Do not wait behind another transaction and later save a scene
            # that was not the one selected. An explicit later click may retry.
            if (c.live_checkpoint_lock.locked() or getattr(c, "_live_save_owner", None) is not None
                    or getattr(c, "_live_battle_owner", None) is not None):
                self._publish(SessionState.RUNNING, "save_not_ready", revision=self._revision)
                return False
            coordinator = LiveCheckpointCoordinator(c, self._profile_directory)
            result = await coordinator.checkpoint(expected_revision=self._revision, expected_session=expected)
            self._assert_session()
            if not isinstance(result, LiveExportResult):
                raise ValueError("unverified checkpoint result")
            metadata = validate_metadata(result.metadata, c.config, c.save_profile)
            if (metadata is None or metadata["revision"] != self._revision + 1
                    or metadata["request_id"] != result.operation_id or metadata["size"] != FLASH_SIZE
                    or metadata["sha256"] != result.flash_sha256 or coordinator.pending_path.exists()
                    or c.save_incarnation != expected[2]):
                raise ValueError("checkpoint completion changed")
            self._revision = metadata["revision"]
            self._autosave_due = self._autosave_clock() + AUTOSAVE_INTERVAL
            self._publish(SessionState.RUNNING, "saved", revision=self._revision)
            return True
        except Exception as error:
            if isinstance(error, LiveSaveError) and error.safe_to_retry is True:
                self._publish(SessionState.RUNNING, "save_not_ready", revision=self._revision)
            else:
                self._fail_save()
            return False

    async def _cleanup(self):
        # A caller may have started play in a child task and left the context.
        # Drain its runtime cancellation before closing network/store owners.
        if self._play_task is not None and not self._play_task.done():
            self._play_task.cancel()
            await asyncio.gather(self._play_task, return_exceptions=True)
        if self._host_restart_task is not None:
            await asyncio.gather(self._host_restart_task, return_exceptions=True)
        if self._entry_cleanup_task is not None:
            await asyncio.gather(self._entry_cleanup_task, return_exceptions=True)
        await self._stop_reachability()
        try:
            if self._companion is not None:
                await self._companion.close()
        finally:
            try:
                if self._server is not None:
                    await self._server.close()
            finally:
                if self._store is not None:
                    self._store.close()

    @asynccontextmanager
    async def open(self):
        if self._entered:
            raise LauncherSessionError("session_active")
        self._entered = True
        failed = False
        try:
            try:
                await self._prepare()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                failed = True
                safe = _safe_error(error)
                self._publish(SessionState.FAILED, safe.code, detail=safe.reason)
                raise safe from None
            yield self
        finally:
            self._closing = True
            cleanup = asyncio.create_task(self._cleanup())
            try:
                _, cancelled = await _finish_even_if_cancelled(cleanup)
            except Exception:
                self._publish(SessionState.FAILED, "session_failed")
                raise LauncherSessionError("session_failed") from None
            finally:
                self._open = False
            if not failed:
                self._publish(SessionState.CLOSED, "closed")
            if cancelled:
                raise asyncio.CancelledError()
