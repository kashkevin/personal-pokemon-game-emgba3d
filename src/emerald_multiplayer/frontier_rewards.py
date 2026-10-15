"""Battle Frontier prizes beyond money: Battle Points, item prizes and the Battle Points shop (Update 16).

Item ids are the engine's (include/constants/items.h, the pokeemerald-expansion numbering). Battle Points live in the player's
own save (``SaveBlock2.frontier.battlePoints``, the same counter the game's Battle Frontier Exchange Service Corners spend), so
they persist with the save and are also redeemable there; the host keeps a ledger of what it paid and what the shop took.

Everything here is a default the owner may change (docs/battle-frontier.md).
"""
from __future__ import annotations

from typing import NamedTuple

SET_LENGTH = 7

# engine item ids (include/constants/items.h)
ITEM_MAX_REVIVE = 34
ITEM_HP_UP = 65
ITEM_PROTEIN = 66
ITEM_IRON = 67
ITEM_CALCIUM = 68
ITEM_ZINC = 69
ITEM_CARBOS = 70
ITEM_PP_UP = 71
ITEM_RARE_CANDY = 102
ITEM_CHOICE_BAND = 442
ITEM_QUICK_CLAW = 462
ITEM_KINGS_ROCK = 465
ITEM_FOCUS_BAND = 469
ITEM_LEFTOVERS = 472

# The prize for finishing a set of seven rounds (clearing its Brain round), once per player per Brain round.
SET_ITEMS = ((ITEM_RARE_CANDY, 1), (ITEM_PP_UP, 1), (ITEM_MAX_REVIVE, 2), (ITEM_RARE_CANDY, 2))
ITEM_NAMES = {ITEM_MAX_REVIVE: "Max Revive", ITEM_HP_UP: "HP Up", ITEM_PROTEIN: "Protein", ITEM_IRON: "Iron",
              ITEM_CALCIUM: "Calcium", ITEM_ZINC: "Zinc", ITEM_CARBOS: "Carbos", ITEM_PP_UP: "PP Up",
              ITEM_RARE_CANDY: "Rare Candy", ITEM_CHOICE_BAND: "Choice Band", ITEM_QUICK_CLAW: "Quick Claw",
              ITEM_KINGS_ROCK: "King's Rock", ITEM_FOCUS_BAND: "Focus Band", ITEM_LEFTOVERS: "Leftovers"}


class ShopItem(NamedTuple):
    item: int
    quantity: int
    price: int       # Battle Points

    @property
    def name(self) -> str:
        return ITEM_NAMES.get(self.item, f"Item {self.item}")


# The Battle Points shop, priced like the game's Exchange Service Corners (vitamins 16 BP; held items 32-64 BP).
SHOP = (
    ShopItem(ITEM_PROTEIN, 1, 16), ShopItem(ITEM_IRON, 1, 16), ShopItem(ITEM_CALCIUM, 1, 16), ShopItem(ITEM_ZINC, 1, 16),
    ShopItem(ITEM_CARBOS, 1, 16), ShopItem(ITEM_HP_UP, 1, 16), ShopItem(ITEM_QUICK_CLAW, 1, 32),
    ShopItem(ITEM_KINGS_ROCK, 1, 32), ShopItem(ITEM_FOCUS_BAND, 1, 32), ShopItem(ITEM_LEFTOVERS, 1, 48),
    ShopItem(ITEM_CHOICE_BAND, 1, 64),
)


def set_of(round_no: int) -> int:
    return (round_no - 1) // SET_LENGTH


def bp_for(round_no: int, *, first_time: bool) -> int:
    """Battle Points for each player for clearing a round: more in later sets, a Brain pays triple-ish, a repeat pays half."""
    sets = set_of(round_no)
    brain = round_no % SET_LENGTH == 0
    amount = (3 + 2 * sets) if brain else (1 + sets // 2)
    return max(1, amount if first_time else amount // 2)


def item_for(round_no: int, *, first_time: bool):
    """The item prize for clearing a Brain round for the first time: (item id, quantity), else None."""
    if not first_time or round_no % SET_LENGTH != 0:
        return None
    return SET_ITEMS[set_of(round_no) % len(SET_ITEMS)]


def describe(kind: str, payload: int) -> str:
    if kind == "bp":
        return f"{payload} BP"
    item, quantity = payload >> 8, payload & 0xFF
    return f"{ITEM_NAMES.get(item, 'an item')}" + (f" x{quantity}" if quantity > 1 else "")
