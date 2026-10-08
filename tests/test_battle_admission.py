"""Real loopback Companion/socket fences for unresolved development battle intent."""
import asyncio
from dataclasses import replace
from pathlib import Path
import struct
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4

from emerald_multiplayer.battle_journal import BattleJournal, read_battle_intent
from emerald_multiplayer.battle_mailbox import response_packet as battle_response
from emerald_multiplayer.battle_roster import CanonicalBattler
from emerald_multiplayer.checkpoint_client import CheckpointClient
from emerald_multiplayer.bridge_protocol import encode_packet, read_packet
from emerald_multiplayer.flash import FLASH_SIZE
from emerald_multiplayer.native_battle import NativeBinding, NativeControl, Opcode as NativeOpcode
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE
from emerald_multiplayer.save_mailbox import (SaveControl, Opcode as SaveOpcode,
    capability_packet, response_packet as save_response)
from test_companion import wait_until, make_pose
from test_ownership_storage import source_flash, owned_flash
import test_companion_battle as ipc_fixture


class CompanionBattleAdmissionTests(unittest.IsolatedAsyncioTestCase):
    abi_version = 2
    asyncTearDown = ipc_fixture.CompanionBattleTests.asyncTearDown

    async def asyncSetUp(self):
        await ipc_fixture.CompanionBattleTests.asyncSetUp(self)
        self.bridge.writer.write(encode_packet(capability_packet()))
        await self.bridge.writer.drain()
        await wait_until(lambda:self.c._bridge.save_capable)
        self.directory = self.root/"private"
        self.journal = BattleJournal(self.c,self.directory)
        actor = self.c.config.player_id
        self.store.enroll_player(actor,source_flash(("party:0",),personalities=(7,)))
        grant = self.store.reserve_instances(actor,self.c.session_epoch,str(uuid4()),0,self.c.save_incarnation,32)
        checkpoint = self.store.commit_checkpoint(actor,self.c.session_epoch,str(uuid4()),0,
            owned_flash(grant,(("party:0",grant.start),),personalities=(7,)),
            self.store.build_id,self.store.ruleset_id,OWNERSHIP_PROFILE)
        peer = str(uuid4());players = tuple(sorted((actor,peer)));local = players.index(actor)
        leases = tuple(self.c.session_epoch if p == actor else self.c.session_epoch+1 for p in players)
        incs = tuple(self.c.battle_incarnation if p == actor else self.c.battle_incarnation+1 for p in players)
        self.binding = NativeBinding(str(uuid4()),players,leases,incs,local)
        self.canonical = CanonicalBattler.from_checkpoint(checkpoint,world_id=self.c.world_id,
            build_id=self.c.config.build_id,ruleset_id=self.c.config.ruleset_id,source_slot=local)
        self.bind = NativeControl(self.c.battle_incarnation,self.c.session_epoch,str(uuid4()),1,
            NativeOpcode.BIND,source_slot=local,data=self.binding.pack())

    async def echo(self,command,data):
        prefix = b"D" if isinstance(command,NativeControl) else b"C"
        codec = NativeControl if prefix == b"D" else SaveControl
        async with asyncio.timeout(3):
            while True:
                packet = await read_packet(self.bridge.reader)
                if packet[:1] == prefix:
                    self.assertEqual(codec.unpack(packet[1:]),command)
                    response = replace(command,data=data)
                    packet = battle_response(response) if prefix == b"D" else save_response(response)
                    self.bridge.writer.write(encode_packet(packet));await self.bridge.writer.drain()
                    return
                self.assertEqual(packet[:1],b"S")

    async def roundtrip(self,command,data):
        echo = asyncio.create_task(self.echo(command,data))
        self.tasks.append(echo)
        result = await (self.c.battle_rpc(command) if isinstance(command,NativeControl) else self.c.save_rpc(command))
        await echo
        self.assertEqual(result,replace(command,data=data))

    def save_command(self,opcode=SaveOpcode.BIND,**changes):
        return SaveControl(**dict(incarnation=self.c.save_incarnation,session_epoch=self.c.session_epoch,
            request_id=str(uuid4()),sequence=1,offset=0,total_size=FLASH_SIZE,revision=0,opcode=opcode,**changes))

    def malformed_intent(self):self.journal.path.write_bytes(b"{}")

    async def test_malformed_intent_fences_all_save_trade_checkpoint_and_native_mutators(self):
        self.malformed_intent()
        for operation in ("begin","chunk","commit","abort","ownership_grant"):
            with self.subTest(operation=operation),self.assertRaisesRegex(ValueError,"pending battle"):
                await self.c.checkpoint_rpc(operation)
        for operation in ("open","offer","confirm","cancel","ack"):
            with self.subTest(operation=operation),self.assertRaisesRegex(ValueError,"pending battle"):
                await self.c.trade_rpc(operation)
        for command in (self.save_command(),replace(self.bind,opcode=NativeOpcode.START,data=b""),self.bind):
            with self.subTest(command=command),self.assertRaisesRegex(ValueError,"pending battle"):
                await (self.c.battle_rpc(command) if isinstance(command,NativeControl) else self.c.save_rpc(command))
        self.assertFalse(self.c._save_pending);self.assertFalse(self.c._battle_pending)
        self.assertFalse(self.c._checkpoint_pending);self.assertFalse(self.c._trade_pending)
        self.assertEqual(self.journal.path.read_bytes(),b"{}")
        self.assertTrue(self.c.connected)

    async def test_observational_checkpoint_trade_queries_and_native_queries_remain_live(self):
        self.malformed_intent()
        from emerald_multiplayer.trade_desk import TradeDesk
        self.server.trade_desk = TradeDesk(self.store,self.server._connected_lease)
        self.assertEqual((await self.c.checkpoint_rpc("info"))["checkpoint"]["revision"],1)
        self.assertEqual((await self.c.checkpoint_rpc("read",expected_revision=1,offset=0,length=128))["offset"],0)
        self.assertEqual((await self.c.trade_rpc("pending"))["recoveries"],[])
        self.assertEqual((await self.c.trade_rpc("status",transaction_id=str(uuid4())))["trade"]["state"],"aborted")
        query = replace(self.bind,opcode=NativeOpcode.QUERY,data=b"",sequence=2)
        await self.roundtrip(query,bytes(64))
        await self.roundtrip(self.save_command(SaveOpcode.QUERY),bytes(48))
        await self.bridge.pose(make_pose(frame=1))
        await asyncio.sleep(.12)
        self.assertTrue(self.c.connected)
        self.assertEqual(self.journal.path.read_bytes(),b"{}")

    async def test_generic_save_owner_cannot_inherit_native_battle_or_trade_authority(self):
        self.malformed_intent();self.c._live_save_owner = asyncio.current_task()
        try:
            for call in (lambda:self.c.checkpoint_rpc("ownership_grant"),
                         lambda:self.c.trade_rpc("confirm"),lambda:self.c.save_rpc(self.save_command()),
                         lambda:self.c.battle_rpc(self.bind)):
                with self.assertRaisesRegex(ValueError,"pending battle"):await call()
        finally:self.c._live_save_owner = None
        self.assertFalse(self.c._save_pending);self.assertFalse(self.c._battle_pending)

    async def test_head_lookup_owns_direct_mutators_before_file_publication(self):
        querying, continue_query, admitted, finish = (asyncio.Event() for _ in range(4))
        original = CheckpointClient.info
        async def paused_info(client):
            # Even the admitting task cannot dispatch BIND before fsync.
            with self.assertRaisesRegex(ValueError,"exact persisted BIND"):
                await self.c.battle_rpc(self.bind)
            with self.assertRaisesRegex(ValueError,"pending battle"):
                await self.c.save_rpc(self.save_command())
            querying.set();await continue_query.wait()
            return await original(client)
        async def admission():
            async with self.journal.bind_intent(self.binding,self.bind,self.canonical):
                admitted.set();await finish.wait()
        with patch.object(CheckpointClient,"info",paused_info):
            task = asyncio.create_task(admission());self.tasks.append(task)
            await asyncio.wait_for(querying.wait(),3)
            self.assertFalse(self.journal.path.exists())
            self.assertIs(self.c._live_battle_owner,task)
            for call in (lambda:self.c.checkpoint_rpc("begin"),lambda:self.c.checkpoint_rpc("ownership_grant"),
                         lambda:self.c.trade_rpc("open"),lambda:self.c.save_rpc(self.save_command()),
                         lambda:self.c.battle_rpc(self.bind)):
                with self.assertRaisesRegex(ValueError,"pending battle"):await call()
            self.assertFalse(self.c._save_pending);self.assertFalse(self.c._battle_pending)
            self.assertFalse(self.c._checkpoint_pending);self.assertFalse(self.c._trade_pending)
            # Direct authenticated observations remain available during info.
            self.assertEqual((await self.c.checkpoint_rpc("info"))["checkpoint"]["revision"],1)
            await self.roundtrip(replace(self.bind,opcode=NativeOpcode.QUERY,data=b"",sequence=2),bytes(64))
            continue_query.set();await asyncio.wait_for(admitted.wait(),3)
            self.assertTrue(self.journal.path.exists())
            finish.set();await task
        self.assertIsNone(self.c._live_save_owner);self.assertIsNone(self.c._live_battle_owner)

    async def test_exact_fsynced_bind_only_is_permitted_in_its_owned_context(self):
        data = struct.pack("<I16sBBBB10I",1,UUID(self.binding.generation).bytes,
            2,self.binding.local_slot,2,0,1,0,0,0,0,0,0,600,0,0)
        async with self.journal.bind_intent(self.binding,self.bind,self.canonical) as intent:
            self.assertEqual(read_battle_intent(self.journal.path),intent)
            await self.roundtrip(intent.bind,data)
            for command in (replace(self.bind,battle_id=str(uuid4())),
                            replace(self.bind,opcode=NativeOpcode.START,data=b"",sequence=2)):
                with self.assertRaisesRegex(ValueError,"exact persisted BIND"):await self.c.battle_rpc(command)
            # Neither generic nor dedicated battle ownership permits ordinary
            # persisted-character writes while the intent is unresolved.
            for call in (lambda:self.c.checkpoint_rpc("ownership_grant"),lambda:self.c.trade_rpc("open"),
                         lambda:self.c.save_rpc(self.save_command())):
                with self.assertRaisesRegex(ValueError,"pending battle"):await call()
            async def outsider():
                with self.assertRaisesRegex(ValueError,"pending battle"):await self.c.battle_rpc(self.bind)
            await asyncio.create_task(outsider())
        self.assertTrue(self.journal.path.exists())
        with self.assertRaisesRegex(ValueError,"pending battle"):await self.c.battle_rpc(self.bind)
        self.assertIsNone(self.c._live_save_owner);self.assertIsNone(self.c._live_battle_owner)
        self.assertTrue(self.c.connected)


if __name__ == "__main__":unittest.main()
