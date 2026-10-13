"""Pure codecs for the native game's shared-spawn mailbox (EMV1, Phase 3).

The native PC game (never the GBA ROM, whose bytes stay pinned) keeps a
384-byte mailbox next to the EMW1 world mailbox:

  game -> companion  'w'  capability: version 1, 12 slots, 384 bytes, 20-byte slots
                     'g'  local record (116 bytes): one claim/result/release action,
                          the player's map and weather, and the spawn objects the
                          game draws right now (for the host's records and proofs)
  companion -> game  'n'  inbound record (252 bytes): enabled flag, action ack, the
                          map the slots belong to and up to 12 host slots

Layout (little-endian, as include/multiplayer_spawns.h):
  0   u32 magic "EMV1"   4 u16 abi version   6 u16 byte size   8 u32 local generation
  12  local record (116)
  128 u32 inbound generation (the bridge's)
  132 u32 flags  136 u32 action ack  140 u8 map group, u8 map number, u8 count, u8 0
  144 12 slots of 20 bytes: u32 spawn id, u32 personality, u16 species, u8 level,
      u8 flags, s16 x, s16 y, u8 facing, u8 move seq, u16 0
These helpers only translate bytes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import struct

SPAWN_MAGIC = 0x31564D45  # "EMV1" (visible wild Pokemon)
SPAWN_ABI_VERSION = 1
SPAWN_MAILBOX_SIZE = 384
SPAWN_MAX_SLOTS = 12
SPAWN_SLOT_SIZE = 20
SPAWN_LOCAL_OFFSET = 12
SPAWN_LOCAL_SIZE = 116
SPAWN_INBOUND_GEN_OFFSET = 128
SPAWN_INBOUND_OFFSET = 132
SPAWN_INBOUND_SIZE = 252
MAX_SPECIES = 1700

FLAG_ENABLED = 1  # connected to a world with shared spawns: no local land encounters

SLOT_SHINY = 1
SLOT_MINE = 2       # the host granted this player's claim
SLOT_BUSY = 4       # another player is battling it
SLOT_OUTBREAK = 8
SLOT_FRESH = 16     # just appeared: the game plays its appear animation

ACTION_NONE = 0
ACTION_CLAIM = 1
ACTION_RESULT = 2
ACTION_RELEASE = 3
ACTION_KINDS = {ACTION_CLAIM: "claim", ACTION_RESULT: "result", ACTION_RELEASE: "release"}
# The same codes as the world mailbox (MP_WORLD_RESULT_*).
RESULT_NAMES = {1: "caught", 2: "defeated", 3: "ran", 4: "lost", 5: "cancelled"}

_ACTION = struct.Struct("<IBBHIBB2x")
_LOCAL_HEAD = struct.Struct("<BBBB")
_SHOWN = struct.Struct("<Ihh")
_SLOT = struct.Struct("<IIHBBhhBBH")
_INBOUND_HEAD = struct.Struct("<IIBBBB")
_UINT32 = 0xFFFFFFFF

assert _ACTION.size == 16 and _SHOWN.size == 8 and _SLOT.size == SPAWN_SLOT_SIZE
assert _ACTION.size + _LOCAL_HEAD.size + SPAWN_MAX_SLOTS * _SHOWN.size == SPAWN_LOCAL_SIZE
assert _INBOUND_HEAD.size + SPAWN_MAX_SLOTS * SPAWN_SLOT_SIZE == SPAWN_INBOUND_SIZE
assert SPAWN_INBOUND_OFFSET + SPAWN_INBOUND_SIZE == SPAWN_MAILBOX_SIZE


class SpawnMailboxError(ValueError):
    pass


def _bound(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise SpawnMailboxError(f"{name} is outside its integer bounds")
    return value


def capability_packet() -> bytes:
    return b"w" + struct.pack("<HHHH", SPAWN_ABI_VERSION, SPAWN_MAX_SLOTS, SPAWN_MAILBOX_SIZE, SPAWN_SLOT_SIZE)


@dataclass(frozen=True)
class SpawnAction:
    seq: int = 0
    kind: int = ACTION_NONE
    result: int = 0
    species: int = 0
    spawn_id: int = 0
    map_group: int = 0
    map_number: int = 0

    def __post_init__(self):
        _bound(self.seq, 0, _UINT32, "spawn action seq")
        _bound(self.kind, 0, ACTION_RELEASE, "spawn action kind")
        _bound(self.result, 0, 5, "spawn action result")
        _bound(self.species, 0, MAX_SPECIES, "spawn action species")
        _bound(self.spawn_id, 0, _UINT32, "spawn id")
        _bound(self.map_group, 0, 255, "spawn action map group")
        _bound(self.map_number, 0, 255, "spawn action map number")
        if self.kind != ACTION_RESULT and self.result != 0:
            raise SpawnMailboxError("only results carry an outcome")

    def pack(self) -> bytes:
        return _ACTION.pack(self.seq, self.kind, self.result, self.species, self.spawn_id,
                            self.map_group, self.map_number)


@dataclass(frozen=True)
class SpawnLocal:
    action: SpawnAction = field(default_factory=SpawnAction)
    map_group: int = 0
    map_number: int = 0
    weather: int = 0
    shown: tuple = ()  # (spawn_id, x, y) of every spawn object the game draws now

    def __post_init__(self):
        _bound(self.map_group, 0, 255, "spawn map group")
        _bound(self.map_number, 0, 255, "spawn map number")
        _bound(self.weather, 0, 255, "weather")
        if not isinstance(self.shown, tuple) or len(self.shown) > SPAWN_MAX_SLOTS:
            raise SpawnMailboxError("too many shown spawns")
        ids = [item[0] for item in self.shown]
        if len(set(ids)) != len(ids) or any(not 1 <= i <= _UINT32 for i in ids):
            raise SpawnMailboxError("shown spawns must have unique nonzero ids")

    def pack(self) -> bytes:
        data = self.action.pack() + _LOCAL_HEAD.pack(self.map_group, self.map_number, self.weather, len(self.shown))
        for spawn_id, x, y in self.shown:
            data += _SHOWN.pack(spawn_id, x, y)
        return data + bytes(SPAWN_LOCAL_SIZE - len(data))

    @classmethod
    def unpack(cls, payload: bytes) -> "SpawnLocal":
        if len(payload) != SPAWN_LOCAL_SIZE:
            raise SpawnMailboxError("spawn local record must contain exactly 116 bytes")
        seq, kind, result, species, spawn_id, action_group, action_number = _ACTION.unpack_from(payload, 0)
        group, number, weather, count = _LOCAL_HEAD.unpack_from(payload, _ACTION.size)
        if count > SPAWN_MAX_SLOTS:
            raise SpawnMailboxError("too many shown spawns")
        base = _ACTION.size + _LOCAL_HEAD.size
        shown = tuple(_SHOWN.unpack_from(payload, base + i * _SHOWN.size) for i in range(count))
        if any(payload[base + count * _SHOWN.size:]):
            raise SpawnMailboxError("unused shown entries must be zero")
        return cls(SpawnAction(seq, kind, result, species, spawn_id, action_group, action_number),
                   group, number, weather, shown)


@dataclass(frozen=True)
class SpawnSlotView:
    spawn_id: int
    species: int
    level: int
    personality: int
    flags: int
    x: int
    y: int
    facing: int
    move_seq: int

    def __post_init__(self):
        _bound(self.spawn_id, 1, _UINT32, "spawn id")
        _bound(self.species, 1, MAX_SPECIES, "spawn species")
        _bound(self.level, 1, 100, "spawn level")
        _bound(self.personality, 0, _UINT32, "spawn personality")
        _bound(self.flags, 0, 31, "spawn flags")
        _bound(self.x, 0, 32767, "spawn x")
        _bound(self.y, 0, 32767, "spawn y")
        _bound(self.facing, 1, 4, "spawn facing")
        _bound(self.move_seq, 0, 255, "spawn move")
        if self.flags & SLOT_MINE and self.flags & SLOT_BUSY:
            raise SpawnMailboxError("a spawn is either mine or busy")

    @classmethod
    def from_network(cls, slot: dict) -> "SpawnSlotView":
        flags = ((SLOT_SHINY if slot["shiny"] else 0) | (SLOT_MINE if slot["mine"] else 0)
                 | (SLOT_BUSY if slot["busy"] else 0) | (SLOT_OUTBREAK if slot["kind"] == "outbreak" else 0)
                 | (SLOT_FRESH if slot["fresh"] else 0))
        return cls(slot["spawn_id"], slot["species"], slot["level"], slot["personality"], flags,
                   slot["x"], slot["y"], slot["facing"], slot["move_seq"])

    def pack(self) -> bytes:
        return _SLOT.pack(self.spawn_id, self.personality, self.species, self.level, self.flags,
                          self.x, self.y, self.facing, self.move_seq, 0)


@dataclass(frozen=True)
class SpawnInbound:
    enabled: bool = False
    action_ack: int = 0
    map_group: int = 0
    map_number: int = 0
    slots: tuple = ()

    def __post_init__(self):
        _bound(self.action_ack, 0, _UINT32, "spawn action ack")
        _bound(self.map_group, 0, 255, "spawn map group")
        _bound(self.map_number, 0, 255, "spawn map number")
        if not isinstance(self.slots, tuple) or len(self.slots) > SPAWN_MAX_SLOTS:
            raise SpawnMailboxError("at most twelve shared spawns")
        ids = [slot.spawn_id for slot in self.slots]
        if len(set(ids)) != len(ids):
            raise SpawnMailboxError("shared spawn ids must be unique")
        if self.slots and not self.enabled:
            raise SpawnMailboxError("slots need the enabled flag")

    @classmethod
    def from_view(cls, view: dict | None, *, enabled: bool, action_ack: int) -> "SpawnInbound":
        # A map the host does not share (the Safari Zone, or no land habitat)
        # is not enabled: the game spawns its own Pokemon there, as offline.
        if view is not None and not view.get("shared", True):
            enabled = False
        if not enabled or view is None:
            return cls(enabled=enabled, action_ack=action_ack)
        slots = tuple(SpawnSlotView.from_network(slot) for slot in view["slots"][:SPAWN_MAX_SLOTS])
        return cls(True, action_ack, view["map_group"], view["map_number"], slots)

    def pack(self) -> bytes:
        data = _INBOUND_HEAD.pack(FLAG_ENABLED if self.enabled else 0, self.action_ack,
                                  self.map_group, self.map_number, len(self.slots), 0)
        for slot in self.slots:
            data += slot.pack()
        data += bytes(SPAWN_INBOUND_SIZE - len(data))
        assert len(data) == SPAWN_INBOUND_SIZE
        return data
