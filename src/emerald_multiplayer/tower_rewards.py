"""Battle Tower: Legends prizes, Battle Points, money and the Tower Shop (docs/battle-tower-legends.md sections 4 and 5).

Item ids are the engine's (include/constants/items.h, the pokeemerald-expansion numbering; every one below was checked
there: Bottle Cap 133, Gold Bottle Cap 134, Ability Capsule 79, Ability Patch 80, Rare Candy 102, PP Up 71, PP Max 72, the
vitamins 65-70, Choice Band/Specs/Scarf 442-444, Expert Belt 477, Life Orb 479, Focus Sash 481, Rocky Helmet 496, Weakness
Policy 502, Assault Vest 503, Leftovers 472, Lum Berry 522, Sitrus Berry 523; none had to be left out). Battle Points
are the save's own ``frontier.battlePoints``, shared with the Battle Frontier and the co-op Battle Frontier (at most 9,999).

Prize floors and their claim bits (the save record's ``claims``, reward kind 6 op 1): bits 0-11 the prize of floors 10, 20,
25, 30, 40, 50, 60, 70, 75, 80, 90 and 100 claimed; bits 12-15 the milestone Pokemon of 25, 50, 75 and 100 delivered.
Prices and amounts are the owner's (design section 4 and the request of 2026-10-21). Only a floor's first clear pays
(the owner's request of 2026-10-22): a floor already cleared - a replay, a re-climb after a loss, a Duo partner's lower
floor - pays nothing again (tower_rules.win_reward).
"""
from __future__ import annotations

from typing import NamedTuple

# engine item ids (include/constants/items.h)
ITEM_HP_UP = 65
ITEM_PROTEIN = 66
ITEM_IRON = 67
ITEM_CALCIUM = 68
ITEM_ZINC = 69
ITEM_CARBOS = 70
ITEM_PP_UP = 71
ITEM_PP_MAX = 72
ITEM_ABILITY_CAPSULE = 79
ITEM_ABILITY_PATCH = 80
ITEM_RARE_CANDY = 102
ITEM_BOTTLE_CAP = 133
ITEM_GOLD_BOTTLE_CAP = 134
ITEM_CHOICE_BAND = 442
ITEM_CHOICE_SPECS = 443
ITEM_CHOICE_SCARF = 444
ITEM_LEFTOVERS = 472
ITEM_EXPERT_BELT = 477
ITEM_LIFE_ORB = 479
ITEM_FOCUS_SASH = 481
ITEM_ROCKY_HELMET = 496
ITEM_WEAKNESS_POLICY = 502
ITEM_ASSAULT_VEST = 503
ITEM_LUM_BERRY = 522
ITEM_SITRUS_BERRY = 523

ITEM_NAMES = {ITEM_HP_UP: "HP Up", ITEM_PROTEIN: "Protein", ITEM_IRON: "Iron", ITEM_CALCIUM: "Calcium", ITEM_ZINC: "Zinc",
              ITEM_CARBOS: "Carbos", ITEM_PP_UP: "PP Up", ITEM_PP_MAX: "PP Max", ITEM_ABILITY_CAPSULE: "Ability Capsule",
              ITEM_ABILITY_PATCH: "Ability Patch", ITEM_RARE_CANDY: "Rare Candy", ITEM_BOTTLE_CAP: "Bottle Cap",
              ITEM_GOLD_BOTTLE_CAP: "Gold Bottle Cap", ITEM_CHOICE_BAND: "Choice Band", ITEM_CHOICE_SPECS: "Choice Specs",
              ITEM_CHOICE_SCARF: "Choice Scarf", ITEM_LEFTOVERS: "Leftovers", ITEM_EXPERT_BELT: "Expert Belt",
              ITEM_LIFE_ORB: "Life Orb", ITEM_FOCUS_SASH: "Focus Sash", ITEM_ROCKY_HELMET: "Rocky Helmet",
              ITEM_WEAKNESS_POLICY: "Weakness Policy", ITEM_ASSAULT_VEST: "Assault Vest", ITEM_LUM_BERRY: "Lum Berry",
              ITEM_SITRUS_BERRY: "Sitrus Berry"}

PRIZE_FLOORS = (10, 20, 25, 30, 40, 50, 60, 70, 75, 80, 90, 100)   # claim bit n = PRIZE_FLOORS[n]
MILESTONE_FLOORS = (25, 50, 75, 100)                                 # milestone n, delivered bit 12 + n
MILESTONE_KINDS = ("a random shiny (natural IVs)", "a random Pokemon, all IVs 31", "a random shiny, all IVs 31",
                   "a shiny legendary, all IVs 31")
