"""Host reachability: the bind policy (every IPv4 interface for Internet and VPN worlds, loopback for Solo worlds), the peer
filter (local network and overlay VPNs without Internet access, everyone else only with it), and this PC's labelled addresses."""
import asyncio
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from emerald_multiplayer import launcher_worlds
from emerald_multiplayer.launcher_gui import LaunchRequest
from emerald_multiplayer.launcher_session import LauncherSession, LauncherSessionError
from emerald_multiplayer.launcher_worlds import (
    LocalAddress, classify_address, lan_addresses, local_addresses, parse_ipconfig, tailscale_address,
)
from emerald_multiplayer.server import ServerConfig, WorldServer
from net_fixtures import make_installation, make_world


class BindPolicyTests(unittest.TestCase):
    def options(self, address, internet=False):
        return LaunchRequest("host", Path("/private/worlds/w/host.json"), address, internet).options()

    def test_a_solo_world_listens_on_this_pc_only(self):
        options = self.options("127.0.0.1")
        self.assertEqual((options["bind_address"], options["host_route"], options["public"]), ("127.0.0.1", "127.0.0.1", False))
        self.assertNotIn("overlay", options)

    def test_a_local_network_world_listens_on_its_address(self):
        options = self.options("192.168.1.20")
        self.assertEqual((options["bind_address"], options["host_route"], options["public"]), ("192.168.1.20", "192.168.1.20", False))

    def test_an_internet_world_listens_on_every_interface_and_the_host_uses_loopback(self):
        for address in ("192.168.1.20", "127.0.0.1"):
            with self.subTest(address=address):
                options = self.options(address, internet=True)
                self.assertEqual((options["bind_address"], options["host_route"], options["public"]), ("0.0.0.0", "127.0.0.1", True))

    def test_a_vpn_address_listens_on_every_interface_without_opening_the_internet(self):
        options = self.options("100.101.102.103")
        self.assertEqual((options["bind_address"], options["host_route"], options["public"], options["overlay"]),
                         ("0.0.0.0", "127.0.0.1", False, True))

    def test_wildcards_and_public_addresses_are_never_a_chosen_address(self):
        for address in ("0.0.0.0", "::", "8.8.8.8", "100.128.0.1", "localhost"):
            with self.subTest(address=address), self.assertRaisesRegex(ValueError, "address_invalid"):
                self.options(address, internet=True)


class ServerBindAndFilterTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.installation = make_installation(cls.root)
        cls.world = make_world(cls.root, cls.installation)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    async def server(self):
        store = self.world.open_store()
        self.addCleanup(store.close)
        server = WorldServer(ServerConfig(self.world.build_id, self.world.ruleset_id), store=store)
        self.addAsyncCleanup(server.close)
        return server

    async def test_the_wildcard_listener_needs_its_opt_in_tls_and_a_durable_world(self):
        bare = WorldServer(ServerConfig(self.world.build_id, self.world.ruleset_id))
        for options in ({"allow_lan": True}, {"allow_lan": True, "wildcard": True},
                        {"allow_lan": True, "wildcard": True, "tls": self.world.server_tls}):
            with self.subTest(options=sorted(options)), self.assertRaises(ValueError):
                await bare.start("0.0.0.0", 0, **options)
        server = await self.server()
        with self.assertRaises(ValueError):
            await server.start("0.0.0.0", 0, wildcard=True, tls=self.world.server_tls)        # neither LAN nor Internet
        with self.assertRaises(ValueError):
            await server.start("192.168.1.2", 0, allow_lan=True, wildcard=True, tls=self.world.server_tls)
        await server.start("0.0.0.0", 0, allow_lan=True, wildcard=True, tls=self.world.server_tls)
        self.assertEqual(server.address[0], "0.0.0.0")

    async def test_peers_without_internet_access_are_local_network_and_overlay_vpn_only(self):
        server = await self.server()
        await server.start("0.0.0.0", 0, allow_lan=True, wildcard=True, tls=self.world.server_tls)
        for address in ("127.0.0.1", "192.168.1.5", "10.1.2.3", "172.20.0.4", "100.101.102.103", "fd7a:115c:a1e0::5"):
            self.assertTrue(server.peer_allowed(address), address)
        for address in ("8.8.8.8", "25.1.2.3", "26.4.5.6", "100.128.0.1", "::ffff:8.8.8.8", None):
            self.assertFalse(server.peer_allowed(address), address)
        self.assertFalse(server.peer_allowed("127.0.0.1", relayed=True), "no relay listener: no relayed peers")

    async def test_internet_access_admits_any_unicast_peer(self):
        server = await self.server()
        await server.start("0.0.0.0", 0, allow_lan=True, public=True, wildcard=True, tls=self.world.server_tls)
        for address in ("8.8.8.8", "25.1.2.3", "100.101.102.103", "192.168.1.5", "2606:4700:4700::1111"):
            self.assertTrue(server.peer_allowed(address), address)
        for address in ("0.0.0.0", "224.0.0.1", "255.255.255.255"):
            self.assertFalse(server.peer_allowed(address), address)

    async def test_the_relay_listener_is_loopback_only_and_exists_only_when_enabled(self):
        server = await self.server()
        await server.start("127.0.0.1", 0, allow_lan=True, tls=self.world.server_tls, relay=True)
        host, port = server.relay_address
        self.assertEqual(host, "127.0.0.1")
        self.assertNotEqual(port, server.address[1])
        self.assertTrue(server.peer_allowed("127.0.0.1", relayed=True))
        self.assertFalse(server.peer_allowed("192.168.1.5", relayed=True))
        plain = WorldServer(ServerConfig(self.world.build_id, self.world.ruleset_id))
        with self.assertRaises(ValueError):
            await plain.start("127.0.0.1", 0, relay=True)
        await server.close()
        with self.assertRaises(RuntimeError):
            server.relay_address


