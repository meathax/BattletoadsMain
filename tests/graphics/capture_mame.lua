-- Diagnostic gameplay coverage; raw native snapshots are retained, not used as
-- a substitute for a concurrent paired whole-system comparison.
local machine = manager.machine
local screen = machine.screens[':screen']
local space = machine.devices[':maincpu'].spaces['program']
local frame, writes, odd_widths, flips, shadows = 0, 0, 0, 0, 0
local modes, srcscale, dstscale = {}, {}, {}
local current_control, current_misc = 0, 0
local current_src, current_dst, current_display = 0, 0, 0
local current_scroll0, current_scroll1 = 0, 0
local display_log = assert(io.open('display_events.txt','w'))
local function log_display(kind)
    -- The TMS VCOUNT/HCOUNT read handlers report the live raster position.
    local counts=space:read_u32(0xc00001c0)
    display_log:write(string.format('%s frame=%d vpos=%d hcount=%d display=%04x scroll0=%04x scroll1=%04x\n',
        kind,frame,counts & 0xffff,(counts >> 16) & 0xffff,
        current_display,current_scroll0,current_scroll1))
end
local configurations = {}
local function merge(old, data, mask)
    mask = mask & 0xffff
    return (old & (~mask & 0xffff)) | (data & mask)
end
local taps = {}
local foreground_accesses = {upper_reads=0, upper_writes=0, upper_nonzero_writes=0,
    gameplay_upper_reads=0, gameplay_upper_writes=0, gameplay_upper_nonzero_writes=0}
