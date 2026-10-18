"""The worlds on this PC, for the main menu's My Worlds and Host pages, and this PC's LAN and VPN addresses.

Read only. A world is a folder under the launcher's private ``worlds`` directory that holds the host's ``host.json`` (setup
creates them); the menu lists each one with its players' names (public labels, never credentials). Opening a world to read its
roster verifies it the same way Host Game does (``HostWorld.open``) but starts no listener and takes no lease, as
``world_accounts`` in launcher_setup.py: a world that is being hosted right now is still listed. Nothing here creates, changes,
moves or deletes a world.
"""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import os
from pathlib import Path
import re
import socket

from .host_world import HostWorld
from .secure_transport import is_overlay_address

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


_VPN_ADAPTERS = ("tailscale", "zerotier", "radmin", "hamachi", "wireguard", "wintun", "openvpn", "tap-windows", "nordlynx",
                 "netbird", "nebula", "vpn")
_HAMACHI_RADMIN = tuple(ipaddress.ip_network(value) for value in ("25.0.0.0/8", "26.0.0.0/8"))


class LocalAddress(str):
    """One of this PC's IPv4 addresses (a ``str``, so existing callers keep working) with what it is:

    ``kind`` "lan" (home/office network), "vpn" (an overlay VPN such as Tailscale, ZeroTier, Radmin VPN or Hamachi) or
    "loopback" (this PC only); ``label`` is a short text for the menu ("Local network", "Tailscale", ...); ``adapter`` the
    network adapter's name when the system told us; ``needs_internet_access`` is True for VPNs that use public address ranges
    (Hamachi 25.x, Radmin VPN 26.x): the world accepts their peers only with Internet access turned on."""

    kind: str
    label: str
    adapter: str
    needs_internet_access: bool

    def __new__(cls, value, kind, label, adapter="", needs_internet_access=False):
        item = super().__new__(cls, value)
        item.kind, item.label, item.adapter, item.needs_internet_access = kind, label, adapter, needs_internet_access
        return item

    def describe(self):
        return f"{self.label}: {self}"


def classify_address(value, adapter=""):
    """A LocalAddress for ``value`` (``adapter`` is the adapter name if known), or None for an address friends cannot use."""
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return None
    if address.version != 4 or address.is_link_local or address.is_multicast or address.is_unspecified:
        return None
    name = adapter.strip()
    vpn_name = next((word for word in _VPN_ADAPTERS if word in name.lower()), None)
    if address.is_loopback:
        return LocalAddress(value, "loopback", "This PC only", name)
    if is_overlay_address(value):
        label = ("Tailscale" if vpn_name == "tailscale" else f"VPN ({name})" if vpn_name
                 else "VPN (Tailscale or similar, 100.x)")
        return LocalAddress(value, "vpn", label, name)
    if any(address in network for network in _HAMACHI_RADMIN) and vpn_name is not None:
        return LocalAddress(value, "vpn", name or "VPN", name, needs_internet_access=True)
    if address.is_private:
        if vpn_name is not None:
            return LocalAddress(value, "vpn", f"VPN ({name})", name)
        return LocalAddress(value, "lan", "Local network", name)
    return None


def parse_ipconfig(text):
    """(address, adapter name) pairs from Windows ``ipconfig`` output, in any display language (adapter headers are the lines
    that do not start with a space and end with ':'; address lines mention IPv4)."""
    pairs, adapter = [], ""
    for line in text.splitlines():
        if not line.strip():
            continue
        if not line[0].isspace() and line.rstrip().endswith(":"):
            header = line.strip()[:-1]
            adapter = re.split(r"(?i)\badapter\b", header, maxsplit=1)[-1].strip() or header
            continue
        if "IPv4" in line and ":" in line:
            match = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", line.split(":", 1)[1])
            if match:
                pairs.append((match.group(1), adapter))
    return pairs


def _adapters(run=None):
    """(address, adapter) pairs the system reports. Windows: ``ipconfig``; Linux: each interface's IPv4 address. Never raises."""
    try:
        if os.name == "nt":
            import subprocess
            run = run or subprocess.run
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            output = run(["ipconfig"], capture_output=True, timeout=3, creationflags=flags)
            return parse_ipconfig(output.stdout.decode(errors="replace"))
        import fcntl
        import struct
        pairs = []
        for _, name in socket.if_nameindex():
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                packed = fcntl.ioctl(probe.fileno(), 0x8915, struct.pack("256s", name.encode()[:15]))   # SIOCGIFADDR
                pairs.append((socket.inet_ntoa(packed[20:24]), name))
            except OSError:
                pass
            finally:
                probe.close()
        return pairs
    except Exception:                                                  # noqa: BLE001 - labels are a convenience only
        return []


def _probed():
    """Addresses the routing table picks for a private and a Tailscale destination, and the host name's addresses. A UDP
    connect sends no packet."""
    found = []
    for destination in ("10.255.255.255", "100.100.100.100"):
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                probe.connect((destination, 9))
                found.append(probe.getsockname()[0])
            finally:
                probe.close()
        except OSError:
            pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.append(info[4][0])
    except OSError:
        pass
    return found


def local_addresses(*, include_loopback=True, adapters=None):
    """Every usable IPv4 address of this PC, labelled (LAN first, then VPNs, then loopback). ``adapters`` overrides the system's
    (address, adapter name) list, for tests."""
    names = dict((address, adapter) for address, adapter in (adapters if adapters is not None else _adapters()))
    order, result = {"lan": 0, "vpn": 1, "loopback": 2}, []
    for value in _probed() + list(names):
        item = classify_address(value, names.get(value, ""))
        if item is None or item in result or (item.kind == "loopback" and not include_loopback):
            continue
        result.append(item)
    if include_loopback and "127.0.0.1" not in result:
        result.append(classify_address("127.0.0.1"))
    return sorted(result, key=lambda item: order[item.kind])


def lan_addresses():
    """This PC's addresses friends can use: private IPv4 (192.168.x.x, 10.x.x.x, 172.16-31.x.x) and overlay VPN addresses
    (Tailscale 100.x), the likeliest first, each a LocalAddress (a ``str`` with ``kind`` and ``label``). Nothing is sent: a UDP
    socket is only asked which local address a destination would use, and the host name is looked up locally."""
    names = dict(_adapters())
    found = []
    for value in _probed():
        item = classify_address(value, names.get(value, ""))
        if item is not None and item.kind in ("lan", "vpn") and not item.needs_internet_access and item not in found:
            found.append(item)
    return sorted(found, key=lambda item: item.kind != "lan")


def tailscale_address(addresses=None):
    """The first 100.64.0.0/10 address of this PC (e.g. for "Tailscale address detected: 100.x.y.z"), or None."""
    for item in (addresses if addresses is not None else local_addresses(include_loopback=False)):
        if is_overlay_address(item):
            return item
    return None
