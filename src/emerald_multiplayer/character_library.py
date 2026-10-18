"""The player's characters on this PC: one trainer each, usable in every world.

A character is created once (the game's New Game: name, look, starter, Save) and then played anywhere: in the player's own
worlds (Solo or hosted) and in friends' worlds. Its Pokémon, levels, items and progress go with it (the owner's decision,
2026-10-18). This module keeps, per character:

* ``characters/<character_id>/character.json`` - its stable id, trainer name and id, when it was made and last played, where
  its latest save came from (a world account, or the New Game itself), and which account it uses in each world;
* ``characters/<character_id>/current.sav`` - its latest save, exactly as the game or the world wrote it;
* ``characters/<character_id>/history/`` - every earlier latest save (newest 40 kept), so a version can be restored.

``<private>/shell/character-library.json`` remembers the active character and which character last played each world
account (so the same account is never mistaken for another character's progress).

Every write is atomic, the previous record is kept as ``.bak``, and a damaged character folder is reported and left
untouched. Nothing here deletes a character: "Delete" moves its folder to ``characters-deleted/`` after the player confirms.
The world files (``players/<world>/<account>/``) are only read here, never moved or changed.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import time
from uuid import uuid4

from .flash import FlashError, LAYOUT_ID, OWNERSHIP_LAYOUT_ID, inspect_flash
from .live_checkpoint import _atomic, _sync_directory
from .shell_store import JsonStore, is_uuid, text_ok, time_ok

FORMAT = "emerald-character-v1"
INDEX_FORMAT = "emerald-character-library-v1"
INDEX_NAME = "character-library.json"
HISTORY_LIMIT = 40
MAX_CHARACTERS = 64
MAX_SAVE = 131072 + 16

# Pokémon Emerald's text encoding for trainer names (English letters, digits and the usual punctuation).
_TEXT = {0x00: " ", 0xAB: "!", 0xAC: "?", 0xAD: ".", 0xAE: "-", 0xB0: "...", 0xB1: '"', 0xB2: '"', 0xB3: "'", 0xB4: "'",
         0xB5: "(m)", 0xB6: "(f)", 0xB8: ",", 0xBA: "/"}
_TEXT.update({0xA1 + i: str(i) for i in range(10)})
_TEXT.update({0xBB + i: chr(ord("A") + i) for i in range(26)})
_TEXT.update({0xD5 + i: chr(ord("a") + i) for i in range(26)})


def trainer_name(encoded: bytes) -> str:
    text = "".join(_TEXT.get(byte, "?") for byte in encoded).strip()
    return text[:24] or "Trainer"


class LibraryError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class SaveInfo:
    trainer_name: str
    trainer_id: int
    gender: int
    party_count: int
    world_id: str | None          # the world the save belongs to (None: a save with no world, e.g. a New Game)
    player_id: str | None
    sha256: str


def read_save(payload: bytes) -> SaveInfo:
    """What a save says about its trainer. Raises LibraryError when it is not a complete Emerald save."""
    if not isinstance(payload, (bytes, bytearray)) or len(payload) > MAX_SAVE:
        raise LibraryError("unreadable_save", "this is not a game save")
    payload = bytes(payload)
    world = player = None
    try:
        snapshot = inspect_flash(payload, save_profile=LAYOUT_ID)
    except FlashError:
        try:
            snapshot = inspect_flash(payload, save_profile=OWNERSHIP_LAYOUT_ID)
            from .ownership import inspect_ownership
            owned = inspect_ownership(snapshot)
            world, player = owned.world_id, owned.player_id
        except FlashError as error:
            raise LibraryError("unreadable_save", f"the save could not be read: {error}") from None
    meta = snapshot.metadata
    return SaveInfo(trainer_name(meta.name), meta.trainer_id, meta.gender, meta.party_count, world, player,
                    hashlib.sha256(payload).hexdigest())


def _key(world_id, player_id):
    return f"{world_id}/{player_id}"


def _validate_character(record):
    fields = {"format", "character_id", "name", "trainer_id", "gender", "created", "updated", "last_played", "current",
              "accounts", "origin"}
    if set(record) != fields or not is_uuid(record["character_id"]) or not text_ok(record["name"], 24):
        raise ValueError("invalid character")
    if type(record["trainer_id"]) is not int or not 0 <= record["trainer_id"] <= 0xFFFFFFFF or record["gender"] not in (0, 1):
        raise ValueError("invalid trainer")
    if not time_ok(record["created"]) or not time_ok(record["updated"]) or not (record["last_played"] is None or time_ok(record["last_played"])):
        raise ValueError("invalid times")
    current = record["current"]
    if (type(current) is not dict or set(current) != {"sha256", "world_id", "player_id", "saved"}
            or type(current["sha256"]) is not str or len(current["sha256"]) != 64
            or not (current["world_id"] is None or is_uuid(current["world_id"]))
            or not (current["player_id"] is None or is_uuid(current["player_id"])) or not time_ok(current["saved"])):
        raise ValueError("invalid current save")
    accounts = record["accounts"]
    if type(accounts) is not dict or len(accounts) > 256:
        raise ValueError("invalid accounts")
    for world, player in accounts.items():
        if not is_uuid(world) or not is_uuid(player):
            raise ValueError("invalid account")
    if record["origin"] not in ("new_game", "migrated", "recovered", "imported"):
        raise ValueError("invalid origin")
    return record


def _validate_index(record):
    if set(record) != {"format", "active", "bindings"}:
        raise ValueError("invalid library index")
    if not (record["active"] is None or is_uuid(record["active"])):
        raise ValueError("invalid active character")
    bindings = record["bindings"]
    if type(bindings) is not dict or len(bindings) > 1024:
        raise ValueError("invalid bindings")
    for key, value in bindings.items():
        world, _, player = key.partition("/")
        if not is_uuid(world) or not is_uuid(player) or type(value) is not dict or set(value) != {"character_id", "sha256"} \
                or not is_uuid(value["character_id"]) or not (value["sha256"] is None or (type(value["sha256"]) is str and len(value["sha256"]) == 64)):
            raise ValueError("invalid binding")
    return record


@dataclass(frozen=True)
class Character:
    character_id: str
    name: str
    trainer_id: int
    gender: int
    created: float
    updated: float
    last_played: float | None
    world_id: str | None           # where the latest save came from (None: never played in a world yet)
    player_id: str | None
    sha256: str
    accounts: dict                 # world_id -> the account this character uses there
    origin: str
    folder: Path

    @property
    def save_path(self):
        return self.folder / "current.sav"


class CharacterLibrary:
    def __init__(self, private_root, *, clock=time.time):
        self.private_root = Path(private_root)
        self.clock = clock
        self.root = self.private_root / "characters"
        self.deleted_root = self.private_root / "characters-deleted"
        self._index = JsonStore(self.private_root / "shell" / INDEX_NAME, INDEX_FORMAT,
                                lambda: {"format": INDEX_FORMAT, "active": None, "bindings": {}}, _validate_index, clock=clock)
        self.damaged = {}

    # ---------------------------------------------------------------- reading

    def _store(self, character_id):
        return JsonStore(self.root / character_id / "character.json", FORMAT, lambda: None, _validate_character, clock=self.clock)

    def _character(self, record):
        current = record["current"]
        return Character(record["character_id"], record["name"], record["trainer_id"], record["gender"], record["created"],
                         record["updated"], record["last_played"], current["world_id"], current["player_id"], current["sha256"],
                         dict(record["accounts"]), record["origin"], self.root / record["character_id"])

    def all(self):
        """Every usable character, most recently played first; unusable folders are listed in ``damaged`` and left alone."""
        self.damaged = {}
        found = []
        try:
            children = sorted(child for child in self.root.iterdir() if child.is_dir() and not child.is_symlink())
        except OSError:
            children = []
        for child in children[:MAX_CHARACTERS * 2]:
            store = self._store(child.name) if is_uuid(child.name) else None
            record = store.record if store is not None and store.available else None
            if record is None or record["character_id"] != child.name:
                self.damaged[child.name] = "unreadable"
                continue
            character = self._character(record)
            try:
                payload = character.save_path.read_bytes()
            except OSError:
                self.damaged[child.name] = "missing save"
                continue
            if hashlib.sha256(payload).hexdigest() != character.sha256:
                self.damaged[child.name] = "save changed"
                continue
            found.append(character)
        found.sort(key=lambda c: (c.last_played or 0, c.updated), reverse=True)
        return found

    def get(self, character_id):
        return next((c for c in self.all() if c.character_id == character_id), None)

    def save_bytes(self, character):
        payload = character.save_path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != character.sha256:
            raise LibraryError("save_changed", "this character's save changed on disk; restore an earlier version")
        return payload

    @property
    def available(self):
        return self._index.available

    def active(self):
        active = self._index.record["active"]
        characters = self.all()
        chosen = next((c for c in characters if c.character_id == active), None)
        if chosen is None and characters:
            chosen = characters[0]
        return chosen

    def set_active(self, character_id):
        if self.get(character_id) is None:
            raise LibraryError("not_found", "that character is not on this PC")
        record = dict(self._index.record, active=character_id)
        self._index.save(record)

    def binding(self, world_id, player_id):
        """(character_id, sha256 of the save it left there) of the character that last played this account, or None."""
        value = self._index.record["bindings"].get(_key(world_id, player_id))
        return (value["character_id"], value["sha256"]) if value else None

    def find(self, *, trainer_id=None, sha256=None):
        for character in self.all():
            if sha256 is not None and character.sha256 == sha256:
                return character
            if trainer_id is not None and character.trainer_id == trainer_id:
                return character
        return None

    # ---------------------------------------------------------------- writing

    def _write_save(self, folder, payload):
        """current.sav becomes ``payload``; the previous one goes into history first."""
        current = folder / "current.sav"
        history = folder / "history"
        if current.exists():
            old = current.read_bytes()
            if old == payload:
                return
            history.mkdir(mode=0o700, parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(self.clock()))
            name = f"{stamp}-{hashlib.sha256(old).hexdigest()[:12]}.sav"
            _atomic(history / name, old)
            kept = sorted(history.glob("*.sav"))
            for path in kept[:-HISTORY_LIMIT]:
                path.unlink()
        _atomic(current, payload)
        _sync_directory(folder)

    def create(self, payload, *, origin="new_game", world_id=None, player_id=None, name=None):
        """A new character from a save (a New Game, or an existing world character being migrated). Returns it."""
        info = read_save(payload)
        if len(self.all()) >= MAX_CHARACTERS:
            raise LibraryError("too_many", "this PC already has the most characters it can keep")
        character_id = str(uuid4())
        folder = self.root / character_id
        folder.mkdir(mode=0o700, parents=True, exist_ok=False)
        self._write_save(folder, bytes(payload))
        now = self.clock()
        accounts = {world_id: player_id} if world_id and player_id else {}
        record = dict(format=FORMAT, character_id=character_id, name=(name or info.trainer_name)[:24], trainer_id=info.trainer_id,
                      gender=info.gender, created=now, updated=now, last_played=None,
                      current=dict(sha256=info.sha256, world_id=world_id, player_id=player_id, saved=now),
                      accounts=accounts, origin=origin)
        self._store(character_id).save(record)
        if world_id and player_id:
            self._bind(world_id, player_id, character_id, info.sha256)
        if self._index.record["active"] is None:
            self._index.save(dict(self._index.record, active=character_id))
        return self.get(character_id)

    def _bind(self, world_id, player_id, character_id, sha256):
        bindings = dict(self._index.record["bindings"])
        bindings[_key(world_id, player_id)] = {"character_id": character_id, "sha256": sha256}
        self._index.save(dict(self._index.record, bindings=bindings))

    def record_world_save(self, character_id, world_id, player_id, payload, *, played=True):
        """After the character played in a world account: its latest save is that account's save (an ownership save of that
        world). The previous latest save is kept in history."""
        store = self._store(character_id)
        if not store.available or store.record is None:
            raise LibraryError("not_found", "that character is not on this PC")
        info = read_save(payload)
        if (info.world_id, info.player_id) != (world_id, player_id):
            raise LibraryError("wrong_world", "that save belongs to another world or account")
        record = dict(store.record)
        if info.trainer_id != record["trainer_id"]:
            raise LibraryError("wrong_trainer", "that save belongs to another trainer")
        self._write_save(self.root / character_id, bytes(payload))
        now = self.clock()
        record.update(updated=now, last_played=now if played else record["last_played"], name=info.trainer_name,
                      current=dict(sha256=info.sha256, world_id=world_id, player_id=player_id, saved=now),
                      accounts=dict(record["accounts"], **{world_id: player_id}))
        store.save(record)
        self._bind(world_id, player_id, character_id, info.sha256)
        return self.get(character_id)

    def remember_account(self, character_id, world_id, player_id):
        store = self._store(character_id)
        record = dict(store.record)
        record["accounts"] = dict(record["accounts"], **{world_id: player_id})
        store.save(record)

    def rename(self, character_id, name):
        if not text_ok(name, 24):
            raise LibraryError("invalid_name", "a name is 1 to 24 characters")
        store = self._store(character_id)
        store.save(dict(store.record, name=name.strip(), updated=self.clock()))

    def history(self, character):
        try:
            return sorted((path for path in (character.folder / "history").glob("*.sav")), reverse=True)
        except OSError:
            return []

    def backup_now(self, character):
        """Keep a copy of the current save in history now (Characters, Back up)."""
        history = character.folder / "history"
        history.mkdir(mode=0o700, parents=True, exist_ok=True)
        payload = self.save_bytes(character)
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(self.clock()))
        path = history / f"{stamp}-{character.sha256[:12]}-backup.sav"
        if not path.exists():
            _atomic(path, payload)
        return path

    def restore(self, character, history_path):
        """Make an earlier save the current one (the present one goes to history first). Same trainer only."""
        history_path = Path(history_path)
        if history_path.parent != character.folder / "history":
            raise LibraryError("not_found", "that is not one of this character's earlier saves")
        payload = history_path.read_bytes()
        info = read_save(payload)
        if info.trainer_id != character.trainer_id:
            raise LibraryError("wrong_trainer", "that save belongs to another trainer")
        self._write_save(character.folder, payload)
        store = self._store(character.character_id)
        now = self.clock()
        store.save(dict(store.record, updated=now,
                        current=dict(sha256=info.sha256, world_id=info.world_id, player_id=info.player_id, saved=now)))
        return self.get(character.character_id)

    def delete(self, character_id):
        """Move a character's folder to characters-deleted/ (after the player confirmed). Its world saves stay in the worlds."""
        folder = self.root / character_id
        if not is_uuid(character_id) or not folder.is_dir():
            raise LibraryError("not_found", "that character is not on this PC")
        self.deleted_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(self.clock()))
        target = self.deleted_root / f"{stamp}-{character_id}"
        os.replace(folder, target)
        record = dict(self._index.record)
        if record["active"] == character_id:
            record["active"] = None
        record["bindings"] = {k: v for k, v in record["bindings"].items() if v["character_id"] != character_id}
        self._index.save(record)
        return target

    def touch(self, character_id):
        store = self._store(character_id)
        store.save(dict(store.record, last_played=self.clock()))


__all__ = ["Character", "CharacterLibrary", "LibraryError", "SaveInfo", "read_save", "trainer_name"]
