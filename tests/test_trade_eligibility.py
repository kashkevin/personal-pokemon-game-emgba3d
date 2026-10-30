from __future__ import annotations

from itertools import permutations
import struct
import unittest
from uuid import uuid4

from emerald_multiplayer.flash import SAVED_PARTY_OFFSET, inspect_flash
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE
from emerald_multiplayer.trade_eligibility import (
    TradeEligibilityError, validate_party_offer, validate_trade_pair,
)
from test_flash import _rewrite
from test_ownership import make_owned_mon, make_ownership_flash, make_ownership_record


def offer_flash(*, species=265, serial=1, personality=7, player_id=None,
                header_egg=False, secure_egg=False, held_item=0,
                mail=0xFF, friendship=137):
    """Independent encrypted C-layout fixture, retaining the real UID bits."""
    payload = make_ownership_flash(records=(("party:0", serial),),
        personalities=(personality,), metadata=make_ownership_record(
            player_id=player_id or str(uuid4())), with_rtc=True)
    mon = bytearray(make_owned_mon(serial, personality=personality, species=species))
    key = personality ^ 0xAABBCCDD
    physical = struct.pack("<12I", *(word ^ key for word in struct.unpack_from("<12I", mon, 32)))
    order = tuple(permutations(range(4)))[personality % 24]
    logical = [bytearray(physical[order.index(index) * 12:order.index(index) * 12 + 12])
               for index in range(4)]
    word = struct.unpack_from("<H", logical[0], 2)[0]
    struct.pack_into("<H", logical[0], 2, (word & 0xFC00) | held_item)
    logical[0][9] = friendship
    word = struct.unpack_from("<I", logical[3], 4)[0]
    struct.pack_into("<I", logical[3], 4, word | (int(secure_egg) << 30))
    secure = b"".join(logical[index] for index in order)
    mon[19] |= int(header_egg) << 2
    mon[85] = mail
    struct.pack_into("<H", mon, 28, sum(struct.unpack("<24H", secure)) & 0xFFFF)
    for index, word in enumerate(struct.unpack("<12I", secure)):
        struct.pack_into("<I", mon, 32 + index * 4, word ^ key)
    return _rewrite(payload, 0, 1, SAVED_PARTY_OFFSET, bytes(mon))


