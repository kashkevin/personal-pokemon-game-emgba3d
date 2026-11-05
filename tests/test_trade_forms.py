from __future__ import annotations

import json
from pathlib import Path
import re
import unittest

from emerald_multiplayer.species_labels import species_label as standard_label
from emerald_multiplayer.species_national import national_number
from emerald_multiplayer.trade_forms import (
    REVIEWED_FORMS, species_label, species_level_label, standard_species, tradable_species,
)


ROOT = Path(__file__).resolve().parents[1]
# The engine pin's name of every species ID (generate_species_national.py's provenance).
ENGINE_NAMES = {entry[0]: entry[1] for entry in json.loads(
    (ROOT / "docs/species-national-table.json").read_text(encoding="utf-8"))["entries"]}

# The review (2026-11-05): each reviewed form's engine name, family by family. A renumbered engine fails here.
REVIEWED_NAMES = re.compile(
    r"SPECIES_(UNOWN_([B-Z]|EXCLAMATION|QUESTION)|DEOXYS_(ATTACK|DEFENSE|SPEED)|(BURMY|WORMADAM|MOTHIM)_(SANDY|TRASH)"
    r"|(SHELLOS|GASTRODON)_EAST|ROTOM_(HEAT|WASH|FROST|FAN|MOW)|GIRATINA_ORIGIN|SHAYMIN_SKY"
    r"|ARCEUS_(FIGHTING|FLYING|POISON|GROUND|ROCK|BUG|GHOST|STEEL|FIRE|WATER|GRASS|ELECTRIC|PSYCHIC|ICE|DRAGON|DARK"
    r"|FAIRY)|BASCULIN_BLUE_STRIPED|(DEERLING|SAWSBUCK)_(SUMMER|AUTUMN|WINTER)|(TORNADUS|THUNDURUS|LANDORUS)_THERIAN"
    r"|KELDEO_RESOLUTE|GENESECT_(DOUSE|SHOCK|BURN|CHILL)"
    r"|(SCATTERBUG|SPEWPA|VIVILLON)_(POLAR|TUNDRA|CONTINENTAL|GARDEN|ELEGANT|MEADOW|MODERN|MARINE|ARCHIPELAGO"
    r"|HIGH_PLAINS|SANDSTORM|RIVER|MONSOON|SAVANNA|SUN|OCEAN|JUNGLE|FANCY|POKEBALL)"
    r"|(FLABEBE|FLOETTE|FLORGES)_(YELLOW|ORANGE|BLUE|WHITE)"
    r"|FURFROU_(HEART|STAR|DIAMOND|DEBUTANTE|MATRON|DANDY|LA_REINE|KABUKI|PHARAOH)|MEOWSTIC_F"
    r"|(PUMPKABOO|GOURGEIST)_(SMALL|LARGE|SUPER)|HOOPA_UNBOUND)")


