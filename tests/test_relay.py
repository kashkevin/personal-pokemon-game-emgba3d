"""The relay: a friend reaches the host's world through it with end-to-end TLS and the same pin check; the relay sees only
ciphertext, keeps rooms for their first registrant, bounds every preamble and idles out silent pipes. Everything is on loopback."""
import asyncio
from dataclasses import replace
import secrets
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from emerald_multiplayer import relay as relay_module
from emerald_multiplayer.companion import Companion
from emerald_multiplayer.connection_diagnostics import check_server
from emerald_multiplayer.invite_code import fetch_certificate
from emerald_multiplayer.network_settings import save_join_route
from emerald_multiplayer.relay import (
    RelayError, RelayHostAgent, RelayLimits, RelayServer, open_relay_connection, room_token, run_cli,
)
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.server_check import OK, probe_route
from net_fixtures import free_port, make_installation, make_world


async def wait_for(predicate, timeout=5.0):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(.01)


async def send(port, text):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(text if isinstance(text, bytes) else text.encode())
    await writer.drain()
    return reader, writer


async def answer(reader, timeout=3):
    return (await asyncio.wait_for(reader.readline(), timeout)).decode().strip()


class RelayBase(unittest.IsolatedAsyncioTestCase):
    async def relay(self, **limits):
        server = RelayServer(RelayLimits(**limits) if limits else None)
        await server.start("127.0.0.1", 0)
        self.addAsyncCleanup(server.close)
        return server

    def close_later(self, writer):
        self.addCleanup(writer.close)


