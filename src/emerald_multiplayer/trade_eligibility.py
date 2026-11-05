"""Eligibility for the pinned, exact-record exchange.

This gate does not implement native trade effects. It checks immutable owned
checkpoints before offers/consent. The caller still authenticates actors, fences
leases/heads, and commits both sides.

Eggs and Pokemon holding Mail (owner decision 39, KNOWN_ISSUES "Trades: eggs and
Mail", option (b)) are offered only where the caller allows them (``eggs``,
``mail``): Mail in every exact exchange (TradeDesk.trade_mail: the trade's save
import already carries the Mail array), Eggs only where the world's game hatches
a traded Egg correctly (TradeDesk.trade_eggs, from the host game's manifest
trade_egg_abi_version). An Egg moves as the record it is; Mail moves with its
Pokemon (trade_mail.py).
"""
from __future__ import annotations

from dataclasses import dataclass
import struct

from .flash import FlashError, POKEMON_SIZE, SAVED_PARTY_OFFSET, inspect_flash
from .ownership import (
    OWNERSHIP_PROFILE, SERIAL_MAX, _SUBSTRUCT_OFFSETS, inspect_ownership,
)
from .trade_forms import tradable_species
from .trade_mail import MAIL_ITEMS, MAIL_NONE, TradeMailError, party_mail, receiving_slot

AUDITED_ENGINE_COMMIT = "b2cdd466abb8b142c3b75384133b5e6b3c3b982c"
CAPABILITY_ID = "simple-owned-party-exchange-v1"
# The exchange with Eggs and Mail: its recipient preparations name it (trade_preparation.py); a launcher from before it
# refuses such a preparation before acknowledging anything, so nothing moves.
EGGS_MAIL_CAPABILITY_ID = "owned-party-exchange-eggs-mail-v1"

# Exact internal IDs from the audited include/constants/species.h and all
# species_info/* EVO_TRADE entries. Since KNOWN_ISSUES MS-151 (2026-10-29) they
# are traded like any other: the exchange stays exact, and the receiving game
# evolves its new Pokemon itself once the trade's save is loaded (the engine's
# mp_trade_evolution.c: item/partner conditions and the Everstone as a link
# trade has them), an ordinary evolution its next checkpoint carries. The forms
# here (968, 1157-1159) stay outside the standard range below.
TRADE_EVOLUTION_SPECIES = frozenset((
    61,    # Poliwhirl
    64,    # Kadabra
    67,    # Machoke
    75,    # Graveler
    79,    # Slowpoke
    93,    # Haunter
    95,    # Onix
    112,   # Rhydon
    117,   # Seadra
    123,   # Scyther
    125,   # Electabuzz
    126,   # Magmar
    137,   # Porygon
    233,   # Porygon2
    349,   # Feebas
    356,   # Dusclops
    366,   # Clamperl
    525,   # Boldore
    533,   # Gurdurr
    588,   # Karrablast
    616,   # Shelmet
    682,   # Spritzee
    684,   # Swirlix
    708,   # Phantump
    710,   # Pumpkaboo (average)
    968,   # Alolan Graveler
    1157,  # Pumpkaboo (small)
    1158,  # Pumpkaboo (large)
    1159,  # Pumpkaboo (super)
))


