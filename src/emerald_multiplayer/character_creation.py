"""First-time character creation from the in-game menu, host or friend, with nothing for the player to select or import.

The existing, tested pieces do the work; this module only chains them and takes away the clicking:

1. **Create.** ``DraftRuntime`` opens the game for an ordinary New Game (name, starter, Save), in a private folder of its own.
   The result is a closed, unassigned save: the *source* of the character.
2. **Approve.** The source is recorded as this account's one approved source. The host's own PC does it for the host's character
   (``launcher_setup.host_enrollment``: the host approves what it created itself). A friend's PC sends it to the host's server
   (``enrollment_protocol``), which checks it and records it for the authenticated account.
3. **Enroll.** The game opens on the approved source (the player chooses Continue) and, at the first safe place outside menus and
   battles, the first checkpoint is made by the existing live-save path (``EnrollmentRuntime.enroll``): every Pokémon gets its
   owner identity from the server's allocation grants, the game closes and the character is the account's canonical save. The old
   "Finish enrollment" button is replaced by trying again every second or so, exactly what pressing it repeatedly would do.

Nothing is guessed or forced: a game closed before the safe place, a source the host refuses, a source already used by another
account or an interrupted attempt all stop with their own code and leave the private files for recovery, as in the launcher.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import base64
import hashlib
from dataclasses import replace
import math
from pathlib import Path
import secrets

from .companion import Companion
from .draft_runtime import DraftRuntime, DraftRuntimeError
from .enrollment_protocol import EnrollmentRemoteError
from .enrollment_runtime import EnrollmentApproval, EnrollmentRuntime, EnrollmentRuntimeError, _source_bytes
from .invitations import Invitation
from .launcher_session import GameInstallation
from .live_checkpoint import LiveSaveError
from .player_runtime import _finish_even_if_cancelled, _preflight_launch
from .protocol import CHECKPOINT_CHUNK_BYTES
from .shell_store import is_uuid

MESSAGES = {
    "game_closed": "The game was closed before your adventure started. Open it again and choose CONTINUE.",
    "connection_timeout": "The server did not answer in time. Check the address and that the host is running, then try again.",
    "connection_lost": "The connection to the server was lost. Nothing was lost; try again.",
    "enrollment_disabled": "The host has turned off creating new characters in this world.",
    "already_enrolled": "This account already has a character.",
    "source_already_enrolled": "That character is already used by another account.",
    "enrollment_conflict": "This account already started with a different character; its files were kept.",
    "invalid_enrollment": "That character cannot be used: it must be a new character saved after choosing a starter.",
    "draft_failed": "Creating your character could not finish. Nothing was changed; try again.",
    "starter_required": "Choose a starter and save in the game before closing it.",
    "save_required": "Save in the game (START menu, SAVE) before closing it.",
    "game_failed": "The game closed unexpectedly while creating your character. Try again.",
    "installation_changed": "The installed game could not be verified.",
    "recovery_required": "An earlier setup of this character got further than it can safely restart; its files were kept.",
    "setup_failed": "Setting up your character could not finish. Your files were kept; try again.",
    "pokemon_owned_here": "One of this character's Pokémon already belongs to another trainer in this world (a copy of a Pokémon "
                          "traded away here), so the host's world refused it. Your character was not changed.",
    "transfer_unsupported": "The host's EmeraldTogether is older than yours and cannot take characters coming back. "
                            "Ask the host to install the same version.",
    "trade_recovery_required": "A trade of this account in the host's world is not finished. Play once in that world to "
                               "finish it, then try again.",
    "battle_reserved": "A battle of this account in the host's world is not finished yet. Try again in a moment.",
    "unreadable_character": "This character's save could not be read. Restore an earlier version in Characters.",
}


class CreationError(ValueError):
    def __init__(self, code):
        self.code = code if code in MESSAGES else "setup_failed"
        super().__init__(MESSAGES[self.code])


def message_for(error):
    code = getattr(error, "code", None)
    return MESSAGES.get(code, MESSAGES["setup_failed"])


async def create_draft(installation, private_root, *, on_status=None):
    """The player's New Game in the game window; returns the DraftSource (path, sha256, party_count) once the game is closed."""
    draft = DraftRuntime(installation, private_root)
    try:
        async with draft.open() as game:
            if on_status is not None:
                on_status("draft_running")
            await game.wait()
            return draft.finish()
    except DraftRuntimeError as error:
        raise CreationError(error.code) from None


