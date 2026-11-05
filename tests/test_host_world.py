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

    def test_opens_read_each_save_once_and_remember_it_beside_the_database(self):
        """KNOWN_ISSUES MS-161 (b): HostWorld's opens read each save once in its life (save_readings.py); the readings
        file is the only file an open writes, and only once the world has saves."""
        from uuid import uuid4
        from emerald_multiplayer import save_readings
        from emerald_multiplayer.ownership import OWNERSHIP_PROFILE
        from test_ownership_storage import owned_flash, source_flash
        host = self.create()
        account = host.accounts[0]
        readings = host.directory / ("world.sqlite3" + save_readings.SUFFIX)
        with host.open_store() as store:
            store.begin_server_boot()
            lease = store.acquire_lease(account.player_id, account.credential)
            store.enroll_player(account.player_id, source_flash())
            grant = store.reserve_instances(account.player_id, lease, str(uuid4()), 0, 1, 4)
            for revision in range(3):
                store.commit_checkpoint(account.player_id, lease, str(uuid4()), revision,
                                        owned_flash(grant, counter=3 + revision), host.build_id, host.ruleset_id,
                                        OWNERSHIP_PROFILE)
        self.assertFalse(readings.exists())                    # opened before it had saves: nothing to remember
        before = directory_hashes(host.directory)
        reads = []
        real = save_readings.inspect_flash
        with patch.object(save_readings, "inspect_flash", lambda *args, **kwargs: reads.append(1) or real(*args, **kwargs)):
            self.assertEqual(HostWorld.open(host.directory, self.rom, self.manifest), host)
            self.assertEqual(len(reads), 3)                    # each save read once ...
            self.assertEqual(HostWorld.open(host.directory, self.rom, self.manifest), host)
            with host.open_store() as store:
                store.integrity_check()
            self.assertEqual(len(reads), 3)                    # ... and not again
        after = directory_hashes(host.directory)
        self.assertEqual(set(after) - set(before), {readings.name})
        self.assertEqual({name: value for name, value in after.items() if name != readings.name}, before)

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


