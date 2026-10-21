-- Log the first writes into the kernel call stubs (0xA0-0xCF) with the CPU state.
local LOG = io.open(os.getenv("REDUX_LOG") or "redux_bp.log", "w")
local function log(s) LOG:write(s, "\n"); LOG:flush() end
local n = 0
for _, base in ipairs({ 0x000000a0, 0x800000a0, 0xa00000a0 }) do
  if base ~= 0x000000a0 then goto continue end
  PCSX.addBreakpoint(base, "Write", 0x30, "kernel stub write", function(address, width)
    local r = PCSX.getRegisters()
    if r.pc >= 0xbfc00000 and r.pc < 0xbfc80000 then return true end
    n = n + 1
    log(string.format("write %08x w%d pc=%08x ra=%08x sp=%08x sr=%08x a0=%08x a1=%08x v0=%08x t0=%08x",
      address, width, r.pc, r.GPR.n.ra, r.GPR.n.sp, r.CP0.r[12], r.GPR.n.a0, r.GPR.n.a1, r.GPR.n.v0, r.GPR.n.t0))
    if n >= 30 then return false end
  end)
  ::continue::
end
log("armed")
