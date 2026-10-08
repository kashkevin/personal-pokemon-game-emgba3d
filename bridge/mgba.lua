-- Project-owned presence/live-save bridge for pinned mGBA 0.10.5.
-- The launcher prepends EMERALD_BRIDGE from the verified build manifest.
-- Network traffic goes to a loopback companion. Writes are limited to the
-- presence inbound slot and the optional, separately allocated save command
-- slot. The ROM owns Flash operations; no save blocks or RTC footer are written.
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
local controls, controlBurst = {}, 0
local saveAddr = cfg.save_address
if saveAddr ~= nil then
    assert(type(saveAddr) == "number" and saveAddr % 4 == 0
        and saveAddr >= 0x02000000 and saveAddr + 512 <= 0x02040000
        and cfg.save_size == 512 and cfg.save_abi == 1
        and not (saveAddr < addr + 128 and addr < saveAddr + 512),
        "Invalid separate save mailbox allocation")
end
local savePending, saveGeneration, capabilitySent = nil, nil, false
local tick, lastConnect, stopped = 0, -120, false
local observedPresence, previousFrame = false, nil
local observedSave, previousSaveFrame, previousSaveState = false, nil, nil

local function forgetRuntime()
    observedPresence, previousFrame = false, nil
    observedSave, previousSaveFrame, previousSaveState = false, nil, nil
end

local function headerReady()
    return emu:read32(addr) == 0x31504D45
        and emu:read16(addr + 4) == 1 and emu:read16(addr + 6) == 128
end

