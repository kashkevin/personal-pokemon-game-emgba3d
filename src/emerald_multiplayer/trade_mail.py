"""Mail that travels with a traded Pokemon (owner decision 39; KNOWN_ISSUES "Trades: eggs and Mail", option (b)).

A party Pokemon holding Mail names one of its trainer's six party Mail slots in its party record (byte 85, MON_DATA_MAIL);
the words, the author's name and ID, the Pokemon the Mail was written for and the Mail item live in that slot of the save
(SaveBlock1.mail[0..5]; [6..15] are the PC's mailbox, never a held Mail). The record alone cannot carry them, so a trade
does what the link trade does (trade.c TradeMons): the sent Pokemon's slot is cleared (mail_data.c ClearMail), then the
received Pokemon's whole Mail is copied into the receiving save's first party slot whose item is ITEM_NONE
(GiveMailToMon2 / GiveMailToMonByItemId) and the Pokemon points at it. Every one of the 36 bytes is copied as it is; the
words are never read or rewritten.

The pinned layout, from the engine's DWARF (tools/pc_port/abi_probe.c, both GBA and PC): SaveBlock1.mail at 0x2BE0,
MAIL_COUNT 16 entries of 36 bytes: words[9] (u16) at 0, playerName[8] at 18, trainerId[4] at 26, species (u16) at 30,
itemId (u16) at 32, two padding bytes. The whole array lies in save section 3; the party in section 1.

Only valid Mail travels. A Pokemon whose Mail reference disagrees with its held item or its trainer's slots, or shares a
slot with another party Pokemon, or an Egg naming a Mail slot, is refused before anything moves ("mail_invalid"), and a
receiving party with no free party Mail slot refuses the trade ("mail_slots_full"); the player takes the Mail off first.
These functions read and build bytes only; they never write a save.
"""
from __future__ import annotations

import struct

from .flash import FlashError, PARTY_SIZE, POKEMON_SIZE, SAVED_PARTY_COUNT_OFFSET, SAVED_PARTY_OFFSET
from .ownership import _SUBSTRUCT_OFFSETS

MAIL_OFFSET = 0x2BE0          # offsetof(SaveBlock1, mail)
MAIL_SIZE = 36                # sizeof(struct Mail)
MAIL_COUNT = 16               # MAIL_COUNT: six party slots, then the PC's mailbox
PARTY_MAIL_SLOTS = PARTY_SIZE  # a held Mail names one of the first six (GiveMailToMonByItemId)
MAIL_NONE = 0xFF              # MON_DATA_MAIL of a Pokemon holding no Mail
MAIL_ITEMS = frozenset(range(199, 211))   # ITEM_ORANGE_MAIL .. ITEM_RETRO_MAIL (mail.h ItemIsMail)
_ITEM_OFFSET = 32             # Mail.itemId
_RECORD_MAIL = 84 + 1         # struct Pokemon: status (u32) at 80, level at 84, mail at 85


class TradeMailError(FlashError):
    """A Mail that cannot travel, before anything is changed."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def mail_slot_bytes(save_block1: bytes, slot: int) -> bytes:
    """The 36 bytes of Mail slot ``slot`` (0-15) of a save's SaveBlock1."""
    if type(slot) is not int or not 0 <= slot < MAIL_COUNT:
        raise TradeMailError("mail_invalid", "a Mail slot is outside the save's Mail array")
    start = MAIL_OFFSET + slot * MAIL_SIZE
    return bytes(save_block1[start:start + MAIL_SIZE])


def mail_item(mail: bytes) -> int:
    """A Mail's item (ITEM_NONE, 0, for a free slot)."""
    return struct.unpack_from("<H", mail, _ITEM_OFFSET)[0]


def cleared_mail(mail: bytes) -> bytes:
    """The slot as mail_data.c ClearMail leaves it: every word EC_EMPTY_WORD (0xFFFF), the name EOS (0xFF) in all eight
    bytes, the trainer ID zero, species SPECIES_BULBASAUR (1), item ITEM_NONE (0); the two padding bytes untouched."""
    if len(mail) != MAIL_SIZE:
        raise TradeMailError("mail_invalid", "a Mail is exactly 36 bytes")
    return b"\xff" * 18 + b"\xff" * 8 + bytes(4) + struct.pack("<HH", 1, 0) + bytes(mail[34:36])


def held_item(record: bytes) -> int:
    """The held item (10 bits; the ownership serial's bits above it are masked) of an occupied party/box record."""
    personality, ot_id = struct.unpack_from("<II", record)
    growth = _SUBSTRUCT_OFFSETS[0][personality % 24] * 12
    return (struct.unpack_from("<I", record, 32 + growth)[0] ^ personality ^ ot_id) >> 16 & 0x3FF


