"""Moving a character's save from one world to another.

A character is the player's own trainer: one save, its Pokémon, items, badges and progress. In a world (a Solo world on this
PC or a friend's server) the server gives each Pokémon an identity of that world (a serial in spare bits of the Pokémon's
data, ``ownership._UID_FIELDS``) and the game writes the world's ownership profile into SaveBlock3. Those identities mean
nothing in another world. Before the character enters a different world, ``detach_from_world`` turns its save back into an
ordinary save with no world identities (the "legacy" profile the server accepts as a source, ``ownership_storage``):

* every Pokémon's identity bits are cleared and its checksum recomputed (party, PC boxes, Day Care, fusion slots), so each
  Pokémon keeps exactly its content (``content_sha256`` excludes only the identity bits and the checksum);
* the 600-byte ownership profile is zeroed; the Day Care egg queue after it is kept byte for byte;
* the newest complete save bank is kept, the older bank is erased (a valid save with one bank, as after a first save);
* two pieces of multiplayer state that belong to the old world are reset: a World Event catch still waiting for the old host's
  verdict (five vars; the Pokémon stays with the character) and the reward wallet sequence (three vars), which is set to the
  sequence the destination world last saw this account apply (``wallet_seq``), so the destination neither repeats nor skips
  a reward or a wager payment;
* nothing else changes: trainer, party stats, items, flags, position, Hall of Fame sectors and the clock footer.

The result is checked before it is returned: it must parse as a legacy save, keep the same trainer, the same Pokémon in the
same places with the same content, and the same egg queue. Any surprise raises ``TransferError`` and nothing is written.
"""
from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass

from .flash import (
    BOX_CAPACITY, BOX_COUNT, BOX_POKEMON_SIZE, EGG_QUEUE_OFFSET, FLASH_SIZE, FUSION_CAPACITY, FUSIONS_OFFSET, FlashError,
    LAYOUT_ID, OWNERSHIP_LAYOUT_ID, OWNERSHIP_SAVE_BLOCK_3_SIZE, PARTY_SIZE, POKEMON_SIZE, SAVE_BLOCK_3_CHUNK_SIZE,
    SAVE_BLOCK_3_FULL_SIZE, SAVE_BLOCK_3_SIZE, SAVED_PARTY_OFFSET, SECTION_LENGTHS, SECTOR_DATA_SIZE, SECTOR_SIZE, _checksum,
    inspect_flash,
)
from .ownership import _SUBSTRUCT_OFFSETS, _UID_FIELDS, DAYCARE_CAPACITY, DAYCARE_OFFSET, DAYCARE_MON_SIZE, \
    extract_source_inventory, inspect_ownership

_FOOTER = struct.Struct("<HHII")
VARS_OFFSET = 0x139C                       # SaveBlock1.vars (engine include/global.h)
CATCH_VARS = (0x409D, 0x40A1, 0x40A8, 0x40B8, 0x40BB)   # VAR_MP_CATCH_EVENT_LO/HI, SPECIES, PID_LO/HI (include/constants/vars.h)
WALLET_SEQ, WALLET_AMOUNT_LO, WALLET_AMOUNT_HI = 0x40FE, 0x40FF, 0x40E5


def _var_offset(var):
    return VARS_OFFSET + 2 * (var - 0x4000)


def _world_vars(block1: bytearray, wallet_seq: int) -> None:
    for var in CATCH_VARS + (WALLET_AMOUNT_LO, WALLET_AMOUNT_HI):
        struct.pack_into("<H", block1, _var_offset(var), 0)
    struct.pack_into("<H", block1, _var_offset(WALLET_SEQ), wallet_seq & 0xFFFF)


def world_vars(payload: bytes) -> dict:
    """The world-scoped vars of a save (for tests and diagnostics)."""
    for profile in (LAYOUT_ID, OWNERSHIP_LAYOUT_ID):
        try:
            block1 = inspect_flash(payload, save_profile=profile).save_block1
            break
        except FlashError:
            continue
    else:
        raise TransferError("unreadable_save", "the save could not be read")
    read = lambda var: struct.unpack_from("<H", block1, _var_offset(var))[0]                 # noqa: E731
    return dict(catch=tuple(read(v) for v in CATCH_VARS), wallet_seq=read(WALLET_SEQ),
                wallet_amount=(read(WALLET_AMOUNT_LO), read(WALLET_AMOUNT_HI)))
