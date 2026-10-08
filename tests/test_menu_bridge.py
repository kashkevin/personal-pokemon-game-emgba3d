import struct
import unittest

from emerald_multiplayer.bridge_protocol import encode_packet
from emerald_multiplayer.menu_mailbox import MenuRequest, pack_screen
from emerald_multiplayer.player_menu import MenuRow, MenuScreen
import test_live_bridge as fixtures


class MenuBridgeTests(unittest.TestCase):
    lua_path = staticmethod(fixtures.LuaBridgeTests.lua_path)
    run_lua = fixtures.LuaBridgeTests.run_lua

    def fixture(self, enabled=True):
        script = fixtures.LuaBridgeTests.fixture(self, live=True, trade=True)
        script = script.replace("or address==0x02002018",
            "or address==0x02003020 or (address>=0x02003024 and address<=0x02003110) or address==0x02002018", 1)
        if enabled:
            setup = '''
EMERALD_BRIDGE.menu_abi=1;EMERALD_BRIDGE.menu_abi_address=0x080000c8
EMERALD_BRIDGE.menu_address=0x02003000;EMERALD_BRIDGE.menu_size=512
loadBytes(0x080000c8,string.pack("<I4",1))
loadBytes(0x02003000,string.pack("<I4I2I2I4I4",0x31554D45,1,512,1,0)..string.rep("\\0",496))
'''
            script = script.replace("local cfg = assert", setup + "\nlocal cfg = assert", 1)
        return script

    def request(self, seq=1, screen=0, action=0, kind=1):
        payload = MenuRequest(seq, screen, action, kind).pack()
        return f'loadBytes(0x02003010,unhex("{payload.hex()}"));loadBytes(0x0200300c,string.pack("<I4",{seq*2}));advance(100)\n'

    def response(self, ack=1):
        return pack_screen(ack, MenuScreen(3, "Players", "Connected: 4/4", (MenuRow(1, "Invite"),), 0))

    def command(self, payload):
        return f'inbox=unhex("{encode_packet(b"M" + payload).hex()}");advance(100)\n'

    def test_request_capability_response_atomic_write_and_presence(self):
        response = self.response()
        script = self.fixture() + self.request() + self.command(response)
        script += f'''
local capability,request,poses=false,false,0
for _,p in ipairs(decoded()) do
 if p=="I"..string.pack("<I2I2I2I2",1,512,240,16) then capability=true end
 if p==unhex("{(b'J'+MenuRequest(1,0,0,1).pack()).hex()}") then request=true end
 if p:sub(1,1)=="P" then poses=poses+1 end
end
assert(capability and request and poses>0 and #console.errors==0)
assert(range(0x02003024,240)==unhex("{response.hex()}"))
assert(writes[1]==0x02003020 and writes[62]==0x02003020)
assert(emu:read32(0x02003020)%2==0)
'''
        self.run_lua(script)

    def test_stale_screen_is_ignored_after_local_close(self):
        self.run_lua(self.fixture() + self.request() + self.request(2, 3, 0, 3)
            + self.command(self.response()) + '''
assert(range(0x02003020,244)==string.rep("\\0",244))
assert(not stopped and #console.errors==0)
''')

    def test_malformed_or_unsupported_screen_never_writes(self):
        valid = self.response()
        bad = bytearray(valid); bad[12] = 255
        for enabled, payload in ((False, valid), (True, bytes(bad)), (True, valid[:-1] + b"\1")):
            with self.subTest(enabled=enabled):
                self.run_lua(self.fixture(enabled) + (self.request() if enabled else "") + self.command(payload) + '''
assert(stopped and closes==1 and #console.errors==1)
assert(range(0x02003020,244)==string.rep("\\0",244))
''')

    def test_each_selection_forwarded_only_once_and_regression_rejected(self):
        self.run_lua(self.fixture() + self.request() + self.request(2, 3, 1, 2) + '''
advance(100)
local count=0;for _,p in ipairs(decoded()) do if p:sub(1,1)=="J" then count=count+1 end end
assert(count==2 and not stopped)
''' + self.request() + 'assert(stopped and closes==1)\n')

    def test_runtime_reset_fences_menu_without_touching_game_memory(self):
        self.run_lua(self.fixture() + self.request() + '''
loadBytes(0x02003008,string.pack("<I4",0));advance(1)
assert(closes==1)
assert(range(0x02003020,244)==string.rep("\\0",244))
''')
