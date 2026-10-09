"""Compact customized-trainer appearance (8 bytes, synchronized by the host).

byte 0  version/flags: 0 = default Brendan/May palette, 1 = customized
byte 1  skin tone      (0..5)
byte 2  hair color     (0..11)
byte 3  top color      (0..15)
byte 4  bottom color   (0..15)
byte 5  hat color      (0..15)
byte 6  accent color   (0..15) shoes/bag/details
byte 7  reserved (0)

The ROM recolors the player's existing sprite palette slots, so every avatar
state (walk, run, bike, surf, fish, ride...) keeps its complete animations.
"""
from __future__ import annotations

SKIN_TONES = ("Light", "Fair", "Tan", "Olive", "Brown", "Dark")
HAIR_COLORS = ("Black", "Dark Brown", "Brown", "Auburn", "Red", "Blonde", "Platinum", "Silver",
               "Blue", "Green", "Purple", "Pink")
CLOTHING_COLORS = ("Red", "Orange", "Yellow", "Lime", "Green", "Teal", "Cyan", "Sky",
                   "Blue", "Navy", "Purple", "Magenta", "Pink", "White", "Gray", "Black")
LIMITS = (1, len(SKIN_TONES) - 1, len(HAIR_COLORS) - 1, 15, 15, 15, 15, 0)
DEFAULT = bytes(8)


def validate_appearance(value: bytes) -> bytes:
    if not isinstance(value, bytes) or len(value) != 8:
        raise ValueError("appearance must contain exactly eight bytes")
    for index, (byte, limit) in enumerate(zip(value, LIMITS)):
        if byte > limit:
            raise ValueError(f"appearance byte {index} is outside its range")
    if value[0] == 0 and any(value[1:]):
        raise ValueError("default appearance cannot carry custom colors")
    return value


def encode(skin=0, hair=0, top=0, bottom=0, hat=0, accent=0) -> bytes:
    return validate_appearance(bytes((1, skin, hair, top, bottom, hat, accent, 0)))


def describe(value: bytes) -> str:
    validate_appearance(value)
    if value[0] == 0:
        return "Default outfit"
    return (f"{SKIN_TONES[value[1]]} skin, {HAIR_COLORS[value[2]]} hair, {CLOTHING_COLORS[value[3]]} top, "
            f"{CLOTHING_COLORS[value[4]]} bottoms, {CLOTHING_COLORS[value[5]]} hat, {CLOTHING_COLORS[value[6]]} accents")
