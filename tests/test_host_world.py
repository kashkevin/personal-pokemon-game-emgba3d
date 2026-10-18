"""Private provisioning only: no listener, game, credential send, or enrollment."""
from dataclasses import replace
from contextlib import closing
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import ssl
import tempfile
import unittest
from unittest.mock import patch
import zlib

from emerald_multiplayer.host_world import HostWorld, HostWorldError
from emerald_multiplayer.invitations import Invitation, InvitationError, _certificate
from emerald_multiplayer.companion import Companion
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.secure_transport import ClientTlsConfig
from emerald_multiplayer.storage import StorageError
from test_companion import make_files


def make_trade_files(directory):
    rom, manifest = make_files(directory)
    raw = b"\x01\0\0\0" + rom.read_bytes()[4:]
    rom.write_bytes(raw)
    value = json.loads(manifest.read_text())
    value.update(rom_sha256=hashlib.sha256(raw).hexdigest(), rom_crc32=f"{zlib.crc32(raw):08x}",
        save_abi_version=1, save_mailbox_size=512, save_mailbox_address=0x02021000,
        ownership_abi_version=1, save_profile="rhh-1.17.1-bb1093-ownership-v1",
        trade_abi_version=1, trade_abi_address=0x08000000)
    manifest.write_text(json.dumps(value))
    return rom, manifest


def directory_hashes(root):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir() if p.is_file()}


class HostWorldTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rom, self.manifest = make_trade_files(self.root)

    def create(self, name="host", **changes):
        values = dict(player_names=["Host", "Friend A", "Friend B", "Friend C"], endpoint="127.0.0.1", port=8765)
        values.update(changes)
        return HostWorld.create(self.root / name, self.rom, self.manifest, **values)

    def test_four_separate_profiles_reopen_without_boot_lease_or_file_change(self):
        host = self.create()
        self.assertEqual([p.slot for p in host.accounts], [0, 1, 2, 3])
        self.assertEqual([p.role for p in host.accounts], ["host", "friend", "friend", "friend"])
        self.assertEqual(len({p.player_id for p in host.accounts}), 4)
        self.assertEqual(len({p.credential for p in host.accounts}), 4)
        original = directory_hashes(host.directory)
        with host.open_store() as store:
            self.assertEqual((store.metadata.server_epoch, store.metadata.session_epoch), (0, 0))
            # Schema 3 plus the character transfer extension (3200) every new world gets (character_transfers.py).
            self.assertEqual(store._connection.execute("PRAGMA user_version").fetchone()[0], 3 + 3200)
            self.assertTrue(store.character_transfers_enabled)
            self.assertEqual(store._connection.execute("SELECT count(*) FROM checkpoints").fetchone()[0], 0)
            for account in host.accounts:
                self.assertEqual(store.authenticate(account.player_id, account.credential).display_name, account.display_name)
        self.assertEqual(HostWorld.open(host.directory, self.rom, self.manifest), host)
        self.assertEqual(directory_hashes(host.directory), original)
        for account in host.accounts:
            self.assertNotIn(account.credential.hex(), repr(host))
        if os.name != "nt":
            self.assertEqual(host.directory.stat().st_mode & 0o777, 0o700)
            for file in ("host.json", "host-key.pem"):
                self.assertEqual((host.directory/file).stat().st_mode & 0o777, 0o600)

    def test_one_to_four_only_and_existing_directory_is_never_changed(self):
        host = self.create(player_names=["Host"])
        original = directory_hashes(host.directory)
        with self.assertRaises(FileExistsError):
            self.create()
        self.assertEqual(directory_hashes(host.directory), original)
        for names in ([], ["A"]*5, "A", [" "]):
            with self.subTest(names=names), self.assertRaises(ValueError):
                self.create(name="rejected", player_names=names)
            self.assertFalse((self.root/"rejected").exists())
        for endpoint, port in (("0.0.0.0", 1), ("example.com", 1), ("127.0.0.1", True), ("127.0.0.1", 0)):
            with self.assertRaises(ValueError):
                self.create(name="rejected", endpoint=endpoint, port=port)
        for days in (True, 0, 3651):
            with self.assertRaises(ValueError):
                self.create(name="rejected", validity_days=days)

    def test_partial_creation_preserved_marked_and_never_opened_as_ready_world(self):
        with patch("emerald_multiplayer.host_world._new_certificate", side_effect=RuntimeError("injected certificate failure")):
            with self.assertRaises(RuntimeError):
                self.create()
        root = self.root / "host"
        self.assertTrue((root/"world.sqlite3").exists())
        self.assertEqual(json.loads((root/"creation-failed.json").read_text()),
                         {"format": "emerald-private-host-v1", "failed": True})
        original = directory_hashes(root)
        with self.assertRaises(HostWorldError):
            HostWorld.open(root, self.rom, self.manifest)
        with self.assertRaises(FileExistsError):
            self.create()
        self.assertEqual(directory_hashes(root), original)

    def test_tampered_role_secret_world_database_and_key_fail_without_regeneration(self):
        host = self.create()
        path = host.directory / "host.json"
        original = path.read_bytes()
        for change in (lambda v: v["accounts"][0].update(role="friend"),
                       lambda v: v["accounts"][1].update(player_id=v["accounts"][0]["player_id"]),
                       lambda v: v["accounts"][1].update(credential="00"*32),
                       lambda v: v.update(world_id="11111111-1111-1111-1111-111111111111")):
            value = json.loads(original)
            change(value)
            path.write_text(json.dumps(value))
            before = directory_hashes(host.directory)
            with self.assertRaises(ValueError):
                HostWorld.open(host.directory, self.rom, self.manifest)
            self.assertEqual(directory_hashes(host.directory), before)
        path.write_bytes(original)
        other = self.create(name="other", player_names=["Another"])
        (host.directory/"host-key.pem").write_bytes((other.directory/"host-key.pem").read_bytes())
        before = directory_hashes(host.directory)
        with self.assertRaises(HostWorldError):
            HostWorld.open(host.directory, self.rom, self.manifest)
        self.assertEqual(directory_hashes(host.directory), before)

    def test_missing_or_old_schema_database_not_recreated_or_migrated(self):
        host = self.create()
        host.database_path.unlink()
        with self.assertRaises(InvitationError):
            HostWorld.open(host.directory, self.rom, self.manifest)
        with self.assertRaises(InvitationError):
            host.open_store()
        self.assertFalse(host.database_path.exists())
        with closing(sqlite3.connect(host.database_path)) as database:
            with database:
                database.execute("PRAGMA user_version = 2")
                database.execute("CREATE TABLE sentinel (value TEXT)")
        original = directory_hashes(host.directory)
        with self.assertRaises(StorageError) as caught:
            HostWorld.open(host.directory, self.rom, self.manifest)
        self.assertEqual(caught.exception.code, "schema_incompatible")
        self.assertEqual(directory_hashes(host.directory), original)

    def test_friend_export_never_exposes_host_and_config_has_world_and_tls_pins(self):
        host = self.create()
        for slot in (0, True, -1, 4):
            with self.assertRaises(ValueError):
                host.export_invitation(slot, self.root/"bad.json")
        invite = host.export_invitation(2, self.root/"friend.json")
        self.assertEqual(invite.player_id, host.accounts[2].player_id)
        self.assertNotIn(host.accounts[0].credential.hex(), (self.root/"friend.json").read_text())
        config = host.host_companion_config(self.rom, self.manifest, token=secrets.token_bytes(32),
                                             private_directory=self.root/"host-client")
        self.assertEqual(config.player_id, host.accounts[0].player_id)
        self.assertEqual(config.expected_world_id, host.world_id)
        self.assertEqual(config.server_tls.certificate_sha256, host.certificate_sha256)

    def test_generated_certificate_chain_and_exact_pin_work_without_any_listener(self):
        host = self.create()
        invitation = host.invitation(1)
        path = self.root / "trust.pem"
        path.write_text(invitation.certificate_pem)
        server_in, server_out, client_in, client_out = [ssl.MemoryBIO() for _ in range(4)]
        server = host.server_tls.build_context().wrap_bio(server_in, server_out, server_side=True)
        tls = ClientTlsConfig(path, invitation.certificate_sha256)
        client = tls.build_context().wrap_bio(client_in, client_out, server_hostname=None)
        done = [False, False]
        for _ in range(20):
            for i, connection in enumerate((client, server)):
                try:
                    connection.do_handshake()
                    done[i] = True
                except ssl.SSLWantReadError:
                    pass
            server_in.write(client_out.read())
            client_in.write(server_out.read())
            if all(done):
                break
        self.assertTrue(all(done))
        self.assertEqual(hashlib.sha256(client.getpeercert(binary_form=True)).hexdigest(), invitation.certificate_sha256)
        client.write(b"bounded TLS proof")
        server_in.write(client_out.read())
        self.assertEqual(server.read(128), b"bounded TLS proof")
        cert = _certificate(invitation.certificate_pem, invitation.world_id, invitation.certificate_sha256)
        with self.assertRaises(InvitationError):
            _certificate(invitation.certificate_pem, invitation.world_id, invitation.certificate_sha256,
                         now=cert.not_valid_after_utc + timedelta(seconds=1))


