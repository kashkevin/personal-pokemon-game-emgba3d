from __future__ import annotations

import asyncio
import struct
import unittest
import uuid

from emerald_multiplayer.protocol import MAX_FRAME_BYTES, encode_message, read_message
from emerald_multiplayer.server import (
    OutboundClosed, OutboundFull, OutboundQueue, ServerConfig, WorldServer,
    is_local_address,
)

BUILD = "test-mailbox-rom-build"
RULESET = "clean-upstream-test"


class Client:
    def __init__(self, reader, writer, player_id):
        self.reader, self.writer, self.player_id = reader, writer, player_id
        self.epoch = None

    @classmethod
    async def connect(cls, address, *, player_id=None, **hello_changes):
        reader, writer = await asyncio.open_connection(*address)
        client = cls(reader, writer, player_id or str(uuid.uuid4()))
        await client.send({
            "type": "hello", "protocol": 1, "build_id": BUILD,
            "ruleset_id": RULESET, "player_id": client.player_id,
            "display_name": "Player", **hello_changes,
        })
        result = await client.next()
        if result["type"] == "welcome":
            client.epoch = result["session_epoch"]
        return client, result

    async def send(self, message):
        self.writer.write(encode_message(message))
        await self.writer.drain()

    async def next(self):
        return await asyncio.wait_for(read_message(self.reader), 1.5)

    async def world(self, predicate=lambda message: True):
        async with asyncio.timeout(1.5):
            while True:
                message = await read_message(self.reader)
                if message is None:
                    raise AssertionError("connection closed before the expected world")
                if message["type"] == "ping":
                    await self.send({**message, "type": "pong"})
                elif message["type"] == "world" and predicate(message):
                    return message

    async def move(self, seq=1, map_epoch=0, **changes):
        await self.send({
            "type": "presence", "session_epoch": self.epoch, "seq": seq,
            "map_epoch": map_epoch, "map_group": 0, "map_number": 1,
            "x": 5, "y": 6, "direction": 1, "elevation": 0,
            "avatar_gender": 0, "movement_mode": "walk",
            "activity": "overworld", **changes,
        })

    async def close(self):
        self.writer.close()
        await self.writer.wait_closed()


async def wait_until(predicate, timeout=1.5):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)


def find_player(world, player_id):
    return next((player for player in world["players"] if player["player_id"] == player_id), None)