async def submit_source(companion, payload, *, mode="enroll", reply=None):
    """Send a friend's source to the host's server and return its SHA-256 once the server has recorded it for this account.
    ``mode`` "transfer": the account already has a character and this is the character coming back (character_transfers);
    ``reply`` receives the server's final answer (its base revision for a transfer)."""
    sha256 = hashlib.sha256(payload).hexdigest()
    extra = {"mode": "transfer"} if mode == "transfer" else {}
    try:
        status = await companion.enrollment_rpc("status")
        if status["state"] == "checkpointed" and mode != "transfer":
            raise CreationError("already_enrolled")
        if mode == "transfer" and not status.get("transfers"):
            raise CreationError("transfer_unsupported")
        begin = await companion.enrollment_rpc("begin", size=len(payload), sha256=sha256, **extra)
        upload_id, offset = begin["upload_id"], begin["next_offset"]
        if not 0 <= offset <= len(payload):
            raise CreationError("setup_failed")
        while offset < len(payload):
            chunk = payload[offset:offset + CHECKPOINT_CHUNK_BYTES]
            answer = await companion.enrollment_rpc("chunk", upload_id=upload_id, offset=offset,
                                                   data_b64=base64.b64encode(chunk).decode("ascii"))
            if answer["next_offset"] != offset + len(chunk):
                raise CreationError("setup_failed")
            offset += len(chunk)
        done = await companion.enrollment_rpc("commit", upload_id=upload_id, size=len(payload), sha256=sha256, **extra)
    except EnrollmentRemoteError as error:
        code = error.code if error.code in ("source_already_enrolled", "enrollment_conflict", "invalid_enrollment",
                                            "enrollment_disabled", "already_enrolled", "pokemon_owned_here",
                                            "transfer_unsupported", "trade_recovery_required", "battle_reserved",
                                            "invalid_fields") else "setup_failed"
        if code == "invalid_fields":
            code = "transfer_unsupported"     # an older host does not know returning characters
        raise CreationError(code) from None
    except (ConnectionError, TimeoutError):
        raise CreationError("connection_lost") from None
    expected = "transferred" if mode == "transfer" else "enrolled"
    if done["state"] != expected or done.get("source_sha256") != sha256:
        raise CreationError("setup_failed")
    if reply is not None:
        reply.update(done)
    return sha256