class CredentialReplacementTests(unittest.TestCase):
    """KNOWN_ISSUES NU-7: one friend's invite code replaced; the old code refused at once, everything else kept."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rom, self.manifest = make_trade_files(self.root)
        self.host = HostWorld.create(self.root / "host", self.rom, self.manifest,
                                     player_names=["Host", "Friend A", "Friend B", "Friend C"], endpoint="127.0.0.1", port=8765)

    def replace(self, slot):
        return HostWorld.replace_credential(self.host.directory, self.rom, self.manifest, slot)

    def assert_credentials(self, world, expected):
        """Each account signs in with ``expected``'s credential and no other world's account credential."""
        with world.open_store() as store:
            for account, credential in zip(world.accounts, expected):
                self.assertEqual(store.authenticate(account.player_id, credential).display_name, account.display_name)
            return store

    def test_a_friends_code_is_replaced_the_old_one_refused_and_everything_else_kept(self):
        old = self.host.accounts[2].credential
        world = self.replace(2)
        new = world.accounts[2].credential
        self.assertNotEqual(new, old)
        self.assertEqual([(a.role, a.slot, a.player_id, a.display_name) for a in world.accounts],
                         [(a.role, a.slot, a.player_id, a.display_name) for a in self.host.accounts])
        self.assertEqual([a.credential for i, a in enumerate(world.accounts) if i != 2],
                         [a.credential for i, a in enumerate(self.host.accounts) if i != 2])
        self.assertEqual((world.world_id, world.certificate_sha256), (self.host.world_id, self.host.certificate_sha256))
        self.assert_credentials(world, [a.credential for a in world.accounts])
        with world.open_store() as store:
            with self.assertRaises(StorageError) as caught:
                store.authenticate(self.host.accounts[2].player_id, old)
            self.assertEqual(caught.exception.code, "credentials_invalid")
        self.assertEqual(HostWorld.open(self.host.directory, self.rom, self.manifest), world)
        self.assertEqual(world.invitation(2).credential, new)
        self.assertNotIn(new.hex(), repr(world))
        names = {p.name for p in self.host.directory.iterdir()}
        self.assertNotIn("credential-replacement.json", names)
        self.assertNotIn("host.json.new", names)
        if os.name != "nt":
            self.assertEqual((self.host.directory / "host.json").stat().st_mode & 0o777, 0o600)
        # replaced again: another new code, the second one refused too
        again = self.replace(2)
        self.assertNotIn(again.accounts[2].credential, (old, new))
        with again.open_store() as store:
            for refused in (old, new):
                with self.assertRaises(StorageError):
                    store.authenticate(again.accounts[2].player_id, refused)

    def test_the_host_account_and_slots_without_a_friend_are_never_replaced(self):
        small = HostWorld.create(self.root / "small", self.rom, self.manifest, player_names=["Host", "Friend A"],
                                 endpoint="127.0.0.1", port=8766)
        for directory, slot in ((self.host.directory, 0), (self.host.directory, 4), (self.host.directory, "1"),
                                (self.host.directory, True), (small.directory, 2)):
            before = directory_hashes(directory)
            with self.assertRaises(HostWorldError) as caught:
                HostWorld.replace_credential(directory, self.rom, self.manifest, slot)
            self.assertEqual(caught.exception.code, "invalid_role")
            self.assertEqual(directory_hashes(directory), before)

    def test_a_hosted_world_is_refused_and_unchanged(self):
        before = directory_hashes(self.host.directory)
        with self.host.open_store() as store:
            store.begin_server_boot()                 # a hosting server holds the owner lock for its run
            with self.assertRaises(HostWorldError) as caught:
                self.replace(1)
            self.assertEqual(caught.exception.code, "world_hosted")
        self.assertNotIn("credential-replacement.json", {p.name for p in self.host.directory.iterdir()})
        reopened = HostWorld.open(self.host.directory, self.rom, self.manifest)
        self.assertEqual([a.credential for a in reopened.accounts], [a.credential for a in self.host.accounts])
        self.assertEqual(directory_hashes(self.host.directory)["host.json"], before["host.json"])

    def test_a_replacement_stopped_at_any_step_is_finished_by_the_next_open(self):
        import emerald_multiplayer.host_world as module
        record = self.host.directory / "credential-replacement.json"
        old = self.host.accounts[1].credential
        stops = (("after its record", "_apply_replacement"), ("after the database", "_replace"),
                 ("after host.json", "unlink_file"))
        for label, name in stops:
            with self.subTest(stop=label):
                original = getattr(module, name)
                setattr(module, name, lambda *args, **kwargs: (_ for _ in ()).throw(OSError("stopped")))
                try:
                    with self.assertRaises(OSError):
                        self.replace(1)
                finally:
                    setattr(module, name, original)
                pending = json.loads(record.read_text())
                new = bytes.fromhex(pending["credential"])
                self.assertEqual((pending["slot"], pending["player_id"]), (1, self.host.accounts[1].player_id))
                world = HostWorld.open(self.host.directory, self.rom, self.manifest)
                self.assertFalse(record.exists())
                self.assertEqual(world.accounts[1].credential, new)
                self.assert_credentials(world, [a.credential for a in world.accounts])
                with world.open_store() as store:
                    with self.assertRaises(StorageError):
                        store.authenticate(world.accounts[1].player_id, old)
                old = new

    def test_a_database_that_refuses_the_new_code_leaves_everything_as_it_was(self):
        from emerald_multiplayer.storage import CheckpointStore
        before = directory_hashes(self.host.directory)

        def refuse(self_, player_id, credential):
            raise StorageError("storage_busy", "database is locked")
        with patch.object(CheckpointStore, "replace_credential", refuse):
            with self.assertRaises(HostWorldError) as caught:
                self.replace(3)
        self.assertEqual(caught.exception.code, "not_replaced")
        self.assertNotIn("credential-replacement.json", {p.name for p in self.host.directory.iterdir()})
        self.assertEqual(directory_hashes(self.host.directory)["host.json"], before["host.json"])
        self.assertEqual(HostWorld.open(self.host.directory, self.rom, self.manifest), self.host)
        self.assert_credentials(self.host, [a.credential for a in self.host.accounts])

    def test_a_record_cut_short_while_written_is_removed_and_the_world_opens_as_it_was(self):
        record = self.host.directory / "credential-replacement.json"
        for content in (b"{", b'{"format":"emerald-credential-replacement-v1"}', b"\0" * 10):
            record.write_bytes(content)
            world = HostWorld.open(self.host.directory, self.rom, self.manifest)
            self.assertEqual(world, self.host)
            self.assertFalse(record.exists())
        # a record for another account than its slot's: never applied
        value = dict(format="emerald-credential-replacement-v1", world_id=self.host.world_id, slot=1,
                     player_id=self.host.accounts[2].player_id, credential="ab" * 32)
        record.write_text(json.dumps(value))
        self.assertEqual(HostWorld.open(self.host.directory, self.rom, self.manifest), self.host)
        self.assertFalse(record.exists())

    def test_a_pending_record_in_a_world_held_by_another_process_is_refused_not_applied(self):
        from emerald_multiplayer.host_world import _owner_lock
        record = self.host.directory / "credential-replacement.json"
        value = dict(format="emerald-credential-replacement-v1", world_id=self.host.world_id, slot=1,
                     player_id=self.host.accounts[1].player_id, credential="cd" * 32)
        record.write_text(json.dumps(value))
        lock = _owner_lock(self.host.directory)
        lock.acquire()
        try:
            with self.assertRaises(HostWorldError) as caught:
                HostWorld.open(self.host.directory, self.rom, self.manifest)
            self.assertEqual(caught.exception.code, "world_busy")
            self.assertTrue(record.exists())
        finally:
            lock.release()
        world = HostWorld.open(self.host.directory, self.rom, self.manifest)
        self.assertEqual(world.accounts[1].credential, bytes.fromhex("cd" * 32))


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
