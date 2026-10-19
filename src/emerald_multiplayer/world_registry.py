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

Every text value is stored as exact ``str``. Callers may hand in a ``str`` subclass (``launcher_worlds.LocalAddress``, which carries
the address's kind and label); it is copied to plain text when the record is built, never stored as it is, and the record is still
checked strictly. A record that does not pass raises ``WorldRegistryError`` naming the setting, for the menu to show.
"""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
from pathlib import Path
import time

from .host_world import HOST_FORMAT
from .invitations import _json, _read
from .shell_store import JsonStore, StoreUnavailable, is_uuid, text_ok, time_ok

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


_PROBLEMS = {
    "world_id": "the world's ID is not usable",
    "folder": "the world's folder name is not usable",
    "name": "the world name is not usable (1 to 32 printable characters)",
    "kind": "the kind of world is not known",
    "created": "the creation time is not usable",
    "last_hosted": "the last hosted time is not usable",
    "bind_address": "the address to listen on is not a numeric address of this PC",
    "internet": "the Internet access setting is not usable",
    "address": "the public address is not usable (up to 253 printable characters)",
    "enrollment": "the new players setting is not usable",
}


def _plain(value):
    """``value`` as exact ``str`` when it is any ``str`` (a subclass such as LocalAddress included); anything else unchanged."""
    return str.__str__(value) if isinstance(value, str) else value


def _bind_ok(value):
    if type(value) is not str:
        return False
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def _world_problem(world):
    """The first field of one world record that is not usable, or None."""
    if type(world) is not dict or set(world) != _FIELDS:
        return "fields"
    checks = (
        ("world_id", is_uuid(world["world_id"])),
        ("folder", text_ok(world["folder"], 128) and "/" not in world["folder"] and "\\" not in world["folder"]
         and world["folder"] not in (".", "..")),
        ("name", text_ok(world["name"], 32)),
        ("kind", world["kind"] in KINDS),
        ("created", time_ok(world["created"])),
        ("last_hosted", world["last_hosted"] is None or time_ok(world["last_hosted"])),
        ("internet", type(world["internet"]) is bool),
        ("enrollment", type(world["enrollment"]) is bool),
        ("bind_address", _bind_ok(world["bind_address"])),
        ("address", text_ok(world["address"], 253, empty=True)),
    )
    return next((field for field, ok in checks if not ok), None)


def _validate(record):
    if set(record) != {"format", "worlds"} or type(record["worlds"]) is not list or len(record["worlds"]) > MAX_WORLDS:
        raise ValueError("invalid world registry")
    ids, folders = set(), set()
    for world in record["worlds"]:
        problem = _world_problem(world)
        if problem is not None:
            raise ValueError(f"invalid world record: {problem}")
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

    def _save(self, worlds):
        """Save a changed list for the menu: a record that does not pass raises WorldRegistryError naming the setting (nothing is
        written). A damaged file without a backup still raises StoreUnavailable."""
        self._check(worlds)
        self._write(worlds)

    @staticmethod
    def _check(worlds):
        if len(worlds) > MAX_WORLDS:
            raise WorldRegistryError("world_limit", f"this PC already keeps {MAX_WORLDS} worlds, the most it can list; delete one first")
        try:
            _validate({"format": FORMAT, "worlds": worlds})
        except ValueError:
            for world in worlds:
                problem = _world_problem(world)
                if problem is not None:
                    raise WorldRegistryError("world_record_invalid", _PROBLEMS.get(problem, "the world's settings are not usable")) from None
            raise WorldRegistryError("world_exists", "another world on this PC already has this ID or folder") from None

    @staticmethod
    def _record(world_id, folder, name, *, kind, created, bind_address, internet, address):
        return dict(world_id=_plain(world_id), folder=_plain(folder), name=_plain(name), kind=_plain(kind), created=created,
                    last_hosted=None, bind_address=_plain(bind_address), internet=internet, address=_plain(address), enrollment=True)

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
        default_bind = _plain(default_bind) if _bind_ok(_plain(default_bind)) else LOOPBACK
        hints = {_plain(folder): _plain(bind) for folder, bind in (hints or {}).items()}
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
            bind = hints.get(child.name, default_bind)      # an earlier launcher's address only if it is a usable one
            worlds.append(self._record(descriptor["world_id"], child.name, name, kind="server", created=modified,
                                       bind_address=bind if _bind_ok(bind) else default_bind, internet=False, address=""))
            changed = True
        if changed:
            try:
                self._save(worlds)
            except (OSError, ValueError, StoreUnavailable):
                # Listing never fails because a newly found folder could not be added: it stays on disk untouched and is listed
                # as needing attention; the next listing tries again.
                stored = {world["folder"] for world in self._store.record["worlds"]}
                for world in worlds:
                    if world["folder"] not in stored:
                        self.damaged[world["folder"]] = "found, but the list of worlds could not be saved"
                worlds = [dict(world) for world in self._store.record["worlds"]]
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

    def check_new(self, name, *, kind="server", bind_address=LOOPBACK, internet=False, address=""):
        """Raise WorldRegistryError if a world with these settings could not be registered, before anything is created."""
        from uuid import uuid4
        worlds = [dict(item) for item in self._store.record["worlds"]]
        worlds.append(self._record(str(uuid4()), "new-world-check", name, kind=kind, created=self.clock(), bind_address=bind_address,
                                   internet=internet, address=address))
        self._check(worlds)

    def register(self, world, name, *, kind="server", bind_address=LOOPBACK, internet=False, address=""):
        """Register a world that was just created (the folder is already on disk)."""
        worlds = [dict(item) for item in self._store.record["worlds"]]
        if any(item["world_id"] == world.world_id for item in worlds):
            raise WorldRegistryError("world_exists", "this world is already registered")
        worlds.append(self._record(world.world_id, Path(world.directory).name, name, kind=kind, created=self.clock(),
                                   bind_address=bind_address, internet=internet, address=address))
        self._save(worlds)

    def configure(self, world_id, **changes):
        allowed = {"name", "bind_address", "internet", "address", "enrollment"}
        if set(changes) - allowed:
            raise ValueError("unknown world setting")
        worlds = [dict(item) for item in self._store.record["worlds"]]
        for item in worlds:
            if item["world_id"] == world_id:
                item.update({key: _plain(value) for key, value in changes.items()})
                self._save(worlds)
                return
        raise KeyError("no such world")

    def remove(self, world_id):
        """Delete a world from this PC after the player confirmed: its folder moves to ``worlds-deleted/<UTC time>-<folder>``
        (kept, never destroyed) and the registry forgets it. Returns the new folder."""
        import os
        worlds = [dict(item) for item in self._store.record["worlds"]]
        record = next((item for item in worlds if item["world_id"] == world_id), None)
        if record is None:
            raise KeyError("no such world")
        source = self.worlds_directory / record["folder"]
        target_root = self.private_root / "worlds-deleted"
        target_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        target = target_root / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(self.clock())) + "-" + record["folder"])
        if source.exists():
            os.replace(source, target)
        self._write([item for item in worlds if item["world_id"] != world_id])
        return target

    def touch_hosted(self, world_id):
        worlds = [dict(item) for item in self._store.record["worlds"]]
        for item in worlds:
            if item["world_id"] == world_id:
                item["last_hosted"] = self.clock()
                self._write(worlds)
                return
        raise KeyError("no such world")
