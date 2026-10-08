"""Authenticated local diagnostic IPC, with a synthetic ROM identity/socket."""
import asyncio
from contextlib import suppress
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import secrets
import struct
import tempfile
import unittest
from uuid import uuid4
import zlib

from emerald_multiplayer.battle_mailbox import BattleBinding, BattleControl, Opcode, capability_packet, response_packet
from emerald_multiplayer.bridge_protocol import encode_packet, read_packet
from emerald_multiplayer.companion import BASELINE_RULESET, Companion, CompanionConfig, verify_rom_manifest
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.trade_storage import TradeCheckpointStore
from test_companion import BinaryBridge, make_files, make_pose, wait_until


class CompanionBattleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.rom, self.manifest = make_files(self.root)
        rom = bytearray(self.rom.read_bytes())
        rom[192:204] = b"\x01\0\0\0" * 3
        abi_version = getattr(self, "abi_version", 1)
        rom[200:204] = abi_version.to_bytes(4, "little")
        self.rom.write_bytes(rom)
        value = json.loads(self.manifest.read_text())
        value.update(rom_sha256=hashlib.sha256(rom).hexdigest(), rom_crc32=f"{zlib.crc32(rom):08x}",
                     save_abi_version=1, save_mailbox_size=512, save_mailbox_address=0x02021000,
                     ownership_abi_version=1, save_profile="rhh-1.17.1-bb1093-ownership-v1",
                     trade_abi_version=1, trade_abi_address=0x080000C4,
                     battle_abi_version=abi_version, battle_abi_address=0x080000C8,
                     battle_mailbox_address=0x02022000, battle_mailbox_size=512)
        self.manifest.write_text(json.dumps(value))
        build = verify_rom_manifest(self.rom, self.manifest)[0]
        self.store = TradeCheckpointStore(self.root / "world.sqlite3", build, BASELINE_RULESET)
        self.owner = self.store.create_player("Diagnostic player")
        self.server = WorldServer(ServerConfig(build, BASELINE_RULESET, heartbeat_interval=.05, idle_timeout=5), store=self.store)
        await self.server.start(port=0)
        self.config = CompanionConfig(self.rom, self.manifest, self.owner.player_id, self.owner.display_name,
            secrets.token_bytes(32), server_port=self.server.address[1], ipc_port=0,
            server_credential=self.owner.credential, development_battle_channel=True)
        self.c = Companion(self.config)
        await self.c.start()
        await wait_until(lambda: self.c.connected, 5)
        self.bridge = await BinaryBridge.connect(self.c)
        self.bridge.writer.write(encode_packet(capability_packet(abi_version)))
        await self.bridge.writer.drain()
        await wait_until(lambda: self.c._bridge is not None and self.c._bridge.battle_capable)
        self.tasks = []

    async def asyncTearDown(self):
        for task in self.tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        with suppress(ConnectionError, OSError):
            await self.bridge.close()
        await self.c.close()
        await self.server.close()
        self.store.close()
        self.temp.cleanup()

    def query(self, **changes):
        return BattleControl(**dict(incarnation=self.c.battle_incarnation,
            session_epoch=self.c.session_epoch, battle_id=str(uuid4()), sequence=1, opcode=Opcode.QUERY, **changes))

    def task(self, command, **kwargs):
        task = asyncio.create_task(self.c.battle_rpc(command, **kwargs))
        self.tasks.append(task)
        return task

    async def next_command(self):
        async with asyncio.timeout(3):
            while True:
                packet = await read_packet(self.bridge.reader)
                if packet[:1] == b"D":
                    return BattleControl.unpack(packet[1:]).validate_command()
                self.assertEqual(packet[:1], b"S")

    async def reply(self, response):
        self.bridge.writer.write(encode_packet(response_packet(response)))
        await self.bridge.writer.drain()

    async def test_correlated_query_with_ongoing_heartbeat_and_pose(self):
        command = self.query()
        task = self.task(command)
        self.assertEqual(await self.next_command(), command)
        await self.bridge.pose(make_pose(frame=1))
        await asyncio.sleep(.15)
        self.assertTrue(self.c.connected)
        response = replace(command, data=bytes(64))
        await self.reply(response)
        self.assertEqual(await task, response)
        self.assertEqual(self.c._battle_pending, {})
        self.assertEqual(self.c._save_pending, {})

    async def test_default_disabled_and_authentication_capability_required(self):
        disabled = Companion(replace(self.config, development_battle_channel=False))
        with self.assertRaises(ValueError):
            await disabled.battle_rpc(self.query())
        for changes in ({"development_battle_channel": 1}, {"server_credential": None}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(self.config, **changes)

    async def test_one_pending_stale_lease_and_incarnation_are_refused(self):
        command = self.query()
        for changed in (replace(command, session_epoch=command.session_epoch+1),
                        replace(command, incarnation=command.incarnation+1)):
            with self.assertRaises(ConnectionError):
                await self.c.battle_rpc(changed)
        task = self.task(command)
        await self.next_command()
        with self.assertRaises(ValueError):
            await self.c.battle_rpc(replace(command, sequence=2))
        await self.reply(replace(command, data=bytes(64)))
        await task

    async def test_bind_must_name_this_authenticated_local_player(self):
        command = self.query()
        roster = BattleBinding(str(uuid4()), (str(uuid4()), str(uuid4())),
                               (command.session_epoch, command.session_epoch+1), (command.incarnation, 2), 0)
        with self.assertRaises(ValueError):
            await self.c.battle_rpc(replace(command, opcode=Opcode.BIND, data=roster.pack()))
        self.assertFalse(self.c._battle_pending)

    async def test_uncertain_timeout_then_readonly_query_and_late_reply(self):
        first = self.query()
        task = self.task(first, timeout=.05)
        await self.next_command()
        with self.assertRaises(asyncio.TimeoutError):
            await task
        second = replace(first, sequence=2)
        next_task = self.task(second)
        self.assertEqual(await self.next_command(), second)
        await self.reply(replace(first, data=bytes(64)))
        await self.reply(replace(second, data=bytes(64)))
        self.assertEqual((await next_task).sequence, 2)

    async def test_wrong_correlation_closes_bridge_and_fails_request(self):
        command = self.query()
        task = self.task(command)
        await self.next_command()
        await self.reply(replace(command, battle_id=str(uuid4()), data=bytes(64)))
        with self.assertRaises(ConnectionError):
            await task
        await wait_until(lambda: self.c._bridge is None)

    async def test_disconnect_fails_pending_without_changing_command_to_close(self):
        command = self.query()
        task = self.task(command)
        await self.next_command()
        self.server.sessions[self.owner.player_id].close("test loss")
        with self.assertRaises(ConnectionError):
            await task
        self.assertFalse(self.c._battle_pending)

    async def test_trade_intent_and_live_save_owner_block_mutators_but_not_query(self):
        command = self.query()
        pending = self.root / "pending-trade.json"
        pending.write_text("durable intent is owned by another coordinator")
        self.c._live_trade_pending_path = pending
        for op, data in ((Opcode.EMIT_DIAGNOSTIC, struct.pack("<I", 9)), (Opcode.CLOSE, b"")):
            with self.assertRaises(ValueError):
                await self.c.battle_rpc(replace(command, opcode=op, data=data))
        task = self.task(command)
        await self.next_command()
        await self.reply(replace(command, data=bytes(64)))
        await task
        pending.unlink()
        self.c._live_save_owner = object()
        try:
            with self.assertRaises(ValueError):
                await self.c.battle_rpc(replace(command, opcode=Opcode.CLOSE))
        finally:
            self.c._live_save_owner = None
