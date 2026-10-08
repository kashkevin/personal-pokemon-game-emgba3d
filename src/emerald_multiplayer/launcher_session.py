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
import math
from pathlib import Path
import re
import secrets

from .battle_journal import pending_battle
from .autosave import AutosaveScheduler, AutosaveState
from .checkpoint_client import CheckpointClient
from .companion import Companion, verify_rom_manifest
from .host_world import HostWorld
from .invitations import Invitation
from .launcher_settings import AUTOSAVE_INTERVAL, LauncherSettings
from .player_runtime import PlayerRuntime, RuntimeBundle, _finish_even_if_cancelled
from .server import ServerConfig, WorldServer, is_local_address


_MESSAGES = {
    "invalid_configuration": "The development launcher configuration is invalid.",
    "installation_changed": "The installed game differs from its application pins.",
    "runtime_hash": "The bundled runtime differs from its application pin.",
    "runtime_manifest": "The bundled runtime manifest is invalid.",
    "runtime_path": "The game or character location is unsupported; use a shorter installation or private-data location.",
    "runtime_unlisted": "The bundle contains an unexpected runtime component.",
    "runtime_size": "A runtime component exceeds its size limit.",
    "world_invalid": "The private host world could not be verified.",
    "certificate_invalid": "The host certificate is invalid or expired.",
    "build_mismatch": "The invitation requires a different installed game.",
    "invalid_invitation": "The friend invitation could not be verified.",
    "enrollment_required": "This character needs the separate first-enrollment workflow.",
    "pending_battle": "An unresolved battle requires explicit recovery before launch.",
    "trade_recovery_unavailable": "This host does not provide authenticated trade recovery.",
    "mirror_active": "Another game or controller owns this character's save.",
    "connection_timeout": "The host did not authenticate this session before the timeout.",
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
}


class LauncherSessionError(ValueError):
    def __init__(self, code):
        self.code = code if code in _MESSAGES else "session_failed"
        super().__init__(_MESSAGES[self.code])


def _safe_error(error):
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
    """Pins come from the application release record, never from an invitation."""

    rom_path: Path
    manifest_path: Path
    rom_sha256: str
    manifest_sha256: str
    bundle: RuntimeBundle

    def verify(self):
        if (not isinstance(self.bundle, RuntimeBundle)
                or any(type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None
                       for value in (self.rom_sha256, self.manifest_sha256))):
            raise LauncherSessionError("invalid_configuration")
        with Path(self.manifest_path).open("rb") as source:
            raw = source.read(131073)
        if len(raw) > 131072 or hashlib.sha256(raw).hexdigest() != self.manifest_sha256:
            raise LauncherSessionError("installation_changed")
        build, _ = verify_rom_manifest(Path(self.rom_path), Path(self.manifest_path))
        if build != self.rom_sha256:
            raise LauncherSessionError("installation_changed")
        self.bundle.verify()


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


