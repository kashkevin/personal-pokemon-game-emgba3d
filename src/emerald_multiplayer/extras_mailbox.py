"""Pure codecs for the native game's extras mailbox (EMX1, expansion Phase 6).

The native PC game (never the GBA ROM, whose bytes stay pinned) keeps a
384-byte mailbox for multiplayer Secret Bases next to the EMV1 spawn mailbox:

  game -> companion  'e'  capability: u16 version 1, u16 size 384, u16 160, u16 0
                     'x'  local record (168 bytes): u32 base sequence, u8 has-base,
                          3 zero bytes, the player's own 160-byte SecretBase record
  companion -> game  'y'  inbound record (176 bytes): u32 flags (bit 0: enabled),
                          u32 base ack, u32 record sequence, u8 source roster slot
                          (< 4), 3 zero bytes, the 160-byte record to apply

A record is the game's `struct SecretBase` (include/global.h, 160 bytes, little
endian) without the registry bookkeeping only the receiving save keeps. An
inbound record whose location byte is 0 is a withdrawal: it names a trainer
(name, id and gender) and removes that trainer's base from the receiving save.

Field offsets in a record:
  0 location id   1 flags (bit 4: gender; bits 0-3 register, 5 battled today,
  6-7 registry: bookkeeping)   2-8 trainer name (7 bytes, 0xFF terminated)
  9-12 trainer id   13 language   14-15 bases received   16 times entered   17 unused
  18-33 decorations (16)   34-49 decoration positions (16)   50-51 padding
  52 party: 6 x u32 personalities, 24 x u16 moves, 6 x u16 species, 6 x u16 items,
  6 x u8 levels, 6 x u8 EVs
These helpers only translate and check bytes.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct

EXTRAS_MAGIC = 0x31584D45  # "EMX1"
EXTRAS_ABI_VERSION = 1
EXTRAS_MAILBOX_SIZE = 384
BASE_BYTES = 160
LOCAL_SIZE = 168
INBOUND_SIZE = 176
FLAG_ENABLED = 1
NUM_SECRET_BASE_GROUPS = 24
MAX_DECORATION = 120
MAX_SPECIES = 1700
MAX_LEVEL = 100
NAME_OFFSET, NAME_LENGTH = 2, 7
ID_OFFSET, ID_LENGTH = 9, 4
NAME_TERMINATOR = 0xFF
GENDER_BIT = 0x10
_PARTY_SPECIES, _PARTY_LEVELS = 124, 148

_LOCAL_HEAD = struct.Struct("<IB3x")
_INBOUND_HEAD = struct.Struct("<IIIB3x")
assert _LOCAL_HEAD.size + BASE_BYTES == LOCAL_SIZE
assert _INBOUND_HEAD.size + BASE_BYTES == INBOUND_SIZE
_UINT32 = 0xFFFFFFFF


class ExtrasMailboxError(ValueError):
    pass


def capability_packet() -> bytes:
    return b"e" + struct.pack("<HHHH", EXTRAS_ABI_VERSION, EXTRAS_MAILBOX_SIZE, BASE_BYTES, 0)


def normalize_base(record: bytes) -> bytes:
    """The record as it is shared: the receiving save keeps its own registry
    bookkeeping, and the padding is cleared so equal bases compare equal."""
    if type(record) not in (bytes, bytearray) or len(record) != BASE_BYTES:
        raise ExtrasMailboxError("a secret base record is 160 bytes")
    out = bytearray(record)
    out[1] &= GENDER_BIT
    out[14:18] = bytes(4)
    out[50:52] = bytes(2)
    return bytes(out)


def _name_ok(record: bytes) -> bool:
    return record[NAME_OFFSET] not in (0, NAME_TERMINATOR)


def validate_base(record: bytes) -> bytes:
    """A shareable base: a real location, a named owner, known decorations and
    species. Returns the normalized record; raises ExtrasMailboxError."""
    record = normalize_base(record)
    base_id = record[0]
    if base_id == 0 or base_id // 10 >= NUM_SECRET_BASE_GROUPS or not 1 <= base_id % 10 <= 4:
        raise ExtrasMailboxError("secret base location does not exist")
    if not _name_ok(record):
        raise ExtrasMailboxError("secret base has no owner name")
    if any(value > MAX_DECORATION for value in record[18:34]):
        raise ExtrasMailboxError("secret base has an unknown decoration")
    for slot in range(6):
        species, = struct.unpack_from("<H", record, _PARTY_SPECIES + 2 * slot)
        if species > MAX_SPECIES or record[_PARTY_LEVELS + slot] > MAX_LEVEL:
            raise ExtrasMailboxError("secret base party is out of bounds")
    return record


def owner_key(record: bytes) -> bytes:
    """What identifies the base's owner in a save: gender, trainer id and name."""
    return bytes((record[1] & GENDER_BIT,)) + record[ID_OFFSET:ID_OFFSET + ID_LENGTH] + _name_bytes(record)


def _name_bytes(record: bytes) -> bytes:
    name = record[NAME_OFFSET:NAME_OFFSET + NAME_LENGTH]
    end = name.find(NAME_TERMINATOR)
    return name if end < 0 else name[:end]


def tombstone(record: bytes) -> bytes:
    """A withdrawal for the owner of `record` (location 0, owner kept)."""
    record = normalize_base(record)
    out = bytearray(BASE_BYTES)
    out[1] = record[1] & GENDER_BIT
    out[NAME_OFFSET:NAME_OFFSET + NAME_LENGTH] = record[NAME_OFFSET:NAME_OFFSET + NAME_LENGTH]
    out[ID_OFFSET:ID_OFFSET + ID_LENGTH] = record[ID_OFFSET:ID_OFFSET + ID_LENGTH]
    return bytes(out)


@dataclass(frozen=True)
class ExtrasLocal:
    base_seq: int
    has_base: bool
    base: bytes

    @classmethod
    def unpack(cls, payload: bytes) -> "ExtrasLocal":
        if type(payload) is not bytes or len(payload) != LOCAL_SIZE:
            raise ExtrasMailboxError("extras local record has the wrong size")
        seq, has = _LOCAL_HEAD.unpack_from(payload)
        if payload[5:8] != bytes(3) or has > 1:
            raise ExtrasMailboxError("extras local record has reserved bits set")
        base = payload[_LOCAL_HEAD.size:]
        if has == 0 and any(base):
            raise ExtrasMailboxError("a missing base carries data")
        return cls(seq, bool(has), base)


@dataclass(frozen=True)
class ExtrasInbound:
    enabled: bool = False
    base_ack: int = 0
    record_seq: int = 0
    source_slot: int = 0
    base: bytes = bytes(BASE_BYTES)

    def pack(self) -> bytes:
        if (type(self.base) is not bytes or len(self.base) != BASE_BYTES or not 0 <= self.source_slot < 4
                or not 0 <= self.base_ack <= _UINT32 or not 0 <= self.record_seq <= _UINT32):
            raise ExtrasMailboxError("invalid extras inbound record")
        return _INBOUND_HEAD.pack(FLAG_ENABLED if self.enabled else 0, self.base_ack, self.record_seq,
                                  self.source_slot) + self.base
