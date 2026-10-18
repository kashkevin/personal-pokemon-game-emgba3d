"""Invite codes: a friend's world account as one short, checksummed piece of text, and the certificate pinned by it."""
import asyncio
import base64
import hashlib
import struct
import zlib
from pathlib import Path
import socket
import tempfile
import unittest
import unittest.mock

from emerald_multiplayer.invitations import Invitation
from emerald_multiplayer.invite_code import (
    InviteCodeError, decode_invite, encode_invite, fetch_certificate, redeem, resolve_address, valid_address, valid_port,
)
from emerald_multiplayer.launcher_session import GameInstallation
from emerald_multiplayer.launcher_setup import create_world
from emerald_multiplayer.server import ServerConfig, WorldServer
from test_host_world import make_trade_files
from test_player_runtime import write_bundle


class InviteCodeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rom, self.manifest = make_trade_files(self.root)
        bundle = self.root / "bundle"
        bundle.mkdir()
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        self.installation = GameInstallation(self.rom, self.manifest, digest(self.rom), digest(self.manifest), write_bundle(bundle))
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            self.port = listener.getsockname()[1]
        self.world = create_world(self.installation, self.root / "private", player_names=("Host", "Friend", "Pal"),
                                  endpoint="192.168.70.50", port=self.port)
        self.invitation = self.world.invitation(1)

    def test_round_trip_keeps_every_identity_and_never_carries_the_certificate_or_host_key(self):
        text = encode_invite(self.invitation)
        self.assertTrue(text.startswith("ET1-"))
        self.assertLess(len(text), 400)
        code = decode_invite(text)
        self.assertEqual((code.world_id, code.player_id, code.slot, code.display_name),
                         (self.invitation.world_id, self.invitation.player_id, 1, "Friend"))
        self.assertEqual(code.credential, self.invitation.credential)
        self.assertEqual(code.certificate_sha256, self.invitation.certificate_sha256)
        self.assertEqual((code.address, code.port), ("192.168.70.50", self.port))
        self.assertEqual(code.build_id, self.invitation.build_id)
        self.assertNotIn("BEGIN", text)
        host_key = (self.world.directory / "host-key.pem").read_bytes()
        self.assertNotIn(host_key.split(b"\n")[1].decode(), text)

    def test_what_a_person_pastes_is_accepted_with_spaces_lines_and_lower_case(self):
        text = encode_invite(self.invitation)
        messy = "  " + text.lower().replace("-", " \n") + "\n"
        self.assertEqual(decode_invite(messy), decode_invite(text))

    def test_the_address_and_port_the_host_chose_are_in_the_code(self):
        code = decode_invite(encode_invite(self.invitation, "friends.example.org", 4555))
        self.assertEqual((code.address, code.port), ("friends.example.org", 4555))
        self.assertEqual(code.player_id, self.invitation.player_id)

    def test_a_mistyped_truncated_or_foreign_code_is_refused_with_a_clear_message(self):
        text = encode_invite(self.invitation)
        body = text[4:].replace("-", "")
        for index in (0, 7, 40, len(body) - 3):
            flipped = body[:index] + ("A" if body[index] != "A" else "B") + body[index + 1:]
            with self.subTest(index=index), self.assertRaises(InviteCodeError) as caught:
                decode_invite("ET1-" + flipped)
            self.assertEqual(caught.exception.code, "invite_malformed")
        for bad in ("", "   ", "ET1-", "ET1-" + body[:-10], "XX1-" + body, "hello world", text * 5, "ET1-!!!!"):
            with self.subTest(bad=bad[:12]), self.assertRaises(InviteCodeError):
                decode_invite(bad)

    def test_the_host_account_and_unusable_addresses_never_become_a_code(self):
        host = self.world._invitation(0)
        with self.assertRaises(InviteCodeError):
            encode_invite(host)
        for address in ("0.0.0.0", "::", "8.8.8.8.8", "", "bad host", "-x.com", "1.2.3", "224.0.0.1"):
            with self.subTest(address=address), self.assertRaises(InviteCodeError):
                encode_invite(self.invitation, address, 7777)
        for port in (0, 65536, True):
            with self.subTest(port=port), self.assertRaises(InviteCodeError):
                encode_invite(self.invitation, "192.168.1.5", port)
        self.assertTrue(valid_address("192.168.1.5") and valid_address("my-server.example.org") and valid_address("93.184.216.34"))
        self.assertFalse(valid_address("192.168.1.256") and True)
        self.assertTrue(valid_port(1) and valid_port(65535) and not valid_port(0))

    async def test_a_host_name_is_looked_up_each_time_and_a_numeric_address_is_used_as_it_is(self):
        self.assertEqual(resolve_address("192.168.1.9", 7777), "192.168.1.9")
        self.assertEqual(resolve_address("localhost", 7777), "127.0.0.1")
        with self.assertRaises(InviteCodeError):
            resolve_address("no-such-host.invalid", 7777, timeout=1)

    async def _serve(self):
        store = self.world.open_store()
        self.addCleanup(store.close)
        server = WorldServer(ServerConfig(self.world.build_id, self.world.ruleset_id), store=store)
        await server.start("127.0.0.1", self.port, tls=self.world.server_tls)
        self.addCleanup(lambda: None)
        return server

    async def test_the_certificate_is_fetched_from_the_server_and_accepted_only_if_it_matches_the_pin(self):
        server = await self._serve()
        try:
            code = decode_invite(encode_invite(self.invitation, "127.0.0.1", self.port))
            pem = await fetch_certificate("127.0.0.1", self.port, code.certificate_sha256, code.world_id)
            self.assertEqual(pem, self.invitation.certificate_pem)
            redeemed = redeem(code, pem)
            self.assertEqual(redeemed.dumps().replace(b"192.168.70.50", b"127.0.0.1"), redeemed.dumps())
            self.assertEqual((redeemed.world_id, redeemed.player_id, redeemed.credential),
                             (self.invitation.world_id, self.invitation.player_id, self.invitation.credential))
            # Another world at the same address (a different certificate) is not accepted.
            with self.assertRaises(InviteCodeError) as caught:
                await fetch_certificate("127.0.0.1", self.port, "0" * 64, code.world_id)
            self.assertEqual(caught.exception.code, "certificate_mismatch")
        finally:
            await server.close()

    async def test_an_unreachable_server_is_reported_not_trusted(self):
        with self.assertRaises(InviteCodeError) as caught:
            await fetch_certificate("127.0.0.1", self.port, self.invitation.certificate_sha256, self.invitation.world_id, timeout=1)
        self.assertEqual(caught.exception.code, "certificate_unavailable")
        # The error says why: nothing listens there (not a generic "could not be reached").
        self.assertEqual(caught.exception.reason, "refused")
        self.assertIn("Nothing is accepting connections", str(caught.exception))

    async def test_a_host_name_that_cannot_be_looked_up_carries_dns_failed(self):
        def fail(*args, **kwargs):
            raise socket.gaierror(socket.EAI_NONAME, "unknown")
        with unittest.mock.patch("emerald_multiplayer.invite_code.socket.getaddrinfo", fail):
            with self.assertRaises(InviteCodeError) as caught:
                resolve_address("no-such-host.invalid", 7777)
        self.assertEqual((caught.exception.code, caught.exception.reason), ("certificate_unavailable", "dns_failed"))
        self.assertIn("could not be found", str(caught.exception))

    @staticmethod
    def raw(text):
        compact = text[4:].replace("-", "")
        return base64.b32decode(compact + "=" * (-len(compact) % 8))

    @staticmethod
    def forge(raw):
        body = raw[:-4]
        data = body + struct.pack(">I", zlib.crc32(body))
        return "ET1-" + base64.b32encode(data).decode("ascii").rstrip("=")

    def test_a_code_without_a_relay_stays_version_1_so_older_games_still_read_it(self):
        text = encode_invite(self.invitation, "93.184.216.34", 7777)
        self.assertEqual(self.raw(text)[:2], bytes([1, 0]))
        self.assertIsNone(decode_invite(text).relay)

    def test_a_relay_endpoint_makes_a_version_2_code_and_round_trips(self):
        for relay in (("relay.example.net", 7780), ("81.2.69.160", 443), ("100.101.102.103", 7780)):
            with self.subTest(relay=relay):
                text = encode_invite(self.invitation, "93.184.216.34", 7777, relay=relay)
                self.assertEqual(self.raw(text)[:2], bytes([2, 1]))
                code = decode_invite(text)
                self.assertEqual(code.relay, relay)
                self.assertEqual((code.address, code.port, code.credential), ("93.184.216.34", 7777, self.invitation.credential))
        for relay in (("0.0.0.0", 7780), ("bad host", 7780), ("relay.example.net", 0), ("relay.example.net",)):
            with self.subTest(relay=relay), self.assertRaises(InviteCodeError):
                encode_invite(self.invitation, relay=relay)

    def test_version_errors_say_newer_or_older_correctly(self):
        raw = bytearray(self.raw(encode_invite(self.invitation)))
        raw[0] = 3
        with self.assertRaises(InviteCodeError) as caught:
            decode_invite(self.forge(bytes(raw)))
        self.assertEqual(caught.exception.code, "invite_version")
        self.assertIn("newer version", str(caught.exception))
        raw[0] = 0
        with self.assertRaises(InviteCodeError) as caught:
            decode_invite(self.forge(bytes(raw)))
        self.assertEqual(caught.exception.code, "invite_version_old")
        self.assertIn("older version", str(caught.exception))
        self.assertNotIn("newer", str(caught.exception))
        raw[0], raw[1] = 2, 0x80                      # a flag this version does not know: made by a newer game
        with self.assertRaises(InviteCodeError) as caught:
            decode_invite(self.forge(bytes(raw)))
        self.assertEqual(caught.exception.code, "invite_version")
        raw[0], raw[1] = 2, 1                         # says it has a relay but carries none
        with self.assertRaises(InviteCodeError) as caught:
            decode_invite(self.forge(bytes(raw)))
        self.assertEqual(caught.exception.code, "invite_malformed")


if __name__ == "__main__":
    unittest.main()
