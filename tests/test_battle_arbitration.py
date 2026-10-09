"""Four real loopback actors; native receipts are explicit trusted fixtures."""
from __future__ import annotations

import asyncio
import base64
from contextlib import suppress
from dataclasses import replace
import hashlib
from pathlib import Path
import struct
import tempfile
import unittest
from uuid import UUID, uuid4

from emerald_multiplayer.battle_desk import BattleError
from emerald_multiplayer.native_battle import Kind, NativeControl, Opcode
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE
from emerald_multiplayer.ownership_storage import OwnershipCheckpointStore
from emerald_multiplayer.protocol import encode_message, read_message
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.storage import CheckpointStore, StorageError
from emerald_multiplayer.trade_storage import TradeCheckpointStore
from test_ownership_storage import owned_flash, source_flash

BUILD, RULES = "native-arbitration-test", "test-rules"


async def wait_until(predicate):
    async with asyncio.timeout(8):
        while not predicate():
            await asyncio.sleep(.005)


class Actor:
    """Authenticate once, route correlated replies and always answer heartbeat."""

    @classmethod
    async def connect(cls, address, player):
        self = cls()
        self.player = player
        self.pending, self.worlds, self.pongs = {}, [], 0
        self.lock = asyncio.Lock()
        self.reader, self.writer = await asyncio.open_connection(*address)
        await self.send(dict(type="hello", protocol=PROTOCOL_VERSION, build_id=BUILD, ruleset_id=RULES,
            player_id=player.player_id, display_name=player.display_name, credential=player.credential.hex()))
        welcome = await asyncio.wait_for(read_message(self.reader),8)
        if welcome is None or welcome["type"] != "welcome":
            raise AssertionError("authenticated actor was not admitted")
        self.lease = welcome["session_epoch"]
        self.task = asyncio.create_task(self.read_loop())
        return self

    async def send(self, message):
        async with self.lock:
            self.writer.write(encode_message(message));await self.writer.drain()

    async def read_loop(self):
        try:
            while True:
                message = await read_message(self.reader)
                if message is None:
                    return
                if message["type"] == "ping":
                    await self.send({**message,"type":"pong"});self.pongs += 1
                elif message["type"] == "world":
                    self.worlds.append(message)
                    self.worlds[:] = self.worlds[-2:]
                else:
                    future = self.pending.get(message.get("request_id"))
                    if future is not None and not future.done():
                        future.set_result(message)
        finally:
            for future in self.pending.values():
                if not future.done():future.set_exception(ConnectionError("test actor closed"))

    async def rpc(self, kind, *, request_id=None, **fields):
        request_id = request_id or str(uuid4())
        future = asyncio.get_running_loop().create_future();self.pending[request_id] = future
        try:
            if kind.startswith("trade_") and kind.removeprefix("trade_") in PREPARATION_OPERATIONS:
                # Hosts require recipient preparation v1 before offers/consent.
                fields.setdefault("preparation_version", PREPARATION_VERSION)
            await self.send(dict(type=kind,request_id=request_id,session_epoch=self.lease,**fields))
            result = await asyncio.wait_for(future,8)
            if result["session_epoch"] != self.lease or result["request_id"] != request_id:
                raise AssertionError("uncorrelated server reply")
            return result
        finally:self.pending.pop(request_id,None)

    async def move(self, x, map_number=9):
        await self.send(dict(type="presence",session_epoch=self.lease,seq=1,map_epoch=0,
            map_group=0,map_number=map_number,x=x,y=11,direction=1,elevation=0,
            avatar_gender=0,activity="overworld"))

    async def close(self):
        self.writer.close()
        with suppress(ConnectionError,OSError):await self.writer.wait_closed()
        if not self.task.done():self.task.cancel()
        await asyncio.gather(self.task,return_exceptions=True)


from emerald_multiplayer.battle_reservations import enable_battle_reservations
from emerald_multiplayer.protocol import PROTOCOL_VERSION
from emerald_multiplayer.trade_protocol import PREPARATION_OPERATIONS, PREPARATION_VERSION


class BattleArbitrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory();self.root = Path(self.temp.name)
        self.store = TradeCheckpointStore(self.root/"world.sqlite3",BUILD,RULES)
        enable_battle_reservations(self.store, self.root/"before-battles.sqlite3")
        self.store.begin_server_boot()
        self.players,self.heads,self.grants = [],[],[]
        for index in range(4):
            player = self.store.create_player(f"Trainer {index}")
            lease = self.store.acquire_lease(player.player_id,player.credential)
            personalities = (7+index*2,8+index*2)
            self.store.enroll_player(player.player_id,source_flash(("party:0","party:1"),personalities=personalities))
            grant = self.store.reserve_instances(player.player_id,lease,str(uuid4()),0,1,32)
            payload = owned_flash(grant,(("party:0",grant.start),("party:1",grant.start+1)),personalities=personalities)
            head = self.store.commit_checkpoint(player.player_id,lease,str(uuid4()),0,payload,BUILD,RULES,OWNERSHIP_PROFILE)
            self.store.release_lease(player.player_id,lease)
            self.players.append(player);self.heads.append(head);self.grants.append(grant)
        self.server = WorldServer(ServerConfig(BUILD,RULES,heartbeat_interval=.05,idle_timeout=20),
            store=self.store,development_trades=True,development_battles=True)
        await self.server.start(port=0)
        self.actors = [await Actor.connect(self.server.address,player) for player in self.players]
        self.desk = self.server.battle_desk
        self.battle_id = str(uuid4())
        self.view = self.desk.invite(*self.actor(0),self.players[1].player_id,self.battle_id)
        self.generation = self.view["generation"]

    async def asyncTearDown(self):
        for actor in self.actors:await actor.close()
        await self.server.close();self.store.close();self.temp.cleanup()

    def actor(self,index):return self.players[index].player_id,self.actors[index].lease

    def call(self,method,index,*args,**fields):
        generation = () if method == "status" else (self.generation,)
        return getattr(self.desk,method)(*self.actor(index),self.battle_id,*generation,*args,**fields)

    def register(self):
        for index in range(1,len(self.view["players"])):self.call("accept",index,self.view["fingerprint"])
        for index in range(len(self.view["players"])):self.call("register",index,100+index)

    def descriptor(self,index):return self.call("descriptor",index)

    def control(self,index,opcode,sequence,data=b""):
        return NativeControl(100+index,self.actors[index].lease,self.battle_id,sequence,opcode,
            source_slot=self.descriptor(index).source_slot,data=data,phase=self.descriptor(index).mode)

    def query(self,index,sequence,flags=1,revision=0,outcome=0):
        return struct.pack("<I16sBBBB10I",flags,UUID(self.generation).bytes,len(self.view["players"]),self.descriptor(index).source_slot,
            self.descriptor(index).mode,0,sequence,0,0,0,0,0,0,600,revision,outcome)

    def bind(self,index,*,ack=True):
        binding = self.call("authorize_bind",index)
        request = self.control(index,Opcode.BIND,1,binding.pack())
        if ack:self.call("bound",index,request,replace(request,data=self.query(index,1)))
        return request

    def abort(self,index):
        request = self.control(index,Opcode.ABORT_PRE_START,2)
        return self.call("aborted",index,request,request)

    def running(self):
        self.register()
        for index in range(len(self.view["players"])):
            self.bind(index)
            command = self.control(index,Opcode.PREPARE,2,self.call("preparation",index).pack())
            self.call("prepared",index,command,replace(command,data=self.query(index,2,9,1)),self.descriptor(index).trainer_descriptor)
        self.desk.authorize_start(self.battle_id,self.generation)
        for index in range(len(self.view["players"])):
            command = self.control(index,Opcode.START,3)
            self.call("started",index,command,replace(command,data=self.query(index,3,25,1)))
            for part in range(3):
                self.call("verify_startup",index,Kind.PARTY_0+part,3+part,self.descriptor(index).party[part*200:part*200+200])
        self.desk.authorize_running(self.battle_id,self.generation)

    def multi(self):
        self.call("cancel",0)
        self.battle_id=str(uuid4())
        self.view=self.desk.invite_multi(*self.actor(0),self.players[2].player_id,
            (self.players[1].player_id,self.players[3].player_id),self.battle_id)
        self.generation=self.view["generation"]

    async def test_multi_first_bind_reserves_all_four_and_partial_abort_cannot_free_them(self):
        self.multi();self.register()
        for index in range(4):self.bind(index,ack=False)
        self.assertEqual(self.call("cancel",3)["state"],"aborting")
        for index in range(3):
            self.assertEqual(self.abort(index)["state"],"aborting")
            for actor in range(4):
                await self.error(actor,"checkpoint_begin",**self.fingerprint(actor))
                self.assertEqual((await self.actors[actor].rpc("checkpoint_info"))["checkpoint"]["revision"],1)
        self.assertEqual(self.abort(3)["state"],"aborted")
        self.assertEqual((await self.upload(3))["revision"],2)

    async def test_multi_all_four_remain_reserved_through_three_release_acks(self):
        self.multi();self.running()
        for index in range(4):
            command=self.control(index,Opcode.QUERY,4);descriptor=self.descriptor(index)
            self.call("finish",index,command,replace(command,data=self.query(index,3,57,1,1)),
                outcome=1,party=descriptor.party,party_count=descriptor.party_count)
        for index in range(4):
            command=self.control(index,Opcode.RELEASE,4,struct.pack("<II",self.descriptor(index).party_crc32,1))
            result=self.call("released",index,command,replace(command,data=b""))
            if index<3:
                self.assertEqual(result["state"],"release_authorized")
                for actor in range(4):await self.error(actor,"checkpoint_begin",**self.fingerprint(actor))
        self.assertEqual(result["state"],"closed")
        for index in range(4):self.assertEqual((await self.upload(index))["revision"],2)

    async def test_multi_fourth_upload_blocks_initial_binding_without_consuming_intent(self):
        self.multi();self.register()
        request_id=str(uuid4())
        response=await self.actors[3].rpc("checkpoint_begin",request_id=request_id,**self.fingerprint(3))
        self.assertEqual(response["type"],"checkpoint_result")
        with self.assertRaises(BattleError) as caught:self.call("authorize_bind",0)
        self.assertEqual(caught.exception.code,"checkpoint_busy")
        self.assertFalse(self.desk._active[self.battle_id].bind_intent)
        self.assertEqual((await self.actors[3].rpc("checkpoint_abort",upload_id=request_id))["type"],"checkpoint_result")
        self.bind(0,ack=False)
        for index in range(4):await self.error(index,"checkpoint_begin",**self.fingerprint(index))

    def fingerprint(self,index,base=1):
        payload = self.heads[index].payload
        return dict(expected_revision=base,size=len(payload),sha256=hashlib.sha256(payload).hexdigest(),save_profile=OWNERSHIP_PROFILE)

    async def error(self,index,kind,code="battle_busy",**fields):
        response = await self.actors[index].rpc(kind,**fields)
        self.assertTrue(response["type"].endswith("_error"),response)
        self.assertEqual(response["code"],code,response)
        return response

    async def upload(self,index,base=1):
        actor = self.actors[index];request_id = str(uuid4());fingerprint = self.fingerprint(index,base)
        reply = await actor.rpc("checkpoint_begin",request_id=request_id,**fingerprint)
        self.assertEqual(reply["type"],"checkpoint_result",reply)
        payload = self.heads[index].payload
        for offset in range(0,len(payload),4096):
            reply = await actor.rpc("checkpoint_chunk",upload_id=request_id,offset=offset,
                data_b64=base64.b64encode(payload[offset:offset+4096]).decode("ascii"))
            self.assertEqual(reply["next_offset"],min(offset+4096,len(payload)))
        reply = await actor.rpc("checkpoint_commit",upload_id=request_id,**fingerprint)
        self.assertEqual(reply["type"],"checkpoint_result",reply)
        return reply["checkpoint"]

    async def trade_ready(self,left,right):
        transaction = str(uuid4())
        view = (await self.actors[left].rpc("trade_open",transaction_id=transaction,peer=self.players[right].player_id))["trade"]
        for index in (left,right):
            head = (await self.actors[index].rpc("checkpoint_info"))["checkpoint"]
            view = (await self.actors[index].rpc("trade_offer",transaction_id=transaction,generation=view["generation"],
                revision=head["revision"],sha256=head["sha256"],serial=self.grants[index].start))["trade"]
        return view

    async def test_development_opt_in_and_explicit_owned_store_are_required(self):
        self.assertIsNone(WorldServer(self.server.config,store=self.store).battle_desk)
        for value in (1,None,"yes"):
            with self.subTest(value=value),self.assertRaises(ValueError):
                WorldServer(self.server.config,store=self.store,development_battles=value)
        with self.assertRaises(ValueError):WorldServer(self.server.config,development_battles=True)
        legacy = CheckpointStore(self.root/"legacy.sqlite3",BUILD,RULES,"rhh-1.17.1-bb1093-presence-v1")
        try:
            with self.assertRaises(ValueError):WorldServer(self.server.config,store=legacy,development_battles=True)
        finally:legacy.close()
        owned = OwnershipCheckpointStore(self.root/"owned.sqlite3",BUILD,RULES)
        try:
            with self.assertRaises(StorageError):WorldServer(self.server.config,store=owned,development_battles=True)
            enable_battle_reservations(owned, self.root/"owned-before-battles.sqlite3")
            self.assertIsNotNone(WorldServer(self.server.config,store=owned,development_battles=True).battle_desk)
        finally:owned.close()

    async def test_first_uncertain_bind_reserves_both_without_native_ack(self):
        self.register();self.bind(0,ack=False)
        before = self.store._connection.execute("SELECT COUNT(*) FROM ownership_grants").fetchone()[0]
        for index in (0,1):
            for kind,fields in (
                ("checkpoint_begin",self.fingerprint(index)),
                ("checkpoint_chunk",dict(upload_id=str(uuid4()),offset=0,data_b64="eA==")),
                ("checkpoint_commit",dict(upload_id=str(uuid4()),**self.fingerprint(index))),
                ("checkpoint_abort",dict(upload_id=str(uuid4()))),
                ("ownership_grant",dict(expected_revision=1,incarnation=1,count=1)),
                ("trade_open",dict(transaction_id=str(uuid4()),peer=self.players[2].player_id)),
                ("trade_offer",dict(transaction_id=str(uuid4()),generation=str(uuid4()),revision=1,
                    sha256=self.heads[index].sha256,serial=self.grants[index].start)),
                ("trade_confirm",dict(transaction_id=str(uuid4()),generation=str(uuid4()),fingerprint="f"*64)),
                ("trade_cancel",dict(transaction_id=str(uuid4()),generation=str(uuid4()))),
                ("trade_ack",dict(transaction_id=str(uuid4()),revision=1,sha256=self.heads[index].sha256))):
                with self.subTest(index=index,kind=kind):await self.error(index,kind,**fields)
            self.assertIsNone(self.server.sessions[self.players[index].player_id].upload)
            self.assertEqual(self.store.read_checkpoint(*self.actor(index)),self.heads[index])
        self.assertEqual(self.store._connection.execute("SELECT COUNT(*) FROM ownership_grants").fetchone()[0],before)
        self.assertFalse(self.server.trade_desk._proposals)

    async def test_preserved_queries_presence_heartbeat_and_uninvolved_saves_and_trade(self):
        self.register();self.bind(0,ack=False)
        for index,actor in enumerate(self.actors):
            await actor.move(6+index,9 if index%2 == 0 else 2)
            self.assertEqual((await actor.rpc("checkpoint_info"))["checkpoint"]["revision"],1)
            self.assertEqual((await actor.rpc("checkpoint_read",expected_revision=1,offset=0,length=128))["offset"],0)
            self.assertEqual((await actor.rpc("trade_pending"))["recoveries"],[])
            self.assertEqual((await actor.rpc("trade_status",transaction_id=str(uuid4())))["trade"]["state"],"aborted")
        await wait_until(lambda:all(actor.pongs >= 1 for actor in self.actors))
        self.assertTrue(all(not self.server.sessions[player.player_id].closed for player in self.players))
        self.assertEqual({session.presence["x"] for session in self.server.sessions.values()},{6,7,8,9})
        self.assertEqual((await self.upload(2))["revision"],2)
        view = await self.trade_ready(2,3)
        first = (await self.actors[2].rpc("trade_confirm",transaction_id=view["transaction_id"],
            generation=view["generation"],fingerprint=view["fingerprint"]))["trade"]
        self.assertEqual(first["state"],"offering")
        result = (await self.actors[3].rpc("trade_confirm",transaction_id=view["transaction_id"],
            generation=view["generation"],fingerprint=view["fingerprint"]))["trade"]
        # Mutual consent advances the uninvolved pair to recipient preparation
        # (preparation v1); the held battle pair's checkpoints never move.
        self.assertEqual(result["state"],"preparing")
        self.assertEqual(self.store.read_checkpoint(*self.actor(0)).revision,1)
        self.assertEqual(self.store.read_checkpoint(*self.actor(1)).revision,1)
        self.store.integrity_check()

    async def test_uninvolved_actor_cannot_admit_held_peer(self):
        self.register();self.bind(0,ack=False)
        for peer in (0,1):
            await self.error(2,"trade_open",transaction_id=str(uuid4()),peer=self.players[peer].player_id)
            with self.assertRaises(BattleError):
                self.desk.invite(*self.actor(2),self.players[peer].player_id,str(uuid4()))
        self.assertFalse(self.server.trade_desk._proposals)

    async def test_existing_partial_upload_prevents_bind_until_explicit_abort(self):
        self.register();upload_id = str(uuid4())
        result = await self.actors[1].rpc("checkpoint_begin",request_id=upload_id,**self.fingerprint(1))
        self.assertEqual(result["type"],"checkpoint_result")
        with self.assertRaises(BattleError) as caught:self.bind(0,ack=False)
        self.assertEqual(caught.exception.code,"checkpoint_busy")
        self.assertFalse(self.desk._active[self.battle_id].bind_intent)
        result = await self.actors[1].rpc("checkpoint_abort",upload_id=upload_id)
        self.assertEqual(result["type"],"checkpoint_result")
        self.bind(0,ack=False)
        await self.error(1,"ownership_grant",expected_revision=1,incarnation=1,count=1)

    async def test_existing_trade_offer_prevents_bind_without_discarding_consent(self):
        self.register();view = await self.trade_ready(1,2)
        with self.assertRaises(BattleError) as caught:self.bind(0,ack=False)
        self.assertEqual(caught.exception.code,"trade_busy")
        self.assertFalse(self.desk._active[self.battle_id].bind_intent)
        status = (await self.actors[1].rpc("trade_status",transaction_id=view["transaction_id"]))["trade"]
        self.assertEqual(status,view)
        await self.actors[1].rpc("trade_cancel",transaction_id=view["transaction_id"],generation=view["generation"])
        self.bind(0,ack=False)
        await self.error(1,"checkpoint_begin",**self.fingerprint(1))

    async def test_prebind_head_edit_clears_battle_consent_without_blocking_saves(self):
        self.register()
        self.assertEqual((await self.upload(1))["revision"],2)
        status = self.call("status",0)
        self.assertEqual((status["state"],status["consent"]),("aborted",[]))
        with self.assertRaises(BattleError):self.bind(0,ack=False)
        self.assertEqual((await self.upload(0))["revision"],2)

    async def test_prebind_cancel_has_no_reservation_and_no_client_bind_endpoint(self):
        self.assertEqual(self.call("cancel",0)["state"],"aborted")
        self.assertEqual((await self.upload(0))["revision"],2)
        self.assertEqual((await self.actors[0].rpc("trade_open",transaction_id=str(uuid4()),
            peer=self.players[1].player_id))["trade"]["state"],"offering")
        # No public message may attest BIND or supply another actor's lease.
        await self.actors[3].send(dict(type="battle_authorize_bind",actor=self.players[0].player_id,
            session_epoch=self.actors[0].lease,battle_id=self.battle_id,generation=self.generation))
        await wait_until(lambda:self.actors[3].task.done())
        self.assertFalse(any(battle.bind_intent for battle in self.desk._active.values()))
        self.assertEqual(self.call("status",0)["state"],"aborted")

    async def test_partial_abort_ack_does_not_free_either_reservation(self):
        self.register();self.bind(0,ack=False);self.bind(1,ack=False)
        self.assertEqual(self.call("cancel",0)["state"],"aborting")
        self.assertEqual(self.abort(0)["state"],"aborting")
        for index in (0,1):await self.error(index,"checkpoint_begin",**self.fingerprint(index))
        self.assertEqual(self.abort(1)["state"],"aborted")
        for index in (0,1):self.assertEqual((await self.upload(index))["revision"],2)

    async def test_partial_release_ack_retains_both_until_terminal_close(self):
        self.running()
        for index in (0,1):
            command = self.control(index,Opcode.QUERY,4)
            descriptor = self.descriptor(index)
            self.call("finish",index,command,replace(command,data=self.query(index,3,57,1,1)),
                outcome=1,party=descriptor.party,party_count=descriptor.party_count)
        for index in (0,1):
            command = self.control(index,Opcode.RELEASE,4,struct.pack("<II",self.descriptor(index).party_crc32,1))
            result = self.call("released",index,command,replace(command,data=b""))
            if index == 0:
                self.assertEqual(result["state"],"release_authorized")
                for actor in (0,1):await self.error(actor,"checkpoint_begin",**self.fingerprint(actor))
        self.assertEqual(result["state"],"closed")
        for index in (0,1):self.assertEqual((await self.upload(index))["revision"],2)

    async def test_disconnect_and_new_lease_do_not_free_uncertain_native_hold(self):
        self.register();self.bind(0,ack=False)
        old_lease = self.actors[0].lease
        await self.actors[0].close()
        await wait_until(lambda:self.players[0].player_id not in self.server.sessions)
        self.actors[0] = await Actor.connect(self.server.address,self.players[0])
        self.assertNotEqual(self.actors[0].lease,old_lease)
        status = self.call("status",0)
        self.assertEqual(status["state"],"aborting")
        for index in (0,1):await self.error(index,"checkpoint_begin",**self.fingerprint(index))
        self.assertEqual((await self.actors[0].rpc("checkpoint_info"))["checkpoint"]["revision"],1)
        with self.assertRaises(StorageError):self.call("cancel",0)
        self.assertEqual((await self.upload(2))["revision"],2)

    async def test_post_start_expiry_stays_recovery_required_and_reserved(self):
        self.running()
        self.desk._active[self.battle_id].deadline = 0
        await wait_until(lambda:self.desk._active[self.battle_id].state == "recovery_required")
        self.assertEqual(self.call("status",0)["reason"],"deadline")
        for index in (0,1):await self.error(index,"ownership_grant",expected_revision=1,incarnation=1,count=1)
        with self.assertRaises(BattleError):self.call("cancel",0)
        self.assertEqual((await self.upload(2))["revision"],2)


if __name__ == "__main__":unittest.main()