class TradeFormsTests(unittest.TestCase):
    def test_rotoms_forms_are_named_and_stand_for_rotom(self):
        self.assertEqual([species_label(s) for s in range(1064, 1069)],
                         ["Heat Rotom", "Wash Rotom", "Frost Rotom", "Fan Rotom", "Mow Rotom"])
        self.assertEqual({standard_species(s) for s in range(1064, 1069)}, {479})
        self.assertEqual(species_label(479), "Rotom")

    def test_every_reviewed_form_is_the_engines_and_its_species_in_the_pokedex(self):
        self.assertEqual(len(REVIEWED_FORMS), 163)
        for species, (standard, label) in REVIEWED_FORMS.items():
            with self.subTest(species=species, label=label):
                self.assertRegex(ENGINE_NAMES[species], "^" + REVIEWED_NAMES.pattern + "$")
                self.assertEqual(national_number(species), standard)
                self.assertTrue(1 <= standard <= 721)
                self.assertTrue(label and len(label) <= 20 and label.isascii())
                self.assertTrue(label.endswith(standard_label(standard)) or label.startswith("Unown "))
        # every engine form the review names is listed (none forgotten), and only those
        named = {species for species, name in ENGINE_NAMES.items() if re.fullmatch(REVIEWED_NAMES, name)}
        self.assertEqual(named, set(REVIEWED_FORMS))

    def test_some_labels(self):
        self.assertEqual([species_label(s) for s in (1024, 1048, 1049, 1050)], ["Unown B", "Unown Z", "Unown !", "Unown ?"])
        self.assertEqual([species_label(s) for s in (1071, 1081, 1101, 1116, 1132, 1154, 1155, 1159, 1168)],
                         ["Origin Giratina", "Fire Arceus", "Therian Thundurus", "Continental Vivillon",
                          "Poke Ball Vivillon", "Pharaoh Furfrou", "Female Meowstic", "Super Pumpkaboo", "Unbound Hoopa"])
        # the game names Scatterbug, Spewpa and Mothim without their pattern or cloak
        self.assertEqual({species_label(s) for s in (*range(1438, 1476), 1436, 1437)}, {"Scatterbug", "Spewpa", "Mothim"})

    def test_forms_left_out_stay_refused(self):
        left_out = {
            906: "SPECIES_VENUSAUR_MEGA", 1023: "SPECIES_PICHU_SPIKY_EARED", 1009: "SPECIES_PIKACHU_COSPLAY",
            1015: "SPECIES_PIKACHU_ORIGINAL", 1051: "SPECIES_CASTFORM_SUNNY", 1061: "SPECIES_CHERRIM_SUNSHINE",
            1069: "SPECIES_DIALGA_ORIGIN", 1070: "SPECIES_PALKIA_ORIGIN", 1091: "SPECIES_BASCULIN_WHITE_STRIPED",
            1092: "SPECIES_DARMANITAN_ZEN", 1104: "SPECIES_KYUREM_WHITE", 1105: "SPECIES_KYUREM_BLACK",
            1107: "SPECIES_MELOETTA_PIROUETTE", 1112: "SPECIES_GRENINJA_BATTLE_BOND", 1141: "SPECIES_FLOETTE_ETERNAL",
            1156: "SPECIES_AEGISLASH_BLADE", 1163: "SPECIES_XERNEAS_ACTIVE", 1164: "SPECIES_ZYGARDE_10_AURA_BREAK",
            1167: "SPECIES_ZYGARDE_COMPLETE", 1487: "SPECIES_PIKACHU_STARTER", 1488: "SPECIES_EEVEE_STARTER"}
        for species, name in left_out.items():
            with self.subTest(species=species):
                self.assertEqual(ENGINE_NAMES[species], name)
                self.assertFalse(tradable_species(species))
        # regional forms of the standard species, and every later species
        for species, name in ENGINE_NAMES.items():
            if re.search(r"_(ALOLA|GALAR|HISUI|PALDEA)", name) or (national_number(species) or 0) > 721:
                self.assertFalse(tradable_species(species), name)

    def test_the_standard_range_and_other_ids_are_as_before(self):
        for species in (1, 25, 479, 721, 722, 968, 1069, 1572, 0, -1):
            with self.subTest(species=species):
                self.assertEqual(species_label(species), standard_label(species))
                self.assertEqual(standard_species(species), species)
                self.assertEqual(tradable_species(species), 1 <= species <= 721)
        self.assertTrue(all(tradable_species(s) for s in REVIEWED_FORMS))
        self.assertFalse(tradable_species("1064"))
        self.assertFalse(tradable_species(True))

    def test_a_menu_row_keeps_the_level_whole(self):
        self.assertEqual(species_level_label(25, 5, 25), "Pikachu Lv5")
        self.assertEqual(species_level_label(1116, 99, 25), "Continental Vivillon Lv99")
        self.assertEqual(species_level_label(1116, 100, 25), "Continental Vivillo Lv100")
        self.assertEqual(species_level_label(1116, 100, 25, "[X] "), "[X] Continental Viv Lv100")
        self.assertEqual(species_level_label(1116, None, 25), "Continental Vivillon")
        for species in REVIEWED_FORMS:
            for prefix in ("", "[X] "):
                row = species_level_label(species, 100, 25, prefix)
                self.assertLessEqual(len(row), 25)
                self.assertTrue(row.endswith(" Lv100"))


if __name__ == "__main__":
    unittest.main()
