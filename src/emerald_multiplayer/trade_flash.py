"""Deterministic, byte-preserving party exchange for the ownership profile.

These functions construct new server transaction candidates. They never write
a local save or a running game. Consent, leases, ownership and durable commit
belong to the trade store/coordinator. Native trade effects are not authorized
by this primitive: only the two offered 100-byte party records may change.
"""
from __future__ import annotations

import struct

from .flash import (
    FlashError, FlashSnapshot, POKEMON_SIZE, SAVED_PARTY_OFFSET,
    SECTOR_SIZE, SECTIONS_PER_BANK, SECTION_LENGTHS, inspect_flash,
)
from .ownership import OWNERSHIP_PROFILE, SERIAL_MAX, inspect_ownership


class TradeFlashError(FlashError):
    """The offered saves cannot form the specified exact reciprocal exchange."""


def _serial(value: int) -> None:
    if type(value) is not int or not 1 <= value <= SERIAL_MAX:
        raise TradeFlashError("offered serial must be a nonzero 20-bit integer")


def _party_record(snapshot: FlashSnapshot, ownership, serial: int) -> tuple[int, bytes]:
    record = next((record for record in ownership.records if record.serial == serial), None)
    if record is None or not record.location.startswith("party:"):
        raise TradeFlashError("the offered instance must be in its owner's current party")
    index = int(record.location.split(":")[1])
    start = SAVED_PARTY_OFFSET + index * POKEMON_SIZE
    return start, snapshot.save_block1[start:start + POKEMON_SIZE]


def _replace_record(snapshot: FlashSnapshot, offset: int, mon: bytes) -> bytes:
    # The pinned six-member party lies entirely in logical section 1. Locate
    # its physical sector using the validated bank's section IDs, not rotation
    # assumptions or a fixed Flash address.
    if offset < SAVED_PARTY_OFFSET or offset + POKEMON_SIZE > SECTION_LENGTHS[1]:
        raise TradeFlashError("party record exceeds its pinned save section")
    first = snapshot.metadata.bank * SECTIONS_PER_BANK
    matches = [index * SECTOR_SIZE for index in range(first, first + SECTIONS_PER_BANK)
               if struct.unpack_from("<H", snapshot.flash, index * SECTOR_SIZE + 4084)[0] == 1]
    if len(matches) != 1:
        raise TradeFlashError("selected party section is missing or duplicated")
    sector = matches[0]
    result = bytearray(snapshot.container)
    result[sector + offset:sector + offset + POKEMON_SIZE] = mon
    # Native CalculateChecksum sums uint32 words, wrapping before one fold.
    data = result[sector:sector + SECTION_LENGTHS[1]]
    total = sum(struct.unpack(f"<{len(data) // 4}I", data)) & 0xFFFFFFFF
    struct.pack_into("<H", result, sector + 4086, (total + (total >> 16)) & 0xFFFF)
    return bytes(result)


def build_party_swap(payload_a: bytes, serial_a: int, payload_b: bytes,
                     serial_b: int) -> tuple[bytes, bytes]:
    """Return exact reciprocal party post-images without changing input bytes.

    Preserve each player's party count, other Pokémon, money, bag, mail array,
    story, playtime, location, ownership metadata, previous bank, special sectors
    and optional RTC footer. An integration layer must separately handle trade
    eligibility and native side effects (including mail references/evolution).
    """
    _serial(serial_a)
    _serial(serial_b)
    if serial_a == serial_b:
        raise TradeFlashError("a reciprocal exchange requires two different instances")
    try:
        a = inspect_flash(payload_a, save_profile=OWNERSHIP_PROFILE)
        b = inspect_flash(payload_b, save_profile=OWNERSHIP_PROFILE)
        owner_a, owner_b = inspect_ownership(a), inspect_ownership(b)
        if owner_a.world_id != owner_b.world_id:
            raise TradeFlashError("trading requires the same ownership world")
        if owner_a.player_id == owner_b.player_id:
            raise TradeFlashError("trading requires two different players")
        if {record.serial for record in owner_a.records} & {record.serial for record in owner_b.records}:
            raise TradeFlashError("the source inventories contain a shared instance")
        offset_a, mon_a = _party_record(a, owner_a, serial_a)
        offset_b, mon_b = _party_record(b, owner_b, serial_b)
        result_a = _replace_record(a, offset_a, mon_b)
        result_b = _replace_record(b, offset_b, mon_a)
        # This also rejects a recipient's retirement/allocation metadata that
        # conflicts with the incoming serial. Store validation supplies authority.
        inspect_flash(result_a, expected_trainer_id=a.metadata.trainer_id,
                      save_profile=OWNERSHIP_PROFILE)
        inspect_flash(result_b, expected_trainer_id=b.metadata.trainer_id,
                      save_profile=OWNERSHIP_PROFILE)
    except FlashError as error:
        if isinstance(error, TradeFlashError):
            raise
        raise TradeFlashError(str(error)) from error
    return result_a, result_b


def validate_party_swap(before_a: bytes, serial_a: int, before_b: bytes,
                        serial_b: int, after_a: bytes, after_b: bytes) -> None:
    """Reject every post-image mutation beyond the exact offered party swap."""
    if not isinstance(after_a, bytes) or not isinstance(after_b, bytes):
        raise TradeFlashError("trade post-images must be immutable bytes")
    expected_a, expected_b = build_party_swap(before_a, serial_a, before_b, serial_b)
    if after_a != expected_a or after_b != expected_b:
        raise TradeFlashError("trade post-images differ from the authorized reciprocal exchange")