class SessionBindValidationTests(unittest.TestCase):
    def test_a_wildcard_session_needs_internet_access_or_a_vpn_address(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        installation = make_installation(Path(temp.name))
        for options in ({"bind_address": "0.0.0.0"}, {"bind_address": "0.0.0.0", "host_route": "8.8.8.8", "public": True},
                        {"bind_address": "::", "public": True}):
            with self.subTest(options=options), self.assertRaises(LauncherSessionError):
                LauncherSession(installation, Path(temp.name), world_directory=Path(temp.name), **options)
        for options in ({"bind_address": "0.0.0.0", "public": True}, {"bind_address": "0.0.0.0", "overlay": True},
                        {"bind_address": "0.0.0.0", "host_route": "100.101.102.103", "overlay": True}):
            with self.subTest(options=options):
                session = LauncherSession(installation, Path(temp.name), world_directory=Path(temp.name), **options)
                self.assertIn(session._host_route, ("127.0.0.1", "100.101.102.103"))
        with self.assertRaises(LauncherSessionError):
            LauncherSession(installation, Path(temp.name), invitation_path=Path("x.json"), overlay=True)


class AddressTests(unittest.TestCase):
    def test_addresses_are_labelled_lan_vpn_or_loopback(self):
        cases = {
            ("192.168.1.20", ""): ("lan", "Local network", False),
            ("10.147.17.5", "ZeroTier One [8056c2e21c000001]"): ("vpn", "VPN (ZeroTier One [8056c2e21c000001])", False),
            ("100.101.102.103", "Tailscale"): ("vpn", "Tailscale", False),
            ("100.101.102.103", ""): ("vpn", "VPN (Tailscale or similar, 100.x)", False),
            ("26.12.0.5", "Radmin VPN"): ("vpn", "Radmin VPN", True),
            ("127.0.0.1", ""): ("loopback", "This PC only", False),
        }
        for (value, adapter), (kind, label, internet) in cases.items():
            with self.subTest(value=value, adapter=adapter):
                item = classify_address(value, adapter)
                self.assertEqual((item, item.kind, item.label, item.needs_internet_access), (value, kind, label, internet))
                self.assertIsInstance(item, str)
        for value in ("169.254.1.2", "8.8.8.8", "26.12.0.5", "224.0.0.1", "::1", "nonsense"):
            self.assertIsNone(classify_address(value), value)

    def test_ipconfig_is_read_in_any_language(self):
        english = ("Windows IP Configuration\r\n\r\nEthernet adapter Ethernet:\r\n\r\n"
                   "   Connection-specific DNS Suffix  . : home\r\n   IPv4 Address. . . . . . . . . . . : 192.168.1.20\r\n"
                   "   Subnet Mask . . . . . . . . . . . : 255.255.255.0\r\n   Default Gateway . . . . . . . . . : 192.168.1.1\r\n"
                   "\r\nUnknown adapter Tailscale:\r\n\r\n   IPv4 Address. . . . . . . . . . . : 100.101.102.103(Preferred)\r\n")
        german = ("Ethernet-Adapter Radmin VPN:\n\n   IPv4-Adresse  . . . . . . . . . . : 26.12.0.5\n"
                  "Drahtlos-LAN-Adapter WLAN:\n   IPv4-Adresse  . . . . . . . . . . : 10.0.0.7\n")
        self.assertEqual(parse_ipconfig(english), [("192.168.1.20", "Ethernet"), ("100.101.102.103", "Tailscale")])
        self.assertEqual(parse_ipconfig(german), [("26.12.0.5", "Radmin VPN"), ("10.0.0.7", "WLAN")])

    def test_local_addresses_list_lan_then_vpn_then_loopback_and_find_tailscale(self):
        with patch.object(launcher_worlds, "_probed", return_value=["192.168.1.20", "127.0.1.1"]):
            items = local_addresses(adapters=[("100.101.102.103", "Tailscale"), ("26.12.0.5", "Radmin VPN"),
                                              ("192.168.1.20", "Ethernet")])
        self.assertEqual(items, ["192.168.1.20", "100.101.102.103", "26.12.0.5", "127.0.1.1", "127.0.0.1"])
        self.assertEqual([item.kind for item in items], ["lan", "vpn", "vpn", "loopback", "loopback"])
        self.assertEqual(tailscale_address(items), "100.101.102.103")
        self.assertIsNone(tailscale_address([classify_address("192.168.1.20")]))

    def test_lan_addresses_include_a_tailscale_address_after_the_local_network(self):
        class FakeSocket:
            def __init__(self, *args):
                pass

            def connect(self, address):
                self.address = address

            def getsockname(self):
                return ("100.101.102.103" if self.address[0] == "100.100.100.100" else "192.168.1.20", 5555)

            def close(self):
                pass
        infos = [(2, 1, 6, "", (a, 0)) for a in ("127.0.0.1", "10.0.0.5")]
        with patch.object(launcher_worlds.socket, "socket", FakeSocket), \
                patch.object(launcher_worlds.socket, "getaddrinfo", return_value=infos), \
                patch.object(launcher_worlds, "_adapters", return_value=[]):
            found = lan_addresses()
        self.assertEqual(found, ["192.168.1.20", "10.0.0.5", "100.101.102.103"])
        self.assertTrue(all(isinstance(item, LocalAddress) for item in found))
        self.assertEqual(found[2].kind, "vpn")


if __name__ == "__main__":
    unittest.main()
