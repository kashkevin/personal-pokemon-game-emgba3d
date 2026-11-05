"""Eggs and Mail in world trades (owner decision 39; KNOWN_ISSUES "Trades: eggs and Mail", option (b) for both).

Independent C-layout fixtures (struct Pokemon, struct Mail, SaveBlock1.mail at 0x2BE0) built here, never by the production
encoders, then the real parser, exchange, preparation, desk, SQLite store and live trade coordinator (with the fake ROM of
test_live_trade). What these cannot show: the native game's own hatch and its reading of a received Mail (the engine's
self-test and a real two-game run, docs/trade-eligibility.md).
"""
from __future__ import annotations

import asyncio
import base64
from dataclasses import replace
import hashlib
from itertools import permutations
import json
from pathlib import Path
import struct
import tempfile
from textwrap import wrap
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from emerald_multiplayer.flash import SECTION_LENGTHS, inspect_flash
from emerald_multiplayer.live_trade import LiveTradeCoordinator, LiveTradeError
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE, box_is_egg, inspect_ownership
from emerald_multiplayer.save_mailbox import Opcode, State
from emerald_multiplayer.storage import Checkpoint, StorageError
from emerald_multiplayer.trade_desk import TradeDesk
from emerald_multiplayer.trade_eligibility import (
    CAPABILITY_ID, EGGS_MAIL_CAPABILITY_ID, TradeEligibilityError, validate_party_offer, validate_trade_pair,
)
from emerald_multiplayer.trade_flash import TradeFlashError, build_party_swap, validate_party_swap
from emerald_multiplayer.trade_mail import (
    MAIL_COUNT, MAIL_OFFSET, MAIL_SIZE, TradeMailError, cleared_mail, party_mail, receiving_slot,
)
from emerald_multiplayer.trade_menu import BLOCKED_REASONS, PartyChoice, prepared_choices
from emerald_multiplayer.trade_preparation import (
    TradePreparationError, prepare_pair, prepare_recipient, validate_preparation,
)
from emerald_multiplayer.trade_storage import TradeCheckpointStore, TradeSide
from test_flash import _blocks, _rewrite, _sector_offset, _write_bank
from test_ownership import _write_record, make_ownership_record

BUILD, RULESET = "eggs-mail-test-ROM-sha256", "baseline-test-rules-v1"
TRAINER_A, TRAINER_B, STRANGER = 0x1111AAAA, 0x2222BBBB, 0x3333CCCC
WORLD = "91f9294e-d509-4023-b055-f940a269aabc"
PLAYER_A, PLAYER_B = "0a3c2e4d-0000-4000-8000-00000000000a", "0b3c2e4d-0000-4000-8000-00000000000b"
FIXTURE_MAIL = 0x2BE0      # offsetof(SaveBlock1, mail) in the pinned engine's DWARF, independent of trade_mail.py
FIXTURE_MAIL_SIZE = 36


def make_mon(serial, *, personality=7, species=265, ot_id=TRAINER_A, egg=False, held_item=0, mail=0xFF,
             friendship=70, level=7, ot_name=b"\xbb\xcc\xdd\xff\xff\xff\xff", ivs=0x0A5294A5):
    """A party record in the C layout: the ownership serial in its six reserved bit fields, the held item below them,
    the Egg flag in both places the engine keeps it (byte 19 bit 2, the misc IV word's bit 30), the Mail byte at 85."""
    logical = [bytearray(12) for _ in range(4)]
    struct.pack_into("<H", logical[0], 0, species)
    struct.pack_into("<H", logical[0], 2, (serial & 63) << 10 | held_item)
    struct.pack_into("<I", logical[0], 4, ((serial >> 6) & 7) << 29 | 1000)
    logical[0][9] = friendship                                         # an Egg's: its egg cycles left
    struct.pack_into("<H", logical[0], 10, ((serial >> 9) & 3) << 14 | 4)
    struct.pack_into("<HH", logical[1], 0, 33, 45)
    struct.pack_into("<H", logical[1], 4, ((serial >> 11) & 31) << 11)
    struct.pack_into("<H", logical[1], 6, ((serial >> 16) & 7) << 11)
    logical[1][8:10] = b"\x23\x28"
    struct.pack_into("<I", logical[3], 4, (ivs & 0x3FFFFFFF) | int(egg) << 30)
    struct.pack_into("<I", logical[3], 8, ((serial >> 19) & 1) << 28)
    order = tuple(permutations(range(4)))[personality % 24]
    secure = b"".join(logical[index] for index in order)
    mon = bytearray(100)
    struct.pack_into("<II", mon, 0, personality, ot_id)
    mon[8:18] = (b"\xbf\xc1\xc1" if egg else b"\xbb\xcc").ljust(10, b"\xff")
    mon[18], mon[19] = 2, 2 | int(egg) << 2
    mon[20:27] = ot_name
    struct.pack_into("<H", mon, 28, sum(struct.unpack("<24H", secure)) & 0xFFFF)
    for index, word in enumerate(struct.unpack("<12I", secure)):
        struct.pack_into("<I", mon, 32 + index * 4, word ^ personality ^ ot_id)
    mon[84], mon[85] = (1 if egg else level), mail
    struct.pack_into("<HH", mon, 86, 12, 12)
    return bytes(mon)


def make_mail(item, *, words=(0x0201, 0x0402, 0x0603, 0x0804, 0x0A05, 0x0C06, 0x0E07, 0x1008, 0x1209),
              author=b"\xbb\xcc\xdd\xff\xff\xff\xff\xff", trainer=b"\x01\x02\x03\x04", species=265, padding=b"\x5a\xa5"):
    """struct Mail: nine Easy Chat words, the author's name and ID, the Pokemon it was written for, its item, and two
    padding bytes (not zero here, to show every byte travels)."""
    return struct.pack("<9H", *words) + author + trainer + struct.pack("<HH", species, item) + padding


def make_save(party, *, mails=None, boxes=None, metadata=None, trainer_id=TRAINER_A, counter=2, legacy=False):
    first, second, storage = _blocks(trainer_id)
    block1, storage = bytearray(first), bytearray(storage)
    for index, mon in enumerate(party):
        block1[0x238 + index * 100:0x238 + (index + 1) * 100] = mon
    block1[0x234] = len(party)
    for slot, mail in (mails or {}).items():
        block1[FIXTURE_MAIL + slot * FIXTURE_MAIL_SIZE:FIXTURE_MAIL + (slot + 1) * FIXTURE_MAIL_SIZE] = mail
    for (box, index), mon in (boxes or {}).items():
        start = 4 + (box * 30 + index) * 80
        storage[start:start + 80] = mon[:80]
    flash = bytearray(b"\xff" * 131072)
    rotation = counter % 14
    blocks = (bytes(block1), second, bytes(storage))
    _write_bank(flash, counter - 1, (rotation - 1) % 14, blocks)
    _write_bank(flash, counter, rotation, blocks)
    if not legacy:
        for bank in (counter - 1, counter):
            _write_record(flash, bank % 2, metadata or make_ownership_record())
    return bytes(flash)


def owned_save(grant, party, *, trainer_id, mails=None, boxes=None):
    metadata = make_ownership_record(world_id=grant.world_id, player_id=grant.player_id, grant_id=grant.grant_id,
        start=grant.start, end_exclusive=grant.end_exclusive, next_serial=grant.end_exclusive,
        lease_epoch=grant.lease_epoch, incarnation=grant.incarnation)
    return make_save(party, mails=mails, boxes=boxes, metadata=metadata, trainer_id=trainer_id)