class LauncherSession:
    """Single-use session; ``async with session.open(): await session.play()``.

    Call ``readiness()`` for an observational check. A reported revision never
    authorizes a write: PlayerRuntime performs closed recovery again. A running
    game's connection status is observable, but this controller does not pause,
    reboot, settle or merge it after connection loss.
    """

    def __init__(self, installation, private_directory, *, world_directory=None,
                 invitation_path=None, bind_address=None, host_route=None,
                 public=False, development_trades=False, connection_timeout=10,
                 on_status=None):
        if (not isinstance(installation, GameInstallation)
                or (world_directory is None) == (invitation_path is None)
                or type(public) is not bool or type(development_trades) is not bool
                or type(connection_timeout) not in (int, float)
                or not math.isfinite(connection_timeout) or not 0 < connection_timeout <= 60
                or on_status is not None and not callable(on_status)):
            raise LauncherSessionError("invalid_configuration")
        if world_directory is not None:
            if (type(bind_address) is not str
                    or host_route is not None and type(host_route) is not str
                    or not is_local_address(bind_address, allow_lan=True)
                    or not is_local_address(host_route or bind_address, allow_lan=True)):
                raise LauncherSessionError("invalid_configuration")
        elif bind_address is not None or host_route is not None or public or development_trades:
            raise LauncherSessionError("invalid_configuration")
        self.installation = installation
        self.private_root = Path(private_directory).resolve()
        self._world_directory = world_directory
        self._invitation_path = invitation_path
        self._bind_address = bind_address
        self._host_route = host_route or bind_address
        self._public = public
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
        self._settings = LauncherSettings()
        self._settings_busy = False
        self._autosave = self._autosave_task = None
        self._autosave_due = None
        self._autosave_wake = asyncio.Event()
        self._autosave_clock = lambda: asyncio.get_running_loop().time()

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
        value = replace(self._status, connected=current is not None,
                        autosave_enabled=self.autosave_enabled)
        if self._open and self._binding is not None and current != self._binding:
            # Observation only. No offline-play or post-disconnect action follows.
            code = "connection_lost" if current is None else "session_changed"
            state = value.state if value.state in {SessionState.RUNNING, SessionState.RECOVERING} else SessionState.BLOCKED
            return replace(value, state=state, code=code)
        return value

    def _publish(self, state, code, *, revision=None, exit_code=None):
        self._status = SessionStatus(state, code, revision=revision, exit_code=exit_code)
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
        if self._world_directory is not None:
            host = HostWorld.open(self._world_directory, game.rom_path, game.manifest_path)
            world_id, player_id = host.world_id, host.accounts[0].player_id
        else:
            host = None
            identity = Invitation.load(self._invitation_path)
            world_id, player_id = identity.world_id, identity.player_id
        self._profile_directory = self.private_root / "players" / world_id / player_id
        self._settings = LauncherSettings.load(self._profile_directory)
        configure = host.host_companion_config if host is not None else identity.companion_config
        config = configure(game.rom_path, game.manifest_path, token=secrets.token_bytes(32),
                           private_directory=self._profile_directory, ipc_port=0)
        if host is not None:
            # Advertised WAN address remains in invitations. The local host
            # route changes only the socket destination, preserving its TLS pin.
            config = replace(config, server_host=self._host_route)
            self._store = host.open_store()
            self._server = WorldServer(ServerConfig(host.build_id, host.ruleset_id),
                store=self._store, development_trades=self._development_trades)
            await self._server.start(self._bind_address, host.port, allow_lan=True,
                                     public=self._public, tls=host.server_tls)
        self._companion = Companion(config)
        self._publish(SessionState.CONNECTING, "authentication")
        await self._companion.start()
        try:
            async with asyncio.timeout(self._timeout):
                while not self._companion.connected:
                    await asyncio.sleep(.025)
        except TimeoutError:
            raise LauncherSessionError("connection_timeout") from None
        self._binding = self._signature()
        self._runtime = PlayerRuntime(self._companion, game.bundle, self._profile_directory,
                                      self._profile_directory / "character.sav",
                                      launch_root=self.private_root / "launches")
        self._open = True
        await self.readiness()

    async def _ready(self):
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
            self.installation.verify()
            self._assert_session()
            self._publish(SessionState.RECOVERING, "canonical_recovery", revision=revision)
            async with self._runtime.open() as game:
                self._played = True
                self._game = game
                self._revision = game.startup.mirror.revision
                self._publish(SessionState.RUNNING, "running", revision=self._revision)
                self._autosave_task = asyncio.create_task(self._schedule_autosave(), name="launcher-autosave")
                try:
                    result = await game.wait()
                finally:
                    # Stop accepting new requests before draining the one
                    # already dispatched, while the native file lease remains
                    # owned by PlayerRuntime. Closing a game is not a save.
                    self._game = None
                    self._autosave_wake.set()
                    if self._autosave_task is not None:
                        _, canceled = await _finish_even_if_cancelled(self._autosave_task)
                        if canceled:
                            # Drain manual saves too before propagating cancellation.
                            if self._save_task is not None:
                                await _finish_even_if_cancelled(self._save_task)
                            raise asyncio.CancelledError()
                    if self._save_task is not None:
                        _, canceled = await _finish_even_if_cancelled(self._save_task)
                        if canceled:
                            raise asyncio.CancelledError()
            self._publish(SessionState.FINISHED, "save_recovery_required" if self._save_failed else "game_closed", revision=self._revision,
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

    @property
    def can_save(self):
        return (self._game is not None and self._game.process.returncode is None
                and self._open and not self._closing and not self._save_failed
                and self._signature() == self._binding
                and (self._save_task is None or self._save_task.done())
                and (self._autosave is None or self._autosave.status.state is not AutosaveState.SAVING))

    async def set_autosave_enabled(self, enabled):
        """Persist this character's preference; disabling drains an active save."""
        if not self._open or self._closing or self._profile_directory is None:
            raise LauncherSessionError("session_closed")
        if type(enabled) is not bool:
            raise LauncherSessionError("invalid_configuration")
        if self._settings_busy:
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
                and (self._save_task is None or self._save_task.done())
                and getattr(self._companion, "_live_battle_owner", None) is None
                and not pending_battle(self._companion, self._profile_directory))

    def _autosave_status(self, status):
        if status.state is AutosaveState.RECOVERY_REQUIRED:
            self._save_failed = True
            self._publish(SessionState.RUNNING, "save_recovery_required", revision=self._revision)
        elif status.state is AutosaveState.SAVING:
            self._publish(SessionState.RUNNING, "saving", revision=self._revision)
        elif status.state is AutosaveState.DEFERRED:
            self._publish(SessionState.RUNNING, "autosave_deferred", revision=self._revision)
        elif status.state is AutosaveState.WAITING and status.expected_revision != self._revision:
            # AutosaveScheduler has verified the typed exact completed result.
            if status.expected_revision != self._revision + 1:
                self._save_failed = True
                self._publish(SessionState.RUNNING, "save_recovery_required", revision=self._revision)
            else:
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
        except Exception:
            if self._game is not None:
                self._save_failed = True
                self._publish(SessionState.RUNNING, "save_recovery_required", revision=self._revision)
        finally:
            await self._stop_autosave()

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
                self._save_failed = True
            self._publish(SessionState.RUNNING, "save_recovery_required" if self._save_failed
                          else "save_not_ready", revision=self._revision)
            return False
        if type(incarnation) is not int or incarnation < 1:
            self._publish(SessionState.RUNNING, "save_not_ready", revision=self._revision)
            return False
        if self._save_incarnation is not None and self._save_incarnation != incarnation:
            self._save_failed = True
            self._publish(SessionState.RUNNING, "save_recovery_required", revision=self._revision)
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
                self._save_failed = True
                self._publish(SessionState.RUNNING, "save_recovery_required", revision=self._revision)
            return False

    async def _cleanup(self):
        # A caller may have started play in a child task and left the context.
        # Drain its runtime cancellation before closing network/store owners.
        if self._play_task is not None and not self._play_task.done():
            self._play_task.cancel()
            await asyncio.gather(self._play_task, return_exceptions=True)
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
                self._publish(SessionState.FAILED, safe.code)
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
