"""Which character belongs to which world account on this PC.

A character is identified by the pair (stable world ID, stable player ID): both are fixed when the host creates the world and never
change when the host's address, the server's name, the port or a trainer's name changes. The character's files live in
``players/<world_id>/<player_id>/`` under the launcher's private folder (``profile_directory``); that path is the whole link, so a
shortcut, a server name or an address can be edited or removed without ever touching a character. This module keeps the readable
bookkeeping beside it: who the account is, which world it is in and how far first-time setup got.

Nothing here creates, moves, replaces or deletes a character file.
"""
from __future__ import annotations

from pathlib import Path
import time

from .shell_store import JsonStore, is_uuid, text_ok, time_ok

FORMAT = "emerald-character-links-v1"
FILE_NAME = "characters.json"
ROLES = ("host", "friend")
STAGES = ("none", "draft", "enrolled")
MAX_LINKS = 256

_FIELDS = {"world_id", "player_id", "role", "slot", "world_name", "display_name", "created", "last_played", "stage", "draft"}


def profile_directory(private_root, world_id, player_id):
    """The one folder of this account's character on this PC."""
    if not is_uuid(world_id) or not is_uuid(player_id):
        raise ValueError("world and player must be canonical identifiers")
    return Path(private_root) / "players" / world_id / player_id


def character_state(private_root, world_id, player_id):
    """What the files say: 'ready' (a character is here), 'interrupted' (first-time setup began and did not finish) or 'none'."""
    folder = profile_directory(private_root, world_id, player_id)
    try:
        if (folder / "pending-enrollment.json").exists():
            return "interrupted"
        save = folder / "character.sav"
        if (folder / "enrollment-completed.json").exists() or (save.is_file() and save.stat().st_size > 0):
            return "ready"
    except OSError:
        pass
    return "none"


def _validate(record):
    if set(record) != {"format", "links"} or type(record["links"]) is not list or len(record["links"]) > MAX_LINKS:
        raise ValueError("invalid character links")
    seen = set()
    for link in record["links"]:
        if (type(link) is not dict or set(link) != _FIELDS or not is_uuid(link["world_id"]) or not is_uuid(link["player_id"])
                or link["role"] not in ROLES or type(link["slot"]) is not int or not 0 <= link["slot"] <= 3
                or not text_ok(link["world_name"], 64) or not text_ok(link["display_name"], 24)
                or not time_ok(link["created"]) or not (link["last_played"] is None or time_ok(link["last_played"]))
                or link["stage"] not in STAGES):
            raise ValueError("invalid character link")
        draft = link["draft"]
        if draft is not None and (type(draft) is not dict or set(draft) != {"source", "sha256"}
                                  or not text_ok(draft["source"], 1024) or not text_ok(draft["sha256"], 64)):
            raise ValueError("invalid draft record")
        key = (link["world_id"], link["player_id"])
        if key in seen:
            raise ValueError("duplicate character link")
        seen.add(key)
    return record


def _empty():
    return {"format": FORMAT, "links": []}


class CharacterLinks:
    def __init__(self, directory=None, *, clock=time.time):
        self.clock = clock
        path = None if directory is None else Path(directory) / FILE_NAME
        self._store = JsonStore(path, FORMAT, _empty, _validate, clock=clock)

    @property
    def available(self):
        return self._store.available

    @property
    def recovered(self):
        return self._store.recovered

    def all(self):
        return tuple(dict(link) for link in self._store.record["links"])

    def get(self, world_id, player_id):
        for link in self._store.record["links"]:
            if link["world_id"] == world_id and link["player_id"] == player_id:
                return dict(link)
        return None

    def for_world(self, world_id):
        return tuple(dict(link) for link in self._store.record["links"] if link["world_id"] == world_id)

    def _write(self, links):
        self._store.save({"format": FORMAT, "links": links})

    def ensure(self, world_id, player_id, role, slot, world_name, display_name):
        """Record that this account exists on this PC. An existing link keeps its identity, stage and times: only the labels
        (the world's name, the account's name) are refreshed. Never replaces another account's link."""
        links = [dict(link) for link in self._store.record["links"]]
        for link in links:
            if link["world_id"] == world_id and link["player_id"] == player_id:
                if link["world_name"] != world_name or link["display_name"] != display_name:
                    link["world_name"], link["display_name"] = world_name, display_name
                    self._write(links)
                return dict(link)
        link = dict(world_id=world_id, player_id=player_id, role=role, slot=slot, world_name=world_name,
                    display_name=display_name, created=self.clock(), last_played=None, stage="none", draft=None)
        links.append(link)
        self._write(links)
        return dict(link)

    def _update(self, world_id, player_id, **changes):
        links = [dict(link) for link in self._store.record["links"]]
        for link in links:
            if link["world_id"] == world_id and link["player_id"] == player_id:
                link.update(changes)
                self._write(links)
                return dict(link)
        raise KeyError("no such character link")

    def set_stage(self, world_id, player_id, stage, draft=None):
        return self._update(world_id, player_id, stage=stage, draft=draft if stage == "draft" else None)

    def touch(self, world_id, player_id):
        return self._update(world_id, player_id, last_played=self.clock())

    def rename_world(self, world_id, name):
        links = [dict(link) for link in self._store.record["links"]]
        changed = False
        for link in links:
            if link["world_id"] == world_id and link["world_name"] != name:
                link["world_name"] = name
                changed = True
        if changed:
            self._write(links)
