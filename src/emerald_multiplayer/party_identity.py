"""KNOWN_ISSUES MS-60: a native battle starts only from the canonical save its challenge names.

The host prepares every native battle from each trainer's canonical checkpoint (its save counter, trainer id and party
CRC: battle_roster.CanonicalBattler), and the game's PREPARE refuses a preparation those do not match
(multiplayer_battle.c). Entered with a party changed since its last host save (a wild battle, an item, a Pokemon caught,
the game's own SAVE), a battle used to leave every trainer held with saving stopped, and its abandonment started the
games again from their host saves - the unsaved progress lost (L ms60-pvp-2, 2026-10-22). A PC game answers QUERY_PARTY
with what PREPARE will compare; the trainer's launcher names it in its claim (Enter battle), and the host turns a game
that differs away there, before anything is held (battle_admission_host.claim).
"""
from __future__ import annotations

from dataclasses import dataclass
import struct

FIELDS = ("save_counter", "battle_counter", "trainer_id", "party_count", "party_crc32")
SIZE = 20  # QUERY_PARTY's response: five little-endian words, in FIELDS' order


@dataclass(frozen=True)
class PartyIdentity:
    save_counter: int
    battle_counter: int  # the counter PREPARE also takes right after a trade's import; else save_counter
    trainer_id: int
    party_count: int
    party_crc32: int     # CRC32 of the player's whole party (600 bytes), as a save holds it

    def __post_init__(self):
        for name in FIELDS:
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
                raise ValueError(f"party identity {name} is not a 32-bit word")
        if not 1 <= self.party_count <= 6:
            raise ValueError("a party identity names 1-6 Pokemon")

    @classmethod
    def unpack(cls, data: bytes) -> PartyIdentity:
        if not isinstance(data, bytes) or len(data) != SIZE:
            raise ValueError(f"a party identity is {SIZE} bytes")
        return cls(*struct.unpack("<5I", data))

    @classmethod
    def from_request(cls, value) -> PartyIdentity:
        """A claim's `live` field (battle_protocol validates its shape; this its values)."""
        if type(value) is not dict or set(value) != set(FIELDS):
            raise ValueError("a party identity names exactly its five fields")
        return cls(**value)

    def as_request(self) -> dict:
        return {name: getattr(self, name) for name in FIELDS}

    def matches(self, roster) -> bool:
        """Whether PREPARE will take a preparation built from `roster` (a CanonicalBattler): its save counter (or,
        right after a trade's import, the counter that image names), its trainer id and its whole party's CRC."""
        return (roster.native_counter in (self.save_counter, self.battle_counter)
                and roster.trainer_id == self.trainer_id and roster.party_crc32 == self.party_crc32)
