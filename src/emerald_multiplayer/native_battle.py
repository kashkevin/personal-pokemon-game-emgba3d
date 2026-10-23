"""ABI2 singles, ABI3 full-party Multi, co-op Gym and free-for-all envelopes; ABI1 stays separate.

These codecs validate bounded transport envelopes. Complete startup blocks still
need canonical-save comparison, and controller blocks need the stateful native
command validator before routing. Importing this module enables no transport.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import ClassVar
import struct
from uuid import UUID
import zlib

from .battle_mailbox import (
    BattleBinding, BattleMailboxError, Status, _CONTROL, _QUERY,
    _enum, _integer, _uuid, uuid_text,
)
from .coop_code import valid_code
from .rival_catalogue import valid_preparation_word
from .protocol import MAX_COUNTER

ABI_VERSION = 2
PHASE = 2
MULTI_ABI_VERSION = 3
MULTI_PHASE = 3
# Co-op Gym phase (ABI3 + the ROM's co-op marker): two trainers on one side
# against a Gym Leader and partner run by the master core's AI.
COOP_PHASE = 4
COOP_GYM_COUNT = 8
# Four-player free-for-all phase (ABI3 + the ROM's free-for-all marker): the four-core full Multi with every trainer on
# a side of their own. Its result is the winner (slot + 1) or a draw (FFA_DRAW); see docs/free-for-all.md.
FFA_PHASE = 5
FFA_DRAW = 5
# Update 32: the three-player free-for-all (1v1v1; ABI3 + the free-for-all marker + the game's 1v1v1 marker): three cores,
# the free-for-all's four battlers with the fourth place (battler 3) empty. Results as FFA_PHASE: winner slot + 1 or FFA_DRAW.
FFA3_PHASE = 6
FFA_PHASES = (FFA_PHASE, FFA3_PHASE)
_U32 = 0xFFFFFFFF
_PREPARE = struct.Struct("<IIII16sI")


def player_count_for_phase(phase):
    """Trainers (cores) in a native phase."""
    _integer(phase, PHASE, FFA3_PHASE, "native phase")
    return 3 if phase == FFA3_PHASE else 4 if phase in (MULTI_PHASE, FFA_PHASE) else 2


def battler_count_for_phase(phase):
    """Battlers on the field: both double phases and both free-for-alls have four (the 1v1v1's fourth is empty)."""
    _integer(phase, PHASE, FFA3_PHASE, "native phase")
    return 2 if phase == PHASE else 4


def outcomes_for_phase(phase):
    """The normalized results a phase's battle can end with: a free-for-all names its winner (slot + 1) or a draw."""
    if phase in FFA_PHASES:
        return tuple(range(1, player_count_for_phase(phase) + 1)) + (FFA_DRAW,)
    return (1, 2, 3)


def battler_owner(phase, battler):
    """The core supplying a battler's choices. Co-op: slot 0 runs both AI foes. The 1v1v1's empty place (battler 3) has
    no core: nobody supplies its choices (it is absent from the first turn)."""
    if phase == COOP_PHASE:
        return 1 if battler == 2 else 0
    return battler


def supports_native_phase(abi, phase):
    return (type(abi) is int and type(phase) is int
            and ((abi == 2 and phase == 2) or (abi == 3 and phase in (2, 3, COOP_PHASE, FFA_PHASE, FFA3_PHASE))))


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
    ARM_RESUME = 14
    SUSPEND = 15
    REAUTHORIZE = 16
    RESUME = 17
    RESUME_QUERY = 18
    ADMIT = 19
    RETIRE = 20
    HANDOFF = 21
    ADMISSION_CANCEL_HOLD = 22
    ADMISSION_CANCEL_HANDOFF = 23
    ADMISSION_CANCEL_READY = 24
    PEEK = 25  # KNOWN_ISSUES MS-62: QUERY plus the outbound block's bytes (PC game, manifest battle_peek_abi_version 1)


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


class _NativeShape(BattleBinding):
    """The diagnostic binding layout as a native binding uses it: the 1v1v1 also binds three trainers."""
    _player_counts: ClassVar[tuple[int, ...]] = (2, 3, 4)


@dataclass(frozen=True)
class NativeBinding:
    generation: str
    players: tuple[str, ...]
    leases: tuple[int, ...]
    incarnations: tuple[int, ...]
    local_slot: int
    mode: int = PHASE
    resumable: bool = False

    def __post_init__(self):
        if type(self.resumable) is not bool:
            raise BattleMailboxError("resumable binding requires an explicit boolean")
        self._diagnostic_shape()
        if len(self.players) != player_count_for_phase(self.mode):
            raise BattleMailboxError("native phase requires its exact trainer count")

    def _diagnostic_shape(self):
        return _NativeShape(self.generation, self.players, self.leases,
                            self.incarnations, self.local_slot)

    def pack(self):
        raw = self._diagnostic_shape().pack()
        return raw[:114] + bytes((self.mode, int(self.resumable)))

    @classmethod
    def unpack(cls, data):
        if (type(data) is not bytes or len(data) != 116
                or data[114] not in (PHASE, MULTI_PHASE, COOP_PHASE, FFA_PHASE, FFA3_PHASE) or data[115] not in (0, 1)):
            raise BattleMailboxError("native binding requires exactly 116 phase2/3/4/5/6 bytes")
        shape = _NativeShape.unpack(data[:114] + b"\x01\0")
        return cls(shape.generation, shape.players, shape.leases,
                   shape.incarnations, shape.local_slot, data[114], bool(data[115]))

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
    gym: int = 0  # co-op battle code (phase 4); for PvP zero, or a rival checkpoint's word (rival_catalogue.preparation_word)

    def __post_init__(self):
        _integer(self.checkpoint_revision, 1, MAX_COUNTER, "checkpoint revision")
        for name in ("native_counter", "trainer_id", "party_crc32"):
            _integer(getattr(self, name), 0, _U32, name)
        if type(self.rng) is not bytes or len(self.rng) != 16 or not any(self.rng):
            raise BattleMailboxError("preparation needs one nonzero 16-byte issued RNG state")
        if self.gym and not valid_code(self.gym) and not valid_preparation_word(self.gym):
            raise BattleMailboxError("unknown co-op battle code")

    def pack(self):
        return _PREPARE.pack(self.checkpoint_revision, self.native_counter,
                             self.trainer_id, self.party_crc32, self.rng, self.gym)

    @classmethod
    def unpack(cls, data):
        if type(data) is not bytes or len(data) != 36:
            raise BattleMailboxError("native preparation needs exactly 36 bytes")
        revision, counter, trainer, crc, rng, flags = _PREPARE.unpack(data)
        if flags and not valid_code(flags) and not valid_preparation_word(flags):
            raise BattleMailboxError("preparation flags carry only a co-op battle code or a rival checkpoint")
        return cls(revision, counter, trainer, crc, rng, flags)


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
    @property
    def provisional(self): return bool(self.flags & 128)
    @property
    def terminal_waiting(self): return bool(self.flags & 256)
    @property
    def handoff_waiting(self): return bool(self.flags & 512)
    @property
    def admission_cleanup_waiting(self): return bool(self.flags & 1024)

    @classmethod
    def unpack(cls, data):
        if type(data) is not bytes or len(data) != 64:
            raise BattleMailboxError("native query requires exactly 64 bytes")
        flags, generation, count, local, mode, reserved, *words = _QUERY.unpack(data)
        if not any(data):
            return cls(flags, None, count, local, mode, *words)
        seq, out_seq, kind, size, crc, cursor, received, remaining, revision, outcome = words
        expected_count = player_count_for_phase(mode)
        if flags & 1024:
            if (flags != 1025 or reserved or count != expected_count or local >= count
                    or not any(generation) or any(words[1:])):
                raise BattleMailboxError("admission cleanup query contains unrelated native state")
            return cls(flags, uuid_text(generation), count, local, mode, *words)
        if flags & (256 | 512):
            if (flags not in (257, 513) or reserved or count != expected_count or local >= count
                    or not any(generation) or not seq or any(words[1:])):
                raise BattleMailboxError("terminal field handoff query contains unrelated native state")
            return cls(flags, uuid_text(generation), count, local, mode, *words)
        if flags & 128:
            if (flags != 129 or reserved or count != expected_count or local >= count
                    or not any(generation) or seq == 0xFFFFFFFF or any(words[1:])):
                raise BattleMailboxError("provisional admission query contains unrelated native state")
            return cls(flags, uuid_text(generation), count, local, mode, *words)
        if (reserved or flags & ~127 or count != expected_count or local >= count
                or not any(generation) or not seq or received & ~((1 << count)-1) or remaining > 600
                or revision > MAX_COUNTER or outcome not in (0, *outcomes_for_phase(mode))
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
        return cls(flags, uuid_text(generation), count, local, mode, *words)


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
        return _CONTROL.pack(self.incarnation, self.session_epoch, _uuid(self.battle_id, "battle ID"),
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
        return cls(inc, lease, uuid_text(battle), seq, op, block, offset,
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
            Opcode.ABORT_PRE_START: 0, Opcode.RELEASE: 8, Opcode.ARM_RESUME: 0,
            Opcode.SUSPEND: 0, Opcode.REAUTHORIZE: 140, Opcode.RESUME: 20,
            Opcode.RESUME_QUERY: 0, Opcode.ADMIT: 48, Opcode.RETIRE: 28, Opcode.HANDOFF: 28,
            Opcode.ADMISSION_CANCEL_HOLD: 84, Opcode.ADMISSION_CANCEL_HANDOFF: 84, Opcode.ADMISSION_CANCEL_READY: 52,
            Opcode.PEEK: 0}
        if len(self.data) != lengths[self.opcode]:
            raise BattleMailboxError("native command has the wrong exact payload length")
        if self.opcode == Opcode.BIND:
            requested = NativeBinding.unpack(self.data)
            requested.validate_control(self, player_id=player_id)
            if binding is not None and requested != binding:
                raise BattleMailboxError("binding command changes the approved roster")
        elif self.opcode == Opcode.PREPARE:
            Preparation.unpack(self.data)
        elif self.opcode == Opcode.REAUTHORIZE:
            from .native_battle_resume import ResumeAuthorization
            renewal = ResumeAuthorization.unpack(self.data)
            renewal.binding.validate_control(self, player_id=player_id)
            if binding is not None and renewal.binding != binding:
                raise BattleMailboxError("resume authorization changed the approved binding")
        elif self.opcode == Opcode.RESUME:
            from .native_battle_resume import validate_resume_token
            validate_resume_token(self.data[:16], struct.unpack_from("<I", self.data, 16)[0])
        elif self.opcode == Opcode.ADMIT:
            from .native_battle_resume import Admission
            admission = Admission.unpack(self.data)
            if player_id is not None and admission.player_id != player_id:
                raise BattleMailboxError("provisional admission changed the authenticated player")
        elif self.opcode == Opcode.ADMISSION_CANCEL_READY:
            from .native_battle_resume import Admission
            admission = Admission.unpack(self.data[:48])
            original_lease = struct.unpack_from("<I", self.data, 48)[0]
            if (self.sequence != 1 or not 1 <= original_lease <= self.session_epoch
                    or player_id is not None and admission.player_id != player_id):
                raise BattleMailboxError("cleanup readiness changed the original native identity")
        elif self.opcode in (Opcode.ADMISSION_CANCEL_HOLD, Opcode.ADMISSION_CANCEL_HANDOFF):
            from .battle_admission_cleanup_protocol import AdmissionCancellation
            cancellation = AdmissionCancellation.unpack(self.data)
            if (self.sequence != 1 or cancellation.original_lease > self.session_epoch
                    or player_id is not None and cancellation.admission.player_id != player_id):
                raise BattleMailboxError("admission cleanup changed its original identity or lease")
        elif self.opcode in (Opcode.RETIRE, Opcode.HANDOFF):
            self._retirement()
        elif self.opcode == Opcode.RELEASE:
            if struct.unpack_from("<I", self.data, 4)[0] not in outcomes_for_phase(self.phase):
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

    def _retirement(self):
        from .native_battle_resume import Retirement
        retirement = Retirement.unpack(self.data)
        if retirement.outcome not in outcomes_for_phase(self.phase):
            raise BattleMailboxError("terminal retirement needs its release's normalized outcome")
        return retirement

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
        if self.opcode == Opcode.ADMISSION_CANCEL_READY:
            self.validate_command()
            if request is not None and self.data != request.data:
                raise BattleMailboxError("cleanup readiness changed the original native identity")
        elif self.opcode in (Opcode.ADMISSION_CANCEL_HOLD, Opcode.ADMISSION_CANCEL_HANDOFF):
            from .battle_admission_cleanup_protocol import AdmissionCancellation
            AdmissionCancellation.unpack(self.data)
            if request is not None and self.data != request.data:
                raise BattleMailboxError("admission cancellation receipt changed its identity")
        elif self.opcode in (Opcode.RETIRE, Opcode.HANDOFF):
            self._retirement()
            if request is not None and self.data != request.data:
                raise BattleMailboxError("retirement receipt changed the exact terminal release")
        elif self.opcode == Opcode.ADMIT:
            query = NativeQuery.unpack(self.data)
            if (not query.provisional or (query.local_slot, query.mode) != (self.source_slot, self.phase)
                    or (request is not None and query.generation != str(UUID(bytes=request.data[:16])))):
                raise BattleMailboxError("admission did not confirm the exact provisional native hold")
        elif Opcode.SUSPEND <= self.opcode <= Opcode.RESUME_QUERY:
            from .native_battle_resume import ResumeQuery
            query = ResumeQuery.unpack(self.data)
            if (query.query.local_slot, query.query.mode) != (self.source_slot, self.phase):
                raise BattleMailboxError("resume response changed the local participant or mode")
            if self.opcode in (Opcode.SUSPEND, Opcode.REAUTHORIZE) and not (query.suspended or query.released):
                raise BattleMailboxError("resume preparation did not confirm a suspended core")
            if self.opcode == Opcode.RESUME and (query.state not in (1, 2, 4, 5, 6, 7) or not query.armed):
                raise BattleMailboxError("resume commit did not leave suspension")
            if request is not None and self.opcode == Opcode.REAUTHORIZE:
                from .native_battle_resume import ResumeAuthorization
                renewal = ResumeAuthorization.unpack(request.data)
                if (query.token, query.epoch, query.query.last_sequence, query.query.generation) != (
                        renewal.token, renewal.epoch, renewal.last_sequence, renewal.binding.generation):
                    raise BattleMailboxError("resume receipt changed its exact renewal")
            if request is not None and self.opcode == Opcode.RESUME:
                if (query.token, query.epoch) != (request.data[:16], struct.unpack_from("<I", request.data, 16)[0]):
                    raise BattleMailboxError("resume receipt changed its quorum token")
        elif self.opcode in (Opcode.BIND, Opcode.QUERY, Opcode.KEEP, Opcode.PREPARE, Opcode.START, Opcode.ARM_RESUME):
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
        elif self.opcode == Opcode.PEEK:
            peek_parts(self)
        elif self.opcode == Opcode.READ_OUT:
            if len(self.data) != min(128, self.total_size-self.offset):
                raise BattleMailboxError("native read response has the wrong chunk length")
        elif self.data:
            raise BattleMailboxError("native acknowledgement must be empty")
        return self


def peek_parts(response):
    """KNOWN_ISSUES MS-62: a successful PEEK's query and, when its core has an outbound block of at most one chunk not yet
    read, that block's exact bytes (None otherwise). The game sends the bytes only then; their CRC is the query's."""
    data = response.data
    if len(data) < 64:
        raise BattleMailboxError("native peek requires its 64-byte query")
    query = NativeQuery.unpack(data[:64])
    if query.player_count and (query.local_slot != response.source_slot or query.mode != response.phase):
        raise BattleMailboxError("native peek names the wrong local participant/phase")
    block = data[64:]
    if not block:
        return query, None
    if (not query.held or not query.outbound_pending or query.read_offset or len(block) != query.outbound_size
            or len(block) > 128 or zlib.crc32(block) != query.outbound_crc32):
        raise BattleMailboxError("native peek bytes differ from its outbound block")
    return query, block
