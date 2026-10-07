-- Transport and memory-boundary regression tests. Real Lua, mocked core/socket.
-- Actual emulated-ROM integration is a separate test and must also pass.
local bridge = assert(arg[1], "Path to bridge/mgba.lua required")
local address = 0x02001000
local pose = string.pack("<I4I4i2i2BBBBBBBB", 1, 10, 5, 7, 0, 9, 1, 3, 0, 0, 1, 0)
local function fresh(crc)
    local env = {memory={}, writes={}, received={}, sent="", errors={}, callback={}}
    EMERALD_BRIDGE = {address=address, rom_size=33554432, rom_crc32="12345678",
        port=23456, token=string.rep("ab", 32)}
    emu = {
        romSize=function() return 33554432 end,
        checksum=function() return crc or string.char(0x12, 0x34, 0x56, 0x78) end,
        read32=function(_, where) return env.memory[where] or 0 end,
        read16=function(_, where) return env.memory[where] or 0 end,
        readRange=function(_, where, size)
            assert(where == address + 16 and size == 20)
            return pose
        end,
        write32=function(_, where, value, ...)
            assert(select("#", ...) == 0, "Unexpected extra core argument")
            assert(where % 4 == 0 and where >= address + 36 and where <= address + 124,
                "Write escaped inbound mailbox")
            env.memory[where] = value
            env.writes[#env.writes + 1] = {where, value}
        end,
    }
    callbacks = {add=function(_, event, fn) env.callback[event]=fn end}
    console = {log=function() end, error=function(_, err) env.errors[#env.errors+1]=err end}
    local transport = {
        close=function() env.closed = true end,
        send=function(_, bytes)
            if env.again then env.again=false; return nil, "again" end
            local n = math.min(#bytes, 3)
            env.sent = env.sent .. bytes:sub(1, n)
            return n
        end,
        hasdata=function() return #env.received > 0 end,
        receive=function(_, max)
            local bytes = table.remove(env.received, 1)
            if bytes then assert(#bytes <= max); return bytes end
            return nil, "again"
        end,
    }
    socket = {ERRORS={AGAIN="again"}, connect=function(host, port)
        assert(host == "127.0.0.1" and port == 23456)
        env.connected=true; return transport
    end}
    env.ready=function()
        env.memory[address]=0x31504D45; env.memory[address+4]=1; env.memory[address+6]=128
    end
    env.step=function(n) for _=1,n do env.callback.frame() end end
    env.feed=function(bytes, chunk)
        for i=1,#bytes,chunk do env.received[#env.received+1]=bytes:sub(i,i+chunk-1) end
    end
    return env
end

local env=fresh("bad!")
assert(not pcall(dofile, bridge)); assert(#env.writes==0 and not env.connected)

env=fresh(); dofile(bridge); env.step(4)
assert(not env.connected and #env.writes==0, "ROM startup must not write memory")
env.ready(); env.again=true; env.step(40)
local hello=string.pack(">I4",33).."H"..string.rep(string.char(0xab),32)
assert(env.sent:sub(1,#hello)==hello, "Partial sends corrupted IPC authentication")
local frameSize=string.unpack(">I4",env.sent,#hello+1)
assert(frameSize==21 and env.sent:sub(#hello+5,#hello+5)=="P")

local payload=string.pack("<I4I4I4BBI2",1,2,1,0,1,0)
    ..string.pack("<I4",2)..pose..string.rep("\0",48)
env.feed(string.pack(">I4",89).."S"..payload,7); env.step(5)
assert(#env.writes==24, "Snapshot should commit once after a complete frame")
assert(env.writes[1][1]==address+36 and env.writes[1][2]%2==1)
assert(env.writes[24][1]==address+36 and env.writes[24][2]%2==0)
assert(env.memory[address+40]==1 and env.memory[address+56]==2)

-- Rejection clears old actors but never copies malformed bytes into the mailbox.
env.feed(string.pack(">I4",257),4); env.step(1)
assert(env.closed and #env.errors==1 and env.memory[address+40]==0)
local count=#env.writes; env.step(300); assert(#env.writes==count)

env=fresh(); dofile(bridge); env.ready(); env.step(1)
local duplicate=string.pack("<I4I4I4BBI2",1,2,1,0,2,0)
    ..string.pack("<I4",2)..pose..string.pack("<I4",2)..pose..string.rep("\0",24)
env.feed(string.pack(">I4",89).."S"..duplicate,100); env.step(1)
assert(env.closed and env.memory[address+40]==0, "Duplicate peer tokens accepted")

env=fresh(); dofile(bridge); env.memory[address]=0xDEADBEEF; env.step(1)
assert(#env.writes==0 and not env.connected and #env.errors==1)
print("PASS: bridge identity, ABI boundary, partial IPC, atomic snapshot, malformed frames")
