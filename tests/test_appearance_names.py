import unittest

from emerald_multiplayer.appearance import (CLOTHING_COLORS, DEFAULT, HAIR_COLORS, LIMITS, SKIN_TONES, describe, encode,
                                            validate_appearance)


class AppearanceNameTests(unittest.TestCase):
    def test_every_valid_index_has_a_name_matching_the_engine_editor(self):
        # The engine's editor has 6 skins, 12 hairs and 16 cloth colours (eng:src/multiplayer_appearance.c).
        self.assertEqual((len(SKIN_TONES), len(HAIR_COLORS), len(CLOTHING_COLORS)), (6, 12, 16))
        self.assertEqual(LIMITS[1:4], (5, 11, 15))
        self.assertEqual(describe(DEFAULT), "Default outfit")
        self.assertEqual(describe(encode(5, 11, 15, 15, 15, 15)),
                         "Deep skin, Green hair, Maroon top, Maroon bottoms, Maroon hat, Maroon accents")
        with self.assertRaises(ValueError):
            validate_appearance(bytes((1, 6, 0, 0, 0, 0, 0, 0)))


if __name__ == "__main__":
    unittest.main()
