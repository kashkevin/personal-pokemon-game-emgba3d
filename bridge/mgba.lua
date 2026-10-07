-- Project-owned presence bridge for pinned mGBA 0.10.5.
-- The launcher prepends EMERALD_BRIDGE from the verified build manifest.
-- Network traffic goes to a loopback companion; only mailbox bytes 36..127
-- may be written. Pokémon, items, save blocks, and input are never written.
local cfg = assert(EMERALD_BRIDGE, "Missing verified bridge configuration")
assert(string.pack and string.unpack, "Bridge requires Lua 5.3 or newer")
assert(type(cfg.address) == "number" and cfg.address % 4 == 0
    and cfg.address >= 0x02000000 and cfg.address + 128 <= 0x02040000,
    "Mailbox address is outside EWRAM")
assert(type(cfg.port) == "number" and cfg.port % 1 == 0
    and cfg.port >= 1 and cfg.port <= 65535, "Invalid loopback port")
assert(type(cfg.token) == "string" and #cfg.token == 64
    and cfg.token:match("^[0-9a-f]+$"), "Invalid IPC token")
assert(type(cfg.rom_crc32) == "string" and #cfg.rom_crc32 == 8
    and cfg.rom_crc32:match("^[0-9a-f]+$"), "Invalid ROM CRC")

local function hex(bytes)
    return (bytes:gsub(".", function(c) return string.format("%02x", c:byte()) end))
end
local function identityMatches()
    return emu:romSize() == cfg.rom_size and hex(emu:checksum()) == cfg.rom_crc32
end
assert(identityMatches(), "Loaded ROM does not match the verified manifest")
local verified = true

local token = cfg.token:gsub("..", function(pair) return string.char(tonumber(pair, 16)) end)
local addr = cfg.address
local sock, rx, tx, latestPose = nil, "", "", nil
local tick, lastConnect, stopped = 0, -120, false

local function headerReady()
    return emu:read32(addr) == 0x31504D45
        and emu:read16(addr + 4) == 1 and emu:read16(addr + 6) == 128
end

local function frame(payload)
    return string.pack(">I4", #payload) .. payload
end

local function commit(payload)
    if not verified or not headerReady() then return end
    local current = emu:read32(addr + 36)
    local odd = ((current - current % 2) + 1) % 0x100000000
    emu:write32(addr + 36, odd)
    for offset = 0, 84, 4 do
        local word = string.unpack("<I4", payload, offset + 1)
        emu:write32(addr + 40 + offset, word)
    end
    emu:write32(addr + 36, (odd + 1) % 0x100000000)
end

local function stop(reason, fatal)
    if sock then sock:close(); sock = nil end
    rx, tx, latestPose = "", "", nil
    commit(string.rep("\0", 88))
    if reason then
        stopped = fatal or false
        lastConnect = tick
        console:error("Multiplayer bridge disconnected: " .. reason)
    end
end

local function validPose(bytes)
    local epoch, f, x, y, group, map, direction, elevation, gender, mode, activity, reserved
        = string.unpack("<I4I4i2i2BBBBBBBB", bytes)
    return direction >= 1 and direction <= 4 and elevation <= 15
        and gender <= 1 and mode <= 4 and activity <= 1 and reserved == 0
end

local function validSnapshot(payload)
    if #payload ~= 88 then return false end
    local flags, heartbeat, epoch, selfSlot, count, reserved
        = string.unpack("<I4I4I4BBI2", payload)
    if flags > 1 or selfSlot > 3 or count > 3 or reserved ~= 0
        or (flags == 1 and epoch == 0) then return false end
    local seen = {}
    for i = 0, 2 do
        local offset = 17 + i * 24
        local peerToken = string.unpack("<I4", payload, offset)
        local pose = payload:sub(offset + 4, offset + 23)
        if i < count then
            if peerToken == 0 or seen[peerToken] or not validPose(pose) then return false end
            seen[peerToken] = true
        elseif payload:sub(offset, offset + 23) ~= string.rep("\0", 24) then
            return false
        end
    end
    return flags == 1 or (count == 0 and selfSlot == 0)
end

local function receive()
    -- Bound work to 1 KiB per emulated frame. Partial headers/bodies persist.
    for _ = 1, 4 do
        local ready, err = sock:hasdata()
        if err then stop(err); return end
        if not ready then break end
        local data, receiveError = sock:receive(256)
        if not data then
            if receiveError ~= socket.ERRORS.AGAIN then stop(receiveError or "disconnected") end
            return
        end
        rx = rx .. data
        while #rx >= 4 do
            local size = string.unpack(">I4", rx)
            if size < 1 or size > 256 then stop("invalid IPC frame length", true); return end
            if #rx < size + 4 then break end
            local payload = rx:sub(5, size + 4)
            rx = rx:sub(size + 5)
            if payload:sub(1, 1) ~= "S" or not validSnapshot(payload:sub(2)) then
                stop("invalid presence snapshot", true); return
            end
            commit(payload:sub(2))
        end
        if #rx > 260 then stop("IPC receive buffer exceeded", true); return end
    end
end

local function flush()
    if #tx == 0 and latestPose then tx, latestPose = latestPose, nil end
    if #tx == 0 then return end
    local sent, err = sock:send(tx)
    if not sent then
        if err ~= socket.ERRORS.AGAIN then stop(err or "send failure") end
        return
    end
    if sent < 0 or sent > #tx then stop("invalid send result", true); return end
    tx = tx:sub(sent + 1)
end

local function onFrame()
    tick = tick + 1
    if stopped or not verified then return end
    if not headerReady() then
        -- Zero means normal ROM startup. A different nonzero ABI is rejected.
        if emu:read32(addr) ~= 0 then stop("mailbox ABI mismatch", true) end
        return
    end
    if not sock and tick - lastConnect >= 120 then
        lastConnect = tick
        local candidate, err = socket.connect("127.0.0.1", cfg.port)
        if not candidate then return end
        sock, rx, tx = candidate, "", frame("H" .. token)
        console:log("Multiplayer bridge connected to local companion")
    end
    if not sock then return end
    receive()
    if not sock then return end
    if tick % 6 == 0 then
        local generation = emu:read32(addr + 12)
        if generation % 2 == 0 then
            local pose = emu:readRange(addr + 16, 20)
            if generation == emu:read32(addr + 12) and #pose == 20 and validPose(pose) then
                latestPose = frame("P" .. pose)
            end
        end
    end
    flush()
end

callbacks:add("frame", onFrame)
local function verifyRestart()
    verified = false
    stop()
    tick, lastConnect, stopped = 0, -120, false
    verified = identityMatches()
    if not verified then stop("ROM changed since bridge configuration", true) end
end
callbacks:add("start", verifyRestart)
callbacks:add("reset", verifyRestart)
callbacks:add("stop", function() stop() end)
callbacks:add("crashed", function() stop("emulator crash", true) end)
callbacks:add("shutdown", function() stop() end)
