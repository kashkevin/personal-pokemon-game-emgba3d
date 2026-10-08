"""Optional resume ABI1 payloads; the original ABI3 capability is insufficient.

The transport must verify the optional ROM marker before using these opcodes.
No payload permits replacing an incarnation, party, generation or battle.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct
from uuid import UUID

from .battle_mailbox import BattleMailboxError, _integer, _uuid
from .native_battle import NativeBinding, NativeQuery
from .protocol import MAX_COUNTER


@dataclass(frozen=True)
class Admission:
    generation: str
    player_id: str
    runtime_id: str

    def __post_init__(self):
        for value in (self.generation, self.player_id, self.runtime_id):
            _uuid(value, "provisional native identity")

    def pack(self):
        return b"".join(UUID(value).bytes for value in (self.generation, self.player_id, self.runtime_id))

    @classmethod
    def unpack(cls, data):
        if type(data) is not bytes or len(data) != 48:
            raise BattleMailboxError("provisional admission requires exactly 48 bytes")
        return cls(*(str(UUID(bytes=data[offset:offset+16])) for offset in (0, 16, 32)))


@dataclass(frozen=True)
class Retirement:
    generation: str
    release_sequence: int
    party_crc32: int
    outcome: int

    def __post_init__(self):
        _uuid(self.generation, "retired battle generation")
        _integer(self.release_sequence, 1, 0xFFFFFFFF, "terminal release sequence")
        _integer(self.party_crc32, 0, 0xFFFFFFFF, "restored party checksum")
        _integer(self.outcome, 1, 3, "terminal normalized outcome")

    def pack(self):
        return UUID(self.generation).bytes + struct.pack("<III", self.release_sequence, self.party_crc32, self.outcome)

    @classmethod
    def unpack(cls, data):
        if type(data) is not bytes or len(data) != 28:
            raise BattleMailboxError("terminal retirement requires exactly 28 bytes")
        return cls(str(UUID(bytes=data[:16])), *struct.unpack_from("<III", data, 16))


def validate_resume_token(token, epoch):
    if type(token) is not bytes or len(token) != 16 or not any(token):
        raise BattleMailboxError("resume needs one nonzero 16-byte quorum token")
    _integer(epoch, 1, MAX_COUNTER, "resume epoch")


@dataclass(frozen=True)
class ResumeAuthorization:
    binding: NativeBinding
    token: bytes
    epoch: int
    last_sequence: int

    def __post_init__(self):
        if not isinstance(self.binding, NativeBinding):
            raise BattleMailboxError("resume needs the complete immutable native roster")
        validate_resume_token(self.token, self.epoch)
        _integer(self.last_sequence, 1, 0xFFFFFFFF, "suspended native sequence")

    def pack(self):
        return self.binding.pack() + self.token + struct.pack("<II", self.epoch, self.last_sequence)

    @classmethod
    def unpack(cls, data):
        if type(data) is not bytes or len(data) != 140:
            raise BattleMailboxError("resume authorization requires exactly 140 bytes")
        return cls(NativeBinding.unpack(data[:116]), data[116:132], *struct.unpack_from("<II", data, 132))

    def validate_previous(self, previous):
        if (not isinstance(previous, NativeBinding)
                or (self.binding.generation, self.binding.players, self.binding.incarnations,
                    self.binding.local_slot, self.binding.mode, self.binding.resumable) !=
                   (previous.generation, previous.players, previous.incarnations, previous.local_slot, previous.mode, previous.resumable)
                or any(new < old for new, old in zip(self.binding.leases, previous.leases))):
            raise BattleMailboxError("resume cannot replace the original core roster or retire a newer lease")


@dataclass(frozen=True)
class ResumeQuery:
    query: NativeQuery
    state: int
    armed: bool
    previous_state: int
    epoch: int
    token: bytes

    @property
    def suspended(self):
        return self.state == 9

    @property
    def released(self):
        return self.state == 1

    @classmethod
    def unpack(cls, data):
        if type(data) is not bytes or len(data) != 88:
            raise BattleMailboxError("resume query requires exactly 88 bytes")
        query = NativeQuery.unpack(data[:64])
        flags, epoch = struct.unpack_from("<II", data, 64)
        state, armed, previous = flags & 255, bool(flags & 256), flags >> 16
        token = data[72:]
        if (flags & 0xFE00 or state not in range(1, 10) or previous not in (0, 2, 4, 5, 6, 7)
                or not query.held or epoch > MAX_COUNTER
                or (state == 1 and (not armed or not query.terminal_waiting or previous
                                   or query.prepared or query.started or query.restored))
                or bool(epoch) != bool(any(token))
                or (state == 9 and (not armed or not previous or not query.expired or not query.recovery_required))
                or (not armed and (previous or epoch))
                or query.expired != (state in (3, 8, 9))
                or query.recovery_required != (state in (8, 9))):
            raise BattleMailboxError("resume query flags or retained lifecycle are inconsistent")
        return cls(query, state, armed, previous, epoch, token)
