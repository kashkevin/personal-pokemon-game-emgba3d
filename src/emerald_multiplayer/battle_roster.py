"""Read-only canonical trainer/party material for development native battles.

The ROM transports its exact protected original six-slot party at startup.
Temporary native form changes and battle mutations must never be substituted
for these bytes when proving that both trainers use their acknowledged saves.
"""
from dataclasses import dataclass, field, replace
import hashlib
import struct
import zlib

from .battle_mailbox import BattleMailboxError, _integer, _uuid
from .flash import SAVED_PARTY_OFFSET, inspect_flash
from .native_battle import COOP_PHASE, Kind, Preparation, PHASE, MULTI_PHASE, FFA_PHASE, player_count_for_phase
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


POKEMON_SIZE = 100
BRING_FLAG = 0x80          # the last byte of a co-op preparation's seed: 0x80 | slot mask, or 0 for the whole party


def valid_bring(mask, party: bytes, party_count: int) -> bool:
    """A team selection (bit n = saved party slot n) the game will accept: existing, non-Egg Pokemon, one able to fight."""
    if type(mask) is not int or isinstance(mask, bool) or not 1 <= mask <= 0x3F or len(party) != 6 * POKEMON_SIZE:
        return False
    able = False
    for slot in range(6):
        if not mask >> slot & 1:
            continue
        mon = party[slot * POKEMON_SIZE:(slot + 1) * POKEMON_SIZE]
        if slot >= party_count or not mon[19] & 2 or mon[19] & 4:      # hasSpecies / isEgg
            return False
        able = able or struct.unpack_from("<H", mon, 86)[0] > 0
    return able


def bring_party(party: bytes, mask: int) -> bytes:
    """The battle party for a selection: the chosen Pokemon in saved order, the other slots empty (as the game builds it)."""
    chosen = [party[slot * POKEMON_SIZE:(slot + 1) * POKEMON_SIZE] for slot in range(6) if mask >> slot & 1]
    return b"".join(chosen) + bytes(POKEMON_SIZE * (6 - len(chosen)))


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
    bring: int = 0     # co-op team selection (valid_bring); 0 = the whole saved party

    @classmethod
    def from_checkpoint(cls, checkpoint, *, world_id, build_id, ruleset_id, source_slot, mode=PHASE, bring=0):
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
        # LINKTYPE_MULTI_BATTLE only for four linked trainers; singles and
        # co-op Gym battles (two linked trainers) use LINKTYPE_BATTLE.
        struct.pack_into("<IHH", trainer, 20, 0x2255 if mode in (MULTI_PHASE, FFA_PHASE) else 0x2211, source_slot, 2)
        if bring and (mode != COOP_PHASE or not valid_bring(bring, party, metadata.party_count)):
            raise BattleMailboxError("team selection is not valid for this party")
        return cls(world_id, checkpoint.player_id, checkpoint.revision, checkpoint.sha256,
            source_slot, metadata.counter, metadata.trainer_id, metadata.party_count,
            zlib.crc32(party), party, bytes(trainer), mode, bring)

    @property
    def battle_party(self) -> bytes:
        """The party the battle really uses: the saved party, or the selection of it (co-op team selection)."""
        return bring_party(self.party, self.bring) if self.bring else self.party

    def issued_rng(self, rng):
        """The seed every core installs. A co-op preparation's last byte carries the team selection, not the seed."""
        return rng[:15] + b"\0" if self.mode == COOP_PHASE else rng

    def preparation(self, rng, gym=0):
        """``gym`` is the co-op Gym index for phase 4 (zero otherwise). A co-op preparation carries the team selection in
        the last byte of its seed (the game reads and clears it; nothing else uses that byte)."""
        if self.mode == COOP_PHASE:
            rng = rng[:15] + bytes([BRING_FLAG | self.bring if self.bring else 0])
        return Preparation(self.revision, self.native_counter, self.trainer_id,
                           self.party_crc32, rng, gym)

    def adopting(self, preparation):
        """This party with the team selection a (host-issued) co-op preparation carries, when it is valid for it."""
        if self.mode != COOP_PHASE:
            return self
        byte = preparation.rng[15]
        if byte == 0:
            return replace(self, bring=0)
        mask = byte & 0x3F
        if not byte & BRING_FLAG or byte & 0x40 or not valid_bring(mask, self.party, self.party_count):
            raise BattleMailboxError("native preparation carries an invalid team selection")
        return replace(self, bring=mask)

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
            expected = self.battle_party[offset:offset+200]
        else:
            raise BattleMailboxError("block kind has no canonical trainer/party comparison")
        if data != expected:
            raise BattleMailboxError("native startup differs from the acknowledged trainer/party")
        return self
