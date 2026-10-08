from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

from emerald_multiplayer.bridge_protocol import (
    BridgeBackpressure, BridgeError, BridgeOutbox, encode_packet, read_packet,
)
from emerald_multiplayer.mailbox import MAILBOX_MAGIC, Pose, Snapshot
from emerald_multiplayer.save_mailbox import Opcode, SaveControl, capability_packet, command_packet, response_packet
from test_save_mailbox import control


class BridgeOutboxTests(unittest.IsolatedAsyncioTestCase):
    async def test_fifo_bounded_controls_latest_presence_and_fairness(self):
        queue = BridgeOutbox()
        for index in range(4):
            queue.put_control(b"C" + bytes([index]))
        with self.assertRaises(BridgeBackpressure):
            queue.put_control(b"Coverflow")
        for index in range(100):
            queue.put(b"S" + bytes([index]))
        expected = [b"C\0", b"C\1", b"S\x63", b"C\2", b"C\3"]
        self.assertEqual([await queue.get() for _ in range(5)], [encode_packet(p) for p in expected])
        pending = asyncio.create_task(queue.get())
        await asyncio.sleep(0)
        queue.close()
        self.assertIsNone(await pending)
        with self.assertRaises(BridgeError):
            queue.put_control(b"Cclosed")

    async def test_real_tcp_fragmented_save_controls_and_presence_share_frame_bound(self):
        command = command_packet(control(opcode=Opcode.WRITE, data=bytes(range(128))))
        response = response_packet(control(opcode=Opcode.WRITE, offset=128))
        snapshot = b"S" + Snapshot().pack()
        finished = asyncio.Event()

        async def handler(reader, writer):
            try:
                self.assertEqual(await read_packet(reader), command)
                queue = BridgeOutbox()
                queue.put_control(response)
                queue.put(snapshot)
                for _ in range(2):
                    frame = await queue.get()
                    for offset in range(0, len(frame), 11):
                        writer.write(frame[offset:offset + 11])
                        await writer.drain()
                        await asyncio.sleep(0)
            finally:
                writer.close()
                await writer.wait_closed()
                finished.set()

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        reader, writer = await asyncio.open_connection("127.0.0.1", server.sockets[0].getsockname()[1])
        try:
            frame = encode_packet(command)
            self.assertEqual(len(frame), 245)
            for offset in range(0, len(frame), 13):
                writer.write(frame[offset:offset + 13])
                await writer.drain()
                await asyncio.sleep(0)
            self.assertEqual(await read_packet(reader), response)
            self.assertEqual(await read_packet(reader), snapshot)
            self.assertIsNone(await read_packet(reader))
            await asyncio.wait_for(finished.wait(), 1)
        finally:
            writer.close()
            await writer.wait_closed()
            server.close()
            await server.wait_closed()


