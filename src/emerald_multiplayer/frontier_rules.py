"""Frontier-style entry rules for Championships (expansion Phase 8).

An optional host setting, off unless the world has a `<world>.frontier.json`
file next to it. When on, a rotating rule decides which parties may enter a
Championship, the way the Battle Frontier limits what a challenger brings:

  open            no limit
  species_clause  no two Pokemon of one species
  item_clause     no two Pokemon holding the same item
  level_50        no Pokemon above level 50
  level_30        no Pokemon above level 30
  no_legendaries  no legendary or mythical Pokemon (Kanto to Kalos)

Rules only admit or refuse a party from the host's last saved checkpoint, so
they change no battle mechanic (Gen 6 rules are untouched). Eggs never count.
Which rule applies follows the world's clock: one entry of `rotation` per
`day_seconds` of world time, or `fixed` always. File format (all keys optional):

  {"enabled": true, "rotation": ["open", "level_50", ...], "day_seconds": 86400, "fixed": "level_50"}
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import struct

from .flash import POKEMON_SIZE, SAVED_PARTY_COUNT_OFFSET, SAVED_PARTY_OFFSET, _GROWTH_SUBSTRUCT_OFFSETS

LEGENDARY = frozenset(
    {144, 145, 146, 150, 151, 243, 244, 245, 249, 250, 251}
    | set(range(377, 387)) | set(range(480, 495)) | set(range(638, 650)) | {716, 717, 718, 719, 720, 721})
LEVEL_RULES = {"level_50": 50, "level_30": 30}
RULE_NAMES = {"open": "Open", "species_clause": "Species Clause", "item_clause": "Item Clause",
              "level_50": "Level 50", "level_30": "Level 30", "no_legendaries": "No Legendaries"}
DEFAULT_ROTATION = ("open", "level_50", "species_clause", "no_legendaries", "level_30", "item_clause")


class FrontierRuleError(ValueError):
    pass


@dataclass(frozen=True)
class PartyMember:
    species: int
    level: int
    item: int


def party_members(save_block1: bytes) -> list[PartyMember]:
    """The non-egg Pokemon of a validated saved party (flash.inspect_flash has
    already checked checksums and occupancy; this only reads, never writes)."""
    count = save_block1[SAVED_PARTY_COUNT_OFFSET]
    members = []
    for slot in range(min(count, 6)):
        mon = save_block1[SAVED_PARTY_OFFSET + slot * POKEMON_SIZE:SAVED_PARTY_OFFSET + (slot + 1) * POKEMON_SIZE]
        personality, ot_id = struct.unpack_from("<II", mon)
        if mon[19] & 4:  # egg
            continue
        key = personality ^ ot_id
        words = struct.unpack_from("<12I", mon, 32)
        growth = struct.pack("<3I", *(word ^ key for word in words[
            _GROWTH_SUBSTRUCT_OFFSETS[personality % 24] * 3:_GROWTH_SUBSTRUCT_OFFSETS[personality % 24] * 3 + 3]))
        species = struct.unpack_from("<H", growth)[0] & 0x7FF
        item = struct.unpack_from("<H", growth, 2)[0] & 0x3FF
        members.append(PartyMember(species, mon[84], item))
    return members


def check_party(rule: str, members: list[PartyMember]) -> str | None:
    """None when the party may enter under `rule`, else the reason (<= 21 characters)."""
    if rule not in RULE_NAMES:
        raise FrontierRuleError("unknown Frontier rule")
    if rule == "open":
        return None
    if not members:
        return "Has no Pokemon"
    if rule in LEVEL_RULES:
        cap = LEVEL_RULES[rule]
        return None if all(m.level <= cap for m in members) else f"Over level {cap}"
    if rule == "species_clause":
        species = [m.species for m in members]
        return None if len(set(species)) == len(species) else "Same species twice"
    if rule == "item_clause":
        items = [m.item for m in members if m.item]
        return None if len(set(items)) == len(items) else "Same item twice"
    return None if not any(m.species in LEGENDARY for m in members) else "Legendary not allowed"


@dataclass(frozen=True)
class FrontierSettings:
    enabled: bool = False
    rotation: tuple[str, ...] = DEFAULT_ROTATION
    day_seconds: int = 86_400
    fixed: str | None = None

    @classmethod
    def load(cls, path) -> "FrontierSettings":
        path = Path(path)
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise FrontierRuleError(f"{path.name} is not valid JSON") from error
        if not isinstance(raw, dict) or set(raw) - {"enabled", "rotation", "day_seconds", "fixed"}:
            raise FrontierRuleError(f"{path.name} has unknown settings")
        rotation = tuple(raw.get("rotation", DEFAULT_ROTATION))
        fixed = raw.get("fixed")
        day = raw.get("day_seconds", 86_400)
        if (type(raw.get("enabled", True)) is not bool or not rotation or any(r not in RULE_NAMES for r in rotation)
                or (fixed is not None and fixed not in RULE_NAMES) or type(day) is not int or not 60 <= day <= 31 * 86_400):
            raise FrontierRuleError(f"{path.name} has an invalid Frontier setting")
        return cls(raw.get("enabled", True), rotation, day, fixed)

    def rule_at(self, world_seconds: int) -> str:
        if self.fixed is not None:
            return self.fixed
        return self.rotation[(max(0, world_seconds) // self.day_seconds) % len(self.rotation)]
