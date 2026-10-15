"""The co-op battle code carried in a native battle's preparation (engine include/multiplayer_ladder.h).

A co-op Gym battle is code 1..8. A *ladder* battle (Battle Frontier, Pokemon League) is the same co-op battle against any
two trainers at a chosen level:

  bit 31 ladder   bit 30 experience is awarded   bits 20-29 first trainer   bits 10-19 second trainer
  bits 7-9 zero   bits 0-6 opposing level 1..100
"""
from __future__ import annotations

from typing import NamedTuple

GYM_COUNT = 8
LADDER_FLAG = 0x80000000
EXP_FLAG = 0x40000000
TRAINER_COUNT = 863          # the game's TRAINERS_COUNT_EMERALD: trainer ids 1..862
MAX_LEVEL = 100
TEAM_SIZE = 3                # Pokemon each opposing trainer brings


class Ladder(NamedTuple):
    trainer_a: int
    trainer_b: int
    level: int
    exp: bool


def encode(trainer_a: int, trainer_b: int, level: int, exp: bool = False) -> int:
    code = LADDER_FLAG | (EXP_FLAG if exp else 0) | (trainer_a << 20) | (trainer_b << 10) | level
    if decode(code) is None:
        raise ValueError("not a valid ladder battle")
    return code


def decode(code: int) -> Ladder | None:
    """The ladder battle a code names, or None when it is not a valid ladder code."""
    if type(code) is not int or isinstance(code, bool) or not LADDER_FLAG <= code <= 0xFFFFFFFF:
        return None
    if code & 0x380:
        return None
    a, b, level = (code >> 20) & 0x3FF, (code >> 10) & 0x3FF, code & 0x7F
    if not (1 <= a < TRAINER_COUNT and 1 <= b < TRAINER_COUNT and a != b and 1 <= level <= MAX_LEVEL):
        return None
    return Ladder(a, b, level, bool(code & EXP_FLAG))


def is_gym(code) -> bool:
    return type(code) is int and not isinstance(code, bool) and 1 <= code <= GYM_COUNT


def valid_code(code) -> bool:
    return is_gym(code) or decode(code) is not None