@asynccontextmanager
async def remote_enrollment(installation, private_root, *, invitation_path, route_host, route_port, source_path=None,
                            connection_timeout=10, on_status=None, character_payload=None, mode="enroll"):
    """The friend's counterpart of ``launcher_setup.host_enrollment``: connect with the account's own invitation, have the host's
    server record the source, and yield an open ``EnrollmentRuntime``. ``route_host`` is a numeric address (already resolved),
    or None when the account connects through its world's relay (its route file).

    ``character_payload`` (a universal character's latest save, any world): after connecting, the server says whether this
    account already has a character here; the save is detached from its old world with this world's wallet sequence
    (``character_transfer``), kept beside the account as ``outgoing-character.sav`` and registered: as the account's first
    character, or as the character coming back (``mode`` is then chosen by the server's answer)."""
    companion = None

    def publish(phase):
        if on_status is not None:
            try:
                on_status(phase)
            except Exception:                                        # noqa: BLE001 - an observer never owns the lifecycle
                pass

    try:
        if (type(connection_timeout) not in (int, float) or not math.isfinite(connection_timeout)
                or not 0 < connection_timeout <= 60 or not isinstance(installation, GameInstallation)):
            raise CreationError("setup_failed")
        try:
            installation.verify()
        except Exception:
            raise CreationError("installation_changed") from None
        invitation = Invitation.load(invitation_path)
        root = Path(private_root).resolve()
        private = root / "players" / invitation.world_id / invitation.player_id
        launch_root = root / "launches"
        executable, _ = installation.bundle.verify()
        _preflight_launch(executable, installation.rom_path, private / "character.sav", private, launch_root=launch_root)
        config = invitation.companion_config(installation.rom_path, installation.manifest_path, token=secrets.token_bytes(32),
                                             private_directory=private, ipc_port=0)
        if route_host is not None:                     # None: the account's relay route (route.json), read by companion_config
            config = replace(config, server_host=route_host, server_port=route_port)
        payload = _source_bytes(source_path) if source_path is not None else None
        companion = Companion(config)
        publish("connecting")
        await companion.start()
        try:
            async with asyncio.timeout(connection_timeout):
                while not companion.connected:
                    await asyncio.sleep(.025)
        except TimeoutError:
            raise CreationError("connection_timeout") from None
        publish("approving")
        if character_payload is not None:
            from .character_transfer import TransferError, detach_from_world
            from .live_checkpoint import _atomic
            try:
                status = await companion.enrollment_rpc("status")
            except EnrollmentRemoteError:
                raise CreationError("setup_failed") from None
            except (ConnectionError, TimeoutError):
                raise CreationError("connection_lost") from None
            mode = "transfer" if status.get("state") == "checkpointed" else "enroll"
            wallet = status.get("wallet_seq", 0)
            try:
                detached = detach_from_world(character_payload, wallet_seq=wallet if type(wallet) is int and 0 <= wallet <= 0xFFFF else 0)
            except TransferError:
                raise CreationError("unreadable_character") from None
            private.mkdir(mode=0o700, parents=True, exist_ok=True)
            source_path = private.parent / f".{private.name}.outgoing-character.sav"
            _atomic(source_path, detached.payload)
            payload = detached.payload
        if payload is None:
            raise CreationError("setup_failed")
        reply = {}
        sha256 = await submit_source(companion, payload, mode=mode, reply=reply)
        base_revision = reply.get("base_revision", 0) if mode == "transfer" else 0
        if mode == "transfer":
            from .enrollment_runtime import set_aside_previous_saves
            if type(base_revision) is not int or base_revision < 1:
                raise CreationError("setup_failed")
            set_aside_previous_saves(private)
        approval = EnrollmentApproval(companion.world_id, config.player_id, config.build_id, config.ruleset_id, sha256,
                                      Path(source_path).resolve(strict=True), payload, base_revision=base_revision)
        # The menu's "Continue setting up my character" after a game that crashed or was closed before the safe place.
        runtime = EnrollmentRuntime(companion, installation.bundle, private, private / "character.sav", approval,
                                    launch_root=launch_root, restart_abandoned=True)
        async with runtime.open():
            publish("running")
            yield runtime
    except asyncio.CancelledError:
        raise
    except CreationError:
        raise
    except EnrollmentRuntimeError as error:
        raise CreationError(error.code if error.code in ("source_already_enrolled", "already_enrolled", "recovery_required")
                            else "setup_failed") from None
    except Exception as error:                                        # noqa: BLE001 - mapped to a stable, safe code
        raise CreationError("setup_failed") from error
    finally:
        if companion is not None:
            _, cancelled = await _finish_even_if_cancelled(asyncio.create_task(companion.close()))
            if cancelled:
                raise asyncio.CancelledError()


