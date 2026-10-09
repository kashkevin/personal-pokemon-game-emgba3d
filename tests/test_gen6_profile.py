"""Identity/provisioning checks only; synthetic ROMs are not gameplay evidence."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import secrets
import tempfile
import unittest
import uuid
import zlib

from emerald_multiplayer.companion import BASELINE_RULESET, CompanionConfig, verify_rom_manifest, validate_welcome
from emerald_multiplayer.gen6_profile import DESCRIPTOR, GEN6_DEFAULTS_RULESET, validate_generation_profile
from emerald_multiplayer.host_world import HostWorld
from emerald_multiplayer.invitations import Invitation, InvitationError
from emerald_multiplayer.protocol import ProtocolError
from test_host_world import make_trade_files, directory_hashes


def add_profile(rom, manifest):
    data = rom.read_bytes()[:256] + DESCRIPTOR + rom.read_bytes()[256 + len(DESCRIPTOR):]
    rom.write_bytes(data)
    value = json.loads(manifest.read_text())
    value.update(ruleset_id=GEN6_DEFAULTS_RULESET, generation_profile_version=1,
                 generation_profile_address=0x08000100,
                 rom_sha256=hashlib.sha256(data).hexdigest(), rom_crc32=f"{zlib.crc32(data):08x}")
    manifest.write_text(json.dumps(value))
    return value


class GenerationProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rom, self.manifest = make_trade_files(self.root)

    def test_legacy_stays_legacy_and_new_client_negotiates_new_rules(self):
        config = lambda: CompanionConfig(self.rom, self.manifest, str(uuid.uuid4()), "Player", secrets.token_bytes(32))
        self.assertEqual(config().ruleset_id, BASELINE_RULESET)
        value = add_profile(self.rom, self.manifest)
        current = config()
        self.assertEqual(current.ruleset_id, GEN6_DEFAULTS_RULESET)
        welcome = dict(type="welcome", protocol=1, build_id=current.build_id,
                       ruleset_id=current.ruleset_id, player_id=current.player_id,
                       session_epoch=1, max_players=4, heartbeat_interval=5, idle_timeout=20)
        validate_welcome(welcome, current)
        with self.assertRaises(ProtocolError):
            validate_welcome({**welcome, "ruleset_id": BASELINE_RULESET}, current)
        self.assertTrue(validate_generation_profile(value, self.rom))

    def test_declaration_cannot_be_partial_or_relabel_baseline(self):
        original = add_profile(self.rom, self.manifest)
        bad = [
            {**original, "ruleset_id": BASELINE_RULESET},
            {**original, "generation_profile_version": True},
            {**original, "generation_profile_address": 0x08000101},
            {**original, "generation_profile_address": 0x0A000000},
            {**original, "generation_profile_address": 0x08010000},
        ]
        for name in ("generation_profile_version", "generation_profile_address"):
            value = dict(original); value.pop(name); bad.append(value)
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_generation_profile(value, self.rom)

    def test_rehashed_rom_with_one_later_setting_is_rejected(self):
        value = add_profile(self.rom, self.manifest)
        for index in range(20):
            data = bytearray(self.rom.read_bytes())
            data[256:256 + len(DESCRIPTOR)] = DESCRIPTOR
            data[256 + 4 * index] ^= 1
            self.rom.write_bytes(data)
            value.update(rom_sha256=hashlib.sha256(data).hexdigest(), rom_crc32=f"{zlib.crc32(data):08x}")
            self.manifest.write_text(json.dumps(value))
            with self.subTest(word=index), self.assertRaises(ValueError):
                verify_rom_manifest(self.rom, self.manifest)

    def test_new_world_and_portable_invitation_keep_exact_profile_old_world_refuses(self):
        old = HostWorld.create(self.root / "old", self.rom, self.manifest,
                              player_names=["Host", "Friend"], endpoint="127.0.0.1", port=8765)
        before = directory_hashes(old.directory)
        add_profile(self.rom, self.manifest)
        with self.assertRaises(ValueError):
            HostWorld.open(old.directory, self.rom, self.manifest)
        self.assertEqual(directory_hashes(old.directory), before)
        new = HostWorld.create(self.root / "new", self.rom, self.manifest,
                              player_names=["Host", "Friend"], endpoint="127.0.0.1", port=8765)
        self.assertEqual(new.ruleset_id, GEN6_DEFAULTS_RULESET)
        invitation = Invitation.loads(new.invitation(1).dumps())
        config = invitation.companion_config(self.rom, self.manifest, token=secrets.token_bytes(32),
                                             private_directory=self.root / "friend")
        self.assertEqual(config.ruleset_id, GEN6_DEFAULTS_RULESET)
        with self.assertRaises(InvitationError):
            replace(invitation, ruleset_id=BASELINE_RULESET).companion_config(
                self.rom, self.manifest, token=secrets.token_bytes(32), private_directory=self.root / "wrong")
        self.assertFalse((self.root / "wrong").exists())


if __name__ == "__main__":
    unittest.main()
