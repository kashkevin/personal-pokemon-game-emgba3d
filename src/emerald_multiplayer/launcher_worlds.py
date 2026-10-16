"""The worlds on this PC, for the main menu's My Worlds and Host pages, and this PC's LAN addresses.

Read only. A world is a folder under the launcher's private ``worlds`` directory that holds the host's ``host.json`` (setup
creates them); the menu lists each one with its players' names (public labels, never credentials). Opening a world to read its
roster verifies it the same way Host Game does (``HostWorld.open``) but starts no listener and takes no lease, as
``world_accounts`` in launcher_setup.py: a world that is being hosted right now is still listed. Nothing here creates, changes,
moves or deletes a world.
"""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
from pathlib import Path
import socket

from .host_world import HostWorld

STATUS_READY = "ready"            # opened and verified against the installed game
STATUS_INVALID = "invalid"        # this folder is not a usable world for the installed game (damaged, other release, partial)
STATUS_NEEDS_GAME = "needs_game"  # the game is not installed (or changed) here: worlds cannot be checked yet
MAX_WORLDS = 64


@dataclass(frozen=True)
class WorldEntry:
    directory: Path
    host_json: Path
    names: tuple          # player names, host first ('' when not verified)
    status: str
    modified: float       # when the record was last written (a file time, for sorting only)

    @property
    def title(self):
        if not self.names:
            return "World " + self.directory.name[:8]
        host, friends = self.names[0], self.names[1:]
        return f"{host}'s world" + (f" with {', '.join(friends)}" if friends else " (solo)")

    @property
    def players(self):
        return len(self.names)


def worlds_directory(private_root):
    return Path(private_root) / "worlds"


def scan_worlds(installation, private_root):
    """Every world folder under private_root/worlds, newest first. Never raises for a bad world: it is listed as invalid."""
    root = worlds_directory(private_root)
    try:
        children = sorted(child for child in root.iterdir() if child.is_dir() and not child.is_symlink())
    except (FileNotFoundError, NotADirectoryError):
        return []
    except OSError:
        return []
    installed = True
    try:
        installation.verify()
    except Exception:
        installed = False
    entries = []
    for child in children[:MAX_WORLDS]:
        record = child / "host.json"
        try:
            if not record.is_file() or record.is_symlink():
                continue
            modified = record.stat().st_mtime
        except OSError:
            continue
        names, status = (), STATUS_NEEDS_GAME
        if installed:
            try:
                world = HostWorld.open(child, installation.rom_path, installation.manifest_path)
                names, status = tuple(account.display_name for account in world.accounts), STATUS_READY
            except Exception:
                names, status = (), STATUS_INVALID
        entries.append(WorldEntry(child, record, names, status, modified))
    entries.sort(key=lambda entry: entry.modified, reverse=True)
    return entries


def lan_addresses():
    """This PC's private IPv4 addresses (192.168.x.x, 10.x.x.x, 172.16-31.x.x), the likeliest first. Nothing is sent: a UDP
    socket is only asked which local address a private destination would use, and the host name is looked up locally."""
    found = []

    def add(value):
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            return
        if address.version == 4 and address.is_private and not address.is_loopback and not address.is_link_local and value not in found:
            found.append(value)

    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("10.255.255.255", 9))   # a UDP connect sends no packet
            add(probe.getsockname()[0])
        finally:
            probe.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            add(info[4][0])
    except OSError:
        pass
    return found
