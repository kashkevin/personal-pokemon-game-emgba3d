"""The server worlds on this PC, by stable world ID.

A world is a folder under the launcher's private ``worlds`` directory that holds its database, its host certificate and ``host.json``
(created by ``launcher_setup.create_world``). This registry adds what a person needs to find and run it: a name, and the network
settings the host chose (which of this PC's addresses it listens on, whether it is open to the Internet, the address friends are told
to use). It is keyed by the world's stable ID, never by its folder, name or address, so renaming a world or moving its address does
not make it a different world.

Listing is read-only: a world is read from its descriptor without opening its database or taking any lease, so a world that is being
hosted right now is still listed. A world folder the registry has not met (made by an earlier version of the launcher) is recognised
by its ID and registered the first time it is listed; nothing in it is moved or rewritten. Creating a world never overwrites or deletes
another, and a restart never resets one (the folder is only ever opened).
"""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
from pathlib import Path
import time

from .host_world import HOST_FORMAT
from .invitations import _json, _read
from .shell_store import JsonStore, is_uuid, text_ok, time_ok

FORMAT = "emerald-shell-worlds-v1"
FILE_NAME = "worlds.json"
KINDS = ("server", "adventure")
MAX_WORLDS = 64
DEFAULT_PORT = 7777
LOOPBACK = "127.0.0.1"

_FIELDS = {"world_id", "folder", "name", "kind", "created", "last_hosted", "bind_address", "internet", "address", "enrollment"}


class WorldRegistryError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def read_descriptor(folder):
    """The public part of a world's host.json: its ID, port, endpoint and account labels (never a credential)."""
    folder = Path(folder)
    if folder.is_symlink() or not folder.is_dir() or (folder / "creation-failed.json").exists():
        raise WorldRegistryError("world_invalid", "this world folder is not usable")
    value = _json(_read(folder / "host.json", 16_384))
    accounts = value.get("accounts")
    if (value.get("format") != HOST_FORMAT or not is_uuid(value.get("world_id")) or type(accounts) is not list
            or not 1 <= len(accounts) <= 4 or type(value.get("port")) is not int or type(value.get("endpoint")) is not str):
        raise WorldRegistryError("world_invalid", "this world's descriptor is not usable")
    labels = []
    for slot, account in enumerate(accounts):
        if (type(account) is not dict or account.get("slot") != slot or not is_uuid(account.get("player_id"))
                or not text_ok(account.get("display_name"), 24)):
            raise WorldRegistryError("world_invalid", "this world's accounts are not usable")
        labels.append((slot, account["player_id"], account["display_name"]))
    return dict(world_id=value["world_id"], port=value["port"], endpoint=value["endpoint"], accounts=tuple(labels))


@dataclass(frozen=True)
class WorldEntry:
    world_id: str
    folder: Path
    name: str
    kind: str
    created: float
    last_hosted: float | None
    bind_address: str
    internet: bool
    address: str
    enrollment: bool
    port: int
    endpoint: str
    accounts: tuple       # (slot, player_id, display_name)

    @property
    def host_name(self):
        return self.accounts[0][2]

    @property
    def player_names(self):
        return tuple(account[2] for account in self.accounts)


def _validate(record):
    if set(record) != {"format", "worlds"} or type(record["worlds"]) is not list or len(record["worlds"]) > MAX_WORLDS:
        raise ValueError("invalid world registry")
    ids, folders = set(), set()
    for world in record["worlds"]:
        if (type(world) is not dict or set(world) != _FIELDS or not is_uuid(world["world_id"]) or not text_ok(world["folder"], 128)
                or "/" in world["folder"] or "\\" in world["folder"] or world["folder"] in (".", "..")
                or not text_ok(world["name"], 32) or world["kind"] not in KINDS or not time_ok(world["created"])
                or not (world["last_hosted"] is None or time_ok(world["last_hosted"]))
                or type(world["internet"]) is not bool or type(world["enrollment"]) is not bool or type(world["bind_address"]) is not str
                or not text_ok(world["address"], 253, empty=True)):
            raise ValueError("invalid world record")
        try:
            ipaddress.ip_address(world["bind_address"])
        except ValueError:
            raise ValueError("invalid bind address") from None
        if world["world_id"] in ids or world["folder"] in folders:
            raise ValueError("duplicate world")
        ids.add(world["world_id"])
        folders.add(world["folder"])
    return record


def _empty():
    return {"format": FORMAT, "worlds": []}


def valid_world_name(name):
    return text_ok(name, 32) and name == name.strip()


def free_port(taken):
    port = DEFAULT_PORT
    while port in taken and port < 65535:
        port += 1
    return port


