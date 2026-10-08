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
local tradeEnabled = cfg.trade_abi ~= nil or cfg.trade_abi_address ~= nil
if tradeEnabled then
    assert(saveAddr ~= nil and cfg.trade_abi == 1
        and type(cfg.trade_abi_address) == "number" and cfg.trade_abi_address % 4 == 0
        and cfg.trade_abi_address >= 0x08000000
        and cfg.trade_abi_address + 4 <= 0x08000000 + cfg.rom_size
        and emu:read32(cfg.trade_abi_address) == 1, "Invalid trade capability marker")
end
local savePending, saveGeneration, capabilitySent = nil, nil, false
local emergencyEnabled = cfg.emergency_save_abi ~= nil or cfg.emergency_save_abi_address ~= nil
if emergencyEnabled then
    assert(tradeEnabled and cfg.emergency_save_abi == 1
        and type(cfg.emergency_save_abi_address) == "number" and cfg.emergency_save_abi_address % 4 == 0
        and cfg.emergency_save_abi_address >= 0x08000000
        and cfg.emergency_save_abi_address + 4 <= 0x08000000 + cfg.rom_size
        and emu:read32(cfg.emergency_save_abi_address) == 1, "Invalid emergency save capability marker")
end
local emergencyCapabilitySent = false
local battleAddr = cfg.battle_address
local battleEnabled = battleAddr ~= nil or cfg.battle_abi ~= nil or cfg.battle_abi_address ~= nil or cfg.battle_size ~= nil
if battleEnabled then
    assert(tradeEnabled and type(battleAddr) == "number" and battleAddr % 4 == 0
        and battleAddr >= 0x02000000 and battleAddr + 512 <= 0x02040000
        and not (battleAddr < addr + 128 and addr < battleAddr + 512)
        and not (battleAddr < saveAddr + 512 and saveAddr < battleAddr + 512)
        and cfg.battle_size == 512 and (cfg.battle_abi == 1 or cfg.battle_abi == 2 or cfg.battle_abi == 3)
        and type(cfg.battle_abi_address) == "number" and cfg.battle_abi_address % 4 == 0
        and cfg.battle_abi_address >= 0x08000000
        and cfg.battle_abi_address + 4 <= 0x08000000 + cfg.rom_size
        and emu:read32(cfg.battle_abi_address) == cfg.battle_abi, "Invalid development battle capability")
end
local battlePending, battleGeneration, battleCapabilitySent = nil, nil, false
local windowAddr = cfg.window_address
local windowEnabled = windowAddr ~= nil or cfg.window_abi ~= nil or cfg.window_abi_address ~= nil or cfg.window_size ~= nil
if windowEnabled then
    assert(tradeEnabled and type(windowAddr) == "number" and windowAddr % 4 == 0
        and windowAddr >= 0x02000000 and windowAddr + 4096 <= 0x02040000
        and not (windowAddr < addr + 128 and addr < windowAddr + 4096)
        and not (windowAddr < saveAddr + 512 and saveAddr < windowAddr + 4096)
        and (not battleEnabled or not (windowAddr < battleAddr + 512 and battleAddr < windowAddr + 4096))
        and cfg.window_size == 4096 and cfg.window_abi == 1
        and type(cfg.window_abi_address) == "number" and cfg.window_abi_address % 4 == 0
        and cfg.window_abi_address >= 0x08000000
        and cfg.window_abi_address + 4 <= 0x08000000 + cfg.rom_size
        and emu:read32(cfg.window_abi_address) == 1, "Invalid read-only save window")
end
local windowCapabilitySent = false
local menuAddr = cfg.menu_address
local menuEnabled = menuAddr ~= nil or cfg.menu_abi ~= nil or cfg.menu_abi_address ~= nil or cfg.menu_size ~= nil
if menuEnabled then
    assert(type(menuAddr) == "number" and menuAddr % 4 == 0
        and menuAddr >= 0x02000000 and menuAddr + 512 <= 0x02040000
        and not (menuAddr < addr + 128 and addr < menuAddr + 512)
        and (saveAddr == nil or not (menuAddr < saveAddr + 512 and saveAddr < menuAddr + 512))
        and (not battleEnabled or not (menuAddr < battleAddr + 512 and battleAddr < menuAddr + 512))
        and (not windowEnabled or not (menuAddr < windowAddr + 4096 and windowAddr < menuAddr + 512))
        and cfg.menu_size == 512 and cfg.menu_abi == 1
        and type(cfg.menu_abi_address) == "number" and cfg.menu_abi_address % 4 == 0
        and cfg.menu_abi_address >= 0x08000000
        and cfg.menu_abi_address + 4 <= 0x08000000 + cfg.rom_size
        and emu:read32(cfg.menu_abi_address) == 1, "Invalid Players menu capability")
