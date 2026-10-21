-- Break when execution reaches 0x874 (kernel pointer table) and dump the CPU state.
local ffi = require("ffi")
local LOG = io.open(os.getenv("REDUX_LOG") or "redux_bp.log", "w")
local function print(s) LOG:write(s, "\n"); LOG:flush() end
local names = { "zero", "at", "v0", "v1", "a0", "a1", "a2", "a3", "t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7",
  "s0", "s1", "s2", "s3", "s4", "s5", "s6", "s7", "t8", "t9", "k0", "k1", "gp", "sp", "fp", "ra" }
local mem = PCSX.getMemPtr()
local function rd(a) return ffi.cast("uint32_t*", mem + bit.band(a, 0x1ffffc))[0] end

local function dump(tag)
  local r = PCSX.getRegisters()
  local out = { tag, string.format("pc=%08x", r.pc) }
  for i = 0, 31 do out[#out + 1] = string.format("%s=%08x", names[i + 1], r.GPR.r[i]) end
  out[#out + 1] = string.format("sr=%08x cause=%08x epc=%08x", r.CP0.r[12], r.CP0.r[13], r.CP0.r[14])
  print(table.concat(out, " "))
  local sp = r.GPR.n.sp
  local s = {}
  for i = 0, 31 do s[#s + 1] = string.format("%08x", rd(sp + i * 4)) end
  print("stack " .. table.concat(s, " "))
end

for _, a in ipairs({ 0x00000874, 0x80000874, 0xa0000874 }) do
  PCSX.addBreakpoint(a, "Exec", 4, "jump to 0x874", function()
    dump("HIT874")
    PCSX.pauseEmulator()
    return false
  end)
end
print("bp874 armed")