local function frame(payload)
    return string.pack(">I4", #payload) .. payload
end

local crcTable = {}
for value = 0, 255 do
    local crc = value
    for _ = 1, 8 do
        crc = (crc >> 1) ~ ((crc & 1) ~= 0 and 0xEDB88320 or 0)
    end
    crcTable[value] = crc
end
local function crc32(data)
    local crc = 0xFFFFFFFF
    for index = 1, #data do
        crc = (crc >> 8) ~ crcTable[(crc ~ data:byte(index)) & 255]
    end
    return (crc ~ 0xFFFFFFFF) & 0xFFFFFFFF
end

local function saveHeaderReady()
    return saveAddr ~= nil and emu:read32(saveAddr) == 0x31534D45
        and emu:read16(saveAddr + 4) == 1 and emu:read16(saveAddr + 6) == 512
        and emu:read32(saveAddr + 12) <= 7
        and emu:read32(saveAddr + 16) == 0 and emu:read32(saveAddr + 20) == 0
end

local function saveControl(payload, command)
    if #payload ~= 240 then return nil end
    local inc, epoch, request, seq, offset, size, revision, opcode, status, length, crc, data
        = string.unpack("<I4I4c16I4I4I4I4BBI2I4c192", payload)
    if inc == 0 or epoch == 0 or epoch > 0x7FFFFFFF or seq == 0
        or request == string.rep("\0", 16) or offset > 131072
        or (size ~= 0 and size ~= 131072) or revision > 0x7FFFFFFF
        or opcode < 1 or opcode > 9 or status > 13 or length > 192
        or data:sub(length + 1) ~= string.rep("\0", 192 - length)
        or crc32(data:sub(1, length)) ~= crc then return nil end
    if command then
        local lengths = {0, 0, 0, 0, 16, 128, 0, 0, 0}
        if status ~= 0 or length ~= lengths[opcode] then return nil end
        if (opcode == 3 or opcode == 6) and (size ~= 131072
            or offset % 128 ~= 0 or offset >= 131072) then return nil end
        if opcode == 5 then
            local _, _, rotation = string.unpack("<I4I4I4I4", data)
            if size ~= 131072 or rotation >= 14 then return nil end
        end
    else
        local lengths = {0, 40, 128, 4, 8, 0, 0, 0, 48}
        if (status == 0 and length ~= lengths[opcode]) or (status ~= 0 and length ~= 0) then return nil end
        if status == 0 and opcode == 3 and (offset % 128 ~= 0 or offset > 130944) then return nil end
    end
    return {incarnation=inc, epoch=epoch, request=request, sequence=seq,
        opcode=opcode, revision=revision, offset=offset, size=size, status=status, payload=payload}
end

local function commitSave(payload)
    if not verified or not saveHeaderReady() then return false end
    local current = emu:read32(saveAddr + 24)
    local odd = ((current - current % 2) + 1) % 0x100000000
    emu:write32(saveAddr + 24, odd)
    for offset = 0, 236, 4 do
        local word = string.unpack("<I4", payload, offset + 1)
        emu:write32(saveAddr + 28 + offset, word)
    end
    emu:write32(saveAddr + 24, (odd + 1) % 0x100000000)
    return true
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
    controls, controlBurst = {}, 0
    savePending, saveGeneration, capabilitySent = nil, nil, false
    commit(string.rep("\0", 88))
    if reason then
        stopped = fatal or false
        lastConnect = tick
        console:error("Multiplayer bridge disconnected: " .. reason)
    end
end

local function reliable(payload)
    if #controls >= 4 then stop("save control backpressure", true); return false end
    controls[#controls + 1] = frame(payload)
    return true
end

local function pollSave()
    if not savePending or not saveHeaderReady() then return end
    local generation = emu:read32(saveAddr + 268)
    if generation % 2 ~= 0 or generation == saveGeneration then return end
    local payload = emu:readRange(saveAddr + 272, 240)
    if generation ~= emu:read32(saveAddr + 268) then return end
    if payload == string.rep("\0", 240) then return end
    local response = saveControl(payload, false)
    if not response then stop("invalid save response", true); return end
    saveGeneration = generation
    -- An old response can remain in ROM RAM across an IPC/server reconnect.
    if response.incarnation ~= savePending.incarnation or response.epoch ~= savePending.epoch
        or response.request ~= savePending.request or response.sequence ~= savePending.sequence
        or response.opcode ~= savePending.opcode or response.revision ~= savePending.revision
        or response.size ~= savePending.size then return end
    if response.status == 0 and ((response.opcode == 3 and response.offset ~= savePending.offset)
        or (response.opcode == 6 and response.offset ~= savePending.offset + 128)) then
        stop("invalid save response offset", true); return
    end
    if reliable("R" .. payload) then savePending = nil end
end

local function validPose(bytes)
    local epoch, f, x, y, group, map, direction, elevation, gender, mode, activity, reserved
        = string.unpack("<I4I4i2i2BBBBBBBB", bytes)
    return direction >= 1 and direction <= 4 and elevation <= 15
        and gender <= 1 and mode <= 4 and activity <= 1 and reserved == 0
end

local function regressed(current, previous)
    -- ROM counters wrap normally at uint32; a pause or Flash loop can stall.
    return previous ~= nil and ((current - previous) & 0xFFFFFFFF) >= 0x80000000
end

local function runtimeRestart(reason)
    -- BIOS joypad soft reset need not emit mGBA's reset callback. A fresh IPC
    -- handshake gives the companion a new incarnation and fences old commands.
    if not identityMatches() then
        verified = false
        stop("ROM changed since bridge configuration", true)
    else
        stop(reason)
    end
    forgetRuntime()
end

local function runtimeReady()
    if not headerReady() then
        if emu:read32(addr) ~= 0 then
            stop("mailbox ABI mismatch", true)
        elseif observedPresence then
            runtimeRestart("ROM mailbox reinitialized")
        end
        return false
    end
    local generation = emu:read32(addr + 12)
    if generation % 2 == 0 then
        local current = emu:read32(addr + 8)
        local pose = emu:readRange(addr + 16, 20)
        if #pose == 20 and validPose(pose) and string.unpack("<I4", pose, 5) == current
            and generation == emu:read32(addr + 12) and current == emu:read32(addr + 8)
            and headerReady() then
            if regressed(current, previousFrame) then
                runtimeRestart("ROM frame counter restarted")
                return false
            end
            observedPresence, previousFrame = true, current
        end
    end
    if saveAddr ~= nil then
        if not saveHeaderReady() then
            if emu:read32(saveAddr) ~= 0 then
                stop("save mailbox ABI mismatch", true)
                return false
            elseif observedSave then
                runtimeRestart("ROM save mailbox reinitialized")
                return false
            end
        else
            local current, state = emu:read32(saveAddr + 8), emu:read32(saveAddr + 12)
            if current == emu:read32(saveAddr + 8) and state == emu:read32(saveAddr + 12)
                and saveHeaderReady() then
                if regressed(current, previousSaveFrame)
                    or (observedSave and previousSaveState ~= 0 and state == 0
                        and emu:readRange(saveAddr + 24, 488) == string.rep("\0", 488)) then
                    runtimeRestart("ROM save runtime restarted")
                    return false
                end
                observedSave, previousSaveFrame, previousSaveState = true, current, state
            end
        end
    end
    return true
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
            if payload:sub(1, 1) == "S" and validSnapshot(payload:sub(2)) then
                commit(payload:sub(2))
            elseif payload:sub(1, 1) == "C" then
                local command = saveControl(payload:sub(2), true)
                if not command or not saveHeaderReady() then stop("invalid save command", true); return end
                -- A new BIND fences a pending operation after server reconnection.
                if savePending and command.opcode ~= 1 and command.payload ~= savePending.payload then
                    stop("multiple outstanding save commands", true); return
                end
                if commitSave(command.payload) then savePending = command end
            else
                stop("invalid bridge packet", true); return
            end
        end
        if #rx > 260 then stop("IPC receive buffer exceeded", true); return end
    end
end

local function flush()
    if #tx == 0 then
        if #controls > 0 and (not latestPose or controlBurst < 2) then
            tx = table.remove(controls, 1)
            controlBurst = controlBurst + 1
        elseif latestPose then
            tx, latestPose = latestPose, nil
            controlBurst = 0
        end
    end
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
    if not runtimeReady() then return end
    if not sock and tick - lastConnect >= 120 then
        lastConnect = tick
        local candidate, err = socket.connect("127.0.0.1", cfg.port)
        if not candidate then return end
        sock, rx, tx = candidate, "", frame("H" .. token)
        controls, controlBurst = {}, 0
        savePending, saveGeneration, capabilitySent = nil, nil, false
        console:log("Multiplayer bridge connected to local companion")
    end
    if not sock then return end
    if saveHeaderReady() and not capabilitySent then
        if not reliable("V" .. string.pack("<I2I2I2I2", 1, 512, 240, 192)) then return end
        capabilitySent = true
    end
    receive()
    if not sock then return end
    pollSave()
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
    forgetRuntime()
    verified = identityMatches()
    if not verified then stop("ROM changed since bridge configuration", true) end
end
callbacks:add("start", verifyRestart)
callbacks:add("reset", verifyRestart)
callbacks:add("stop", function() stop() end)
callbacks:add("crashed", function() stop("emulator crash", true) end)
callbacks:add("shutdown", function() stop() end)
