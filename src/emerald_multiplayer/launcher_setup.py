"""Local host setup composition; ordinary play retains canonical recovery.

The caller's explicit invocation authorizes world creation or exact-source
enrollment. This is not remote registration, a save generator or a launch gate.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
import inspect
import math
from pathlib import Path
import secrets
from uuid import uuid4

from .companion import Companion
from .enrollment_runtime import EnrollmentRuntime, approve_enrollment_source
from .host_world import HostWorld
from .launcher_session import GameInstallation
from .player_runtime import _finish_even_if_cancelled
from .server import ServerConfig, WorldServer, is_local_address


_MESSAGES = {
    "invalid_configuration": "The character setup configuration is invalid.",
    "installation_changed": "The installed game could not be verified.",
    "world_invalid": "The private host world could not be verified.",
    "world_active": "Close the running host before setting up a character.",
    "invalid_profile": "Choose an existing character slot in this host world.",
    "invitation_exists": "Choose a new file for the friend invitation.",
    "source_required": "First create and save a character through ordinary New Game, then select that save.",
    "invalid_source": "Select a valid character save that has not been enrolled.",
    "source_changed": "The approved source changed; character setup has stopped.",
    "source_already_enrolled": "This source is already approved for another character.",
    "already_enrolled": "This character already has a canonical save; use normal Host or Join.",
    "recovery_required": "An existing character attempt requires recovery; its files are retained.",
    "pending_battle": "An unresolved battle requires recovery before character setup.",
    "mirror_active": "Another game or controller owns this character's save.",
    "connection_timeout": "The host did not authenticate this character before the timeout.",
    "connection_lost": "The authenticated host connection is unavailable.",
    "session_changed": "The authenticated character session changed; setup has stopped.",
    "setup_failed": "Character setup could not complete; private recovery files are retained.",
}


class LauncherSetupError(ValueError):
    def __init__(self, code):
        self.code = code if code in _MESSAGES else "setup_failed"
        super().__init__(_MESSAGES[self.code])


@dataclass(frozen=True)
class SetupStatus:
    """Public progress carries no credentials, source paths, or error details."""
    phase: str
    code: str


def _error(error):
    code = getattr(error, "code", None)
    if code in {"runtime_hash", "runtime_manifest", "runtime_path", "runtime_unlisted",
                "runtime_size", "game_changed", "build_mismatch"}:
        code = "installation_changed"
    elif code in {"host_active", "store_in_use", "server_active"}:
        code = "world_active"
    elif code in {"pending_export", "pending_trade", "invalid_journal", "revision_conflict",
                  "journal_changed", "trade_conflict", "mirror_changed", "startup_active",
                  "enrollment_conflict"}:
        code = "recovery_required"
    elif code == "invalid_enrollment":
        code = "invalid_source"
    elif isinstance(error, ConnectionError):
        code = "connection_lost"
    return LauncherSetupError(code)


def _installation(installation):
    if not isinstance(installation, GameInstallation):
        raise LauncherSetupError("invalid_configuration")
    try:
        installation.verify()
    except Exception:
        raise LauncherSetupError("installation_changed") from None


def create_world(installation, private_root, *, player_names, endpoint, port):
    """Explicitly create one new private world, without starting a listener."""
    try:
        _installation(installation)
        worlds = Path(private_root).resolve() / "worlds"
        worlds.mkdir(mode=0o700, parents=True, exist_ok=True)
        return HostWorld.create(worlds / str(uuid4()), installation.rom_path,
            installation.manifest_path, player_names=player_names, endpoint=endpoint, port=port)
    except Exception as error:
        raise _error(error) from None


def export_friend_invitation(installation, world_directory, slot, destination):
    """Explicit Save As; only a friend's credential is written, never replaced."""
    try:
        _installation(installation)
        host = HostWorld.open(world_directory, installation.rom_path, installation.manifest_path)
        if type(slot) is not int or not 1 <= slot < len(host.accounts):
            raise LauncherSetupError("invalid_profile")
        path = Path(destination).absolute()
        host.export_invitation(slot, path)
        return path
    except FileExistsError:
        raise LauncherSetupError("invitation_exists") from None
    except Exception as error:
        raise _error(error) from None


