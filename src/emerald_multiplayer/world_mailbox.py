"""Pure codecs for the EMW1 shared-world mailbox (followers, mounts, appearance,
world clock, world events and notices).

The ROM publishes a 32-byte local record (state + one action). The bridge writes
a 208-byte inbound record. These helpers only translate bytes; they never pick
addresses or touch emulator memory.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import struct

WORLD_ABI_VERSION = 1
WORLD_MAGIC = 0x31574D45
WORLD_MAILBOX_SIZE = 256
WORLD_LOCAL_OFFSET = 12
WORLD_LOCAL_SIZE = 32
WORLD_INBOUND_GEN_OFFSET = 44
WORLD_INBOUND_OFFSET = 48
WORLD_INBOUND_SIZE = 208
APPEARANCE_BYTES = 8
NOTICE_CHARS = 64  # two banner lines joined by '|'
MAX_SPECIES = 1700  # bound for wire validation; the ROM checks NUM_SPECIES

FOLLOWER_SHINY = 1
FOLLOWER_FEMALE = 2
FOLLOWER_VISIBLE = 4

MOUNT_NONE = 0
MOUNT_RIDING = 1

FLAG_CLOCK_VALID = 1
FLAG_EVENTS = 2

EVENT_SHINY = 1
EVENT_VISIBLE = 2
EVENT_MINE = 4
EVENT_BUSY = 8
EVENT_MEGA = 16

ACTION_NONE = 0
ACTION_CLAIM = 1
ACTION_RESULT = 2
ACTION_RELEASE = 3
ACTION_APPEARANCE = 4  # the local state carries a newly saved trainer look
ACTION_KINDS = {ACTION_CLAIM: "claim", ACTION_RESULT: "result", ACTION_RELEASE: "release",
                ACTION_APPEARANCE: "appearance"}

RESULT_NAMES = {1: "caught", 2: "defeated", 3: "ran", 4: "lost", 5: "cancelled"}

_STATE = struct.Struct("<HBBHBB8s")
_ACTION = struct.Struct("<IBBHII")
_EVENT = struct.Struct("<IHBBBBhhHIB11s")
_INBOUND_HEAD = struct.Struct("<III8s")
_UINT32 = 0xFFFFFFFF


class WorldMailboxError(ValueError):
    pass


def _bound(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise WorldMailboxError(f"{name} is outside its integer bounds")
    return value


def _appearance(value: bytes) -> bytes:
    if not isinstance(value, bytes) or len(value) != APPEARANCE_BYTES:
        raise WorldMailboxError("appearance must contain exactly eight bytes")
    return value


@dataclass(frozen=True)
class WorldState:
    follower_species: int = 0
    follower_flags: int = 0
    mount_state: int = MOUNT_NONE
    mount_species: int = 0
    mount_flags: int = 0
    appearance: bytes = bytes(APPEARANCE_BYTES)

    def __post_init__(self):
        _bound(self.follower_species, 0, MAX_SPECIES, "follower species")
        _bound(self.follower_flags, 0, 7, "follower flags")
        _bound(self.mount_state, 0, 1, "mount state")
        _bound(self.mount_species, 0, MAX_SPECIES, "mount species")
        _bound(self.mount_flags, 0, 3, "mount flags")
        _appearance(self.appearance)

    def pack(self) -> bytes:
        return _STATE.pack(self.follower_species, self.follower_flags, self.mount_state,
                           self.mount_species, self.mount_flags, 0, self.appearance)

    @classmethod
    def unpack(cls, payload: bytes) -> "WorldState":
        if len(payload) != 16:
            raise WorldMailboxError("world state must contain exactly 16 bytes")
        species, flags, mount, mount_species, mount_flags, reserved, appearance = _STATE.unpack(payload)
        if reserved != 0:
            raise WorldMailboxError("world state reserved byte must be zero")
        return cls(species, flags, mount, mount_species, mount_flags, appearance)

    def network_fields(self) -> dict:
        return {
            "follower_species": self.follower_species, "follower_flags": self.follower_flags,
            "mount_state": self.mount_state, "mount_species": self.mount_species,
            "mount_flags": self.mount_flags,
        }

    @classmethod
    def from_network(cls, presence: dict | None, appearance: bytes) -> "WorldState":
        presence = presence or {}
        return cls(presence.get("follower_species", 0), presence.get("follower_flags", 0),
                   presence.get("mount_state", 0), presence.get("mount_species", 0),
                   presence.get("mount_flags", 0), appearance)


@dataclass(frozen=True)
class WorldAction:
    seq: int = 0
    kind: int = ACTION_NONE
    result: int = 0
    species: int = 0
    event_id: int = 0

    def __post_init__(self):
        _bound(self.seq, 0, _UINT32, "action seq")
        _bound(self.kind, 0, 4, "action kind")
        _bound(self.result, 0, 5, "action result")
        _bound(self.species, 0, MAX_SPECIES, "action species")
        _bound(self.event_id, 0, _UINT32, "action event")

    def pack(self) -> bytes:
        return _ACTION.pack(self.seq, self.kind, self.result, self.species, self.event_id, 0)

    @classmethod
    def unpack(cls, payload: bytes) -> "WorldAction":
        if len(payload) != 16:
            raise WorldMailboxError("world action must contain exactly 16 bytes")
        seq, kind, result, species, event_id, reserved = _ACTION.unpack(payload)
        if reserved != 0:
            raise WorldMailboxError("world action reserved field must be zero")
        return cls(seq, kind, result, species, event_id)


def unpack_local(payload: bytes) -> tuple[WorldState, WorldAction]:
    if len(payload) != WORLD_LOCAL_SIZE:
        raise WorldMailboxError("world local record must contain exactly 32 bytes")
    return WorldState.unpack(payload[:16]), WorldAction.unpack(payload[16:])


@dataclass(frozen=True)
class WorldEventView:
    event_id: int = 0
    species: int = 0
    level: int = 0
    flags: int = 0
    map_group: int = 0
    map_number: int = 0
    x: int = 0
    y: int = 0
    held_item: int = 0
    seconds_left: int = 0
    perfect_ivs: int = 0

    def __post_init__(self):
        _bound(self.event_id, 0, _UINT32, "event id")
        _bound(self.species, 0, MAX_SPECIES, "event species")
        _bound(self.level, 0, 100, "event level")
        _bound(self.flags, 0, 31, "event flags")
        _bound(self.map_group, 0, 255, "event map group")
        _bound(self.map_number, 0, 255, "event map number")
        _bound(self.x, -32768, 32767, "event x")
        _bound(self.y, -32768, 32767, "event y")
        _bound(self.held_item, 0, 0xFFFF, "event item")
        _bound(self.seconds_left, 0, _UINT32, "event timer")
        _bound(self.perfect_ivs, 0, 6, "event perfect IVs")

    def pack(self) -> bytes:
        return _EVENT.pack(self.event_id, self.species, self.level, self.flags, self.map_group,
                           self.map_number, self.x, self.y, self.held_item, self.seconds_left,
                           self.perfect_ivs, bytes(11))


def _notice_bytes(text: str) -> bytes:
    data = "".join(c if 32 <= ord(c) < 127 else " " for c in (text or ""))[:NOTICE_CHARS].encode("ascii")
    return data + bytes(NOTICE_CHARS - len(data))


@dataclass(frozen=True)
class WorldInbound:
    clock_valid: bool = False
    events_enabled: bool = False
    world_seconds: int = 0
    action_ack: int = 0
    self_appearance: bytes = bytes(APPEARANCE_BYTES)
    peers: tuple = ()  # (token, WorldState) for up to three peers
    event: WorldEventView = field(default_factory=WorldEventView)
    notice_id: int = 0
    notice_text: str = ""

    def __post_init__(self):
        _bound(self.world_seconds, 0, _UINT32, "world seconds")
        _bound(self.action_ack, 0, _UINT32, "action ack")
        _bound(self.notice_id, 0, _UINT32, "notice id")
        _appearance(self.self_appearance)
        if not isinstance(self.peers, tuple) or len(self.peers) > 3:
            raise WorldMailboxError("at most three world peers")
        tokens = [token for token, _ in self.peers]
        if len(set(tokens)) != len(tokens) or any(type(t) is not int or not 1 <= t <= _UINT32 for t in tokens):
            raise WorldMailboxError("world peer tokens must be unique nonzero integers")

    def pack(self) -> bytes:
        flags = (FLAG_CLOCK_VALID if self.clock_valid else 0) | (FLAG_EVENTS if self.events_enabled else 0)
        data = _INBOUND_HEAD.pack(flags, self.world_seconds, self.action_ack, self.self_appearance)
        for token, state in self.peers:
            data += struct.pack("<I", token) + state.pack()
        data += bytes(20 * (3 - len(self.peers)))
        data += self.event.pack()
        data += struct.pack("<I", self.notice_id) + _notice_bytes(self.notice_text)
        data += bytes(WORLD_INBOUND_SIZE - len(data))
        assert len(data) == WORLD_INBOUND_SIZE
        return data


def capability_matches(manifest: dict) -> bool:
    return (manifest.get("world_abi_version") == WORLD_ABI_VERSION
            and type(manifest.get("world_mailbox_address")) is int
            and manifest.get("world_mailbox_size") == WORLD_MAILBOX_SIZE)


WORLD_FIELDS = frozenset({"world_abi_version", "world_abi_address", "world_mailbox_address", "world_mailbox_size"})
_OTHER_RAM_REGIONS = (
    ("mailbox_address", "mailbox_size"),
    ("save_mailbox_address", "save_mailbox_size"),
    ("battle_mailbox_address", "battle_mailbox_size"),
    ("menu_mailbox_address", "menu_mailbox_size"),
    ("reset_mailbox_address", "reset_mailbox_size"),
    ("save_window_address", "save_window_size"),
)


def validate_world_manifest(manifest, rom_path=None) -> bool:
    """Validate the optional EMW1 capability; False when the ROM has none."""
    if not WORLD_FIELDS.intersection(manifest):
        return False
    marker = manifest.get("world_abi_address")
    address = manifest.get("world_mailbox_address")
    if (not WORLD_FIELDS.issubset(manifest)
            or manifest.get("world_abi_version") != WORLD_ABI_VERSION
            or manifest.get("world_mailbox_size") != WORLD_MAILBOX_SIZE
            or type(marker) is not int or marker % 4 or not 0x08000000 <= marker <= 0x09FFFFFC
            or type(address) is not int or address % 4
            or not 0x02000000 <= address <= 0x02040000 - WORLD_MAILBOX_SIZE):
        raise ValueError("shared-world capability is incompatible")
    for start_key, size_key in _OTHER_RAM_REGIONS:
        start, size = manifest.get(start_key), manifest.get(size_key)
        if type(start) is int and type(size) is int and not (address + WORLD_MAILBOX_SIZE <= start or start + size <= address):
            raise ValueError("shared-world mailbox overlaps another mailbox")
    if rom_path is not None:
        if marker - 0x08000000 > rom_path.stat().st_size - 4:
            raise ValueError("shared-world marker is outside the ROM")
        with rom_path.open("rb") as source:
            source.seek(marker - 0x08000000)
            if source.read(4) != struct.pack("<I", WORLD_ABI_VERSION):
                raise ValueError("shared-world marker differs from the verified ROM")
    return True
