"""Saved servers: the shortcuts behind Join Server.

A shortcut is a name, an address and a port, plus the stable world and player identifiers of the account it signs in as. The address
is only where to knock: the world is recognised by its identifiers and its pinned certificate, so a host who moves to another
address is followed by editing the shortcut's address, and the character stays linked (``character_links``). Removing a shortcut
removes only this record: the character's folder and its invitation copy stay, and pasting the same invite code again links to the
same character.

The account's sign-in credential is not stored here. It lives in the private invitation copy in the character's own folder
(``players/<world>/<player>/invitation.json``, created once, never replaced).

A shortcut also remembers its route: ``relay`` is None for a direct connection, or {"address", "port"} of the world's relay
(``relay.py``). Records written before relays existed have no ``relay`` field and are direct. Adding or editing a shortcut also
writes the account's route file (``network_settings.save_join_route``) beside its invitation copy, which is what the game reads
when it connects, so a session started for the account uses the same route as its shortcut.
"""
from __future__ import annotations

import os
from pathlib import Path
import time
from uuid import uuid4

from .character_links import profile_directory
from .invitations import Invitation, InvitationError, _write_new
from .invite_code import valid_address, valid_port
from .shell_store import JsonStore, is_uuid, text_ok, time_ok

FORMAT = "emerald-saved-servers-v1"
FILE_NAME = "servers.json"
MAX_SERVERS = 64
INVITATION_NAME = "invitation.json"

_FIELDS = {"id", "name", "address", "port", "world_id", "player_id", "slot", "display_name", "added", "last_joined"}
_UNSET = object()


def _relay_ok(value):
    from .relay import valid_endpoint
    return value is None or (type(value) is dict and set(value) == {"address", "port"} and valid_endpoint(value["address"], value["port"]))


def _relay_record(relay):
    if relay is None:
        return None
    relay = tuple(relay)
    record = {"address": relay[0], "port": relay[1]} if len(relay) == 2 else None
    if record is None or not _relay_ok(record):
        raise ValueError("relay address or port is not usable")
    return record


def relay_of(server):
    """(address, port) of a saved server's relay, or None for a direct route."""
    relay = server.get("relay")
    return None if relay is None else (relay["address"], relay["port"])


class InvitationConflict(ValueError):
    """A different invitation already exists for this account: never replaced (a person has to resolve it)."""


def invitation_path(private_root, world_id, player_id):
    return profile_directory(private_root, world_id, player_id) / INVITATION_NAME


def store_invitation(private_root, invitation):
    """Keep a private copy of a friend invitation in its character's folder. Returns the path. An identical copy is accepted; a
    different one for the same account raises InvitationConflict and nothing changes."""
    path = invitation_path(private_root, invitation.world_id, invitation.player_id)
    if path.is_symlink():
        raise InvitationConflict("linked invitation location")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    wanted = invitation.dumps()
    try:
        _write_new(path, wanted)
    except FileExistsError:
        try:
            existing = Invitation.load(path)
        except (OSError, InvitationError):
            raise InvitationConflict("an unreadable invitation is already stored for this account") from None
        if (existing.credential != invitation.credential or existing.certificate_sha256 != invitation.certificate_sha256
                or existing.slot != invitation.slot or existing.build_id != invitation.build_id):
            raise InvitationConflict("a different invitation is already stored for this account")
    return path


def _validate(record):
    if set(record) != {"format", "servers"} or type(record["servers"]) is not list or len(record["servers"]) > MAX_SERVERS:
        raise ValueError("invalid saved servers")
    ids, accounts = set(), set()
    for server in record["servers"]:
        if (type(server) is not dict or set(server) not in (_FIELDS, _FIELDS | {"relay"}) or not _relay_ok(server.get("relay"))
                or not is_uuid(server["id"]) or not text_ok(server["name"], 48)
                or not valid_address(server["address"]) or not valid_port(server["port"])
                or not is_uuid(server["world_id"]) or not is_uuid(server["player_id"])
                or type(server["slot"]) is not int or not 1 <= server["slot"] <= 3
                or not text_ok(server["display_name"], 24) or not time_ok(server["added"])
                or not (server["last_joined"] is None or time_ok(server["last_joined"]))):
            raise ValueError("invalid saved server")
        key = (server["world_id"], server["player_id"])
        if server["id"] in ids or key in accounts:
            raise ValueError("duplicate saved server")
        ids.add(server["id"])
        accounts.add(key)
    return record


def _empty():
    return {"format": FORMAT, "servers": []}


