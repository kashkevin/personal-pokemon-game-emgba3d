"""The copies of world saves kept on this PC: the newest 40 of each world account (KNOWN_ISSUES MS-216; the owner's
choice of 2026-11-17, docs/owner-decisions.md #53 (b) and #72).

Every save a world acknowledges for a player leaves its bytes beside its receipt in the world account's folder
(live_checkpoint: ``<operation>.flash`` and ``<operation>.export.json``). Only the newest is ever read back
(character_play.account_save: the character comes back from it when the game's own save is not this account's). The
world keeps every save itself (MS-161); these copies are this PC's own backups of them.

``prune_save_copies`` keeps the newest KEEP_SAVE_COPIES copies whose bytes match their receipts and removes the older
ones, a copy's bytes first and then its receipt (a receipt left alone by an interruption is removed the next time). It
removes nothing:

* while an export is pending (``pending-export.json``: its bytes are written before the world acknowledged them);
* unless the newest copy is whole (its bytes match its receipt) - the copy a restore would use;
* that is not a complete pair this module understands: a receipt it cannot read, one of another world account, a
  ``.flash`` with no receipt (a trade's frozen save has the same kind of name).

The trades' files, the recoveries', the grants, the account's own save and every journal are left as they are. It runs
in the menu, after a game in a world ends and at start-up - never while a save is being made - and removes at most
``limit`` copies a run, so a folder that grew before this existed is thinned over a few runs without a long wait.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from uuid import UUID

KEEP_SAVE_COPIES = 40
REMOVE_PER_RUN = 200
RECEIPT_SUFFIX = ".export.json"
FLASH_SUFFIX = ".flash"
FLASH_BYTES = 131072
RECEIPT_LIMIT = 64 * 1024


@dataclass(frozen=True)
class SaveCopy:
    operation_id: str
    revision: int
    sha256: str
    receipt: Path
    flash: Path


@dataclass(frozen=True)
class PruneResult:
    kept: int                       # whole copies kept (at most KEEP_SAVE_COPIES)
    removed: tuple[str, ...]        # the operations whose copy was removed
    reason: str                     # "pruned" | "nothing_to_remove" | "pending_export" | "newest_not_whole" | "unreadable"


def _canonical_uuid(value) -> bool:
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except ValueError:
        return False


def read_receipt(path, world_id, player_id) -> SaveCopy | None:
    """The copy a receipt describes, or None when it is not a complete receipt of this account."""
    path = Path(path)
    if not path.name.endswith(RECEIPT_SUFFIX):
        return None
    operation = path.name[:-len(RECEIPT_SUFFIX)]
    if not _canonical_uuid(operation):
        return None
    try:
        with path.open("rb") as source:
            raw = source.read(RECEIPT_LIMIT + 1)
        if len(raw) > RECEIPT_LIMIT:
            return None
        record = json.loads(raw)
        intent, checkpoint = record["intent"], record["checkpoint"]
        if intent["operation_id"] != operation or (intent["world_id"], intent["player_id"]) != (world_id, player_id):
            return None
        revision, sha256 = checkpoint["revision"], checkpoint["sha256"]
        if type(revision) is not int or revision < 1 or not isinstance(sha256, str) or len(sha256) != 64:
            return None
    except (OSError, ValueError, KeyError, TypeError, UnicodeError, RecursionError):
        return None
    return SaveCopy(operation, revision, sha256, path, path.with_name(operation + FLASH_SUFFIX))


def is_whole(copy: SaveCopy) -> bool:
    """Its bytes are there and match its receipt."""
    try:
        with copy.flash.open("rb") as source:
            payload = source.read(FLASH_BYTES + 1)
    except OSError:
        return False
    return len(payload) == FLASH_BYTES and hashlib.sha256(payload).hexdigest() == copy.sha256


def save_copies(folder, world_id, player_id) -> list[SaveCopy]:
    """This account's receipts in its folder, newest first (by the world's revision)."""
    copies = []
    with os.scandir(folder) as entries:
        for entry in entries:
            if entry.name.endswith(RECEIPT_SUFFIX) and entry.is_file(follow_symlinks=False):
                copy = read_receipt(Path(folder) / entry.name, world_id, player_id)
                if copy is not None:
                    copies.append(copy)
    copies.sort(key=lambda copy: (copy.revision, copy.operation_id), reverse=True)
    return copies


def _remove(path: Path) -> bool:
    """One plain try (a file another program holds is left for the next run): True when it is gone."""
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError:
        return False
    return True


def prune_save_copies(folder, world_id, player_id, *, keep=KEEP_SAVE_COPIES, limit=REMOVE_PER_RUN) -> PruneResult:
    folder = Path(folder)
    if keep < 1:
        raise ValueError("at least one copy is always kept")
    try:
        if (folder / "pending-export.json").exists():
            return PruneResult(0, (), "pending_export")
        copies = save_copies(folder, world_id, player_id)
    except OSError:
        return PruneResult(0, (), "unreadable")
    if not copies:
        return PruneResult(0, (), "nothing_to_remove")
    if not is_whole(copies[0]):
        return PruneResult(0, (), "newest_not_whole")
    kept, older = [copies[0]], []
    for copy in copies[1:]:
        if len(kept) < keep:
            if is_whole(copy):
                kept.append(copy)
            # a copy among the newest that is not whole is neither counted nor removed
        else:
            older.append(copy)
    removed = []
    for copy in reversed(older[-max(0, limit):] if limit > 0 else []):     # the oldest first
        if _remove(copy.flash) and _remove(copy.receipt):
            removed.append(copy.operation_id)
    return PruneResult(len(kept), tuple(removed), "pruned" if removed else "nothing_to_remove")


def prune_all_accounts(private_root, *, keep=KEEP_SAVE_COPIES, limit=REMOVE_PER_RUN) -> dict:
    """At start-up: every world account's folder on this PC (``players/<world>/<player>``). Returns
    {(world_id, player_id): PruneResult} for the folders it looked at; a folder it cannot read is skipped."""
    results = {}
    players = Path(private_root) / "players"
    try:
        worlds = sorted(entry for entry in players.iterdir() if entry.is_dir() and _canonical_uuid(entry.name))
    except OSError:
        return results
    for world in worlds:
        try:
            accounts = sorted(entry for entry in world.iterdir() if entry.is_dir() and _canonical_uuid(entry.name))
        except OSError:
            continue
        for account in accounts:
            results[(world.name, account.name)] = prune_save_copies(account, world.name, account.name, keep=keep, limit=limit)
    return results
