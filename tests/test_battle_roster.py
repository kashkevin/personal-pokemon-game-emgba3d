from dataclasses import replace
import hashlib
import struct
import unittest
from uuid import UUID
import zlib

from emerald_multiplayer.battle_mailbox import BattleMailboxError
from emerald_multiplayer.battle_roster import CanonicalBattler, validate_auxiliary_startup
from emerald_multiplayer.flash import FlashError, inspect_flash
from emerald_multiplayer.native_battle import Kind
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE
from emerald_multiplayer.storage import Checkpoint
from test_ownership import make_ownership_flash, WORLD_ID, PLAYER_ID


class CanonicalBattleRosterTests(unittest.TestCase):
    def setUp(self):
        self.payload = make_ownership_flash(records=(("party:0", 1), ("party:1", 2), ("box:0:0", 3)))
        self.checkpoint = Checkpoint(PLAYER_ID, 3, str(UUID(int=123)), self.payload,
            hashlib.sha256(self.payload).hexdigest(), "test-build", "test-rules", OWNERSHIP_PROFILE)

    def roster(self, checkpoint=None, **kwargs):
        return CanonicalBattler.from_checkpoint(checkpoint or self.checkpoint,
            **{**dict(world_id=WORLD_ID, build_id="test-build", ruleset_id="test-rules", source_slot=0), **kwargs})

    def test_exact_six_slot_party_descriptor_and_native_preparation(self):
        before = hashlib.sha256(self.payload).hexdigest()
        for source in (0, 1):
            roster = self.roster(source_slot=source)
            snap = inspect_flash(self.payload, save_profile=OWNERSHIP_PROFILE)
            self.assertEqual(roster.party_count, 2)
            self.assertEqual(len(roster.party), 600)
            self.assertEqual(roster.party, snap.save_block1[0x238:0x490])
            self.assertEqual(roster.party_crc32, zlib.crc32(roster.party))
            self.assertEqual(struct.unpack_from("<HHI", roster.trainer_descriptor),
                             (0x4003, 0, snap.metadata.trainer_id))
            self.assertEqual(roster.trainer_descriptor[8:16], snap.save_block2[:8])
            self.assertEqual(roster.trainer_descriptor[16:19], bytes(3))
            self.assertEqual(struct.unpack_from("<IHH", roster.trainer_descriptor, 20), (0x2211, source, 2))
            prep = roster.preparation(bytes(range(16)))
            self.assertEqual((prep.checkpoint_revision, prep.native_counter, prep.trainer_id, prep.party_crc32),
                             (3, snap.metadata.counter, snap.metadata.trainer_id, zlib.crc32(roster.party)))
        self.assertEqual(hashlib.sha256(self.payload).hexdigest(), before)

    def test_requires_exact_world_player_build_rules_profile_and_payload_hash(self):
        for changed in (dict(world_id=str(UUID(int=54))), dict(build_id="wrong"),
                        dict(ruleset_id="wrong"), dict(source_slot=2), dict(source_slot=True)):
            with self.subTest(changed=changed), self.assertRaises((ValueError, FlashError)):
                self.roster(**changed)
        for changed in (dict(player_id=str(UUID(int=99))), dict(revision=0), dict(revision=True),
                        dict(save_profile="legacy"), dict(sha256="0"*64),
                        dict(payload=self.payload[:-1]+b"x")):
            with self.subTest(changed=changed), self.assertRaises((ValueError, FlashError)):
                self.roster(replace(self.checkpoint, **changed))

    def test_complete_startup_compares_all_original_bytes_including_empty_slots(self):
        roster = self.roster()
        blocks = ((Kind.TRAINER, roster.trainer_descriptor),
                  *((Kind.PARTY_0+i, roster.party[i*200:(i+1)*200]) for i in range(3)))
        for kind, data in blocks:
            self.assertIs(roster.verify_startup(kind, data), roster)
            for changed in (data[:-1], data+b"x", data[:-1]+bytes((data[-1]^1,))):
                with self.subTest(kind=kind), self.assertRaises(BattleMailboxError):
                    roster.verify_startup(kind, changed)
        for kind in (Kind.START_HEADER, Kind.RNG, Kind.CONTROLLER, True):
            with self.assertRaises(BattleMailboxError):
                roster.verify_startup(kind, bytes(16))

    def test_peer_descriptor_cannot_impersonate_local_slot(self):
        local, remote = self.roster(source_slot=0), self.roster(source_slot=1)
        with self.assertRaises(BattleMailboxError):
            local.verify_startup(Kind.TRAINER, remote.trainer_descriptor)
        self.assertEqual(local.party, remote.party)

    def test_auxiliary_startup_uses_exact_rng_and_bounded_nonpointer_header(self):
        rng = bytes(range(16))
        header = bytearray(32)
        header[1], header[4], header[11] = 3, 255, 125
        validate_auxiliary_startup(Kind.START_HEADER, bytes(header), issued_rng=rng)
        validate_auxiliary_startup(Kind.RNG, rng, issued_rng=rng)
        for offset, value in ((0, 1), (1, 4), (3, 16), (4, 252), (11, 126), (31, 1)):
            malformed = bytearray(header)
            malformed[offset] = value
            with self.subTest(offset=offset), self.assertRaises(BattleMailboxError):
                validate_auxiliary_startup(Kind.START_HEADER, bytes(malformed), issued_rng=rng)
        for kind, data, issued in ((Kind.RNG, bytes(16), rng), (Kind.RNG, rng[:-1], rng),
                                   (Kind.RNG, rng, bytes(16)), (Kind.CONTROLLER, rng, rng),
                                   (Kind.START_HEADER, bytes(header[:-1]), rng)):
            with self.assertRaises(BattleMailboxError):
                validate_auxiliary_startup(kind, data, issued_rng=issued)


if __name__ == "__main__":
    unittest.main()
