from __future__ import annotations

import unittest

from emerald_multiplayer.species_labels import species_label as standard_label
from emerald_multiplayer.trade_forms import REVIEWED_FORMS, species_label, standard_species, tradable_species


class TradeFormsTests(unittest.TestCase):
    def test_rotoms_forms_are_named_and_stand_for_rotom(self):
        self.assertEqual([species_label(s) for s in range(1064, 1069)],
                         ["Heat Rotom", "Wash Rotom", "Frost Rotom", "Fan Rotom", "Mow Rotom"])
        self.assertEqual({standard_species(s) for s in REVIEWED_FORMS}, {479})
        self.assertEqual(species_label(479), "Rotom")

    def test_the_standard_range_and_other_ids_are_as_before(self):
        for species in (1, 25, 479, 721, 722, 968, 1063, 1069, 1157, 1572, 0, -1):
            with self.subTest(species=species):
                if species not in REVIEWED_FORMS:
                    self.assertEqual(species_label(species), standard_label(species))
                    self.assertEqual(standard_species(species), species)
                self.assertEqual(tradable_species(species), 1 <= species <= 721)
        self.assertTrue(all(tradable_species(s) for s in REVIEWED_FORMS))
        self.assertFalse(tradable_species("1064"))


if __name__ == "__main__":
    unittest.main()
