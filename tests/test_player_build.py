"""Compiled-control and packaging boundaries; fixture ROMs are not gameplay."""
import argparse
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zlib

from emerald_multiplayer.companion import verify_rom_manifest
from emerald_multiplayer.player_build import (
    DESCRIPTOR, FIELDS, require_production_player_build, validate_player_build_manifest,
)
from test_companion import make_files
from test_player_runtime import write_bundle
from test_save_manifest import generator
from test_package_audit import build_launcher


class PlayerBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rom, self.manifest_path = make_files(self.root)
        self.value = json.loads(self.manifest_path.read_text())
        self.elf = self.root / "fixture.elf"
        self.elf.write_bytes(b"symbol fixture, never executed")
        self.symbols = ("02020000 00000080 B gMultiplayerMailbox\n"
                        "02001000 00000960 B gParties\n"
                        "02001960 00000004 B gPartiesCount\n"
                        "03000000 00000004 B gSaveBlock1Ptr\n")
        self.marker = "08000100 00000018 R gMultiplayerPlayerBuildGuard\n"

    def publish(self, value=None):
        data = self.rom.read_bytes()
        value = dict(self.value if value is None else value)
        value.update(rom_sha256=hashlib.sha256(data).hexdigest(),
                     rom_crc32=f"{zlib.crc32(data):08x}", rom_size=len(data))
        self.manifest_path.write_text(json.dumps(value))
        return value

    def guarded(self):
        data = bytearray(self.rom.read_bytes())
        data[256:256 + len(DESCRIPTOR)] = DESCRIPTOR
        self.rom.write_bytes(data)
        self.value.update(player_build_guard_abi_version=1, player_build_guard_address=0x08000100)
        self.value = self.publish()
        return self.value

    def generate(self, extra=""):
        with patch.object(generator.subprocess, "check_output", return_value=self.symbols + extra):
            return generator.generate(self.rom, self.elf, "fixture-nm", "b" * 40)

    def test_legacy_companion_verification_is_preserved_but_production_refuses(self):
        verify_rom_manifest(self.rom, self.manifest_path)
        self.assertFalse(validate_player_build_manifest(self.value, self.rom))
        with self.assertRaisesRegex(ValueError, "requires the compiled player build guard"):
            require_production_player_build(self.value, self.rom)

    def test_exact_disabled_marker_verifies_the_file(self):
        self.guarded()
        self.assertEqual(len(DESCRIPTOR), 24)
        self.assertTrue(require_production_player_build(self.value, self.rom))
        self.assertEqual(verify_rom_manifest(self.rom, self.manifest_path)[1], self.value)
        with self.assertRaisesRegex(ValueError, "requires the verified ROM bytes"):
            require_production_player_build(self.value, None)

    def test_partial_wrong_abi_alignment_and_out_of_rom_refused(self):
        value = self.guarded()
        bad = [{key: entry for key, entry in value.items() if key != field} for field in FIELDS]
        bad.extend({**value, "player_build_guard_abi_version": entry} for entry in (True, 0, 2, "1"))
        bad.extend({**value, "player_build_guard_address": entry} for entry in (
            True, "0x08000100", 0x08000101, 0x07FFFFFC, 0x0A000000,
            0x08000000 + len(self.rom.read_bytes()) - 20))
        for changed in bad:
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                validate_player_build_manifest(changed, self.rom)

    def test_rehash_cannot_hide_each_debug_flag_or_malformed_header(self):
        self.guarded()
        for word in range(6):
            data = bytearray(self.rom.read_bytes())
            data[256:280] = DESCRIPTOR
            struct.pack_into("<I", data, 256 + word * 4, 1 if word >= 2 else 0)
            self.rom.write_bytes(data)
            self.publish()
            with self.subTest(word=word), self.assertRaisesRegex(ValueError, "development controls"):
                verify_rom_manifest(self.rom, self.manifest_path)

    def test_shortened_rehashed_rom_cannot_supply_partial_marker(self):
        self.guarded()
        self.rom.write_bytes(self.rom.read_bytes()[:276])
        self.publish()
        with self.assertRaisesRegex(ValueError, "outside"):
            verify_rom_manifest(self.rom, self.manifest_path)

    def test_generator_legacy_absence_and_exact_symbol(self):
        self.assertFalse(FIELDS.intersection(self.generate()))
        self.guarded()
        generated = self.generate(self.marker)
        self.assertEqual(generated["player_build_guard_address"], 0x08000100)
        self.assertEqual(generated["player_build_guard_abi_version"], 1)
        self.assertTrue(require_production_player_build(generated, self.rom))

    def test_generator_named_malformed_symbol_is_not_silently_legacy(self):
        self.guarded()
        for extra in (self.marker * 2, self.marker.replace("18", "14"),
                      self.marker.replace(" R ", " B "),
                      "08000100 R gMultiplayerPlayerBuildGuard\n",
                      self.marker.replace("08000100", "02000100"),
                      self.marker.replace("08000100", "08000101")):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.generate(extra)

    def test_generator_refuses_enabled_compiled_control(self):
        self.guarded()
        data = bytearray(self.rom.read_bytes())
        struct.pack_into("<I", data, 264, 1)
        self.rom.write_bytes(data)
        with self.assertRaisesRegex(ValueError, "development controls"):
            self.generate(self.marker)

    def build_args(self, *, development=False):
        runtime = self.root / "runtime"
        runtime.mkdir()
        bundle = write_bundle(runtime)
        return argparse.Namespace(output=self.root / "output", version="fixture",
            rom_sha256=hashlib.sha256(self.rom.read_bytes()).hexdigest(),
            manifest_sha256=hashlib.sha256(self.manifest_path.read_bytes()).hexdigest(),
            runtime_sha256=bundle.manifest_sha256, runtime=runtime,
            rom=self.rom, manifest=self.manifest_path, development_preview=development,
            preflight_only=True, base=None, base_sha256=None, patch=None, patch_sha256=None,
            create_patch=False)

    def preflight(self, args):
        with patch.object(build_launcher, "os", SimpleNamespace(name="nt")), \
                patch.object(build_launcher.importlib.metadata, "version", return_value=build_launcher.PYINSTALLER), \
                patch.object(build_launcher.subprocess, "run") as process:
            try:
                build_launcher.build(args)
            finally:
                process.assert_not_called()
                self.assertFalse(args.output.exists())

    def test_normal_preflight_refuses_real_verified_legacy_before_any_build(self):
        args = self.build_args()
        before = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        with self.assertRaisesRegex(ValueError, "requires the compiled player build guard"):
            self.preflight(args)
        self.assertEqual(before, {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()})

    def test_explicit_development_preflight_retains_legacy_exception(self):
        args = self.build_args(development=True)
        output = io.StringIO()
        with redirect_stdout(output):
            self.preflight(args)
        result = json.loads(output.getvalue())
        self.assertTrue(result["development_preview"])
        self.assertFalse(result["package_created"])

    def test_development_does_not_bypass_advertised_invalid_guard(self):
        self.guarded()
        data = bytearray(self.rom.read_bytes())
        struct.pack_into("<I", data, 276, 1)
        self.rom.write_bytes(data)
        self.publish()
        args = self.build_args(development=True)
        with self.assertRaisesRegex(ValueError, "development controls"):
            self.preflight(args)


if __name__ == "__main__":
    unittest.main()