def _party(save_block1: bytes):
    count = save_block1[SAVED_PARTY_COUNT_OFFSET]
    if count > PARTY_SIZE:
        raise TradeMailError("mail_invalid", "the party count exceeds six")
    return [bytes(save_block1[SAVED_PARTY_OFFSET + index * POKEMON_SIZE:SAVED_PARTY_OFFSET + (index + 1) * POKEMON_SIZE])
            for index in range(count)]


def party_mail(save_block1: bytes, index: int) -> bytes | None:
    """The Mail party Pokemon ``index`` holds, or None. Refuses ("mail_invalid") a reference the game itself would not
    make: a slot outside the party's six, a slot whose item is not the Pokemon's held Mail item, a slot another party
    Pokemon names too. A Mail item held with no reference (MAIL_NONE) is an ordinary held item: None."""
    party = _party(save_block1)
    if type(index) is not int or not 0 <= index < len(party):
        raise TradeMailError("mail_invalid", "the Pokemon is not in the party")
    record = party[index]
    slot = record[_RECORD_MAIL]
    if slot == MAIL_NONE:
        return None
    if slot >= PARTY_MAIL_SLOTS:
        raise TradeMailError("mail_invalid", "the Pokemon's Mail is not one of its party's Mail slots")
    mail = mail_slot_bytes(save_block1, slot)
    item = mail_item(mail)
    if item not in MAIL_ITEMS or held_item(record) != item:
        raise TradeMailError("mail_invalid", "the Pokemon's Mail does not match its held item")
    if any(other[_RECORD_MAIL] == slot for position, other in enumerate(party) if position != index):
        raise TradeMailError("mail_invalid", "two party Pokemon name the same Mail slot")
    return mail


def receiving_slot(save_block1: bytes, outgoing_index: int) -> int:
    """The party Mail slot an incoming Mail takes in this save once its outgoing Pokemon has left: the first of the six
    whose item is ITEM_NONE, the outgoing Pokemon's own slot counted free (TradeMons clears it first). A slot another
    remaining party Pokemon names while its item is ITEM_NONE is a damaged save: refused ("mail_invalid"), never shared.
    None free: "mail_slots_full"."""
    party = _party(save_block1)
    if type(outgoing_index) is not int or not 0 <= outgoing_index < len(party):
        raise TradeMailError("mail_invalid", "the outgoing Pokemon is not in the party")
    outgoing = party[outgoing_index][_RECORD_MAIL]
    named = {record[_RECORD_MAIL] for position, record in enumerate(party) if position != outgoing_index}
    for slot in range(PARTY_MAIL_SLOTS):
        if slot == outgoing or mail_item(mail_slot_bytes(save_block1, slot)) == 0:
            if slot in named:
                raise TradeMailError("mail_invalid", "a free Mail slot is still named by a party Pokemon")
            return slot
    raise TradeMailError("mail_slots_full", "the receiving party has no free Mail slot")


def recipient_block1(save_block1: bytes, outgoing_index: int, incoming: bytes, incoming_mail: bytes | None) -> bytes:
    """The receiving SaveBlock1 after the trade: the outgoing Pokemon's Mail slot cleared (when it held Mail), the incoming
    record in its party slot, and the incoming Mail (when it carries one) copied whole into the receiving slot with the
    record pointing at it. Every other byte as it was; only the record's Mail byte differs from the sender's record."""
    if type(incoming) is not bytes or len(incoming) != POKEMON_SIZE:
        raise TradeMailError("mail_invalid", "an incoming party record is exactly 100 bytes")
    if incoming_mail is None:
        if incoming[_RECORD_MAIL] != MAIL_NONE:
            raise TradeMailError("mail_invalid", "an incoming Mail reference arrived without its Mail")
    elif (type(incoming_mail) is not bytes or len(incoming_mail) != MAIL_SIZE or mail_item(incoming_mail) not in MAIL_ITEMS
          or incoming[_RECORD_MAIL] == MAIL_NONE or held_item(incoming) != mail_item(incoming_mail)):
        raise TradeMailError("mail_invalid", "the incoming Mail does not match its Pokemon")
    outgoing_mail = party_mail(save_block1, outgoing_index)
    target = None if incoming_mail is None else receiving_slot(save_block1, outgoing_index)
    block1 = bytearray(save_block1)
    if outgoing_mail is not None:
        slot = save_block1[SAVED_PARTY_OFFSET + outgoing_index * POKEMON_SIZE + _RECORD_MAIL]
        start = MAIL_OFFSET + slot * MAIL_SIZE
        block1[start:start + MAIL_SIZE] = cleared_mail(outgoing_mail)
    record = bytearray(incoming)
    if target is not None:
        start = MAIL_OFFSET + target * MAIL_SIZE
        block1[start:start + MAIL_SIZE] = incoming_mail
        record[_RECORD_MAIL] = target
    start = SAVED_PARTY_OFFSET + outgoing_index * POKEMON_SIZE
    block1[start:start + POKEMON_SIZE] = record
    return bytes(block1)
