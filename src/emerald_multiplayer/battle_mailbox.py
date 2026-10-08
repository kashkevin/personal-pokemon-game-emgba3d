"""Pure codecs for the development typed native-block diagnostic channel.

No address, controller instruction, party edit or battle entry is accepted.
This separate ABI preserves existing presence/save transport and profiles.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import struct
from uuid import UUID
import zlib

from .protocol import MAX_COUNTER

BATTLE_MAILBOX_MAGIC = 0x31424D45
BATTLE_ABI_VERSION = 1
BATTLE_MAILBOX_SIZE = 512
BATTLE_SLOT_SIZE = 240
BATTLE_DATA_SIZE = 192
BATTLE_BLOCK_SIZE = 256
BATTLE_CHUNK_SIZE = 128
BATTLE_IDLE_FRAMES = 600
DIAGNOSTIC_MAGIC = 0x44424D45
COMMAND_GEN_OFFSET = 24
COMMAND_OFFSET = 28
RESPONSE_GEN_OFFSET = 268
RESPONSE_OFFSET = 272
_UINT32 = 0xFFFFFFFF
_CONTROL = struct.Struct("<II16sIIHHBBBBBBHI192s")
_BINDING = struct.Struct("<16s64s4I4IBBBB")
_DIAGNOSTIC = struct.Struct("<II16sIIII")
_QUERY = struct.Struct("<I16sBBBB10I")


class BattleMailboxError(ValueError):
    pass


class Opcode(IntEnum):
    BIND = 1
    QUERY = 2
    EMIT_DIAGNOSTIC = 3
    READ_OUT = 4
    ACK_OUT = 5
    RECEIVE = 6
    CLEAR_RX = 7
    CLOSE = 8
    KEEP = 9


class State(IntEnum):
    UNBOUND = 0
    IDLE = 1
    CHANNEL = 2
    EXPIRED = 3


class Phase(IntEnum):
    DIAGNOSTIC = 1


class Kind(IntEnum):
    NONE = 0
    DIAGNOSTIC = 1


class Status(IntEnum):
    OK = 0
    BUSY = 1
    UNSAFE = 2
    MALFORMED = 3
    SESSION = 4
    ORDER = 5
    CRC = 6
    ROLE = 7
    KIND = 8
    TIMEOUT = 9
    INTERNAL = 10


def _integer(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise BattleMailboxError(f"{name} is outside its integer bounds")


def _enum(value, enum, name):
    if isinstance(value, bool) or not isinstance(value, int) or value not in tuple(enum):
        raise BattleMailboxError(f"unsupported {name}")


def _uuid(value, name):
    try:
        valid = (type(value) is str and len(value) == 36 and str(UUID(value)) == value
                 and UUID(value).int != 0)
    except (ValueError, TypeError, AttributeError):
        valid = False
    if not valid:
        raise BattleMailboxError(f"{name} must be a nonzero canonical UUID")
    return UUID(value).bytes


@dataclass(frozen=True)
class BattleBinding:
    generation: str
    players: tuple[str, ...]
    leases: tuple[int, ...]
    incarnations: tuple[int, ...]
    local_slot: int

    def __post_init__(self):
        _uuid(self.generation, "battle generation")
        if (type(self.players) is not tuple or len(self.players) not in (2, 4)
                or type(self.leases) is not tuple or type(self.incarnations) is not tuple
                or len(self.leases) != len(self.players) or len(self.incarnations) != len(self.players)):
            raise BattleMailboxError("binding needs exactly two or four immutable player/lease/incarnation entries")
        _integer(self.local_slot, 0, len(self.players)-1, "local slot")
        for player, lease, incarnation in zip(self.players, self.leases, self.incarnations):
            _uuid(player, "player")
            _integer(lease, 1, MAX_COUNTER, "player lease")
            _integer(incarnation, 1, _UINT32, "player incarnation")
        if len(set(self.players)) != len(self.players):
            raise BattleMailboxError("binding players must be distinct")

    @property
    def player_count(self):
        return len(self.players)

    def pack(self):
        padding = 4 - self.player_count
        players = b"".join(UUID(p).bytes for p in self.players) + bytes(padding * 16)
        return _BINDING.pack(UUID(self.generation).bytes, players,
            *(self.leases + (0,)*padding), *(self.incarnations + (0,)*padding),
            self.player_count, self.local_slot, Phase.DIAGNOSTIC, 0)

    @classmethod
    def unpack(cls, data):
        if type(data) is not bytes or len(data) != 116:
            raise BattleMailboxError("binding must contain exactly 116 bytes")
        generation, players, *fields = _BINDING.unpack(data)
        leases, incarnations = fields[:4], fields[4:8]
        count, local, mode, reserved = fields[8:]
        if (count not in (2, 4) or mode != Phase.DIAGNOSTIC or reserved
                or any(players[count*16:]) or any(leases[count:]) or any(incarnations[count:])):
            raise BattleMailboxError("binding count, mode or unused fields are invalid")
        return cls(str(UUID(bytes=generation)),
            tuple(str(UUID(bytes=players[i*16:(i+1)*16])) for i in range(count)),
            tuple(leases[:count]), tuple(incarnations[:count]), local)

    def validate_control(self, control, *, player_id=None):
        if not isinstance(control, BattleControl):
            raise BattleMailboxError("binding needs a validated control")
        if (control.source_slot != self.local_slot
                or control.session_epoch != self.leases[self.local_slot]
                or control.incarnation != self.incarnations[self.local_slot]
                or (player_id is not None and player_id != self.players[self.local_slot])):
            raise BattleMailboxError("binding does not match the authenticated local participant")
        return self


@dataclass(frozen=True)
class DiagnosticBlock:
    generation: str
    source_slot: int
    token: int
    lease: int
    incarnation: int

    def __post_init__(self):
        _uuid(self.generation, "diagnostic generation")
        _integer(self.source_slot, 0, 3, "diagnostic source")
        _integer(self.token, 0, _UINT32, "diagnostic token")
        _integer(self.lease, 1, MAX_COUNTER, "diagnostic lease")
        _integer(self.incarnation, 1, _UINT32, "diagnostic incarnation")

    def pack(self):
        return _DIAGNOSTIC.pack(DIAGNOSTIC_MAGIC, 1, UUID(self.generation).bytes,
                               self.source_slot, self.token, self.lease, self.incarnation)

    @classmethod
    def unpack(cls, data):
        if type(data) is not bytes or len(data) != 40:
            raise BattleMailboxError("only exact 40-byte typed diagnostic blocks are supported")
        magic, version, generation, source, token, lease, incarnation = _DIAGNOSTIC.unpack(data)
        if magic != DIAGNOSTIC_MAGIC or version != 1:
            raise BattleMailboxError("unsupported diagnostic magic/version")
        return cls(str(UUID(bytes=generation)), source, token, lease, incarnation)

    def validate_binding(self, binding):
        if not isinstance(binding, BattleBinding):
            raise BattleMailboxError("frame needs a validated binding")
        source = self.source_slot
        if (source >= binding.player_count or self.generation != binding.generation
                or self.lease != binding.leases[source] or self.incarnation != binding.incarnations[source]):
            raise BattleMailboxError("diagnostic frame does not match the bound source")
        return self


@dataclass(frozen=True)
class BattleQuery:
    flags: int
    generation: str | None
    player_count: int
    local_slot: int
    mode: int
    last_sequence: int
    outbound_sequence: int
    outbound_kind: int
    outbound_size: int
    outbound_crc32: int
    read_offset: int
    received_mask: int
    remaining_frames: int

    @property
    def held(self): return bool(self.flags & 1)
    @property
    def expired(self): return bool(self.flags & 2)
    @property
    def outbound_pending(self): return bool(self.flags & 4)

    @classmethod
    def unpack(cls, data):
        if type(data) is not bytes or len(data) != 64:
            raise BattleMailboxError("query must contain exactly 64 bytes")
        flags, generation, count, local, mode, reserved, *words = _QUERY.unpack(data)
        sequence, out_seq, kind, size, crc, cursor, received, remaining, r1, r2 = words
        if reserved or r1 or r2 or flags & ~7 or count not in (0, 2, 4):
            raise BattleMailboxError("query flags, count or reserved fields are invalid")
        if not count:
            if any(data):
                raise BattleMailboxError("unbound query must be canonical zero data")
            return cls(flags, None, count, local, mode, *words[:8])
        if (not any(generation) or local >= count or mode != Phase.DIAGNOSTIC
                or not sequence or received & ~((1 << count)-1) or remaining > BATTLE_IDLE_FRAMES
                or (flags & 2 and not flags & 1) or (not flags & 1 and remaining)
                or (flags & 2 and remaining)):
            raise BattleMailboxError("query binding or held deadline is inconsistent")
        if size == 0:
            if out_seq or kind or crc or cursor or flags & 4:
                raise BattleMailboxError("empty outbound query is inconsistent")
        elif size != 40 or not out_seq or kind != Kind.DIAGNOSTIC or cursor not in (0, 40):
            raise BattleMailboxError("query exposes an unsupported outbound block")
        if not flags & 1 and (flags & 4 or received or size):
            raise BattleMailboxError("closed diagnostic channel cannot retain pending blocks")
        return cls(flags, str(UUID(bytes=generation)), count, local, mode, *words[:8])


@dataclass(frozen=True)
class BattleControl:
    incarnation: int
    session_epoch: int
    battle_id: str
    sequence: int
    opcode: int
    block_sequence: int = 0
    offset: int = 0
    total_size: int = 0
    phase: int = Phase.DIAGNOSTIC
    source_slot: int = 0
    kind: int = Kind.NONE
    status: int = Status.OK
    data: bytes = b""

    def __post_init__(self):
        _integer(self.incarnation, 1, _UINT32, "bridge incarnation")
        _integer(self.session_epoch, 1, MAX_COUNTER, "local lease")
        _uuid(self.battle_id, "battle ID")
        _integer(self.sequence, 1, _UINT32, "command sequence")
        _integer(self.block_sequence, 0, _UINT32, "block sequence")
        _integer(self.total_size, 0, BATTLE_BLOCK_SIZE, "block size")
        _integer(self.offset, 0, self.total_size, "block offset")
        _integer(self.source_slot, 0, 3, "source slot")
        for value, enum, name in ((self.opcode, Opcode, "opcode"), (self.status, Status, "status"),
                                 (self.phase, Phase, "phase"), (self.kind, Kind, "block kind")):
            _enum(value, enum, name)
        if type(self.data) is not bytes or len(self.data) > BATTLE_DATA_SIZE:
            raise BattleMailboxError("control data exceeds its byte bound")

    @property
    def length(self): return len(self.data)

    def pack(self):
        return _CONTROL.pack(self.incarnation, self.session_epoch, UUID(self.battle_id).bytes,
            self.sequence, self.block_sequence, self.offset, self.total_size,
            self.opcode, self.status, self.phase, self.source_slot, self.kind, 0,
            self.length, zlib.crc32(self.data), self.data + bytes(BATTLE_DATA_SIZE-self.length))

    @classmethod
    def unpack(cls, data):
        if type(data) is not bytes or len(data) != BATTLE_SLOT_SIZE:
            raise BattleMailboxError("control must contain exactly 240 bytes")
        inc, lease, battle, sequence, block, offset, size, op, status, phase, source, kind, reserved, length, crc, payload = _CONTROL.unpack(data)
        if reserved or length > BATTLE_DATA_SIZE or any(payload[length:]) or zlib.crc32(payload[:length]) != crc:
            raise BattleMailboxError("control reserved field, length, tail or CRC32 is invalid")
        return cls(inc, lease, str(UUID(bytes=battle)), sequence, op, block, offset, size,
                   phase, source, kind, status, payload[:length])

    def _no_block(self):
        if self.block_sequence or self.offset or self.total_size or self.kind != Kind.NONE:
            raise BattleMailboxError("non-block command cannot carry block fields")

    def validate_command(self, *, binding: BattleBinding | None = None, player_id=None):
        if binding is not None and not isinstance(binding, BattleBinding):
            raise BattleMailboxError("binding must be a validated immutable binding")
        if self.status != Status.OK:
            raise BattleMailboxError("command status must be zero")
        lengths = {Opcode.BIND: 116, Opcode.QUERY: 0, Opcode.EMIT_DIAGNOSTIC: 4,
                   Opcode.READ_OUT: 0, Opcode.ACK_OUT: 8, Opcode.RECEIVE: 40,
                   Opcode.CLEAR_RX: 4, Opcode.CLOSE: 0, Opcode.KEEP: 0}
        if self.length != lengths[self.opcode]:
            raise BattleMailboxError("command has an unsupported data length")
        if self.opcode not in (Opcode.READ_OUT, Opcode.ACK_OUT, Opcode.RECEIVE):
            self._no_block()
        elif not self.block_sequence or self.kind != Kind.DIAGNOSTIC or self.total_size != 40:
            raise BattleMailboxError("only sequenced typed diagnostic blocks are supported")
        if self.opcode in (Opcode.READ_OUT, Opcode.RECEIVE) and self.offset:
            raise BattleMailboxError("the diagnostic block begins at offset zero")
        if self.opcode == Opcode.ACK_OUT:
            masks = ((2, 14), (1, 13), (11,), (7,))
            if self.offset != 40 or struct.unpack_from("<I", self.data, 4)[0] not in masks[self.source_slot]:
                raise BattleMailboxError("diagnostic acknowledgment needs the exact peer delivery mask")
        if self.opcode == Opcode.BIND:
            BattleBinding.unpack(self.data).validate_control(self, player_id=player_id)
        if self.opcode == Opcode.RECEIVE:
            frame = DiagnosticBlock.unpack(self.data)
            if frame.source_slot != self.source_slot:
                raise BattleMailboxError("frame source disagrees with its routed command")
            if binding is not None:
                frame.validate_binding(binding)
                if self.source_slot == binding.local_slot:
                    raise BattleMailboxError("remote delivery cannot impersonate local loopback")
        if self.opcode == Opcode.CLEAR_RX:
            mask, = struct.unpack("<I", self.data)
            if not 1 <= mask <= 15:
                raise BattleMailboxError("receive clearing needs a bounded nonzero mask")
        if binding is not None:
            if (self.incarnation != binding.incarnations[binding.local_slot]
                    or self.session_epoch != binding.leases[binding.local_slot]
                    or (self.opcode != Opcode.RECEIVE and self.source_slot != binding.local_slot)):
                raise BattleMailboxError("command does not match the local binding")
            if self.opcode == Opcode.ACK_OUT:
                mask = ((1 << binding.player_count)-1) ^ (1 << binding.local_slot)
                if struct.unpack_from("<I", self.data, 4)[0] != mask:
                    raise BattleMailboxError("delivery mask does not cover precisely the other participants")
            if self.opcode == Opcode.CLEAR_RX and struct.unpack("<I", self.data)[0] & ~((1 << binding.player_count)-1):
                raise BattleMailboxError("receive mask names a nonparticipant")
        return self

    def validate_response(self, request: BattleControl | None = None):
        if request is not None:
            if not isinstance(request, BattleControl):
                raise BattleMailboxError("response needs a validated correlated request")
            names = ("incarnation", "session_epoch", "battle_id", "sequence", "opcode", "block_sequence",
                     "offset", "total_size", "phase", "source_slot", "kind")
            if any(getattr(self, n) != getattr(request, n) for n in names):
                raise BattleMailboxError("response does not echo its request correlation fields")
        if self.status != Status.OK:
            if self.data:
                raise BattleMailboxError("error responses must have empty data")
            return self
        if self.opcode in (Opcode.BIND, Opcode.QUERY, Opcode.EMIT_DIAGNOSTIC,
                           Opcode.CLEAR_RX, Opcode.CLOSE, Opcode.KEEP):
            self._no_block()
        elif (not self.block_sequence or self.kind != Kind.DIAGNOSTIC or self.total_size != 40
                or self.offset != (40 if self.opcode == Opcode.ACK_OUT else 0)):
            raise BattleMailboxError("success response has unsupported block fields")
        if self.opcode in (Opcode.BIND, Opcode.QUERY, Opcode.EMIT_DIAGNOSTIC, Opcode.KEEP):
            query = BattleQuery.unpack(self.data)
            if query.player_count and query.local_slot != self.source_slot:
                raise BattleMailboxError("query response names a different local participant")
            if self.opcode != Opcode.QUERY and (not query.held or query.expired):
                raise BattleMailboxError("successful channel mutator must confirm an active hold")
            if self.opcode != Opcode.QUERY and query.last_sequence != self.sequence:
                raise BattleMailboxError("successful mutator query has the wrong command sequence")
            if self.opcode == Opcode.BIND and request is not None:
                bound = BattleBinding.unpack(request.data)
                if (query.generation, query.player_count, query.local_slot, query.mode) != (
                        bound.generation, bound.player_count, bound.local_slot, Phase.DIAGNOSTIC):
                    raise BattleMailboxError("binding response does not confirm the requested roster")
        elif self.opcode == Opcode.READ_OUT:
            if self.total_size != 40 or self.offset or not self.block_sequence or self.kind != Kind.DIAGNOSTIC:
                raise BattleMailboxError("read response is outside the diagnostic block")
            frame = DiagnosticBlock.unpack(self.data)
            if frame.source_slot != self.source_slot or (frame.lease, frame.incarnation) != (self.session_epoch, self.incarnation):
                raise BattleMailboxError("outbound diagnostic source disagrees with the local command")
        elif self.data:
            raise BattleMailboxError("successful acknowledgment must have empty data")
        return self


def command_packet(control):
    return b"D" + control.validate_command().pack()


def response_packet(control):
    return b"E" + control.validate_response().pack()


def parse_command_packet(payload):
    if type(payload) is not bytes or payload[:1] != b"D":
        raise BattleMailboxError("expected a battle channel command packet")
    return BattleControl.unpack(payload[1:]).validate_command()


def parse_response_packet(payload):
    if type(payload) is not bytes or payload[:1] != b"E":
        raise BattleMailboxError("expected a battle channel response packet")
    return BattleControl.unpack(payload[1:]).validate_response()


def capability_packet():
    return b"W" + struct.pack("<HHHH", BATTLE_ABI_VERSION, BATTLE_MAILBOX_SIZE, BATTLE_SLOT_SIZE, BATTLE_DATA_SIZE)


def validate_capability_packet(payload):
    if type(payload) is not bytes or payload != capability_packet():
        raise BattleMailboxError("battle capability disagrees with the verified diagnostic ABI")


@dataclass(frozen=True)
class BattleMailbox:
    frame: int
    state: State
    command_generation: int
    response_generation: int
    command: BattleControl | None
    response: BattleControl | None


def inspect_battle_mailbox(payload):
    if type(payload) is not bytes or len(payload) != BATTLE_MAILBOX_SIZE:
        raise BattleMailboxError("battle mailbox must contain exactly 512 bytes")
    magic, version, size, frame, state, r1, r2 = struct.unpack_from("<IHHIIII", payload)
    if magic != BATTLE_MAILBOX_MAGIC or version != BATTLE_ABI_VERSION or size != BATTLE_MAILBOX_SIZE or r1 or r2:
        raise BattleMailboxError("battle mailbox header is invalid")
    _enum(state, State, "mailbox state")
    generations = tuple(struct.unpack_from("<I", payload, o)[0] for o in (COMMAND_GEN_OFFSET, RESPONSE_GEN_OFFSET))
    if any(g & 1 for g in generations):
        raise BattleMailboxError("mailbox snapshot has an uncommitted slot")
    values = []
    for generation, offset, response in zip(generations, (COMMAND_OFFSET, RESPONSE_OFFSET), (False, True)):
        raw = payload[offset:offset+BATTLE_SLOT_SIZE]
        if not generation:
            if any(raw):
                raise BattleMailboxError("unpublished mailbox slot must be zero")
            values.append(None)
        else:
            control = BattleControl.unpack(raw)
            values.append(control.validate_response() if response else control.validate_command())
    return BattleMailbox(frame, State(state), *generations, *values)