class TradeEligibilityError(FlashError):
    """A checkpoint cannot use the temporary simple-exchange capability."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class EligibleTradeMon:
    """Observed checkpoint fields, not proof of consent or current ownership.

    ``friendship`` is the native byte: an Egg's remaining egg cycles. ``mail`` is the whole 36-byte Mail the Pokemon
    holds (None without one)."""

    world_id: str
    player_id: str
    checkpoint_sha256: str
    serial: int
    slot: int
    species: int
    personality: int
    ot_id: int
    held_item: int
    friendship: int
    egg: bool = False
    mail: bytes | None = None

    @property
    def needs_eggs_and_mail(self) -> bool:
        """Only the Egg-and-Mail exchange may carry it: an Egg, a Pokemon holding Mail, or one holding a Mail item."""
        return self.egg or self.mail is not None or self.held_item in MAIL_ITEMS


def _inspect_offer(payload: bytes, serial: int, *, eggs: bool = False, mail: bool = False):
    if type(eggs) is not bool or type(mail) is not bool:
        raise TradeEligibilityError("invalid_capability", "Egg and Mail allowances must be explicit booleans")
    if type(serial) is not int or not 1 <= serial <= SERIAL_MAX:
        raise TradeEligibilityError("invalid_serial", "offered serial must be a nonzero 20-bit integer")
    try:
        snapshot = inspect_flash(payload, save_profile=OWNERSHIP_PROFILE)
        owned = inspect_ownership(snapshot)
    except FlashError as error:
        raise TradeEligibilityError("invalid_checkpoint", "offered checkpoint is not a valid owned save") from error
    record = next((record for record in owned.records if record.serial == serial), None)
    if record is None or not record.location.startswith("party:"):
        raise TradeEligibilityError("party_required", "offer an instance in the current owned party")
    slot = int(record.location.split(":")[1])
    offset = SAVED_PARTY_OFFSET + slot * POKEMON_SIZE
    mon = snapshot.save_block1[offset:offset + POKEMON_SIZE]

    # The shared strict parser has already checked checksum, occupancy, UID,
    # all retained containers, and party bounds. Decrypt a copy to read the
    # growth/misc fields; XOR and permutation never alter uploaded bytes.
    key = record.personality ^ record.ot_id
    physical = struct.pack("<12I", *(word ^ key for word in struct.unpack_from("<12I", mon, 32)))
    growth_index = _SUBSTRUCT_OFFSETS[0][record.personality % 24]
    misc_index = _SUBSTRUCT_OFFSETS[3][record.personality % 24]
    growth = physical[growth_index * 12:growth_index * 12 + 12]
    misc = physical[misc_index * 12:misc_index * 12 + 12]
    egg = bool(mon[19] & 4 or struct.unpack_from("<I", misc, 4)[0] & (1 << 30))
    if egg and not eggs:
        raise TradeEligibilityError("egg_unsupported", "this world's game does not trade Eggs")
    held_item = struct.unpack_from("<H", growth, 2)[0] & 0x3FF
    carried = None
    if not mail:
        if mon[85] != MAIL_NONE or held_item in MAIL_ITEMS:
            raise TradeEligibilityError("mail_unsupported", "this world's game does not trade Mail")
    else:
        try:
            carried = party_mail(snapshot.save_block1, slot)
        except TradeMailError as error:
            raise TradeEligibilityError(error.code, str(error)) from error
        if egg and carried is not None:
            raise TradeEligibilityError("mail_invalid", "an Egg cannot hold Mail")
    # The pinned enum explicitly numbers the standard species 1..721. Its
    # alternate/form namespace is not a National Dex number; no unreviewed form
    # or later-generation record is enabled by this first capability. Every
    # native cannotBeTraded entry also lies outside this conservative range.
    # The forms reviewed one by one (trade_forms.py: Rotom's appliance forms,
    # 2026-10-30) are exchanged exactly like the standard species.
    if not tradable_species(record.species):
        raise TradeEligibilityError("species_unsupported", "this species or form is outside the audited exchange capability")
    return EligibleTradeMon(owned.world_id, owned.player_id, snapshot.container_sha256,
        serial, slot, record.species, record.personality, record.ot_id, held_item, growth[9],
        egg, carried), owned, snapshot


def validate_party_offer(payload: bytes, serial: int, *, eggs: bool = False, mail: bool = False) -> EligibleTradeMon:
    """Accept owned party offers of the standard range or a reviewed form (trade_forms.py); an Egg only with ``eggs``, a
    Pokemon holding Mail (or a Mail item) only with ``mail`` and only when its Mail is valid (trade_mail.party_mail).

    Ordinary friendship, IVs, shiny/PID/OT, moves and other data are preserved.
    Passing this gate does not apply native friendship/Pokédex/ribbon effects.
    """
    return _inspect_offer(payload, serial, eggs=eggs, mail=mail)[0]


def validate_trade_pair(payload_a: bytes, serial_a: int, payload_b: bytes, serial_b: int, *,
                        eggs: bool = False, mail: bool = False) -> tuple[EligibleTradeMon, EligibleTradeMon]:
    """Recheck both complete offers before recording consent or committing. With Mail on either side, the party that
    receives it must have a free party Mail slot once its own offered Pokemon has left ("mail_slots_full")."""
    a, owned_a, snapshot_a = _inspect_offer(payload_a, serial_a, eggs=eggs, mail=mail)
    b, owned_b, snapshot_b = _inspect_offer(payload_b, serial_b, eggs=eggs, mail=mail)
    if a.world_id != b.world_id or a.player_id == b.player_id:
        raise TradeEligibilityError("invalid_pair", "a trade requires different players in the same world")
    if {record.serial for record in owned_a.records} & {record.serial for record in owned_b.records}:
        raise TradeEligibilityError("shared_identity", "the source inventories contain a shared instance")
    for receiver, snapshot, incoming in ((a, snapshot_a, b), (b, snapshot_b, a)):
        if incoming.mail is not None:
            try:
                receiving_slot(snapshot.save_block1, receiver.slot)
            except TradeMailError as error:
                raise TradeEligibilityError(error.code, str(error)) from error
    return a, b
