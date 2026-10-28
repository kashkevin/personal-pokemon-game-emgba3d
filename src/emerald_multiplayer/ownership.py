"""Read-only identity format for the pinned ownership-enabled Emerald profile.

The 20-bit serial is an instance handle within the record's world UUID. It is
not inferred from personality, original trainer, species, or a storage slot.
Allocation and owner transitions belong to the transactional server store.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import struct
import uuid
import zlib

from .flash import (
    BOX_CAPACITY, BOX_COUNT, BOX_POKEMON_SIZE, FUSION_CAPACITY, FUSIONS_OFFSET,
    FlashError, FlashSnapshot, LAYOUT_ID, OWNERSHIP_LAYOUT_ID,
    OWNERSHIP_SAVE_BLOCK_3_SIZE, PARTY_SIZE, POKEMON_SIZE, SAVED_PARTY_COUNT_OFFSET,
    SAVED_PARTY_OFFSET, SAVE_BLOCK_1_SIZE, STORAGE_SIZE, _RecentResults, _box_species, _inspect_party,
)

OWNERSHIP_PROFILE = OWNERSHIP_LAYOUT_ID
SERIAL_LIMIT = 0x100000
SERIAL_MAX = SERIAL_LIMIT - 1
RETIRE_CAPACITY = 128
RETIRE_RELEASE = 1
RETIRE_NPC_EXCHANGE = 2
# Pinned Emerald ELF/source: offsetof(SaveBlock1, daycare) = 0x3030;
# sizeof(DaycareMon) = BoxPokemon80 + DaycareMail56 + steps4 = 140.
DAYCARE_OFFSET = 0x3030
DAYCARE_MON_SIZE = 140
DAYCARE_CAPACITY = 2
OWNED_SLOT_COUNT = PARTY_SIZE + BOX_COUNT * BOX_CAPACITY + DAYCARE_CAPACITY + FUSION_CAPACITY

# Logical substructure -> physical index, independently checked against d18.
_SUBSTRUCT_OFFSETS = (
    (0, 0, 0, 0, 0, 0, 1, 1, 2, 3, 2, 3, 1, 1, 2, 3, 2, 3, 1, 1, 2, 3, 2, 3),
    (1, 1, 2, 3, 2, 3, 0, 0, 0, 0, 0, 0, 2, 3, 1, 1, 3, 2, 2, 3, 1, 1, 3, 2),
    (2, 3, 1, 1, 3, 2, 2, 3, 1, 1, 3, 2, 0, 0, 0, 0, 0, 0, 3, 2, 3, 2, 1, 1),
    (3, 2, 3, 2, 1, 1, 3, 2, 3, 2, 1, 1, 3, 2, 3, 2, 1, 1, 0, 0, 0, 0, 0, 0),
)
# logical substruct, byte offset, packed word width, bit shift, field width
_UID_FIELDS = ((0, 2, 2, 10, 6), (0, 4, 4, 29, 3), (0, 10, 2, 14, 2),
               (1, 4, 2, 11, 5), (1, 6, 2, 11, 3), (3, 8, 4, 28, 1))


class OwnershipError(FlashError):
    """An ownership record or owned Pokémon is not valid for this profile."""


@dataclass(frozen=True)
class Retirement:
    serial: int
    reason: int


@dataclass(frozen=True)
class OwnershipRecord:
    serial: int
    location: str
    personality: int
    ot_id: int
    species: int
    content_sha256: str


@dataclass(frozen=True)
class OwnershipSnapshot:
    world_id: str
    player_id: str
    grant_id: str
    start: int
    end_exclusive: int
    next_serial: int
    lease_epoch: int
    incarnation: int
    retirements: tuple[Retirement, ...]
    records: tuple[OwnershipRecord, ...]
    manifest_sha256: str


@dataclass(frozen=True)
class _Metadata:
    world_id: str
    player_id: str
    grant_id: str
    start: int
    end_exclusive: int
    next_serial: int
    lease_epoch: int
    incarnation: int
    retirements: tuple[Retirement, ...]


def _uuid_field(raw: bytes, name: str) -> str:
    # Native ABI treats UUIDs as opaque bytes, including their byte order.
    if len(raw) != 16 or not any(raw):
        raise OwnershipError(f"ownership {name} must be a nonzero 16-byte UUID")
    return str(uuid.UUID(bytes=raw))


def _parse_metadata(data: bytes) -> _Metadata:
    if not isinstance(data, bytes) or len(data) != OWNERSHIP_SAVE_BLOCK_3_SIZE:
        raise OwnershipError("selected save is missing its 600-byte ownership record")
    if data[4:8] != b"EMO1":
        raise OwnershipError("ownership record magic is invalid")
    version, record_size = struct.unpack_from("<HH", data, 8)
    if version != 1 or record_size != 596:
        raise OwnershipError("ownership record version or size is unknown")
    if zlib.crc32(data[:596]) != struct.unpack_from("<I", data, 596)[0]:
        raise OwnershipError("ownership record CRC32 mismatch")
    world_id = _uuid_field(data[12:28], "world")
    player_id = _uuid_field(data[28:44], "player")
    grant_id = _uuid_field(data[44:60], "grant")
    start, end, next_serial, lease, incarnation = struct.unpack_from("<IIIII", data, 60)
    if not 1 <= start < end <= SERIAL_LIMIT or not start <= next_serial <= end:
        raise OwnershipError("ownership allocation range or next serial is invalid")
    if not lease or not incarnation:
        raise OwnershipError("ownership lease epoch and incarnation must be nonzero")
    count, reserved = struct.unpack_from("<HH", data, 80)
    if count > RETIRE_CAPACITY or reserved:
        raise OwnershipError("ownership retirement count or reserved field is invalid")
    retirements = []
    seen = set()
    for index in range(RETIRE_CAPACITY):
        value = struct.unpack_from("<I", data, 84 + index * 4)[0]
        if index >= count:
            if value:
                raise OwnershipError("ownership unused retirement entries must be zero")
            continue
        serial, reason = value & SERIAL_MAX, (value >> 20) & 0xF
        if value >> 24 or not serial or reason not in (RETIRE_RELEASE, RETIRE_NPC_EXCHANGE):
            raise OwnershipError("ownership retirement serial or reason is invalid")
        if serial in seen:
            raise OwnershipError("ownership retirement journal contains a duplicate serial")
        if start <= serial < end and serial >= next_serial:
            raise OwnershipError("ownership retirement uses an unconsumed allocation serial")
        seen.add(serial)
        retirements.append(Retirement(serial, reason))
    return _Metadata(world_id, player_id, grant_id, start, end, next_serial,
                     lease, incarnation, tuple(retirements))


def _decode_box(box: bytes, location: str) -> tuple[int, int, int, int, str]:
    species = _box_species(box, location)  # Decrypts and checks a copy only.
    personality, ot_id = struct.unpack_from("<II", box)
    words = tuple(value ^ personality ^ ot_id for value in struct.unpack_from("<12I", box, 32))
    physical = struct.pack("<12I", *words)
    logical = bytearray().join(physical[index * 12:index * 12 + 12]
                              for index in (row[personality % 24] for row in _SUBSTRUCT_OFFSETS))
    serial, serial_shift = 0, 0
    for substruct, offset, word_size, shift, width in _UID_FIELDS:
        offset += substruct * 12
        value = int.from_bytes(logical[offset:offset + word_size], "little")
        mask = ((1 << width) - 1) << shift
        serial |= ((value & mask) >> shift) << serial_shift
        serial_shift += width
        logical[offset:offset + word_size] = (value & ~mask).to_bytes(word_size, "little")
    if box[19] & 0x80 or box[31] & 0x80:
        raise OwnershipError(f"{location} has unknown reserved header bits")
    # Native ZeroMonData clears Box80, then HP before maxHP. The HP setter
    # can leave the previous maxHP in the 14-bit hpLost header field. Empty
    # slots may retain only that residue; identity, checksum and all other
    # header/secure bytes must still be zero. Preserve the uploaded bytes.
    if not species and (serial or any(box[:30]) or box[31] & 0xC0 or any(box[32:])):
        raise OwnershipError(f"{location} is not a canonical empty Pokémon slot")
    # Identity assignment changes the checksum; exclude both it and UID bits.
    header = box[:28] + b"\0\0" + box[30:32]
    content = hashlib.sha256(b"EMO-MON-CONTENT\0" + header + logical).hexdigest()
    return serial, personality, ot_id, species, content


def _inspect_inventory(block1: bytes, storage: bytes, *, require_ids: bool,
                       allow_unassigned: bool = False) -> tuple[OwnershipRecord, ...]:
    if len(block1) != SAVE_BLOCK_1_SIZE or len(storage) != STORAGE_SIZE:
        raise OwnershipError("owned inventory does not match its pinned block sizes")
    count = block1[SAVED_PARTY_COUNT_OFFSET]
    if count > PARTY_SIZE:
        raise OwnershipError("party count exceeds six")
    slots = []
    for index in range(PARTY_SIZE):
        start = SAVED_PARTY_OFFSET + index * POKEMON_SIZE
        mon = block1[start:start + POKEMON_SIZE]
        if _inspect_party(mon, f"party:{index}") != (index < count):
            raise OwnershipError("party occupancy does not match its saved count")
        slots.append((f"party:{index}", mon[:BOX_POKEMON_SIZE]))
    for box in range(BOX_COUNT):
        for index in range(BOX_CAPACITY):
            start = 4 + (box * BOX_CAPACITY + index) * BOX_POKEMON_SIZE
            slots.append((f"box:{box}:{index}", storage[start:start + BOX_POKEMON_SIZE]))
    for index in range(DAYCARE_CAPACITY):
        start = DAYCARE_OFFSET + index * DAYCARE_MON_SIZE
        slots.append((f"daycare:{index}", block1[start:start + BOX_POKEMON_SIZE]))
    for index in range(FUSION_CAPACITY):
        start = FUSIONS_OFFSET + index * POKEMON_SIZE
        mon = storage[start:start + POKEMON_SIZE]
        _inspect_party(mon, f"fusion:{index}")
        slots.append((f"fusion:{index}", mon[:BOX_POKEMON_SIZE]))
    records, seen = [], set()
    for location, box in slots:
        serial, personality, ot_id, species, content = _decode_box(box, location)
        if not species:
            continue
        if require_ids:
            if not serial and not allow_unassigned:
                raise OwnershipError(f"{location} is missing its instance serial")
            if serial and serial in seen:
                raise OwnershipError("owned inventory contains duplicate instance serials")
            if serial:
                seen.add(serial)
        elif serial:
            raise OwnershipError("legacy source contains nonzero identity fields; explicit migration policy is required")
        records.append(OwnershipRecord(serial, location, personality, ot_id, species, content))
    return tuple(records)


# KNOWN_ISSUES MS-161: a world's integrity check reads each save's owned inventory up to three times (its newer bank, its
# older bank, which is usually the last save's newer one, and inspect_ownership the newer one again). The answer depends
# only on these bytes and is immutable, so the most recent answers are kept, by content. A strict answer (every Pokemon
# with its serial) also answers a request that would allow unassigned ones: it is the same snapshot.
_recent_components = _RecentResults(32)


def _inspect_components(block3: bytes, block1: bytes, storage: bytes, *,
                        allow_unassigned_inventory: bool = False) -> OwnershipSnapshot:
    if not (type(block3) is bytes and type(block1) is bytes and type(storage) is bytes):
        return _inspect_components_now(block3, block1, storage, allow_unassigned_inventory=allow_unassigned_inventory)
    strict = _recent_components.get((block3, block1, storage, False))
    if strict is not None:
        return strict
    key = (block3, block1, storage, allow_unassigned_inventory)
    return _recent_components.get(key) or _recent_components.put(
        key, _inspect_components_now(block3, block1, storage, allow_unassigned_inventory=allow_unassigned_inventory))


def _inspect_components_now(block3: bytes, block1: bytes, storage: bytes, *,
                            allow_unassigned_inventory: bool = False) -> OwnershipSnapshot:
    metadata = _parse_metadata(block3)
    records = _inspect_inventory(block1, storage, require_ids=True,
                                 allow_unassigned=allow_unassigned_inventory)
    retired = {entry.serial for entry in metadata.retirements}
    for record in records:
        if record.serial in retired:
            raise OwnershipError("a retired instance is still present in owned inventory")
        if metadata.start <= record.serial < metadata.end_exclusive and record.serial >= metadata.next_serial:
            raise OwnershipError("owned inventory uses an unconsumed allocation serial")
    manifest = json.dumps(
        {"world_id": metadata.world_id, "player_id": metadata.player_id,
         "records": [[record.serial, record.location, record.personality, record.ot_id,
                      record.species, record.content_sha256] for record in records]},
        sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return OwnershipSnapshot(metadata.world_id, metadata.player_id, metadata.grant_id,
                             metadata.start, metadata.end_exclusive, metadata.next_serial,
                             metadata.lease_epoch, metadata.incarnation, metadata.retirements,
                             records, hashlib.sha256(b"EMO-MANIFEST\0" + manifest).hexdigest())


def inspect_ownership(snapshot: FlashSnapshot) -> OwnershipSnapshot:
    """Validate selected ownership metadata and every retained owned location."""
    if not isinstance(snapshot, FlashSnapshot) or snapshot.save_profile != OWNERSHIP_PROFILE:
        raise OwnershipError("ownership inspection requires the explicit ownership save profile")
    try:
        return _inspect_components(snapshot.save_block3, snapshot.save_block1, snapshot.storage)
    except FlashError as error:
        if isinstance(error, OwnershipError):
            raise
        raise OwnershipError(str(error)) from error


def extract_source_inventory(snapshot: FlashSnapshot) -> tuple[OwnershipRecord, ...]:
    """Enumerate an explicit legacy migration source without assigning any IDs.

    Unknown nonzero reserved identity fields are rejected rather than adopted.
    ``content_sha256`` hashes Box data in logical substructure order with only
    its checksum and new serial fields removed; party-only stats remain in the
    enclosing Flash checkpoint hash.
    """
    if not isinstance(snapshot, FlashSnapshot) or snapshot.save_profile != LAYOUT_ID or len(snapshot.save_block3) != 4:
        raise OwnershipError("migration source requires the explicit legacy save profile")
    try:
        return _inspect_inventory(snapshot.save_block1, snapshot.storage, require_ids=False)
    except FlashError as error:
        if isinstance(error, OwnershipError):
            raise
        raise OwnershipError(str(error)) from error
