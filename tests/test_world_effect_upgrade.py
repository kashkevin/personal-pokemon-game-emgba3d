"""Real disposable SQLite provisioning; synthetic ROM markers, no native launch."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from uuid import uuid4
import zlib

from emerald_multiplayer.companion import verify_rom_manifest
from emerald_multiplayer.character_transfers import EXTENSION_VERSION as TRANSFERS
from emerald_multiplayer.host_world import HostWorld, HostWorldError
from emerald_multiplayer.launcher_session import GameInstallation
from emerald_multiplayer.launcher_setup import LauncherSetupError, upgrade_world_features
from emerald_multiplayer.trade_effect_storage import read_effect_policy
from emerald_multiplayer.trade_replay_manifest import MAGIC, HEAP_SIZE, INPUT_MAX, OUTPUT_MAX
from emerald_multiplayer.trade_storage import TradeCheckpointStore
from test_host_world import make_trade_files
from test_ownership_storage import source_flash, owned_flash
from test_player_runtime import write_bundle


POLICIES = ("gen6-stable-world-region-v1", "gen6-absent-geography-refresh-v1")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def effect_installation(root):
    """A verified marker fixture; never executable or native replay evidence."""
    rom, manifest = make_trade_files(root)
    raw = bytearray(rom.read_bytes())
    for offset, value in ((4, 2), (8, 1), (12, 1), (16, 1), (20, 1), (24, 2)):
        struct.pack_into("<I", raw, offset, value)
    struct.pack_into("<8I", raw, 64, MAGIC, 1, 0x08000101, 0x02000000,
                     HEAP_SIZE, INPUT_MAX, OUTPUT_MAX, 0)
    rom.write_bytes(raw)
    value = json.loads(manifest.read_text())
    value.update(rom_sha256=digest(rom), rom_crc32=f"{zlib.crc32(raw):08x}",
        menu_abi_version=2, menu_abi_address=0x08000004,
        menu_mailbox_address=0x02022000, menu_mailbox_size=512,
        trade_effect_prepare_abi_version=1, trade_effect_prepare_abi_address=0x08000008,
        trade_effect_save_abi_version=1, trade_effect_save_abi_address=0x0800000C,
        trade_effect_choice_abi_version=1, trade_effect_choice_abi_address=0x08000010,
        save_window_abi_version=1, save_window_abi_address=0x08000014,
        save_window_address=0x02023000, save_window_size=4096,
        reset_abi_version=2, reset_abi_address=0x08000018,
        reset_mailbox_address=0x02025000, reset_mailbox_size=128,
        trade_replay_abi_version=1, trade_replay_descriptor_address=0x08000040)
    manifest.write_text(json.dumps(value))
    legacy = root / "legacy-manifest.json"
    legacy.write_text(json.dumps({k: v for k, v in value.items()
                                 if not k.startswith(("trade_replay_", "reset_"))}))
    # Verify both fixture manifests through the actual marker validators.
    assert verify_rom_manifest(rom, manifest)[0] == verify_rom_manifest(rom, legacy)[0]
    bundle_path = root / "bundle"
    bundle_path.mkdir()
    installation = GameInstallation(rom, manifest, digest(rom), digest(manifest), write_bundle(bundle_path))
    installation.verify()
    return installation, legacy


class WorldEffectUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.installation, self.legacy_manifest = effect_installation(self.root)

    def create(self, name="world", *, legacy=False, policy=None):
        return HostWorld.create(self.root / name, self.installation.rom_path,
            self.legacy_manifest if legacy else self.installation.manifest_path,
            player_names=("Host", "Friend"), endpoint="127.0.0.1", port=8765,
            trade_effect_policy=policy)

    def upgrade(self, host, policy=POLICIES[0], installation=None):
        return upgrade_world_features(installation or self.installation, host.directory,
                                      trade_effect_policy=policy)

    def backup_hashes(self, host):
        return {p.name: digest(p) for p in host.directory.glob("*before-*.sqlite3")}

    def original_rows(self, store, tables=None):
        if tables is None:
            tables = [r[0] for r in store._connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {name: tuple(tuple(r) for r in store._connection.execute('SELECT * FROM "' + name + '"'))
                for name in tables}

    def unchanged_refusal(self, host, policy, code, *, installation=None):
        before_backups = self.backup_hashes(host)
        before_files = {name: digest(host.directory / name)
                        for name in ("host.json", "host-key.pem", "host-certificate.pem")}
        with host.open_store() as store:
            before_rows = self.original_rows(store)
            before_version = store._connection.execute("PRAGMA user_version").fetchone()[0]
        with self.assertRaises(LauncherSetupError) as caught:
            self.upgrade(host, policy, installation)
        self.assertEqual(caught.exception.code, code)
        with host.open_store() as store:
            self.assertEqual(self.original_rows(store), before_rows)
            self.assertEqual(store._connection.execute("PRAGMA user_version").fetchone()[0], before_version)
            store.integrity_check()
        self.assertEqual(self.backup_hashes(host), before_backups)
        self.assertEqual({name: digest(host.directory / name) for name in before_files}, before_files)

    def test_new_effect_world_requires_explicit_valid_policy_before_creation(self):
        for policy in (None, "", "unknown-policy"):
            with self.subTest(policy=policy), self.assertRaises(HostWorldError) as caught:
                self.create(name="refused", policy=policy)
            self.assertEqual(caught.exception.code, "trade_effect_policy_required")
            self.assertFalse((self.root / "refused").exists())

    def test_new_world_enables_both_explicit_policies_and_preserves_valid_backups(self):
        for i, policy in enumerate(POLICIES):
            with self.subTest(policy=policy):
                host = self.create(name="new-" + str(i), policy=policy)
                original = self.backup_hashes(host)
                self.assertEqual(len(original), 4)  # reset, character transfers, history, then native effects
                with host.open_store() as store:
                    self.assertTrue(store.friendship_history_enabled)
                    self.assertTrue(store.trade_effects_enabled)
                    self.assertTrue(store.reset_attempts_enabled)
                    self.assertEqual(read_effect_policy(store), policy)
                    self.assertEqual((store.metadata.server_epoch, store.metadata.session_epoch), (0, 0))
                    rows = self.original_rows(store, ("players", "world_metadata"))
                    store.integrity_check()
                for name in original:
                    with TradeCheckpointStore(host.directory / name, host.build_id, host.ruleset_id,
                                              host.save_profile) as backup:
                        backup.integrity_check()
                        self.assertEqual(self.original_rows(backup, rows), rows)
                        self.assertFalse(backup.trade_effects_enabled)
                self.assertEqual(self.backup_hashes(host), original)

    def test_legacy_creation_is_unchanged_and_refuses_unsuitable_policy(self):
        host = self.create(legacy=True)
        with host.open_store() as store:
            self.assertFalse(store.friendship_history_enabled)
            self.assertFalse(store.trade_effects_enabled)
            # Every new world takes its characters back (character_transfers.py); nothing else is added.
            self.assertEqual(store._connection.execute("PRAGMA user_version").fetchone()[0], 3 + TRANSFERS)
        self.assertEqual(set(self.backup_hashes(host)), {"before-character-transfers.sqlite3"})
        with self.assertRaises(HostWorldError) as caught:
            self.create(name="legacy-refused", legacy=True, policy=POLICIES[0])
        self.assertEqual(caught.exception.code, "trade_effect_policy_required")
        self.assertFalse((self.root / "legacy-refused").exists())

    def test_populated_same_build_upgrade_preserves_heads_identity_and_preimage_backups(self):
        host = self.create(legacy=True)
        account = host.accounts[0]
        with host.open_store() as store:
            store.begin_server_boot()
            lease = store.acquire_lease(account.player_id, account.credential)
            store.enroll_player(account.player_id, source_flash())
            grant = store.reserve_instances(account.player_id, lease, str(uuid4()), 0, 1, 1)
            payload = owned_flash(grant)
            head = store.commit_checkpoint(account.player_id, lease, str(uuid4()), 0, payload,
                                           host.build_id, host.ruleset_id, host.save_profile)
            store.release_lease(account.player_id, lease)
            before_rows = self.original_rows(store)
            before_metadata = store.metadata
        descriptor = (host.directory / "host.json").read_bytes()
        created = self.backup_hashes(host)                 # the new world's own (character transfers, before any play)
        self.assertEqual(self.upgrade(host), host.directory)
        backups = {name: value for name, value in self.backup_hashes(host).items() if name not in created}
        self.assertEqual(len(backups), 3)
        with host.open_store() as store:
            self.assertEqual(self.original_rows(store, before_rows), before_rows)
            self.assertEqual(store.metadata, before_metadata)
            self.assertEqual(read_effect_policy(store), POLICIES[0])
            row = store._connection.execute("SELECT payload,sha256 FROM checkpoints WHERE player_id=? AND revision=?",
                                             (account.player_id, head.revision)).fetchone()
            self.assertEqual(tuple(row), (payload, head.sha256))
            self.assertEqual(store._connection.execute("SELECT count(*) FROM pokemon_friendship_history").fetchone()[0], 1)
            self.assertTrue(store.reset_attempts_enabled)
            store.integrity_check()
        for name in backups:
            with TradeCheckpointStore(host.directory / name, host.build_id, host.ruleset_id,
                                      host.save_profile) as backup:
                backup.integrity_check()
                self.assertEqual(self.original_rows(backup, before_rows), before_rows)
        self.assertEqual(self.backup_hashes(host), {**created, **backups})
        self.assertEqual((host.directory / "host.json").read_bytes(), descriptor)

    def test_upgrade_rejects_missing_policy_or_non_replay_manifest_without_changes(self):
        host = self.create(legacy=True)
        for policy in (None, "", "unknown-policy"):
            with self.subTest(policy=policy):
                self.unchanged_refusal(host, policy, "trade_effect_policy_required")
        legacy_installation = replace(self.installation, manifest_path=self.legacy_manifest,
                                      manifest_sha256=digest(self.legacy_manifest))
        self.unchanged_refusal(host, POLICIES[0], "trade_effect_policy_required", installation=legacy_installation)

    def test_different_verified_rom_is_not_a_world_upgrade(self):
        host = self.create(legacy=True)
        second = self.root / "other-installation"
        second.mkdir()
        candidate, _ = effect_installation(second)
        raw = bytearray(candidate.rom_path.read_bytes())
        raw[-1] ^= 1
        candidate.rom_path.write_bytes(raw)
        value = json.loads(candidate.manifest_path.read_text())
        value.update(rom_sha256=digest(candidate.rom_path), rom_crc32=f"{zlib.crc32(raw):08x}")
        candidate.manifest_path.write_text(json.dumps(value))
        candidate = replace(candidate, rom_sha256=digest(candidate.rom_path),
                            manifest_sha256=digest(candidate.manifest_path))
        candidate.verify()
        self.assertNotEqual(candidate.rom_sha256, host.build_id)
        self.unchanged_refusal(host, POLICIES[0], "world_invalid", installation=candidate)

    def test_active_owner_lock_refuses_even_without_player_leases(self):
        host = self.create(legacy=True)
        with host.open_store() as active:
            active.begin_server_boot()
            self.unchanged_refusal(host, POLICIES[0], "world_active")
            self.assertIsNotNone(active._owner_lock)
        # Refusal must not leave a second lock owned after the first host closes.
        self.assertEqual(self.upgrade(host), host.directory)

    def test_closed_store_with_unreleased_character_lease_is_not_silently_booted(self):
        host = self.create(legacy=True)
        account = host.accounts[0]
        with host.open_store() as store:
            store.begin_server_boot()
            lease = store.acquire_lease(account.player_id, account.credential)
        self.unchanged_refusal(host, POLICIES[0], "world_active")
        with host.open_store() as store:
            self.assertEqual(store._connection.execute("SELECT lease_epoch FROM players WHERE player_id=?",
                                                       (account.player_id,)).fetchone()[0], lease)

    def test_existing_policy_cannot_change_and_same_policy_replay_creates_no_backups(self):
        host = self.create(policy=POLICIES[0])
        before = self.backup_hashes(host)
        self.unchanged_refusal(host, POLICIES[1], "trade_effect_policy_required")
        with host.open_store() as store:
            rows = self.original_rows(store)
        self.assertEqual(self.upgrade(host), host.directory)
        self.assertEqual(self.backup_hashes(host), before)
        with host.open_store() as store:
            self.assertEqual(self.original_rows(store), rows)
            self.assertEqual(read_effect_policy(store), POLICIES[0])
            store.integrity_check()


if __name__ == "__main__":
    unittest.main()