_ERASED = b"\xff" * SECTOR_SIZE


class TransferError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class DetachedSave:
    payload: bytes
    sha256: str
    trainer_id: int
    trainer_name: bytes
    pokemon: int                       # Pokémon carried (party, PC, Day Care, fusions)
    source_world_id: str | None        # the world the save came from (None: it had no world)


def _clear_identity(box: bytes) -> bytes:
    """The same boxed Pokémon without its world identity bits; checksum recomputed, content untouched."""
    personality, ot_id = struct.unpack_from("<II", box)
    key = personality ^ ot_id
    words = [value ^ key for value in struct.unpack_from("<12I", box, 32)]
    physical = bytearray(struct.pack("<12I", *words))
    order = personality % 24
    positions = [row[order] for row in _SUBSTRUCT_OFFSETS]            # logical substruct k lives at physical positions[k]
    logical = [bytearray(physical[p * 12:p * 12 + 12]) for p in positions]
    for substruct, offset, word_size, shift, width in _UID_FIELDS:
        value = int.from_bytes(logical[substruct][offset:offset + word_size], "little")
        value &= ~(((1 << width) - 1) << shift)
        logical[substruct][offset:offset + word_size] = value.to_bytes(word_size, "little")
    for k, p in enumerate(positions):
        physical[p * 12:p * 12 + 12] = logical[k]
    plain = struct.unpack("<12I", physical)
    checksum = sum((value & 0xFFFF) + (value >> 16) for value in plain) & 0xFFFF
    out = bytearray(box)
    struct.pack_into("<H", out, 28, checksum)
    struct.pack_into("<12I", out, 32, *(value ^ key for value in plain))
    return bytes(out)


def _slot_has_species(box: bytes) -> bool:
    return bool(box[19] & 2)


def _strip_region(data: bytearray, start: int, count: int, stride: int) -> None:
    for index in range(count):
        offset = start + index * stride
        box = bytes(data[offset:offset + BOX_POKEMON_SIZE])
        if _slot_has_species(box) or any(box[32:]):
            data[offset:offset + BOX_POKEMON_SIZE] = _clear_identity(box)


def _latest_bank(flash: bytes, bank_index: int):
    sectors = [flash[(bank_index * 14 + i) * SECTOR_SIZE:(bank_index * 14 + i + 1) * SECTOR_SIZE] for i in range(14)]
    by_section = {}
    for physical, sector in enumerate(sectors):
        section_id, _, _, counter = _FOOTER.unpack_from(sector, 4084)
        by_section[section_id] = (physical, sector, counter)
    if sorted(by_section) != list(range(14)):
        raise TransferError("unexpected_save", "the newest save bank is incomplete")
    return by_section


