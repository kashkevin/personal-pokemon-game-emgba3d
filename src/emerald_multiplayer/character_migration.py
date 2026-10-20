"""Bringing the characters of an earlier version into the character library, without changing any original file.

Before universal characters, a character existed only inside one world account (``players/<world>/<account>/character.sav``)
and an unfinished first-time setup left a New Game save in ``drafts/<id>/character.sav``. On first start of this version:

* every world account with a readable save becomes a library character (its save copied, the account remembered as where its
  latest save came from), unless the library already knows that account;
* the New Game save of an unfinished setup that the menu recorded (``characters.json`` stage "draft") becomes a character too,
  so the player continues with it instead of creating another one;
* any other New Game save in ``drafts/`` is not imported automatically (they are often several attempts of the same
  trainer); Characters, "Recover a character" lists them, newest first, with the trainer's name and date.

The originals stay exactly where they are. A save that cannot be read is skipped and listed in ``problems``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path

from .character_library import CharacterLibrary, LibraryError, read_save
from .shell_store import is_uuid


@dataclass
class LibraryMigration:
    imported: list = field(default_factory=list)      # (character name, where from)
    problems: list = field(default_factory=list)      # (path, reason)


@dataclass(frozen=True)
class RecoverableDraft:
    path: Path
    sha256: str
    trainer_name: str
    modified: float


def _read(path):
    try:
        with Path(path).open("rb") as source:
            payload = source.read(131072 + 17)
        return payload, read_save(payload)
    except (OSError, LibraryError):
        return None, None


def migrate_characters(private_root, library: CharacterLibrary, links=None) -> LibraryMigration:
    result = LibraryMigration()
    root = Path(private_root)
    known = {(c.world_id, c.player_id) for c in library.all()}
    known_sha = {c.sha256 for c in library.all()}
    players = root / "players"
    try:
        worlds = sorted(child for child in players.iterdir() if child.is_dir() and is_uuid(child.name))
    except OSError:
        worlds = []
    for world in worlds:
        try:
            accounts = sorted(child for child in world.iterdir() if child.is_dir() and is_uuid(child.name))
        except OSError:
            continue
        for account in accounts:
            if library.binding(world.name, account.name) is not None or (world.name, account.name) in known:
                continue
            save = account / "character.sav"
            if not save.is_file():
                continue
            payload, info = _read(save)
            if info is None:
                result.problems.append((str(save), "unreadable save"))
                continue
            if (info.world_id, info.player_id) != (world.name, account.name):
                result.problems.append((str(save), "save of another account"))
                continue
            if info.sha256 in known_sha:
                continue
            # The trainer's own name (in the save) is the character's name; the world's account label is not.
            character = library.create(payload, origin="migrated", world_id=world.name, player_id=account.name)
            known_sha.add(info.sha256)
            result.imported.append((character.name, f"world {world.name[:8]}"))
    if links is not None:
        for link in links.all():
            draft = link.get("draft")
            if link.get("stage") != "draft" or not draft:
                continue
            payload, info = _read(draft.get("source", ""))
            if info is None or info.sha256 != draft.get("sha256") or info.sha256 in known_sha or info.world_id is not None:
                continue
            character = library.create(payload, origin="recovered")
            library.remember_account(character.character_id, link["world_id"], link["player_id"])
            known_sha.add(info.sha256)
            result.imported.append((character.name, "an unfinished setup"))
    return result


def recoverable_drafts(private_root, library: CharacterLibrary):
    """New Game saves of earlier attempts that are not in the library, newest first."""
    known = {c.sha256 for c in library.all()}
    found = []
    try:
        folders = [child for child in (Path(private_root) / "drafts").iterdir() if child.is_dir()]
    except OSError:
        folders = []
    for folder in folders:
        save = folder / "character.sav"
        if not save.is_file():
            continue
        payload, info = _read(save)
        # Update 32: a draft with no Pokemon yet (the short introduction's save) is a character too.
        if info is None or info.world_id is not None or info.sha256 in known:
            continue
        try:
            modified = save.stat().st_mtime
        except OSError:
            modified = 0
        if any(item.sha256 == info.sha256 for item in found):
            continue
        found.append(RecoverableDraft(save, info.sha256, info.trainer_name, modified))
    found.sort(key=lambda item: item.modified, reverse=True)
    return found


def recover_draft(library: CharacterLibrary, draft: RecoverableDraft):
    payload = Path(draft.path).read_bytes()
    if hashlib.sha256(payload).hexdigest() != draft.sha256:
        raise LibraryError("save_changed", "that save changed; look again")
    return library.create(payload, origin="recovered")


__all__ = ["LibraryMigration", "RecoverableDraft", "migrate_characters", "recover_draft", "recoverable_drafts"]
