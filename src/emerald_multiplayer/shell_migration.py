"""Bringing what the earlier launcher left on this PC into the in-game menu, without moving or rewriting any of it.

What the earlier versions created and where it stays:

* **Worlds** (``worlds/<folder>/host.json``, the database and keys) - listed by their stable world ID; the registry only adds a name and
  network settings (``world_registry``).
* **Characters** (``players/<world_id>/<player_id>/character.sav`` and its recovery files) - the same folders are used as they are;
  the character links (``character_links``) note which account each belongs to. A host's character is linked to its world's host account.
* **Friend invitations** the player used (their paths are in ``launcher-recent.json``) - each becomes a saved server. Its invitation is
  copied once into the character's own folder (never replacing a different one there); the original file is left where it is.
* **The last session and when each world was played** (``launcher-recent.json``) - read, never written; copied to ``shell/backups`` first.

Only unambiguous matches are imported: an invitation that disagrees with the one already stored for its account, or a second world folder
that claims an ID already registered, is listed in ``problems`` and left alone. Everything is idempotent: running it again changes nothing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import shutil
import time

from .character_links import CharacterLinks, character_state, profile_directory
from .invitations import Invitation, InvitationError
from .launcher_recent import FILE_NAME as RECENT_FILE, RecentStore
from .saved_servers import InvitationConflict, SavedServers, store_invitation
from .shell_store import JsonStore, time_ok
from .world_registry import LOOPBACK, WorldRegistry

FORMAT = "emerald-shell-migration-v1"
FILE_NAME = "migration.json"


@dataclass
class MigrationResult:
    worlds: int = 0
    characters: int = 0
    servers: int = 0
    problems: list = field(default_factory=list)


def _validate(record):
    if (set(record) != {"format", "version", "done", "worlds", "servers", "problems"} or record["version"] != 1
            or not time_ok(record["done"]) or type(record["problems"]) is not list or len(record["problems"]) > 64):
        raise ValueError("invalid migration record")
    return record


def _empty():
    return {"format": FORMAT, "version": 1, "done": 0, "worlds": 0, "servers": 0, "problems": []}


def migrate(private_root, registry, links, servers, *, clock=time.time):
    """Idempotent import of the earlier launcher's data. Returns what is new this time."""
    private_root = Path(private_root)
    result = MigrationResult()
    shell = registry.directory
    recent_path = private_root / RECENT_FILE
    recent = RecentStore(private_root)
    if recent_path.exists():
        backups = shell / "backups"
        stamp = int(clock())
        try:
            backups.mkdir(parents=True, exist_ok=True, mode=0o700)
            if not any(backups.glob("launcher-recent-*.json")):
                shutil.copyfile(recent_path, backups / f"launcher-recent-{stamp}.json")
        except OSError:
            pass
    hints = {}
    last = recent.last
    if last is not None and last.mode == "host":
        hints[last.world_name] = last.address
    before = {world["world_id"] for world in registry._store.record["worlds"]}
    entries = registry.entries(hints=hints)
    result.worlds = len({entry.world_id for entry in entries} - before)
    for folder, reason in registry.damaged.items():
        result.problems.append(f"world folder {folder}: {reason}")
    for entry in entries:
        for slot, player_id, display_name in entry.accounts:
            state = character_state(private_root, entry.world_id, player_id)
            if slot == 0 or state != "none":
                if links.get(entry.world_id, player_id) is None and state != "none":
                    result.characters += 1
                link = links.ensure(entry.world_id, player_id, "host" if slot == 0 else "friend", slot, entry.name, display_name)
                if state != "none" and link["stage"] != "enrolled":
                    links.set_stage(entry.world_id, player_id, "enrolled")
        played = recent.world_played(entry.folder)
        host_id = entry.accounts[0][1]
        if played is not None and (links.get(entry.world_id, host_id) or {}).get("last_played") is None:
            try:
                links._update(entry.world_id, host_id, last_played=played)
            except KeyError:
                pass
    # Friend invitations the player used.
    candidates = list(recent.invitations)
    if last is not None and last.mode == "join" and last.selection not in candidates:
        candidates.append(last.selection)
    for path in candidates:
        try:
            invitation = Invitation.load(path)
        except (OSError, InvitationError, ValueError):
            continue
        if servers.for_account(invitation.world_id, invitation.player_id) is not None:
            continue
        try:
            store_invitation(private_root, invitation)
        except InvitationConflict:
            result.problems.append(f"invitation for {invitation.display_name}: a different one is already stored for that account")
            continue
        except OSError:
            continue
        name = servers.unique_name(f"{invitation.display_name}'s server")
        try:
            servers.add(name, invitation.endpoint, invitation.port, invitation.world_id, invitation.player_id, invitation.slot,
                        invitation.display_name)
        except ValueError:
            result.problems.append(f"invitation for {invitation.display_name}: could not be saved")
            continue
        state = character_state(private_root, invitation.world_id, invitation.player_id)
        link = links.ensure(invitation.world_id, invitation.player_id, "friend", invitation.slot, name, invitation.display_name)
        if state != "none" and link["stage"] != "enrolled":
            links.set_stage(invitation.world_id, invitation.player_id, "enrolled")
        if last is not None and last.mode == "join" and last.selection == path:
            try:
                links._update(invitation.world_id, invitation.player_id, last_played=last.played)
            except KeyError:
                pass
        result.servers += 1
    record = JsonStore(shell / FILE_NAME, FORMAT, _empty, _validate, clock=clock)
    if result.worlds or result.servers or result.characters or record.record["done"] == 0 or result.problems:
        try:
            record.save({"format": FORMAT, "version": 1, "done": clock(),
                         "worlds": record.record["worlds"] + result.worlds, "servers": record.record["servers"] + result.servers,
                         "problems": (record.record["problems"] + result.problems)[-64:]})
        except Exception:                                              # noqa: BLE001 - the note is informational
            pass
    return result


__all__ = ["MigrationResult", "migrate", "LOOPBACK", "CharacterLinks", "SavedServers", "WorldRegistry", "profile_directory"]
