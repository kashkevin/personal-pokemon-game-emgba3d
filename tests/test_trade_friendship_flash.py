from dataclasses import replace
import hashlib
import struct
import unittest
from uuid import uuid4

from emerald_multiplayer.flash import inspect_flash
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE, inspect_ownership
from emerald_multiplayer.protocol import MAX_COUNTER
from emerald_multiplayer.storage import Checkpoint
from emerald_multiplayer.trade_flash import TradeFlashError, validate_party_swap
from emerald_multiplayer.trade_friendship import FriendshipHistory
from emerald_multiplayer.trade_friendship_flash import (
    FriendshipOfferPlan, build_friendship_pair, validate_friendship_pair,
)
from test_flash import _rewrite, _sector_offset
import test_trade_flash as flash_fixtures
from test_trade_friendship import ALICE, BOB, decode_fixture, encode_fixture, make_friendship_mon


class FriendshipFlashTests(unittest.TestCase):
    def sources(self, *, counter=2, previous=True, rtc=True, species=(265, 265)):
        payloads = flash_fixtures.TradeFlashTests().sources(counter_a=counter, counter_b=counter,
                                                          rtc=rtc, previous=previous)
        checkpoints, plans = [], []
        for index, (payload, trainer, serial) in enumerate(zip(payloads, (ALICE, BOB), (2, 33))):
            snapshot = inspect_flash(payload, save_profile=OWNERSHIP_PROFILE)
            bank = snapshot.metadata.bank
            # Both valid banks retain the same character identity, including
            # counter wrap cases. Only the current offered party is replaced.
            for identity_bank in ((0, 1) if previous else (bank,)):
                payload = _rewrite(payload, identity_bank, 0, 0, trainer.name + bytes([255])*(8-len(trainer.name)))
                payload = _rewrite(payload, identity_bank, 0, 8, bytes([trainer.gender]))
                payload = _rewrite(payload, identity_bank, 0, 10, struct.pack("<I", trainer.trainer_id))
            mon = make_friendship_mon(7 if index == 0 else 13, serial=serial,
                                      friendship=215 if index == 0 else 160,
                                      moves=(33, 45, 0, 0) if index == 0 else (33, 45, 0, 218))
            logical = decode_fixture(mon)
            struct.pack_into("<H", logical[0], 0, species[index])
            changed = bytearray(mon)
            struct.pack_into("<I", changed, 4, trainer.trainer_id)
            changed[20:27] = trainer.name + bytes([255])*(7-len(trainer.name))
            struct.pack_into("<H", logical[3], 2, trainer.gender << 15 | trainer.version << 7 | 5)
            mon = encode_fixture(changed, logical)
            payload = _rewrite(payload, bank, 1, 0x238 + (100 if index == 0 else 0), mon)
            owner = inspect_ownership(inspect_flash(payload, save_profile=OWNERSHIP_PROFILE))
            checkpoints.append(Checkpoint(owner.player_id, 5+index, str(uuid4()), payload,
                hashlib.sha256(payload).hexdigest(), "friendship-native-build", "gen6-pending-profile", OWNERSHIP_PROFILE))
            history = FriendshipHistory(serial, trainer, 200, None, 0, 0)
            plans.append(FriendshipOfferPlan(history, False))
        return checkpoints[0], plans[0], checkpoints[1], plans[1]

    def test_exact_paired_changes_and_recipient_identities_come_from_canonical_flash(self):
        a, pa, b, pb = self.sources()
        result = build_friendship_pair(a, pa, b, pb, profile_game_version=3)
        self.assertEqual(result.offered_a.friendship, 70)
        self.assertEqual(result.offered_b.friendship, 160)
        self.assertEqual(result.offered_a.history.handler, BOB)
        self.assertEqual(result.offered_b.history.handler, ALICE)
        self.assertEqual(result.offered_a.history.original_friendship, 215)
        for cp, post, slot in ((a, result.after_a, 1), (b, result.after_b, 0)):
            snapshot = inspect_flash(cp.payload, save_profile=OWNERSHIP_PROFILE)
            after = inspect_flash(post, save_profile=OWNERSHIP_PROFILE)
            self.assertEqual(snapshot.metadata, after.metadata)
            self.assertEqual(snapshot.save_block2, after.save_block2)
            self.assertEqual(snapshot.save_block3, after.save_block3)
            sector = _sector_offset(cp.payload, snapshot.metadata.bank, 1)
            start = sector + 0x238 + slot*100
            allowed = set(range(start, start+100)) | {sector+4086, sector+4087}
            self.assertTrue(all(left == right or i in allowed for i, (left, right) in enumerate(zip(cp.payload, post))))
            self.assertEqual(len(cp.payload), len(post))
        self.assertEqual(validate_friendship_pair(a, pa, b, pb, result.after_a, result.after_b,
                                                  profile_game_version=3), result)
        # Existing production validation still rejects friendship side effects.
        with self.assertRaises(TradeFlashError):
            validate_party_swap(a.payload, 2, b.payload, 33, result.after_a, result.after_b)

    def test_repeat_is_exact_and_input_digest_binds_envelope_history_and_policy(self):
        a, pa, b, pb = self.sources()
        original = build_friendship_pair(a, pa, b, pb, profile_game_version=3)
        self.assertEqual(build_friendship_pair(a, pa, b, pb, profile_game_version=3), original)
        for ca, plan, version in (
            (replace(a, revision=10), pa, 3), (replace(a, request_id=str(uuid4())), pa, 3),
            (a, replace(pa, history=replace(pa.history, original_friendship=199)), 3),
            (a, replace(pa, refresh_handler=True), 3),
            (a, pa, 4),
        ):
            with self.subTest(revision=ca.revision, plan=plan, version=version):
                changed = build_friendship_pair(ca, plan, b, pb, profile_game_version=version)
                self.assertNotEqual(changed.input_sha256, original.input_sha256)
                self.assertNotEqual(changed.outcome_sha256, original.outcome_sha256)

    def test_full_postimage_validator_refuses_unrelated_changes_and_partial_pair(self):
        a, pa, b, pb = self.sources()
        result = build_friendship_pair(a, pa, b, pb, profile_game_version=3)
        bank = inspect_flash(result.after_a, save_profile=OWNERSHIP_PROFILE).metadata.bank
        for section, offset in ((1, 0), (1, 0x490), (2, 7), (0, 20)):
            changed = _rewrite(result.after_a, bank, section, offset, b"\x01")
            with self.subTest(section=section, offset=offset), self.assertRaises(TradeFlashError):
                validate_friendship_pair(a, pa, b, pb, changed, result.after_b, profile_game_version=3)
        for offset in (-1, 28*4096, (1-bank)*14*4096+50):
            changed = bytearray(result.after_a)
            changed[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaises(TradeFlashError):
                validate_friendship_pair(a, pa, b, pb, bytes(changed), result.after_b, profile_game_version=3)
        for left, right in ((result.after_a, b.payload), (result.after_b, result.after_a),
                            (bytearray(result.after_a), result.after_b)):
            with self.assertRaises(TradeFlashError):
                validate_friendship_pair(a, pa, b, pb, left, right, profile_game_version=3)

    def test_foreign_stale_or_untrusted_envelopes_and_histories_refuse(self):
        a, pa, b, pb = self.sources()
        for changed in (replace(a, sha256="0"*64), replace(a, player_id=b.player_id),
                        replace(a, revision=True), replace(a, revision=0), replace(a, revision=MAX_COUNTER),
                        replace(a, build_id="another-build"), replace(a, ruleset_id="another-ruleset"),
                        replace(a, save_profile="legacy"), replace(a, request_id="not-a-uuid"),
                        replace(a, payload=bytearray(a.payload))):
            with self.subTest(changed=changed), self.assertRaises(TradeFlashError):
                build_friendship_pair(changed, pa, b, pb, profile_game_version=3)
        for changed in (replace(pa, history=replace(pa.history, known=False)),
                        replace(pa, history=replace(pa.history, serial=33)),
                        replace(pa, history=replace(pa.history, original=BOB)),
                        replace(pa, refresh_handler=None)):
            with self.subTest(changed=changed), self.assertRaises(TradeFlashError):
                build_friendship_pair(a, changed, b, pb, profile_game_version=3)
        for version in (True, -1, 16, None):
            with self.subTest(version=version), self.assertRaises(TradeFlashError):
                build_friendship_pair(a, pa, b, pb, profile_game_version=version)

    def test_species_base_is_derived_from_each_exact_offered_record(self):
        # Gen6 Buneary starts at 0; Buneary and Zubat share neither a base nor
        # an implicit handler value. Return still preserves the offered 160.
        a, pa, b, pb = self.sources(species=(427, 41))
        result = build_friendship_pair(a, pa, b, pb, profile_game_version=3)
        self.assertEqual(result.offered_a.friendship, 0)
        self.assertEqual(result.offered_b.friendship, 160)
        recipient = inspect_flash(result.after_b, save_profile=OWNERSHIP_PROFILE)
        self.assertEqual(decode_fixture(recipient.save_block1[0x238:0x238+100])[0][9], 0)
        with self.assertRaises(TypeError):
            FriendshipOfferPlan(pa.history, False, base_friendship=255)
        with self.assertRaises(TypeError):
            replace(pa, base_friendship=255)

    def test_preserves_bank_rotation_counter_wrap_previous_bank_and_rtc(self):
        for counter in (0, 1, 13, 14, 0xFFFFFFFF):
            for previous in (False, True):
                with self.subTest(counter=counter, previous=previous):
                    a, pa, b, pb = self.sources(counter=counter, previous=previous, rtc=False)
                    result = build_friendship_pair(a, pa, b, pb, profile_game_version=3)
                    validate_friendship_pair(a, pa, b, pb, result.after_a, result.after_b, profile_game_version=3)


if __name__ == "__main__":
    unittest.main()