class EndToEndTests(RelayBase):
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

    async def world_server(self, world=None, *, relayed=True):
        world = world or self.world
        store = world.open_store()
        self.addCleanup(store.close)
        server = WorldServer(ServerConfig(world.build_id, world.ruleset_id), store=store)
        await server.start("127.0.0.1", 0, tls=world.server_tls, relay=relayed)
        self.addAsyncCleanup(server.close)
        return server

    async def agent(self, relay, server, world=None, secret=None):
        world = world or self.world
        target = (lambda: server.relay_address) if server is not None else (lambda: (_ for _ in ()).throw(RuntimeError()))
        agent = RelayHostAgent("127.0.0.1", relay.address[1], self.world.world_id, secret or secrets.token_bytes(32), target)
        await agent.start()
        self.addAsyncCleanup(agent.close)
        await wait_for(lambda: agent.status.code != "relay_connecting")
        return agent

    def friend(self, relay_port, private):
        save_join_route(private, self.world.world_id, self.world.accounts[1].player_id, ("127.0.0.1", relay_port))
        profile = private / "players" / self.world.world_id / self.world.accounts[1].player_id
        config = self.world.invitation(1).companion_config(self.installation.rom_path, self.installation.manifest_path,
                                                           token=secrets.token_bytes(32), private_directory=profile)
        companion = Companion(replace(config, reconnect_delay=.05))
        self.addAsyncCleanup(companion.close)
        return companion

    async def test_a_friend_joins_through_the_relay_with_end_to_end_tls_and_the_relay_sees_only_ciphertext(self):
        relay = await self.relay()
        server = await self.world_server()
        agent = await self.agent(relay, server)
        self.assertEqual(agent.status.code, "relay_ready")
        seen = []
        original = relay_module.pipe

        class Recorder:
            def __init__(self, reader):
                self.reader = reader

            async def read(self, size):
                data = await self.reader.read(size)
                seen.append(data)
                return data

        async def recording(a_reader, a_writer, b_reader, b_writer, **options):
            await original(Recorder(a_reader), a_writer, Recorder(b_reader), b_writer, **options)
        private = Path(tempfile.mkdtemp(dir=self.root))
        companion = self.friend(relay.address[1], private)
        self.assertEqual((companion.config.relay_host, companion.config.relay_port), ("127.0.0.1", relay.address[1]))
        with patch.object(relay_module, "pipe", recording):
            await companion.start()
            await wait_for(lambda: companion.connected, 10)
            self.assertEqual(companion.world_id, self.world.world_id)
            self.assertIn(self.world.accounts[1].player_id, server.sessions)
            await wait_for(lambda: agent.status.friends == 1)
            traffic = b"".join(seen)
            self.assertGreater(len(traffic), 500)
            self.assertNotIn(self.world.accounts[1].credential.hex().encode(), traffic)
            self.assertNotIn(b'"hello"', traffic)
            self.assertNotIn(self.world.accounts[1].player_id.encode(), traffic)
            await companion.close()

    async def test_checks_and_certificate_fetch_work_through_the_relay(self):
        relay = await self.relay()
        server = await self.world_server()
        await self.agent(relay, server)
        route = ("127.0.0.1", relay.address[1])
        result = await check_server("192.168.70.50", self.world.port, certificate_sha256=self.world.certificate_sha256,
                                    world_id=self.world.world_id, build_id=self.world.build_id, ruleset_id=self.world.ruleset_id,
                                    relay=route, timeout=5)
        self.assertEqual((result.code, result.route, result.port), ("ok", "relay", relay.address[1]))
        pem = await fetch_certificate("192.168.70.50", self.world.port, self.world.certificate_sha256, self.world.world_id,
                                      relay=route)
        self.assertEqual(pem, self.world.invitation(1).certificate_pem)
        probe = await probe_route(self.world.invitation(1), "192.168.70.50", self.world.port, self.root / "checks", relay=route)
        self.assertEqual(probe.code, OK)
        self.assertEqual(server.sessions, {})

    async def test_the_relay_cannot_stand_in_for_the_host_the_pin_still_decides(self):
        relay = await self.relay()
        impostor = await self.world_server(self.other)
        await self.agent(relay, impostor)                      # someone else's world registered under this world's room
        result = await check_server("192.168.70.50", self.world.port, certificate_sha256=self.world.certificate_sha256,
                                    world_id=self.world.world_id, relay=("127.0.0.1", relay.address[1]), timeout=5)
        self.assertEqual(result.code, "wrong_world")
        companion = self.friend(relay.address[1], Path(tempfile.mkdtemp(dir=self.root)))
        await companion.start()
        await wait_for(lambda: companion.stopped is not None, 10)
        self.assertEqual(companion.stopped, "wrong_world")
        self.assertEqual(impostor.sessions, {})

    async def test_without_relayed_connections_enabled_the_friend_is_told_the_host_did_not_answer(self):
        relay = await self.relay(pair_timeout=1.0)
        server = await self.world_server(relayed=False)
        await self.agent(relay, None)
        result = await check_server("192.168.70.50", self.world.port, certificate_sha256=self.world.certificate_sha256,
                                    world_id=self.world.world_id, relay=("127.0.0.1", relay.address[1]), timeout=5)
        self.assertEqual(result.code, "relay_host_offline")
        self.assertEqual(server.sessions, {})

    async def test_a_relay_nobody_runs_and_a_room_nobody_holds_have_their_own_codes(self):
        with self.assertRaises(RelayError) as caught:
            await open_relay_connection("127.0.0.1", free_port(), self.world.world_id)
        self.assertEqual((caught.exception.code, caught.exception.reason_code), ("relay_unreachable", "refused"))
        relay = await self.relay()
        with self.assertRaises(RelayError) as caught:
            await open_relay_connection("127.0.0.1", relay.address[1], self.world.world_id)
        self.assertEqual(caught.exception.code, "relay_host_offline")
        result = await check_server("192.168.70.50", self.world.port, certificate_sha256=self.world.certificate_sha256,
                                    world_id=self.world.world_id, relay=("127.0.0.1", relay.address[1]), timeout=5)
        self.assertEqual(result.code, "relay_host_offline")
        self.assertIn("not connected to the relay", result.title)


