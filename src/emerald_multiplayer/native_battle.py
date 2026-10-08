"""ABI2 singles and ABI3 full-party Multi envelopes; ABI1 stays separate.

These codecs validate bounded transport envelopes. Complete startup blocks still
need canonical-save comparison, and controller blocks need the stateful native
command validator before routing. Importing this module enables no transport.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import struct
from uuid import UUID
import zlib

from .battle_mailbox import (
    BattleBinding, BattleMailboxError, Status, _CONTROL, _QUERY,
    _enum, _integer, _uuid,
)
from .protocol import MAX_COUNTER

ABI_VERSION = 2
PHASE = 2
MULTI_ABI_VERSION = 3
MULTI_PHASE = 3
_U32 = 0xFFFFFFFF
_PREPARE = struct.Struct("<IIII16sI")


def player_count_for_phase(phase):
    _integer(phase, PHASE, MULTI_PHASE, "native phase")
    return 2 if phase == PHASE else 4


def supports_native_phase(abi, phase):
    return (type(abi) is int and type(phase) is int
            and ((abi == 2 and phase == 2) or (abi == 3 and phase in (2, 3))))


class Opcode(IntEnum):
    BIND = 1
    QUERY = 2
    READ_OUT = 4
    ACK_OUT = 5
    RECEIVE = 6
    KEEP = 9
    PREPARE = 10
    START = 11
    ABORT_PRE_START = 12
    RELEASE = 13


class Kind(IntEnum):
    NONE = 0
    TRAINER = 2
    START_HEADER = 3
    PARTY_0 = 4
    PARTY_1 = 5
    PARTY_2 = 6
    RNG = 7
    CONTROLLER = 8


def validate_block_size(kind, size):
    """Validate allocation bounds only; this does not validate block contents."""
    _enum(kind, Kind, "native block kind")
    _integer(size, 0, 256, "native block size")
    sizes = {Kind.TRAINER: 28, Kind.START_HEADER: 32, Kind.PARTY_0: 200,
             Kind.PARTY_1: 200, Kind.PARTY_2: 200, Kind.RNG: 16}
    if kind == Kind.CONTROLLER:
        if size not in (12, 16, 20, 24, 28, 36, 56, 64, 92, 156):
            raise BattleMailboxError("controller size is outside the audited command table")
    elif kind not in sizes or size != sizes[kind]:
        raise BattleMailboxError("native block has the wrong exact size")


@dataclass(frozen=True)
class NativeBinding:
    generation: str
    players: tuple[str, ...]
    leases: tuple[int, ...]
    incarnations: tuple[int, ...]
    local_slot: int
    mode: int = PHASE

    def __post_init__(self):
        self._diagnostic_shape()
        if len(self.players) != player_count_for_phase(self.mode):
            raise BattleMailboxError("native phase requires its exact trainer count")

    def _diagnostic_shape(self):
        return BattleBinding(self.generation, self.players, self.leases,
                             self.incarnations, self.local_slot)

    def pack(self):
        raw = self._diagnostic_shape().pack()
        return raw[:114] + bytes((self.mode, 0))

    @classmethod
    def unpack(cls, data):
        if type(data) is not bytes or len(data) != 116 or data[114] not in (PHASE, MULTI_PHASE):
            raise BattleMailboxError("native binding requires exactly 116 phase2/3 bytes")
        shape = BattleBinding.unpack(data[:114] + b"\x01" + data[115:])
        return cls(shape.generation, shape.players, shape.leases,
                   shape.incarnations, shape.local_slot, data[114])

    def validate_control(self, control, *, player_id=None):
        if not isinstance(control, NativeControl):
            raise BattleMailboxError("native binding needs a native control")
        if (control.phase != self.mode or control.source_slot != self.local_slot
                or control.session_epoch != self.leases[self.local_slot]
                or control.incarnation != self.incarnations[self.local_slot]
                or (player_id is not None and player_id != self.players[self.local_slot])):
            raise BattleMailboxError("native binding disagrees with the authenticated participant")


@dataclass(frozen=True)
class Preparation:
    checkpoint_revision: int
    native_counter: int
    trainer_id: int
    party_crc32: int
    rng: bytes

    def __post_init__(self):
        _integer(self.checkpoint_revision, 1, MAX_COUNTER, "checkpoint revision")
        for name in ("native_counter", "trainer_id", "party_crc32"):
            _integer(getattr(self, name), 0, _U32, name)
        if type(self.rng) is not bytes or len(self.rng) != 16 or not any(self.rng):
            raise BattleMailboxError("preparation needs one nonzero 16-byte issued RNG state")

    def pack(self):
        return _PREPARE.pack(self.checkpoint_revision, self.native_counter,
                             self.trainer_id, self.party_crc32, self.rng, 0)

    @classmethod
    def unpack(cls, data):
        if type(data) is not bytes or len(data) != 36:
            raise BattleMailboxError("native preparation needs exactly 36 bytes")
        revision, counter, trainer, crc, rng, flags = _PREPARE.unpack(data)
        if flags:
            raise BattleMailboxError("preparation flags are reserved")
        return cls(revision, counter, trainer, crc, rng)


@dataclass(frozen=True)
class NativeQuery:
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
    checkpoint_revision: int
    outcome: int

    @property
    def held(self): return bool(self.flags & 1)
    @property
    def expired(self): return bool(self.flags & 2)
    @property
    def outbound_pending(self): return bool(self.flags & 4)
    @property
    def prepared(self): return bool(self.flags & 8)
    @property
    def started(self): return bool(self.flags & 16)
    @property
    def restored(self): return bool(self.flags & 32)
    @property
    def recovery_required(self): return bool(self.flags & 64)

    @classmethod
    def unpack(cls, data):
        if type(data) is not bytes or len(data) != 64:
            raise BattleMailboxError("native query requires exactly 64 bytes")
        flags, generation, count, local, mode, reserved, *words = _QUERY.unpack(data)
        if not any(data):
            return cls(flags, None, count, local, mode, *words)
        seq, out_seq, kind, size, crc, cursor, received, remaining, revision, outcome = words
        expected_count = player_count_for_phase(mode)
        if (reserved or flags & ~127 or count != expected_count or local >= count
                or not any(generation) or not seq or received & ~((1 << count)-1) or remaining > 600
                or revision > MAX_COUNTER or outcome not in (0, 1, 2, 3)
                or (flags & 2 and (not flags & 1 or remaining))
                or (not flags & 1 and (remaining or flags & ~1 or received or size))
                or (flags & 64 and flags & 3 != 3)
                or (flags & (16 | 32) and not flags & 8)
                or (flags & 32 and (not flags & 16 or not outcome))
                or bool(flags & 8) != bool(revision)
                or (outcome and not flags & 16)):
            raise BattleMailboxError("native query binding, flags or lifecycle is inconsistent")
        if size:
            validate_block_size(kind, size)
            if not out_seq or cursor not in (0, 128, size) or cursor > size:
                raise BattleMailboxError("native query outbound cursor is inconsistent")
        elif out_seq or kind or crc or cursor or flags & 4:
            raise BattleMailboxError("empty native outbound descriptor is inconsistent")
        return cls(flags, str(UUID(bytes=generation)), count, local, mode, *words)


@dataclass(frozen=True)
class NativeControl:
    incarnation: int
    session_epoch: int
    battle_id: str
    sequence: int
    opcode: int
    block_sequence: int = 0
    offset: int = 0
    total_size: int = 0
    phase: int = PHASE
    source_slot: int = 0
    kind: int = Kind.NONE
    status: int = Status.OK
    data: bytes = b""

    def __post_init__(self):
        _integer(self.incarnation, 1, _U32, "incarnation")
        _integer(self.session_epoch, 1, MAX_COUNTER, "local lease")
        _uuid(self.battle_id, "battle ID")
        _integer(self.sequence, 1, _U32, "command sequence")
        _integer(self.block_sequence, 0, _U32, "block sequence")
        _integer(self.total_size, 0, 256, "block size")
        _integer(self.offset, 0, self.total_size, "block offset")
        _integer(self.source_slot, 0, player_count_for_phase(self.phase)-1, "source slot")
        for value, enum, name in ((self.opcode, Opcode, "native opcode"),
                                 (self.kind, Kind, "native kind"), (self.status, Status, "status")):
            _enum(value, enum, name)
        if type(self.data) is not bytes or len(self.data) > 192:
            raise BattleMailboxError("native control payload exceeds its byte bound")

    def pack(self):
        return _CONTROL.pack(self.incarnation, self.session_epoch, UUID(self.battle_id).bytes,
            self.sequence, self.block_sequence, self.offset, self.total_size,
            self.opcode, self.status, self.phase, self.source_slot, self.kind, 0,
            len(self.data), zlib.crc32(self.data), self.data + bytes(192-len(self.data)))

    @classmethod
    def unpack(cls, data):
        if type(data) is not bytes or len(data) != 240:
            raise BattleMailboxError("native control requires exactly 240 bytes")
        inc, lease, battle, seq, block, offset, size, op, status, phase, source, kind, reserved, length, crc, payload = _CONTROL.unpack(data)
        if reserved or length > 192 or any(payload[length:]) or zlib.crc32(payload[:length]) != crc:
            raise BattleMailboxError("native control reserved field, tail, length or CRC is invalid")
        return cls(inc, lease, str(UUID(bytes=battle)), seq, op, block, offset,
                   size, phase, source, kind, status, payload[:length])

    def _validate_block(self):
        if self.opcode in (Opcode.READ_OUT, Opcode.ACK_OUT, Opcode.RECEIVE):
            validate_block_size(self.kind, self.total_size)
            if not self.block_sequence:
                raise BattleMailboxError("native block sequence must be nonzero")
            if self.opcode == Opcode.ACK_OUT:
                if self.offset != self.total_size:
                    raise BattleMailboxError("native acknowledgement must follow complete readback")
            elif self.offset >= self.total_size or self.offset % 128:
                raise BattleMailboxError("native read/delivery requires an exact chunk boundary")
        elif self.block_sequence or self.offset or self.total_size or self.kind:
            raise BattleMailboxError("native non-block command carries block fields")

    def validate_command(self, *, binding=None, player_id=None):
        self._validate_block()
        if self.status:
            raise BattleMailboxError("native command status must be zero")
        lengths = {Opcode.BIND: 116, Opcode.QUERY: 0, Opcode.READ_OUT: 0,
            Opcode.ACK_OUT: 8, Opcode.RECEIVE: min(128, self.total_size-self.offset),
            Opcode.KEEP: 0, Opcode.PREPARE: 36, Opcode.START: 0,
            Opcode.ABORT_PRE_START: 0, Opcode.RELEASE: 8}
        if len(self.data) != lengths[self.opcode]:
            raise BattleMailboxError("native command has the wrong exact payload length")
        if self.opcode == Opcode.BIND:
            requested = NativeBinding.unpack(self.data)
            requested.validate_control(self, player_id=player_id)
            if binding is not None and requested != binding:
                raise BattleMailboxError("binding command changes the approved roster")
        elif self.opcode == Opcode.PREPARE:
            Preparation.unpack(self.data)
        elif self.opcode == Opcode.RELEASE:
            if struct.unpack_from("<I", self.data, 4)[0] not in (1, 2, 3):
                raise BattleMailboxError("release needs a normalized win/loss/draw outcome")
        elif self.opcode == Opcode.ACK_OUT:
            mask = (1 << player_count_for_phase(self.phase))-1
            if struct.unpack_from("<I", self.data, 4)[0] != (mask ^ (1 << self.source_slot)):
                raise BattleMailboxError("native acknowledgement must name exactly all peers")
        if binding is not None:
            if not isinstance(binding, NativeBinding):
                raise BattleMailboxError("native control needs an immutable native binding")
            local = binding.local_slot
            if (self.phase != binding.mode or self.incarnation != binding.incarnations[local]
                    or self.session_epoch != binding.leases[local]
                    or (player_id is not None and player_id != binding.players[local])
                    or (self.source_slot == local if self.opcode == Opcode.RECEIVE else self.source_slot != local)):
                raise BattleMailboxError("native command disagrees with the authenticated local binding")
        return self

    def validate_response(self, request=None):
        if request is not None:
            if not isinstance(request, NativeControl):
                raise BattleMailboxError("native response needs a native request")
            names = ("incarnation", "session_epoch", "battle_id", "sequence", "opcode",
                     "block_sequence", "offset", "total_size", "phase", "source_slot", "kind")
            if any(getattr(self, n) != getattr(request, n) for n in names):
                raise BattleMailboxError("native response changed its request correlation")
        if self.status:
            if self.data:
                raise BattleMailboxError("native error response must be empty")
            return self
        self._validate_block()
        if self.opcode in (Opcode.BIND, Opcode.QUERY, Opcode.KEEP, Opcode.PREPARE, Opcode.START):
            query = NativeQuery.unpack(self.data)
            if query.player_count and (query.local_slot != self.source_slot or query.mode != self.phase):
                raise BattleMailboxError("native query names the wrong local participant/phase")
            if self.opcode != Opcode.QUERY and (not query.held or query.expired
                    or query.recovery_required or query.last_sequence != self.sequence):
                raise BattleMailboxError("native mutator did not confirm its active hold/sequence")
            if self.opcode == Opcode.PREPARE and (not query.prepared or query.started):
                raise BattleMailboxError("preparation response has inconsistent lifecycle flags")
            if self.opcode == Opcode.START and (not query.prepared or not query.started):
                raise BattleMailboxError("start response did not confirm native battle entry")
            if request is not None and self.opcode == Opcode.BIND:
                bound = NativeBinding.unpack(request.data)
                if (query.generation, query.local_slot) != (bound.generation, bound.local_slot):
                    raise BattleMailboxError("native bind response changed the generation/role")
            if request is not None and self.opcode == Opcode.PREPARE:
                if query.checkpoint_revision != Preparation.unpack(request.data).checkpoint_revision:
                    raise BattleMailboxError("preparation response changed the canonical revision")
        elif self.opcode == Opcode.READ_OUT:
            if len(self.data) != min(128, self.total_size-self.offset):
                raise BattleMailboxError("native read response has the wrong chunk length")
        elif self.data:
            raise BattleMailboxError("native acknowledgement must be empty")
        return self
