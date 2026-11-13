"""A running game's Pokemon read from outside its process, as the game keeps them at rest.

The game decrypts a Pokemon's 48 secure bytes in place while it reads or writes them (the engine's src/pokemon.c:
GetBoxMonData and SetBoxMonData decrypt, then encrypt again) - the followers read the party's lead every frame, a battle
far more - so a read from another process can catch a slot decrypted, or half of it. Measured on Linux (TEST_LEDGER, the
world trades' egg-box failure in run 450, 2026-11-13): 9 such reads in 6.7 million of two playing games' parties in the
field, 257 in 1.7 million elsewhere (battles, menus). A read counts here when every record in it checks out - its secure
bytes, decrypted with personality ^ OT ID, sum to its checksum, the game's own check - and the next read is the same.
"""
from __future__ import annotations

import struct

from emerald_multiplayer.flash import BOX_POKEMON_SIZE, POKEMON_SIZE


def box_checks_out(box: bytes) -> bool:
    """A BoxPokemon's 80 bytes as the game keeps them at rest (src/pokemon.c CalculateBoxMonChecksum): its 48 secure
    bytes, decrypted with personality ^ OT ID, sum (16-bit halves) to its checksum. An empty slot (zeros) checks out."""
    personality, ot_id = struct.unpack_from("<II", box, 0)
    key = personality ^ ot_id
    total = 0
    for (word,) in struct.iter_unpack("<I", box[32:BOX_POKEMON_SIZE]):
        word ^= key
        total += (word & 0xFFFF) + (word >> 16)
    return total & 0xFFFF == struct.unpack_from("<H", box, 28)[0]


def consistent(read, stride: int = POKEMON_SIZE, tries: int = 400) -> bytes:
    """`read()` again until a read whose records (one every `stride` bytes from the first, each a BoxPokemon's 80 bytes
    first) all check out is followed by the same read. After `tries` reads, the last one: a record that never checks out
    (a Bad Egg) is the game's as it is, and the caller's own check says what it found."""
    last, data = None, b""
    for _ in range(tries):
        data = read()
        if all(box_checks_out(data[at:at + BOX_POKEMON_SIZE])
               for at in range(0, len(data) - BOX_POKEMON_SIZE + 1, stride)):
            if data == last:
                return data
            last = data
        else:
            last = None
    return data