end
local menuCapabilitySent, menuSequence = false, nil
local observedMenu, previousMenuFrame = false, nil
local observedBattle, previousBattleFrame, previousBattleState = false, nil, nil
local tick, lastConnect, stopped = 0, -120, false
local observedPresence, previousFrame = false, nil
local observedSave, previousSaveFrame, previousSaveState = false, nil, nil

local function forgetRuntime()
    observedPresence, previousFrame = false, nil
    observedSave, previousSaveFrame, previousSaveState = false, nil, nil
    observedBattle, previousBattleFrame, previousBattleState = false, nil, nil
    observedMenu, previousMenuFrame = false, nil
end

local function headerReady()
    return emu:read32(addr) == 0x31504D45
        and emu:read16(addr + 4) == 1 and emu:read16(addr + 6) == 128
end

local function frame(payload)
    return string.pack(">I4", #payload) .. payload
end

local function menuHeaderReady()
    return menuEnabled and emu:read32(menuAddr) == 0x31554D45
        and emu:read16(menuAddr + 4) == 1 and emu:read16(menuAddr + 6) == 512
end

local function menuText(value)
    local zero = value:find("\0", 1, true)
    if not zero or value:sub(zero) ~= string.rep("\0", #value - zero + 1) then return false end
    for i = 1, zero - 1 do
        local c = value:byte(i)
        if c < 32 or c > 126 then return false end
    end
    return true
end

local function validMenuScreen(payload)
    if #payload ~= 240 then return false end
    local ack, revision, flags, count, back = string.unpack("<I4I4BBI2", payload)
    if ack == 0 or revision == 0 or flags > 1 or count > 6 or (back ~= 0 and back ~= 7)
        or not menuText(payload:sub(13, 36)) or not menuText(payload:sub(37, 68))
        or payload:sub(69 + count * 28) ~= string.rep("\0", 172 - count * 28) then return false end
    for i = 0, count - 1 do
        local action = string.unpack("<I2", payload, 69 + i * 28)
        if (action ~= 0 and action ~= i + 1) or not menuText(payload:sub(71 + i * 28, 96 + i * 28)) then return false end
    end
    return true
end

local function commitMenu(payload)
    if not verified or not menuHeaderReady() then return false end
    -- Stale replies remain harmless even if the local user closed/reopened.
    local ack = string.unpack("<I4", payload)
    if ack ~= emu:read32(menuAddr + 16) then return true end
    local current = emu:read32(menuAddr + 32)
    local odd = ((current - current % 2) + 1) % 0x100000000
    emu:write32(menuAddr + 32, odd)
    for offset = 0, 236, 4 do
        local word = string.unpack("<I4", payload, offset + 1)
        emu:write32(menuAddr + 36 + offset, word)
    end
    emu:write32(menuAddr + 32, (odd + 1) % 0x100000000)
    return true
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
        and emu:read32(saveAddr + 12) <= (emergencyEnabled and 10 or (tradeEnabled and 8 or 7))
        and emu:read32(saveAddr + 16) == 0 and emu:read32(saveAddr + 20) == 0
end

local function saveControl(payload, command)
    if #payload ~= 240 then return nil end
    local inc, epoch, request, seq, offset, size, revision, opcode, status, length, crc, data
        = string.unpack("<I4I4c16I4I4I4I4BBI2I4c192", payload)
    if inc == 0 or epoch == 0 or epoch > 0x7FFFFFFF or seq == 0
        or request == string.rep("\0", 16) or offset > 131072
        or (size ~= 0 and size ~= 131072) or revision > 0x7FFFFFFF
        or opcode < 1 or opcode > (emergencyEnabled and 21 or (windowEnabled and 18 or (tradeEnabled and 17 or 11)))
        or (opcode == 18 and not windowEnabled) or status > 13 or length > 192
        or data:sub(length + 1) ~= string.rep("\0", 192 - length)
        or crc32(data:sub(1, length)) ~= crc then return nil end
    if command then
        local lengths = {0, 0, 0, 0, 16, 128, 0, 0, 0, 0, 60, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0}
        if status ~= 0 or length ~= lengths[opcode] then return nil end
        if opcode >= 12 and opcode <= 17 and (size ~= 131072 or offset ~= 0) then return nil end
        if opcode == 18 and (size ~= 131072 or offset % 4096 ~= 0 or offset > 126976) then return nil end
        if opcode == 12 and (revision == 0 or revision >= 0x7FFFFFFF) then return nil end
        if opcode == 16 and seq ~= 1 then return nil end
        if opcode >= 19 then
            if size ~= 131072 or offset ~= (opcode == 20 and 131072 or 0) then return nil end
            if opcode ~= 21 and revision == 0 then return nil end
        end
        if (opcode == 3 or opcode == 6) and (size ~= 131072
            or offset % 128 ~= 0 or offset >= 131072) then return nil end
        if opcode == 5 then
            local _, _, rotation = string.unpack("<I4I4I4I4", data)
            if size ~= 131072 or rotation >= 14 then return nil end
        end
    else
        local lengths = {0, 40, 128, 4, 8, 0, 0, 0, 48, 80, 80, 40, 48, 0, 4, 48, 48, 4, 40, 4, 48}
        if (status == 0 and length ~= lengths[opcode]) or (status ~= 0 and length ~= 0) then return nil end
        if status == 0 and opcode == 3 and (offset % 128 ~= 0 or offset > 130944) then return nil end
        if status == 0 and opcode == 18 and (size ~= 131072 or offset % 4096 ~= 0 or offset > 126976) then return nil end
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

local function battleHeaderReady()
    return battleEnabled and emu:read32(battleAddr) == 0x31424D45
        and emu:read16(battleAddr + 4) == cfg.battle_abi and emu:read16(battleAddr + 6) == 512
        and emu:read32(battleAddr + 12) <= (cfg.battle_abi >= 2 and 8 or 3)
        and emu:read32(battleAddr + 16) == 0 and emu:read32(battleAddr + 20) == 0
end

local function battleControl(payload, command)
    if #payload ~= 240 then return nil end
    local inc, epoch, id, seq, block, offset, size, opcode, status, phase, source, kind, reserved, length, crc, data
        = string.unpack("<I4I4c16I4I4I2I2BBBBBBI2I4c192", payload)
    if inc == 0 or epoch == 0 or epoch > 0x7FFFFFFF or id == string.rep("\0", 16)
        or seq == 0 or size > 256 or offset > size or opcode < 1 or opcode > 13
        or status > 10 or source > 3 or reserved ~= 0
        or length > 192 or data:sub(length + 1) ~= string.rep("\0", 192 - length)
        or crc32(data:sub(1, length)) ~= crc then return nil end
    local native = ((cfg.battle_abi == 2 or cfg.battle_abi == 3) and phase == 2) or (cfg.battle_abi == 3 and phase == 3)
    local count = phase == 3 and 4 or 2
    if not native and (phase ~= 1 or opcode > 9 or kind > 1) then return nil end
    if native and (source >= count or opcode == 3 or opcode == 7 or opcode == 8 or kind == 1 or kind > 8) then return nil end
    local blockOp = opcode == 4 or opcode == 5 or opcode == 6
    if blockOp then
        if block == 0 then return nil end
        if native then
            local sizes = {[2]=28,[3]=32,[4]=200,[5]=200,[6]=200,[7]=16}
            local controllerSizes = {[12]=true,[16]=true,[20]=true,[24]=true,[28]=true,
                [36]=true,[56]=true,[64]=true,[92]=true,[156]=true}
            if (kind == 8 and not controllerSizes[size]) or (kind ~= 8 and sizes[kind] ~= size) then return nil end
            if (opcode == 5 and offset ~= size)
                or (opcode ~= 5 and (offset >= size or offset % 128 ~= 0)) then return nil end
        else
            if kind ~= 1 or size ~= 40 then return nil end
            if (opcode == 5 and offset ~= 40) or (opcode ~= 5 and offset ~= 0) then return nil end
        end
    elseif block ~= 0 or offset ~= 0 or size ~= 0 or kind ~= 0 then return nil end
    if command then
        local lengths = native and {[1]=116,[2]=0,[4]=0,[5]=8,[6]=math.min(128,size-offset),
            [9]=0,[10]=36,[11]=0,[12]=0,[13]=8} or {116, 0, 4, 0, 8, 40, 4, 0, 0}
        if status ~= 0 or length ~= lengths[opcode] then return nil end
        if opcode == 5 or opcode == 7 then
            local mask = string.unpack("<I4", data, opcode == 5 and 5 or 1)
            if mask == 0 or mask > 15 then return nil end
            if native and mask ~= (((1 << count)-1) ~ (1 << source)) then return nil end
        end
        if opcode == 6 and not native then
            local magic, version, generation, slot, _, lease, incarnation = string.unpack("<I4I4c16I4I4I4I4", data)
            if magic ~= 0x44424D45 or version ~= 1 or generation == string.rep("\0", 16)
                or slot ~= source or lease == 0 or lease > 0x7FFFFFFF or incarnation == 0 then return nil end
        end
    else
        local lengths = native and {[1]=64,[2]=64,[4]=math.min(128,size-offset),[5]=0,
            [6]=0,[9]=64,[10]=64,[11]=64,[12]=0,[13]=0} or {64, 64, 64, 40, 0, 0, 0, 0, 64}
        if (status == 0 and length ~= lengths[opcode]) or (status ~= 0 and length ~= 0) then return nil end
    end
    -- Bytes 1-37 and 39-41 are the immutable response correlation fields;
    -- status, length, CRC and data may change. C validates roster/roles again.
    return {payload=payload, opcode=opcode, correlation=payload:sub(1,37)..payload:sub(39,41)}
end

local function commitBattle(payload)
    if not verified or not battleHeaderReady() then return false end
    local current = emu:read32(battleAddr + 24)
    local odd = ((current - current % 2) + 1) % 0x100000000
    emu:write32(battleAddr + 24, odd)
    for offset = 0, 236, 4 do
        local word = string.unpack("<I4", payload, offset + 1)
        emu:write32(battleAddr + 28 + offset, word)
    end
    emu:write32(battleAddr + 24, (odd + 1) % 0x100000000)
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
    windowCapabilitySent = false
    emergencyCapabilitySent = false
    battlePending, battleGeneration, battleCapabilitySent = nil, nil, false
    menuCapabilitySent, menuSequence = false, nil
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
        or (response.opcode == 18 and response.offset ~= savePending.offset)
        or (response.opcode == 6 and response.offset ~= savePending.offset + 128)) then
        stop("invalid save response offset", true); return
    end
    if response.opcode == 18 and response.status == 0 then
        local state = emu:read32(saveAddr + 12)
        if state ~= 2 and state ~= 6 then stop("save window no longer held", true); return end
        local bytes = emu:readRange(windowAddr, 4096)
        local expected = string.unpack("<I4", payload, 49)
        if #bytes ~= 4096 or crc32(bytes) ~= expected
            or generation ~= emu:read32(saveAddr + 268) or state ~= emu:read32(saveAddr + 12) then
            stop("save window changed before readback", true); return
        end
        if reliable("F" .. payload .. bytes) then savePending = nil end
    elseif reliable("R" .. payload) then savePending = nil end
end

local function pollBattle()
    if not battlePending or not battleHeaderReady() then return end
    local generation = emu:read32(battleAddr + 268)
    if generation % 2 ~= 0 or generation == battleGeneration then return end
    local payload = emu:readRange(battleAddr + 272, 240)
    if generation ~= emu:read32(battleAddr + 268) or payload == string.rep("\0", 240) then return end
    local response = battleControl(payload, false)
    if not response then stop("invalid battle response", true); return end
    battleGeneration = generation
    if response.correlation ~= battlePending.correlation then return end
    if reliable("E" .. payload) then battlePending = nil end
end

local function pollMenu()
    if not menuCapabilitySent or not menuHeaderReady() then return end
    if #controls >= 4 then return end -- Initial capability announcements drain first.
    local generation = emu:read32(menuAddr + 12)
    if generation % 2 ~= 0 then return end
    local payload = emu:readRange(menuAddr + 16, 16)
    if generation ~= emu:read32(menuAddr + 12) or payload == string.rep("\0", 16) then return end
    if #payload ~= 16 then stop("invalid menu read", true); return end
    local seq, screen, action, kind, reserved = string.unpack("<I4I4I2Bc5", payload)
    if seq == 0 or action > 7 or kind < 1 or kind > 3 or reserved ~= string.rep("\0", 5)
        or (kind == 2 and (screen == 0 or action == 0)) or (kind ~= 2 and action ~= 0)
        or (kind == 1 and screen ~= 0) then stop("invalid menu request", true); return end
    if seq == menuSequence then return end
    if menuSequence and seq < menuSequence then stop("menu request sequence regressed", true); return end
    if reliable("J" .. payload) then menuSequence = seq end
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
    if battleEnabled then
        if not battleHeaderReady() then
            if emu:read32(battleAddr) ~= 0 then stop("battle mailbox ABI mismatch", true)
            elseif observedBattle then runtimeRestart("ROM battle mailbox reinitialized") end
            return false
        end
        local current, state = emu:read32(battleAddr + 8), emu:read32(battleAddr + 12)
        if regressed(current, previousBattleFrame)
            or (observedBattle and previousBattleState ~= 0 and state == 0
                and emu:readRange(battleAddr + 24, 488) == string.rep("\0", 488)) then
            runtimeRestart("ROM battle runtime restarted")
            return false
        end
        observedBattle, previousBattleFrame, previousBattleState = true, current, state
    end
    if menuEnabled then
        if not menuHeaderReady() then
            if emu:read32(menuAddr) ~= 0 then stop("menu mailbox ABI mismatch", true)
            elseif observedMenu then runtimeRestart("ROM menu mailbox reinitialized") end
            return false
        end
        local current = emu:read32(menuAddr + 8)
        if regressed(current, previousMenuFrame) then
            runtimeRestart("ROM menu runtime restarted")
            return false
        end
        observedMenu, previousMenuFrame = true, current
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
                -- Recovery must observe/rebind an uncertain trade command.
                -- The ROM fences UUID/incarnation/lease and preserves pending
                -- Flash publication; these controls cannot release the hold.
                local recovery = command.opcode == 1 or command.opcode == 16 or command.opcode == 17 or command.opcode == 21
                if savePending and not recovery and command.payload ~= savePending.payload then
                    stop("multiple outstanding save commands", true); return
                end
                if commitSave(command.payload) then savePending = command end
            elseif payload:sub(1, 1) == "D" then
                local command = battleControl(payload:sub(2), true)
                if not command or not battleHeaderReady() then stop("invalid battle command", true); return end
                if battlePending and command.opcode ~= 2 and command.payload ~= battlePending.payload then
                    stop("multiple outstanding battle commands", true); return
                end
                if commitBattle(command.payload) then battlePending = command end
            elseif payload:sub(1, 1) == "M" then
                if not menuCapabilitySent or not validMenuScreen(payload:sub(2)) or not commitMenu(payload:sub(2)) then
                    stop("invalid menu screen", true); return
                end
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
        windowCapabilitySent = false
        emergencyCapabilitySent = false
        battlePending, battleGeneration, battleCapabilitySent = nil, nil, false
        menuCapabilitySent, menuSequence = false, nil
        console:log("Multiplayer bridge connected to local companion")
    end
    if not sock then return end
    if saveHeaderReady() and not capabilitySent then
        if not reliable("V" .. string.pack("<I2I2I2I2", 1, 512, 240, 192)) then return end
        capabilitySent = true
    end
    if battleHeaderReady() and not battleCapabilitySent then
        if not reliable("W" .. string.pack("<I2I2I2I2", cfg.battle_abi, 512, 240, 192)) then return end
        battleCapabilitySent = true
    end
    if windowEnabled and saveHeaderReady() and capabilitySent and not windowCapabilitySent then
        if not reliable("X" .. string.pack("<I2I2", 1, 4096)) then return end
        windowCapabilitySent = true
    end
    if menuHeaderReady() and not menuCapabilitySent then
        if not reliable("I" .. string.pack("<I2I2I2I2", 1, 512, 240, 16)) then return end
        menuCapabilitySent = true
    end
    -- The existing four reliable slots remain bounded. Advertise the fifth
    -- optional capability only when earlier announcements have drained.
    if emergencyEnabled and saveHeaderReady() and capabilitySent and not emergencyCapabilitySent and #controls < 4 then
        if not reliable("Z" .. string.pack("<I2I2I2I2", 1, 19, 21, 10)) then return end
        emergencyCapabilitySent = true
    end
    receive()
    if not sock then return end
    pollSave()
    if not sock then return end
    pollBattle()
    if not sock then return end
    pollMenu()
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
