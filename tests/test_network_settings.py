"""Per-world network settings (router setup preference, relay and relay key) and each friend account's remembered route."""
import json
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from emerald_multiplayer.network_settings import NetworkSettings, WorldNetwork, load_join_route, route_path, save_join_route
from emerald_multiplayer.saved_servers import SavedServers, relay_of


class NetworkSettingsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.world = str(uuid4())

    def test_defaults_router_setup_on_and_no_relay(self):
        network = NetworkSettings(self.root).get(self.world)
        self.assertEqual(network, WorldNetwork())
        self.assertTrue(network.router_setup)
        self.assertIsNone(network.relay)

    def test_a_relay_gets_one_key_that_survives_reopening_and_address_changes(self):
        settings = NetworkSettings(self.root)
        first = settings.set_relay(self.world, "relay.example.net", 7780)
        self.assertEqual(first.relay, ("relay.example.net", 7780))
        self.assertEqual(len(first.relay_secret), 32)
        moved = settings.set_relay(self.world, "81.2.69.160", 443)
        self.assertEqual(moved.relay_secret, first.relay_secret)
        reopened = NetworkSettings(self.root).get(self.world)
        self.assertEqual((reopened.relay, reopened.relay_secret), (("81.2.69.160", 443), first.relay_secret))
        self.assertNotIn(first.relay_secret.hex(), repr(reopened))
        off = settings.disable_relay(self.world)
        self.assertIsNone(off.relay)
        self.assertEqual(off.relay_secret, first.relay_secret)
        renewed = settings.new_relay_key(self.world)
        self.assertNotEqual(renewed.relay_secret, first.relay_secret)
        self.assertFalse(settings.set_router_setup(self.world, False).router_setup)
        record = json.loads((self.root / "shell" / "network.json").read_text())
        self.assertEqual(set(record["worlds"][self.world]), {"router_setup", "relay_enabled", "relay_address", "relay_port",
                                                             "relay_secret"})

    def test_unusable_values_are_refused_and_a_damaged_file_is_not_trusted(self):
        settings = NetworkSettings(self.root)
        for address, port in (("0.0.0.0", 7780), ("bad host", 7780), ("relay.example.net", 0)):
            with self.subTest(address=address), self.assertRaises(ValueError):
                settings.set_relay(self.world, address, port)
        with self.assertRaises(ValueError):
            settings.set_router_setup("not-a-world", True)
        (self.root / "shell" / "network.json").parent.mkdir(parents=True, exist_ok=True)
        (self.root / "shell" / "network.json").write_text('{"format": "emerald-network-settings-v1", "worlds": {"x": 1}}')
        damaged = NetworkSettings(self.root)
        self.assertFalse(damaged.available)
        self.assertEqual(damaged.get(self.world), WorldNetwork())


class JoinRouteTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.world, self.player = str(uuid4()), str(uuid4())

    def test_the_route_file_says_direct_or_relay(self):
        profile = route_path(self.root, self.world, self.player).parent
        self.assertIsNone(load_join_route(profile))
        save_join_route(self.root, self.world, self.player, ("relay.example.net", 7780))
        self.assertEqual(load_join_route(profile), ("relay.example.net", 7780))
        save_join_route(self.root, self.world, self.player, None)
        self.assertIsNone(load_join_route(profile))
        route_path(self.root, self.world, self.player).write_text("not json")
        self.assertIsNone(load_join_route(profile))
        with self.assertRaises(ValueError):
            save_join_route(self.root, self.world, self.player, ("bad host", 1))

    def test_a_saved_server_remembers_its_route_and_keeps_the_route_file_in_step(self):
        servers = SavedServers(self.root / "shell")
        profile = route_path(self.root, self.world, self.player).parent
        server, created = servers.add("Pal's server", "81.2.69.160", 7777, self.world, self.player, 1, "Pal",
                                      relay=("relay.example.net", 7780))
        self.assertTrue(created)
        self.assertEqual(relay_of(server), ("relay.example.net", 7780))
        self.assertEqual(load_join_route(profile), ("relay.example.net", 7780))
        server = servers.edit(server["id"], relay=None)
        self.assertIsNone(relay_of(server))
        self.assertIsNone(load_join_route(profile))
        server, created = servers.add("again", "81.2.69.160", 7777, self.world, self.player, 1, "Pal", relay=("81.2.69.161", 443))
        self.assertFalse(created)
        self.assertEqual(load_join_route(profile), ("81.2.69.161", 443))
        self.assertEqual(relay_of(SavedServers(self.root / "shell").get(server["id"])), ("81.2.69.161", 443))
        with self.assertRaises(ValueError):
            servers.edit(server["id"], relay=("0.0.0.0", 1))

    def test_records_written_before_relays_existed_still_load_as_direct(self):
        shell = self.root / "shell"
        shell.mkdir()
        old = {"format": "emerald-saved-servers-v1", "servers": [dict(
            id=str(uuid4()), name="Old", address="192.168.1.5", port=7777, world_id=self.world, player_id=self.player, slot=1,
            display_name="Pal", added=1.0, last_joined=None)]}
        (shell / "servers.json").write_text(json.dumps(old))
        servers = SavedServers(shell)
        self.assertTrue(servers.available)
        self.assertIsNone(relay_of(servers.all()[0]))
        # A direct shortcut does not create a route file it does not need.
        servers.add("Old", "192.168.1.6", 7777, self.world, self.player, 1, "Pal")
        self.assertFalse(route_path(self.root, self.world, self.player).exists())


if __name__ == "__main__":
    unittest.main()
