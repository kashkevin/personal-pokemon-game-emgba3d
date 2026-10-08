from __future__ import annotations

import struct
import unittest
from uuid import uuid4

from emerald_multiplayer.flash import inspect_flash
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE, inspect_ownership
from emerald_multiplayer.trade_flash import TradeFlashError, build_party_swap, validate_party_swap
from test_flash import _rewrite, _sector_offset, make_flash
from test_ownership import WORLD_ID, make_ownership_flash, make_ownership_record


class TradeFlashTests(unittest.TestCase):
    def sources(self, *, counter_a=2, counter_b=3, rtc=True, previous=True):
        a = make_ownership_flash(counter=counter_a,
            records=(("party:0", 1), ("party:1", 2), ("box:0:2", 3)),
            metadata=make_ownership_record(player_id=str(uuid4()), start=1,
                end_exclusive=33, next_serial=4), with_rtc=rtc, with_previous=previous)
        b = make_ownership_flash(counter=counter_b,
            records=(("party:0", 33), ("party:1", 34), ("daycare:0", 35)),
            metadata=make_ownership_record(player_id=str(uuid4()), start=33,
                end_exclusive=65, next_serial=36), personalities=(13, 17, 23),
            with_rtc=rtc, with_previous=previous)
        return a, b

    def test_exact_exchange_preserves_every_other_byte_and_identity(self):
        a, b = self.sources()
        after_a, after_b = build_party_swap(a, 2, b, 33)
        validate_party_swap(a, 2, b, 33, after_a, after_b)
        for before, after, index, incoming, outgoing in (
                (a, after_a, 1, b, 0), (b, after_b, 0, a, 1)):
            source = inspect_flash(before, save_profile=OWNERSHIP_PROFILE)
            peer = inspect_flash(incoming, save_profile=OWNERSHIP_PROFILE)
            parsed = inspect_flash(after, save_profile=OWNERSHIP_PROFILE)
            first = 0x238 + index * 100
            peer_first = 0x238 + outgoing * 100
            self.assertEqual(parsed.save_block1[first:first+100], peer.save_block1[peer_first:peer_first+100])
            # Expected allowed byte positions are independent of the production helper.
            sector = _sector_offset(before, source.metadata.bank, 1)
            allowed = set(range(sector+first, sector+first+100)) | {sector+4086, sector+4087}
            self.assertTrue(all(x == y or offset in allowed for offset,(x,y) in enumerate(zip(before,after))))
            self.assertEqual(len(before),len(after))
            self.assertEqual(source.save_block3,parsed.save_block3)
            self.assertEqual(source.metadata,parsed.metadata)
        self.assertEqual([r.serial for r in inspect_ownership(inspect_flash(after_a,save_profile=OWNERSHIP_PROFILE)).records],[1,33,3])
        self.assertEqual([r.serial for r in inspect_ownership(inspect_flash(after_b,save_profile=OWNERSHIP_PROFILE)).records],[2,34,35])
        self.assertEqual(build_party_swap(after_a,33,after_b,2),(a,b))

    def test_banks_counter_wrap_and_rtc_boundaries(self):
        for counter in (0,1,13,14,0xFFFFFFFF):
            for previous in (False,True):
                with self.subTest(counter=counter,previous=previous):
                    a,b=self.sources(counter_a=counter,counter_b=counter,rtc=False,previous=previous)
                    swapped=build_party_swap(a,1,b,34)
                    self.assertEqual(build_party_swap(swapped[0],34,swapped[1],1),(a,b))

    def test_post_image_mutations_in_unrelated_state_are_rejected(self):
        a,b=self.sources()
        post_a,post_b=build_party_swap(a,2,b,33)
        # Valid sector checksums do not authorize money/location/mail/flags changes.
        for section,offset in ((1,0),(1,0x490),(2,7),(0,20)):
            changed=_rewrite(post_a,0,section,offset,b'\x01')
            with self.subTest(section=section,offset=offset),self.assertRaises(TradeFlashError):
                validate_party_swap(a,2,b,33,changed,post_b)
        for offset in (-1,28*4096,14*4096+50):
            changed=bytearray(post_a);changed[offset]^=1
            with self.subTest(offset=offset),self.assertRaises(TradeFlashError):
                validate_party_swap(a,2,b,33,bytes(changed),post_b)
        with self.assertRaises(TradeFlashError):
            validate_party_swap(a,2,b,33,post_b,post_a)
        with self.assertRaises(TradeFlashError):
            validate_party_swap(a,2,b,33,bytearray(post_a),post_b)

    def test_reject_nonparty_absent_same_serial_and_invalid_inputs(self):
        a,b=self.sources()
        for serial in (True,0,-1,0x100000,'2',3,500):
            with self.subTest(serial=serial),self.assertRaises(TradeFlashError):
                build_party_swap(a,serial,b,33)
        for left,right in ((a,a),(a,make_flash()),(a,a[:-1])):
            with self.assertRaises(TradeFlashError):
                build_party_swap(left,1,right,2)
        with self.assertRaises(TradeFlashError):
            build_party_swap(a,1,b,1)

    def test_reject_foreign_world_same_player_or_shared_inventory(self):
        a,b=self.sources()
        player=inspect_ownership(inspect_flash(a,save_profile=OWNERSHIP_PROFILE)).player_id
        for world,peer,records in ((str(uuid4()),str(uuid4()),(("party:0",33),)),
                                  (WORLD_ID,player,(("party:0",33),)),
                                  (WORLD_ID,str(uuid4()),(("party:0",33),("box:0:0",1)))):
            b=make_ownership_flash(records=records,metadata=make_ownership_record(world_id=world,player_id=peer))
            with self.assertRaises(TradeFlashError):
                build_party_swap(a,1,b,33)

    def test_unconsumed_recipient_allocation_cannot_accept_incoming_id(self):
        a,b=self.sources()
        # Distinct worlds can have corrupt overlapping allocation metadata; a
        # store rejects that provenance, and this helper must not bypass parsing.
        b=make_ownership_flash(records=(("party:0",33),),metadata=make_ownership_record(
            player_id=str(uuid4()),start=1,end_exclusive=33,next_serial=1))
        with self.assertRaises(TradeFlashError):
            build_party_swap(a,1,b,33)


if __name__ == '__main__':
    unittest.main()
