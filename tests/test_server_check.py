"""server_check.probe_route: the saved-server check keeps its route codes and now also carries the specific reason."""
import tempfile
import unittest
from pathlib import Path

from emerald_multiplayer.server_check import NOT_THIS_WORLD, OK, REFUSED, RouteCheck, probe_route
from net_fixtures import FakeWorldServer, free_port, make_installation, make_world


class ProbeRouteTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        installation = make_installation(cls.root)
        cls.world = make_world(cls.root, installation)
        cls.other = make_world(cls.root, installation, name="other", names=("Mallory", "Eve"))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    async def test_the_right_world_is_ok(self):
        fake = await FakeWorldServer(self.world).start()
        self.addAsyncCleanup(fake.close)
        result = await probe_route(self.world.invitation(1), "127.0.0.1", fake.port, self.root / "checks", timeout=3)
        self.assertEqual((result.code, result.reason), (OK, "ok"))
        self.assertEqual(fake.hellos, [])

    async def test_nothing_listening_is_refused_with_its_explanation(self):
        result = await probe_route(self.world.invitation(1), "127.0.0.1", free_port(), self.root / "checks", timeout=3)
        self.assertEqual((result.code, result.reason), (REFUSED, "refused"))
        self.assertIn("Nothing is listening", result.message)
        self.assertIn("Host the world", " ".join(result.explanation(7777).host_steps))

    async def test_another_world_is_not_this_world(self):
        fake = await FakeWorldServer(self.other).start()
        self.addAsyncCleanup(fake.close)
        result = await probe_route(self.world.invitation(1), "127.0.0.1", fake.port, self.root / "checks", timeout=3)
        self.assertEqual((result.code, result.reason), (NOT_THIS_WORLD, "wrong_world"))
        self.assertIn("not this world", result.message)

    def test_a_route_check_made_from_a_code_alone_derives_its_reason(self):
        self.assertEqual(RouteCheck("timeout").reason, "timeout")
        self.assertEqual(RouteCheck("no_network").reason, "unreachable")
        self.assertEqual(RouteCheck("unreachable", "relay_host_offline").reason, "relay_host_offline")


if __name__ == "__main__":
    unittest.main()