def _closed(game):
    """A game that ended before the safe place: closed by the player (exit code 0) or not (a crash, a kill): "game_failed",
    so the player is not told to have closed a game that crashed (the owner's report, 2026-10-17)."""
    code = None if game is None else game.process.returncode
    return CreationError("game_closed" if code == 0 else "game_failed")


async def finish_when_ready(runtime, *, interval=1.5, on_waiting=None):
    """Enroll at the first safe place. Until then the game's own refusal ("not ready") is the answer and nothing has started."""
    while True:
        game = getattr(runtime, "_game", None)
        if game is not None and game.process.returncode is not None:
            raise _closed(game)
        if getattr(runtime.companion, "_bridge", None) is None:
            if on_waiting is not None:
                on_waiting()
            await asyncio.sleep(interval)
            continue
        try:
            return await runtime.enroll()
        except LiveSaveError as error:
            if error.safe_to_retry is True:
                if on_waiting is not None:
                    on_waiting()
                await asyncio.sleep(interval)
                continue
            if await _game_ended(getattr(runtime, "_game", None)):
                raise _closed(runtime._game) from None
            raise
        except EnrollmentRuntimeError as error:
            if error.code == "game_closed" or await _game_ended(getattr(runtime, "_game", None)):
                raise _closed(getattr(runtime, "_game", None)) from None
            raise
        except ConnectionError:
            # A game that crashes mid-request takes its bridge with it: the request fails as a lost connection a moment
            # before the process is seen to end. Say what happened to the game, not "the connection was lost".
            if await _game_ended(getattr(runtime, "_game", None)):
                raise _closed(runtime._game) from None
            raise


async def _game_ended(game, grace=3.0):
    """Whether the enrollment game has ended, or does within ``grace`` seconds."""
    if game is None:
        return False
    if game.process.returncode is not None:
        return True
    try:
        await asyncio.wait_for(asyncio.shield(game.process.wait()), grace)
    except TimeoutError:
        return False
    return True


async def create_character(installation, private_root, *, role, world_directory=None, invitation_path=None, route_host=None,
                           route_port=None, draft=None, on_status=None, on_draft=None, interval=1.5, drafter=create_draft):
    """The whole of first-time setup for one account. ``draft`` is an existing DraftSource to resume from (a closed, valid
    source left by an earlier attempt that did not finish enrolling); otherwise the player's New Game runs first.

    Returns the DraftSource used, so the caller can note which source this account was created from."""
    from .launcher_setup import host_enrollment
    if draft is None:
        draft = await drafter(installation, private_root, on_status=on_status)
        if on_draft is not None:
            on_draft(draft)
    if on_status is not None:
        on_status("draft_ready")
    if role == "host":
        if world_directory is None:
            raise CreationError("setup_failed")
        context = host_enrollment(installation, private_root, world_directory=world_directory, slot=0,
                                  source_path=draft.source_path, bind_address="127.0.0.1", host_route="127.0.0.1",
                                  expected_source_sha256=draft.sha256, restart_abandoned=True)
    else:
        if invitation_path is None or route_host is None or route_port is None:
            raise CreationError("setup_failed")
        context = remote_enrollment(installation, private_root, invitation_path=invitation_path, route_host=route_host,
                                    route_port=route_port, source_path=draft.source_path, on_status=on_status)
    try:
        async with context as runtime:
            if on_status is not None:
                on_status("choose_continue")
            await finish_when_ready(runtime, interval=interval,
                                    on_waiting=(lambda: on_status("waiting_safe_place")) if on_status is not None else None)
    except CreationError:
        raise
    except Exception as error:                                         # noqa: BLE001
        code = getattr(error, "code", None)
        raise CreationError(code if code in MESSAGES else "setup_failed") from error
    if on_status is not None:
        on_status("enrolled")
    return draft


__all__ = ["CreationError", "create_character", "create_draft", "finish_when_ready", "message_for", "remote_enrollment",
           "submit_source", "is_uuid", "MESSAGES"]
