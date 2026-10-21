-- PCSX-Redux driver: press pad buttons on a schedule and save screenshots.
-- usage: pcsx-redux -portable -iso <cue> -bios <bios> -run -dofile redux_route.lua
-- Steps are {seconds to wait before, action, arg}; "press" taps a button, "shot" writes
-- <OUT>/<name>.raw plus <name>.txt (width height bpp). Times are host UI frames (60/s).
local OUT = os.getenv("REDUX_OUT") or "."
local B = PCSX.CONSTS.PAD.BUTTON
local pad = PCSX.SIO0.slots[1].pads[1]

local steps = {}
local function add(wait, action, arg) steps[#steps + 1] = { wait = wait, action = action, arg = arg } end
local function press(wait, b) add(wait, "press", b) end

-- title -> NEW GAME -> name entry (down x7, ok) -> main menu
add(28, "shot", "00_title")
press(0, "CIRCLE"); press(3, "CIRCLE")
for _ = 1, 7 do press(0.4, "DOWN") end
press(1, "CIRCLE")
add(4, "shot", "01_menu")
-- plan: summer, partner (movies play out), peak I, route decided
press(0, "DOWN"); press(0.5, "DOWN"); press(0.5, "CIRCLE")
press(4, "CIRCLE")
add(40, "shot", "02_after_summer_movie")
press(0, "CIRCLE")
add(40, "shot", "03_after_partner_movie")
press(0, "CIRCLE")
press(4, "DOWN"); press(0.4, "DOWN"); press(0.4, "CIRCLE")
add(4, "shot", "04_plan")
for _ = 1, 30 do press(2.5, "CIRCLE") end
press(2, "CROSS")
add(2, "shot", "05_menu_with_plan")
-- go to the mountain and watch
press(0, "DOWN"); press(0.4, "DOWN"); press(0.4, "DOWN"); press(0.5, "CIRCLE")
for i = 1, 12 do add(10, "shot", string.format("06_mountain_%02d", i)) end

local idx, timer, held = 1, 0, nil
local function shot(name)
  local s = PCSX.GPU.takeScreenShot()
  local f = Support.File.open(OUT .. "/" .. name .. ".raw", "TRUNCATE")
  local w, h, bpp = s.width, s.height, s.bpp
  f:writeMoveSlice(s.data)
  f:close()
  local t = Support.File.open(OUT .. "/" .. name .. ".txt", "TRUNCATE")
  t:write(string.format("%d %d %d\n", w, h, bpp == 0 and 16 or 24))
  t:close()
  print("shot " .. name)
end

function DrawImguiFrame()
  if held then
    held.n = held.n - 1
    if held.n <= 0 then pad.clearOverride(B[held.b]); held = nil end
    return
  end
  local st = steps[idx]
  if not st then return end
  timer = timer + 1
  if timer < st.wait * 60 then return end
  timer = 0
  idx = idx + 1
  if st.action == "press" then
    pad.setOverride(B[st.arg]); held = { b = st.arg, n = 6 }
  elseif st.action == "shot" then
    shot(st.arg)
  end
end
