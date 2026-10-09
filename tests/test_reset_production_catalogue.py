"""Synthetic compiler/ROM descriptors and disposable ledgers, not gameplay proof."""
import json
import struct
from types import SimpleNamespace
import unittest
from uuid import uuid4

from emerald_multiplayer.companion import CompanionConfig
from emerald_multiplayer.reset_catalogue import (ALL_SOURCES, DESCRIPTOR, FIELDS,
    require_production_reset_manifest, validate_reset_catalogue, reset_source_catalogue, reset_controls)
from emerald_multiplayer.reset_attempts import require_reset_ledger, enable_reset_attempts
from emerald_multiplayer.reset_protocol import SOURCES
from emerald_multiplayer.storage import StorageError
from emerald_multiplayer.trade_storage import TradeCheckpointStore
import test_save_manifest as fixtures


class ProductionResetCatalogueTests(unittest.TestCase):
    tearDown = fixtures.SaveManifestTests.tearDown
    generate = fixtures.SaveManifestTests.generate
    configure = fixtures.SaveManifestTests.configure

    def setUp(self):
        fixtures.SaveManifestTests.setUp(self)
        self.extra = ("02021000 00000200 B gMultiplayerSaveMailbox\n"
            "080000c0 00000004 R gMultiplayerOwnershipAbi\n"
            "080000c4 00000004 R gMultiplayerTradeAbiVersion\n"
            "080000c8 00000004 R gMultiplayerBattleAbiVersion\n"
            "02022000 00000200 B gMultiplayerBattleMailbox\n"
            "080000cc 00000004 R gMultiplayerResetAbiVersion\n"
            "02023000 00000080 B gMultiplayerResetMailbox\n"
            "080000d0 00000004 R gMultiplayerResetInputAbiVersion\n"
            "080000d4 00000004 R gMultiplayerEmergencySaveAbiVersion\n"
            "080000e0 00000018 R gMultiplayerResetCatalogue\n"
            "08000300 00000b44 R gBattleStringsTable\n")
        with self.rom.open("r+b") as rom:
            rom.seek(0xC0); rom.write(struct.pack("<6I", 1, 1, 3, 2, 1, 2))
            rom.seek(0xE0); rom.write(DESCRIPTOR.pack(1, min(SOURCES), len(SOURCES), ALL_SOURCES, 3, 0))
            rom.seek(0x300); rom.write(bytes(721 * 4))
        self.production = self.generate(self.extra)

    def test_exact_normal_all25_descriptor_is_generated_and_release_accepted(self):
        self.assertEqual(len(SOURCES), 25)
        self.assertEqual(self.production["reset_source_mask"], (1 << 25) - 1)
        self.assertEqual(self.production["reset_build_flags"], 0)
        self.assertTrue(require_production_reset_manifest(self.production, self.rom))
        self.assertIn("reset_input_abi=1", self.configure(self.production))
        self.manifest_path.write_text(json.dumps(self.production))
        config = CompanionConfig(self.rom, self.manifest_path, str(uuid4()), "Fixture", bytes(32))
        self.assertEqual(config.reset_source_mask, ALL_SOURCES)
        rows = reset_source_catalogue(config)
        self.assertEqual({row["encounter_id"] for row in rows}, set(SOURCES))
        self.assertTrue(all(row["availability"] == "enabled" and row["eligibility"] == "UNKNOWN" for row in rows))

    def test_omitted_pilot_disabled_development_testing_or_old_recovery_cannot_release(self):
        changes = [{"reset_source_mask": 0}, {"reset_source_mask": 1},
            {"reset_build_flags": 1}, {"reset_build_flags": 2}, {"reset_build_flags": 3},
            {"reset_control_flags": 0}, {"reset_abi_version": 1},
            {"reset_input_abi_version": 0}, {"emergency_save_abi_version": 1},
            {"battle_execution_abi_version": 0}]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                require_production_reset_manifest({**self.production, **change})
        for field in FIELDS | {"reset_abi_version", "emergency_save_abi_version", "battle_execution_abi_version"}:
            changed = dict(self.production); del changed[field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                require_production_reset_manifest(changed)

    def test_compiler_descriptor_first_count_flags_and_allocations_are_exact(self):
        original = self.rom.read_bytes()
        values = (1, min(SOURCES), len(SOURCES), ALL_SOURCES, 3, 0)
        for index, changed in enumerate((2, min(SOURCES) + 1, 24, 1, 0, 1)):
            words = list(values); words[index] = changed
            with self.rom.open("r+b") as rom:
                rom.seek(0xE0); rom.write(DESCRIPTOR.pack(*words))
            with self.subTest(index=index), self.assertRaises(ValueError):
                validate_reset_catalogue(self.production, self.rom)
            self.rom.write_bytes(original)
        for symbol in (self.extra + "080000e0 00000018 R gMultiplayerResetCatalogue\n",
            self.extra.replace("080000e0 00000018", "080000e0 00000014"),
            self.extra.replace("080000e0 00000018", "080000cc 00000018")):
            with self.subTest(symbol=symbol), self.assertRaises(ValueError):
                self.generate(symbol)

    def test_legacy_input_contract_never_invents_source_availability(self):
        unknown = SimpleNamespace(reset_input_abi_version=1)
        self.assertTrue(all(row["availability"] == "unknown" for row in reset_source_catalogue(unknown)))
        self.assertEqual(reset_controls(unknown)["status"], "enabled")
        pilot = SimpleNamespace(reset_catalogue_version=1, reset_source_mask=1,
            reset_control_flags=3, reset_input_abi_version=1)
        self.assertEqual([r["availability"] for r in reset_source_catalogue(pilot)], ["enabled"] + ["disabled"] * 24)

    def test_enabled_host_requires_existing_durable_ledger_without_silent_upgrade(self):
        with TradeCheckpointStore(self.rom.parent / "disposable-world", "fixture", "rules") as store:
            before = tuple(store._connection.iterdump())
            with self.assertRaises(StorageError) as caught:
                require_reset_ledger(store, self.production)
            self.assertEqual(caught.exception.code, "reset_migration_required")
            self.assertEqual(tuple(store._connection.iterdump()), before)
            self.assertTrue(require_reset_ledger(store, {}))
            enable_reset_attempts(store, self.rom.parent / "explicit-disposable-backup")
            self.assertTrue(require_reset_ledger(store, self.production))