class HostJoinNetworkTests(unittest.IsolatedAsyncioTestCase):
    async def test_four_provisioned_accounts_authenticate_through_exact_invitation_tls(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rom, manifest = make_trade_files(root)
            host = HostWorld.create(root/"host", rom, manifest, player_names=["Host", "A", "B", "C"],
                                    endpoint="127.0.0.1", port=8765)
            store = host.open_store()
            server = WorldServer(ServerConfig(host.build_id, host.ruleset_id), store=store)
            companions = []
            try:
                await server.start(port=0, tls=host.server_tls)
                actual_port = server.address[1]
                config = host.host_companion_config(rom, manifest, token=secrets.token_bytes(32),
                                                     private_directory=root/"client-0")
                configs = [replace(config, server_port=actual_port)]
                for slot in (1, 2, 3):
                    path = root/f"invitation-{slot}.json"
                    # Ephemeral test listener only; retain the private host's
                    # advertised fixed port unchanged. No invitation is sent.
                    replace(host.invitation(slot), port=actual_port).save(path)
                    configs.append(Invitation.load(path).companion_config(rom, manifest,
                        token=secrets.token_bytes(32), private_directory=root/f"client-{slot}"))
                for config in configs:
                    companion = Companion(config)
                    companions.append(companion)
                    await companion.start()
                async with asyncio.timeout(8):
                    while not all(c.connected and len(c._players) == 4 for c in companions):
                        await asyncio.sleep(.01)
                self.assertEqual({c.config.player_id for c in companions}, {p.player_id for p in host.accounts})
                for companion in companions:
                    self.assertEqual(companion.world_id, host.world_id)
                    self.assertEqual(companion.save_profile, host.save_profile)
                    self.assertIsNotNone(companion._remote_writer.get_extra_info("ssl_object"))
                    companion.config.server_tls.verify_peer(companion._remote_writer)
                self.assertEqual(len(server.sessions), 4)
                self.assertEqual(store._connection.execute("SELECT count(*) FROM checkpoints").fetchone()[0], 0)
                self.assertIsNone(server.trade_desk)
                store.integrity_check()
            finally:
                await asyncio.gather(*(c.close() for c in companions), return_exceptions=True)
                await server.close()
                store.close()
