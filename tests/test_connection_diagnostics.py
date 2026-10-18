"""connection_diagnostics: every failure has its own code and plain-English explanation; the check never sends a credential."""
import asyncio
import errno
import socket
import ssl
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from emerald_multiplayer import connection_diagnostics as diagnostics
from emerald_multiplayer.connection_diagnostics import check_routes, check_server, classify, describe, rejection_code
from emerald_multiplayer.invitations import InvitationError
from emerald_multiplayer.protocol import ProtocolError
from emerald_multiplayer.relay import RelayError
from emerald_multiplayer.secure_transport import HostIdentityError
from emerald_multiplayer.server import ServerConfig, WorldServer
from net_fixtures import FakeWorldServer, free_port, make_installation, make_world


class ExplanationTests(unittest.TestCase):
    def test_every_code_has_a_title_a_message_and_steps_for_the_person_who_can_act(self):
        for code in diagnostics.CODES:
            explanation = describe(code, port=7777)
            with self.subTest(code=code):
                self.assertTrue(explanation.title and explanation.message)
                if code != diagnostics.OK:
                    self.assertTrue(explanation.steps, "a failure must say what to do")
                self.assertTrue(all(step.startswith(("Host: ", "You: ")) for step in explanation.steps))
                self.assertNotIn("{port}", " ".join(explanation.steps))
        self.assertIn("7777", " ".join(describe("timeout", port=7777).steps))
        self.assertIn("CGNAT", " ".join(describe("timeout").host_steps))
        self.assertEqual(describe("no-such-code").title, describe("rejected").title)

    def test_server_error_codes_map_to_stable_codes_and_permanence(self):
        self.assertEqual(rejection_code("public_exposure_disabled"), "rejected_public_exposure_disabled")
        self.assertEqual(rejection_code("player_already_connected"), "rejected_player_already_connected")
        self.assertEqual(rejection_code("lease_active"), "rejected_player_already_connected")
        self.assertEqual(rejection_code("credentials_invalid"), "rejected_invalid_credentials")
        self.assertEqual(rejection_code("enrollment_disabled"), "rejected_enrollment_disabled")
        self.assertEqual(rejection_code("build_mismatch"), "version_mismatch")
        self.assertEqual(rejection_code("unsupported_protocol"), "version_mismatch")
        self.assertEqual(rejection_code("something_new"), "rejected")
        for code in ("version_mismatch", "wrong_world", "rejected_invalid_credentials", "rejected_public_exposure_disabled"):
            self.assertTrue(diagnostics.is_permanent(code))
        for code in ("refused", "timeout", "rejected_player_already_connected", "rejected_server_full", "relay_host_offline"):
            self.assertFalse(diagnostics.is_permanent(code))

    def test_exceptions_are_classified_including_windows_error_numbers(self):
        def os_error(number, *, winerror=None):
            error = OSError(number, "x")
            if winerror is not None:
                error.winerror = winerror
            return error
        cases = [
            (socket.gaierror(socket.EAI_NONAME, "x"), "dns_failed"),
            (ConnectionRefusedError(), "refused"),
            (TimeoutError(), "timeout"),
            (asyncio.TimeoutError(), "timeout"),
            (os_error(errno.ENETUNREACH), "unreachable"),
            (os_error(errno.EHOSTUNREACH), "unreachable"),
            (os_error(0, winerror=10065), "unreachable"),
            (os_error(0, winerror=1231), "unreachable"),
            (os_error(0, winerror=10060), "timeout"),
            (os_error(0, winerror=121), "timeout"),
            (os_error(0, winerror=1225), "refused"),
            (os_error(0, winerror=10013), "blocked"),
            (os_error(errno.EACCES), "blocked"),
            (ssl.SSLError(1, "bad"), "tls_failed"),
            (ConnectionResetError(), "tls_failed"),
            (HostIdentityError("pin"), "wrong_world"),
            (RelayError("relay_host_offline"), "relay_host_offline"),
            (RelayError("relay_unreachable", reason="refused"), "relay_unreachable"),
            (ProtocolError("public_exposure_disabled", "x"), "rejected_public_exposure_disabled"),
        ]
        for error, code in cases:
            with self.subTest(error=repr(error)):
                found, detail = classify(error)
                self.assertEqual(found, code)
                self.assertTrue(detail)


class CheckServerTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        cls.installation = make_installation(root)
        cls.world = make_world(root, cls.installation)
        cls.other = make_world(root, cls.installation, name="other", names=("Mallory", "Eve"))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def options(self, world=None, **changes):
        world = world or self.world
        values = dict(certificate_sha256=world.certificate_sha256, world_id=world.world_id, build_id=world.build_id,
                      ruleset_id=world.ruleset_id, timeout=3)
        values.update(changes)
        return values

    async def fake(self, **behaviour):
        server = await FakeWorldServer(self.world, **behaviour).start()
        self.addAsyncCleanup(server.close)
        return server

    async def test_the_real_world_server_passes_with_its_version_and_no_credential_is_sent(self):
        store = self.world.open_store()
        self.addCleanup(store.close)
        server = WorldServer(ServerConfig(self.world.build_id, self.world.ruleset_id), store=store)
        await server.start("127.0.0.1", 0, tls=self.world.server_tls)
        self.addAsyncCleanup(server.close)
        result = await check_server("127.0.0.1", server.address[1], **self.options())
        self.assertTrue(result.ok, result)
        self.assertEqual(result.detail, "version check passed")
        self.assertIn("BEGIN CERTIFICATE", result.certificate_pem)
        self.assertEqual(server.sessions, {})                       # no session, lease or character was created
        self.assertEqual((result.route, result.port), ("direct", server.address[1]))

    async def test_a_hello_without_credential_detects_a_different_game_version(self):
        fake = await self.fake(on_hello="build_mismatch")
        result = await check_server("127.0.0.1", fake.port, **self.options())
        self.assertEqual(result.code, "version_mismatch")
        self.assertNotIn("credential", fake.hellos[0])
        self.assertEqual(fake.hellos[0]["build_id"], self.world.build_id)

    async def test_a_world_closed_to_the_internet_says_so(self):
        fake = await self.fake(immediate="public_exposure_disabled")
        result = await check_server("127.0.0.1", fake.port, **self.options())
        self.assertEqual(result.code, "rejected_public_exposure_disabled")
        self.assertIn("Internet access", " ".join(result.steps))
        self.assertEqual(fake.hellos, [])

    async def test_without_a_build_the_check_stops_after_the_certificate(self):
        fake = await self.fake(on_hello="build_mismatch")
        result = await check_server("127.0.0.1", fake.port, **self.options(build_id=None))
        self.assertTrue(result.ok)
        self.assertEqual(fake.hellos, [])

    async def test_nothing_listening_is_refused_not_a_generic_failure(self):
        result = await check_server("127.0.0.1", free_port(), **self.options())
        self.assertEqual(result.code, "refused")
        self.assertIn("Host the world", " ".join(result.host_steps))

    async def test_another_world_at_the_address_is_wrong_world_and_nothing_is_sent(self):
        fake = await FakeWorldServer(self.other, on_hello="credentials_required").start()
        self.addAsyncCleanup(fake.close)
        result = await check_server("127.0.0.1", fake.port, **self.options())
        self.assertEqual(result.code, "wrong_world")
        self.assertEqual(fake.hellos, [])

    async def test_a_right_pin_with_an_unusable_certificate_is_certificate_invalid(self):
        fake = await self.fake(on_hello="credentials_required")
        def broken(*args, **kwargs):
            raise InvitationError("certificate_invalid", "expired")
        with patch("emerald_multiplayer.invitations._certificate", broken):
            result = await check_server("127.0.0.1", fake.port, **self.options())
        self.assertEqual(result.code, "certificate_invalid")

    async def test_a_non_tls_service_is_tls_failed(self):
        fake = await self.fake(tls=False)
        result = await check_server("127.0.0.1", fake.port, **self.options())
        self.assertEqual(result.code, "tls_failed")

    async def test_no_answer_at_all_is_a_timeout(self):
        async def never(*args, **kwargs):
            await asyncio.sleep(60)
        with patch.object(diagnostics, "open_tls", never):
            result = await check_server("127.0.0.1", 7777, **self.options(timeout=.2))
        self.assertEqual(result.code, "timeout")
        self.assertIn("Windows Firewall", " ".join(result.steps))

    async def test_an_unknown_host_name_is_dns_failed_and_a_bad_address_is_invalid(self):
        def fail(*args, **kwargs):
            raise socket.gaierror(socket.EAI_NONAME, "unknown")
        with patch("emerald_multiplayer.invite_code.socket.getaddrinfo", fail):
            result = await check_server("no-such-host.invalid", 7777, **self.options())
        self.assertEqual(result.code, "dns_failed")
        for address, port in (("0.0.0.0", 7777), ("bad host", 7777), ("127.0.0.1", 0)):
            self.assertEqual((await check_server(address, port, **self.options())).code, "invalid_address")
        bad_relay = await check_server("127.0.0.1", 7777, relay=("::", 1), **self.options())
        self.assertEqual(bad_relay.code, "invalid_address")

    async def test_check_routes_uses_the_relay_only_when_the_direct_route_fails(self):
        calls = []

        async def fake_check(address, port, *, relay=None, **options):
            calls.append(relay)
            return diagnostics.result("timeout" if relay is None else "ok", route="direct" if relay is None else "relay")
        with patch.object(diagnostics, "check_server", fake_check):
            result = await check_routes("203.0.113.5", 7777, relay=("198.51.100.2", 7780), **self.options())
            self.assertEqual((result.code, result.route), ("ok", "relay"))
            self.assertEqual(calls, [None, ("198.51.100.2", 7780)])
            calls.clear()
            result = await check_routes("203.0.113.5", 7777, **self.options())
            self.assertEqual(result.code, "timeout")
            self.assertEqual(calls, [None])


if __name__ == "__main__":
    unittest.main()