def pair_saves(a_party, b_party, *, a_mails=None, b_mails=None):
    a = make_save(a_party, mails=a_mails, trainer_id=TRAINER_A,
                  metadata=make_ownership_record(player_id=PLAYER_A, start=1, end_exclusive=33, next_serial=33))
    b = make_save(b_party, mails=b_mails, trainer_id=TRAINER_B,
                  metadata=make_ownership_record(player_id=PLAYER_B, start=33, end_exclusive=65, next_serial=65))
    return a, b


def block1(payload):
    return inspect_flash(payload, save_profile=OWNERSHIP_PROFILE).save_block1


def slot_bytes(payload, slot):
    return block1(payload)[FIXTURE_MAIL + slot * FIXTURE_MAIL_SIZE:FIXTURE_MAIL + (slot + 1) * FIXTURE_MAIL_SIZE]


def party_record(payload, index):
    return block1(payload)[0x238 + index * 100:0x238 + (index + 1) * 100]


def held_mails(payload):
    """{serial: the Mail its party Pokemon points at} for every party Pokemon holding Mail."""
    snapshot = inspect_flash(payload, save_profile=OWNERSHIP_PROFILE)
    result = {}
    for record in inspect_ownership(snapshot).records:
        if record.location.startswith("party:"):
            mon = party_record(payload, int(record.location.split(":")[1]))
            if mon[85] != 0xFF:
                result[record.serial] = slot_bytes(payload, mon[85])
    return result


def occupied_mail(payload):
    """Every party Mail slot whose item is set (ITEM_NONE at bytes 32-33 marks a free one): [(slot, bytes)]."""
    return [(slot, slot_bytes(payload, slot)) for slot in range(6) if slot_bytes(payload, slot)[32:34] != b"\0\0"]


class MailLayoutTests(unittest.TestCase):
    def test_the_layout_is_the_pinned_engines_and_lies_in_section_three(self):
        self.assertEqual((MAIL_OFFSET, MAIL_SIZE, MAIL_COUNT), (FIXTURE_MAIL, FIXTURE_MAIL_SIZE, 16))
        section3 = sum(SECTION_LENGTHS[1:3])
        self.assertTrue(section3 <= MAIL_OFFSET and MAIL_OFFSET + MAIL_COUNT * MAIL_SIZE <= section3 + SECTION_LENGTHS[3])
        self.assertLessEqual(0x238 + 600, SECTION_LENGTHS[1])                      # the party: section 1

    def test_a_cleared_slot_is_native_clear_mail_and_keeps_its_padding(self):
        cleared = cleared_mail(make_mail(203))
        self.assertEqual(cleared, b"\xff" * 26 + bytes(4) + b"\x01\x00\x00\x00" + b"\x5a\xa5")
        with self.assertRaises(TradeMailError):
            cleared_mail(b"\0" * 35)


class MailReadingTests(unittest.TestCase):
    def save(self, party, mails):
        return block1(make_save(party, mails=mails, metadata=make_ownership_record()))

    def test_a_held_mail_is_read_whole_and_a_bare_mail_item_is_an_ordinary_item(self):
        b1 = self.save([make_mon(1, held_item=200, mail=2), make_mon(2, personality=8, held_item=201)],
                       {2: make_mail(200)})
        self.assertEqual(party_mail(b1, 0), make_mail(200))
        self.assertIsNone(party_mail(b1, 1))

    def test_references_the_game_never_makes_are_refused(self):
        cases = {
            "the PC mailbox": ([make_mon(1, held_item=200, mail=6)], {6: make_mail(200)}),
            "outside the array": ([make_mon(1, held_item=200, mail=254)], {}),
            "another Mail item": ([make_mon(1, held_item=200, mail=0)], {0: make_mail(201)}),
            "a free slot": ([make_mon(1, held_item=200, mail=0)], {}),
            "no Mail held": ([make_mon(1, held_item=5, mail=0)], {0: make_mail(5)}),
            "a shared slot": ([make_mon(1, held_item=200, mail=0), make_mon(2, personality=8, held_item=200, mail=0)],
                              {0: make_mail(200)}),
        }
        for name, (party, mails) in cases.items():
            with self.subTest(name), self.assertRaises(TradeMailError) as caught:
                party_mail(self.save(party, mails), 0)
            self.assertEqual(caught.exception.code, "mail_invalid")

    def test_the_receiving_slot_is_the_first_free_once_the_outgoing_pokemon_left(self):
        party = [make_mon(1, held_item=200, mail=3), make_mon(2, personality=8, held_item=201, mail=0),
                 make_mon(3, personality=9)]
        b1 = self.save(party, {0: make_mail(201), 3: make_mail(200)})
        self.assertEqual((receiving_slot(b1, 0), receiving_slot(b1, 2)), (1, 1))
        full = self.save(party, {slot: make_mail(201 if slot == 0 else 202) for slot in range(6)} | {3: make_mail(200)})
        self.assertEqual((receiving_slot(full, 0), receiving_slot(full, 1)), (3, 0))   # only its own slot, freed first
        with self.assertRaises(TradeMailError) as caught:
            receiving_slot(full, 2)                                                       # it holds no Mail: none free
        self.assertEqual(caught.exception.code, "mail_slots_full")
        named_free = self.save([make_mon(1), make_mon(2, personality=8, held_item=201, mail=0)], {})
        with self.assertRaises(TradeMailError) as caught:
            receiving_slot(named_free, 0)
        self.assertEqual(caught.exception.code, "mail_invalid")


