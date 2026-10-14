"""Real Lua diagnostic channel checks with bounded fake memory and sockets."""
import struct
import unittest
from uuid import UUID
import zlib

from emerald_multiplayer.bridge_protocol import encode_packet
import test_live_bridge as fixtures


def control(opcode=2, *, seq=1, epoch=7, block=0, offset=0, size=0, source=0, kind=0,
            status=0, phase=1, data=b""):
    return struct.pack("<II16sIIHHBBBBBBHI192s", 1, epoch, UUID(int=1).bytes, seq, block,
                       offset, size, opcode, status, phase, source, kind, 0,
                       len(data), zlib.crc32(data), data.ljust(192, b"\0"))


class BattleBridgeTests(unittest.TestCase):
    lua_path = staticmethod(fixtures.LuaBridgeTests.lua_path)
    run_lua = fixtures.LuaBridgeTests.run_lua

    def fixture(self, enabled=True):
        script = fixtures.LuaBridgeTests.fixture(self, live=True, trade=True)
        script = script.replace("or address==0x02002018", "or address==0x02003018 or (address>=0x0200301c and address<=0x02003108) or address==0x02002018", 1)
        if enabled:
            setup = '''
EMERALD_BRIDGE.battle_abi=1;EMERALD_BRIDGE.battle_abi_address=0x080000c8
EMERALD_BRIDGE.battle_address=0x02003000;EMERALD_BRIDGE.battle_size=512
loadBytes(0x080000c8,string.pack("<I4",1))
loadBytes(0x02003000,string.pack("<I4I2I2I4I4I4I4",0x31424D45,1,512,1,0,0,0)..string.rep("\\0",488))
'''
            script = script.replace("local cfg = assert", setup + "\nlocal cfg = assert", 1)
        return script

    def command(self, payload):
        return f'inbox=unhex("{encode_packet(b"D" + payload).hex()}");advance(80)\n'

    def response(self, payload, generation=2):
        return (f'loadBytes(0x02003110,unhex("{payload.hex()}"));'
                f'loadBytes(0x0200310c,string.pack("<I4",{generation}));advance(160)\n')

    def test_capability_atomic_command_response_and_presence(self):
        query, response = control(), control(data=bytes(64))
        script = self.fixture() + self.command(query)
        script += f'assert(range(0x0200301c,240)==unhex("{query.hex()}"))\n'
        script += self.response(response)
        script += f'''
local capability,replied,poses=false,false,0
for _,p in ipairs(decoded()) do
    if p=="W"..string.pack("<I2I2I2I2",1,512,240,192) then capability=true end
    if p==unhex("{(b'E'+response).hex()}") then replied=true end
    if p:sub(1,1)=="P" then poses=poses+1 end
end
assert(capability and replied and poses>0 and #console.errors==0)
assert(writes[1]==0x02003018 and writes[62]==0x02003018)
assert(emu:read32(0x02003018)%2==0)
'''
        self.run_lua(script)

    def test_absent_capability_and_malformed_commands_never_reach_channel(self):
        valid = control()
        for enabled, payload in ((False, valid), (True, control(phase=2)),
                                 (True, valid[:-1] + b"\x01"), (True, control(data=b"x")),
                                 (True, control(opcode=6, block=1, size=40, kind=1, source=1, data=bytes(40)))):
            with self.subTest(enabled=enabled, payload=payload[:48].hex()):
                self.run_lua(self.fixture(enabled) + self.command(payload) + '''
assert(closes==1 and stopped and #console.errors==1)
assert(range(0x02003018,244)==string.rep("\\0",244))
''')

    def native_fixture(self):
        """The native battle ABI 3 (singles, full Multi, co-op Gym)."""
        script = self.fixture()
        script = script.replace("EMERALD_BRIDGE.battle_abi=1;", "EMERALD_BRIDGE.battle_abi=3;", 1)
        script = script.replace('loadBytes(0x080000c8,string.pack("<I4",1))', 'loadBytes(0x080000c8,string.pack("<I4",3))', 1)
        return script.replace('string.pack("<I4I2I2I4I4I4I4",0x31424D45,1,512', 'string.pack("<I4I2I2I4I4I4I4",0x31424D45,3,512', 1)

    def test_native_phases_reach_the_channel_co_op_included(self):
        # Co-op Gym battles (native phase 4, two cores) were refused here, so
        # no co-op battle could start (combined game audit, 2026-10-13).
        for phase in (2, 3, 4):
            payload = control(phase=phase)
            with self.subTest(phase=phase):
                self.run_lua(self.native_fixture() + self.command(payload) + f'''
assert(range(0x0200301c,240)==unhex("{payload.hex()}"))
assert(closes==0 and #console.errors==0)
''')
        self.run_lua(self.native_fixture() + self.command(control(phase=5)) + '''
assert(closes==1 and stopped)
''')

    def test_stale_response_is_ignored_then_correlated_reply_is_forwarded(self):
        script = self.fixture() + self.command(control())
        script += self.response(control(epoch=6, data=bytes(64)))
        script += 'for _,p in ipairs(decoded()) do assert(p:sub(1,1)~="E") end\n'
        script += self.response(control(data=bytes(64)), 4)
        script += 'local seen=false;for _,p in ipairs(decoded()) do if p:sub(1,1)=="E" then seen=true end end;assert(seen and not stopped)\n'
        self.run_lua(script)

    def test_query_can_observe_uncertain_emit_but_other_commands_cannot_replace_it(self):
        emit = control(3, data=struct.pack("<I", 123))
        query = control(2, seq=2)
        self.run_lua(self.fixture() + self.command(emit) + self.command(query)
                     + f'assert(range(0x0200301c,240)==unhex("{query.hex()}"));assert(not stopped)\n')
        self.run_lua(self.fixture() + self.command(emit) + self.command(control(8, seq=2))
                     + 'assert(stopped and closes==1)\n')

    def test_typed_remote_frame_and_diagnostic_read_have_exact_bounds(self):
        frame = struct.pack("<II16sIIII", 0x44424D45, 1, UUID(int=2).bytes, 1, 987, 8, 2)
        receive = control(6, block=1, size=40, source=1, kind=1, data=frame)
        self.run_lua(self.fixture() + self.command(receive)
                     + f'assert(range(0x0200301c,240)==unhex("{receive.hex()}"));assert(not stopped)\n')
        read = control(4, block=1, size=40, kind=1)
        local_frame = struct.pack("<II16sIIII", 0x44424D45, 1, UUID(int=2).bytes, 0, 987, 7, 1)
        reply = control(4, block=1, size=40, kind=1, data=local_frame)
        self.run_lua(self.fixture() + self.command(read) + self.response(reply)
                     + 'local seen=false;for _,p in ipairs(decoded()) do if p:sub(1,1)=="E" then seen=true end end;assert(seen and not stopped)\n')

    def test_battle_counter_reset_reincarnates_without_writing_an_abort(self):
        self.run_lua(self.fixture() + '''
loadBytes(0x02003008,string.pack("<I4",500));advance(80)
local before=#writes
loadBytes(0x02003008,string.pack("<I4",1));advance(1)
assert(closes==1 and not stopped and #console.errors==1)
for i=before+1,#writes do assert(writes[i]>=0x02001024 and writes[i]<=0x0200107c) end
advance(240);assert(connects==2)
''')
