"""Battle Frontier rewards (Battle Points and items) on the wager wallet stream.

The host sends each player's game a numbered *wallet adjustment* (wagers.py): a signed 32-bit delta applied exactly once per
save. Money fits +-999,999. A **reward word** is a delta above that with bit 30 set (engine ``src/multiplayer_world.c``):

    bit 30 set | bits 24-27 kind | bits 0-23 payload

    kind 1  Battle Points added   payload = points (1-9999; the save holds at most 9999)
    kind 2  an item               payload = item id << 8 | quantity (1-99); bag first, then the PC's item storage
    kind 3  Battle Points taken   payload = points asked (a shop purchase); at most the points on hand are taken
    kind 4  catch confirmed       payload = catch number of a World Event (the game clears its recorded catch)
    kind 5  catch released        payload = catch number: the game releases the recorded duplicate (and nothing else)
    kind 6  Battle Tower state    (docs/battle-tower-legends.md 8.4) bits 22-23 op:
              op 0 PROGRESS       bits 15-21 the highest floor cleared H (0-100), bits 8-14 the progress floor P (1-101),
                                  bits 0-7 the low byte of the ticket this word settles (0: none)
              op 1 CLAIMS         bits 0-15 claim bits OR-ed into the save's Tower record; bits 16-21 zero
              receipt: the record's revision after applying
    kind 7  Battle Tower Pokemon  bits 22-23 milestone (0-3: floors 25, 50, 75, 100), bits 11-21 species (1-2047),
                                  bits 4-10 level (1-100), bits 0-3 zero; receipt: 1 made, 2 already delivered
                                  (the save's record has it: nothing made), 0 nothing made

The game answers with a receipt of what really moved (0 when nothing could), so the host never believes a reward that did not
land. These words are understood only by the native PC game (the Frontier itself is PC-only); the GBA ROM ignores them.
Kinds 6 and 7 exist only in games with the Battle Tower (manifest ``tower_abi_version`` 1): every codec here refuses them
unless its caller says the game has it (``tower=True``), so they can never be sent to a game without it.
"""
from __future__ import annotations

REWARD_FLAG = 0x40000000
REWARD_MASK = 0x70000000
KIND_BP = 1
KIND_ITEM = 2
KIND_BP_DEBIT = 3
KIND_CATCH_KEEP = 4       # a World Event catch the host confirms (payload = catch_number(event id))
KIND_CATCH_RELEASE = 5    # ... or another trainer's report came first: the duplicate in this save is released
KIND_TOWER_STATE = 6      # Battle Tower: Legends: the player's progress, or the prizes claimed (tower_progress, tower_claims)
KIND_TOWER_MON = 7        # ... a milestone Pokemon to make (tower_mon)
TOWER_KINDS = frozenset((KIND_TOWER_STATE, KIND_TOWER_MON))
TOWER_PROGRESS = 0        # kind 6 ops (bits 22-23)
TOWER_CLAIMS = 1
TOWER_FLOORS = 100
TOWER_MAX_SPECIES = 2047  # the payload's 11 bits; the game checks the real species table
MAX_CATCH_NUMBER = 0x7FFFFF
MAX_BP = 9999
MAX_ITEM_QUANTITY = 99
ITEMS_COUNT = 0x4000      # a sanity bound; the game checks the real item table


class RewardError(ValueError):
    pass


def _bounded(value, low, high) -> bool:
    return type(value) is int and low <= value <= high


def tower_progress(highest: int, progress: int, ticket_low: int = 0) -> int:
    """The kind 6 PROGRESS payload: the save takes H and P as they are and settles the ticket whose low byte this is."""
    if not _bounded(highest, 0, TOWER_FLOORS) or not _bounded(progress, 1, TOWER_FLOORS + 1):
        raise RewardError("Tower progress is a highest floor 0-100 and a progress floor 1-101")
    if not _bounded(ticket_low, 0, 0xFF):
        raise RewardError("a settled ticket is named by its low byte")
    return (TOWER_PROGRESS << 22) | (highest << 15) | (progress << 8) | ticket_low


def tower_claims(claims: int) -> int:
    """The kind 6 CLAIMS payload (bits 0-11 the prize floors claimed, 12-15 the milestone Pokemon delivered)."""
    if not _bounded(claims, 0, 0xFFFF):
        raise RewardError("Tower claims are sixteen bits")
    return (TOWER_CLAIMS << 22) | claims


