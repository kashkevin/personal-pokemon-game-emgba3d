"""Battle Frontier rewards (Battle Points and items) on the wager wallet stream.

The host sends each player's game a numbered *wallet adjustment* (wagers.py): a signed 32-bit delta applied exactly once per
save. Money fits +-999,999. A **reward word** is a delta above that with bit 30 set (engine ``src/multiplayer_world.c``):

    bit 30 set | bits 24-27 kind | bits 0-23 payload

    kind 1  Battle Points added   payload = points (1-9999; the save holds at most 9999)
    kind 2  an item               payload = item id << 8 | quantity (1-99); bag first, then the PC's item storage
    kind 3  Battle Points taken   payload = points asked (a shop purchase); at most the points on hand are taken

The game answers with a receipt of what really moved (0 when nothing could), so the host never believes a reward that did not
land. These words are understood only by the native PC game (the Frontier itself is PC-only); the GBA ROM ignores them.
"""
from __future__ import annotations

REWARD_FLAG = 0x40000000
REWARD_MASK = 0x70000000
KIND_BP = 1
KIND_ITEM = 2
KIND_BP_DEBIT = 3
MAX_BP = 9999
MAX_ITEM_QUANTITY = 99
ITEMS_COUNT = 0x4000      # a sanity bound; the game checks the real item table


class RewardError(ValueError):
    pass


def encode(kind: int, payload: int) -> int:
    """The wallet delta for a reward. Raises RewardError for anything the game would refuse."""
    if kind in (KIND_BP, KIND_BP_DEBIT):
        if type(payload) is not int or not 1 <= payload <= MAX_BP:
            raise RewardError("Battle Points are 1 to 9999")
    elif kind == KIND_ITEM:
        if type(payload) is not int or not 0 < (payload >> 8) < ITEMS_COUNT or not 1 <= (payload & 0xFF) <= MAX_ITEM_QUANTITY:
            raise RewardError("an item is a known id and 1 to 99")
    else:
        raise RewardError("unknown reward kind")
    return REWARD_FLAG | (kind << 24) | payload


def item_payload(item_id: int, quantity: int) -> int:
    return (item_id << 8) | quantity


def is_reward_word(delta) -> bool:
    return type(delta) is int and delta > 999_999 and (delta & REWARD_MASK) == REWARD_FLAG


def decode(delta) -> tuple[int, int] | None:
    """(kind, payload) of a valid reward word, else None."""
    if not is_reward_word(delta):
        return None
    kind, payload = (delta >> 24) & 0xF, delta & 0xFFFFFF
    try:
        encode(kind, payload)
    except RewardError:
        return None
    return kind, payload


def valid_wallet_delta(delta) -> bool:
    """A wallet delta the game accepts: money (+-999,999, nonzero) or a valid reward word."""
    if type(delta) is not int or isinstance(delta, bool):
        return False
    return (delta != 0 and -999_999 <= delta <= 999_999) or decode(delta) is not None
