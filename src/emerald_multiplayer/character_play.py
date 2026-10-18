"""Entering a world with a universal character, and keeping the character up to date afterwards.

The menu calls three things:

* ``needs_registration(library, character, world_id, player_id)`` - whether the world account already holds this character's
  latest progress (then the world is simply played) or the character must be registered there first: as the account's
  first character, or as the character coming back with progress made elsewhere (``character_transfers``). No New Game is
  ever needed to enter a world: the character's own save goes in.
* ``register_character(...)`` - that registration, for the player's own world (Solo or hosted: the host's PC approves it
  directly) or for a friend's world (the host's server approves it over the connection). The game opens once on the
  character; the player chooses CONTINUE and it closes by itself when the world has saved the character for the first time.
* ``record_after_session(...)`` - after any game in a world ends, the world account's save becomes the character's latest
  save (the previous one stays in the character's history). ``sync_from_worlds`` does the same at start-up for a game that
  ended while the menu was not running (a crash, a power cut).
"""
from __future__ import annotations

from dataclasses import dataclass
import sqlite3
from pathlib import Path

from .character_library import CharacterLibrary, LibraryError, read_save
from .character_links import character_state, profile_directory


@dataclass(frozen=True)
class EntryPlan:
    register: bool
    reason: str            # "ready" | "new_here" | "coming_back" | "other_character_here"


def needs_registration(private_root, library: CharacterLibrary, character, world_id, player_id) -> EntryPlan:
    """Whether ``character`` must be registered in this world account before playing."""
    binding = library.binding(world_id, player_id)
    ready = character_state(private_root, world_id, player_id) == "ready"
    if binding is None:
        return EntryPlan(True, "new_here" if not ready else "other_character_here")
    if binding[0] != character.character_id:
        return EntryPlan(True, "other_character_here")
    if (character.world_id, character.player_id) == (world_id, player_id) and ready:
        return EntryPlan(False, "ready")
    return EntryPlan(True, "coming_back")


def _owned_for(payload, world_id, player_id):
    try:
        info = read_save(payload)
    except LibraryError:
        return False
    return (info.world_id, info.player_id) == (world_id, player_id)


def account_save(private_root, world_id, player_id):
    """The world account's save on this PC (an ownership save of that world), or None: the game's own save file when it
    belongs to this account, otherwise the newest save the world acknowledged (``<operation>.flash`` beside its
    ``<operation>.export.json`` receipt, live_checkpoint)."""
    import json
    folder = profile_directory(private_root, world_id, player_id)
    try:
        payload = (folder / "character.sav").read_bytes()
        if _owned_for(payload, world_id, player_id):
            return payload
    except OSError:
        pass
    best = None
    try:
        receipts = list(folder.glob("*.export.json"))
    except OSError:
        receipts = []
    for receipt in receipts:
        try:
            record = json.loads(receipt.read_text(encoding="ascii"))
            revision = int(record["checkpoint"]["revision"])
            flash = folder / (receipt.name[:-len(".export.json")] + ".flash")
            payload = flash.read_bytes()
        except (OSError, ValueError, KeyError, TypeError):
            continue
        import hashlib
        if hashlib.sha256(payload).hexdigest() != record["checkpoint"].get("sha256") or not _owned_for(payload, world_id, player_id):
            continue
        if best is None or revision > best[0]:
            best = (revision, payload)
    return best[1] if best else None


def record_after_session(private_root, library: CharacterLibrary, character_id, world_id, player_id):
    """The character's latest save becomes this world account's save. Returns the updated character, or None when the
    account has no readable save (nothing changes then)."""
    payload = account_save(private_root, world_id, player_id)
    if payload is None:
        return None
    return library.record_world_save(character_id, world_id, player_id, payload)


def sync_from_worlds(private_root, library: CharacterLibrary):
    """At start-up: a world account whose save is newer than what its character last took from it (the game ended while the
    menu was not running) updates that character, when the account is still where the character's latest save came from."""
    updated = []
    for character in library.all():
        if character.world_id is None:
            continue
        binding = library.binding(character.world_id, character.player_id)
        if binding is None or binding[0] != character.character_id:
            continue
        payload = account_save(private_root, character.world_id, character.player_id)
        if payload is None:
            continue
        import hashlib
        if hashlib.sha256(payload).hexdigest() == character.sha256:
            continue
        try:
            library.record_world_save(character.character_id, character.world_id, character.player_id, payload, played=False)
            updated.append(character.name)
        except LibraryError:
            continue
    return updated


