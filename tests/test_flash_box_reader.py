"""KNOWN_ISSUES MS-161: the save reader's PC slot check (flash._box_species) answers as before, faster.

The faster reader answers an empty slot at once and decrypts a full one in one step; this compares it with the reader it
replaced, kept here word for word, on generated slots: empty, valid Pokemon (Eggs, every substructure order), and slots
with one byte or bit changed. Both the answer and the refusal (its message) must be the same."""
from __future__ import annotations

import random
import struct
import unittest

from emerald_multiplayer.flash import (
    BOX_POKEMON_SIZE, MAX_SPECIES_ID, FlashError, _GROWTH_SUBSTRUCT_OFFSETS, _box_species, inspect_flash,
)


def old_box_species(box: bytes, label: str) -> int:
    """flash._box_species before MS-161's second step (app 2026-11-04), unchanged."""
    if len(box) != BOX_POKEMON_SIZE:
        raise FlashError("invalid boxed Pokémon size")
    personality, ot_id = struct.unpack_from("<II", box)
    key = personality ^ ot_id
    words = tuple(value ^ key for value in struct.unpack_from("<12I", box, 32))
    checksum = sum((value & 0xFFFF) + (value >> 16) for value in words) & 0xFFFF
    if checksum != struct.unpack_from("<H", box, 28)[0]:
        raise FlashError(f"{label} boxed Pokémon checksum mismatch")
    has_species = bool(box[19] & 2)
    if box[19] & 1:
        raise FlashError(f"{label} is marked as a bad egg")
    growth = words[_GROWTH_SUBSTRUCT_OFFSETS[personality % 24] * 3]
    species = growth & 0x7FF
    if has_species:
        if not 1 <= species <= MAX_SPECIES_ID or not 1 <= (box[18] & 7) <= 7:
            raise FlashError(f"{label} has invalid species or language bounds")
    elif species != 0:
        raise FlashError(f"{label} species disagrees with its occupancy flag")
    return species


def boxed(rng: random.Random, *, species: int | None = None, egg: bool = False) -> bytes:
    """A sealed boxed Pokemon: random identity and substructures, the given species in its growth substructure."""
    personality, ot_id = rng.getrandbits(32), rng.getrandbits(32)
    words = [rng.getrandbits(32) for _ in range(12)]
    growth = _GROWTH_SUBSTRUCT_OFFSETS[personality % 24] * 3
    kind = rng.randint(1, MAX_SPECIES_ID) if species is None else species
    words[growth] = (words[growth] & ~0x7FF) | kind
    checksum = sum((w & 0xFFFF) + (w >> 16) for w in words) & 0xFFFF
    key = personality ^ ot_id
    box = bytearray(BOX_POKEMON_SIZE)
    struct.pack_into("<II", box, 0, personality, ot_id)
    box[18] = rng.randint(1, 7)
    box[19] = 2 | (4 if egg else 0) if kind else 0
    struct.pack_into("<H", box, 28, checksum)
    struct.pack_into("<12I", box, 32, *(w ^ key for w in words))
    return bytes(box)


def answer(reader, box):
    try:
        return ("species", reader(box, "slot"))
    except FlashError as error:
        return ("refused", str(error))


class BoxReaderTests(unittest.TestCase):
    def test_the_same_answers_as_the_reader_it_replaced(self):
        rng = random.Random(161)
        boxes = [bytes(BOX_POKEMON_SIZE)]
        for _ in range(3000):
            boxes.append(boxed(rng))
        for _ in range(300):
            boxes.append(boxed(rng, egg=True))
            boxes.append(boxed(rng, species=0))                   # no species and no flag: an empty-looking slot
        changed = []
        for box in boxes[:1500]:
            data = bytearray(box)
            spot = rng.randrange(BOX_POKEMON_SIZE)
            data[spot] ^= 1 << rng.randrange(8)
            changed.append(bytes(data))
        boxes += changed
        for _ in range(500):
            boxes.append(bytes(rng.getrandbits(8) for _ in range(BOX_POKEMON_SIZE)))
        one = bytearray(BOX_POKEMON_SIZE)
        one[19] = 1                                                # an all-zero slot marked as a bad egg
        boxes.append(bytes(one))
        one[19], one[28] = 0, 1                                    # ... with only its checksum set
        boxes.append(bytes(one))
        kinds = {"species": 0, "refused": 0}
        for box in boxes:
            with self.subTest(box=box.hex()):
                expected = answer(old_box_species, box)
                self.assertEqual(answer(_box_species, box), expected)
                kinds[expected[0]] += 1
        self.assertGreater(kinds["species"], 3000)                 # many read as Pokemon
        self.assertGreater(kinds["refused"], 1000)                 # and many refused, with the same messages
        self.assertRaisesRegex(FlashError, "size", _box_species, bytes(79), "slot")

    def test_snapshot_hashes_are_made_when_read(self):
        from test_flash import make_flash
        import hashlib
        data = make_flash()
        snapshot = inspect_flash(data)
        self.assertEqual(snapshot.sha256, hashlib.sha256(data[:128 * 1024]).hexdigest())
        self.assertEqual(snapshot.container_sha256, hashlib.sha256(data).hexdigest())
        self.assertEqual(snapshot.state_sha256, inspect_flash(data).state_sha256)
        self.assertEqual(snapshot, inspect_flash(data))
        self.assertNotIn("_state", repr(snapshot))


if __name__ == "__main__":
    unittest.main()
