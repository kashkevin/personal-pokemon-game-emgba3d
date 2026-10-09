"""Compatibility and actual loopback transport for optional running poses."""
import asyncio
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
from emerald_multiplayer.companion import Companion, CompanionConfig, verify_rom_manifest
from emerald_multiplayer.mailbox import MailboxError, Peer, Pose, Snapshot
from emerald_multiplayer.server import ServerConfig, WorldServer
from test_companion import make_files, make_pose, wait_until


def animation_files(directory):
    rom, manifest = make_files(directory)
    raw = bytearray(rom.read_bytes())
    struct.pack_into("<I", raw, 128, 1)
    rom.write_bytes(raw)
    value = json.loads(manifest.read_text())
    value.update(rom_sha256=hashlib.sha256(raw).hexdigest(), rom_crc32=f"{zlib.crc32(raw):08x}",
                 presence_animation_abi_version=1, presence_animation_abi_address=0x08000080)
    manifest.write_text(json.dumps(value))
    return rom, manifest


class RunningCodecTests(unittest.TestCase):
    def test_running_requires_verified_extension_and_preserves_old_wire_shape(self):
        runner = make_pose(movement_mode=5, presentation_version=1)
        self.assertEqual(len(runner.pack()), 20)
        self.assertEqual(runner.pack()[-1], 0)
        with self.assertRaises(MailboxError):
            Pose.unpack(runner.pack())
        self.assertEqual(Pose.unpack(runner.pack(), presentation_version=1), runner)
        network = dict(runner.network_fields(True), map_epoch=1, seq=2)
        self.assertEqual(network["movement_mode"], "run")
        self.assertEqual(Pose.from_presence(network).movement_mode, 0)
        self.assertEqual(Pose.from_presence(network, presentation_version=1).movement_mode, 5)
        packet = Snapshot(1, 2, 3, 0, (Peer(1, runner),)).pack()
        self.assertEqual(len(packet), 88)
        with self.assertRaises(MailboxError):
            Snapshot.unpack(packet)
        self.assertEqual(Snapshot.unpack(packet, presentation_version=1).peers[0].pose, runner)

    def test_manifest_marker_cannot_be_invented_or_partially_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            rom, manifest = animation_files(directory)
            verify_rom_manifest(rom, manifest)
            original = json.loads(manifest.read_text())
            for mutation in ({"presence_animation_abi_version": True}, {"presence_animation_abi_version": 2},
                             {"presence_animation_abi_address": 0x08000081},
                             {"presence_animation_abi_address": 0x08000084}):
                manifest.write_text(json.dumps({**original, **mutation}))
                with self.assertRaises(ValueError):
                    verify_rom_manifest(rom, manifest)
            del original["presence_animation_abi_address"]
            manifest.write_text(json.dumps(original))
            with self.assertRaises(ValueError):
                verify_rom_manifest(rom, manifest)


class RunningTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_companions_keep_run_then_walk_across_actual_server_and_binary_bridges(self):
        with tempfile.TemporaryDirectory() as directory:
            rom, manifest = animation_files(directory)
            build, _ = verify_rom_manifest(rom, manifest)
            from emerald_multiplayer.companion import BASELINE_RULESET
            server = WorldServer(ServerConfig(build, BASELINE_RULESET))
            companions, bridges = [], []
            await server.start(port=0)
            try:
                for name in ("Runner", "Observer"):
                    config = CompanionConfig(rom, manifest, str(uuid.uuid4()), name, secrets.token_bytes(32),
                        server_port=server.address[1], ipc_port=0, pose_interval=.01, snapshot_interval=.01)
                    companion = Companion(config)
                    companions.append(companion)
                    await companion.start()
                    await wait_until(lambda: companion.connected)
                    reader, writer = await asyncio.open_connection(*companion.ipc_address)
                    bridges.append((reader, writer))
                    writer.write(encode_packet(b"H" + config.token))
                    await writer.drain()
                async def send(mode, frame):
                    bridges[0][1].write(encode_packet(b"P" + make_pose(frame=frame, movement_mode=mode,
                                                                     presentation_version=1).pack()))
                    await bridges[0][1].drain()
                async def observe(mode):
                    async with asyncio.timeout(3):
                        while True:
                            packet = await read_packet(bridges[1][0])
                            if packet is None:
                                self.fail("observer bridge closed")
                            if packet[:1] == b"S":
                                snapshot = Snapshot.unpack(packet[1:], presentation_version=1)
                                if any(p.pose.activity == 1 and p.pose.movement_mode == mode for p in snapshot.peers):
                                    return
                await send(5, 1)
                await observe(5)
                await send(0, 2)
                await observe(0)
            finally:
                for _, writer in bridges:
                    writer.close()
                    await writer.wait_closed()
                for companion in companions:
                    await companion.close()
                await server.close()