@asynccontextmanager
async def host_enrollment(installation, private_root, *, world_directory, slot,
                          source_path, bind_address="127.0.0.1", host_route=None,
                          public=False, connection_timeout=10, on_status=None):
    """Approve a selected source and yield a running EnrollmentRuntime.

    Call only after explicit host approval. The player uses ordinary Continue
    and the caller explicitly awaits runtime.enroll() at a safe field point.
    This context owns the child, companion, listener and store in that order.
    It must close before a normal LauncherSession starts. New trades stay off.
    """
    store = server = companion = None

    def publish(phase, code):
        if on_status is not None:
            try:
                result = on_status(SetupStatus(phase, code))
                if inspect.iscoroutine(result):
                    result.close()
            except (Exception, asyncio.CancelledError):
                # An observer cannot steal lifecycle ownership or leak errors.
                pass

    async def cleanup():
        try:
            if companion is not None:
                await companion.close()
        finally:
            try:
                if server is not None:
                    await server.close()
            finally:
                if store is not None:
                    store.close()

    try:
        if (type(slot) is not int or not 0 <= slot <= 3
                or type(public) is not bool
                or type(connection_timeout) not in (int, float)
                or not math.isfinite(connection_timeout) or not 0 < connection_timeout <= 60
                or on_status is not None and not callable(on_status)
                or type(bind_address) is not str
                or host_route is not None and type(host_route) is not str
                or not is_local_address(bind_address, allow_lan=True)
                or not is_local_address(host_route or bind_address, allow_lan=True)):
            raise LauncherSetupError("invalid_configuration")
        publish("validating", "installation")
        _installation(installation)
        if source_path is None:
            raise LauncherSetupError("source_required")
        host = HostWorld.open(world_directory, installation.rom_path, installation.manifest_path)
        if slot >= len(host.accounts):
            raise LauncherSetupError("invalid_profile")
        account = host.accounts[slot]
        private = Path(private_root).resolve() / "players" / host.world_id / account.player_id
        configure = host.host_companion_config if slot == 0 else host.invitation(slot).companion_config
        config = configure(installation.rom_path, installation.manifest_path,
            token=secrets.token_bytes(32), private_directory=private, ipc_port=0)
        config = replace(config, server_host=host_route or bind_address)
        store = host.open_store()
        server = WorldServer(ServerConfig(host.build_id, host.ruleset_id), store=store)
        # Binding and the existing exclusive store boot precede approval, so
        # a second host cannot mutate enrollment before discovering contention.
        try:
            await server.start(bind_address, host.port, allow_lan=True,
                               public=public, tls=host.server_tls)
        except OSError:
            raise LauncherSetupError("world_active") from None
        publish("approving", "source_approval")
        approval = approve_enrollment_source(store, account.player_id, source_path)
        companion = Companion(config)
        publish("connecting", "authentication")
        await companion.start()
        try:
            async with asyncio.timeout(connection_timeout):
                while not companion.connected:
                    await asyncio.sleep(.025)
        except TimeoutError:
            raise LauncherSetupError("connection_timeout") from None
        runtime = EnrollmentRuntime(companion, installation.bundle, private,
                                    private / "character.sav", approval)
        async with runtime.open():
            publish("running", "continue_then_enroll")
            yield runtime
        publish("finished", "enrolled" if runtime.result is not None else "enrollment_closed")
    except asyncio.CancelledError:
        publish("blocked", "cancelled")
        raise
    except Exception as error:
        safe = _error(error)
        publish("blocked", safe.code)
        raise safe from None
    finally:
        # runtime.open has already drained its enrollment task and child. Only
        # then may the transport/store and their authenticated lease disappear.
        try:
            _, cancelled = await _finish_even_if_cancelled(asyncio.create_task(cleanup()))
        except Exception:
            publish("blocked", "setup_failed")
            raise LauncherSetupError("setup_failed") from None
        if cancelled:
            raise asyncio.CancelledError()
