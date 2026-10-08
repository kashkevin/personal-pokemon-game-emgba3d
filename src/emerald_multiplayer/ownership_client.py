"""Bounded ownership controls; only the ROM may assign IDs to live Pokémon."""
from __future__ import annotations

from dataclasses import dataclass
import struct
from uuid import UUID

from .save_mailbox import SaveMailboxError

_QUERY = struct.Struct("<IIII16s16s16sIIII")
_GRANT = struct.Struct("<16s16s16sIII")
MAX_SERIAL = (1 << 20) - 1


@dataclass(frozen=True)
class OwnershipStatus:
    enrolled: bool
    active_grant: bool
    missing: int
    remaining: int
    retire_count: int
    world_id: str
    player_id: str
    grant_id: str
    next_serial: int
    end_exclusive: int
    lease_epoch: int
    incarnation: int


def parse_status(data: bytes) -> OwnershipStatus:
    if not isinstance(data, bytes) or len(data) != _QUERY.size:
        raise SaveMailboxError("ownership status must contain exactly 80 bytes")
    flags, missing, remaining, retired, world, player, grant, next_id, end, lease, incarnation = _QUERY.unpack(data)
    if flags & ~3 or missing > 432 or retired > 128:
        raise SaveMailboxError("ownership status fields are invalid")
    if flags & 1:
        if (not all(any(value) for value in (world, player, grant))
                or not 1 <= next_id <= end <= MAX_SERIAL + 1 or not lease or not incarnation
                or remaining != (end - next_id if flags & 2 else 0)):
            raise SaveMailboxError("ownership allocation status is invalid")
    elif flags or remaining or retired or any(world + player + grant) or any((next_id, end, lease, incarnation)):
        raise SaveMailboxError("unenrolled ownership status contains authority")
    return OwnershipStatus(bool(flags & 1), bool(flags & 2), missing, remaining, retired,
                           str(UUID(bytes=world)), str(UUID(bytes=player)), str(UUID(bytes=grant)),
                           next_id, end, lease, incarnation)


def grant_bytes(grant: dict, *, enroll: bool) -> bytes:
    """Caller has already validated the authenticated, correlated grant reply."""
    return _GRANT.pack(UUID(grant["world_id"]).bytes, UUID(grant["player_id"]).bytes,
                       UUID(grant["grant_id"]).bytes, grant["start"], grant["end_exclusive"], int(enroll))
