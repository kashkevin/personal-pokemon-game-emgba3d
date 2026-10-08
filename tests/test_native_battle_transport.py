"""ABI2 transport tests use synthetic mailboxes, never claim game acceptance."""
import asyncio
from dataclasses import replace
import struct
import unittest
from uuid import uuid4

from emerald_multiplayer.battle_mailbox import capability_packet
from emerald_multiplayer.bridge_protocol import encode_packet, read_packet
from emerald_multiplayer.companion import Companion
from emerald_multiplayer.native_battle import NativeControl, NativeBinding, Kind, Opcode
import test_battle_bridge as lua_fixture
import test_companion_battle as socket_fixture
from test_companion import wait_until


class NativeLuaTests(unittest.TestCase):
    lua_path = staticmethod(lua_fixture.BattleBridgeTests.lua_path)
    run_lua = lua_fixture.BattleBridgeTests.run_lua
    command = lua_fixture.BattleBridgeTests.command
    response = lua_fixture.BattleBridgeTests.response

    def fixture(self, abi=2):
        raw = lua_fixture.BattleBridgeTests.fixture(self)
        if abi == 2:
            raw = raw.replace("EMERALD_BRIDGE.battle_abi=1;", "EMERALD_BRIDGE.battle_abi=2;")
            raw = raw.replace('loadBytes(0x080000c8,string.pack("<I4",1))',
                              'loadBytes(0x080000c8,string.pack("<I4",2))')
            raw = raw.replace("0x31424D45,1,512,1,0,0,0", "0x31424D45,2,512,1,0,0,0")
        return raw

    def test_native_query_and_capability_keep_diagnostic_available(self):
        for phase in (1, 2):
            request = lua_fixture.control(phase=phase)
            response = lua_fixture.control(phase=phase, data=bytes(64))
            script = self.fixture() + self.command(request) + self.response(response)
            script += '''
local capability,replied=false,false
for _,p in ipairs(decoded()) do
 if p=="W"..string.pack("<I2I2I2I2",2,512,240,192) then capability=true end
 if p:sub(1,1)=="E" then replied=true end
end
assert(capability and replied and not stopped)
'''
            self.run_lua(script)

    def test_party_second_chunk_has_exact_72_bytes_and_only_mailbox_writes(self):
        read = lua_fixture.control(4, phase=2, block=1, offset=128, size=200, kind=4)
        response = lua_fixture.control(4, phase=2, block=1, offset=128, size=200, kind=4, data=bytes(72))
        script = self.fixture() + self.command(read) + self.response(response)
        script += '''
local replied=false
for _,p in ipairs(decoded()) do if p:sub(1,1)=="E" then replied=true end end
assert(replied and not stopped)
for _,a in ipairs(writes) do
 assert((a>=0x02001024 and a<=0x0200107c) or (a>=0x02003018 and a<=0x02003108))
end
'''
        self.run_lua(script)
        wrong = lua_fixture.control(4, phase=2, block=1, offset=128, size=200, kind=4, data=bytes(73))
        self.run_lua(self.fixture() + self.command(read) + self.response(wrong) + 'assert(stopped)\n')

    def test_native_forbidden_phase_kind_offset_mask_and_abi_never_write(self):
        cases = ((1, lua_fixture.control(phase=2)),
            (2, lua_fixture.control(phase=3)),
            (2, lua_fixture.control(3, phase=2, data=bytes(4))),
            (2, lua_fixture.control(8, phase=2)),
            (2, lua_fixture.control(phase=2, source=2)),
            (2, lua_fixture.control(6, phase=2, block=1, offset=1, size=200, kind=4, source=1, data=bytes(128))),
            (2, lua_fixture.control(6, phase=2, block=1, size=40, kind=1, source=1, data=bytes(40))),
            (2, lua_fixture.control(5, phase=2, block=1, offset=200, size=200, kind=4, data=struct.pack("<II", 0, 3))))
        for abi, request in cases:
            with self.subTest(abi=abi, request=request[:48]):
                self.run_lua(self.fixture(abi) + self.command(request) + '''
assert(stopped and closes==1)
assert(range(0x02003018,244)==string.rep("\\0",244))
''')


class NativeCompanionTests(unittest.IsolatedAsyncioTestCase):
    abi_version = 2
    asyncSetUp = socket_fixture.CompanionBattleTests.asyncSetUp
    asyncTearDown = socket_fixture.CompanionBattleTests.asyncTearDown
    task = socket_fixture.CompanionBattleTests.task

    def query(self):
        return NativeControl(self.c.battle_incarnation, self.c.session_epoch,
                             str(uuid4()), 1, Opcode.QUERY)

    async def next_command(self):
        async with asyncio.timeout(3):
            while True:
                packet = await read_packet(self.bridge.reader)
                if packet[:1] == b"D":
                    return NativeControl.unpack(packet[1:]).validate_command()
                self.assertEqual(packet[:1], b"S")

    async def reply(self, response):
        self.bridge.writer.write(encode_packet(b"E"+response.pack()))
        await self.bridge.writer.drain()

    async def test_native_query_and_party_chunk_use_correlated_socket(self):
        for request, data in ((self.query(), bytes(64)),
                (replace(self.query(), opcode=Opcode.READ_OUT, kind=Kind.PARTY_0,
                         block_sequence=1, total_size=200, offset=128), bytes(72))):
            task = self.task(request)
            self.assertEqual(await self.next_command(), request)
            response = replace(request, data=data)
            await self.reply(response)
            self.assertEqual(await task, response)
        self.assertFalse(self.c._battle_pending)

    async def test_optin_identity_and_lifecycle_guard_native_commands(self):
        disabled = Companion(replace(self.config, development_battle_channel=False))
        with self.assertRaises(ValueError):
            await disabled.battle_rpc(self.query())
        request = self.query()
        roster = NativeBinding(str(uuid4()), (str(uuid4()), str(uuid4())),
            (request.session_epoch, 5), (request.incarnation, 9), 0)
        with self.assertRaises(ValueError):
            await self.c.battle_rpc(replace(request, opcode=Opcode.BIND, data=roster.pack()))
        self.c._live_save_owner = object()
        try:
            with self.assertRaises(ValueError):
                await self.c.battle_rpc(replace(request, opcode=Opcode.START))
        finally:
            self.c._live_save_owner = None
        self.assertFalse(self.c._battle_pending)

    async def test_wrong_native_read_length_closes_bridge_without_success(self):
        request = replace(self.query(), opcode=Opcode.READ_OUT, kind=Kind.PARTY_0,
                          block_sequence=1, total_size=200, offset=128)
        task = self.task(request)
        await self.next_command()
        await self.reply(replace(request, data=bytes(73)))
        with self.assertRaises(ConnectionError):
            await task
        await wait_until(lambda: self.c._bridge is None)

    async def test_capability_downgrade_is_refused(self):
        self.bridge.writer.write(encode_packet(capability_packet(1)))
        await self.bridge.writer.drain()
        await wait_until(lambda: self.c._bridge is None)
        self.assertFalse(self.c._battle_pending)
