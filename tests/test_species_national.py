import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import unittest

from emerald_multiplayer.species_national import (
    ENGINE_REVISION, IDENTITY_LAST, MAPPING_SHA256, NATIONAL, TABLE_ID, national_number,
)


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("species_national_generator",
    ROOT / "scripts/multiplayer/generate_species_national.py")
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


class SpeciesNationalTests(unittest.TestCase):
    def test_generated_table_matches_its_provenance(self):
        evidence = json.loads((ROOT / "docs/species-national-table.json").read_text(encoding="utf-8"))
        self.assertEqual((evidence["table_id"], evidence["engine_revision"], evidence["mapping_sha256"]),
                         (TABLE_ID, ENGINE_REVISION, MAPPING_SHA256))
        self.assertEqual((evidence["identity_last"], IDENTITY_LAST), (905, 905))
        packed = b"".join(struct.pack("<HH", species, national) for species, national in sorted(NATIONAL.items()))
        self.assertEqual(hashlib.sha256(packed).hexdigest(), MAPPING_SHA256)
        numbered = {entry[0]: entry[3] for entry in evidence["entries"] if entry[3]}
        self.assertEqual(numbered, NATIONAL)
        # every ID up to the storage namespace's end has a number but 1435 (SPECIES_LUGIA_SHADOW: a constant with no
        # species entry in this build, an empty slot of the game's table)
        self.assertEqual(set(range(IDENTITY_LAST + 1, 1573)) - set(NATIONAL), {1435})
        self.assertNotIn(1435, {entry[0] for entry in evidence["entries"]})

    def test_known_numbers(self):
        for species, national in ((1, 1), (479, 479), (905, 905), (906, 3), (1064, 479), (1071, 487), (1105, 646),
                                  (1155, 678), (1157, 710), (1168, 720), (1434, 1025), (1475, 665), (1572, 970)):
            with self.subTest(species=species):
                self.assertEqual(national_number(species), national)
        for species in (0, -1, 1435, 1573, True, "25", 25.0, None):
            with self.subTest(species=species):
                self.assertIsNone(national_number(species))

    def test_generator_refuses_a_table_that_does_not_hold(self):
        rows = [(species, f"SPECIES_{species}", f"NATIONAL_DEX_{species}", species) for species in range(1, 906)]
        self.assertEqual(generator.check_table(rows + [(906, "SPECIES_FORM", "NATIONAL_DEX_3", 3)]), {906: 3})
        self.assertEqual(generator.check_table(rows + [(1435, "SPECIES_PLACEHOLDER", "NATIONAL_DEX_NONE", 0)]), {})
        for invalid in (rows[:-1],                                              # an identity ID missing
                        rows[:24] + [(25, "SPECIES_25", "NATIONAL_DEX_26", 26)] + rows[25:],   # not its own number
                        rows + [(5, "SPECIES_AGAIN", "NATIONAL_DEX_5", 5)],     # an ID twice
                        rows + [(906, "SPECIES_FORM", "NATIONAL_DEX_X", 1026)]):  # beyond Pecharunt
            with self.subTest(rows=len(invalid)), self.assertRaises(ValueError):
                generator.check_table(invalid)

    def test_generator_reads_one_national_number_per_entry(self):
        source = ('[SPECIES_NONE] = {.x = 1,}, [SPECIES_A] = {.nested = {"}not an end", 1}, .natDexNum = NATIONAL_DEX_A,},'
                  + "".join(f"[SPECIES_{i}] = {{.natDexNum = NATIONAL_DEX_{i},}}," for i in range(905)))
        entries = dict(generator.extract_national(source))
        self.assertEqual(entries["SPECIES_A"], "NATIONAL_DEX_A")
        self.assertNotIn("SPECIES_NONE", entries)
        for invalid in (source.replace(".natDexNum = NATIONAL_DEX_A,", ""),
                        source.replace(".natDexNum = NATIONAL_DEX_A,", ".natDexNum = NATIONAL_DEX_A, .natDexNum = NATIONAL_DEX_B,"),
                        source + source[:60]):
            with self.subTest(invalid=invalid[:90]), self.assertRaises(ValueError):
                generator.extract_national(invalid)


if __name__ == "__main__":
    unittest.main()
