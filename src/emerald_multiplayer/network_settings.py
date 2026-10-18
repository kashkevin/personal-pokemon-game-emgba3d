"""The host's per-world network choices, and how a friend's account reaches its world.

**Host side** (``<private>/shell/network.json``, one record per world ID; written atomically with a backup, like the other menu
records in ``shell_store``): whether the game may set up the router automatically (UPnP / NAT-PMP, used only while the world
allows Internet connections), and the world's relay: on or off, its address and port, and the world's relay key. The relay key is
generated once per world (32 random bytes) and only ever shown to the relay as an HMAC token for the world's room
(``relay.room_token``); it protects the relay *room* (who may register as this world's host on that relay), not the world: the
world's own TLS identity and the players' credentials are unchanged and stay where they were. It is kept here, not in the world
folder, so nothing inside a world's verified files changes.

**Friend side** (``players/<world>/<player>/route.json`` beside the account's invitation copy): whether the account connects
directly or through a relay. ``Invitation.companion_config`` reads it, so every game started for that account (joining, first-time
character creation) uses the same route. The route only says where to knock; the pinned certificate and credential are checked end
to end either way.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
from pathlib import Path
import re
import secrets
import time

from .live_checkpoint import _atomic, _json_bytes
from .relay import DEFAULT_PORT, valid_endpoint
from .shell_store import JsonStore, is_uuid

FORMAT = "emerald-network-settings-v1"
FILE_NAME = "network.json"
ROUTE_FORMAT = "emerald-join-route-v1"
ROUTE_NAME = "route.json"
MAX_WORLDS = 64
_KEYS = {"router_setup", "relay_enabled", "relay_address", "relay_port", "relay_secret"}


@dataclass(frozen=True)
class WorldNetwork:
    router_setup: bool = True             # try automatic router setup while the world allows Internet connections
    relay_enabled: bool = False
    relay_address: str = ""
    relay_port: int = DEFAULT_PORT
    relay_secret: bytes = field(default=b"", repr=False)

    @property
    def relay(self):
        """(address, port) of the relay this world uses, or None."""
        if self.relay_enabled and self.relay_address and len(self.relay_secret) == 32:
            return (self.relay_address, self.relay_port)
        return None


def _validate(record):
    worlds = record.get("worlds")
    if set(record) != {"format", "worlds"} or type(worlds) is not dict or len(worlds) > MAX_WORLDS:
        raise ValueError("invalid network settings")
    for world_id, value in worlds.items():
        if (not is_uuid(world_id) or type(value) is not dict or set(value) != _KEYS
                or type(value["router_setup"]) is not bool or type(value["relay_enabled"]) is not bool
                or type(value["relay_address"]) is not str or type(value["relay_port"]) is not int
                or not 1 <= value["relay_port"] <= 65535
                or (value["relay_address"] and not valid_endpoint(value["relay_address"], value["relay_port"]))
                or type(value["relay_secret"]) is not str
                or (value["relay_secret"] and re.fullmatch("[0-9a-f]{64}", value["relay_secret"]) is None)):
            raise ValueError("invalid world network settings")
    return record


def _empty():
    return {"format": FORMAT, "worlds": {}}


def _record(network):
    return {"router_setup": network.router_setup, "relay_enabled": network.relay_enabled, "relay_address": network.relay_address,
            "relay_port": network.relay_port, "relay_secret": network.relay_secret.hex()}


class NetworkSettings:
    def __init__(self, private_root=None, *, clock=time.time):
        path = None if private_root is None else Path(private_root) / "shell" / FILE_NAME
        self._store = JsonStore(path, FORMAT, _empty, _validate, clock=clock)

    @property
    def available(self):
        return self._store.available

    def get(self, world_id):
        value = self._store.record["worlds"].get(world_id)
        if value is None:
            return WorldNetwork()
        return WorldNetwork(value["router_setup"], value["relay_enabled"], value["relay_address"], value["relay_port"],
                            bytes.fromhex(value["relay_secret"]))

    def _put(self, world_id, network):
        if not is_uuid(world_id):
            raise ValueError("unknown world")
        worlds = dict(self._store.record["worlds"])
        worlds[world_id] = _record(network)
        self._store.save({"format": FORMAT, "worlds": worlds})
        return network

    def set_router_setup(self, world_id, enabled):
        if type(enabled) is not bool:
            raise ValueError("router setup is on or off")
        return self._put(world_id, replace(self.get(world_id), router_setup=enabled))

    def set_relay(self, world_id, address, port=DEFAULT_PORT):
        """Use the relay at address:port for this world (its relay key is made the first time)."""
        if not valid_endpoint(address, port):
            raise ValueError("relay address or port is not usable")
        current = self.get(world_id)
        secret = current.relay_secret if len(current.relay_secret) == 32 else secrets.token_bytes(32)
        return self._put(world_id, replace(current, relay_enabled=True, relay_address=address, relay_port=port, relay_secret=secret))

    def disable_relay(self, world_id):
        return self._put(world_id, replace(self.get(world_id), relay_enabled=False))

    def new_relay_key(self, world_id):
        """A fresh relay key. A relay that is running keeps the world's room for the old key until it restarts (or the room has
        been empty for its reservation time); use this only to move away from a key someone else learned."""
        return self._put(world_id, replace(self.get(world_id), relay_secret=secrets.token_bytes(32)))


# ------------------------------------------------------------------------------------------------------------- friend routes


def route_path(private_root, world_id, player_id):
    from .character_links import profile_directory
    return profile_directory(private_root, world_id, player_id) / ROUTE_NAME


def save_join_route(private_root, world_id, player_id, relay=None):
    """Remember how this account connects: ``relay`` = (address, port), or None for direct."""
    if relay is not None:
        relay = tuple(relay)
        if len(relay) != 2 or not valid_endpoint(*relay):
            raise ValueError("relay address or port is not usable")
    path = route_path(private_root, world_id, player_id)
    if path.is_symlink():
        raise ValueError("linked route location")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    value = {"format": ROUTE_FORMAT, "relay": None if relay is None else {"address": relay[0], "port": relay[1]}}
    _atomic(path, _json_bytes(value))
    return path


def load_join_route(profile_directory):
    """(address, port) of the account's relay, or None for direct (also when the file is missing or not usable)."""
    path = Path(profile_directory) / ROUTE_NAME
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
            return None
        value = json.loads(path.read_bytes())
        relay = value.get("relay") if type(value) is dict and value.get("format") == ROUTE_FORMAT else None
        if type(relay) is not dict or set(relay) != {"address", "port"} or not valid_endpoint(relay["address"], relay["port"]):
            return None
        return (relay["address"], relay["port"])
    except (OSError, ValueError, UnicodeError):
        return None


__all__ = ["NetworkSettings", "WorldNetwork", "load_join_route", "route_path", "save_join_route"]