class LuaBridgeTests(unittest.TestCase):
    """Execute real Lua against a transport-only fake emulator/socket API."""

    @staticmethod
    def lua_path(path):
        path = Path(path).resolve()
        if os.name == "nt":
            return "/mnt/" + path.drive[0].lower() + path.as_posix()[2:]
        return str(path)

    def run_lua(self, script):
        executable = shutil.which("lua") or shutil.which("lua5.4")
        prefix = [executable] if executable else ([shutil.which("wsl"), "-d", "Ubuntu", "--", "lua"] if os.name == "nt" and shutil.which("wsl") else None)
        if prefix is None:
            self.skipTest("Lua 5.3+ is unavailable; pure Python bridge tests still run")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge-test.lua"
            path.write_text(script, encoding="utf-8")
            result = subprocess.run(prefix + [self.lua_path(path)], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def fixture(self, *, live, trade=False, emergency=False):
        local = Pose(0, 1, 6, 11, 0, 9, 1, 0, 0, 0, 1)
        presence = struct.pack("<IHHII", MAILBOX_MAGIC, 1, 128, 1, 2) + local.pack() + bytes(92)
        save = struct.pack("<IHHIIII", 0x31534D45, 1, 512, 1, 1, 0, 0) + bytes(488)
        return r'''
local memory, writes = {}, {}
local function unhex(value)
    return (value:gsub("..", function(pair) return string.char(tonumber(pair,16)) end))
end
local function loadBytes(address,data)
    for i=1,#data do memory[address+i-1]=data:byte(i) end
end
local function range(address,size)
    local values={}
    for i=0,size-1 do values[#values+1]=string.char(memory[address+i] or 0) end
    return table.concat(values)
end
emu={}
function emu:read32(address) return string.unpack("<I4",range(address,4)) end
function emu:read16(address) return string.unpack("<I2",range(address,2)) end
function emu:readRange(address,size) return range(address,size) end
function emu:write32(address,value,...)
    assert(select("#",...)==0,"extra write arguments")
    assert((address>=0x02001024 and address<=0x0200107c)
        or address==0x02002018 or (address>=0x0200201c and address<=0x02002108),
        "write outside allocated inbound/command slots")
    writes[#writes+1]=address
    loadBytes(address,string.pack("<I4",value))
end
function emu:romSize() return 1024 end
function emu:checksum() return unhex("aabbccdd") end
callbacks={list={}}
function callbacks:add(event,fn) self.list[event]=fn end
console={errors={}}
function console:log(value) end
function console:error(value) self.errors[#self.errors+1]=value end
local wire,inbox,sendCalls,connects,closes="","",0,0,0
local closedWires={}
local endpoint={}
function endpoint:hasdata() return #inbox>0 end
function endpoint:receive(max)
    local count=math.min(max,17,#inbox)
    local data=inbox:sub(1,count);inbox=inbox:sub(count+1);return data
end
function endpoint:send(data)
    sendCalls=sendCalls+1
    if sendCalls%3==0 then return nil,99 end
    local count=math.min(7,#data);wire=wire..data:sub(1,count);return count
end
function endpoint:close()
    closes=closes+1;closedWires[#closedWires+1]=wire;wire="";inbox=""
end
socket={ERRORS={AGAIN=99}}
function socket.connect(host,port) assert(host=="127.0.0.1");connects=connects+1;return endpoint end
EMERALD_BRIDGE={address=0x02001000,rom_size=1024,rom_crc32="aabbccdd",port=8870,token=string.rep("a",64)}
''' + ("EMERALD_BRIDGE.save_address=0x02002000;EMERALD_BRIDGE.save_size=512;EMERALD_BRIDGE.save_abi=1\n" if live else "") + ("EMERALD_BRIDGE.trade_abi=1;EMERALD_BRIDGE.trade_abi_address=0x080000c4;loadBytes(0x080000c4,string.pack('<I4',1))\n" if trade else "") + ("EMERALD_BRIDGE.emergency_save_abi=1;EMERALD_BRIDGE.emergency_save_abi_address=0x080000c8;loadBytes(0x080000c8,string.pack('<I4',1))\n" if emergency else "") + f'loadBytes(0x02001000,unhex("{presence.hex()}"))\nloadBytes(0x02002000,unhex("{save.hex()}"))\n' + Path(__file__).parents[1].joinpath("bridge/mgba.lua").read_text() + r'''
local function advance(count) for _=1,count do callbacks.list.frame() end end
local function packet(payload) return string.pack(">I4",#payload)..payload end
local function romFrames(presence,save)
    loadBytes(0x02001008,string.pack("<I4",presence))
    loadBytes(0x02001014,string.pack("<I4",presence))
    loadBytes(0x02002008,string.pack("<I4",save or presence))
end
local function decoded()
    local result,offset={},1
    while offset+3<=#wire do
        local size=string.unpack(">I4",wire,offset)
        assert(size>=1 and size<=256)
        if offset+3+size>#wire then break end
        result[#result+1]=wire:sub(offset+4,offset+3+size);offset=offset+4+size
    end
    assert(#wire-offset+1<=260,"unbounded partial frame")
    return result
end
'''

    def test_legacy_presence_unchanged_and_no_save_capability(self):
        snapshot = b"S" + Snapshot(1, 1, 1).pack()
        self.run_lua(self.fixture(live=False) + f'inbox=unhex("{encode_packet(snapshot).hex()}")\n' + r'''
advance(80)
assert(emu:read32(0x02001028)==1)
local packets=decoded();assert(packets[1]=="H"..unhex(string.rep("a",64)))
local poses=0
for _,p in ipairs(packets) do assert(p:sub(1,1)~="V" and p:sub(1,1)~="R");if p:sub(1,1)=="P" then poses=poses+1 end end
assert(poses>0 and #console.errors==0)
''')

    def test_trade_hold_queries_and_rebind_are_capability_gated(self):
        for enabled in (False, True):
            query = control(opcode=Opcode.QUERY_TRADE, sequence=2)
            script = self.fixture(live=True, trade=enabled)
            script += f'inbox=unhex("{encode_packet(command_packet(query)).hex()}");advance(80)\n'
            if enabled:
                script += f'assert(range(0x0200201c,240)==unhex("{query.pack().hex()}"))\n'
                response = replace(query, data=struct.pack("<II16sIIIIII", 1, 8,
                    bytes.fromhex(query.request_id.replace("-", "")), 7, 1, 3, 131072, 12, 60))
                script += f'loadBytes(0x0200200c,string.pack("<I4",8));loadBytes(0x02002110,unhex("{response.pack().hex()}"));loadBytes(0x0200210c,string.pack("<I4",2));advance(160)\n'
                script += f'local found=false;for _,p in ipairs(decoded()) do if p==unhex("{response_packet(response).hex()}") then found=true end end;assert(found and #console.errors==0)\n'
                rebind = control(opcode=Opcode.REBIND_TRADE, session_epoch=8)
                script += f'inbox=unhex("{encode_packet(command_packet(rebind)).hex()}");advance(80);assert(range(0x0200201c,240)==unhex("{rebind.pack().hex()}"))\n'
            else:
                script += 'assert(#console.errors==1 and range(0x0200201c,240)==string.rep("\\0",240))\n'
            self.run_lua(script)

    def test_trade_recovery_can_replace_an_unacknowledged_control_without_releasing_hold(self):
        begin = control(opcode=Opcode.BEGIN_TRADE_EXPORT, revision=2, sequence=2)
        query = replace(begin, opcode=Opcode.QUERY_TRADE, session_epoch=8, sequence=1, revision=0)
        rebind = replace(query, opcode=Opcode.REBIND_TRADE, revision=2)
        script = self.fixture(live=True, trade=True)
        for command in (begin, query, rebind):
            script += f'inbox=unhex("{encode_packet(command_packet(command)).hex()}");advance(80)\n'
            script += f'assert(range(0x0200201c,240)==unhex("{command.pack().hex()}"));assert(#console.errors==0)\n'
        # Delayed old-session ACK must not satisfy the new rebind waiter.
        late = replace(begin, data=bytes(40))
        script += f'loadBytes(0x02002110,unhex("{late.pack().hex()}"));loadBytes(0x0200210c,string.pack("<I4",2));advance(100);assert(savePending~=nil)\n'
        self.run_lua(script)

    def test_live_commands_stale_response_crc_rejection_and_write_limits(self):
        bind = control()
        stale = replace(bind, sequence=99)
        read = replace(bind, sequence=2, opcode=Opcode.READ)
        read_response = replace(read, data=bytes(range(128)))
        broken = bytearray(command_packet(replace(read, sequence=3, opcode=Opcode.WRITE, offset=128, data=bytes(range(128)))))
        broken[60] ^= 1
        script = self.fixture(live=True)
        script += f'inbox=unhex("{encode_packet(command_packet(bind)).hex()}")\nadvance(60)\n'
        script += f'assert(range(0x0200201c,240)==unhex("{bind.pack().hex()}"))\n'
        script += f'loadBytes(0x02002110,unhex("{stale.pack().hex()}"));loadBytes(0x0200210c,string.pack("<I4",2));advance(5);assert(savePending~=nil)\n'
        script += f'loadBytes(0x02002110,unhex("{bind.pack().hex()}"));loadBytes(0x0200210c,string.pack("<I4",4));advance(100)\n'
        script += f'inbox=unhex("{encode_packet(command_packet(read)).hex()}");advance(60)\n'
        script += f'loadBytes(0x02002110,unhex("{read_response.pack().hex()}"));loadBytes(0x0200210c,string.pack("<I4",6));advance(140)\n'
        script += f'local expectedV=unhex("{capability_packet().hex()}");local expectedR=unhex("{response_packet(read_response).hex()}")\n'
        script += r'''
local packets=decoded();local capabilities,responses,poses=0,0,0
for _,p in ipairs(packets) do
    if p==expectedV then capabilities=capabilities+1 end
    if p==expectedR then responses=responses+1 end
    if p:sub(1,1)=="P" then poses=poses+1 end
end
assert(capabilities==1 and responses==1 and poses>0 and #console.errors==0)
local previous=range(0x0200201c,240);local generation=emu:read32(0x02002018)
'''
        script += f'inbox=unhex("{encode_packet(bytes(broken)).hex()}");advance(80)\n'
        script += r'''
assert(stopped and #console.errors==1)
assert(range(0x0200201c,240)==previous and emu:read32(0x02002018)==generation)
assert(emu:read32(0x02001028)==0)
'''
        self.run_lua(script)

    def test_callbackless_ram_reset_fences_pending_control_and_reconnects(self):
        bind = control()
        new_bind = replace(bind, incarnation=2)
        presence = struct.pack("<IHHII", MAILBOX_MAGIC, 1, 128, 1, 2) + Pose(1, 1, 6, 11, 0, 9, 1, 0, 0, 0, 0).pack() + bytes(92)
        save = struct.pack("<IHHIIII", 0x31534D45, 1, 512, 1, 0, 0, 0) + bytes(488)
        script = self.fixture(live=True) + "romFrames(500)\n"
        script += f'inbox=unhex("{encode_packet(command_packet(bind)).hex()}");advance(80)\n'
        script += r'''
assert(connects==1 and closes==0 and savePending~=nil)
loadBytes(0x02001000,string.rep("\0",128));loadBytes(0x02002000,string.rep("\0",512))
advance(1) -- BIOS reset does not call callbacks.list.reset().
assert(closes==1 and not stopped and verified and #console.errors==1)
assert(savePending==nil and saveGeneration==nil and not capabilitySent)
assert(#controls==0 and #rx==0 and #tx==0 and latestPose==nil)
'''
        script += f'loadBytes(0x02001000,unhex("{presence.hex()}"));loadBytes(0x02002000,unhex("{save.hex()}"))\n'
        script += r'''
advance(119);assert(connects==1)
advance(1);assert(connects==2)
advance(120)
assert(range(0x0200201c,240)==string.rep("\0",240) and emu:read32(0x02002018)==0)
local packets=decoded();local hello,capabilities=0,0
for _,p in ipairs(packets) do
    if p:sub(1,1)=="H" then hello=hello+1 end
    if p:sub(1,1)=="V" then capabilities=capabilities+1 end
    assert(p:sub(1,1)~="R","old response crossed reconnect")
end
assert(hello==1 and capabilities==1)
'''
        script += f'inbox=unhex("{encode_packet(command_packet(new_bind)).hex()}");advance(60)\n'
        script += f'assert(range(0x0200201c,240)==unhex("{new_bind.pack().hex()}"))\n'
        script += f'loadBytes(0x0200200c,string.pack("<I4",1));loadBytes(0x02002110,unhex("{new_bind.pack().hex()}"));loadBytes(0x0200210c,string.pack("<I4",2));advance(120)\n'
        script += f'local expected=unhex("{response_packet(new_bind).hex()}");local responses=0;for _,p in ipairs(decoded()) do if p==expected then responses=responses+1 end end\n'
        script += 'assert(responses==1 and savePending==nil and connects==2 and closes==1 and not stopped)\n'
        self.run_lua(script)

    def test_ownership_commands_use_only_allocated_mailbox_and_return_full_status(self):
        for opcode, data in ((Opcode.QUERY_OWNERSHIP, b""), (Opcode.GRANT_OWNERSHIP, bytes(range(60)))):
            request = control(opcode=opcode, data=data)
            response = replace(request, data=bytes(range(80)))
            script = self.fixture(live=True)
            script += f'inbox=unhex("{encode_packet(command_packet(request)).hex()}");advance(60)\n'
            script += f'assert(range(0x0200201c,240)==unhex("{request.pack().hex()}"))\n'
            script += f'loadBytes(0x02002110,unhex("{response.pack().hex()}"));loadBytes(0x0200210c,string.pack("<I4",2));advance(140)\n'
            script += f'local expected=unhex("{response_packet(response).hex()}");local count=0;for _,p in ipairs(decoded()) do if p==expected then count=count+1 end end\n'
            script += 'assert(count==1 and savePending==nil and #console.errors==0)\n'
            with self.subTest(opcode=opcode):
                self.run_lua(script)

    def test_valid_frame_regression_reconnects_without_header_gap(self):
        self.run_lua(self.fixture(live=True) + r'''
romFrames(500);advance(80);assert(connects==1 and closes==0)
romFrames(7);advance(1)
assert(closes==1 and not stopped and #console.errors==1)
advance(119);assert(connects==1)
advance(121);assert(connects==2 and closes==1)
assert(decoded()[1]:sub(1,1)=="H")
''')

    def test_save_only_regression_or_zeroed_unbound_state_fences_bridge(self):
        for restart in ("romFrames(500,3)",
                        'loadBytes(0x0200200c,string.pack("<I4",0));loadBytes(0x02002018,string.rep("\\0",488))'):
            with self.subTest(restart=restart):
                self.run_lua(self.fixture(live=True) + "romFrames(500);advance(80)\n" + restart + r'''
advance(1);assert(closes==1 and not stopped and #console.errors==1)
advance(240);assert(connects==2 and closes==1)
''')

    def test_save_mailbox_disappearance_is_detected_before_receiving_commands(self):
        bind = control()
        save = struct.pack("<IHHIIII", 0x31534D45, 1, 512, 2, 0, 0, 0) + bytes(488)
        script = self.fixture(live=True) + "romFrames(500);advance(80)\n"
        script += f'inbox=unhex("{encode_packet(command_packet(bind)).hex()}")\n'
        script += r'''
loadBytes(0x02002000,string.rep("\0",512));advance(1)
assert(closes==1 and not stopped and #console.errors==1)
assert(range(0x02002018,244)==string.rep("\0",244))
'''
        script += f'loadBytes(0x02002000,unhex("{save.hex()}"));advance(240)\n'
        script += 'assert(connects==2 and closes==1 and savePending==nil)\n'
        self.run_lua(script)

    def test_frame_stalls_and_uint32_wrap_do_not_reincarnate(self):
        self.run_lua(self.fixture(live=True) + r'''
romFrames(0xFFFFFFFE);advance(80)
romFrames(0xFFFFFFFF);advance(1)
romFrames(0);advance(1)
romFrames(1);advance(300)
assert(connects==1 and closes==0 and #console.errors==0 and not stopped)
''')

    def test_unstable_or_invalid_pose_is_not_reset_evidence(self):
        self.run_lua(self.fixture(live=False) + r'''
romFrames(500);advance(80)
romFrames(1);loadBytes(0x0200100c,string.pack("<I4",3));advance(10)
assert(connects==1 and closes==0)
loadBytes(0x0200100c,string.pack("<I4",4));loadBytes(0x02001023,"\xff");advance(10)
assert(connects==1 and closes==0)
romFrames(500);loadBytes(0x02001023,"\0");advance(80)
assert(connects==1 and closes==0 and #console.errors==0)
''')

    def test_explicit_mgba_reset_callback_forgets_old_runtime_counters(self):
        self.run_lua(self.fixture(live=True) + r'''
romFrames(500);advance(80)
callbacks.list.reset();romFrames(1);loadBytes(0x0200200c,string.pack("<I4",0));advance(100)
assert(connects==2 and closes==1 and #console.errors==0 and not stopped)
''')


if __name__ == "__main__":
    unittest.main()