class TradeEligibilityTests(unittest.TestCase):
    def assert_code(self, code, payload, serial=1):
        with self.assertRaises(TradeEligibilityError) as caught:
            validate_party_offer(payload, serial)
        self.assertEqual(caught.exception.code, code)

    def test_simple_proof_species_and_all_encrypted_permutations_preserve_bytes(self):
        # Exact native IDs: Treecko252, Torchic255, Wurmple265.
        for species in (252, 255, 265):
            for personality in range(24):
                with self.subTest(species=species, personality=personality):
                    payload = offer_flash(species=species, personality=personality,
                        serial=0xFFFFF, held_item=1023, friendship=231)
                    original = bytes(payload)
                    result = validate_party_offer(payload, 0xFFFFF)
                    self.assertEqual((result.serial, result.species, result.personality,
                        result.ot_id, result.held_item, result.friendship, result.slot),
                        (0xFFFFF, species, personality, 0xAABBCCDD, 1023, 231, 0))
                    self.assertEqual(result.checkpoint_sha256,
                        inspect_flash(payload, save_profile=OWNERSHIP_PROFILE).container_sha256)
                    self.assertEqual(payload, original)

    def test_either_native_egg_flag_is_refused_without_mutation(self):
        for header, secure in ((True, False), (False, True), (True, True)):
            with self.subTest(header=header, secure=secure):
                payload = offer_flash(header_egg=header, secure_egg=secure)
                self.assert_code("egg_unsupported", payload)
                self.assertEqual(payload, bytes(payload))

    def test_every_mail_item_and_local_mail_reference_is_refused(self):
        for item in range(199, 211):
            with self.subTest(item=item):
                self.assert_code("mail_unsupported", offer_flash(held_item=item))
        for mail in (0, 5, 15, 254):
            with self.subTest(mail=mail):
                self.assert_code("mail_unsupported", offer_flash(mail=mail))
        self.assertEqual(validate_party_offer(offer_flash(held_item=198), 1).held_item, 198)
        self.assertEqual(validate_party_offer(offer_flash(held_item=211), 1).held_item, 211)

    def test_trade_evolution_species_are_offered_like_any_other(self):
        # KNOWN_ISSUES MS-151: the exchange stays exact and the receiving game
        # evolves its new Pokemon itself. Independent audited table; the forms
        # (968, 1157-1159) stay outside the standard range.
        species = (61,64,67,75,79,93,95,112,117,123,125,126,137,233,349,
                   356,366,525,533,588,616,682,684,708,710)
        for value in species:
            for held_item in (0, 245, 441):  # No held item, Everstone, Metal Coat.
                with self.subTest(species=value, held_item=held_item):
                    result = validate_party_offer(offer_flash(species=value, held_item=held_item), 1)
                    self.assertEqual((result.species, result.held_item), (value, held_item))
        for value in (968, 1157, 1158, 1159):
            with self.subTest(species=value):
                self.assert_code("species_unsupported", offer_flash(species=value))

    def test_nonstandard_namespace_is_an_explicit_temporary_capability_limit(self):
        for species in (722, 871, 1104, 1105, 1487, 1572):
            with self.subTest(species=species):
                self.assert_code("species_unsupported", offer_flash(species=species))
        # Last Gen6 standard species is an explicit native enum ID, not a
        # broad allowance for later internal form IDs.
        self.assertEqual(validate_party_offer(offer_flash(species=721), 1).species, 721)

    def test_rotoms_reviewed_forms_are_exchanged_exactly(self):
        # The Rotom Catalog (2026-10-30): Rotom's five appliance forms (engine
        # SPECIES_ROTOM_HEAT 1064 .. SPECIES_ROTOM_MOW 1068) are offered as the
        # standard species are, the record unchanged; the forms on either side
        # of them, and every other form, stay outside.
        for value in (479, 1064, 1065, 1066, 1067, 1068):
            with self.subTest(species=value):
                payload = offer_flash(species=value, held_item=158)
                result = validate_party_offer(payload, 1)
                self.assertEqual((result.species, result.held_item), (value, 158))
        for value in (1063, 1069):
            with self.subTest(species=value):
                self.assert_code("species_unsupported", offer_flash(species=value))
        first, second = offer_flash(species=1064), offer_flash(species=1067, serial=2, personality=9)
        self.assertEqual(tuple(mon.species for mon in validate_trade_pair(first, 1, second, 2)), (1064, 1067))

    def test_full_parser_rejects_checksum_uid_and_party_corruption(self):
        payload = offer_flash()
        for offset, value in ((32, b"\x00"), (19, b"\x03"), (84, b"\x00")):
            changed = _rewrite(payload, 0, 1, SAVED_PARTY_OFFSET + offset, value)
            self.assert_code("invalid_checkpoint", changed)
        unowned = make_ownership_flash(records=(("party:0", 0),))
        self.assert_code("invalid_checkpoint", unowned)
        for invalid in (payload[:-1], bytearray(payload), b"", None):
            self.assert_code("invalid_checkpoint", invalid)

    def test_serial_and_current_party_location_are_strict(self):
        payload = offer_flash()
        for serial in (True, False, 0, -1, 0x100000, "1", 1.0, None):
            self.assert_code("invalid_serial", payload, serial)
        self.assert_code("party_required", payload, 2)
        for location in ("box:0:0", "daycare:0", "fusion:0"):
            data = make_ownership_flash(records=((location, 1),))
            self.assert_code("party_required", data)

    def test_pair_requires_two_eligible_independent_owners_in_one_world(self):
        a, b = offer_flash(), offer_flash(serial=33, species=252)
        pair = validate_trade_pair(a, 1, b, 33)
        self.assertNotEqual(pair[0].player_id, pair[1].player_id)
        self.assertEqual(pair[0].world_id, pair[1].world_id)
        for peer, serial, code in (
                (a,1,"invalid_pair"),
                (offer_flash(serial=1),1,"shared_identity"),
                (offer_flash(serial=33, secure_egg=True),33,"egg_unsupported")):
            with self.subTest(code=code), self.assertRaises(TradeEligibilityError) as caught:
                validate_trade_pair(a,1,peer,serial)
            self.assertEqual(caught.exception.code,code)
        foreign = make_ownership_flash(records=(("party:0", 33),),
            metadata=make_ownership_record(world_id=str(uuid4()), player_id=str(uuid4())))
        with self.assertRaises(TradeEligibilityError) as caught:
            validate_trade_pair(a,1,foreign,33)
        self.assertEqual(caught.exception.code,"invalid_pair")


if __name__ == "__main__":
    unittest.main()
