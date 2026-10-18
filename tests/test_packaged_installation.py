"""A packaged native installation needs no game.gba: the pinned game facts stand in for the ROM.

Covers game_facts.py, the facts mode of companion.verify_rom_manifest, RuntimeBundle's
"game_facts" pin, GameInstallation/LauncherRelease, and installation_check.check_installation.
The world build id must stay the ROM SHA-256, so worlds, invitations and saves made with a ROM
open unchanged from the facts.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from emerald_multiplayer.battle_controller import read_string_lengths
from emerald_multiplayer.companion import verify_rom_manifest
from emerald_multiplayer.game_facts import (FILE_NAME, GameFactsError, build_facts, encode_facts, is_game_facts,
                                            load_facts)
from emerald_multiplayer.host_world import HostWorld
from emerald_multiplayer.installation_check import REPAIR_STEPS, SAVES_KEPT, check_installation
from emerald_multiplayer.launcher_session import GameInstallation, LauncherSessionError
from emerald_multiplayer.player_runtime import PlayerRuntimeError, RuntimeBundle
from package_fixture import Package, sha
from test_companion import make_files
from test_save_manifest import generator


def codes(report):
    return [problem.code for problem in report.problems]


def make_battle_files(directory):
    """A synthetic ROM whose generated manifest has the native battle capability and a string table."""
    rom, _ = make_files(directory)
    data = bytearray(rom.read_bytes()) + bytes(8192 - len(rom.read_bytes()))
    data[0xC0:0xCC] = b"\x01\0\0\0" + b"\x01\0\0\0" + b"\x03\0\0\0"     # ownership, trade, battle ABI 3
    table = [0] * 721
    for index, start, text in ((8, 0x1000, b"\x01\x02\xff"), (9, 0x1100, b"\x05" * 28 + b"\xff"),
                               (30, 0x1200, b"\xff"), (700, 0x1300, b"\x07" * 300)):
        data[start:start + len(text)] = text
        table[index] = 0x08000000 + start
    struct.pack_into("<721I", data, 0x300, *table)
    rom.write_bytes(bytes(data))
    elf = Path(directory) / "synthetic.elf"
    elf.write_bytes(b"synthetic symbol fixture")
    symbols = ("02020000 00000080 B gMultiplayerMailbox\n02001000 00000960 B gParties\n"
               "02001960 00000004 B gPartiesCount\n03000000 00000004 B gSaveBlock1Ptr\n"
               "02021000 00000200 B gMultiplayerSaveMailbox\n080000c0 00000004 R gMultiplayerOwnershipAbi\n"
               "080000c4 00000004 R gMultiplayerTradeAbiVersion\n080000c8 00000004 R gMultiplayerBattleAbiVersion\n"
               "02022000 00000200 B gMultiplayerBattleMailbox\n08000300 00000b44 R gBattleStringsTable\n")
    with patch.object(generator.subprocess, "check_output", return_value=symbols):
        manifest = generator.generate(rom, elf, "fixture-nm", "b" * 40)
    path = Path(directory) / "manifest.json"
    path.write_text(json.dumps(manifest))
    return rom, path


class GameFactsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rom, self.manifest = make_battle_files(self.root)

    def write(self, facts, name=FILE_NAME):
        path = self.root / name
        path.write_bytes(encode_facts(facts))
        return path

    def test_facts_give_the_same_build_and_manifest_as_the_rom(self):
        facts = build_facts(self.rom, self.manifest)
        path = self.write(facts)
        self.assertEqual(verify_rom_manifest(path, self.manifest), verify_rom_manifest(self.rom, self.manifest))
        self.assertEqual(facts["rom_sha256"], sha(self.rom))
        self.assertEqual(facts["manifest_sha256"], sha(self.manifest))
        # The markers the companion checks are recorded with the ROM bytes they had.
        self.assertEqual(facts["markers"], {"battle_abi_address": "03000000", "trade_abi_address": "01000000"})

    def test_battle_message_lengths_are_recorded_from_the_rom(self):
        facts = build_facts(self.rom, self.manifest)
        table = json.loads(self.manifest.read_text())["battle_string_table_address"]
        expected = read_string_lengths(self.rom, table_address=table)
        self.assertEqual(tuple(facts["battle_string_lengths"]), expected)
        self.assertEqual(expected[8:10], (2, 28))
        self.assertEqual((expected[30], expected[700], expected[0]), (0, 256, None))
        loaded = load_facts(self.write(facts), self.manifest.read_bytes(), json.loads(self.manifest.read_text()))
        self.assertEqual(loaded.battle_string_lengths, expected)

    def test_facts_for_another_manifest_or_build_are_refused(self):
        facts = build_facts(self.rom, self.manifest)
        other = dict(json.loads(self.manifest.read_text()), engine_commit="c" * 40)
        changed = self.root / "other.json"
        changed.write_text(json.dumps(other))
        with self.assertRaisesRegex(ValueError, "another game manifest"):
            verify_rom_manifest(self.write(facts), changed)
        for key, value in (("rom_sha256", "0" * 64), ("rom_size", 4096), ("rom_crc32", "00000000")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                verify_rom_manifest(self.write(dict(facts, **{key: value})), self.manifest)

    def test_malformed_facts_are_refused(self):
        facts = build_facts(self.rom, self.manifest)
        broken = (dict(facts, format="other"), dict(facts, extra=1),
                  dict(facts, markers={}), dict(facts, markers=dict(facts["markers"], trade_abi_address="01")),
                  dict(facts, battle_string_lengths=facts["battle_string_lengths"][:-1]),
                  dict(facts, battle_string_lengths=[300] * 721),
                  dict(facts, battle_string_table_address=facts["battle_string_table_address"] + 4),
                  {key: value for key, value in facts.items() if key != "battle_string_lengths"})
        for value in broken:
            with self.subTest(value=sorted(value)), self.assertRaises(GameFactsError):
                load_facts(self.write(value), self.manifest.read_bytes(), json.loads(self.manifest.read_text()))
        path = self.root / FILE_NAME
        path.write_bytes(b'{"format": "emerald-game-facts-v1", "format": "x"}')
        with self.assertRaises(GameFactsError):
            load_facts(path, self.manifest.read_bytes(), json.loads(self.manifest.read_text()))
        path.write_bytes(b" " * 70_000)
        with self.assertRaises(GameFactsError):
            load_facts(path, self.manifest.read_bytes(), json.loads(self.manifest.read_text()))

    def test_only_a_rom_builds_facts_and_names_tell_them_apart(self):
        self.assertTrue(is_game_facts(Path("runtime") / FILE_NAME))
        self.assertFalse(is_game_facts(Path("games") / "game.gba"))
        with self.assertRaises(GameFactsError):
            build_facts(self.write(build_facts(self.rom, self.manifest)), self.manifest)


class PackagedInstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.package = Package(Path(self.temp.name) / "package")

    def test_packaged_layout_without_game_gba_verifies(self):
        installation = self.package.installation()
        self.assertTrue(installation.uses_game_facts)
        self.assertEqual(installation.rom_path, (self.package.runtime / FILE_NAME).resolve())
        installation.verify()
        replace_2d = installation.bundle.verify("2d")
        self.assertEqual(replace_2d[0].name, "pokeemerald-mp.exe")
        report = check_installation(installation)
        self.assertTrue(report.ok, report.text())
        self.assertTrue(report.uses_game_facts)
        self.assertIn("installed correctly", report.text())
        self.assertFalse((self.package.private / "games").exists())   # nothing was installed or expected there

    def test_world_build_id_stays_the_rom_sha256(self):
        installation = self.package.installation()
        self.assertEqual(self.package.release.rom_sha256, sha(self.package.rom))
        names = dict(player_names=["Host", "Friend"], endpoint="127.0.0.1", port=8765)
        from_rom = HostWorld.create(Path(self.temp.name) / "rom-world", self.package.rom, self.package.manifest, **names)
        from_facts = HostWorld.create(Path(self.temp.name) / "facts-world", installation.rom_path,
                                      installation.manifest_path, **names)
        self.assertEqual(from_rom.build_id, sha(self.package.rom))
        self.assertEqual(from_facts.build_id, from_rom.build_id)
        # A world (and its invitations) created with the ROM opens unchanged from the package's facts, and back.
        self.assertEqual(HostWorld.open(from_rom.directory, installation.rom_path, installation.manifest_path), from_rom)
        self.assertEqual(HostWorld.open(from_facts.directory, self.package.rom, self.package.manifest), from_facts)
        invitation = from_rom.invitation(1)
        config = invitation.companion_config(installation.rom_path, installation.manifest_path, token=b"t" * 32,
                                             private_directory=Path(self.temp.name) / "friend")
        self.assertEqual(config.build_id, invitation.build_id)
        self.assertEqual(config.build_id, sha(self.package.rom))

    def test_a_stale_game_gba_in_private_storage_does_not_matter(self):
        stale = self.package.private / "games" / self.package.release.rom_sha256 / "game.gba"
        stale.parent.mkdir(parents=True)
        stale.write_bytes(b"a renamed file from another build")
        installation = self.package.installation()
        self.assertTrue(installation.uses_game_facts)
        installation.verify()
        self.assertTrue(check_installation(installation).ok)

    def assert_problem(self, report, code, name=None):
        self.assertFalse(report.ok)
        self.assertEqual(codes(report), [code], report.text())
        problem = report.problems[0]
        if name is not None:
            self.assertIn(name, problem.title)
            self.assertIn(name, problem.message)
        self.assertIn(SAVES_KEPT, problem.steps)
        self.assertNotIn(str(self.package.root), report.text())       # no private paths in what the player reads
        return problem

    def test_tampered_or_missing_game_executable(self):
        installation = self.package.installation()
        game = self.package.runtime / "pokeemerald-mp-diorama.exe"
        game.write_bytes(game.read_bytes() + b"!")
        with self.assertRaises(PlayerRuntimeError) as caught:
            installation.verify()
        self.assertEqual(caught.exception.code, "runtime_hash")
        problem = self.assert_problem(check_installation(installation), "game_changed", "pokeemerald-mp-diorama.exe")
        self.assertEqual(problem.steps, REPAIR_STEPS)
        self.assertIn("Setup file again", problem.text())
        game.unlink()
        problem = self.assert_problem(check_installation(installation), "game_missing", "pokeemerald-mp-diorama.exe")
        self.assertIn("antivirus", problem.steps[-1])

    def test_each_kind_of_package_file_is_named(self):
        installation = self.package.installation()
        runtime = self.package.runtime
        cases = (("SDL2.dll", "missing", "sdl_missing"), ("battle-sprites.ebsp", "changed", "sprites_changed"),
                 ("pokeemerald-mp.exe", "changed", "classic_game_changed"),
                 ("game-facts.json", "missing", "game_facts_missing"))
        for name, state, code in cases:
            with self.subTest(name=name):
                original = (runtime / name).read_bytes()
                if state == "missing":
                    (runtime / name).unlink()
                else:
                    (runtime / name).write_bytes(original + b"\0")
                self.assert_problem(check_installation(installation), code, name)
                with self.assertRaises(Exception):
                    installation.verify()
                (runtime / name).write_bytes(original)
                self.assertTrue(check_installation(installation).ok)

    def test_tampered_or_missing_manifest(self):
        installation = self.package.installation()
        manifest = self.package.application / "game-manifest.json"
        original = manifest.read_bytes()
        manifest.write_bytes(original.replace(b"}", b', "extra": 1}'))
        with self.assertRaises(LauncherSessionError) as caught:
            installation.verify()
        self.assertEqual(caught.exception.code, "installation_changed")
        self.assert_problem(check_installation(installation), "manifest_changed", "game-manifest.json")
        manifest.unlink()
        self.assert_problem(check_installation(installation), "manifest_missing", "game-manifest.json")

    def test_rewritten_facts_are_caught_by_the_runtime_pin(self):
        installation = self.package.installation()
        facts_path = self.package.runtime / FILE_NAME
        facts = json.loads(facts_path.read_text())
        facts["markers"] = {name: "00" * (len(value) // 2) for name, value in facts["markers"].items()}
        facts_path.write_bytes(encode_facts(facts))
        with self.assertRaises(PlayerRuntimeError) as caught:
            installation.verify()
        self.assertEqual(caught.exception.code, "runtime_hash")
        self.assert_problem(check_installation(installation), "game_facts_changed", FILE_NAME)

    def test_runtime_record_and_unlisted_programs(self):
        installation = self.package.installation()
        extra = self.package.runtime / "helper.dll"
        extra.write_bytes(b"unknown library")
        with self.assertRaises(PlayerRuntimeError) as caught:
            installation.verify()
        self.assertEqual(caught.exception.code, "runtime_unlisted")
        self.assertIn("helper.dll", self.assert_problem(check_installation(installation), "runtime_unlisted").message)
        extra.unlink()
        record = self.package.runtime / "runtime.json"
        record.write_bytes(record.read_bytes() + b"\n")
        self.assert_problem(check_installation(installation), "runtime_record_changed", "runtime.json")
        record.unlink()
        self.assert_problem(check_installation(installation), "runtime_record_missing", "runtime.json")
        # Started without a runtime record the installation cannot know about facts; one report, not two.
        self.assertEqual(codes(check_installation(self.package.installation())), ["runtime_record_missing"])

    def test_facts_count_only_when_the_pinned_runtime_names_them(self):
        installation = self.package.installation()
        other = Path(self.temp.name) / "elsewhere" / FILE_NAME
        other.parent.mkdir()
        other.write_bytes((self.package.runtime / FILE_NAME).read_bytes())
        moved = GameInstallation(other, installation.manifest_path, installation.rom_sha256,
                                 installation.manifest_sha256, installation.bundle)
        with self.assertRaises(LauncherSessionError):
            moved.verify()
        self.assertEqual(codes(check_installation(moved)), ["game_facts_changed"])

    def test_battle_message_lengths_come_from_the_facts(self):
        root = Path(self.temp.name) / "battle"
        root.mkdir()
        rom, manifest = make_battle_files(root)
        package = Package(root / "package", rom=rom, manifest=manifest)
        installation = package.installation()
        self.assertTrue(installation.uses_game_facts)
        installation.verify()
        table = json.loads(manifest.read_text())["battle_string_table_address"]
        dev = GameInstallation(rom, installation.manifest_path, installation.rom_sha256,
                               installation.manifest_sha256, installation.bundle)
        self.assertEqual(installation.battle_string_lengths(table), read_string_lengths(rom, table_address=table))
        self.assertEqual(dev.battle_string_lengths(table), installation.battle_string_lengths(table))
        with self.assertRaises(LauncherSessionError):
            installation.battle_string_lengths(table + 4)

    def test_the_emulator_runtime_and_trade_replay_never_take_facts(self):
        installation = self.package.installation()
        emulator = Path(self.temp.name) / "emulator"
        emulator.mkdir()
        (emulator / "mGBA.exe").write_bytes(b"MZ fixture")
        (emulator / "bridge.lua").write_text("-- fixture\n")
        record = json.dumps(dict(format="emerald-windows-runtime-v1", executable="mGBA.exe", bridge="bridge.lua",
                                 files={name: sha(emulator / name) for name in ("mGBA.exe", "bridge.lua")})).encode()
        (emulator / "runtime.json").write_bytes(record)
        bundle = RuntimeBundle(emulator, hashlib.sha256(record).hexdigest())
        self.assertIsNone(bundle.game_facts_path())
        mixed = GameInstallation(installation.rom_path, installation.manifest_path, installation.rom_sha256,
                                 installation.manifest_sha256, bundle)
        with self.assertRaises(LauncherSessionError):
            mixed.verify()
        from emerald_multiplayer.trade_native_replay import NativeReplayError, NativeTradeReplay
        with self.assertRaises(NativeReplayError):
            NativeTradeReplay(installation.rom_path, installation.manifest_path, installation.bundle)

    def test_runtime_record_names_only_its_own_facts_file(self):
        record = json.loads((self.package.runtime / "runtime.json").read_text())
        for value in ("other.json", "pokeemerald-mp.exe", 1):
            raw = json.dumps(dict(record, game_facts=value)).encode()
            (self.package.runtime / "runtime.json").write_bytes(raw)
            with self.subTest(value=value), self.assertRaises(PlayerRuntimeError) as caught:
                RuntimeBundle(self.package.runtime, hashlib.sha256(raw).hexdigest()).verify()
            self.assertEqual(caught.exception.code, "runtime_manifest")


class DevelopmentInstallationTests(unittest.TestCase):
    """Setups that still have a game.gba (tests, the mGBA replay worker, an imported game) verify it as before."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.package = Package(Path(self.temp.name) / "package", facts=False)

    def test_without_facts_the_package_checks_the_imported_game(self):
        installation = self.package.installation()
        self.assertFalse(installation.uses_game_facts)
        target = self.package.private / "games" / self.package.release.rom_sha256 / "game.gba"
        self.assertEqual(installation.rom_path, target)
        with self.assertRaises(FileNotFoundError):
            installation.verify()
        report = check_installation(installation)
        self.assertEqual(codes(report), ["rom_missing"])
        self.assertIn("Setup file", report.problems[0].steps[0])
        importer = object()
        self.assertIn("Settings, Game files", check_installation(installation, importer=importer).problems[0].steps[0])
        target.parent.mkdir(parents=True)
        target.write_bytes(self.package.rom.read_bytes())
        installation.verify()
        self.assertTrue(check_installation(installation).ok)
        target.write_bytes(target.read_bytes()[:-1] + b"\0")
        with self.assertRaises(ValueError):
            installation.verify()
        self.assertEqual(codes(check_installation(installation, importer=importer)), ["rom_changed"])

    def test_a_dev_layout_with_game_gba_still_verifies(self):
        installation = self.package.installation()
        dev = GameInstallation(self.package.rom, installation.manifest_path, installation.rom_sha256,
                               installation.manifest_sha256, installation.bundle)
        self.assertFalse(dev.uses_game_facts)
        dev.verify()
        self.assertTrue(check_installation(dev).ok)

    def test_check_never_raises(self):
        report = check_installation(object())
        self.assertFalse(report.ok)
        self.assertEqual(codes(report), ["unverified"])


if __name__ == "__main__":
    unittest.main()