class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = WorldServer(ServerConfig(BUILD, RULESET))
        await self.server.start(port=0)
        self.clients = []

    async def asyncTearDown(self):
        for client in self.clients:
            await client.close()
        await self.server.close()

    async def connect(self, **changes):
        client, result = await Client.connect(self.server.address, **changes)
        self.clients.append(client)
        return client, result

    async def test_welcome_precedes_snapshot_and_sender_is_included(self):
        client, welcome = await self.connect()
        self.assertEqual(welcome["type"], "welcome")
        self.assertEqual(welcome["build_id"], BUILD)
        self.assertEqual(welcome["max_players"], 4)
        world = await client.world()
        self.assertEqual(len(world["players"]), 1)
        own = find_player(world, client.player_id)
        self.assertEqual(own["session_epoch"], client.epoch)
        self.assertIsNone(own["presence"])

    async def test_four_independent_players_two_maps_and_fifth_rejected(self):
        for index in range(4):
            client, welcome = await self.connect(display_name=f"Player {index}")
            self.assertEqual(welcome["type"], "welcome")
            await client.move(map_number=index % 2, x=index + 10, avatar_gender=index % 2)
        world = await self.clients[0].world(lambda message: len(message["players"]) == 4 and all(player["presence"] is not None for player in message["players"]))
        for index, client in enumerate(self.clients):
            own = find_player(world, client.player_id)
            self.assertEqual(own["presence"]["x"], index + 10)
            self.assertEqual(own["presence"]["map_number"], index % 2)
        rejected, error = await self.connect()
        self.assertEqual(error["code"], "server_full")
        self.assertIsNone(await rejected.next())
        self.assertEqual(len(self.server.sessions), 4)

    async def test_two_clients_receive_each_others_independent_positions(self):
        first, _ = await self.connect()
        second, _ = await self.connect()
        await first.move(x=17, direction=4)
        await second.move(x=-2, direction=3, map_number=7)
        for client in (first, second):
            world = await client.world(lambda message: len(message["players"]) == 2 and all(player["presence"] is not None for player in message["players"]))
            self.assertEqual(find_player(world, first.player_id)["presence"]["x"], 17)
            self.assertEqual(find_player(world, second.player_id)["presence"]["x"], -2)

    async def test_identity_protocol_build_and_ruleset_rejection(self):
        for changes, expected in (
            ({"protocol": 2}, "unsupported_protocol"),
            ({"build_id": "different"}, "build_mismatch"),
            ({"ruleset_id": "gen6"}, "ruleset_mismatch"),
            ({"player_id": "invalid"}, "invalid_player_id"),
        ):
            with self.subTest(changes=changes):
                client, error = await self.connect(**changes)
                self.assertEqual(error["code"], expected)
                self.assertIsNone(await client.next())
        self.assertFalse(self.server.sessions)

    async def test_duplicate_lease_rejected_disconnect_and_rejoin_new_epoch(self):
        first, _ = await self.connect()
        observer, _ = await self.connect()
        await first.move(x=21)
        await observer.world(lambda message: (find_player(message, first.player_id) or {}).get("presence") is not None)
        duplicate, error = await self.connect(player_id=first.player_id)
        self.assertEqual(error["code"], "player_already_connected")
        self.assertIsNone(await duplicate.next())
        old_epoch = first.epoch
        await first.close()
        await observer.world(lambda message: find_player(message, first.player_id) is None)
        rejoined, welcome = await self.connect(player_id=first.player_id)
        self.assertGreater(welcome["session_epoch"], old_epoch)
        world = await observer.world(lambda message: find_player(message, first.player_id) is not None)
        self.assertIsNone(find_player(world, first.player_id)["presence"])
        await rejoined.move(x=42)
        await observer.move(seq=2, x=30)
        world = await observer.world(lambda message: (find_player(message, first.player_id) or {}).get("presence") is not None)
        self.assertEqual(find_player(world, first.player_id)["presence"]["x"], 42)

    async def test_stale_sequence_and_map_epochs_are_ignored(self):
        client, _ = await self.connect()
        await client.move(seq=1, map_epoch=0, x=1)
        await wait_until(lambda: self.server.sessions[client.player_id].presence is not None)
        await client.move(seq=2, map_epoch=2, x=2)  # Reload the same map.
        await wait_until(lambda: self.server.sessions[client.player_id].presence["seq"] == 2)
        await client.move(seq=3, map_epoch=1, x=99)
        await client.move(seq=1, map_epoch=2, x=98)
        await client.move(seq=4, map_epoch=2, map_number=2, x=97)
        # A ping/pong round trip proves all preceding TCP frames were processed.
        await client.send({"type": "ping", "protocol": 1, "session_epoch": client.epoch, "nonce": 7})
        while (await client.next())["type"] != "pong":
            pass
        current = self.server.sessions[client.player_id].presence
        self.assertEqual((current["seq"], current["x"], current["map_number"]), (2, 2, 1))
        await client.move(seq=5, map_epoch=3, map_number=2, x=3)
        world = await client.world(lambda message: find_player(message, client.player_id)["presence"]["seq"] == 5)
        self.assertEqual(find_player(world, client.player_id)["presence"]["map_number"], 2)

    async def test_old_connection_epoch_is_rejected(self):
        client, _ = await self.connect()
        await client.move(session_epoch=client.epoch + 1)
        while True:
            message = await client.next()
            if message["type"] == "error":
                break
        self.assertEqual(message["code"], "session_epoch_mismatch")
        self.assertIsNone(await client.next())
        await wait_until(lambda: not self.server.sessions)

    async def test_real_partial_hello_and_oversized_frame(self):
        reader, writer = await asyncio.open_connection(*self.server.address)
        self.clients.append(Client(reader, writer, "partial"))
        frame = encode_message({
            "type": "hello", "protocol": 1, "build_id": BUILD, "ruleset_id": RULESET,
            "player_id": str(uuid.uuid4()), "display_name": "Partial",
        })
        for chunk in (frame[:1], frame[1:3], frame[3:20], frame[20:]):
            writer.write(chunk)
            await writer.drain()
            await asyncio.sleep(0)
        self.assertEqual((await asyncio.wait_for(read_message(reader), 1))["type"], "welcome")
        self.assertEqual((await read_message(reader))["type"], "world")
        writer.write(struct.pack("!I", MAX_FRAME_BYTES + 1))
        await writer.drain()
        error = await asyncio.wait_for(read_message(reader), 1)
        self.assertEqual(error["code"], "frame_too_large")
        self.assertIsNone(await read_message(reader))

    async def test_stalled_consumer_is_removed_other_player_continues(self):
        await self.server.close()
        self.server = WorldServer(ServerConfig(BUILD, RULESET, send_timeout=0.08))
        await self.server.start(port=0)
        slow, _ = await self.connect()
        observer, _ = await self.connect()
        await slow.world(lambda message: len(message["players"]) == 2)
        session = self.server.sessions[slow.player_id]
        stalled = asyncio.Event()

        async def blocked_drain():
            stalled.set()
            await asyncio.Event().wait()

        session.writer.drain = blocked_drain
        self.server._control(session, {"type": "test-control"})
        await stalled.wait()
        await observer.move(x=55)
        world = await observer.world(lambda message: find_player(message, slow.player_id) is None)
        self.assertEqual(find_player(world, observer.player_id)["presence"]["x"], 55)
        self.assertEqual(session.close_reason, "slow_or_disconnected_consumer")
        self.assertEqual(len(self.server.sessions), 1)

    async def test_control_flood_is_bounded_and_other_client_remains_connected(self):
        flooded, _ = await self.connect()
        observer, _ = await self.connect()
        await flooded.world(lambda message: len(message["players"]) == 2)
        session = self.server.sessions[flooded.player_id]
        flooded.writer.write(b"".join(encode_message({
            "type": "ping", "protocol": 1, "session_epoch": flooded.epoch,
            "nonce": index,
        }) for index in range(100)))
        await flooded.writer.drain()
        world = await observer.world(lambda message: find_player(message, flooded.player_id) is None)
        self.assertEqual(session.close_reason, "control_backpressure")
        self.assertIsNotNone(find_player(world, observer.player_id))
        await observer.move(x=63)
        world = await observer.world(lambda message: find_player(message, observer.player_id)["presence"] is not None)
        self.assertEqual(find_player(world, observer.player_id)["presence"]["x"], 63)

    async def test_coalescing_keeps_only_latest_world_for_a_stalled_writer(self):
        await self.server.close()
        self.server = WorldServer(ServerConfig(BUILD, RULESET, send_timeout=5))
        await self.server.start(port=0)
        slow, _ = await self.connect()
        producer, _ = await self.connect()
        await slow.world(lambda message: len(message["players"]) == 2)
        session = self.server.sessions[slow.player_id]
        stalled = asyncio.Event()

        async def blocked_drain():
            stalled.set()
            await asyncio.Event().wait()

        session.writer.drain = blocked_drain
        self.server._control(session, {"type": "test-control"})
        await stalled.wait()
        for index in range(1, 101):
            await producer.move(seq=index, x=index)
        await wait_until(lambda: self.server.sessions[producer.player_id].presence is not None and self.server.sessions[producer.player_id].presence["seq"] == 100)
        self.assertIsNotNone(session.outbox.world)
        reader = asyncio.StreamReader()
        reader.feed_data(session.outbox.world)
        pending_world = await read_message(reader)
        self.assertEqual(find_player(pending_world, producer.player_id)["presence"]["x"], 100)
        self.assertLessEqual(len(session.outbox.controls), self.server.config.reliable_limit)


class TimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = WorldServer(ServerConfig(
            BUILD, RULESET, heartbeat_interval=0.05, idle_timeout=0.3,
            presence_timeout=0.08, handshake_timeout=0.05, monitor_interval=0.005,
        ))
        await self.server.start(port=0)
        self.clients = []

    async def asyncTearDown(self):
        for client in self.clients:
            await client.close()
        await self.server.close()

    async def test_hello_timeout_and_idle_cleanup(self):
        reader, writer = await asyncio.open_connection(*self.server.address)
        pending = Client(reader, writer, "pending")
        self.clients.append(pending)
        self.assertEqual((await pending.next())["code"], "hello_timeout")
        self.assertIsNone(await pending.next())
        client, _ = await Client.connect(self.server.address)
        self.clients.append(client)
        session = self.server.sessions[client.player_id]
        await wait_until(lambda: client.player_id not in self.server.sessions)
        self.assertEqual(session.close_reason, "heartbeat_timeout")

    async def test_game_inactive_then_fresh_presence_and_heartbeat_resumes(self):
        client, _ = await Client.connect(self.server.address)
        self.clients.append(client)
        await client.move()
        world = await client.world(lambda message: (find_player(message, client.player_id) or {}).get("presence") is not None and find_player(message, client.player_id)["presence"]["activity"] == "unavailable")
        self.assertEqual(find_player(world, client.player_id)["presence"]["seq"], 1)
        await client.move(seq=2, x=7)
        world = await client.world(lambda message: find_player(message, client.player_id)["presence"]["seq"] == 2)
        self.assertEqual(find_player(world, client.player_id)["presence"]["activity"], "overworld")
        # Handle real server heartbeats for longer than one idle timeout.
        finish = asyncio.get_running_loop().time() + 0.35
        while asyncio.get_running_loop().time() < finish:
            message = await client.next()
            if message["type"] == "ping":
                self.assertEqual(message["session_epoch"], client.epoch)
                await client.send({**message, "type": "pong"})
        self.assertIn(client.player_id, self.server.sessions)


class QueueAndGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_control_capacity_prioritization_and_world_replacement(self):
        outbox = OutboundQueue(2)
        outbox.put_world(b"old")
        outbox.put_control(b"one")
        outbox.put_control(b"two")
        outbox.put_world(b"latest")
        with self.assertRaises(OutboundFull):
            outbox.put_control(b"three")
        self.assertEqual(await outbox.get(), b"one")
        self.assertEqual(await outbox.get(), b"two")
        self.assertEqual(await outbox.get(), b"latest")
        pending = asyncio.create_task(outbox.get())
        await asyncio.sleep(0)
        outbox.close()
        with self.assertRaises(OutboundClosed):
            await pending

    async def test_public_wildcard_and_implicit_lan_binds_are_rejected(self):
        server = WorldServer(ServerConfig(BUILD, RULESET))
        for host, allow_lan in (("0.0.0.0", True), ("::", True), ("8.8.8.8", True), ("192.168.1.2", False), ("localhost", False)):
            with self.subTest(host=host):
                with self.assertRaises(ValueError):
                    await server.start(host, 0, allow_lan=allow_lan)
        self.assertTrue(is_local_address("127.0.0.1"))
        self.assertTrue(is_local_address("::1"))
        self.assertTrue(is_local_address("::ffff:127.0.0.1"))
        self.assertTrue(is_local_address("192.168.1.2", True))
        self.assertTrue(is_local_address("fd00::2", True))
        self.assertFalse(is_local_address("8.8.8.8", True))
        self.assertFalse(is_local_address("100.64.0.1", True))


if __name__ == "__main__":
    unittest.main()
