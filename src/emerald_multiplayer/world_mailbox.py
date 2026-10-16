"""Pure codecs for the EMW1 shared-world mailbox (followers, mounts, appearance,
world clock, world events, notices and wager wallet adjustments).

The ROM publishes a 32-byte local record (state + one action). The bridge writes
a 208-byte inbound record. These helpers only translate bytes; they never pick
addresses or touch emulator memory.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import struct

from .rewards import decode, is_reward_word

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
ACTION_WALLET = 5      # the save applied wallet adjustment event_id moving `amount`
ACTION_COOP_GYM = 6    # a Gym Leader script asks for a co-op battle; event_id = Gym 1..8
ACTION_KINDS = {ACTION_CLAIM: "claim", ACTION_RESULT: "result", ACTION_RELEASE: "release",
                ACTION_APPEARANCE: "appearance", ACTION_WALLET: "wallet", ACTION_COOP_GYM: "coop_gym"}
MAX_MONEY = 999_999
WALLET_OFFSET = 180  # inbound: u32 wallet seq, s32 wallet delta, u32 teammate token
RIVAL_OFFSET = 200  # inbound (Update 31, only for engines advertising rival_abi_version 1): RivalRecord
RIVAL_ABI_VERSION = 1
RIVAL_VALID, RIVAL_PRESENT, RIVAL_MY_MATCH = 1, 2, 4
RIVAL_STATES = {"open": 1, "countdown": 2, "battling": 3, "completed": 4}

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
    wallet_seq: int = 0  # local record only: low byte of the save's last applied wallet sequence

    def __post_init__(self):
        _bound(self.follower_species, 0, MAX_SPECIES, "follower species")
        _bound(self.follower_flags, 0, 7, "follower flags")
        _bound(self.mount_state, 0, 1, "mount state")
        _bound(self.mount_species, 0, MAX_SPECIES, "mount species")
        _bound(self.mount_flags, 0, 3, "mount flags")
        _bound(self.wallet_seq, 0, 255, "wallet sequence")
        _appearance(self.appearance)

    def pack(self) -> bytes:
        # Peer records never carry another player's wallet sequence.
        return _STATE.pack(self.follower_species, self.follower_flags, self.mount_state,
                           self.mount_species, self.mount_flags, 0, self.appearance)

    @classmethod
    def unpack(cls, payload: bytes) -> "WorldState":
        if len(payload) != 16:
            raise WorldMailboxError("world state must contain exactly 16 bytes")
        species, flags, mount, mount_species, mount_flags, wallet_seq, appearance = _STATE.unpack(payload)
        return cls(species, flags, mount, mount_species, mount_flags, appearance, wallet_seq)

    def network_fields(self) -> dict:
        return {
            "follower_species": self.follower_species, "follower_flags": self.follower_flags,
            "mount_state": self.mount_state, "mount_species": self.mount_species,
            "mount_flags": self.mount_flags, "wallet_seq": self.wallet_seq,
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
    amount: int = 0  # wallet receipts only: the money the save actually moved

    def __post_init__(self):
        _bound(self.seq, 0, _UINT32, "action seq")
        _bound(self.kind, 0, ACTION_COOP_GYM, "action kind")
        _bound(self.result, 0, 5, "action result")
        _bound(self.species, 0, MAX_SPECIES, "action species")
        _bound(self.event_id, 0, _UINT32, "action event")
        _bound(self.amount, 0, MAX_MONEY if self.kind == ACTION_WALLET else 0, "action amount")

    def pack(self) -> bytes:
        return _ACTION.pack(self.seq, self.kind, self.result, self.species, self.event_id, self.amount)

    @classmethod
    def unpack(cls, payload: bytes) -> "WorldAction":
        if len(payload) != 16:
            raise WorldMailboxError("world action must contain exactly 16 bytes")
        seq, kind, result, species, event_id, amount = _ACTION.unpack(payload)
        if amount != 0 and kind != ACTION_WALLET:
            raise WorldMailboxError("only wallet receipts carry an amount")
        return cls(seq, kind, result, species, event_id, amount)


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


@dataclass(frozen=True)
class RivalRecord:
    """Eight bytes: flags, completed mask, cleared mask, here (1..5, 0 none), here state, 3 zero.

    Bit i of a mask is checkpoint i+1 in story order (rival_catalogue.IDS). ``completed`` is the
    world's checkpoint completion; ``cleared`` is this player's own pass (battle, catch-up or solo).
    The engine blocks an armed trigger line only when neither bit is set (gate_blocks) and gives
    the original scene's personal rewards from its own scripts, guarded by its own save flags.
    """
    completed: int = 0
    cleared: int = 0
    here: int = 0
    state: int = 0
    present: bool = False
    my_match: bool = False

    def __post_init__(self):
        _bound(self.completed, 0, 31, "rival completed mask")
        _bound(self.cleared, 0, 31, "rival cleared mask")
        _bound(self.here, 0, 5, "rival checkpoint")
        _bound(self.state, 0, 4, "rival state")
        if (self.here == 0) != (self.state == 0) or type(self.present) is not bool or type(self.my_match) is not bool:
            raise WorldMailboxError("a rival state needs its checkpoint")
        if (self.present or self.my_match) and not self.here:
            raise WorldMailboxError("rival presence needs a checkpoint")

    def pack(self) -> bytes:
        flags = RIVAL_VALID | (RIVAL_PRESENT if self.present else 0) | (RIVAL_MY_MATCH if self.my_match else 0)
        return struct.pack("<BBBBB3x", flags, self.completed, self.cleared, self.here, self.state)

    @classmethod
    def from_reply(cls, reply: dict, actor: str) -> "RivalRecord":
        """From a validated rival reply (rival_protocol.validate_rival_reply)."""
        from .rival_catalogue import IDS
        completed = sum(1 << i for i, row in enumerate(reply["checkpoints"]) if row["completed"])
        cleared = sum(1 << i for i, row in enumerate(reply["checkpoints"]) if row["cleared"])
        here = reply["here"]
        if here is None:
            return cls(completed, cleared)
        mine = any(actor in sum(match["teams"], []) and match["state"] in {"ready", "invited"}
                   for match in (here["session"] or {"matches": ()})["matches"])
        return cls(completed, cleared, IDS.index(here["checkpoint_id"]) + 1, RIVAL_STATES[here["state"]],
                   any(row["player_id"] == actor for row in here["present"]), here["state"] == "battling" and mine)


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
    wallet_seq: int = 0     # this player's next wallet adjustment (0 = none)
    wallet_delta: int = 0   # money to add (positive) or collect (negative)
    teammate_token: int = 0  # peer token of the host-formed teammate (0 = none)
    outbreak: tuple | None = None  # (map group, map number) of the running outbreak, for the Town Map marker
    rival: RivalRecord | None = None  # Update 31; None (all zero) unless the engine advertises rival_abi_version 1

    def __post_init__(self):
        _bound(self.world_seconds, 0, _UINT32, "world seconds")
        _bound(self.action_ack, 0, _UINT32, "action ack")
        _bound(self.notice_id, 0, _UINT32, "notice id")
        _bound(self.wallet_seq, 0, 0xFFFF, "wallet sequence")
        if not is_reward_word(self.wallet_delta):   # money, or a Frontier reward (Battle Points / an item), rewards.py
            _bound(self.wallet_delta, -MAX_MONEY, MAX_MONEY, "wallet delta")
        elif decode(self.wallet_delta) is None:
            raise WorldMailboxError("wallet delta is not a valid reward")
        if (self.wallet_seq == 0) != (self.wallet_delta == 0):
            raise WorldMailboxError("a wallet adjustment needs both a sequence and a nonzero delta")
        _bound(self.teammate_token, 0, 4, "teammate token")
        if self.outbreak is not None:
            if not isinstance(self.outbreak, tuple) or len(self.outbreak) != 2:
                raise WorldMailboxError("an outbreak is a (map group, map number) pair")
            _bound(self.outbreak[0], 0, 255, "outbreak map group")
            _bound(self.outbreak[1], 0, 255, "outbreak map number")
        if self.teammate_token and self.teammate_token not in [token for token, _ in self.peers]:
            raise WorldMailboxError("the teammate must be one of the published peers")
        _appearance(self.self_appearance)
        if self.rival is not None and not isinstance(self.rival, RivalRecord):
            raise WorldMailboxError("the rival record must be a RivalRecord")
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
        assert len(data) == WALLET_OFFSET
        data += struct.pack("<IiI", self.wallet_seq, self.wallet_delta, self.teammate_token)
        # The engine's reserved bytes: the outbreak's place (valid, group, number, 0, species unused).
        data += struct.pack("<BBBBH2x", 1, *self.outbreak, 0, 0) if self.outbreak is not None else bytes(8)
        assert len(data) == RIVAL_OFFSET
        data += self.rival.pack() if self.rival is not None else bytes(8)
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