def detach_from_world(payload: bytes, *, wallet_seq: int = 0) -> DetachedSave:
    """An ordinary (legacy) copy of a save, ready to enter a world whose reward wallet last saw ``wallet_seq`` applied for
    this account (0 for an account that never played there). ``payload`` may be a world save or already legacy (a new
    character, or a save detached earlier); either way only identities and world-scoped vars change."""
    if not isinstance(payload, (bytes, bytearray)):
        raise TransferError("unexpected_save", "a save is bytes")
    if type(wallet_seq) is not int or not 0 <= wallet_seq <= 0xFFFF:
        raise TransferError("unexpected_save", "the wallet sequence is out of range")
    payload = bytes(payload)
    identity = None
    try:
        snapshot = inspect_flash(payload, save_profile=LAYOUT_ID)
        records = extract_source_inventory(snapshot)
    except FlashError:
        snapshot = None
    if snapshot is None:
        try:
            snapshot = inspect_flash(payload, save_profile=OWNERSHIP_LAYOUT_ID)
            identity = inspect_ownership(snapshot)
        except FlashError as error:
            raise TransferError("unreadable_save", f"the save could not be read: {error}") from None
        records = identity.records
    flash, footer = payload[:FLASH_SIZE], payload[FLASH_SIZE:]
    bank_index = snapshot.metadata.bank
    sections = _latest_bank(flash, bank_index)
    data = {sid: bytearray(sector[:SECTION_LENGTHS[sid]]) for sid, (_, sector, _) in sections.items()}
    block1 = bytearray(b"".join(data[i] for i in range(1, 5)))
    storage = bytearray(b"".join(data[i] for i in range(5, 14)))
    full3 = bytearray(b"".join(sections[i][1][SECTOR_DATA_SIZE:SECTOR_DATA_SIZE + SAVE_BLOCK_3_CHUNK_SIZE] for i in range(14)))
    if block1 != snapshot.save_block1 or storage != snapshot.storage:
        raise TransferError("unexpected_save", "the newest save bank does not match the parsed save")
    if identity is not None:
        _strip_region(block1, SAVED_PARTY_OFFSET, PARTY_SIZE, POKEMON_SIZE)
        _strip_region(block1, DAYCARE_OFFSET, DAYCARE_CAPACITY, DAYCARE_MON_SIZE)
        _strip_region(storage, 4, BOX_COUNT * BOX_CAPACITY, BOX_POKEMON_SIZE)
        _strip_region(storage, FUSIONS_OFFSET, FUSION_CAPACITY, POKEMON_SIZE)
        full3[SAVE_BLOCK_3_SIZE:OWNERSHIP_SAVE_BLOCK_3_SIZE] = bytes(OWNERSHIP_SAVE_BLOCK_3_SIZE - SAVE_BLOCK_3_SIZE)
    _world_vars(block1, wallet_seq)
    other = 1 - bank_index
    other_erased = flash[other * 14 * SECTOR_SIZE:(other + 1) * 14 * SECTOR_SIZE] == _ERASED * 14
    if identity is None and block1 == snapshot.save_block1 and other_erased:
        return DetachedSave(payload, hashlib.sha256(payload).hexdigest(), snapshot.metadata.trainer_id, snapshot.metadata.name,
                            len(records), None)
    # Write the sections back in place (same physical sectors, same counter and rotation), checksums recomputed.
    new_data = {0: data[0]}
    offset = 0
    for sid in range(1, 5):
        size = SECTION_LENGTHS[sid]
        new_data[sid] = block1[offset:offset + size]
        offset += size
    offset = 0
    for sid in range(5, 14):
        size = SECTION_LENGTHS[sid]
        new_data[sid] = storage[offset:offset + size]
        offset += size
    out = bytearray(flash)
    for sid, (physical, sector, counter) in sections.items():
        rebuilt = bytearray(sector)
        size = SECTION_LENGTHS[sid]
        rebuilt[:size] = new_data[sid]
        rebuilt[SECTOR_DATA_SIZE:SECTOR_DATA_SIZE + SAVE_BLOCK_3_CHUNK_SIZE] = \
            full3[sid * SAVE_BLOCK_3_CHUNK_SIZE:(sid + 1) * SAVE_BLOCK_3_CHUNK_SIZE]
        section_id, _, signature, counter = _FOOTER.unpack_from(sector, 4084)
        _FOOTER.pack_into(rebuilt, 4084, section_id, _checksum(bytes(rebuilt[:size])), signature, counter)
        start = (bank_index * 14 + physical) * SECTOR_SIZE
        out[start:start + SECTOR_SIZE] = rebuilt
    out[other * 14 * SECTOR_SIZE:(other + 1) * 14 * SECTOR_SIZE] = _ERASED * 14
    result = bytes(out) + footer
    _verify(snapshot, records, result, wallet_seq)
    return DetachedSave(result, hashlib.sha256(result).hexdigest(), snapshot.metadata.trainer_id, snapshot.metadata.name,
                        len(records), identity.world_id if identity is not None else None)


