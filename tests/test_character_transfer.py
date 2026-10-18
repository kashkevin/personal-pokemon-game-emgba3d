from __future__ import annotations

import hashlib
import unittest

import struct

from emerald_multiplayer.character_transfer import (
    CATCH_VARS, WALLET_AMOUNT_HI, WALLET_AMOUNT_LO, WALLET_SEQ, TransferError, _var_offset, detach_from_world, world_vars,
)
from emerald_multiplayer.flash import LAYOUT_ID, OWNERSHIP_LAYOUT_ID, FlashError, inspect_flash
from emerald_multiplayer.ownership import extract_source_inventory, inspect_ownership
from test_flash import _rewrite
from test_ownership import make_ownership_flash

RECORDS = (("party:0", 1), ("party:1", 2), ("box:3:14", 27), ("box:13:29", 400), ("daycare:1", 55), ("fusion:2", 100))


class DetachTests(unittest.TestCase):
    def test_world_identities_are_removed_and_every_pokemon_keeps_its_content(self):
        owned = make_ownership_flash(records=RECORDS, with_rtc=True)
        before = inspect_ownership(inspect_flash(owned, save_profile=OWNERSHIP_LAYOUT_ID))
        detached = detach_from_world(owned)
        source = extract_source_inventory(inspect_flash(detached.payload, save_profile=LAYOUT_ID))
        self.assertEqual([r.serial for r in source], [0] * len(RECORDS))
        self.assertEqual(sorted((r.location, r.content_sha256, r.personality, r.ot_id, r.species) for r in source),
                         sorted((r.location, r.content_sha256, r.personality, r.ot_id, r.species) for r in before.records))
        self.assertEqual(detached.pokemon, len(RECORDS))
        self.assertEqual(detached.source_world_id, before.world_id)
        self.assertEqual(detached.sha256, hashlib.sha256(detached.payload).hexdigest())
        self.assertEqual(detached.payload[131072:], owned[131072:])          # the clock footer is kept
        with self.assertRaises(FlashError):                                    # it no longer belongs to any world
            inspect_ownership(inspect_flash(detached.payload, save_profile=OWNERSHIP_LAYOUT_ID))

    def test_only_the_newest_bank_is_kept(self):
        owned = make_ownership_flash(records=RECORDS)
        detached = detach_from_world(owned).payload
        old = inspect_flash(owned, save_profile=OWNERSHIP_LAYOUT_ID).metadata
        new = inspect_flash(detached, save_profile=LAYOUT_ID).metadata
        self.assertEqual((old.counter, old.bank, old.trainer_id, old.name), (new.counter, new.bank, new.trainer_id, new.name))
        other = 1 - new.bank
        self.assertEqual(detached[other * 14 * 4096:(other + 1) * 14 * 4096], b"\xff" * 14 * 4096)

    def test_a_save_with_no_world_is_returned_unchanged(self):
        owned = make_ownership_flash(records=RECORDS)
        once = detach_from_world(owned)
        twice = detach_from_world(once.payload)
        self.assertEqual(twice.payload, once.payload)
        self.assertIsNone(twice.source_world_id)

    def test_every_substructure_order_round_trips(self):
        for personality in range(24):
            owned = make_ownership_flash(records=(("party:0", 0x80001 + personality),), personalities=(personality,))
            before = inspect_ownership(inspect_flash(owned, save_profile=OWNERSHIP_LAYOUT_ID)).records[0]
            after = extract_source_inventory(inspect_flash(detach_from_world(owned).payload, save_profile=LAYOUT_ID))[0]
            self.assertEqual((after.serial, after.content_sha256), (0, before.content_sha256), personality)

    def test_the_old_worlds_catch_record_and_wallet_are_reset_for_the_new_world(self):
        owned = make_ownership_flash(records=RECORDS)            # counter 2: the newest bank is bank 0
        for var, value in zip(CATCH_VARS + (WALLET_SEQ, WALLET_AMOUNT_LO, WALLET_AMOUNT_HI), (3, 0, 25, 0x1234, 0x5678, 9, 500, 1)):
            offset = _var_offset(var)                            # SaveBlock1 starts in section 1 (3968 bytes each)
            owned = _rewrite(owned, 0, 1 + offset // 3968, offset % 3968, struct.pack("<H", value))
        self.assertEqual(world_vars(owned)["catch"], (3, 0, 25, 0x1234, 0x5678))
        for wallet in (0, 12):
            detached = detach_from_world(owned, wallet_seq=wallet).payload
            self.assertEqual(world_vars(detached), dict(catch=(0, 0, 0, 0, 0), wallet_seq=wallet, wallet_amount=(0, 0)))
        again = detach_from_world(detach_from_world(owned).payload, wallet_seq=40)      # a legacy save entering another world
        self.assertEqual(world_vars(again.payload)["wallet_seq"], 40)
        with self.assertRaises(TransferError):
            detach_from_world(owned, wallet_seq=70000)

    def test_damaged_saves_are_refused(self):
        owned = bytearray(make_ownership_flash(records=RECORDS))
        owned[5000] ^= 0xFF
        with self.assertRaises(TransferError) as caught:
            detach_from_world(bytes(owned))
        self.assertEqual(caught.exception.code, "unreadable_save")
        with self.assertRaises(TransferError):
            detach_from_world(b"not a save")


if __name__ == "__main__":
    unittest.main()