def local_wallet_seq(world_directory, player_id):
    """The reward wallet sequence the player's own world last saw this account apply (0 when none)."""
    path = Path(world_directory) / "world.sqlite3.wagers.sqlite3"
    if not path.is_file():
        return 0
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
            row = db.execute("SELECT seq FROM wallet_base WHERE player_id=?", (player_id,)).fetchone()
    except sqlite3.Error:
        return 0
    return int(row[0]) if row and 0 <= row[0] <= 0xFFFF else 0


def local_account_revision(world_directory, player_id):
    """The latest checkpoint revision of an account in the player's own (closed) world, read only."""
    path = Path(world_directory) / "world.sqlite3"
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
            row = db.execute("SELECT latest_revision FROM players WHERE player_id=?", (player_id,)).fetchone()
    except sqlite3.Error:
        return None
    return None if row is None else int(row[0])


async def register_character(installation, private_root, library: CharacterLibrary, character, *, role, world_directory=None,
                             world_id=None, player_id=None, invitation_path=None, route_host=None, route_port=None,
                             on_status=None, interval=1.5):
    """Register ``character`` in a world account and return the updated character (its latest save now that account's).

    ``role`` "host": the player's own world (``world_directory``, slot 0 or the account ``player_id``); "friend": a friend's
    world reached with the account's invitation at ``route_host``:``route_port`` (a numeric address)."""
    from .character_creation import CreationError, finish_when_ready, remote_enrollment
    payload = library.save_bytes(character)
    if role == "host":
        from .character_transfer import TransferError, detach_from_world
        from .launcher_setup import host_enrollment, prepare_world_for_returning_characters
        from .live_checkpoint import _atomic
        revision = local_account_revision(world_directory, player_id)
        if revision is None:
            raise CreationError("setup_failed")
        mode = "transfer" if revision > 0 else "enroll"
        if mode == "transfer":
            prepare_world_for_returning_characters(installation, world_directory)
        try:
            detached = detach_from_world(payload, wallet_seq=local_wallet_seq(world_directory, player_id))
        except TransferError:
            raise CreationError("unreadable_character") from None
        profile = profile_directory(private_root, world_id, player_id)
        profile.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        source = profile.parent / f".{profile.name}.outgoing-character.sav"
        _atomic(source, detached.payload)
        from .host_world import HostWorld
        host = HostWorld.open(world_directory, installation.rom_path, installation.manifest_path)
        slot = next(account.slot for account in host.accounts if account.player_id == player_id)
        context = host_enrollment(installation, private_root, world_directory=world_directory, slot=slot, source_path=source,
                                  bind_address="127.0.0.1", host_route="127.0.0.1", expected_source_sha256=detached.sha256,
                                  restart_abandoned=True, mode=mode)
    else:
        context = remote_enrollment(installation, private_root, invitation_path=invitation_path, route_host=route_host,
                                    route_port=route_port, character_payload=payload, on_status=on_status)
    try:
        async with context as runtime:
            if on_status is not None:
                on_status("choose_continue")
            await finish_when_ready(runtime, interval=interval,
                                    on_waiting=(lambda: on_status("waiting_safe_place")) if on_status is not None else None)
    except CreationError:
        raise
    except Exception as error:                                         # noqa: BLE001 - one stable code for the menu
        code = getattr(error, "code", None)
        from .character_creation import MESSAGES
        raise CreationError(code if code in MESSAGES else "setup_failed") from error
    if on_status is not None:
        on_status("enrolled")
    updated = record_after_session(private_root, library, character.character_id, world_id, player_id)
    if updated is None:
        raise CreationError("setup_failed")
    return updated


__all__ = ["EntryPlan", "account_save", "local_account_revision", "local_wallet_seq", "needs_registration",
           "record_after_session", "register_character", "sync_from_worlds"]