class RoomTests(RelayBase):
    room = "6f1c9a52-2d4b-4b8e-9a43-1f0d2a7b9c11"

    async def test_the_first_registrant_holds_the_room_and_a_different_key_is_refused(self):
        relay = await self.relay()
        port = relay.address[1]
        secret = secrets.token_bytes(32)
        owner = RelayHostAgent("127.0.0.1", port, self.room, secret, lambda: ("127.0.0.1", 1))
        await owner.start()
        self.addAsyncCleanup(owner.close)
        await wait_for(lambda: owner.status.ready)
        thief = RelayHostAgent("127.0.0.1", port, self.room, secrets.token_bytes(32), lambda: ("127.0.0.1", 1))
        await thief.start()
        self.addAsyncCleanup(thief.close)
        await wait_for(lambda: thief.status.code == "relay_room_taken")
        self.assertIn("different relay key", thief.status.message)
        reader, writer = await send(port, f"ETR1 HOST {self.room} {'0' * 64}\n")
        self.close_later(writer)
        self.assertEqual(await answer(reader), "ERR room_taken")
        # The owner's key takes the room back even from a stale control connection, and the room survives its host leaving.
        reader, writer = await send(port, f"ETR1 HOST {self.room} {room_token(secret, self.room)}\n")
        self.close_later(writer)
        self.assertEqual(await answer(reader), "OK")
        await owner.close()
        writer.close()
        await wait_for(lambda: relay.rooms[self.room].control is None)
        reader, writer = await send(port, f"ETR1 HOST {self.room} {'1' * 64}\n")
        self.close_later(writer)
        self.assertEqual(await answer(reader), "ERR room_taken")

    async def test_the_token_is_derived_from_the_secret_and_never_is_the_secret(self):
        secret = secrets.token_bytes(32)
        token = room_token(secret, self.room)
        self.assertRegex(token, "^[0-9a-f]{64}$")
        self.assertNotIn(secret.hex(), token)
        self.assertNotEqual(token, room_token(secret, "6f1c9a52-2d4b-4b8e-9a43-1f0d2a7b9c12"))
        with self.assertRaises(ValueError):
            room_token(b"short", self.room)

    async def test_a_silent_pipe_is_closed_after_the_idle_timeout(self):
        relay = await self.relay(idle_timeout=.5)
        port = relay.address[1]
        control_reader, control = await send(port, f"ETR1 HOST {self.room} {'2' * 64}\n")
        self.close_later(control)
        self.assertEqual(await answer(control_reader), "OK")
        friend_reader, friend = await send(port, f"ETR1 JOIN {self.room}\n")
        self.close_later(friend)
        connect = await answer(control_reader)
        self.assertRegex(connect, "^CONNECT [0-9a-f]{32}$")
        data_reader, data = await send(port, f"ETR1 DATA {self.room} {connect.split()[1]}\n")
        self.close_later(data)
        self.assertEqual(await answer(data_reader), "OK")
        self.assertEqual(await answer(friend_reader), "OK")
        friend.write(b"ping")
        await friend.drain()
        self.assertEqual(await asyncio.wait_for(data_reader.readexactly(4), 3), b"ping")
        started = asyncio.get_running_loop().time()
        self.assertEqual(await asyncio.wait_for(friend_reader.read(), 5), b"")
        self.assertLess(asyncio.get_running_loop().time() - started, 4)
        self.assertEqual(relay.rooms[self.room].pipes, 0)

    async def test_a_host_that_never_answers_a_friend_and_an_unknown_data_id_are_refused(self):
        relay = await self.relay(pair_timeout=.3)
        port = relay.address[1]
        control_reader, control = await send(port, f"ETR1 HOST {self.room} {'3' * 64}\n")
        self.close_later(control)
        self.assertEqual(await answer(control_reader), "OK")
        friend_reader, friend = await send(port, f"ETR1 JOIN {self.room}\n")
        self.close_later(friend)
        self.assertEqual(await answer(friend_reader), "ERR host_timeout")
        reader, writer = await send(port, f"ETR1 DATA {self.room} {'a' * 32}\n")
        self.close_later(writer)
        self.assertEqual(await answer(reader), "ERR unknown_connection")
        reader, writer = await send(port, "ETR1 JOIN 6f1c9a52-2d4b-4b8e-9a43-1f0d2a7b9c99\n")
        self.close_later(writer)
        self.assertEqual(await answer(reader), "ERR host_offline")


