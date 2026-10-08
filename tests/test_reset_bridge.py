"""Real Lua, TLS/SQLite and IPC coverage; synthetic native mailboxes, no gameplay claim."""
import asyncio
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
from emerald_multiplayer.reset_mailbox import CAPABILITY, ResetRequest, capability
from emerald_multiplayer.reset_attempts import enable_reset_attempts
from emerald_multiplayer.bridge_protocol import encode_packet, read_packet
from emerald_multiplayer.companion import Companion
from emerald_multiplayer.host_world import HostWorld
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE
from emerald_multiplayer.trade_storage import TradeCheckpointStore
from test_companion import BinaryBridge, wait_until
from test_host_world import make_trade_files
from test_ownership_storage import source_flash, owned_flash
import test_live_bridge as fixtures


class ResetProvisioningTests(unittest.TestCase):
    def test_combined_fresh_capabilities_compose_and_existing_world_is_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rom, manifest = make_trade_files(root)
            # One immutable synthetic build; only its optional capabilities
            # become visible after the old world's creation.
            raw = bytearray(4096)
            raw[0:4] = struct.pack("<I", 1)
            raw[4:8] = struct.pack("<I", 3)
            rom.write_bytes(raw)
            value = json.loads(manifest.read_text())
            value.update(rom_size=len(raw), rom_sha256=hashlib.sha256(raw).hexdigest(),
                         rom_crc32=f"{zlib.crc32(raw):08x}")
            manifest.write_text(json.dumps(value))
            old = HostWorld.create(root/"old", rom, manifest, player_names=["Host"], endpoint="127.0.0.1", port=8765)
            value.update(battle_execution_abi_version=1, battle_abi_version=3,
                         battle_abi_address=0x08000004, battle_mailbox_address=0x02022000, battle_mailbox_size=512,
                         battle_string_table_address=0x08000100, battle_string_table_size=721*4,
                         reset_abi_version=1, reset_abi_address=0x08000000,
                         reset_mailbox_address=0x02023000, reset_mailbox_size=128)
            manifest.write_text(json.dumps(value))
            with HostWorld.open(old.directory, rom, manifest).open_store() as store:
                self.assertEqual(store._schema_version, 3)
                self.assertFalse(store.battle_reservations_enabled)
                self.assertFalse(store.reset_attempts_enabled)
            fresh = HostWorld.create(root/"new", rom, manifest, player_names=["Host"], endpoint="127.0.0.1", port=8765)
            with fresh.open_store() as store:
                self.assertEqual(store._schema_version, 303)
                self.assertTrue(store.battle_reservations_enabled and store.reset_attempts_enabled)
            for filename, version in (("before-battle-reservations.sqlite3", 3), ("before-personal-attempts.sqlite3", 103)):
                with TradeCheckpointStore(fresh.directory/filename, fresh.build_id, fresh.ruleset_id) as backup:
                    self.assertEqual(backup._schema_version, version)
                    self.assertEqual(backup.metadata.world_id, fresh.world_id)
                    backup.authenticate(fresh.accounts[0].player_id, fresh.accounts[0].credential)
                self.assertFalse((old.directory/filename).exists())

    def test_fresh_verified_build_enables_ledger_but_opening_existing_world_never_migrates(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            rom,manifest=make_trade_files(root)
            old=HostWorld.create(root/"old",rom,manifest,player_names=["Host"],endpoint="127.0.0.1",port=8765)
            value=json.loads(manifest.read_text())
            value.update(reset_abi_version=1,reset_abi_address=0x08000000,
                reset_mailbox_address=0x02023000,reset_mailbox_size=128)
            manifest.write_text(json.dumps(value))
            reopened=HostWorld.open(old.directory,rom,manifest)
            with reopened.open_store() as store:
                self.assertFalse(store.reset_attempts_enabled)
                self.assertEqual(store._schema_version,3)
            self.assertFalse((old.directory/"before-personal-attempts.sqlite3").exists())
            new=HostWorld.create(root/"new",rom,manifest,player_names=["Host","Friend"],endpoint="127.0.0.1",port=8765)
            with new.open_store() as store:
                self.assertTrue(store.reset_attempts_enabled)
                self.assertEqual(store._schema_version,203)
            with TradeCheckpointStore(new.directory/"before-personal-attempts.sqlite3",new.build_id,new.ruleset_id) as backup:
                self.assertFalse(backup.reset_attempts_enabled)
                self.assertEqual(backup.metadata.world_id,new.world_id)
                for account in new.accounts:
                    self.assertEqual(backup.authenticate(account.player_id,account.credential).display_name,account.display_name)


class ResetLuaTests(unittest.TestCase):
    lua_path = staticmethod(fixtures.LuaBridgeTests.lua_path)
    run_lua = fixtures.LuaBridgeTests.run_lua

    def fixture(self, version=1):
        script = fixtures.LuaBridgeTests.fixture(self, live=True, trade=True)
        script = script.replace("or address==0x02002018",
            "or (address>=0x02004030 and address<=0x02004050) or address==0x02002018", 1)
        setup = '''
EMERALD_BRIDGE.reset_abi=1;EMERALD_BRIDGE.reset_abi_address=0x080000cc
EMERALD_BRIDGE.reset_address=0x02004000;EMERALD_BRIDGE.reset_size=128
loadBytes(0x080000cc,string.pack("<I4",1))
loadBytes(0x02004000,string.pack("<I4I2I2I4I4",0x31524D45,1,128,1,0)..string.rep("\\0",112))
'''
        if version == 2:
            setup = setup.replace("reset_abi=1", "reset_abi=2").replace('string.pack("<I4",1)', 'string.pack("<I4",2)').replace('0x31524D45,1,128', '0x31524D45,2,128')
        return script.replace("local cfg = assert", setup+"\nlocal cfg = assert", 1)

    def request(self, sequence=1):
        request = ResetRequest(sequence, 2, 3, 0x1001, sequence-1)
        return request, f'loadBytes(0x02004010,unhex("{request.pack().hex()}"));loadBytes(0x0200400c,string.pack("<I4",{sequence*2}));advance(100)\n'

    def test_exact_native_request_and_atomic_count_only_ack(self):
        request, send = self.request()
        reply = request.reply(1)
        self.run_lua(self.fixture()+send+f'''
inbox=unhex("{encode_packet(b'U'+reply).hex()}");advance(100)
local cap,req=false,false
for _,p in ipairs(decoded()) do
 if p==unhex("{CAPABILITY.hex()}") then cap=true end
 if p==unhex("{(b'T'+request.pack()).hex()}") then req=true end
end
assert(cap and req and #console.errors==0)
assert(range(0x02004034,32)==unhex("{reply.hex()}"))
assert(emu:read32(0x02004030)%2==0)
''')

    def test_old_ack_and_malformed_padding_never_change_counter(self):
        first, send1 = self.request()
        second, send2 = self.request(2)
        self.run_lua(self.fixture()+send1+send2+f'''
inbox=unhex("{encode_packet(b'U'+first.reply(1)).hex()}");advance(100)
assert(range(0x02004030,36)==string.rep("\\0",36))
assert(#console.errors==0)
''')
        bad = second.reply(2)[:-1]+b"x"
        self.run_lua(self.fixture()+send2+f'''
inbox=unhex("{encode_packet(b'U'+bad).hex()}");advance(100)
assert(stopped and #console.errors==1)
assert(range(0x02004030,36)==string.rep("\\0",36))
''')

    def test_native_runtime_regression_closes_bridge_without_an_ack(self):
        _, send=self.request()
        self.run_lua(self.fixture()+send+'''
loadBytes(0x02004008,string.pack("<I4",0));advance(1)
assert(closes==1)
assert(range(0x02004030,36)==string.rep("\\0",36))
''')

    def test_abi2_cancel_writes_only_reply_and_relays_exact_readonly_receipt(self):
        request, send = self.request()
        waiting = struct.pack("<8I", 1, 2, 3, 0x1001, 0, 1, 0, 0)
        cancelled = struct.pack("<8I", 1, 2, 3, 0x1001, 0, 4, 0, 0)
        ready = struct.pack("<8I", 1, 2, 3, 0x1001, 0, 4, 1, 0)
        self.run_lua(self.fixture(2)+send+f'''
loadBytes(0x02004054,unhex("{waiting.hex()}"));advance(100)
inbox=unhex("{encode_packet(b'U'+request.cancel()).hex()}");advance(100)
assert(range(0x02004034,32)==unhex("{request.cancel().hex()}"))
assert(range(0x02004054,32)==unhex("{waiting.hex()}"))
loadBytes(0x02004054,unhex("{cancelled.hex()}"));advance(100)
loadBytes(0x02004054,unhex("{ready.hex()}"));advance(100)
local found,receipts=false,{{}}
for _,p in ipairs(decoded()) do
 if p==unhex("{capability(2).hex()}") then found=true end
 if p:sub(1,1)=="Y" then receipts[#receipts+1]=p:sub(2) end
end
assert(found and #receipts==3 and #console.errors==0)
assert(receipts[1]==unhex("{waiting.hex()}"))
assert(receipts[2]==unhex("{cancelled.hex()}"))
assert(receipts[3]==unhex("{ready.hex()}"))
''')

    def test_abi1_refuses_cancellation_and_abi2_refuses_foreign_receipt(self):
        request, send = self.request()
        self.run_lua(self.fixture()+send+f'''
inbox=unhex("{encode_packet(b'U'+request.cancel()).hex()}");advance(100)
assert(stopped and #console.errors==1)
assert(range(0x02004030,36)==string.rep("\\0",36))
''')
        foreign = struct.pack("<8I", 1, 2, 4, 0x1001, 0, 4, 1, 0)
        self.run_lua(self.fixture(2)+send+f'''
loadBytes(0x02004054,unhex("{foreign.hex()}"));advance(100)
assert(stopped and #console.errors==1)
assert(range(0x02004030,36)==string.rep("\\0",36))
''')


class ResetTlsBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_four_authenticated_players_and_native_admission_survive_host_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            rom, manifest=make_trade_files(root)
            raw = bytearray(rom.read_bytes())
            raw[4:8] = struct.pack("<I", 2)
            rom.write_bytes(raw)
            value=json.loads(manifest.read_text())
            value.update(rom_sha256=hashlib.sha256(raw).hexdigest(), rom_crc32=f"{zlib.crc32(raw):08x}",
                reset_abi_version=2, reset_abi_address=0x08000004,
                reset_mailbox_address=0x02023000, reset_mailbox_size=128)
            manifest.write_text(json.dumps(value))
            host=HostWorld.create(root/"host",rom,manifest,player_names=["Host","A","B","C"],endpoint="127.0.0.1",port=8765)
            store=host.open_store()
            enable_reset_attempts(store,root/"before-reset")
            store.begin_server_boot()
            heads=[]
            for index, player in enumerate(host.accounts):
                lease=store.acquire_lease(player.player_id,player.credential)
                store.enroll_player(player.player_id,source_flash(personalities=(index+11,)))
                grant=store.reserve_instances(player.player_id,lease,str(uuid4()),0,1,32)
                heads.append(store.commit_checkpoint(player.player_id,lease,str(uuid4()),0,
                    owned_flash(grant,personalities=(index+11,)),host.build_id,host.ruleset_id,OWNERSHIP_PROFILE))
                store.release_lease(player.player_id,lease)
            server=WorldServer(ServerConfig(host.build_id,host.ruleset_id),store=store)
            companions=[]; bridge=None
            try:
                await server.start(port=0,tls=host.server_tls)
                for index in range(4):
                    options=dict(token=secrets.token_bytes(32),private_directory=root/f"client-{index}")
                    config=(host.host_companion_config(rom,manifest,**options) if index==0 else
                            host.invitation(index).companion_config(rom,manifest,**options))
                    companion=Companion(replace(config,server_port=server.address[1],ipc_port=0))
                    companions.append(companion);await companion.start()
                await wait_until(lambda:all(c.connected and len(c._players)==4 for c in companions))
                companion=companions[0]
                bridge=await BinaryBridge.connect(companion)
                bridge.writer.write(encode_packet(capability(2)));await bridge.writer.drain()
                await wait_until(lambda:companion._bridge is not None and companion._bridge.reset_session is not None)
                request=ResetRequest(1,companion.session_epoch,companion._bridge.incarnation,0x1001,0)
                bridge.writer.write(encode_packet(b"T"+request.pack()));await bridge.writer.drain()
                async with asyncio.timeout(8):
                    while True:
                        packet=await read_packet(bridge.reader)
                        if packet[:1]==b"U":break
                self.assertEqual(packet,b"U"+request.reply(1))
                receipt = struct.pack("<8I", request.sequence, request.session, request.incarnation,
                                      request.encounter, 1, 2, 0, 0)
                bridge.writer.write(encode_packet(b"Y" + receipt)); await bridge.writer.drain()
                await wait_until(lambda:companion._bridge.reset_session.receipt is not None)
                self.assertEqual(companion._bridge.reset_session.receipt.attempt, 1)
                for c,cp in zip(companions,heads):
                    self.assertEqual(store.read_checkpoint(c.config.player_id,c.session_epoch),cp)
                    self.assertIsNotNone(c._remote_writer.get_extra_info("ssl_object"))
                    c.config.server_tls.verify_peer(c._remote_writer)
                await bridge.close();bridge=None
                await asyncio.gather(*(c.close() for c in companions));companions=[]
                await server.close();store.close()
                store=host.open_store()
                server=WorldServer(ServerConfig(host.build_id,host.ruleset_id),store=store)
                await server.start(port=0,tls=host.server_tls)
                config=host.host_companion_config(rom,manifest,token=secrets.token_bytes(32),private_directory=root/"fresh")
                c=Companion(replace(config,server_port=server.address[1],ipc_port=0));companions.append(c)
                await c.start();await wait_until(lambda:c.connected)
                result=await c.reset_rpc(encounter_id=0x1001,incarnation=1,sequence=1,observed_count=0)
                self.assertEqual(result["result"]["attempt"],2)
                store.integrity_check()
            finally:
                if bridge is not None:await bridge.close()
                await asyncio.gather(*(c.close() for c in companions),return_exceptions=True)
                await server.close();store.close()
