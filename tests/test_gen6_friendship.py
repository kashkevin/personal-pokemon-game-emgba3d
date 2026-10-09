import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

from emerald_multiplayer.gen6_friendship import (
    ENGINE_REVISION, TABLE_ID, VALUES, VALUES_SHA256, base_friendship,
)


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("friendship_generator",
    ROOT / "scripts/multiplayer/generate_gen6_friendship.py")
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


class Gen6FriendshipTests(unittest.TestCase):
    def test_complete_generated_table_matches_provenance(self):
        evidence = json.loads((ROOT / "docs/gen6-friendship-table.json").read_text(encoding="utf-8"))
        self.assertEqual((evidence["table_id"], evidence["engine_revision"], evidence["values_sha256"]),
                         (TABLE_ID, ENGINE_REVISION, VALUES_SHA256))
        self.assertEqual(evidence["config_override"], {"P_UPDATED_FRIENDSHIP": "GEN_6"})
        self.assertEqual(hashlib.sha256(VALUES).hexdigest(), VALUES_SHA256)
        entries = evidence["entries"]
        self.assertEqual([entry[0] for entry in entries], list(range(1, 722)))
        self.assertEqual(len({entry[1] for entry in entries}), 721)
        self.assertEqual(len({entry[2] for entry in entries}), 721)
        self.assertEqual(bytes(entry[3] for entry in entries), VALUES)
        self.assertEqual([base_friendship(i) for i in range(1, 722)], list(VALUES))

    def test_known_gen6_bases_and_unsupported_species_boundary(self):
        # Explicit examples cover every value present in the native Gen6
        # standard-species table, including the pre-Gen8 default of 70.
        for species, value in ((1, 70), (113, 140), (151, 100), (280, 35),
                               (380, 90), (427, 0)):
            with self.subTest(species=species):
                self.assertEqual(base_friendship(species), value)
        self.assertEqual(set(VALUES), {0, 35, 70, 90, 100, 140})
        for species in (0, -1, 722, 968, 1157, True, False, 1.0, "1", None):
            with self.subTest(species=species), self.assertRaises(ValueError):
                base_friendship(species)

    def test_generator_requires_complete_unique_native_standard_mapping(self):
        source = "\n".join(f"SPECIES_TEST_{i} = {i}," for i in range(1, 722))
        expected = tuple(f"SPECIES_TEST_{i}" for i in range(1, 722))
        self.assertEqual(generator.species_names(source), expected)
        for invalid in (source.replace("SPECIES_TEST_721 = 721,", ""),
                        source + "\nSPECIES_DUPLICATE = 42,",
                        source.replace("SPECIES_TEST_42", "SPECIES_TEST_41")):
            with self.subTest(invalid=invalid[-80:]), self.assertRaises(ValueError):
                generator.species_names(invalid)

    def test_generator_refuses_unresolved_ambiguous_or_unsafe_fields(self):
        valid = ('[SPECIES_TEST] = {.nested = {"}not an end", 1}, '
                 '.friendship = ((5 >= 7) ? 50 : 70), .natDexNum = NATIONAL_DEX_TEST,},')
        self.assertEqual(generator.extract_fields(valid, ("SPECIES_TEST",)),
                         (("((5 >= 7) ? 50 : 70)", "NATIONAL_DEX_TEST"),))
        for invalid in (valid + valid, valid.replace(".friendship", ".missing"),
                        valid.replace("((5 >= 7) ? 50 : 70)", "UNKNOWN"),
                        valid.replace("((5 >= 7) ? 50 : 70)", "system(1)"),
                        valid.replace(".natDexNum", ".wrongDex"),
                        valid.replace(".nested", ".friendship"), valid[:-2]):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                generator.extract_fields(invalid, ("SPECIES_TEST",))


if __name__ == "__main__":
    unittest.main()
