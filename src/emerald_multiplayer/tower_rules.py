"""Battle Tower: Legends' rules as pure functions (docs/battle-tower-legends.md sections 2-4), shared by the host
(tower_service.py) and the Players menu (tower_menu.py) so both say the same thing.

* Each player has a progress floor P (the next floor of their climb, 1..100; 101 once floor 100 is cleared) and a highest
  cleared floor H (0..100). Winning floor P: P+1 and H = max(H, P). Losing or drawing floor P: P = C+1, where C is the
  highest checkpoint <= H (0 when none). A player only ever fights their P or a floor <= H; any floor <= H other than P is
  a replay, which never changes P or H.
* A Duo battle's floor defaults to the lower of the two progress floors; a replay may be any floor up to the lower of the
  two players' highest unlocked floors (max(H, P), at most 100). For each player the floor is progression when it is their
  P, else a replay: one battle may move one player and be a replay for the other.
* Experience caps (shown here, applied by each game itself): 0..8 badges cap Tower experience at level 15, 20, 25, 30, 40,
  45, 50, 55, 60; a Champion (FLAG_SYS_GAME_CLEAR: the Hall of Fame entered) at 100.
* Prizes and Battle Points: tower_rewards.py; ``win_reward`` combines them for one player's win.
"""
from __future__ import annotations

import struct
from typing import NamedTuple

from . import tower_rewards
from .flash import POKEMON_SIZE, SAVED_PARTY_COUNT_OFFSET, SAVED_PARTY_OFFSET
from .frontier_service import BADGE_FLAGS, FLAGS_OFFSET, count_badges

FLOORS = 100
CLIMBED = FLOORS + 1                      # P once floor 100 is cleared: every floor is a replay
CHECKPOINTS = (10, 20, 25, 30, 40, 50, 60, 70, 75, 80, 90, 100)
EXP_CAPS = (15, 20, 25, 30, 40, 45, 50, 55, 60)   # by badges 0..8
CHAMPION_CAP = 100
FLAG_SYS_GAME_CLEAR = 0x864               # engine include/constants/flags.h (SYSTEM_FLAGS + 0x4): the Hall of Fame entered
OUTCOMES = ("won", "lost", "drew")


class TowerRuleError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def _floor(value) -> bool:
    return type(value) is int and 1 <= value <= FLOORS


def _check_state(progress: int, highest: int) -> None:
    if type(progress) is not int or type(highest) is not int or not 0 <= highest <= FLOORS or not 1 <= progress <= CLIMBED:
        raise TowerRuleError("invalid_progress", "progress is a floor 1-101 and the highest cleared floor 0-100")


def checkpoint(highest: int) -> int:
    """C: the highest checkpoint reached (cleared), 0 when none."""
    return max((floor for floor in CHECKPOINTS if floor <= highest), default=0)


def is_progression(progress: int, floor: int) -> bool:
    """The floor is the player's next floor of the climb (never once the climb is done)."""
    return _floor(floor) and floor == progress and progress <= FLOORS


def can_fight(progress: int, highest: int, floor: int) -> bool:
    """No skipping: the player's own progress floor, or a floor already cleared (a replay)."""
    return is_progression(progress, floor) or (_floor(floor) and floor <= highest)


def after(progress: int, highest: int, floor: int, outcome: str) -> tuple[int, int]:
    """(P, H) after a battle on ``floor``: a win at P climbs, a loss or a draw at P falls back to the last checkpoint + 1;
    a replay never changes either."""
    _check_state(progress, highest)
    if outcome not in OUTCOMES:
        raise TowerRuleError("invalid_outcome", "a Tower battle ends won, lost or drawn")
    if not can_fight(progress, highest, floor):
        raise TowerRuleError("tower_floor_locked", f"floor {floor} is not open to this player")
    if not is_progression(progress, floor):
        return progress, highest
    if outcome == "won":
        return progress + 1, max(highest, progress)
    return checkpoint(highest) + 1, highest


def max_unlocked(progress: int, highest: int) -> int:
    return min(FLOORS, max(highest, progress))


def default_duo_floor(progress_a: int, progress_b: int) -> int:
    """The Duo's floor unless the pair chooses a replay: the lower progress floor (floor 100 once both have climbed)."""
    return min(FLOORS, progress_a, progress_b)


def duo_floor_allowed(floor: int, a: tuple[int, int], b: tuple[int, int]) -> bool:
    """``a`` and ``b`` are each player's (P, H)."""
    return _floor(floor) and floor <= min(max_unlocked(*a), max_unlocked(*b))


