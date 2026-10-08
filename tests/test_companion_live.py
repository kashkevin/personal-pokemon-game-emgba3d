from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import secrets
import tempfile
import unittest
import uuid
import zlib

from emerald_multiplayer.bridge_protocol import encode_packet, read_packet
from emerald_multiplayer.companion import BASELINE_RULESET, Companion, CompanionConfig, TradeError, verify_rom_manifest
from emerald_multiplayer.checkpoint_client import CheckpointError
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE
from emerald_multiplayer.flash import LAYOUT_ID
from emerald_multiplayer.save_mailbox import (
    FLASH_SIZE, Opcode, SaveControl, capability_packet, parse_command_packet, response_packet,
)
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.storage import CheckpointStore
from emerald_multiplayer.trade_storage import TradeCheckpointStore
from test_companion import BinaryBridge, make_files, make_pose, wait_until


class CompanionLiveTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.rom, self.manifest = make_files(self.temp.name)
        value = json.loads(self.manifest.read_text())
        value.update(save_abi_version=1, save_mailbox_size=512, save_mailbox_address=0x02021000)
        self.manifest.write_text(json.dumps(value))
        build = verify_rom_manifest(self.rom, self.manifest)[0]
        self.store = CheckpointStore(Path(self.temp.name) / "world.sqlite3", build, BASELINE_RULESET, LAYOUT_ID)
        self.owner = self.store.create_player("Authenticated player")
        self.server = WorldServer(ServerConfig(build, BASELINE_RULESET, heartbeat_interval=0.03,
                                               idle_timeout=0.3, monitor_interval=0.005), store=self.store)
        await self.server.start(port=0)
        self.companion = Companion(CompanionConfig(self.rom, self.manifest, self.owner.player_id,
                                                   self.owner.display_name, secrets.token_bytes(32),
                                                   server_port=self.server.address[1], ipc_port=0,
                                                   server_credential=self.owner.credential,
                                                   pose_interval=0.005, snapshot_interval=0.01,
                                                   reconnect_delay=0.02))
        await self.companion.start()
        await wait_until(lambda: self.companion.connected)
        self.bridge = await BinaryBridge.connect(self.companion)
        self.bridge.writer.write(encode_packet(capability_packet()))
        await self.bridge.writer.drain()
        await wait_until(lambda: self.companion._bridge is not None and self.companion._bridge.save_capable)
        self.pending_tasks = []

    async def asyncTearDown(self):
        for task in self.pending_tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.pending_tasks, return_exceptions=True)
        with suppress(ConnectionError, OSError):
            await self.bridge.close()
        await self.companion.close()
        await self.server.close()
        self.store.close()
        self.temp.cleanup()

    def control(self, **changes):
        fields = dict(incarnation=self.companion.save_incarnation, session_epoch=self.companion.session_epoch,
                      request_id=str(uuid.uuid4()), sequence=1, offset=0, total_size=FLASH_SIZE,
                      revision=0, opcode=Opcode.BIND)
        return SaveControl(**{**fields, **changes})

    async def next_command(self):
        async with asyncio.timeout(1):
            while True:
                packet = await read_packet(self.bridge.reader)
                self.assertIsNotNone(packet)
                if packet[:1] == b"C":
                    return parse_command_packet(packet)
                self.assertEqual(packet[:1], b"S")

    async def respond(self, control):
        self.bridge.writer.write(encode_packet(response_packet(control)))
        await self.bridge.writer.drain()

    def rpc_task(self, control, **kwargs):
        task = asyncio.create_task(self.companion.save_rpc(control, **kwargs))
        self.pending_tasks.append(task)
        return task

    async def test_authenticated_capability_control_response_and_continuing_pose_heartbeat(self):
        self.assertEqual(self.companion.world_id, self.store.metadata.world_id)
        self.assertEqual(self.companion.save_profile, LAYOUT_ID)
        await self.bridge.pose(make_pose(frame=1, x=6))
        control = self.control()
        task = self.rpc_task(control)
        self.assertEqual(await self.next_command(), control)
        # Hold a mailbox response while the existing world reader answers pings.
        await asyncio.sleep(0.08)
        await self.bridge.pose(make_pose(frame=2, x=7))
        await wait_until(lambda: self.server.sessions[self.owner.player_id].presence is not None
                         and self.server.sessions[self.owner.player_id].presence["x"] == 7)
        self.assertGreater(self.server.sessions[self.owner.player_id].ping_nonce, 0)
        self.assertFalse(task.done())
        await self.respond(control)
        self.assertEqual(await task, control)
        self.assertTrue(self.companion.connected)
        self.assertEqual(self.companion.session_epoch, control.session_epoch)

    async def test_legacy_build_cannot_issue_trade_hold_commands(self):
        self.assertFalse(self.companion.config.trade_enabled)
        with self.assertRaisesRegex(ValueError, "no trade hold capability"):
            await self.companion.save_rpc(self.control(opcode=Opcode.BEGIN_TRADE_EXPORT, revision=1))
        self.assertEqual(self.companion._save_pending, {})
        self.assertTrue(self.companion.connected)

    async def test_mismatched_reply_disconnects_ipc_and_fails_pending_without_closing_world(self):
        control = self.control()
        task = self.rpc_task(control)
        await self.next_command()
        await self.respond(replace(control, request_id=str(uuid.uuid4())))
        with self.assertRaises(ConnectionError):
            await task
        await wait_until(lambda: self.companion._bridge is None)
        self.assertTrue(self.companion.connected)
        self.assertIn(self.owner.player_id, self.server.sessions)

    async def test_bridge_disconnect_fails_pending_and_late_timed_out_reply_is_ignored(self):
        control = self.control()
        task = self.rpc_task(control, timeout=0.025)
        await self.next_command()
        with self.assertRaises(asyncio.TimeoutError):
            await task
        await self.respond(control)
        await asyncio.sleep(0.02)
        self.assertIsNotNone(self.companion._bridge)
        query = replace(control, opcode=Opcode.QUERY, sequence=2)
        pending = self.rpc_task(query)
        self.assertEqual(await self.next_command(), query)
        await self.bridge.close()
        with self.assertRaises(ConnectionError):
            await pending
        self.assertTrue(self.companion.connected)

    async def test_invalid_command_shape_rejected_before_mailbox_enqueue(self):
        bad = self.control(opcode=Opcode.READ, data=bytes(128))
        with self.assertRaises(ValueError):
            await self.companion.save_rpc(bad)
        self.assertFalse(self.companion._save_pending)
        self.assertTrue(self.companion.connected)

    async def test_runtime_ipc_reconnect_reincarnates_without_changing_world_lease(self):
        old_control = self.control()
        world, epoch = self.companion.world_id, self.companion.session_epoch
        task = self.rpc_task(old_control)
        await self.next_command()
        await self.bridge.close()
        with self.assertRaises(ConnectionError):
            await task
        await wait_until(lambda: self.companion._bridge is None)
        self.bridge = await BinaryBridge.connect(self.companion)
        self.bridge.writer.write(encode_packet(capability_packet()))
        await self.bridge.writer.drain()
        await wait_until(lambda: self.companion._bridge is not None and self.companion._bridge.save_capable)
        self.assertEqual((self.companion.world_id, self.companion.session_epoch), (world, epoch))
        self.assertGreater(self.companion.save_incarnation, old_control.incarnation)
        with self.assertRaises(ConnectionError):
            await self.companion.save_rpc(old_control)
        new_control = self.control()
        pending = self.rpc_task(new_control)
        self.assertEqual(await self.next_command(), new_control)
        await self.respond(new_control)
        self.assertEqual(await pending, new_control)
        self.assertTrue(self.companion.connected)


class CompanionTradeGuardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        rom, manifest = make_files(self.temp.name)
        data = b"\x01\0\0\0" + rom.read_bytes()[4:]
        rom.write_bytes(data)
        value = json.loads(manifest.read_text())
        value.update(rom_sha256=hashlib.sha256(data).hexdigest(), rom_crc32=f"{zlib.crc32(data):08x}",
            save_abi_version=1, save_mailbox_size=512, save_mailbox_address=0x02021000,
            ownership_abi_version=1, save_profile=OWNERSHIP_PROFILE,
            trade_abi_version=1, trade_abi_address=0x08000000)
        manifest.write_text(json.dumps(value))
        self.store = TradeCheckpointStore(Path(self.temp.name)/"guard.sqlite3", value["rom_sha256"], BASELINE_RULESET)
        owner = self.store.create_player("Guard actor")
        self.server = WorldServer(ServerConfig(value["rom_sha256"], BASELINE_RULESET,
            heartbeat_interval=0.05, idle_timeout=10), store=self.store, development_trades=True)
        await self.server.start(port=0)
        self.companion = Companion(CompanionConfig(rom, manifest, owner.player_id, owner.display_name,
            secrets.token_bytes(32), server_port=self.server.address[1], ipc_port=0,
            server_credential=owner.credential, reconnect_delay=0.05))
        await self.companion.start()
        await wait_until(lambda: self.companion.connected)
        self.bridge = await BinaryBridge.connect(self.companion)
        self.bridge.writer.write(encode_packet(capability_packet())); await self.bridge.writer.drain()
        await wait_until(lambda: self.companion._bridge is not None and self.companion._bridge.save_capable)
        self.pending = Path(self.temp.name)/"pending-trade.json"
        self.pending.write_text("{}")  # Existence fences; coordinator validates contents.
        self.companion._live_trade_pending_path = self.pending

    async def asyncTearDown(self):
        await self.bridge.close(); await self.companion.close(); await self.server.close()
        self.store.close(); self.temp.cleanup()

    def control(self, opcode=Opcode.BIND, **changes):
        values = dict(incarnation=self.companion.save_incarnation, session_epoch=self.companion.session_epoch,
            request_id=str(uuid.uuid4()), sequence=1, offset=0, total_size=FLASH_SIZE, revision=0, opcode=opcode)
        return SaveControl(**{**values, **changes})

    async def echo(self, command, data=b""):
        while True:
            packet = await read_packet(self.bridge.reader)
            if packet[:1] == b"C":
                self.assertEqual(parse_command_packet(packet), command)
                self.bridge.writer.write(encode_packet(response_packet(replace(command, data=data))))
                await self.bridge.writer.drain()
                return
            self.assertEqual(packet[:1], b"S")

    async def test_journal_fences_raw_checkpoint_trade_and_all_mutating_mailbox_calls(self):
        for operation in ("begin", "chunk", "commit", "abort", "ownership_grant"):
            with self.subTest(operation=operation), self.assertRaisesRegex(ValueError, "pending trade recovery"):
                await self.companion.checkpoint_rpc(operation)
        for operation in ("open", "offer", "confirm", "cancel", "ack"):
            with self.subTest(operation=operation), self.assertRaisesRegex(ValueError, "pending trade recovery"):
                await self.companion.trade_rpc(operation)
        sizes = {Opcode.BEGIN_IMPORT: bytes(16), Opcode.WRITE: bytes(128), Opcode.GRANT_OWNERSHIP: bytes(60)}
        readonly = {Opcode.QUERY, Opcode.QUERY_OWNERSHIP, Opcode.QUERY_TRADE}
        for opcode in set(Opcode)-readonly:
            command = self.control(opcode, revision=1 if opcode == Opcode.BEGIN_TRADE_EXPORT else 0,
                data=sizes.get(opcode, b""))
            with self.subTest(opcode=opcode), self.assertRaisesRegex(ValueError, "pending trade recovery"):
                await self.companion.save_rpc(command)
        self.assertEqual(self.companion._save_pending, {})
        self.assertEqual(self.companion._checkpoint_pending, {})
        self.assertEqual(self.companion._trade_pending, {})
        self.assertTrue(self.companion.connected)

    async def test_readonly_rpc_and_mailbox_work_and_exact_current_owner_can_mutate(self):
        self.assertIsNone((await self.companion.checkpoint_rpc("info"))["checkpoint"])
        self.assertEqual((await self.companion.trade_rpc("pending"))["recoveries"], [])
        self.assertEqual((await self.companion.trade_rpc("status", transaction_id=str(uuid.uuid4())))["trade"]["state"], "aborted")
        query = self.control(Opcode.QUERY)
        echo = asyncio.create_task(self.echo(query, bytes(48)))
        try:
            self.assertEqual((await self.companion.save_rpc(query)).data, bytes(48))
            await echo
        finally:
            if not echo.done():
                echo.cancel(); await asyncio.gather(echo, return_exceptions=True)
        self.companion._live_save_owner = asyncio.current_task()
        try:
            with self.assertRaises(CheckpointError) as caught:
                await self.companion.checkpoint_rpc("ownership_grant", expected_revision=0,
                    incarnation=self.companion.save_incarnation, count=32)
            self.assertEqual(caught.exception.code, "enrollment_required")
            with self.assertRaises(TradeError) as caught:
                await self.companion.trade_rpc("open", transaction_id=str(uuid.uuid4()), peer=str(uuid.uuid4()))
            self.assertIn(caught.exception.code, {"player_offline", "checkpoint_required"})
            bind = self.control()
            echo = asyncio.create_task(self.echo(bind))
            try:
                self.assertEqual(await self.companion.save_rpc(bind), bind)
                await echo
            finally:
                if not echo.done():
                    echo.cancel(); await asyncio.gather(echo, return_exceptions=True)
        finally:
            self.companion._live_save_owner = None


    async def test_startup_gate_rejects_new_and_already_waiting_bridge_hellos(self):
        await self.bridge.close()
        await wait_until(lambda: self.companion._bridge is None)
        await wait_until(lambda: self.companion.connected)
        lease = self.companion.session_epoch
        incarnation = self.companion._bridge_incarnation
        reader, writer = await asyncio.open_connection(*self.companion.ipc_address)
        await wait_until(lambda: writer is not None and bool(self.companion._ipc_writers))
        # This socket was admitted to the hello reader before recovery began.
        self.companion._bridge_admission_blocked = True
        writer.write(encode_packet(b"H" + self.companion.config.token))
        await writer.drain()
        self.assertIsNone(await asyncio.wait_for(read_packet(reader), 2))
        writer.close()
        await writer.wait_closed()
        reader2, writer2 = await asyncio.open_connection(*self.companion.ipc_address)
        self.assertIsNone(await asyncio.wait_for(read_packet(reader2), 2))
        writer2.close()
        await writer2.wait_closed()
        self.assertIsNone(self.companion._bridge)
        self.assertEqual(self.companion._bridge_incarnation, incarnation)
        self.assertTrue(self.companion.connected)
        self.assertEqual(self.companion.session_epoch, lease)
        self.companion._bridge_admission_blocked = False
        self.bridge = await BinaryBridge.connect(self.companion)
        await wait_until(lambda: self.companion._bridge is not None)
        self.assertEqual(self.companion._bridge_incarnation, incarnation + 1)


if __name__ == "__main__":
    unittest.main()