class SavedServers:
    def __init__(self, directory=None, *, clock=time.time, private_root=None):
        """``directory`` is the menu's ``<private>/shell`` folder; ``private_root`` (default: the parent of a folder named
        "shell") is where the accounts' route files live."""
        self.clock = clock
        path = None if directory is None else Path(directory) / FILE_NAME
        self._store = JsonStore(path, FORMAT, _empty, _validate, clock=clock)
        if private_root is None and directory is not None and Path(directory).name == "shell":
            private_root = Path(directory).parent
        self.private_root = None if private_root is None else Path(private_root)

    def _route(self, server):
        """Keep the account's route file in step with the shortcut (no file at all means direct, so a direct shortcut writes one
        only to replace an earlier relay route)."""
        if self.private_root is None:
            return
        from .network_settings import route_path, save_join_route
        relay = relay_of(server)
        if relay is None and not route_path(self.private_root, server["world_id"], server["player_id"]).exists():
            return
        save_join_route(self.private_root, server["world_id"], server["player_id"], relay)

    @property
    def available(self):
        return self._store.available

    @property
    def recovered(self):
        return self._store.recovered

    def all(self):
        """Most recently joined first, never-joined ones in the order they were added."""
        servers = [dict(server) for server in self._store.record["servers"]]
        return sorted(servers, key=lambda server: (server["last_joined"] is None, -(server["last_joined"] or 0), server["added"]))

    def get(self, server_id):
        for server in self._store.record["servers"]:
            if server["id"] == server_id:
                return dict(server)
        return None

    def for_account(self, world_id, player_id):
        for server in self._store.record["servers"]:
            if server["world_id"] == world_id and server["player_id"] == player_id:
                return dict(server)
        return None

    def _write(self, servers):
        self._store.save({"format": FORMAT, "servers": servers})

    def unique_name(self, wanted):
        names = {server["name"].casefold() for server in self._store.record["servers"]}
        if wanted.casefold() not in names:
            return wanted
        for number in range(2, 100):
            candidate = f"{wanted} ({number})"
            if candidate.casefold() not in names:
                return candidate
        return wanted

    def add(self, name, address, port, world_id, player_id, slot, display_name, *, relay=None):
        """Save a server. If this account already has a shortcut, that one is kept (its address, port and route follow the new
        values) and returned with created=False: an account never gets two shortcuts. ``relay`` = (address, port) saves a relay
        route; None a direct one."""
        relay = _relay_record(relay)
        servers = [dict(server) for server in self._store.record["servers"]]
        for server in servers:
            if server["world_id"] == world_id and server["player_id"] == player_id:
                if (server["address"], server["port"], server.get("relay")) != (address, port, relay):
                    server["address"], server["port"], server["relay"] = address, port, relay
                    self._write(servers)
                self._route(server)
                return dict(server), False
        if len(servers) >= MAX_SERVERS:
            raise ValueError("too many saved servers")
        server = dict(id=str(uuid4()), name=self.unique_name(name), address=address, port=port, world_id=world_id,
                      player_id=player_id, slot=slot, display_name=display_name, added=self.clock(), last_joined=None, relay=relay)
        servers.append(server)
        self._write(servers)
        self._route(server)
        return dict(server), True

    def edit(self, server_id, *, name=None, address=None, port=None, relay=_UNSET):
        """Change the shortcut's name and where it connects (``relay``: (address, port), or None for direct). Its world and player
        identifiers never change here."""
        servers = [dict(server) for server in self._store.record["servers"]]
        for server in servers:
            if server["id"] == server_id:
                if name is not None:
                    server["name"] = name
                if address is not None:
                    server["address"] = address
                if port is not None:
                    server["port"] = port
                if relay is not _UNSET:
                    server["relay"] = _relay_record(relay)
                self._write(servers)
                if relay is not _UNSET:
                    self._route(server)
                return dict(server)
        raise KeyError("no such saved server")

    def touch(self, server_id):
        servers = [dict(server) for server in self._store.record["servers"]]
        for server in servers:
            if server["id"] == server_id:
                server["last_joined"] = self.clock()
                self._write(servers)
                return
        raise KeyError("no such saved server")

    def remove(self, server_id):
        """Remove the shortcut only. Characters and invitation copies are not touched."""
        servers = [dict(server) for server in self._store.record["servers"] if server["id"] != server_id]
        if len(servers) == len(self._store.record["servers"]):
            return False
        self._write(servers)
        return True


__all__ = ["InvitationConflict", "SavedServers", "invitation_path", "relay_of", "store_invitation", "INVITATION_NAME", "os"]
