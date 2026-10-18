"""A refusal is reported as itself: permanent refusals stop reconnecting, the session never claims a connection it did not
complete, and the menu receives the specific code (never the old catch-all "host did not respond")."""
import asyncio
from dataclasses import replace
import secrets
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from emerald_multiplayer.companion import Companion
from emerald_multiplayer.launcher_gui import SessionWorker, UiEvent, status_text, _TEXT
from emerald_multiplayer.launcher_session import LauncherSession, LauncherSessionError, SessionState
from emerald_multiplayer.protocol import MAX_PLAYERS, PROTOCOL_VERSION, encode_message, read_message
from emerald_multiplayer.connection_diagnostics import CODES
from net_fixtures import FakeWorldServer, make_installation, make_world


async def wait_for(predicate, timeout=5.0):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(.01)


class Base(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.installation = make_installation(cls.root)
        cls.world = make_world(cls.root, cls.installation)
        cls.other = make_world(cls.root, cls.installation, name="other", names=("Mallory", "Eve"))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.private = Path(tempfile.mkdtemp(dir=self.root))

    async def fake(self, world=None, **behaviour):
        server = await FakeWorldServer(world or self.world, **behaviour).start()
        self.addAsyncCleanup(server.close)
        return server

    def companion(self, port):
        invitation = self.world.invitation(1)
        config = invitation.companion_config(self.installation.rom_path, self.installation.manifest_path,
                                             token=secrets.token_bytes(32), private_directory=self.private / "profile")
        config = replace(config, server_host="127.0.0.1", server_port=port, reconnect_delay=.02)
        companion = Companion(config)
        self.addAsyncCleanup(companion.close)
        return companion

    def friend_session(self, port, **options):
        path = self.private / (str(uuid4()) + ".json")
        replace(self.world.invitation(1), endpoint="127.0.0.1").save(path)
        return LauncherSession(self.installation, self.private, invitation_path=path, server_route=("127.0.0.1", port), **options)


class CompanionRejectionTests(Base):
    async def test_a_permanent_refusal_stops_reconnecting_and_names_itself(self):
        fake = await self.fake(on_hello="public_exposure_disabled")
        companion = self.companion(fake.port)
        await companion.start()
        await wait_for(lambda: companion.stopped is not None)
        self.assertEqual(companion.stopped, "rejected_public_exposure_disabled")
        self.assertEqual(companion.failure, "rejected_public_exposure_disabled")
        await wait_for(lambda: companion._remote_task.done())
        await asyncio.sleep(.15)
        self.assertEqual(len(fake.hellos), 1, "a permanent refusal is not retried")
        self.assertFalse(companion.connected)

    async def test_a_different_game_version_and_a_bad_credential_are_permanent(self):
        for server_code, code in (("build_mismatch", "version_mismatch"), ("credentials_invalid", "rejected_invalid_credentials")):
            with self.subTest(server_code=server_code):
                fake = await self.fake(on_hello=server_code)
                companion = self.companion(fake.port)
                await companion.start()
                await wait_for(lambda: companion.stopped is not None)
                self.assertEqual(companion.stopped, code)
                await companion.close()

    async def test_another_world_at_the_address_is_wrong_world_and_gets_no_hello(self):
        fake = await self.fake(self.other, on_hello="credentials_required")
        companion = self.companion(fake.port)
        await companion.start()
        await wait_for(lambda: companion.stopped is not None)
        self.assertEqual(companion.stopped, "wrong_world")
        self.assertEqual(fake.hellos, [])

    async def test_a_refusal_that_clears_by_itself_keeps_retrying(self):
        fake = await self.fake(on_hello="player_already_connected")
        companion = self.companion(fake.port)
        await companion.start()
        await wait_for(lambda: len(fake.hellos) >= 2)
        self.assertIsNone(companion.stopped)
        self.assertEqual(companion.failure, "rejected_player_already_connected")

    async def test_nothing_listening_is_transient_and_classified(self):
        fake = await self.fake()
        port = fake.port
        await fake.close()
        companion = self.companion(port)
        await companion.start()
        await wait_for(lambda: companion.failure is not None)
        self.assertEqual(companion.failure, "refused")
        self.assertIsNone(companion.stopped)

    async def test_connected_is_set_only_after_the_servers_welcome(self):
        hello_seen, send_welcome, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        world = self.world

        async def handler(reader, writer):
            try:
                hello = await read_message(reader)
                hello_seen.set()
                await send_welcome.wait()
                writer.write(encode_message({
                    "type": "welcome", "protocol": PROTOCOL_VERSION, "build_id": hello["build_id"],
                    "ruleset_id": hello["ruleset_id"], "player_id": hello["player_id"], "session_epoch": 1,
                    "max_players": MAX_PLAYERS, "heartbeat_interval": 5, "idle_timeout": 20, "world_id": world.world_id,
                    "server_epoch": 1, "save_profile": world.save_profile, "checkpoint_enabled": True}))
                await writer.drain()
                await release.wait()
            finally:
                writer.close()
        server = await asyncio.start_server(handler, "127.0.0.1", 0, ssl=world.server_tls.build_context())
        self.addAsyncCleanup(server.wait_closed)
        self.addCleanup(server.close)
        self.addCleanup(release.set)
        companion = self.companion(server.sockets[0].getsockname()[1])
        await companion.start()
        await asyncio.wait_for(hello_seen.wait(), 5)
        await asyncio.sleep(.2)
        self.assertFalse(companion.connected, "TLS and a sent hello are not a connection")
        send_welcome.set()
        await wait_for(lambda: companion.connected)
        self.assertEqual(companion.world_id, world.world_id)


class SessionRejectionTests(Base):
    async def test_a_world_closed_to_this_network_fails_fast_with_its_own_code(self):
        fake = await self.fake(immediate="public_exposure_disabled")
        statuses = []
        session = self.friend_session(fake.port, connection_timeout=10, on_status=statuses.append)
        started = asyncio.get_running_loop().time()
        with self.assertRaises(LauncherSessionError) as caught:
            async with session.open():
                self.fail("a refused session cannot open")
        self.assertLess(asyncio.get_running_loop().time() - started, 5, "a permanent refusal does not wait for the timeout")
        self.assertEqual(caught.exception.code, "rejected_public_exposure_disabled")
        self.assertEqual(session.status.state, SessionState.FAILED)
        self.assertEqual(statuses[-1].code, "rejected_public_exposure_disabled")
        self.assertFalse(session.status.connected)
        self.assertIsNone(session._runtime)

    async def test_version_mismatch_and_wrong_world_reach_the_session(self):
        for world, behaviour, code in ((self.world, {"on_hello": "ruleset_mismatch"}, "version_mismatch"),
                                       (self.other, {"on_hello": "credentials_required"}, "wrong_world")):
            with self.subTest(code=code):
                fake = await self.fake(world, **behaviour)
                session = self.friend_session(fake.port, connection_timeout=10)
                with self.assertRaises(LauncherSessionError) as caught:
                    async with session.open():
                        self.fail("refused")
                self.assertEqual(caught.exception.code, code)

    async def test_a_server_that_never_welcomes_is_not_connected_and_times_out(self):
        fake = await self.fake()                          # reads the hello and says nothing
        session = self.friend_session(fake.port, connection_timeout=.6)
        with self.assertRaises(LauncherSessionError) as caught:
            async with session.open():
                self.fail("no welcome, no session")
        self.assertEqual(caught.exception.code, "connection_timeout")
        self.assertEqual(len(fake.hellos), 1)
        self.assertFalse(session.status.connected)
        self.assertIsNone(session._runtime)

    async def test_a_held_refusal_is_named_when_time_runs_out(self):
        fake = await self.fake(on_hello="player_already_connected")
        session = self.friend_session(fake.port, connection_timeout=.5)
        with self.assertRaises(LauncherSessionError) as caught:
            async with session.open():
                self.fail("refused")
        self.assertEqual(caught.exception.code, "rejected_player_already_connected")

    async def test_nothing_listening_times_out_with_refused_as_the_reason(self):
        fake = await self.fake()
        port = fake.port
        await fake.close()
        statuses = []
        session = self.friend_session(port, connection_timeout=.3, on_status=statuses.append)
        with self.assertRaises(LauncherSessionError) as caught:
            async with session.open():
                self.fail("nobody is there")
        self.assertEqual((caught.exception.code, caught.exception.reason), ("connection_timeout", "refused"))
        self.assertEqual((statuses[-1].code, statuses[-1].detail), ("connection_timeout", "refused"))


class WorkerPlumbingTests(unittest.TestCase):
    def test_every_new_session_code_has_its_own_clear_text(self):
        for code in ("version_mismatch", "wrong_world", "rejected_public_exposure_disabled", "rejected_player_already_connected",
                     "rejected_invalid_credentials", "rejected_enrollment_disabled", "rejected_server_full", "rejected_busy",
                     "rejected", "connection_timeout"):
            with self.subTest(code=code):
                self.assertIn(code, _TEXT)
                self.assertNotEqual(status_text(code), status_text("session_failed"))
        self.assertNotIn("did not respond", status_text("connection_timeout"))
        self.assertTrue(set(CODES))

    def test_a_failed_session_hands_its_code_and_reason_to_the_menu(self):
        class Refusing:
            def __init__(self, *args, **kwargs):
                pass

            def open(self):
                raise LauncherSessionError("connection_timeout", "timeout")
        worker = SessionWorker(object(), Path("."), factory=Refusing)
        worker._run({})
        event = worker.events.get_nowait()
        self.assertEqual((event.kind, event.code, event.detail), ("complete", "connection_timeout", "timeout"))
        self.assertIsInstance(event, UiEvent)


if __name__ == "__main__":
    unittest.main()