def exp_cap(badges: int, champion: bool) -> int:
    if champion:
        return CHAMPION_CAP
    return EXP_CAPS[max(0, min(len(BADGE_FLAGS), badges))]


def flag_set(save_block1: bytes, flag: int) -> bool:
    return bool(save_block1[FLAGS_OFFSET + flag // 8] >> (flag % 8) & 1)


def save_cap(save_block1: bytes) -> tuple[int, bool, int]:
    """(badges, champion, cap) of a saved game's first block, as the game itself reads them."""
    badges, champion = count_badges(save_block1), flag_set(save_block1, FLAG_SYS_GAME_CLEAR)
    return badges, champion, exp_cap(badges, champion)


def milestone_level(floor: int, cap: int) -> int:
    """A milestone Pokemon's level: the floor, at most the player's experience cap at the claim, a legendary at most 70."""
    level = min(floor, cap)
    return min(level, tower_rewards.LEGENDARY_MAX_LEVEL) if floor == FLOORS else level


def legal_pool(pool, level: int) -> tuple:
    """The species of a milestone pool (tower_data.Species) that can exist at that level."""
    return tuple(entry for entry in pool if entry.min_level <= level)


def choose_milestone(pool, level: int, rng):
    """The milestone's species: a random choice (``rng``: random.SystemRandom on the host) among the pool's species legal
    at that level, or None when none is. The host records it before anything is sent, so it never changes."""
    legal = legal_pool(pool, level)
    return rng.choice(legal) if legal else None


class WinReward(NamedTuple):
    first_clear: bool            # the floor's first win ever for this player
    bp: int
    money: int
    items: tuple                 # (item id, quantity)
    claim: int                   # the claim bit this win sets (0: none)
    milestone: int | None        # the milestone Pokemon this win makes owed (0-3)


def win_reward(floor: int, highest: int, best: int, claims: int) -> WinReward:
    """What one player earns for winning ``floor``. ``highest`` is their H before the battle, ``best`` the highest floor
    they ever cleared in this world (an import may have lowered H: a floor cleared before is never a first clear again),
    ``claims`` their claim bits (a prize is paid once per player, ever)."""
    first = floor > max(highest, best)
    prize = tower_rewards.PRIZES.get(floor)
    if first and prize is not None and not claims & tower_rewards.claim_bit(floor):
        # A prize floor's first clear pays its prize instead of the floor's money.
        return WinReward(True, tower_rewards.first_clear_bp(floor), prize.money, prize.items,
                         tower_rewards.claim_bit(floor), prize.milestone)
    if first:
        return WinReward(True, tower_rewards.first_clear_bp(floor), tower_rewards.first_clear_money(floor), (), 0, None)
    return WinReward(False, tower_rewards.later_win_bp(floor, highest), tower_rewards.later_win_money(floor, highest), (), 0,
                     None)


def party_training(save_block1: bytes) -> list[dict]:
    """The saved party's natural IVs and Hyper Training (the Tower page's Hyper Training information): for every Pokemon,
    its species, level, whether it is an Egg, its six natural IVs (HP, Atk, Def, Spe, SpA, SpD as the save packs them) and
    which of them are trained (PokemonSubstruct1's hyperTrained bits). Read-only, from a validated save."""
    from .ownership import _SUBSTRUCT_OFFSETS
    party = []
    for slot in range(min(save_block1[SAVED_PARTY_COUNT_OFFSET], 6)):
        mon = save_block1[SAVED_PARTY_OFFSET + slot * POKEMON_SIZE:SAVED_PARTY_OFFSET + (slot + 1) * POKEMON_SIZE]
        personality, ot_id = struct.unpack_from("<II", mon)
        physical = struct.pack("<12I", *(word ^ personality ^ ot_id for word in struct.unpack_from("<12I", mon, 32)))
        logical = b"".join(physical[index * 12:index * 12 + 12]
                           for index in (row[personality % 24] for row in _SUBSTRUCT_OFFSETS))
        species = struct.unpack_from("<H", logical, 0)[0] & 0x7FF
        packed = struct.unpack_from("<I", logical, 36 + 4)[0]
        move4 = struct.unpack_from("<H", logical, 12 + 6)[0]
        trained = ((move4 >> 14) & 1, (move4 >> 15) & 1, logical[20] >> 7, logical[21] >> 7, logical[22] >> 7,
                   logical[23] >> 7)
        party.append({"slot": slot, "species": species, "level": mon[84], "egg": bool(mon[19] & 4),
                      "ivs": [(packed >> (5 * index)) & 31 for index in range(6)], "trained": [bool(t) for t in trained]})
    return party
