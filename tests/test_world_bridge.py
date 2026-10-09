"""Real Lua bridge: the EMW1 shared-world mailbox path (mocked core/socket)."""
from __future__ import annotations

import struct
import unittest

from emerald_multiplayer.bridge_protocol import encode_packet
from emerald_multiplayer.world_mailbox import (
    ACTION_WALLET, WorldAction, WorldEventView, WorldInbound, WorldState,
)
from test_live_bridge import LuaBridgeTests

WORLD = 0x02003000
LOOK = bytes((1, 2, 3, 4, 5, 6, 7, 0))
WORLD_CONFIG = (
    f"EMERALD_BRIDGE.world_address={WORLD};EMERALD_BRIDGE.world_abi=1;EMERALD_BRIDGE.world_size=256;"
    "EMERALD_BRIDGE.world_abi_address=0x080000d0;loadBytes(0x080000d0,string.pack('<I4',1))\n"
)
OLD_ASSERT = '''    assert((address>=0x02001024 and address<=0x0200107c)
        or address==0x02002018 or (address>=0x0200201c and address<=0x02002108),
        "write outside allocated inbound/command slots")'''
NEW_ASSERT = '''    assert((address>=0x02001024 and address<=0x0200107c)
        or address==0x02002018 or (address>=0x0200201c and address<=0x02002108)
        or (address>=0x0200302c and address<=0x020030fc),
        "write outside allocated inbound/command slots")'''


def header(generation=0, state=WorldState(25, 4, 0, 0, 0, LOOK, 3), action=WorldAction()):
    raw_state = struct.pack("<HBBHBB8s", state.follower_species, state.follower_flags, state.mount_state,
                            state.mount_species, state.mount_flags, state.wallet_seq, state.appearance)
    return struct.pack("<IHHI", 0x31574D45, 1, 256, generation) + raw_state + action.pack()


class LuaWorldBridgeTests(unittest.TestCase):
    lua_path = staticmethod(LuaBridgeTests.lua_path)
    run_lua = LuaBridgeTests.run_lua
    fixture = LuaBridgeTests.fixture

    def world_fixture(self):
        script = self.fixture(live=False)
        assert script.count(OLD_ASSERT) == 1
        script = script.replace(OLD_ASSERT, NEW_ASSERT)
        anchor = 'EMERALD_BRIDGE={address=0x02001000,rom_size=1024,rom_crc32="aabbccdd",port=8870,token=string.rep("a",64)}\n'
        assert script.count(anchor) == 1
        return script.replace(anchor, anchor + WORLD_CONFIG)

    def inbound(self, **changes):
        peer = WorldState(6, 4, 0, 0, 0, LOOK)
        values = dict(clock_valid=True, events_enabled=True, world_seconds=86_400, action_ack=2,
                      self_appearance=LOOK, peers=((2, peer),),
                      event=WorldEventView(5, 359, 20, 2, 0, 16, 9, 9, 0, 900, 1),
                      notice_id=4, notice_text="WORLD EVENT! ABSOL|near ROUTE 101", wallet_seq=3,
                      wallet_delta=-5000, teammate_token=2)
        values.update(changes)
        return WorldInbound(**values).pack()

    def test_local_record_is_published_and_valid_inbound_is_committed(self):
        action = WorldAction(7, ACTION_WALLET, 2, 0, 3, 5000)
        payload = self.inbound()
        script = self.world_fixture()
        script += f'loadBytes({WORLD},unhex("{header(4, action=action).hex()}"))\n'
        script += f'inbox=unhex("{encode_packet(b"N" + payload).hex()}")\n'
        script += 'advance(80)\n'
        script += f'local expected=unhex("{(b"G" + header(4, action=action)[12:44]).hex()}")\n'
        script += r'''
local found=0
for _,p in ipairs(decoded()) do if p==expected then found=found+1 end end
assert(found>0, "no shared-world local record")
assert(#console.errors==0, console.errors[1])
'''
        script += f'assert(range({WORLD + 48},208)==unhex("{payload.hex()}"), "inbound not committed")\n'
        script += f'assert(emu:read32({WORLD + 44})%2==0 and emu:read32({WORLD + 44})>0, "inbound generation")\n'
        self.run_lua(script)

    def test_odd_local_generation_is_never_published(self):
        script = self.world_fixture()
        script += f'loadBytes({WORLD},unhex("{header(5).hex()}"))\nadvance(80)\n'
        script += 'for _,p in ipairs(decoded()) do assert(p:sub(1,1)~="G", "torn local record published") end\n'
        self.run_lua(script)

    def test_invalid_inbound_fences_the_bridge_without_writing(self):
        good = self.inbound()
        bad = {
            "wallet_without_delta": good[:180] + struct.pack("<IiI", 1, 0, 2) + bytes(16),
            "unknown_teammate": good[:180] + struct.pack("<IiI", 3, -5000, 3) + bytes(16),
            "delta_too_large": good[:180] + struct.pack("<IiI", 3, 1_000_000, 2) + bytes(16),
            "reserved_tail": good[:192] + b"\x01" + bytes(15),
            "notice_control_char": good[:116] + b"\x07" + good[117:],
            "event_level": good[:86] + bytes((101,)) + good[87:],
            "short": good[:207],
        }
        for name, payload in bad.items():
            with self.subTest(name=name):
                script = self.world_fixture()
                script += f'loadBytes({WORLD},unhex("{header(4).hex()}"))\n'
                script += f'inbox=unhex("{encode_packet(b"N" + payload).hex()}")\nadvance(80)\n'
                script += f'assert(stopped and #console.errors>=1, "invalid inbound accepted")\n'
                script += f'assert(range({WORLD + 48},208)==string.rep("\\0",208), "invalid inbound written")\n'
                self.run_lua(script)

    def test_world_update_without_capability_is_refused(self):
        script = self.fixture(live=False)
        script += f'inbox=unhex("{encode_packet(b"N" + self.inbound()).hex()}")\nadvance(80)\n'
        script += 'assert(stopped and #console.errors>=1)\n'
        self.run_lua(script)


class OutboxFairnessTests(unittest.IsolatedAsyncioTestCase):
    async def test_presence_and_world_alternate_and_controls_yield(self):
        from emerald_multiplayer.bridge_protocol import BridgeOutbox
        queue = BridgeOutbox()
        for index in range(3):
            queue.put_control(b"C" + bytes([index]))
        queue.put(b"S1")
        queue.put_world(b"N1")
        order = [await queue.get() for _ in range(5)]
        self.assertEqual(order, [encode_packet(p) for p in (b"C\0", b"C\1", b"S1", b"C\2", b"N1")])
        # Both streams always refreshed (a busy link): output alternates.
        kinds = []
        for index in range(8):
            queue.put(b"S" + bytes([index]))
            queue.put_world(b"N" + bytes([index]))
            kinds.append((await queue.get())[4:5])
        self.assertEqual(kinds, [b"S", b"N"] * 4)


if __name__ == "__main__":
    unittest.main()