local foreground_examples = {}
local function tap(a, b, name, cb)
    taps[#taps+1] = space:install_write_tap(a, b, name, cb)
end
tap(0x20000000, 0x2000047f, 'graphics_audit', function(offset, data, mask)
    writes = writes + 1
    if offset == 0x20000100 then
        current_control = merge(current_control, data, mask)
        if (((~data & 0x1ff) + 2) & 1) ~= 0 then odd_widths = odd_widths + 1 end
        if (data & 0x400) ~= 0 then flips = flips + 1 end
    elseif offset == 0x20000000 then
        current_src = merge(current_src, data, mask)
        srcscale[current_src] = true
    elseif offset == 0x20000080 then
        current_dst = merge(current_dst, data, mask)
        dstscale[current_dst] = true
    elseif offset == 0x20000180 then
        current_display = merge(current_display, data, mask)
        modes[(current_display >> 8) & 3] = true
    elseif offset == 0x20000200 then
        current_scroll0 = merge(current_scroll0, data, mask)
    elseif offset == 0x20000280 then
        current_scroll1 = merge(current_scroll1, data, mask)
    elseif offset == 0x20000400 then
        current_misc = merge(current_misc, data, mask)
        if (data & 0x10) ~= 0 then shadows = shadows + 1 end
    end
    if offset == 0x20000180 or offset == 0x20000200 or offset == 0x20000280 then
        log_display('write')
    end
    if frame >= 1000 and (offset == 0x20000000 or offset == 0x20000080 or
        offset == 0x20000100 or offset == 0x20000180 or offset == 0x20000400) then
        local key = string.format('%d %d %d %d %d', current_src, current_dst,
            current_control, (current_misc >> 4) & 1, current_display)
        configurations[key] = true
    end
end)
-- Ordinary CPU accesses only: shift callbacks copy backing arrays directly.
-- Bit 13 selects the independent upper 512 bytes of a logical foreground row.
for _, base in ipairs({0xa0000000, 0xa4000000}) do
    taps[#taps+1] = space:install_read_tap(base, base+0x3fffff,
        string.format('foreground_read_%x',base), function(offset, data, mask)
        if frame<1800 and (offset & 0x2000)~=0 then
            foreground_accesses.upper_reads=foreground_accesses.upper_reads+1
            if frame>=1000 then
                foreground_accesses.gameplay_upper_reads=foreground_accesses.gameplay_upper_reads+1
            end
        end
    end)
    tap(base, base+0x3fffff, string.format('foreground_write_%x',base),
        function(offset, data, mask)
        if frame<1800 and (offset & 0x2000)~=0 and (mask & 0xff)~=0 then
            foreground_accesses.upper_writes=foreground_accesses.upper_writes+1
            local nonzero=(data & mask & 0xff)~=0
            if nonzero then
                foreground_accesses.upper_nonzero_writes=foreground_accesses.upper_nonzero_writes+1
                if #foreground_examples<16 then
                    foreground_examples[#foreground_examples+1]=string.format(
                        'frame=%d address=%08x data=%04x mask=%04x',frame,offset,data,mask)
                end
            end
            if frame>=1000 then
                foreground_accesses.gameplay_upper_writes=foreground_accesses.gameplay_upper_writes+1
                if nonzero then
                    foreground_accesses.gameplay_upper_nonzero_writes=
                        foreground_accesses.gameplay_upper_nonzero_writes+1
                end
            end
        end
    end)
end
local fields = machine.ioport.ports[':P1'].fields
local coin, start, attack, right
for name, field in pairs(fields) do
    if field.mask == 0x40 then coin=field end
    if field.mask == 0x80 then start=field end
    if field.mask == 0x10 then attack=field end
    if field.mask == 0x02 then right=field end
end
assert(coin and start and attack and right, 'required P1 fields absent')
local input_log = assert(io.open('inputs.txt','w'))
local function count(t)
    local n=0
    for _ in pairs(t) do n=n+1 end
    return n
end
local function capture_video_state(n)
    local prefix=string.format('state-%04d-',n)
    for _,name in ipairs({'vram_fg0','vram_fg1','vram_bg0','vram_bg1'}) do
        local share=assert(machine.memory.shares[':'..name], 'missing '..name)
        local f=assert(io.open(prefix..name..'.bin','wb'))
        for base=0,share.size-1,4096 do
            local bytes={}
            for i=base,math.min(base+4095,share.size-1) do
                bytes[#bytes+1]=string.char(share:read_u8(i))
            end
            f:write(table.concat(bytes))
        end
        f:close()
    end
    local f=assert(io.open(prefix..'io.bin','wb'))
    for offset=0,0x3e0,0x20 do f:write(string.pack('<I4',space:read_u32(0xc0000000+offset))) end
    f:close()
    -- Read back the DAC using its separate read pointer. The write pointer,
    -- palette and visible graphics are preserved; this is diagnostic capture.
    local old_read=space:read_u8(0x20000360)
    local pixel_mask=space:read_u8(0x20000340)
    space:write_u8(0x20000360,0)
    f=assert(io.open(prefix..'palette.bin','wb'))
    for i=1,768 do f:write(string.char(space:read_u8(0x20000320))) end
    f:close()
    space:write_u8(0x20000360,old_read)
    f=assert(io.open(prefix..'meta.txt','w'))
    f:write(string.format('%d %d %d %d\n',current_display,current_scroll0,current_scroll1,pixel_mask))
    f:close()
end
emu.register_frame_done(function()
    frame=frame+1
    if coin then coin:set_value(((frame>=360 and frame<370) or (frame>=420 and frame<430)) and 1 or 0) end
    if start then start:set_value(((frame>=450 and frame<480) or (frame>=930 and frame<960)) and 1 or 0) end
    if attack then attack:set_value((frame>=1000 and frame%12<6) and 1 or 0) end
    if right then right:set_value((frame>=1000 and frame<1700) and 1 or 0) end
    input_log:write(string.format('frame=%d p1=%08x\n',frame,machine.ioport.ports[':P1']:read()))
    if frame==350 or frame==600 or frame==900 or frame==1500 or frame==1800 then
        log_display('capture')
        screen:snapshot(string.format('mame_%04d.png',frame))
        capture_video_state(frame)
    end
    if frame==1800 then
        local f=assert(io.open('coverage.txt','w'))
        f:write(string.format('frames=%d\nregister_writes=%d\nodd_width_commands=%d\nflip_commands=%d\nshadow_commands=%d\npriority_modes=%d\nsource_scales=%d\ndestination_scales=%d\nretained_taps=%d\n',
            frame,writes,odd_widths,flips,shadows,count(modes),count(srcscale),count(dstscale),#taps))
        f:close()
        local a=assert(io.open('foreground_accesses.txt','w'))
        for key,value in pairs(foreground_accesses) do a:write(key..'='..value..'\n') end
        for _,example in ipairs(foreground_examples) do a:write(example..'\n') end
        a:close()
        local keys = {}
        for key in pairs(configurations) do keys[#keys+1] = key end
        table.sort(keys)
        local c = assert(io.open('configurations.txt','w'))
        for _, key in ipairs(keys) do c:write(key .. '\n') end
        c:close()
        -- Capture each source block as the TMS callback sees it: 256 DWORDs
        -- from a 0x4000-bit-address-aligned row, little endian.
        local s = assert(io.open('sprite_sources.bin','wb'))
        for row=0,511 do
            for word=0,255 do
                s:write(string.pack('<I4', space:read_u32(0xa8000000 +
                    row*0x4000 + word*0x20)))
            end
        end
        s:close()
        input_log:close()
        display_log:close()
        machine:exit()
    end
end)