class EligibilityTests(unittest.TestCase):
    def code(self, code, function, *args, **kwargs):
        with self.assertRaises(TradeEligibilityError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def test_an_egg_is_offered_only_when_allowed_and_read_without_change(self):
        for header, secure in ((True, True), (True, False), (False, True)):
            with self.subTest(header=header, secure=secure):
                mon = bytearray(make_mon(1, egg=True, friendship=9))
                mon[19] = 2 | int(header) << 2
                if not secure:   # a record with only the header flag (the parser never repairs either)
                    mon = bytearray(make_mon(1, egg=False, friendship=9))
                    mon[19] = 6
                payload = make_save([bytes(mon)])
                self.code("egg_unsupported", validate_party_offer, payload, 1)
                self.code("egg_unsupported", validate_party_offer, payload, 1, mail=True)
                before = bytes(payload)
                offer = validate_party_offer(payload, 1, eggs=True)
                self.assertTrue(offer.egg and offer.needs_eggs_and_mail)
                self.assertEqual((offer.friendship, offer.mail), (9, None))      # its egg cycles, untouched
                self.assertEqual(payload, before)

    def test_mail_is_offered_only_when_allowed_valid_and_whole(self):
        payload = make_save([make_mon(1, held_item=200, mail=2)], mails={2: make_mail(200)})
        self.code("mail_unsupported", validate_party_offer, payload, 1)
        self.code("mail_unsupported", validate_party_offer, payload, 1, eggs=True)
        offer = validate_party_offer(payload, 1, mail=True)
        self.assertEqual((offer.mail, offer.held_item, offer.egg), (make_mail(200), 200, False))
        bare = make_save([make_mon(1, held_item=210)])
        self.code("mail_unsupported", validate_party_offer, bare, 1)
        offer = validate_party_offer(bare, 1, mail=True)
        self.assertTrue(offer.mail is None and offer.needs_eggs_and_mail)
        self.code("mail_invalid", validate_party_offer, make_save([make_mon(1, held_item=200, mail=6)],
                  mails={6: make_mail(200)}), 1, mail=True)
        self.code("mail_invalid", validate_party_offer, make_save([make_mon(1, egg=True, held_item=200, mail=0)],
                  mails={0: make_mail(200)}), 1, eggs=True, mail=True)
        plain = validate_party_offer(make_save([make_mon(1)]), 1, eggs=True, mail=True)
        self.assertFalse(plain.needs_eggs_and_mail)
        for value in ("yes", 1, None):
            self.code("invalid_capability", validate_party_offer, payload, 1, mail=value)

    def test_a_pair_needs_a_free_mail_slot_where_the_mail_goes(self):
        a_party = [make_mon(1, held_item=200, mail=0)]
        others = [make_mon(34 + index, personality=20 + index, held_item=201, mail=index) for index in range(5)]
        full_mails = {slot: make_mail(201) for slot in range(5)} | {5: make_mail(209)}       # slot 5: no Pokemon's
        a, b = pair_saves(a_party, [make_mon(33, personality=13)] + others, a_mails={0: make_mail(200)},
                          b_mails=full_mails)
        self.code("mail_slots_full", validate_trade_pair, a, 1, b, 33, eggs=True, mail=True)
        self.code("mail_unsupported", validate_trade_pair, a, 1, b, 33)
        # The same party, its offered Pokemon holding Mail: its slot is freed first, so the incoming Mail fits.
        a, b = pair_saves(a_party, [make_mon(33, personality=13, held_item=209, mail=5)] + others,
                          a_mails={0: make_mail(200)}, b_mails=full_mails)
        first, second = validate_trade_pair(a, 1, b, 33, eggs=True, mail=True)
        self.assertEqual((first.mail, second.mail), (make_mail(200), make_mail(209)))


class ExchangeTests(unittest.TestCase):
    def allowed(self, before, after, changed):
        """Every differing byte lies in a changed block range of the latest bank or its two sector checksum bytes."""
        snapshot = inspect_flash(before, save_profile=OWNERSHIP_PROFILE)
        allowed = set()
        for start, length in changed:
            section = 1 + (start >= SECTION_LENGTHS[1]) + (start >= sum(SECTION_LENGTHS[1:3])) + \
                (start >= sum(SECTION_LENGTHS[1:4]))
            sector = _sector_offset(before, snapshot.metadata.bank, section)
            base = start - sum(SECTION_LENGTHS[1:section])
            allowed |= set(range(sector + base, sector + base + length)) | {sector + 4086, sector + 4087}
        return all(x == y or index in allowed for index, (x, y) in enumerate(zip(before, after)))

    def test_without_mail_the_exchange_is_the_record_exchange_of_before_byte_for_byte(self):
        for personality in range(24):
            with self.subTest(personality=personality):
                a, b = pair_saves([make_mon(1, personality=personality), make_mon(2, personality=40, held_item=44)],
                                  [make_mon(33, personality=personality + 1)])
                self.assertEqual(build_party_swap(a, 1, b, 33), build_party_swap(a, 1, b, 33, carry_mail=False))

    def test_one_way_mail_moves_whole_and_frees_the_senders_slot(self):
        sent, other, pc = make_mail(200), make_mail(201, species=1), make_mail(202, species=7)
        a, b = pair_saves([make_mon(1, held_item=200, mail=3), make_mon(2, personality=8, held_item=201, mail=0)],
                          [make_mon(33, personality=13), make_mon(34, personality=14, held_item=203, mail=0)],
                          a_mails={0: other, 3: sent, 9: pc}, b_mails={0: make_mail(203)})
        after_a, after_b = build_party_swap(a, 1, b, 33)
        validate_party_swap(a, 1, b, 33, after_a, after_b)
        # The receiver: the record whole but its Mail byte, which names the receiver's first free slot (1); the Mail whole.
        received = party_record(after_b, 0)
        self.assertEqual(received[:85] + received[86:], party_record(a, 0)[:85] + party_record(a, 0)[86:])
        self.assertEqual((received[85], slot_bytes(after_b, 1)), (1, sent))
        self.assertEqual(slot_bytes(after_b, 0), make_mail(203))
        # The sender: its slot cleared as ClearMail clears it; its other party Mail and its PC mailbox untouched.
        self.assertEqual(slot_bytes(after_a, 3), cleared_mail(sent))
        self.assertEqual((slot_bytes(after_a, 0), slot_bytes(after_a, 9)), (other, pc))
        self.assertEqual(party_record(after_a, 0), party_record(b, 0))
        self.assertTrue(self.allowed(a, after_a, ((0x238, 100), (FIXTURE_MAIL + 3 * 36, 36))))
        self.assertTrue(self.allowed(b, after_b, ((0x238, 100), (FIXTURE_MAIL + 36, 36))))
        # One copy of each Mail, on the Pokemon that carried it.
        self.assertEqual({**held_mails(after_a), **held_mails(after_b)}, {1: sent, 2: other, 34: make_mail(203)})
        self.assertEqual(sorted(m for _, m in occupied_mail(after_a) + occupied_mail(after_b)),
                         sorted((sent, other, make_mail(203))))

    def test_both_ways_each_mail_takes_the_first_free_slot(self):
        mail_a, mail_b = make_mail(204, words=(1,) * 9), make_mail(205, words=(2,) * 9)
        a, b = pair_saves([make_mon(1, held_item=204, mail=4)],
                          [make_mon(33, personality=13, held_item=205, mail=2), make_mon(34, personality=14, held_item=206, mail=0),
                           make_mon(35, personality=15, held_item=207, mail=1)],
                          a_mails={4: mail_a}, b_mails={0: make_mail(206), 1: make_mail(207), 2: mail_b})
        after_a, after_b = build_party_swap(a, 1, b, 33)
        self.assertEqual((party_record(after_a, 0)[85], slot_bytes(after_a, 0), slot_bytes(after_a, 4)),
                         (0, mail_b, cleared_mail(mail_a)))
        self.assertEqual((party_record(after_b, 0)[85], slot_bytes(after_b, 2)), (2, mail_a))
        self.assertEqual(held_mails(after_a) | held_mails(after_b),
                         {33: mail_b, 1: mail_a, 34: make_mail(206), 35: make_mail(207)})
        validate_party_swap(a, 1, b, 33, after_a, after_b)

    def test_an_egg_moves_as_the_record_it_is(self):
        egg = make_mon(1, egg=True, friendship=11, ot_id=TRAINER_A, personality=0x4B1D5EED)
        a, b = pair_saves([egg, make_mon(2, personality=8)], [make_mon(33, personality=13)])
        after_a, after_b = build_party_swap(a, 1, b, 33)
        self.assertEqual(party_record(after_b, 0), egg)            # every byte: flags, egg cycles, IVs, moves, trainer
        self.assertTrue(box_is_egg(party_record(after_b, 0)))
        self.assertEqual((after_a, after_b), build_party_swap(a, 1, b, 33, carry_mail=False))

    def test_a_receiver_without_a_free_slot_is_refused(self):
        others = [make_mon(34 + index, personality=20 + index, held_item=201, mail=index) for index in range(5)]
        a, b = pair_saves([make_mon(1, held_item=200, mail=0)], [make_mon(33, personality=13)] + others,
                          a_mails={0: make_mail(200)},
                          b_mails={slot: make_mail(201) for slot in range(5)} | {5: make_mail(209)})
        with self.assertRaisesRegex(TradeFlashError, "no free Mail slot"):
            build_party_swap(a, 1, b, 33)

    def test_duplicated_lost_or_misplaced_mail_is_refused_and_only_the_audit_knows_the_old_exchange(self):
        sent = make_mail(200)
        a, b = pair_saves([make_mon(1, held_item=200, mail=3)], [make_mon(33, personality=13)], a_mails={3: sent})
        after_a, after_b = build_party_swap(a, 1, b, 33)
        bank_a = inspect_flash(after_a, save_profile=OWNERSHIP_PROFILE).metadata.bank
        bank_b = inspect_flash(after_b, save_profile=OWNERSHIP_PROFILE).metadata.bank
        section3 = sum(SECTION_LENGTHS[1:3])
        duplicated = _rewrite(after_a, bank_a, 3, FIXTURE_MAIL - section3 + 3 * 36, sent)
        lost = _rewrite(after_b, bank_b, 3, FIXTURE_MAIL - section3 + 0 * 36, cleared_mail(sent))
        moved = _rewrite(_rewrite(after_b, bank_b, 3, FIXTURE_MAIL - section3 + 5 * 36, sent),
                         bank_b, 3, FIXTURE_MAIL - section3, bytes(36))
        for name, posts in (("duplicated", (duplicated, after_b)), ("lost", (after_a, lost)), ("moved", (after_a, moved))):
            with self.subTest(name), self.assertRaises(TradeFlashError):
                validate_party_swap(a, 1, b, 33, *posts)
        legacy = build_party_swap(a, 1, b, 33, carry_mail=False)
        self.assertEqual(slot_bytes(legacy[0], 3), sent)               # the record-only exchange left the Mail behind
        with self.assertRaises(TradeFlashError):
            validate_party_swap(a, 1, b, 33, *legacy)
        validate_party_swap(a, 1, b, 33, *legacy, legacy=True)
        with self.assertRaises(TradeFlashError):
            validate_party_swap(a, 1, b, 33, duplicated, after_b, legacy=True)


def _checkpoint(player_id, payload, revision=2):
    return Checkpoint(player_id, revision, str(uuid.uuid4()), payload, hashlib.sha256(payload).hexdigest(),
                      BUILD, RULESET, OWNERSHIP_PROFILE)


class PreparationTests(unittest.TestCase):
    def prepare(self, a, b, serials=(1, 33), **options):
        checkpoints = (_checkpoint(PLAYER_A, a), _checkpoint(PLAYER_B, b))
        return prepare_pair(WORLD, str(uuid.uuid4()), str(uuid.uuid4()), "f" * 64, checkpoints, (3, 4), serials,
                            **options), checkpoints

    def test_a_plain_pair_keeps_the_plain_capability_and_fields(self):
        a, b = pair_saves([make_mon(1)], [make_mon(33, personality=13)])
        tx, generation = str(uuid.uuid4()), str(uuid.uuid4())
        checkpoints = (_checkpoint(PLAYER_A, a), _checkpoint(PLAYER_B, b))
        plain = prepare_pair(WORLD, tx, generation, "f" * 64, checkpoints, (3, 4), (1, 33))
        allowed = prepare_pair(WORLD, tx, generation, "f" * 64, checkpoints, (3, 4), (1, 33), eggs=True, mail=True)
        self.assertEqual(plain, allowed)
        self.assertEqual(plain[0][0]["capability"], CAPABILITY_ID)
        self.assertNotIn("incoming_mail", plain[0][0])
        self.assertNotIn("mail_sha256", plain[0][0]["players"][0])

    def test_mail_and_egg_descriptions_rebuild_each_recipient_exactly(self):
        mail_a, mail_b = make_mail(200), make_mail(206, words=(7,) * 9)
        for name, a_party, b_party, a_mails, b_mails in (
                ("both Mail", [make_mon(1, held_item=200, mail=1)], [make_mon(33, personality=13, held_item=206, mail=0)],
                 {1: mail_a}, {0: mail_b}),
                ("Egg for Mail", [make_mon(1, egg=True, friendship=4)], [make_mon(33, personality=13, held_item=206, mail=0)],
                 {}, {0: mail_b}),
                ("Egg for a bare Mail item", [make_mon(1, egg=True)], [make_mon(33, personality=13, held_item=199)], {}, {})):
            with self.subTest(name):
                a, b = pair_saves(a_party, b_party, a_mails=a_mails, b_mails=b_mails)
                with self.assertRaises(TradeEligibilityError):
                    self.prepare(a, b)
                if name == "both Mail":
                    (alone, _), _ = self.prepare(a, b, mail=True)      # Mail needs no Egg allowance
                    self.assertEqual(alone[0]["capability"], EGGS_MAIL_CAPABILITY_ID)
                else:
                    with self.assertRaises(TradeEligibilityError):
                        self.prepare(a, b, mail=True)                 # an Egg needs its game's allowance
                (descriptions, candidates), checkpoints = self.prepare(a, b, eggs=True, mail=True)
                self.assertEqual(candidates, build_party_swap(a, 1, b, 33))
                for index, (description, checkpoint) in enumerate(zip(descriptions, checkpoints)):
                    self.assertEqual(description["capability"], EGGS_MAIL_CAPABILITY_ID)
                    self.assertEqual(prepare_recipient(checkpoint.payload, description), candidates[index])
                incoming = [d["incoming_mail"] for d in descriptions]
                expected_a = None if not b_mails else base64.b64encode(mail_b).decode("ascii")
                expected_b = None if not a_mails else base64.b64encode(mail_a).decode("ascii")
                self.assertEqual(incoming, [expected_a, expected_b])

    def test_a_changed_or_missing_mail_is_refused_as_an_older_launcher_refuses_the_capability(self):
        a, b = pair_saves([make_mon(1, held_item=200, mail=1)], [make_mon(33, personality=13)], a_mails={1: make_mail(200)})
        (descriptions, _), checkpoints = self.prepare(a, b, mail=True)
        receiving = descriptions[1]
        forged = dict(receiving, incoming_mail=base64.b64encode(make_mail(200, words=(9,) * 9)).decode("ascii"))
        for name, value in (("other words", forged), ("no Mail", dict(receiving, incoming_mail=None)),
                            ("no field", {k: v for k, v in receiving.items() if k != "incoming_mail"}),
                            ("plain capability", dict(receiving, capability=CAPABILITY_ID)),
                            ("short", dict(receiving, incoming_mail=receiving["incoming_mail"][:44]))):
            with self.subTest(name), self.assertRaises(TradePreparationError):
                validate_preparation(value)
        with self.assertRaises(ValueError):
            prepare_recipient(checkpoints[1].payload, forged)
        # The sender's own Mail must be the one the pair names.
        changed = make_save([make_mon(1, held_item=200, mail=1)], mails={1: make_mail(200, species=1)},
                            trainer_id=TRAINER_A, metadata=make_ownership_record(player_id=PLAYER_A, start=1,
                                                                                end_exclusive=33, next_serial=33))
        with self.assertRaises(ValueError):
            prepare_recipient(changed, dict(descriptions[0]))


class StoreFixture:
    """A schema-3 world whose accounts enroll their own sources and make their first checkpoints."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = TradeCheckpointStore(self.root / "world.sqlite3", BUILD, RULESET)
        self.store.begin_server_boot()
        self.accounts = []

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def account(self, name, trainer_id, specs, mails=None):
        player = self.store.create_player(name)
        lease = self.store.acquire_lease(player.player_id, player.credential)
        self.store.enroll_player(player.player_id, make_save([make_mon(0, **spec) for spec in specs], mails=mails,
                                                             trainer_id=trainer_id, legacy=True))
        grant = self.store.reserve_instances(player.player_id, lease, str(uuid.uuid4()), 0, 1, 32)
        party = [make_mon(grant.start + index, **spec) for index, spec in enumerate(specs)]
        head = self.store.commit_checkpoint(player.player_id, lease, str(uuid.uuid4()), 0,
                                            owned_save(grant, party, trainer_id=trainer_id, mails=mails),
                                            BUILD, RULESET, OWNERSHIP_PROFILE)
        account = SimpleNamespace(player=player, lease=lease, grant=grant, trainer=trainer_id, head=head)
        self.accounts.append(account)
        return account

    def code(self, code, function, *args, **kwargs):
        with self.assertRaises(StorageError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def head(self, account):
        return self.store.read_checkpoint(account.player.player_id, account.lease)

    def trade(self, first, first_serial, second, second_serial):
        heads = sorted(((first, first_serial), (second, second_serial)), key=lambda item: item[0].player.player_id)
        payloads = build_party_swap(self.head(heads[0][0]).payload, heads[0][1], self.head(heads[1][0]).payload, heads[1][1])
        sides = tuple(TradeSide(account.player.player_id, account.lease, self.head(account).revision, serial, payload)
                      for (account, serial), payload in zip(heads, payloads))
        result = self.store.commit_trade(str(uuid.uuid4()), *sides, BUILD, RULESET, OWNERSHIP_PROFILE)
        for checkpoint in (result.checkpoint_a, result.checkpoint_b):
            account = next(a for a in self.accounts if a.player.player_id == checkpoint.player_id)
            self.store.acknowledge_trade(checkpoint.player_id, account.lease, result.transaction_id,
                                         checkpoint.revision, checkpoint.sha256)
        return result

    def save(self, account, party, *, mails=None, boxes=None):
        head = self.head(account)
        return self.store.commit_checkpoint(account.player.player_id, account.lease, str(uuid.uuid4()), head.revision,
                                            owned_save(account.grant, party, trainer_id=account.trainer, mails=mails,
                                                       boxes=boxes), BUILD, RULESET, OWNERSHIP_PROFILE)

    def instance(self, serial):
        return self.store._connection.execute("SELECT * FROM ownership_instances WHERE serial = ?", (serial,)).fetchone()


class DeskTests(StoreFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.a = self.account("A", TRAINER_A, [dict(personality=7, egg=True, friendship=5),
                                               dict(personality=8, held_item=200, mail=2)], mails={2: make_mail(200)})
        self.b = self.account("B", TRAINER_B, [dict(personality=9, ot_id=TRAINER_B, held_item=205, mail=0),
                                               dict(personality=10, ot_id=TRAINER_B)], mails={0: make_mail(205)})
        self.leases = {acc.player.player_id: acc.lease for acc in (self.a, self.b)}
        self.desk = TradeDesk(self.store, self.leases.get)
        self.tx = str(uuid.uuid4())
        self.view = self.desk.open(self.a.player.player_id, self.a.lease, self.b.player.player_id, self.tx)

    def offer(self, account, serial):
        head = self.head(account)
        return self.desk.offer(account.player.player_id, account.lease, self.tx, self.view["generation"],
                               head.revision, head.sha256, serial)

    def confirm(self, account, view):
        return self.desk.confirm(account.player.player_id, account.lease, self.tx, view["generation"], view["fingerprint"])

    def test_an_egg_needs_its_games_capability_and_mail_none(self):
        self.code("egg_unsupported", self.offer, self.a, self.a.grant.start)
        self.assertEqual(self.offer(self.a, self.a.grant.start + 1)["offers"][0]["serial"], self.a.grant.start + 1)
        self.desk.trade_mail = False                                # the exchange of before
        self.code("mail_unsupported", self.offer, self.b, self.b.grant.start)

    def test_an_egg_for_a_pokemon_holding_mail_commits_in_one_transaction(self):
        self.desk.trade_eggs = True
        before = (self.head(self.a), self.head(self.b))
        self.offer(self.a, self.a.grant.start)
        view = self.offer(self.b, self.b.grant.start)
        self.confirm(self.a, view)
        view = self.confirm(self.b, view)
        self.assertEqual(view["state"], "preparing")
        for account in (self.a, self.b):
            description = self.desk.preparation(account.player.player_id, account.lease, self.tx, view["generation"])["preparation"]
            self.assertEqual(description["capability"], EGGS_MAIL_CAPABILITY_ID)
            own = next(p for p in description["players"] if p["player_id"] == account.player.player_id)
            candidate = prepare_recipient(self.head(account).payload, description)
            self.assertEqual(hashlib.sha256(candidate).hexdigest(), own["candidate_sha256"])
            result = self.desk.prepared(account.player.player_id, account.lease, self.tx, view["generation"],
                                        description["fingerprint"], description["preparation_id"], own["candidate_sha256"])
        self.assertEqual(result["state"], "committed")
        after_a, after_b = self.head(self.a).payload, self.head(self.b).payload
        self.assertEqual(party_record(after_b, 0), party_record(before[0].payload, 0))     # the Egg, every byte
        # A's first party slot now holds B's Pokemon with B's Mail in A's first free slot (0); B's slot 0 is free again.
        self.assertEqual((party_record(after_a, 0)[85], slot_bytes(after_a, 0), slot_bytes(after_a, 2)),
                         (0, make_mail(205), make_mail(200)))
        self.assertEqual(slot_bytes(after_b, 0), cleared_mail(make_mail(205)))
        self.assertEqual(held_mails(after_a), {self.b.grant.start: make_mail(205), self.a.grant.start + 1: make_mail(200)})
        self.assertEqual(held_mails(after_b), {})
        self.store.integrity_check()

    def test_a_receiver_with_no_free_mail_slot_refuses_at_confirmation_before_anything_moves(self):
        full = self.account("Full", STRANGER, [dict(personality=11, ot_id=STRANGER)] + [
            dict(personality=12 + index, ot_id=STRANGER, held_item=201, mail=index) for index in range(5)],
            mails={slot: make_mail(201) for slot in range(5)} | {5: make_mail(209)})
        self.leases[full.player.player_id] = full.lease
        self.desk.cancel(self.a.player.player_id, self.a.lease, self.tx, self.view["generation"])
        self.tx = str(uuid.uuid4())
        self.view = self.desk.open(self.a.player.player_id, self.a.lease, full.player.player_id, self.tx)
        self.offer(self.a, self.a.grant.start + 1)
        view = self.offer(full, full.grant.start)
        for account in (self.a, full):     # each confirmation checks the pair again; neither is recorded
            self.code("mail_slots_full", self.confirm, account, view)
        self.assertEqual(self.desk.status(self.a.player.player_id, self.a.lease, self.tx)["confirmations"], [])
        self.assertEqual(self.store._connection.execute("SELECT COUNT(*) FROM trade_transactions").fetchone()[0], 0)
        self.assertEqual((self.head(self.a).revision, self.head(full).revision), (1, 1))
        self.store.integrity_check()


class HatchTests(StoreFixture, unittest.TestCase):
    """The one change of a Pokemon's original trainer the host accepts: a traded Egg hatched by its owner's game."""

    def setUp(self):
        super().setUp()
        self.a = self.account("A", TRAINER_A, [dict(personality=0x4B1D5EED, egg=True, friendship=3),
                                               dict(personality=8)])
        self.b = self.account("B", TRAINER_B, [dict(personality=9, ot_id=TRAINER_B), dict(personality=10, ot_id=TRAINER_B)])
        self.egg = self.a.grant.start
        self.trade(self.a, self.egg, self.b, self.b.grant.start)
        self.kept = make_mon(self.b.grant.start + 1, personality=10, ot_id=TRAINER_B)

    def hatched(self, **changes):
        values = dict(personality=0x4B1D5EED, egg=False, friendship=120, ot_id=TRAINER_B, level=1,
                      ot_name=b"\xbc\xbd\xbe\xff\xff\xff\xff")
        values.update(changes)
        return make_mon(self.egg, **values)

    def test_the_receivers_hatch_makes_its_player_the_original_trainer_and_audits(self):
        head = self.save(self.b, [self.hatched(), self.kept])
        self.assertEqual((self.instance(self.egg)["ot_id"], self.instance(self.egg)["personality"]), (TRAINER_B, 0x4B1D5EED))
        rows = self.store._connection.execute("SELECT revision, ot_id FROM ownership_memberships WHERE serial = ? "
                                              "ORDER BY player_id, revision", (self.egg,)).fetchall()
        self.assertIn((head.revision, TRAINER_B), [tuple(row) for row in rows])
        self.assertIn(TRAINER_A, [row["ot_id"] for row in rows])                  # its history keeps the Egg's trainer
        self.store.integrity_check()
        # The hatched Pokemon trades on as any other, and the history still balances after a restart.
        self.trade(self.b, self.egg, self.a, self.a.grant.start + 1)
        self.store.close()
        self.store = TradeCheckpointStore(self.root / "world.sqlite3", BUILD, RULESET)
        self.store.integrity_check()

    def test_a_hatch_in_a_pc_box_is_the_same_change(self):
        self.save(self.b, [self.kept], boxes={(0, 0): make_mon(self.egg, personality=0x4B1D5EED, egg=True, friendship=3)})
        self.save(self.b, [self.kept], boxes={(0, 0): self.hatched()})
        self.assertEqual(self.instance(self.egg)["ot_id"], TRAINER_B)
        self.store.integrity_check()

    def test_every_other_change_of_original_trainer_is_refused(self):
        cases = {
            "another trainer": self.hatched(ot_id=STRANGER),
            "still an Egg": self.hatched(egg=True, friendship=3),
            "another personality": self.hatched(personality=0x4B1D5EEE),
        }
        for name, mon in cases.items():
            with self.subTest(name):
                self.code("immutable_identity_changed", self.save, self.b, [mon, self.kept])
                self.assertEqual(self.head(self.b).revision, 2)
        # Not an Egg: B's own Pokemon (it came with B's character) and A's traded one keep their trainers.
        self.code("immutable_identity_changed", self.save, self.b,
                  [make_mon(self.egg, personality=0x4B1D5EED, egg=True, friendship=3),
                   make_mon(self.b.grant.start + 1, personality=10, ot_id=STRANGER)])
        self.code("immutable_identity_changed", self.save, self.a,
                  [make_mon(self.b.grant.start, personality=9, ot_id=TRAINER_A), make_mon(self.a.grant.start + 1, personality=8)])
        self.assertEqual(self.instance(self.egg)["ot_id"], TRAINER_A)
        self.store.integrity_check()

    def test_an_egg_born_in_the_owners_own_play_never_changes_its_trainer(self):
        born = self.a.grant.start + 5
        egg = make_mon(born, personality=77, egg=True, friendship=2, ot_id=STRANGER)   # as no game of this world makes one
        self.save(self.a, [make_mon(self.b.grant.start, personality=9, ot_id=TRAINER_B),
                           make_mon(self.a.grant.start + 1, personality=8), egg])
        self.code("immutable_identity_changed", self.save, self.a,
                  [make_mon(self.b.grant.start, personality=9, ot_id=TRAINER_B), make_mon(self.a.grant.start + 1, personality=8),
                   make_mon(born, personality=77, friendship=120, ot_id=TRAINER_A)])
        self.store.integrity_check()

    def test_an_egg_that_came_with_the_character_hatches_too(self):
        c = self.account("C", STRANGER, [dict(personality=21, egg=True, friendship=1, ot_id=TRAINER_A)])
        self.save(c, [make_mon(c.grant.start, personality=21, friendship=120, ot_id=STRANGER)])
        self.assertEqual(self.instance(c.grant.start)["ot_id"], STRANGER)
        self.store.integrity_check()

    def test_the_audit_refuses_a_changed_trainer_its_history_does_not_explain(self):
        self.save(self.b, [self.hatched(), self.kept])
        connection = self.store._connection
        for sql, args, undo, undo_args in (
                ("UPDATE ownership_instances SET ot_id = ? WHERE serial = ?", (TRAINER_A, self.egg),
                 "UPDATE ownership_instances SET ot_id = ? WHERE serial = ?", (TRAINER_B, self.egg)),
                ("UPDATE ownership_events SET kind = 'acquire', transaction_id = NULL WHERE serial = ? AND kind = 'transfer_in'",
                 (self.egg,), None, None)):
            with self.subTest(sql=sql):
                connection.execute(sql, args)
                self.code("storage_corrupt", self.store.integrity_check)
                if undo is None:
                    break
                connection.execute(undo, undo_args)
                self.store.integrity_check()

    def test_a_copy_of_the_egg_cannot_come_back_with_its_old_trainer(self):
        from emerald_multiplayer.character_transfer import detach_from_world
        from emerald_multiplayer.character_transfers import enable_character_transfers, transfer_player
        copy = self.store.read_checkpoint(self.a.player.player_id, self.a.lease, revision=1).payload   # still the Egg
        self.save(self.b, [self.hatched(), self.kept])
        for account in (self.a, self.b):
            self.store.release_lease(account.player.player_id, account.lease)
        self.assertTrue(enable_character_transfers(self.store, self.root / "before-transfers.sqlite3"))
        self.a.lease = self.store.acquire_lease(self.a.player.player_id, self.a.player.credential)
        self.code("pokemon_owned_here", transfer_player, self.store, self.a.player.player_id, detach_from_world(copy).payload)


class LiveMailTradeTests(unittest.IsolatedAsyncioTestCase):
    """Interruptions of a trade carrying Mail both ways, through the real coordinator, desk and store (test_live_trade's
    fake ROM): each ends with the Mail in exactly one save, on the Pokemon that carried it, and the world audits."""

    MAIL_0, MAIL_1, OTHER = make_mail(199, words=(3,) * 9), make_mail(205, words=(4,) * 9), make_mail(200, species=1)

    def setUp(self):
        from test_live_trade import TradeCompanion
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.store = TradeCheckpointStore(self.directory / "world.sqlite3", "a" * 64, "rules-v1")
        self.store.begin_server_boot()
        self.companions, self.coordinators, self.grants, self.originals = [], [], [], []
        self.leases = {}
        specs = ([dict(personality=7, held_item=199, mail=1), dict(personality=8, held_item=200, mail=0)],
                 [dict(personality=9, ot_id=TRAINER_B, held_item=205, mail=0),
                  dict(personality=0x4B1D5EED, ot_id=TRAINER_B, egg=True, friendship=4)])
        mails = ({0: self.OTHER, 1: self.MAIL_0}, {0: self.MAIL_1})
        for index, trainer in enumerate((TRAINER_A, TRAINER_B)):
            identity = self.store.create_player("Actor " + str(index))
            lease = self.store.acquire_lease(identity.player_id, identity.credential)
            self.leases[identity.player_id] = lease
            self.store.enroll_player(identity.player_id, make_save([make_mon(0, **s) for s in specs[index]],
                                                                   mails=mails[index], trainer_id=trainer, legacy=True))
            grant = self.store.reserve_instances(identity.player_id, lease, str(uuid.uuid4()), 0, 2, 32)
            payload = owned_save(grant, [make_mon(grant.start + i, **s) for i, s in enumerate(specs[index])],
                                 trainer_id=trainer, mails=mails[index])
            self.store.commit_checkpoint(identity.player_id, lease, str(uuid.uuid4()), 0, payload, self.store.build_id,
                                         self.store.ruleset_id, OWNERSHIP_PROFILE)
            private = self.directory / str(index)
            companion = TradeCompanion(self.store, identity, lease, payload, private, self.leases)
            companion.config.trade_egg_abi_version = 1
            self.companions.append(companion)
            self.coordinators.append(LiveTradeCoordinator(companion, private))
            self.grants.append(grant)
            self.originals.append(payload)
        self.desk = TradeDesk(self.store, self.leases.get)
        self.desk.trade_eggs = True
        for companion in self.companions:
            companion.desk = self.desk
        self.tx = str(uuid.uuid4())
        self.generation = self.desk.open(self.companions[0].config.player_id, self.companions[0].session_epoch,
                                         self.companions[1].config.player_id, self.tx)["generation"]

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def replacement(self, index):
        self.coordinators[index] = LiveTradeCoordinator(self.companions[index], self.coordinators[index].directory)
        return self.coordinators[index]

    def ops(self, index):
        return [command.opcode for command in self.companions[index].commands]

    async def ready(self, serials=None):
        for coordinator in self.coordinators:
            await coordinator.prepare(self.tx, self.generation, 1)
        serials = serials or (self.grants[0].start, self.grants[1].start)
        await self.coordinators[0].offer(serials[0])
        return await self.coordinators[1].offer(serials[1])

    async def committed(self, serials=None):
        view = await self.ready(serials)
        await self.coordinators[0].confirm(view["fingerprint"])
        await self.coordinators[1].confirm(view["fingerprint"])
        await self.coordinators[0].prepare_recipient()
        await self.coordinators[1].prepare_recipient()
        return view

    def heads(self):
        return [c.store.read_checkpoint(c.config.player_id, c.session_epoch) for c in self.companions]

    def assert_traded(self, *, applied=True):
        """The Mail moved with each Pokemon, once; the senders' slots are free; the games hold the canonical results."""
        heads = [head.payload for head in self.heads()]
        self.assertEqual(held_mails(heads[0]) | held_mails(heads[1]),
                         {self.grants[0].start: self.MAIL_0, self.grants[1].start: self.MAIL_1,
                          self.grants[0].start + 1: self.OTHER})
        self.assertEqual(held_mails(heads[0]), {self.grants[1].start: self.MAIL_1, self.grants[0].start + 1: self.OTHER})
        self.assertEqual(sorted(m for payload in heads for _, m in occupied_mail(payload)),
                         sorted((self.MAIL_0, self.MAIL_1, self.OTHER)))
        if applied:
            for companion, head in zip(self.companions, heads):
                self.assertEqual(companion.rom_flash, inspect_flash(head, save_profile=OWNERSHIP_PROFILE).flash)
        self.store.integrity_check()

    def assert_untouched(self):
        for companion, original in zip(self.companions, self.originals):
            self.assertEqual(held_mails(companion.rom_flash + b""), held_mails(original))
        self.assertEqual(self.store._connection.execute("SELECT COUNT(*) FROM trade_transactions").fetchone()[0], 0)
        self.store.integrity_check()

    async def test_the_mail_trade_applies_once_in_both_games(self):
        await self.committed()
        for index in (0, 1):
            self.assertEqual((await self.coordinators[index].resume())["state"], "applied")
            self.assertEqual((self.companions[index].rom_commits, self.companions[index].releases), (1, 1))
        self.assert_traded()

    async def test_an_interrupted_freeze_restarts_the_same_save_and_the_mail_moves_once(self):
        c = self.companions[0]
        for opcode, count in ((Opcode.BEGIN_TRADE_EXPORT, 1), (Opcode.READ, 7), (Opcode.END, 1)):
            c.faults[opcode] = count
            with self.assertRaises(asyncio.TimeoutError):
                await self.replacement(0).prepare(self.tx, self.generation, 1)
            self.assertTrue(c.active)                                 # the game stays held, its save not exported twice
        await self.replacement(0).prepare(self.tx, self.generation, 1)
        self.assertEqual(c.normal_saves, 1)
        await self.coordinators[1].prepare(self.tx, self.generation, 1)
        await self.coordinators[0].offer(self.grants[0].start)
        view = await self.coordinators[1].offer(self.grants[1].start)
        for coordinator in self.coordinators:
            await coordinator.confirm(view["fingerprint"])
        for coordinator in self.coordinators:
            await coordinator.prepare_recipient()
        for index in (0, 1):
            self.assertEqual((await self.coordinators[index].resume())["state"], "applied")
        self.assert_traded()

    async def test_a_lost_acknowledgment_and_a_lost_release_keep_one_copy(self):
        await self.committed()
        c = self.companions[1]

        async def lose(operation, result):
            if operation == "ack":
                c.trade_hook = None
                raise asyncio.TimeoutError("durable apply acknowledgment lost")
        c.trade_hook = lose
        with self.assertRaises(asyncio.TimeoutError), patch("emerald_multiplayer.live_trade.HOST_PATIENCE_SECONDS", 0):
            await self.coordinators[1].resume()
        self.assertFalse(self.store.pending_trade_recovery(c.config.player_id, c.session_epoch))   # the ack was applied
        c.reconnect()
        c.faults[Opcode.RELEASE_TRADE] = 1
        with self.assertRaises(asyncio.TimeoutError):
            await self.replacement(1).resume()
        self.assertEqual((await self.replacement(1).resume())["state"], "applied")
        self.assertEqual((c.rom_commits, c.releases), (1, 1))
        # Meanwhile the other game had not applied: its next save stays refused until it does.
        other = self.companions[0]
        head = self.heads()[0]
        with self.assertRaises(StorageError) as caught:
            self.store.commit_checkpoint(other.config.player_id, other.session_epoch, str(uuid.uuid4()), head.revision,
                                         self.originals[0], self.store.build_id, self.store.ruleset_id, OWNERSHIP_PROFILE)
        self.assertEqual(caught.exception.code, "trade_recovery_required")
        self.assertEqual((await self.coordinators[0].resume())["state"], "applied")
        self.assert_traded()

    async def test_a_lost_commit_reply_then_a_reconnect_recovers_the_same_mail(self):
        view = await self.ready()
        await self.coordinators[0].confirm(view["fingerprint"])
        await self.coordinators[1].confirm(view["fingerprint"])
        await self.coordinators[0].prepare_recipient()
        c = self.companions[1]

        async def lose(operation, result):
            if operation == "prepared":
                c.trade_hook = None
                raise asyncio.TimeoutError("paired commit reply lost")
        c.trade_hook = lose
        with self.assertRaises(asyncio.TimeoutError), patch("emerald_multiplayer.live_trade.HOST_PATIENCE_SECONDS", 0):
            await self.coordinators[1].prepare_recipient()
        self.assert_traded(applied=False)                  # committed: canonical saves hold the Mail once already
        c.reconnect()
        self.assertEqual((await self.replacement(1).recover())["state"], "applied")
        self.assertEqual((await self.coordinators[0].resume())["state"], "applied")
        self.assert_traded()

    async def test_interrupted_imports_restage_the_same_post_image(self):
        await self.committed()
        c = self.companions[0]
        c.faults[Opcode.WRITE] = 4
        with self.assertRaises(asyncio.TimeoutError):
            await self.coordinators[0].resume()
        c.reconnect()
        c.faults[Opcode.COMMIT] = 1
        with self.assertRaises(asyncio.TimeoutError):
            await self.replacement(0).resume()
        self.assertEqual(c.phase, State.COMMITTED)
        self.assertEqual((await self.replacement(0).resume())["state"], "applied")
        other = self.companions[1]
        other.faults[Opcode.RELEASE_TRADE] = 1
        with self.assertRaises(asyncio.TimeoutError):
            await self.coordinators[1].resume()
        other.reconnect()
        self.assertEqual((await self.replacement(1).resume())["state"], "applied")
        self.assertEqual((other.rom_commits, other.releases), (1, 1))
        self.assert_traded()

    async def test_recovery_rebuilds_the_retained_candidate_with_its_mail_and_refuses_a_changed_one(self):
        await self.committed()
        for index in (0, 1):
            coordinator = self.replacement(index)
            session = coordinator._session()
            intent = coordinator._load(session)
            self.assertEqual(coordinator._prepared_candidate(intent, session), self.heads()[index].payload)
        prefix = self.directory / "1" / (self.tx + "." + self.generation)
        record_path = Path(str(prefix) + ".recipient-preparation.json")
        record = json.loads(record_path.read_bytes())
        record["preparation"]["incoming_mail"] = base64.b64encode(make_mail(199, words=(5,) * 9)).decode("ascii")
        from emerald_multiplayer.live_checkpoint import _json_bytes
        original = record_path.read_bytes()
        record_path.write_bytes(_json_bytes(record))
        coordinator = self.replacement(1)
        session = coordinator._session()
        with self.assertRaises(LiveTradeError) as caught:
            coordinator._prepared_candidate(coordinator._load(session), session)
        self.assertEqual(caught.exception.code, "invalid_journal")
        record_path.write_bytes(original)
        for index in (0, 1):
            self.assertEqual((await self.replacement(index).resume())["state"], "applied")
        self.assert_traded()

    async def test_a_cancel_before_both_consents_moves_nothing(self):
        view = await self.ready()
        await self.coordinators[0].confirm(view["fingerprint"])
        self.assertEqual((await self.coordinators[1].cancel())["state"], "aborted")
        self.assertEqual((await self.coordinators[0].resume())["state"], "aborted")
        self.assert_untouched()

    async def test_mail_needs_no_egg_capability_in_either_game(self):
        for companion in self.companions:
            companion.config.trade_egg_abi_version = 0
        await self.committed()
        for index in (0, 1):
            self.assertEqual((await self.coordinators[index].resume())["state"], "applied")
        self.assert_traded()

    async def test_a_game_that_cannot_hatch_a_traded_egg_refuses_it_before_acknowledging_anything(self):
        self.companions[0].config.trade_egg_abi_version = 0
        view = await self.ready((self.grants[0].start + 1, self.grants[1].start + 1))      # Mail for the Egg
        await self.coordinators[0].confirm(view["fingerprint"])
        await self.coordinators[1].confirm(view["fingerprint"])
        await self.coordinators[1].prepare_recipient()
        with self.assertRaises(LiveTradeError) as caught:
            await self.coordinators[0].prepare_recipient()
        self.assertEqual(caught.exception.code, "trade_egg_unsupported")
        self.assertEqual([head.revision for head in self.heads()], [2, 2])         # the frozen saves; nothing committed
        self.assertEqual((await self.coordinators[0].cancel())["state"], "aborted")
        self.assertEqual((await self.coordinators[1].resume())["state"], "aborted")
        self.assert_untouched()

    async def test_an_egg_travels_whole_and_the_menu_offers_it_only_with_the_capability(self):
        await self.ready((self.grants[0].start + 1, self.grants[1].start + 1))
        choices = prepared_choices(self.coordinators[1])
        egg = next(choice for choice in choices if choice.serial == self.grants[1].start + 1)
        self.assertTrue(egg.egg and egg.eligible)
        self.assertEqual(egg.label(25), "Egg")
        self.companions[1].config.trade_egg_abi_version = 0
        blocked = {choice.serial: choice for choice in prepared_choices(self.coordinators[1])}
        self.assertEqual(blocked[self.grants[1].start + 1].reason, BLOCKED_REASONS["egg_unsupported"])
        self.assertTrue(blocked[self.grants[1].start].eligible)                          # holding Mail
        self.assertEqual(blocked[self.grants[1].start + 1].label(25), "[X] Egg")
        self.companions[1].config.trade_egg_abi_version = 1
        view = await self.coordinators[1].status()
        await self.coordinators[0].confirm(view["fingerprint"])
        await self.coordinators[1].confirm(view["fingerprint"])
        await self.coordinators[0].prepare_recipient()
        await self.coordinators[1].prepare_recipient()
        for index in (0, 1):
            self.assertEqual((await self.coordinators[index].resume())["state"], "applied")
        received = inspect_flash(self.companions[0].rom_flash, save_profile=OWNERSHIP_PROFILE).save_block1
        self.assertEqual(received[0x238 + 100:0x238 + 200], party_record(self.originals[1], 1))
        self.store.integrity_check()


class MenuTextTests(unittest.TestCase):
    def test_every_refusal_fits_the_blocked_page(self):
        for code, text in BLOCKED_REASONS.items():
            with self.subTest(code):
                self.assertLessEqual(len(wrap(text, 25)), 5)       # five rows and "Back to your party"
        self.assertEqual(PartyChoice(1, 25, 5, True).label(25), "Pikachu Lv5")
        self.assertEqual(PartyChoice(1, 25, 1, False, egg=True).label(25), "[X] Egg")


class CapabilityTests(unittest.TestCase):
    def test_the_manifest_marker_needs_the_ownership_trade_and_enables_host_and_launcher(self):
        from emerald_multiplayer.bridge_config import trade_eggs_enabled
        import test_save_manifest as fixtures
        case = fixtures.SaveManifestTests()
        case.setUp()
        self.addCleanup(case.tearDown)
        owned = "02021000 00000200 B gMultiplayerSaveMailbox\n080000c0 00000004 R gMultiplayerOwnershipAbi\n"
        trade = "080000c4 00000004 R gMultiplayerTradeAbiVersion\n"
        marker = "00bd27a0 00000004 R gMultiplayerTradeEggAbiVersion\n"
        with case.rom.open("r+b") as rom:
            rom.seek(192)
            rom.write(b"\x01\0\0\0" * 2)

        def generate(elf, native):
            with patch.object(fixtures.generator.subprocess, "check_output", return_value=case.symbols + elf):
                return fixtures.generator.generate(case.rom, case.elf, "fixture-nm", "b" * 40, native_symbols=native)
        generated = generate(owned + trade, marker)
        self.assertEqual(generated["trade_egg_abi_version"], 1)
        self.assertTrue(trade_eggs_enabled(generated))
        case.verify(generated)
        self.assertEqual(generate(owned + trade, "00bd27a0 R _gMultiplayerTradeEggAbiVersion\n")
                         ["trade_egg_abi_version"], 1)                                        # MinGW nm: no sizes
        plain = generate(owned + trade, "")
        self.assertNotIn("trade_egg_abi_version", plain)
        self.assertFalse(trade_eggs_enabled(plain))
        for elf, native in ((owned, marker), (owned + trade, marker + marker),
                            (owned + trade, marker.replace("00000004", "00000008"))):
            with self.subTest(elf=elf, native=native), self.assertRaises(ValueError):
                generate(elf, native)
        for changes in (dict(trade_egg_abi_version=2), dict(trade_egg_abi_version=True), dict(trade_abi_version=None)):
            with self.subTest(changes=changes):
                self.assertFalse(trade_eggs_enabled({**generated, **changes}))

    def test_the_host_enables_eggs_only_before_it_starts_and_carries_mail_always(self):
        from emerald_multiplayer.server import ServerConfig, WorldServer
        with tempfile.TemporaryDirectory() as temp:
            store = TradeCheckpointStore(Path(temp) / "world.sqlite3", "a" * 64, "baseline-test-rules-v1")
            try:
                server = WorldServer(ServerConfig("a" * 64, "baseline-test-rules-v1"), store=store, development_trades=True)
                self.assertEqual((server.trade_desk.trade_eggs, server.trade_desk.trade_mail), (False, True))
                server.enable_egg_trades()
                self.assertTrue(server.trade_desk.trade_eggs)
                server.shared_world.close()
                server.friendships.close()
                server.wagers.close()
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