class PreambleAndLimitTests(RelayBase):
    async def test_malformed_preambles_are_refused_with_one_short_line(self):
        relay = await self.relay(preamble_timeout=.5)
        port = relay.address[1]
        cases = [b"hello\n", b"ETR9 JOIN 6f1c9a52-2d4b-4b8e-9a43-1f0d2a7b9c11\n", b"ETR1 JOIN not-a-room\n",
                 b"ETR1 HOST 6f1c9a52-2d4b-4b8e-9a43-1f0d2a7b9c11 short\n", b"ETR1 JOIN \xff\xfe\n", b"ETR1 SHOUT\n",
                 b"ETR1 JOIN 6f1c9a52-2d4b-4b8e-9a43-1f0d2a7b9c11 extra\n", b"x" * 300]
        for request in cases:
            with self.subTest(request=request[:24]):
                reader, writer = await send(port, request)
                self.close_later(writer)
                reply = await asyncio.wait_for(reader.read(), 3)
                self.assertEqual(reply, b"ERR bad_request\n")
                self.assertLessEqual(len(reply), relay_module.MAX_REPLY)

    async def test_a_silent_connection_is_closed_after_the_preamble_timeout(self):
        relay = await self.relay(preamble_timeout=.3)
        reader, writer = await send(relay.address[1], b"ETR1 JO")
        self.close_later(writer)
        started = asyncio.get_running_loop().time()
        self.assertEqual(await asyncio.wait_for(reader.read(), 3), b"ERR bad_request\n")
        self.assertLess(asyncio.get_running_loop().time() - started, 2)

    async def test_connection_and_room_limits(self):
        relay = await self.relay(max_connections=2, max_rooms=1)
        port = relay.address[1]
        first_reader, first = await send(port, "ETR1 HOST 6f1c9a52-2d4b-4b8e-9a43-1f0d2a7b9c11 " + "4" * 64 + "\n")
        self.close_later(first)
        self.assertEqual(await answer(first_reader), "OK")
        second_reader, second = await send(port, "ETR1 HOST 6f1c9a52-2d4b-4b8e-9a43-1f0d2a7b9c12 " + "5" * 64 + "\n")
        self.close_later(second)
        self.assertEqual(await answer(second_reader), "ERR full")
        await wait_for(lambda: relay._connections == 1)
        holder_reader, holder = await send(port, "ETR1 JO")         # occupies the second slot while it types
        self.close_later(holder)
        await wait_for(lambda: relay._connections == 2)
        third_reader, third = await send(port, "ETR1 JOIN 6f1c9a52-2d4b-4b8e-9a43-1f0d2a7b9c11\n")
        self.close_later(third)
        self.assertEqual(await answer(third_reader), "ERR busy")

    def test_limits_are_validated(self):
        for change in ({"max_rooms": 0}, {"idle_timeout": 0}, {"ping_interval": 90}, {"max_connections": True}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                RelayLimits(**change)


class CommandLineTests(unittest.TestCase):
    def test_the_relay_command_line_and_the_packaged_entry(self):
        with self.assertRaises(SystemExit):
            run_cli(["serve", "--port", "nope"])
        with patch.object(relay_module, "run_cli", return_value=0) as run:
            self.assertEqual(relay_module.frozen_main(["--relay-server", "--port", "7780"]), 0)
        run.assert_called_once_with(["serve", "--port", "7780"])
        from emerald_multiplayer import shell_app
        with patch.object(sys, "argv", ["EmeraldTogether.exe", "--relay-server", "--port", "7781"]), \
                patch.object(relay_module, "frozen_main", return_value=0) as frozen:
            self.assertEqual(shell_app.main(object(), Path("."), None), 0)
        frozen.assert_called_once_with(["--relay-server", "--port", "7781"])

    def test_relay_addresses_people_type(self):
        for address, port in (("relay.example.net", 7780), ("81.2.69.160", 7780), ("100.101.102.103", 443), ("127.0.0.1", 1)):
            self.assertTrue(relay_module.valid_endpoint(address, port), address)
        for address, port in (("0.0.0.0", 7780), ("bad host", 7780), ("relay.example.net", 0), ("::", 7780), ("", 7780),
                              ("relay.example.net", True)):
            self.assertFalse(relay_module.valid_endpoint(address, port), address)


if __name__ == "__main__":
    unittest.main()