LEGENDARY_MAX_LEVEL = 70


class Prize(NamedTuple):
    money: int
    items: tuple                 # (item id, quantity), in the order they are sent
    milestone: int | None = None # 0-3: the milestone Pokemon of floors 25, 50, 75, 100


# The first clear of a prize floor, once per player ever (design section 4).
PRIZES = {
    10: Prize(10_000, ((ITEM_RARE_CANDY, 10),)),
    20: Prize(20_000, ((ITEM_BOTTLE_CAP, 5),)),
    25: Prize(0, (), 0),
    30: Prize(30_000, ((ITEM_RARE_CANDY, 15),)),
    40: Prize(40_000, ((ITEM_GOLD_BOTTLE_CAP, 1),)),
    50: Prize(50_000, (), 1),
    60: Prize(60_000, ((ITEM_RARE_CANDY, 20),)),
    70: Prize(70_000, ((ITEM_GOLD_BOTTLE_CAP, 2),)),
    75: Prize(0, (), 2),
    80: Prize(80_000, ((ITEM_ABILITY_PATCH, 1),)),
    90: Prize(90_000, ((ITEM_ABILITY_PATCH, 1), (ITEM_GOLD_BOTTLE_CAP, 3))),
    100: Prize(100_000, (), 3),
}
CLAIMS_MASK = (1 << len(PRIZE_FLOORS)) - 1
DELIVERED_MASK = 0xF << 12


def claim_bit(floor: int) -> int:
    return 1 << PRIZE_FLOORS.index(floor)


def delivered_bit(milestone: int) -> int:
    return 1 << (12 + milestone)


def bp_multiplier(floor: int) -> int:
    return 5 if floor == 100 else 4 if floor in (25, 50, 75) else 3 if floor % 10 == 0 else 1


def first_clear_bp(floor: int) -> int:
    """Battle Points for a floor's first win ever: (1 + floor // 10) x 3 on the Gym floors, 4 on 25/50/75, 5 on 100."""
    return (1 + floor // 10) * bp_multiplier(floor)


def first_clear_money(floor: int) -> int:
    return floor * 100


def describe_items(items) -> str:
    """'10 Rare Candy', '1 Ability Patch + 3 Gold Bottle Cap'."""
    return " + ".join(f"{quantity} {ITEM_NAMES.get(item, 'item')}" for item, quantity in items)


class ShopItem(NamedTuple):
    item: int
    quantity: int
    price: int       # Battle Points

    @property
    def name(self) -> str:
        return ITEM_NAMES.get(self.item, f"Item {self.item}")


# The Tower Shop (design section 5): debit first, like the Frontier shop.
SHOP = (
    ShopItem(ITEM_BOTTLE_CAP, 1, 48), ShopItem(ITEM_GOLD_BOTTLE_CAP, 1, 192), ShopItem(ITEM_ABILITY_PATCH, 1, 200),
    ShopItem(ITEM_ABILITY_CAPSULE, 1, 50), ShopItem(ITEM_RARE_CANDY, 1, 24), ShopItem(ITEM_PP_UP, 1, 24),
    ShopItem(ITEM_PP_MAX, 1, 64), ShopItem(ITEM_HP_UP, 1, 16), ShopItem(ITEM_PROTEIN, 1, 16), ShopItem(ITEM_IRON, 1, 16),
    ShopItem(ITEM_CALCIUM, 1, 16), ShopItem(ITEM_ZINC, 1, 16), ShopItem(ITEM_CARBOS, 1, 16), ShopItem(ITEM_LEFTOVERS, 1, 48),
    ShopItem(ITEM_CHOICE_BAND, 1, 64), ShopItem(ITEM_CHOICE_SPECS, 1, 64), ShopItem(ITEM_CHOICE_SCARF, 1, 64),
    ShopItem(ITEM_LIFE_ORB, 1, 64), ShopItem(ITEM_FOCUS_SASH, 1, 48), ShopItem(ITEM_ASSAULT_VEST, 1, 64),
    ShopItem(ITEM_ROCKY_HELMET, 1, 48), ShopItem(ITEM_EXPERT_BELT, 1, 48), ShopItem(ITEM_WEAKNESS_POLICY, 1, 48),
    ShopItem(ITEM_LUM_BERRY, 1, 16), ShopItem(ITEM_SITRUS_BERRY, 1, 8),
)
