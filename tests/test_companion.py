from __future__ import annotations

import asyncio
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import secrets
import struct
import tempfile
import unittest
import uuid
import zlib

from emerald_multiplayer.bridge_protocol import encode_packet, read_packet
from emerald_multiplayer.companion import (
    BASELINE_RULESET, Companion, CompanionConfig, validate_welcome,
    validate_world, verify_rom_manifest,
)
from emerald_multiplayer.mailbox import Pose, Snapshot
from emerald_multiplayer.protocol import ProtocolError, encode_message, read_message
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.protocol import PROTOCOL_VERSION

# Shared-world fields carried by every world message (protocol 2; "spawns",
# the shared wild Pokemon of the player's map, since protocol 3).
WORLD_FIELDS = {"clock": {"seconds": 0, "running": False}, "event": None, "notice": None,
                "wallet": None, "teammate": None, "spawns": None}


def make_files(directory):
    # Synthetic bytes test identity/transport only; they are not a playable ROM.
    data = b"synthetic mailbox protocol fixture" * 32
    rom = Path(directory) / "fixture.gba"
    manifest = Path(directory) / "manifest.json"
    rom.write_bytes(data)
    manifest.write_text(json.dumps({
        "rom_sha256": hashlib.sha256(data).hexdigest(), "abi_version": 1,
        "mailbox_size": 128, "ruleset_id": BASELINE_RULESET,
        "rom_size": len(data), "rom_crc32": f"{zlib.crc32(data):08x}",
        "mailbox_address": 0x02020000,
    }), encoding="utf-8")
    return rom, manifest


def make_pose(frame=1, epoch=0, **changes):
    fields = dict(map_epoch=epoch, frame=frame, x=5, y=6, map_group=0,
                  map_number=1, direction=1, elevation=0, avatar_gender=0,
                  movement_mode=0, activity=1)
    return Pose(**{**fields, **changes})


async def wait_until(predicate, timeout=1.5):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)


class BinaryBridge:
    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer

    @classmethod
    async def connect(cls, companion, token=None):
        reader, writer = await asyncio.open_connection(*companion.ipc_address)
        bridge = cls(reader, writer)
        writer.write(encode_packet(b"H" + (token if token is not None else companion.config.token)))
        await writer.drain()
        return bridge

    async def pose(self, pose):
        self.writer.write(encode_packet(b"P" + pose.pack()))
        await self.writer.drain()

    async def snapshot(self, predicate=lambda value: True):
        async with asyncio.timeout(1.5):
            while True:
                packet = await read_packet(self.reader)
                if packet is None:
                    raise AssertionError("bridge closed before expected snapshot")
                if len(packet) != 89 or packet[:1] != b"S":
                    raise AssertionError("invalid binary snapshot")
                snapshot = Snapshot.unpack(packet[1:])
                if predicate(snapshot):
                    return snapshot

    async def close(self):
        self.writer.close()
        await self.writer.wait_closed()


class ConfigValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.rom, self.manifest = make_files(self.temp.name)
        self.config = CompanionConfig(self.rom, self.manifest, str(uuid.uuid4()), "Player", secrets.token_bytes(32))

    def tearDown(self):
        self.temp.cleanup()

    def test_actual_file_hash_required_and_manifest_bounds(self):
        self.assertEqual(verify_rom_manifest(self.rom, self.manifest)[0], self.config.build_id)
        self.rom.write_bytes(b"different")
        with self.assertRaises(ValueError):
            verify_rom_manifest(self.rom, self.manifest)
        self.rom, self.manifest = make_files(self.temp.name)
        original = json.loads(self.manifest.read_text())
        for changes in (
            {"abi_version": 2}, {"mailbox_size": 127}, {"ruleset_id": "gen6-complete"},
            {"rom_sha256": "0" * 64}, {"rom_crc32": "0" * 8},
            {"mailbox_address": 0x03000000}, {"mailbox_address": 0x02020001},
        ):
            with self.subTest(changes=changes):
                self.manifest.write_text(json.dumps({**original, **changes}))
                with self.assertRaises(ValueError):
                    verify_rom_manifest(self.rom, self.manifest)

    def test_no_public_ipc_or_world_connection_and_secret_not_in_repr(self):
        self.assertNotIn(self.config.token.hex(), repr(self.config))
        for changes in ({"ipc_host": "0.0.0.0"}, {"ipc_host": "192.168.1.1"}, {"server_host": "8.8.8.8"}, {"token": b"short"}, {"player_id": "invalid"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(self.config, **changes)

    def test_welcome_and_world_reject_mismatches_and_bad_rosters(self):
        welcome = {
            "type": "welcome", "protocol": PROTOCOL_VERSION, "build_id": self.config.build_id,
            "ruleset_id": BASELINE_RULESET, "player_id": self.config.player_id,
            "session_epoch": 1, "max_players": 4,
            "heartbeat_interval": 5, "idle_timeout": 20,
        }
        self.assertEqual(validate_welcome(welcome, self.config), welcome)
        for changes in ({"protocol": PROTOCOL_VERSION + 1}, {"build_id": "other"}, {"session_epoch": True}, {"max_players": 5}):
            with self.subTest(changes=changes), self.assertRaises(ProtocolError):
                validate_welcome({**welcome, **changes}, self.config)
        own = {"player_id": self.config.player_id, "display_name": "Player", "session_epoch": 1, "presence": None,
               "appearance": None}
        world = {"type": "world", "protocol": PROTOCOL_VERSION, "world_seq": 1, "players": [own], **WORLD_FIELDS}
        self.assertEqual(validate_world(world, self.config, 1), [own])
        safari = {"spawns": {"map_group": 26, "map_number": 0, "shared": False, "slots": []}}
        self.assertEqual(validate_world({**world, **safari}, self.config, 1), [own])
        slot = {"spawn_id": 1, "species": 263, "level": 3, "personality": 1, "shiny": False, "form": 0,
                "kind": "normal", "x": 1, "y": 1, "facing": 1, "move_seq": 0, "mine": False, "busy": False,
                "fresh": False, "seconds_left": 9}
        for changes in ({"players": [own, own]}, {"players": []}, {"world_seq": -1}, {"players": [{**own, "session_epoch": 2}]}, {"players": [{**own, "presence": {}}]},
                        {"clock": None}, {"wallet": {"seq": 1, "delta": 0}}, {"wallet": {"seq": 0, "delta": 5}},
                        {"teammate": "not-a-uuid"}, {"notice": {"id": 1, "text": "x" * 65, "to": None}},
                        {"spawns": {"map_group": 0, "map_number": 16}},
                        {"spawns": {"map_group": 0, "map_number": 16, "slots": []}},
                        {"spawns": {"map_group": 0, "map_number": 16, "shared": 1, "slots": []}},
                        {"spawns": {"map_group": 0, "map_number": 16, "shared": True, "slots": [{"spawn_id": 0}]}},
                        {"spawns": {"map_group": 26, "map_number": 0, "shared": False, "slots": [slot]}},
                        {"players": [{**own, "appearance": "zz"}]}, {"players": [{k: v for k, v in own.items() if k != "appearance"}]}):
            with self.subTest(changes=changes), self.assertRaises(ProtocolError):
                validate_world({**world, **changes}, self.config, 1)

    def test_equal_sequence_allows_only_server_unavailable_mark(self):
        companion = Companion(self.config)
        companion.connected, companion.session_epoch = True, 1
        # A welcome alone must never expose a connected ROM roster.
        self.assertEqual(companion.snapshot.connection_flags, 0)
        presence = {"session_epoch": 1, "seq": 1, "map_epoch": 0, **make_pose().network_fields(True)}
        own = {"player_id": self.config.player_id, "display_name": "Player", "session_epoch": 1, "presence": presence,
               "appearance": None}
        world = {"type": "world", "protocol": PROTOCOL_VERSION, "world_seq": 1, "players": [own], **WORLD_FIELDS}
        companion._apply_world(world)
        self.assertEqual(companion.snapshot.connection_flags, 1)
        self.assertGreater(companion.snapshot.roster_epoch, 0)
        companion._apply_world({**world, "world_seq": 2, "players": [{**own, "presence": {**presence, "activity": "unavailable"}}]})
        for changes in ({"x": 99, "activity": "unavailable"}, {"activity": "overworld"}):
            with self.subTest(changes=changes), self.assertRaises(ProtocolError):
                companion._apply_world({**world, "world_seq": 3, "players": [{**own, "presence": {**presence, **changes}}]})


class CompanionIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.rom, self.manifest = make_files(self.temp.name)
        build = verify_rom_manifest(self.rom, self.manifest)[0]
        self.server = WorldServer(ServerConfig(build, BASELINE_RULESET, heartbeat_interval=0.05, idle_timeout=0.5, presence_timeout=0.25, monitor_interval=0.005))
        await self.server.start(port=0)
        self.companions, self.bridges = [], []

    async def asyncTearDown(self):
        for bridge in self.bridges:
            await bridge.close()
        for companion in self.companions:
            await companion.close()
        await self.server.close()
        self.temp.cleanup()

    async def add_companion(self, index=1, **changes):
        config = CompanionConfig(
            self.rom, self.manifest, str(uuid.UUID(int=index)), f"Player {index}", secrets.token_bytes(32),
            server_port=self.server.address[1], ipc_port=0,
            pause_timeout=0.12, pose_interval=0.005, snapshot_interval=0.01,
            reconnect_delay=0.025, handshake_timeout=0.1,
            remote_timeout=0.3, send_timeout=changes.pop("send_timeout", 0.08),
            drain_timeout=changes.pop("drain_timeout", 0.08),
            **changes,
        )
        companion = Companion(config)
        await companion.start()
        self.companions.append(companion)
        await wait_until(lambda: companion.connected and bool(companion._players))
        return companion

    async def add_bridge(self, companion, token=None):
        bridge = await BinaryBridge.connect(companion, token)
        self.bridges.append(bridge)
        return bridge

    async def test_two_binary_clients_receive_actual_tcp_world_positions(self):
        first, second = await self.add_companion(1), await self.add_companion(2)
        bridge_a, bridge_b = await self.add_bridge(first), await self.add_bridge(second)
        await bridge_a.pose(make_pose(x=11, direction=4))
        await bridge_b.pose(make_pose(x=-2, avatar_gender=1, map_number=2))
        # A position off the map's grid (a step over a map edge) reaches the other game listed and hidden at the
        # grid's edge: the game refuses a whole snapshot for one such peer, which hid every player.
        a = await bridge_a.snapshot(lambda snapshot: len(snapshot.peers) == 1 and snapshot.peers[0].pose.map_number == 2)
        self.assertEqual((a.peers[0].pose.x, a.peers[0].pose.activity), (0, 0))
        b = await bridge_b.snapshot(lambda snapshot: len(snapshot.peers) == 1 and snapshot.peers[0].pose.x == 11)
        self.assertEqual((a.self_slot, b.self_slot), (0, 1))
        self.assertEqual((a.peers[0].token, b.peers[0].token), (2, 1))
        self.assertEqual(a.peers[0].pose.map_number, 2)
        self.assertEqual(b.peers[0].pose.direction, 4)
        # Independent movement and a real map transition.
        await bridge_a.pose(make_pose(frame=2, epoch=1, map_number=3, x=17))
        b = await bridge_b.snapshot(lambda snapshot: snapshot.peers and snapshot.peers[0].pose.map_number == 3)
        self.assertEqual(b.peers[0].pose.x, 17)
        self.assertEqual(b.peers[0].pose.map_epoch, 1)

    async def test_pause_hides_pose_heartbeat_keeps_session_then_resume(self):
        first, second = await self.add_companion(1), await self.add_companion(2)
        a, b = await self.add_bridge(first), await self.add_bridge(second)
        await a.pose(make_pose())
        await b.snapshot(lambda snapshot: snapshot.peers and snapshot.peers[0].pose.activity == 1)
        paused = await b.snapshot(lambda snapshot: snapshot.peers and snapshot.peers[0].pose.activity == 0)
        self.assertEqual(paused.peers[0].pose.x, 5)
        await asyncio.sleep(0.6)  # Longer than server idle timeout.
        self.assertIn(first.config.player_id, self.server.sessions)
        self.assertTrue(first.connected)
        await a.pose(make_pose(frame=2, x=8))
        resumed = await b.snapshot(lambda snapshot: snapshot.peers and snapshot.peers[0].pose.activity == 1)
        self.assertEqual(resumed.peers[0].pose.x, 8)

    async def test_repeated_and_stale_pose_does_not_extend_game_availability(self):
        first, second = await self.add_companion(1), await self.add_companion(2)
        a, b = await self.add_bridge(first), await self.add_bridge(second)
        await a.pose(make_pose(frame=10, epoch=2, x=19))
        await b.snapshot(lambda snapshot: snapshot.peers and snapshot.peers[0].pose.x == 19)
        for _ in range(10):
            await a.pose(make_pose(frame=10, epoch=2, x=99))
            await a.pose(make_pose(frame=11, epoch=1, x=98))
            await asyncio.sleep(0.015)
        snapshot = await b.snapshot(lambda value: value.peers and value.peers[0].pose.activity == 0)
        self.assertEqual(snapshot.peers[0].pose.x, 19)

    async def test_bridge_disconnect_and_rejoin_clears_stale_avatar_state(self):
        first, second = await self.add_companion(1), await self.add_companion(2)
        a, b = await self.add_bridge(first), await self.add_bridge(second)
        await a.pose(make_pose(frame=90, epoch=5, x=20))
        await b.snapshot(lambda snapshot: snapshot.peers and snapshot.peers[0].pose.x == 20)
        await a.close()
        await b.snapshot(lambda snapshot: snapshot.peers and snapshot.peers[0].pose.activity == 0)
        await wait_until(lambda: first._bridge is None)
        rejoined = await self.add_bridge(first)
        await rejoined.pose(make_pose(frame=1, epoch=0, map_number=4, x=30))
        snapshot = await b.snapshot(lambda value: value.peers and value.peers[0].pose.x == 30)
        self.assertEqual(snapshot.peers[0].pose.map_number, 4)
        self.assertEqual(snapshot.peers[0].pose.map_epoch, 1)

    async def test_remote_disconnect_reconnect_epoch_and_sequence_reset(self):
        first = await self.add_companion(1)
        bridge = await self.add_bridge(first)
        await bridge.pose(make_pose(frame=1, x=7))
        await wait_until(lambda: self.server.sessions[first.config.player_id].presence is not None)
        old_epoch = first.session_epoch
        port = self.server.address[1]
        await self.server.close()
        await bridge.snapshot(lambda snapshot: snapshot.connection_flags == 0)
        self.server = WorldServer(ServerConfig(first.config.build_id, BASELINE_RULESET, heartbeat_interval=0.05, idle_timeout=0.5))
        # Advance admission epoch so restart tests distinguish the session.
        self.server._session_epoch = old_epoch + 5
        await self.server.start(port=port)
        await wait_until(lambda: first.connected and first.session_epoch != old_epoch)
        await bridge.pose(make_pose(frame=2, x=8))
        await wait_until(lambda: self.server.sessions[first.config.player_id].presence is not None)
        presence = self.server.sessions[first.config.player_id].presence
        self.assertEqual(presence["session_epoch"], first.session_epoch)
        self.assertEqual(presence["map_epoch"], 0)
        self.assertLessEqual(presence["seq"], 2)

    async def test_bad_token_oversize_invalid_pose_and_duplicate_bridge_rejected(self):
        companion = await self.add_companion(1)
        wrong = await self.add_bridge(companion, bytes(32))
        self.assertIsNone(await asyncio.wait_for(read_packet(wrong.reader), 0.5))
        bridge = await self.add_bridge(companion)
        await bridge.snapshot()
        duplicate = await self.add_bridge(companion)
        self.assertIsNone(await asyncio.wait_for(read_packet(duplicate.reader), 0.5))
        bridge.writer.write(struct.pack("!I", 257))
        await bridge.writer.drain()
        # Previously queued S frames may precede the boundary EOF.
        while await asyncio.wait_for(read_packet(bridge.reader), 0.5) is not None:
            pass
        await wait_until(lambda: companion._bridge is None)
        invalid = await self.add_bridge(companion)
        await invalid.snapshot()
        invalid.writer.write(encode_packet(b"P" + make_pose().pack()[:-1] + b"\1"))
        await invalid.writer.drain()
        while await asyncio.wait_for(read_packet(invalid.reader), 0.5) is not None:
            pass
        self.assertTrue(companion.connected)

    async def test_binary_slow_consumer_is_bounded_and_removed(self):
        companion = await self.add_companion(1, send_timeout=0.04, drain_timeout=0.04)
        bridge = await self.add_bridge(companion)
        await bridge.snapshot()
        session = companion._bridge
        started = asyncio.Event()

        async def blocked_drain():
            started.set()
            await asyncio.Event().wait()

        session.writer.drain = blocked_drain
        await started.wait()
        await asyncio.sleep(0.015)
        self.assertIsNotNone(session.outbox.pending)
        self.assertLessEqual(len(session.outbox.pending), 93)
        await wait_until(lambda: companion._bridge is None)
        self.assertTrue(companion.connected)

    async def test_companion_shutdown_with_active_binary_client_is_bounded(self):
        companion = await self.add_companion(1)
        bridge = await self.add_bridge(companion)
        await bridge.snapshot()
        await asyncio.wait_for(companion.close(), 1)
        while await asyncio.wait_for(read_packet(bridge.reader), 0.5) is not None:
            pass
        await wait_until(lambda: companion.config.player_id not in self.server.sessions)


class BadWorldIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_malformed_server_world_disconnects_before_rom_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            rom, manifest = make_files(directory)
            bad_sent = asyncio.Event()
            closed = asyncio.Event()
            handlers = set()

            async def malicious(reader, writer):
                task = asyncio.current_task()
                handlers.add(task)
                try:
                    hello = await read_message(reader)
                    writer.write(encode_message({
                        "type": "welcome", "protocol": PROTOCOL_VERSION, "build_id": hello["build_id"],
                        "ruleset_id": BASELINE_RULESET, "player_id": hello["player_id"],
                        "session_epoch": 1, "max_players": 4, "heartbeat_interval": 5, "idle_timeout": 20,
                    }))
                    writer.write(encode_message({
                        "type": "world", "protocol": PROTOCOL_VERSION, "world_seq": 1,
                        "players": [{"player_id": hello["player_id"], "display_name": "Player", "session_epoch": 2, "presence": None,
                                     "appearance": None}], **WORLD_FIELDS,
                    }))
                    await writer.drain()
                    bad_sent.set()
                    if await reader.read() == b"":
                        closed.set()
                finally:
                    writer.close()
                    await writer.wait_closed()
                    handlers.discard(task)

            server = await asyncio.start_server(malicious, "127.0.0.1", 0)
            config = CompanionConfig(rom, manifest, str(uuid.uuid4()), "Player", secrets.token_bytes(32), server_port=server.sockets[0].getsockname()[1], ipc_port=0, reconnect_delay=1)
            companion = Companion(config)
            await companion.start()
            try:
                await asyncio.wait_for(bad_sent.wait(), 1)
                await asyncio.wait_for(closed.wait(), 1)
                await wait_until(lambda: companion.last_error == "session_epoch_mismatch")
                self.assertEqual(companion.snapshot.connection_flags, 0)
                self.assertFalse(companion.snapshot.peers)
            finally:
                await companion.close()
                server.close()
                await server.wait_closed()
                await asyncio.gather(*tuple(handlers), return_exceptions=True)


if __name__ == "__main__":
    unittest.main()