class WorldRegistry:
    def __init__(self, private_root, directory=None, *, clock=time.time):
        self.private_root = Path(private_root)
        self.clock = clock
        self.directory = Path(directory) if directory is not None else self.private_root / "shell"
        self._store = JsonStore(self.directory / FILE_NAME, FORMAT, _empty, _validate, clock=clock)
        self.damaged = {}          # folder name -> reason, for worlds that are on disk but not usable

    @property
    def available(self):
        return self._store.available

    @property
    def recovered(self):
        return self._store.recovered

    @property
    def worlds_directory(self):
        return self.private_root / "worlds"

    def _write(self, worlds):
        self._store.save({"format": FORMAT, "worlds": worlds})

    def _entry(self, record, descriptor):
        return WorldEntry(record["world_id"], self.worlds_directory / record["folder"], record["name"], record["kind"],
                          record["created"], record["last_hosted"], record["bind_address"], record["internet"], record["address"],
                          record["enrollment"], descriptor["port"], descriptor["endpoint"], descriptor["accounts"])

    def _unique_name(self, wanted, worlds):
        names = {world["name"].casefold() for world in worlds}
        if wanted.casefold() not in names:
            return wanted
        for number in range(2, 100):
            candidate = f"{wanted} ({number})"[:32]
            if candidate.casefold() not in names:
                return candidate
        return wanted[:28] + " (x)"

    def entries(self, *, default_bind=LOOPBACK, hints=None):
        """Every usable world on disk, newest activity first. A folder the registry has not met is registered under a name made from
        its host ('Kevin's world'); ``hints`` maps a folder name to a bind address an earlier launcher remembered for it."""
        hints = hints or {}
        worlds = [dict(world) for world in self._store.record["worlds"]]
        known = {world["folder"] for world in worlds}
        self.damaged = {}
        found = {}
        try:
            children = sorted(child for child in self.worlds_directory.iterdir() if child.is_dir() and not child.is_symlink())
        except OSError:
            children = []
        changed = False
        for child in children[:MAX_WORLDS]:
            if not (child / "host.json").is_file():
                continue
            try:
                descriptor = read_descriptor(child)
            except (OSError, ValueError):
                self.damaged[child.name] = "unreadable"
                continue
            found[child.name] = descriptor
            if child.name in known:
                continue
            if any(world["world_id"] == descriptor["world_id"] for world in worlds):
                self.damaged[child.name] = "duplicate"     # two folders claim one world ID: neither is replaced
                continue
            if not self._store.available or len(worlds) >= MAX_WORLDS:
                continue
            host = descriptor["accounts"][0][2]
            name = self._unique_name(f"{host}'s world"[:32], worlds)
            try:
                modified = (child / "host.json").stat().st_mtime
            except OSError:
                modified = self.clock()
            worlds.append(dict(world_id=descriptor["world_id"], folder=child.name, name=name, kind="server", created=modified,
                               last_hosted=None, bind_address=hints.get(child.name, default_bind), internet=False, address="",
                               enrollment=True))
            changed = True
        if changed:
            self._write(worlds)
        entries = [self._entry(world, found[world["folder"]]) for world in worlds if world["folder"] in found]
        entries.sort(key=lambda entry: (entry.last_hosted or entry.created), reverse=True)
        return entries

    def get(self, world_id):
        for entry in self.entries():
            if entry.world_id == world_id:
                return entry
        return None

    def name_taken(self, name, *, except_world=None):
        return any(world["name"].casefold() == name.casefold() and world["world_id"] != except_world
                   for world in self._store.record["worlds"])

    def used_ports(self):
        return {entry.port for entry in self.entries()}

    def register(self, world, name, *, kind="server", bind_address=LOOPBACK, internet=False, address=""):
        """Register a world that was just created (the folder is already on disk)."""
        worlds = [dict(item) for item in self._store.record["worlds"]]
        if any(item["world_id"] == world.world_id for item in worlds):
            raise WorldRegistryError("world_exists", "this world is already registered")
        worlds.append(dict(world_id=world.world_id, folder=Path(world.directory).name, name=name, kind=kind, created=self.clock(),
                           last_hosted=None, bind_address=bind_address, internet=internet, address=address, enrollment=True))
        self._write(worlds)

    def configure(self, world_id, **changes):
        allowed = {"name", "bind_address", "internet", "address", "enrollment"}
        if set(changes) - allowed:
            raise ValueError("unknown world setting")
        worlds = [dict(item) for item in self._store.record["worlds"]]
        for item in worlds:
            if item["world_id"] == world_id:
                item.update(changes)
                self._write(worlds)
                return
        raise KeyError("no such world")

    def touch_hosted(self, world_id):
        worlds = [dict(item) for item in self._store.record["worlds"]]
        for item in worlds:
            if item["world_id"] == world_id:
                item["last_hosted"] = self.clock()
                self._write(worlds)
                return
        raise KeyError("no such world")
