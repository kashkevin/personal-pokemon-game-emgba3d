from dataclasses import replace
import json
from pathlib import Path
import secrets
import tempfile
import unittest

from emerald_multiplayer.host_world import HostWorld
from emerald_multiplayer.invitations import Invitation, InvitationError, MAX_INVITATION_BYTES
from test_host_world import make_trade_files


class InvitationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared = tempfile.TemporaryDirectory()
        cls.root = Path(cls.shared.name)
        cls.rom, cls.manifest = make_trade_files(cls.root)
        cls.host = HostWorld.create(cls.root/"host", cls.rom, cls.manifest,
                                   player_names=["Host", "Friend"], endpoint="192.168.1.20", port=8765)
        cls.invite = cls.host.invitation(1)

    @classmethod
    def tearDownClass(cls):
        cls.shared.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.private = Path(self.temp.name)

    def test_roundtrip_copy_is_path_independent_and_secret_repr_is_redacted(self):
        self.invite.save(self.private/"friend.json")
        original = (self.private/"friend.json").read_bytes()
        (self.private/"copied.json").write_bytes(original)
        self.assertEqual(Invitation.load(self.private/"copied.json"), self.invite)
        self.assertEqual(Invitation.loads(original).dumps(), original)
        self.assertNotIn(self.invite.credential.hex(), repr(self.invite))
        self.assertNotIn(str(self.root), original.decode())
        with self.assertRaises(FileExistsError):
            self.invite.save(self.private/"friend.json")
        self.assertEqual((self.private/"friend.json").read_bytes(), original)

    def test_strict_json_bounds_duplicate_keys_unknown_version_and_fields(self):
        raw = self.invite.dumps()
        for invalid in (b"", b"x"*(MAX_INVITATION_BYTES+1), b"\xff", b"[]", b'{"format":"x","format":"y"}',
                        b'{"value":NaN}', raw[:-1]+b"junk"):
            with self.subTest(size=len(invalid)), self.assertRaises(InvitationError):
                Invitation.loads(invalid)
        value = json.loads(raw)
        for changes in (dict(format="future-version"), dict(slot=True), dict(port=True), dict(port=1.0),
                        dict(role="host"), dict(endpoint="example.com"), dict(endpoint="0.0.0.0"),
                        dict(endpoint="2001:0db8::1"), dict(credential=self.invite.credential.hex().upper()),
                        dict(save_profile="legacy"), dict(certificate_sha256="0"*64)):
            with self.subTest(changes=tuple(changes)), self.assertRaises(ValueError):
                Invitation.loads(json.dumps({**value, **changes}).encode())
        for key in value:
            invalid = dict(value); del invalid[key]
            with self.subTest(missing=key), self.assertRaises(InvitationError):
                Invitation.loads(json.dumps(invalid).encode())
        with self.assertRaises(InvitationError):
            Invitation.loads(json.dumps({**value, "save_path": "arbitrary/path"}).encode())
        with self.assertRaises(InvitationError):
            Invitation.loads(json.dumps({**value, "role": "host", "slot": 0}).encode())
        with self.assertRaises(InvitationError):
            self.host._invitation(0).dumps()

    def test_certificate_cannot_be_rebound_to_another_world_or_concatenated(self):
        for changes in (dict(world_id="11111111-1111-1111-1111-111111111111"),
                        dict(certificate_pem=self.invite.certificate_pem*2),
                        dict(certificate_pem=self.invite.certificate_pem.replace("CERTIFICATE", "PRIVATE KEY"))):
            with self.assertRaises(InvitationError):
                replace(self.invite, **changes)

    def test_import_verifies_build_first_and_never_replaces_changed_trust(self):
        token = secrets.token_bytes(32)
        config = self.invite.companion_config(self.rom, self.manifest, token=token, private_directory=self.private)
        self.assertEqual(config.player_id, self.invite.player_id)
        self.assertEqual(config.server_credential, self.invite.credential)
        self.assertEqual(config.expected_world_id, self.invite.world_id)
        self.assertEqual(config.server_host, "192.168.1.20")
        self.assertTrue(config.public_server)
        self.assertEqual(config.server_tls.certificate_sha256, self.invite.certificate_sha256)
        self.assertEqual(config.server_tls.build_context().verify_mode, 2)
        trust = config.server_tls.trusted_certificate_path
        original = trust.read_bytes()
        self.invite.companion_config(self.rom, self.manifest, token=token, private_directory=self.private)
        self.assertEqual(trust.read_bytes(), original)
        trust.write_bytes(b"preserve changed private file")
        with self.assertRaises(InvitationError):
            self.invite.companion_config(self.rom, self.manifest, token=token, private_directory=self.private)
        self.assertEqual(trust.read_bytes(), b"preserve changed private file")
        other = replace(self.invite, build_id="0"*64)
        untouched = self.private/"must-not-create"
        with self.assertRaises(InvitationError):
            other.companion_config(self.rom, self.manifest, token=token, private_directory=untouched)
        self.assertFalse(untouched.exists())
