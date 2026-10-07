"""Pure codecs for the allocated 128-byte ROM mailbox ABI.

These functions handle bytes only; they never choose addresses or write emulator
memory. Underwater movement (ROM mode 4) has no transport/rendering support yet
and is advertised as unavailable. This is a presence ABI, not a save format.
"""

from __future__ import annotations

from dataclasses import dataclass
import struct

ABI_VERSION = 1
MAILBOX_MAGIC = 0x31504D45
MAILBOX_SIZE = 128
POSE_SIZE = 20
INBOUND_SIZE = 88
LOCAL_POSE_OFFSET = 16
EXTERNAL_GEN_OFFSET = 36
INBOUND_OFFSET = 40
CONNECTED = 1
_POSE = struct.Struct("<IIhh8B")
_INBOUND = struct.Struct("<IIIBBH")
_UINT32 = 0xFFFFFFFF


class MailboxError(ValueError):
    pass


def _bound(value: int, low: int, high: int, name: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise MailboxError(f"{name} is outside its integer bounds")
    return value


@dataclass(frozen=True)
class Pose:
    map_epoch: int
    frame: int
    x: int
    y: int
    map_group: int
    map_number: int
    direction: int
    elevation: int
    avatar_gender: int
    movement_mode: int
    activity: int

    def __post_init__(self) -> None:
        for name in ("map_epoch", "frame"):
            _bound(getattr(self, name), 0, _UINT32, name)
        for name in ("x", "y"):
            _bound(getattr(self, name), -32768, 32767, name)
        for name in ("map_group", "map_number"):
            _bound(getattr(self, name), 0, 255, name)
        _bound(self.direction, 1, 4, "direction")
        _bound(self.elevation, 0, 15, "elevation")
        _bound(self.avatar_gender, 0, 1, "avatar_gender")
        _bound(self.movement_mode, 0, 4, "movement_mode")
        _bound(self.activity, 0, 1, "activity")

    def pack(self) -> bytes:
        return _POSE.pack(
            self.map_epoch, self.frame, self.x, self.y, self.map_group,
            self.map_number, self.direction, self.elevation,
            self.avatar_gender, self.movement_mode, self.activity, 0,
        )

    @classmethod
    def unpack(cls, payload: bytes) -> Pose:
        if len(payload) != POSE_SIZE:
            raise MailboxError("local pose must contain exactly 20 bytes")
        fields = _POSE.unpack(payload)
        if fields[-1] != 0:
            raise MailboxError("local pose reserved byte must be zero")
        return cls(*fields[:-1])

    def network_fields(self, available: bool) -> dict:
        modes = {0: "walk", 1: "bike", 2: "bike", 3: "surf", 4: "walk"}
        return {
            "map_group": self.map_group, "map_number": self.map_number,
            "x": self.x, "y": self.y, "direction": self.direction,
            "elevation": self.elevation, "avatar_gender": self.avatar_gender,
            "movement_mode": modes[self.movement_mode],
            "activity": "overworld" if available and self.activity == 1 and self.movement_mode != 4 else "unavailable",
        }

    @classmethod
    def from_presence(cls, presence: dict) -> Pose:
        modes = {"walk": 0, "run": 0, "bike": 1, "surf": 3}
        return cls(
            presence["map_epoch"], presence["seq"], presence["x"], presence["y"],
            presence["map_group"], presence["map_number"], presence["direction"],
            presence["elevation"], presence["avatar_gender"],
            modes[presence["movement_mode"]], 1 if presence["activity"] == "overworld" else 0,
        )


@dataclass(frozen=True)
class Peer:
    token: int
    pose: Pose

    def __post_init__(self) -> None:
        _bound(self.token, 1, _UINT32, "player token")
        if not isinstance(self.pose, Pose):
            raise MailboxError("peer requires a validated pose")


@dataclass(frozen=True)
class Snapshot:
    connection_flags: int = 0
    heartbeat: int = 0
    roster_epoch: int = 0
    self_slot: int = 0
    peers: tuple[Peer, ...] = ()

    def __post_init__(self) -> None:
        _bound(self.connection_flags, 0, CONNECTED, "connection flags")
        _bound(self.heartbeat, 0, _UINT32, "heartbeat")
        _bound(self.roster_epoch, 0, _UINT32, "roster epoch")
        _bound(self.self_slot, 0, 3, "self slot")
        if not isinstance(self.peers, tuple) or len(self.peers) > 3 or any(not isinstance(peer, Peer) for peer in self.peers):
            raise MailboxError("snapshot permits at most three validated peers")
        if len({peer.token for peer in self.peers}) != len(self.peers):
            raise MailboxError("peer tokens must be unique")
        if not self.connection_flags and (self.peers or self.self_slot != 0):
            raise MailboxError("disconnected snapshot must have an empty roster")

    def pack(self) -> bytes:
        data = _INBOUND.pack(self.connection_flags, self.heartbeat, self.roster_epoch, self.self_slot, len(self.peers), 0)
        data += b"".join(struct.pack("<I", peer.token) + peer.pose.pack() for peer in self.peers)
        return data + bytes(INBOUND_SIZE - len(data))

    @classmethod
    def unpack(cls, payload: bytes) -> Snapshot:
        if len(payload) != INBOUND_SIZE:
            raise MailboxError("inbound snapshot must contain exactly 88 bytes")
        flags, heartbeat, epoch, slot, count, reserved = _INBOUND.unpack(payload[:16])
        if reserved != 0 or count > 3:
            raise MailboxError("invalid snapshot count or reserved field")
        peers = []
        for index in range(count):
            start = 16 + index * 24
            token = struct.unpack("<I", payload[start:start + 4])[0]
            peers.append(Peer(token, Pose.unpack(payload[start + 4:start + 24])))
        if any(payload[16 + count * 24:]):
            raise MailboxError("unused peer records must be zero")
        return cls(flags, heartbeat, epoch, slot, tuple(peers))


def inspect_mailbox(payload: bytes) -> tuple[Pose, Snapshot]:
    """Validate a complete stable mailbox copy without reading emulator memory."""
    if len(payload) != MAILBOX_SIZE:
        raise MailboxError("mailbox must contain exactly 128 bytes")
    magic, abi, size, frame, local_gen = struct.unpack("<IHHII", payload[:16])
    if (magic, abi, size) != (MAILBOX_MAGIC, ABI_VERSION, MAILBOX_SIZE):
        raise MailboxError("mailbox header is incompatible")
    external_gen = struct.unpack("<I", payload[EXTERNAL_GEN_OFFSET:INBOUND_OFFSET])[0]
    if local_gen & 1 or external_gen & 1:
        raise MailboxError("mailbox copy was made during an update")
    return Pose.unpack(payload[LOCAL_POSE_OFFSET:EXTERNAL_GEN_OFFSET]), Snapshot.unpack(payload[INBOUND_OFFSET:])