def _verify(owned, owned_records, result, wallet_seq):
    """The detached save is the same character: same trainer, same Pokémon in the same places with the same content; only
    the world-scoped vars differ, and they hold what was asked."""
    try:
        snapshot = inspect_flash(result, save_profile=LAYOUT_ID)
        records = extract_source_inventory(snapshot)
    except FlashError as error:
        raise TransferError("detach_failed", f"the converted save did not verify: {error}") from None
    before = owned.metadata
    after = snapshot.metadata
    same = ("trainer_id", "name", "gender", "party_count", "current_box", "map_group", "map_number", "x", "y",
            "map_layout_id", "stored_pokemon_count", "fusion_count")
    if any(getattr(before, field) != getattr(after, field) for field in same):
        raise TransferError("detach_failed", "the converted save changed the trainer")
    expected = sorted((r.location, r.personality, r.ot_id, r.species, r.content_sha256) for r in owned_records)
    actual = sorted((r.location, r.personality, r.ot_id, r.species, r.content_sha256) for r in records)
    if expected != actual:
        raise TransferError("detach_failed", "the converted save changed a Pokémon")
    if snapshot.save_block2 != owned.save_block2:
        raise TransferError("detach_failed", "the converted save changed the trainer data")
    if owned.save_block3[:SAVE_BLOCK_3_SIZE] != snapshot.save_block3[:SAVE_BLOCK_3_SIZE]:
        raise TransferError("detach_failed", "the converted save changed SaveBlock3")
    old_flash, new_flash = owned.flash, snapshot.flash
    if old_flash[28 * SECTOR_SIZE:] != new_flash[28 * SECTOR_SIZE:]:
        raise TransferError("detach_failed", "the converted save changed the Hall of Fame or special sectors")
    if _egg_queue(owned.flash, owned.metadata.bank) != _egg_queue(new_flash, after.bank):
        raise TransferError("detach_failed", "the converted save changed the Day Care eggs")
    # Outside the Pokémon slots and the world vars, SaveBlock1 and the PC storage are byte for byte the same.
    old1, new1 = bytearray(owned.save_block1), bytearray(snapshot.save_block1)
    for buffer in (old1, new1):
        _world_vars(buffer, 0)
        for start, count, stride in ((SAVED_PARTY_OFFSET, PARTY_SIZE, POKEMON_SIZE), (DAYCARE_OFFSET, DAYCARE_CAPACITY, DAYCARE_MON_SIZE)):
            for index in range(count):
                offset = start + index * stride
                buffer[offset:offset + BOX_POKEMON_SIZE] = bytes(BOX_POKEMON_SIZE)
    if old1 != new1:
        raise TransferError("detach_failed", "the converted save changed the trainer's progress")
    old_storage, new_storage = bytearray(owned.storage), bytearray(snapshot.storage)
    for buffer in (old_storage, new_storage):
        for start, count, stride in ((4, BOX_COUNT * BOX_CAPACITY, BOX_POKEMON_SIZE), (FUSIONS_OFFSET, FUSION_CAPACITY, POKEMON_SIZE)):
            for index in range(count):
                offset = start + index * stride
                buffer[offset:offset + BOX_POKEMON_SIZE] = bytes(BOX_POKEMON_SIZE)
    if old_storage != new_storage:
        raise TransferError("detach_failed", "the converted save changed the PC")
    vars_after = struct.unpack_from("<H", snapshot.save_block1, _var_offset(WALLET_SEQ))[0]
    if vars_after != wallet_seq:
        raise TransferError("detach_failed", "the converted save has the wrong wallet sequence")


def _egg_queue(flash, bank):
    sections = _latest_bank(flash, bank)
    full = b"".join(sections[i][1][SECTOR_DATA_SIZE:SECTOR_DATA_SIZE + SAVE_BLOCK_3_CHUNK_SIZE] for i in range(14))
    return full[EGG_QUEUE_OFFSET:SAVE_BLOCK_3_FULL_SIZE]


__all__ = ["DetachedSave", "TransferError", "detach_from_world", "world_vars"]
