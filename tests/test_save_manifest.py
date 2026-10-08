from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from emerald_multiplayer.companion import verify_rom_manifest
from test_companion import make_files


def load_script(name):
    path = Path(__file__).parents[1] / "scripts" / "multiplayer" / (name + ".py")
    spec = importlib.util.spec_from_file_location("test_" + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


generator = load_script("generate_manifest")
configurer = load_script("configure_bridge")
SAVE_FIELDS = dict(save_abi_version=1, save_mailbox_size=512, save_mailbox_address=0x02021000)


class SaveManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.rom, self.manifest_path = make_files(self.temp.name)
        self.manifest = json.loads(self.manifest_path.read_text())
        self.elf = Path(self.temp.name) / "synthetic.elf"
        self.elf.write_bytes(b"synthetic symbol fixture, not executable engine code")
        self.symbols = "\n".join((
            "02020000 00000080 B gMultiplayerMailbox",
            "02001000 00000960 B gParties", "02001960 00000004 B gPartiesCount",
            "03000000 00000004 B gSaveBlock1Ptr",
        )) + "\n"

    def tearDown(self):
        self.temp.cleanup()

    def verify(self, value):
        self.manifest_path.write_text(json.dumps(value))
        return verify_rom_manifest(self.rom, self.manifest_path)

    def configure(self, value):
        return configurer.configure(value, "a" * 64, 8870, "-- fixture bridge\n")

    def generate(self, extra=""):
        with patch.object(generator.subprocess, "check_output", return_value=self.symbols + extra):
            return generator.generate(self.rom, self.elf, "fixture-nm", "b" * 40)

    def test_old_presence_build_remains_valid_without_live_capability_fields(self):
        self.verify(self.manifest)
        configured = self.configure(self.manifest)
        self.assertNotIn("save_address", configured)
        generated = self.generate()
        self.assertFalse(set(SAVE_FIELDS) & set(generated))
        self.verify(generated)

    def test_generated_optional_allocated_symbol_and_configure_names(self):
        generated = self.generate("02021000 00000200 B gMultiplayerSaveMailbox\n")
        self.assertEqual({key: generated[key] for key in SAVE_FIELDS}, SAVE_FIELDS)
        self.verify(generated)
        configured = self.configure(generated)
        self.assertIn("save_address=", configured)
        self.assertIn("save_size=512, save_abi=1", configured)
        self.assertTrue(configured.endswith("-- fixture bridge\n"))

    def test_elf_rejects_wrong_size_duplicate_overlap_and_outside_allocation(self):
        for extra in (
            "02021000 000001fc B gMultiplayerSaveMailbox\n",
            "02021001 00000200 B gMultiplayerSaveMailbox\n",
            "02020000 00000200 B gMultiplayerSaveMailbox\n",
            "0203fe04 00000200 B gMultiplayerSaveMailbox\n",
            "03001000 00000200 B gMultiplayerSaveMailbox\n",
            "02021000 00000200 B gMultiplayerSaveMailbox\n02022000 00000200 B gMultiplayerSaveMailbox\n",
        ):
            with self.subTest(symbols=extra), self.assertRaises(ValueError):
                self.generate(extra)

    def test_all_optional_fields_required_in_both_validators(self):
        for missing in SAVE_FIELDS:
            value = {**self.manifest, **SAVE_FIELDS}
            del value[missing]
            with self.subTest(missing=missing):
                with self.assertRaises(ValueError):
                    self.verify(value)
                with self.assertRaises(ValueError):
                    self.configure(value)
        value = {**self.manifest, **SAVE_FIELDS}
        del value["mailbox_address"]
        with self.assertRaises(ValueError):
            self.verify(value)

    def test_strict_save_types_bounds_abi_and_overlap_match(self):
        for changes in (dict(save_abi_version=2), dict(save_abi_version=True),
                        dict(save_mailbox_size=511), dict(save_mailbox_size="512"),
                        dict(save_mailbox_address=True), dict(save_mailbox_address=0x02021001),
                        dict(save_mailbox_address=0x0203FE04), dict(save_mailbox_address=0x03001000),
                        dict(save_mailbox_address=self.manifest["mailbox_address"] + 124),
                        dict(save_mailbox_address=self.manifest["mailbox_address"] - 508)):
            value = {**self.manifest, **SAVE_FIELDS, **changes}
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    self.verify(value)
                with self.assertRaises(ValueError):
                    self.configure(value)
        # Adjacent, nonoverlapping allocations are legitimate in either order.
        for address in (self.manifest["mailbox_address"] + 128, self.manifest["mailbox_address"] - 512):
            value = {**self.manifest, **SAVE_FIELDS, "save_mailbox_address": address}
            self.verify(value)
            self.configure(value)


if __name__ == "__main__":
    unittest.main()
