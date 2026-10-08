"""Read-only canonical trainer/party material for development native battles.

The ROM transports its exact protected original six-slot party at startup.
Temporary native form changes and battle mutations must never be substituted
for these bytes when proving that both trainers use their acknowledged saves.
"""
from dataclasses import dataclass, field
import hashlib
import struct
import zlib

from .battle_mailbox import BattleMailboxError, _integer, _uuid
from .flash import SAVED_PARTY_OFFSET, inspect_flash
from .native_battle import Kind, Preparation, PHASE, player_count_for_phase
from .ownership import OWNERSHIP_PROFILE, inspect_ownership
from .protocol import MAX_COUNTER
from .storage import Checkpoint


def validate_auxiliary_startup(kind, data, *, issued_rng):
    """Validate the bounded header or the exact server-issued RNG block.

    The header contains only the native health display and Enigma Berry fields;
    it carries no address or independent party authority. Pokémon data still
    requires all three exact canonical party blocks.
    """
    if type(data) is not bytes or isinstance(kind, bool) or not isinstance(kind, int):
        raise BattleMailboxError("startup requires immutable typed bytes")
    if type(issued_rng) is not bytes or len(issued_rng) != 16 or not any(issued_rng):
        raise BattleMailboxError("startup requires the issued nonzero RNG state")
    if kind == Kind.RNG:
        if data != issued_rng:
            raise BattleMailboxError("native startup RNG differs from its issued state")
    elif kind == Kind.START_HEADER:
        # ARM LinkBattlerHeader32 / BattleEnigmaBerry28 from the pinned build.
        if len(data) != 32 or data[:2] != b"\0\x03" or data[3] & 0xF0 or data[11] >= 126 or data[31]:
            raise BattleMailboxError("native startup header has invalid fields")
        name = data[4:11]
        end = name.find(b"\xff")
        if end < 0 or any(value >= 252 for value in name[:end]):
            raise BattleMailboxError("native Enigma Berry name is invalid")
    else:
        raise BattleMailboxError("startup kind is not header/RNG")


@dataclass(frozen=True)
class CanonicalBattler:
    world_id: str
    player_id: str
    revision: int
    checkpoint_sha256: str
    source_slot: int
    native_counter: int
    trainer_id: int
    party_count: int
    party_crc32: int
    party: bytes = field(repr=False)
    trainer_descriptor: bytes = field(repr=False)
    mode: int = PHASE

    @classmethod
    def from_checkpoint(cls, checkpoint, *, world_id, build_id, ruleset_id, source_slot, mode=PHASE):
        """Validate immutable canonical bytes; current lease/head checks are separate."""
        if not isinstance(checkpoint, Checkpoint):
            raise BattleMailboxError("battle roster needs an acknowledged checkpoint")
        _uuid(world_id, "world")
        _uuid(checkpoint.player_id, "player")
        _integer(source_slot, 0, player_count_for_phase(mode)-1, "native source slot")
        _integer(checkpoint.revision, 1, MAX_COUNTER, "canonical revision")
        if (checkpoint.build_id != build_id or checkpoint.ruleset_id != ruleset_id
                or checkpoint.save_profile != OWNERSHIP_PROFILE
                or type(checkpoint.payload) is not bytes
                or hashlib.sha256(checkpoint.payload).hexdigest() != checkpoint.sha256):
            raise BattleMailboxError("canonical battle checkpoint identity/hash does not match the world")
        snapshot = inspect_flash(checkpoint.payload, save_profile=OWNERSHIP_PROFILE)
        owned = inspect_ownership(snapshot)
        if (owned.world_id, owned.player_id) != (world_id, checkpoint.player_id):
            raise BattleMailboxError("canonical battle checkpoint belongs to a different world/player")
        metadata = snapshot.metadata
        if not metadata.party_count:
            raise BattleMailboxError("native battle requires a nonempty owned party")
        party = snapshot.save_block1[SAVED_PARTY_OFFSET:SAVED_PARTY_OFFSET+600]
        # Pinned LinkPlayer layout: version0/u16, field2/u16, trainer4/u32,
        # name8/8B, progress16..18/zero, gender19/u8, linktype20/u32,
        # source24/u16, language26/u16. The compiled game language is English2.
        # Copy the whole original name including its actual trailing bytes.
        trainer = bytearray(28)
        struct.pack_into("<HHI", trainer, 0, 0x4003, 0, metadata.trainer_id)
        trainer[8:16] = snapshot.save_block2[:8]
        trainer[19] = metadata.gender
        struct.pack_into("<IHH", trainer, 20, 0x2211 if mode == PHASE else 0x2255, source_slot, 2)
        return cls(world_id, checkpoint.player_id, checkpoint.revision, checkpoint.sha256,
            source_slot, metadata.counter, metadata.trainer_id, metadata.party_count,
            zlib.crc32(party), party, bytes(trainer), mode)

    def preparation(self, rng):
        return Preparation(self.revision, self.native_counter, self.trainer_id,
                           self.party_crc32, rng)

    def verify_startup(self, kind, data):
        """Compare a complete trainer/party block, including unused party tails.

        HEADER, RNG and controller messages require their own validators. This
        method never treats their omission as successful canonical validation.
        """
        if type(data) is not bytes or isinstance(kind, bool) or not isinstance(kind, int):
            raise BattleMailboxError("startup block must contain immutable typed bytes")
        if kind == Kind.TRAINER:
            expected = self.trainer_descriptor
        elif kind in (Kind.PARTY_0, Kind.PARTY_1, Kind.PARTY_2):
            offset = (kind-Kind.PARTY_0)*200
            expected = self.party[offset:offset+200]
        else:
            raise BattleMailboxError("block kind has no canonical trainer/party comparison")
        if data != expected:
            raise BattleMailboxError("native startup differs from the acknowledged trainer/party")
        return self