def tower_mon(milestone: int, species: int, level: int) -> int:
    """The kind 7 payload: the milestone Pokemon the game makes from that species, at that level."""
    if not _bounded(milestone, 0, 3) or not _bounded(species, 1, TOWER_MAX_SPECIES) or not _bounded(level, 1, 100):
        raise RewardError("a milestone Pokemon is milestone 0-3, species 1-2047 and level 1-100")
    return (milestone << 22) | (species << 11) | (level << 4)


def decode_tower_state(payload: int) -> tuple:
    """("progress", H, P, ticket low byte) or ("claims", bits) of a kind 6 payload; RewardError for anything else."""
    if not _bounded(payload, 0, 0xFFFFFF):
        raise RewardError("a reward payload is 24 bits")
    op = payload >> 22
    if op == TOWER_PROGRESS:
        highest, progress = (payload >> 15) & 0x7F, (payload >> 8) & 0x7F
        if highest > TOWER_FLOORS or not 1 <= progress <= TOWER_FLOORS + 1:
            raise RewardError("Tower progress is a highest floor 0-100 and a progress floor 1-101")
        return ("progress", highest, progress, payload & 0xFF)
    if op == TOWER_CLAIMS:
        if payload & 0x3F0000:
            raise RewardError("Tower claims leave bits 16-21 zero")
        return ("claims", payload & 0xFFFF)
    raise RewardError("unknown Tower state operation")


def decode_tower_mon(payload: int) -> tuple[int, int, int]:
    """(milestone, species, level) of a kind 7 payload; RewardError for anything else."""
    if not _bounded(payload, 0, 0xFFFFFF) or payload & 0xF:
        raise RewardError("a milestone Pokemon leaves bits 0-3 zero")
    milestone, species, level = payload >> 22, (payload >> 11) & 0x7FF, (payload >> 4) & 0x7F
    tower_mon(milestone, species, level)
    return milestone, species, level


def encode(kind: int, payload: int, *, tower: bool = False) -> int:
    """The wallet delta for a reward. Raises RewardError for anything the game would refuse; Battle Tower words (kinds 6
    and 7) only when the caller says the game has the Tower (``tower``)."""
    if kind in (KIND_BP, KIND_BP_DEBIT):
        if type(payload) is not int or not 1 <= payload <= MAX_BP:
            raise RewardError("Battle Points are 1 to 9999")
    elif kind in (KIND_CATCH_KEEP, KIND_CATCH_RELEASE):
        if type(payload) is not int or not 1 <= payload <= MAX_CATCH_NUMBER:
            raise RewardError("a catch number is 1 to 8,388,607")
    elif kind == KIND_ITEM:
        if type(payload) is not int or not 0 < (payload >> 8) < ITEMS_COUNT or not 1 <= (payload & 0xFF) <= MAX_ITEM_QUANTITY:
            raise RewardError("an item is a known id and 1 to 99")
    elif kind in TOWER_KINDS:
        if tower is not True:
            raise RewardError("Battle Tower words go only to a game with the Tower")
        (decode_tower_state if kind == KIND_TOWER_STATE else decode_tower_mon)(payload)
    else:
        raise RewardError("unknown reward kind")
    return REWARD_FLAG | (kind << 24) | payload


def catch_number(event_id: int) -> int:
    """The 23-bit number a verdict carries for a World Event (never zero); the game derives the same from its record."""
    if type(event_id) is not int or isinstance(event_id, bool) or event_id < 1:
        raise RewardError("an event number is positive")
    return ((event_id - 1) & MAX_CATCH_NUMBER) + 1


def item_payload(item_id: int, quantity: int) -> int:
    return (item_id << 8) | quantity


def is_reward_word(delta) -> bool:
    return type(delta) is int and delta > 999_999 and (delta & REWARD_MASK) == REWARD_FLAG


def decode(delta, *, tower: bool = False) -> tuple[int, int] | None:
    """(kind, payload) of a valid reward word, else None (a Battle Tower word is valid only with ``tower``)."""
    if not is_reward_word(delta):
        return None
    kind, payload = (delta >> 24) & 0xF, delta & 0xFFFFFF
    try:
        encode(kind, payload, tower=tower)
    except RewardError:
        return None
    return kind, payload


def valid_wallet_delta(delta, *, tower: bool = False) -> bool:
    """A wallet delta the game accepts: money (+-999,999, nonzero) or a valid reward word (Battle Tower words only for a
    game with the Tower, ``tower``)."""
    if type(delta) is not int or isinstance(delta, bool):
        return False
    return (delta != 0 and -999_999 <= delta <= 999_999) or decode(delta, tower=tower) is not None
