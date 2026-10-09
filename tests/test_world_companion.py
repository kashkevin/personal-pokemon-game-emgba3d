"""Companion shared-world path: host world frames -> EMW1 inbound records, and
ROM local records/actions -> host requests. Real TCP host, binary fake bridge."""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import secrets
import struct
import tempfile
import unittest
import zlib

from emerald_multiplayer.bridge_protocol import encode_packet, read_packet
from emerald_multiplayer.companion import BASELINE_RULESET, Companion, CompanionConfig, verify_rom_manifest
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.world_mailbox import (
    ACTION_APPEARANCE, ACTION_COOP_GYM, ACTION_WALLET, WALLET_OFFSET, WorldAction, WorldState,
)
from test_companion import make_pose, wait_until

LOOK = bytes((1, 2, 3, 4, 5, 6, 7, 0))


def make_world_files(directory):
    data = bytearray(b"synthetic shared-world protocol fixture" * 32)
    struct.pack_into("<I", data, 0x100, 1)  # EMW1 capability marker
    data = bytes(data)
    rom = Path(directory) / "fixture.gba"
    manifest = Path(directory) / "manifest.json"
    rom.write_bytes(data)
    manifest.write_text(json.dumps({
        "rom_sha256": hashlib.sha256(data).hexdigest(), "abi_version": 1,
        "mailbox_size": 128, "ruleset_id": BASELINE_RULESET,
        "rom_size": len(data), "rom_crc32": f"{zlib.crc32(data):08x}",
        "mailbox_address": 0x02020000, "world_abi_version": 1, "world_abi_address": 0x08000100,
        "world_mailbox_address": 0x02030000, "world_mailbox_size": 256,
    }), encoding="utf-8")
    return rom, manifest


def local_record(state: WorldState, action: WorldAction = WorldAction()) -> bytes:
    raw = struct.pack("<HBBHBB8s", state.follower_species, state.follower_flags, state.mount_state,
                      state.mount_species, state.mount_flags, state.wallet_seq, state.appearance)
    return b"G" + raw + action.pack()


class Bridge:
    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer
        self.inbound = None

    @classmethod
    async def connect(cls, companion):
        reader, writer = await asyncio.open_connection(*companion.ipc_address)
        writer.write(encode_packet(b"H" + companion.config.token))
        await writer.drain()
        return cls(reader, writer)

    async def send(self, packet):
        self.writer.write(encode_packet(packet))
        await self.writer.drain()

    async def world(self, predicate=lambda data: True, timeout=3):
        async with asyncio.timeout(timeout):
            while True:
                packet = await read_packet(self.reader)
                if packet is None:
                    raise ConnectionError("bridge closed")
                if packet[:1] == b"N":
                    self.assertLength(packet)
                    self.inbound = packet[1:]
                    if predicate(self.inbound):
                        return self.inbound

    @staticmethod
    def assertLength(packet):
        if len(packet) != 209:
            raise AssertionError("world inbound must be 208 bytes")

    async def close(self):
        self.writer.close()
        await self.writer.wait_closed()


def flags(data):
    return struct.unpack_from("<I", data, 0)[0]


def seconds(data):
    return struct.unpack_from("<I", data, 4)[0]


def ack(data):
    return struct.unpack_from("<I", data, 8)[0]


def peers(data):
    result = {}
    for slot in range(3):
        token, species, fflags = struct.unpack_from("<IHB", data, 20 + slot * 20)
        if token:
            result[token] = (species, fflags, data[20 + slot * 20 + 12:20 + slot * 20 + 20])
    return result


def wallet(data):
    return struct.unpack_from("<IiI", data, WALLET_OFFSET)


class WorldCompanionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.rom, self.manifest = make_world_files(self.temp.name)
        build = verify_rom_manifest(self.rom, self.manifest)[0]
        self.server = WorldServer(ServerConfig(build, BASELINE_RULESET, heartbeat_interval=0.05,
                                               idle_timeout=2, monitor_interval=0.005))
        await self.server.start(port=0)
        self.companions, self.bridges = [], []
        for name in ("Alice", "Bob"):
            config = CompanionConfig(self.rom, self.manifest, str(__import__("uuid").uuid4()), name,
                                     secrets.token_bytes(32), server_port=self.server.address[1], ipc_port=0,
                                     pose_interval=0.005, snapshot_interval=0.01, reconnect_delay=0.02)
            self.assertTrue(config.world_enabled)
            companion = Companion(config)
            await companion.start()
            await wait_until(lambda: companion.connected)
            self.companions.append(companion)
            self.bridges.append(await Bridge.connect(companion))

    async def asyncTearDown(self):
        for bridge in self.bridges:
            try:
                await bridge.close()
            except (ConnectionError, OSError):
                pass
        for companion in self.companions:
            await companion.close()
        await self.server.close()
        self.temp.cleanup()

    async def present(self, index, x, state=WorldState()):
        await self.bridges[index].send(local_record(state))
        await self.bridges[index].send(b"P" + make_pose(frame=x, x=x).pack())
        player = self.companions[index].config.player_id
        await wait_until(lambda: (self.server.sessions[player].presence or {}).get("x") == x, timeout=3)

    async def test_clock_peers_followers_and_teammate_free_inbound(self):
        await self.present(0, 5, WorldState(25, 4, 0, 0, 0, bytes(8), 0))
        await self.present(1, 6, WorldState(6, 5, 1, 254, 1, bytes(8), 9))
        data = await self.bridges[0].world(lambda d: len(peers(d)) == 1 and peers(d)[next(iter(peers(d)))][0] == 6)
        self.assertEqual(flags(data) & 1, 1)  # host clock valid
        self.assertGreaterEqual(seconds(data), 8 * 3600)
        (token, (species, fflags, _)), = peers(data).items()
        self.assertEqual((species, fflags), (6, 5))
        # The peer record carries Bob's mount but never his wallet sequence.
        record = data[20:40] if struct.unpack_from("<I", data, 20)[0] == token else data[40:60]
        self.assertEqual(struct.unpack_from("<BHB", record, 7), (1, 254, 1))
        self.assertEqual(record[11], 0)
        self.assertEqual(wallet(data), (0, 0, 0))
        # Alice's own follower reached the host presence.
        alice = self.server.sessions[self.companions[0].config.player_id].presence
        self.assertEqual((alice["follower_species"], alice["follower_flags"], alice["wallet_seq"]), (25, 4, 0))

    async def test_appearance_action_saves_the_look_and_acknowledges(self):
        await self.present(0, 5)
        await self.bridges[0].send(local_record(WorldState(appearance=LOOK), WorldAction(3, ACTION_APPEARANCE)))
        player = self.companions[0].config.player_id
        await wait_until(lambda: self.server.shared_world.appearance(player) == LOOK.hex(), timeout=3)
        data = await self.bridges[0].world(lambda d: ack(d) == 3 and d[12:20] == LOOK)
        self.assertEqual(data[12:20], LOOK)
        await self.present(1, 6)
        other = await self.bridges[1].world(lambda d: any(look == LOOK for _, _, look in peers(d).values()))
        self.assertTrue(other)

    async def test_wallet_receipt_reports_the_exact_amount_and_acknowledges(self):
        await self.present(0, 5)
        received = []
        self.server.wagers.applied = lambda player, seq, amount: received.append((player, seq, amount)) or []
        await self.bridges[0].send(local_record(WorldState(wallet_seq=4), WorldAction(8, ACTION_WALLET, 2, 0, 4, 1234)))
        await self.bridges[0].world(lambda d: ack(d) == 8)
        self.assertEqual(received, [(self.companions[0].config.player_id, 4, 1234)])

    async def test_coop_gym_request_reaches_the_host_and_refusal_still_acknowledges(self):
        await self.present(0, 5)
        await self.bridges[0].send(local_record(WorldState(), WorldAction(2, ACTION_COOP_GYM, 0, 0, 1)))
        data = await self.bridges[0].world(lambda d: ack(d) == 2)
        notice = data[116:180].rstrip(b"\0").decode()
        self.assertIn("TEAM GYM CHALLENGE", notice)  # battles are off on this host

    async def test_repeated_action_sequence_is_sent_once(self):
        await self.present(0, 5)
        calls = []
        self.server.wagers.applied = lambda *args: calls.append(args) or []
        record = local_record(WorldState(wallet_seq=1), WorldAction(5, ACTION_WALLET, 0, 0, 1, 0))
        for _ in range(4):
            await self.bridges[0].send(record)
        await self.bridges[0].world(lambda d: ack(d) == 5)
        await asyncio.sleep(0.1)
        self.assertEqual(len(calls), 1)

    async def test_malformed_local_record_disconnects_the_bridge(self):
        await self.bridges[0].send(b"G" + bytes(31))
        with self.assertRaises(ConnectionError):
            for _ in range(50):
                await self.bridges[0].world(timeout=1)


if __name__ == "__main__":
    unittest.main()
