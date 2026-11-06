-- KKMap (WoW AI Chat): a colour strip in the top-left corner that the wowclaude bridge reads from the screen.
-- Format: 1 pixel per cell, 128 cells per row, 3 bytes (R,G,B) per cell, only as many rows as the data needs.
-- Cells 0..7 are fixed calibration colours, then: 4 bytes length (LE), 4 bytes checksum, then UTF-8 text lines:
--   #ver|n  #screen|w|h  #msg|seq|1|text  #edit|0/1  #ctx|...  name|type|text|x|y|w|h
-- The decoder (wowclaude/decode.py) finds the cell size itself. tests/ run this very file inside a fake WoW API.
local CELL, COLS, ROWS = 1, 128, 40
-- The button list is sent only with a question (so the AI can click in menus); /strip frames keeps it on permanently.
local MAGIC = {{255,0,255},{0,255,255},{255,255,0},{0,0,0},{255,255,255},{255,0,0},{0,255,0},{0,0,255}}
KKMapDB = KKMapDB or {}
local pending  -- set while a question waits for its answer (declared early: the frame scan reads it)
local DE = false  -- the whole addon speaks English
local function L(de, en) if DE then return de end return en end
local host = CreateFrame("Frame", "KKMapHost", UIParent)
host:SetFrameStrata("TOOLTIP"); host:SetFrameLevel(10000)
host:EnableMouse(false)
host:SetSize(COLS * CELL, ROWS * CELL)
local cells = {}

local function pxPerUnit()
  local _, ph = GetPhysicalScreenSize()
  return (ph / 768) * UIParent:GetEffectiveScale(), ph
end

local function layout()
  -- 1 Einheit in host = 1 physisches Pixel
  local _, ph = GetPhysicalScreenSize()
  host:SetScale(768 / (ph * UIParent:GetEffectiveScale()))
  host:ClearAllPoints()
  if KKMapDB.stripX then host:SetPoint("TOPLEFT", UIParent, "BOTTOMLEFT", KKMapDB.stripX, KKMapDB.stripY)
  else host:SetPoint("TOPLEFT", UIParent, "TOPLEFT", 3, -29) end  -- 3 px in: the gold frame stays fully visible
end

local function cell(i)
  local c = cells[i]
  if not c then
    c = host:CreateTexture(nil, "OVERLAY")
    c:SetSize(CELL, CELL)
    local col, row = i % COLS, math.floor(i / COLS)
    c:SetPoint("TOPLEFT", host, "TOPLEFT", col * CELL, -row * CELL)
    cells[i] = c
  end
  return c
end

local function setByte3(i, r, g, b)
  local c = cell(i); c:SetColorTexture(r / 255, g / 255, b / 255, 1); c:Show()
end

local function clean(s)
  s = tostring(s or ""):gsub("[|\n\r%[%]]", " ")
  return s:sub(1, 40)
end

local STRATA = { WORLD = 1, BACKGROUND = 2, LOW = 3, MEDIUM = 4, HIGH = 5, DIALOG = 6, FULLSCREEN = 7, FULLSCREEN_DIALOG = 8, TOOLTIP = 9 }

-- Secret values (restricted text of protected frames) cannot be compared or used: skip them instead of raising errors
local function usableText(t)
  if t == nil then return false end
  if issecretvalue and issecretvalue(t) then return false end
  local ok, res = pcall(function() return type(t) == "string" and t ~= "" end)
  return ok and res
end

local function labelOf(f)
  local ok, text = pcall(function() return f.GetText and f:GetText() end)
  if ok and usableText(text) then return text end
  if f.GetRegions then
    for _, r in ipairs({ f:GetRegions() }) do
      if r.GetObjectType and r:GetObjectType() == "FontString" then
        local okr, t = pcall(r.GetText, r)
        if okr and usableText(t) then return t end
      end
    end
  end
  return ""
end

local function ctxLine()
  local function c(v) return (tostring(v or "")):gsub("[|\n\r%[%]]", " ") end
  local xp, xpm = UnitXP("player") or 0, UnitXPMax("player") or 0
  local parts = {
    c(UnitName("player")), "Level " .. c(UnitLevel("player")), c((UnitClass("player"))),
    c(GetZoneText()), c(GetSubZoneText()), "XP " .. xp .. "/" .. xpm,
    "Copper " .. c(GetMoney()),
    UnitAffectingCombat("player") and "in combat" or "calm",
    "Pet " .. c(UnitName("pet") or "none"),
    "Client " .. c((GetBuildInfo())) .. " iface " .. c(select(4, GetBuildInfo())) .. " " .. c(GetLocale()),
  }
  return "#ctx|" .. table.concat(parts, "|")
end

local function safeCtx()
  local ok, r = pcall(ctxLine)
  if ok then return r end
  return "#ctx|Error " .. string.sub(tostring(r), 1, 120):gsub("|", "/")
end

local function collect()
  local _, ph = pxPerUnit()
  local pw = select(1, GetPhysicalScreenSize())
  local top = UIParent:GetTop() * UIParent:GetEffectiveScale() * (ph / 768)
  local entries = {}
  local f = (KKMapDB.frames or pending ~= nil) and EnumerateFrames() or nil
  local n = 0
  while f and n < 1500 do
    n = n + 1
    -- protected/restricted frames (secure UI, nameplates ...) refuse to be measured: never let that abort the whole scan
    local usable = false
    if f ~= host and f ~= UIParent and not (f.IsForbidden and f:IsForbidden()) and f.IsVisible and f.GetLeft then
      local okm, vis, left = pcall(function() return f:IsVisible(), f:GetLeft() end)
      usable = okm and vis and left and true or false
    end
    if usable then
      local typ = f.GetObjectType and f:GetObjectType() or "?"
      local clickable = (typ == "Button" or typ == "CheckButton" or typ == "EditBox" or typ == "Slider")
      if clickable and pcall(function() return f:GetTop(), f:GetWidth(), f:GetEffectiveScale() end) then
        local es = f:GetEffectiveScale() * (ph / 768)
        local w, h = f:GetWidth() * es, f:GetHeight() * es
        if w >= 6 and h >= 6 and w < pw and h < ph then
          local x = f:GetLeft() * es
          local y = top - f:GetTop() * es
          local name = f.GetName and f:GetName()
          local text = labelOf(f)
          if not name then
            local parent = f:GetParent()
            local pname = parent and parent.GetName and parent:GetName() or "?"
            name = "~" .. pname .. "@" .. math.floor(x + 0.5) .. "," .. math.floor(y + 0.5)
          end
          local sort = (STRATA[f:GetFrameStrata()] or 4) * 100000 + (f:GetFrameLevel() or 0)
          entries[#entries + 1] = { sort = sort, line = table.concat({ clean(name), typ, clean(text), math.floor(x + 0.5), math.floor(y + 0.5), math.floor(w + 0.5), math.floor(h + 0.5) }, "|") }
        end
      end
    end
    f = EnumerateFrames(f)
  end
  table.sort(entries, function(a, b) return a.sort > b.sort end)
  local lines = { "#ver|25", "#screen|" .. pw .. "|" .. ph, "#msg|" .. (KKMapState.seq or 0) .. "|" .. (KKMapState.idx or 0) .. "|" .. (KKMapState.out or ""), "#edit|" .. ((ChatEdit_GetActiveWindow and ChatEdit_GetActiveWindow()) and 1 or 0), safeCtx() }
  for i = 1, math.min(#entries, 300) do lines[#lines + 1] = entries[i].line end
  return table.concat(lines, "\n")
end

local usedRows = ROWS
local function render()
  layout()
  local text = collect()
  local maxBytes = COLS * ROWS * 3 - 8 * 3 - 8
  if #text > maxBytes then text = text:sub(1, maxBytes) end
  local sum = 0
  for i = 1, #text do sum = (sum * 31 + text:byte(i)) % 16777216 end
  local bytes = {}
  local len = #text
  for s = 0, 3 do bytes[#bytes + 1] = math.floor(len / 256 ^ s) % 256 end
  for s = 0, 3 do bytes[#bytes + 1] = math.floor(sum / 256 ^ s) % 256 end
  for i = 1, #text do bytes[#bytes + 1] = text:byte(i) end
  for i = 0, 7 do setByte3(i, MAGIC[i + 1][1], MAGIC[i + 1][2], MAGIC[i + 1][3]) end
  local total = COLS * ROWS
  local ci = 8
  for p = 1, #bytes, 3 do
    setByte3(ci, bytes[p] or 0, bytes[p + 1] or 0, bytes[p + 2] or 0)
    ci = ci + 1
  end
  for i = ci, total - 1 do if cells[i] then cells[i]:Hide() end end
  usedRows = math.ceil(ci / COLS)  -- the label box hangs right under the drawn pixels
end

KKMapState = KKMapState or { seq = 0, out = "", idx = 1 }
KKMapDB.n = KKMapDB.n or 0
local chatFrame

-- Streifen nur bei Bedarf sichtbar (Antwort offen, Chatbox offen, kurz nach Zustellung) + dezente Leiste darunter.
-- Die Leiste liegt NUR unter dem Streifen: Ursprung (0,0) und Zellen bleiben unberuehrt.
local holdUntil, stripOn, lastEdit = 0, true, false
local deco = CreateFrame("Frame", nil, host, "BackdropTemplate")
deco:SetPoint("BOTTOMLEFT", host, "TOPLEFT", 0, 0)  -- the text sits ABOVE the pixels
deco:SetSize(COLS * CELL, 25)  -- as wide as the strip: strip + label form one box
deco:SetBackdrop({ bgFile = "Interface\\Buttons\\WHITE8X8", edgeFile = "Interface\\Buttons\\WHITE8X8", edgeSize = 1 })
deco:SetBackdropColor(0.06, 0.05, 0.03, 0.85)
deco:SetBackdropBorderColor(0, 0, 0, 0)
-- one gold frame around pixels + label (drawn just OUTSIDE the pixel cells, so they stay untouched)
local box = CreateFrame("Frame", nil, host, "BackdropTemplate")
box:SetPoint("TOPLEFT", deco, "TOPLEFT", -1, 1)
box:SetPoint("BOTTOMRIGHT", host, "TOPLEFT", COLS * CELL + 1, -ROWS * CELL - 1)
box:SetBackdrop({ edgeFile = "Interface\\Buttons\\WHITE8X8", edgeSize = 1 })
box:SetBackdropBorderColor(0.85, 0.65, 0.2, 1)
deco.fs = deco:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
deco.fs:SetPoint("TOPLEFT", deco, "TOPLEFT", 4, -2)
deco.fs:SetTextColor(0.9, 0.8, 0.5)
deco.fs2 = deco:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
deco.fs2:SetPoint("TOPLEFT", deco, "TOPLEFT", 4, -13)
deco.fs2:SetTextColor(1, 0.55, 0.45)
deco.fs2:SetText("Do not cover!")
-- The strip can be dragged away from the corner (grab the label next to it): so the window or a tooltip over the corner
-- does not blind the program. Kept within reach of the program's search area.
deco:EnableMouse(true); deco:RegisterForDrag("LeftButton")
deco:SetScript("OnDragStart", function() deco.drag = true end)
deco:SetScript("OnDragStop", function() deco.drag = false end)
deco:SetScript("OnUpdate", function()
  if not deco.drag then return end
  local cx, cy = GetCursorPosition()
  local s = host:GetEffectiveScale()
  local x, y = cx / s - 40, cy / s - 13
  local top = UIParent:GetTop() * UIParent:GetEffectiveScale() / s
  x = math.max(0, math.min(x, 700)); y = math.max(top - 460, math.min(y, top))
  KKMapDB.stripX, KKMapDB.stripY = x, y
  host:ClearAllPoints(); host:SetPoint("TOPLEFT", UIParent, "BOTTOMLEFT", x, y)
end)
local function applyVisible()
  local ae = (ChatEdit_GetActiveWindow and ChatEdit_GetActiveWindow()) and true or false
  if lastEdit and not ae then holdUntil = math.max(holdUntil, GetTime() + 2) end
  lastEdit = ae
  local want = KKMapDB.always or pending ~= nil or ae or GetTime() < holdUntil
  if pending ~= nil then deco.fs:SetText("AI Bridge: thinking")
  elseif ae then deco.fs:SetText("AI Bridge: listening")
  else deco.fs:SetText("AI Bridge") end
  box:ClearAllPoints(); box:SetPoint("TOPLEFT", deco, "TOPLEFT", -1, 1)
  box:SetPoint("BOTTOMRIGHT", host, "TOPLEFT", COLS * CELL + 1, -usedRows * CELL - 1)
  if want and not stripOn then stripOn = true; host:SetAlpha(1); render()
  elseif not want and stripOn then stripOn = false; host:SetAlpha(0) end
end

-- The tab is always called TABNAME. The AI's own name (AI setup page, stored in Name.lua) is only who writes in it.
local TABNAME = "WoW AI"
local function aiName()
  local n = KKMapDB.aiName or KKAiName  -- renamed in the menu (instant) or Name.lua from the AI setup page (after /reload)
  if type(n) == "string" and n ~= "" then return n end
  return "WoW AI"
end
local function renameTab(frame, new)
  if not frame or frame == DEFAULT_CHAT_FRAME then return end
  pcall(function()
    if FCF_SetWindowName then FCF_SetWindowName(frame, new) end
    local tab = _G[frame:GetName() .. "Tab"]
    if tab and tab.SetText then tab:SetText(new) end
  end)
end
local function claudeFrame0()
  if chatFrame then return chatFrame end
  -- the tab may carry the previous name (the AI was renamed): find it by the name we used last, rename it, and never
  -- leave a second tab behind
  local olds = { [TABNAME] = true, [KKMapDB.tabName or "Claude"] = true, Claude = true }
  local found
  for i = 1, NUM_CHAT_WINDOWS do
    local name = GetChatWindowInfo(i)
    local fr = _G["ChatFrame" .. i]
    if name and olds[name] and fr and fr ~= DEFAULT_CHAT_FRAME then
      if not found then found = fr
      elseif FCF_Close then pcall(FCF_Close, fr) end  -- a leftover duplicate from an earlier rename
    end
  end
  if found then
    chatFrame = found
    renameTab(chatFrame, TABNAME)
    KKMapDB.tabName = TABNAME
    return chatFrame
  end
  local ok, f = pcall(FCF_OpenNewWindow, TABNAME)
  if not (ok and f) or f == DEFAULT_CHAT_FRAME then return nil end  -- never fall back to the normal chat: it would swallow every message
  chatFrame = f
  KKMapDB.tabName = TABNAME
  if FCF_SetChatWindowFontSize then pcall(FCF_SetChatWindowFontSize, nil, chatFrame, 16) end
  return chatFrame
end
-- Two small coloured squares on the tab's corners tell the overlay program where the tab is (and that it is shown).
local function addMarks(f)
  if not f or f == DEFAULT_CHAT_FRAME or f.kkMarks then return end
  f.kkMarks = true
  local function mark(point, x, r, g, b)  -- own frame on the top strata: other frames (unit frame, action bar) must not cover it
    local m = CreateFrame("Frame", nil, f)
    m:SetFrameStrata("TOOLTIP"); m:SetSize(4, 4); m:SetPoint(point, f, point, x, 0)
    local t = m:CreateTexture(nil, "OVERLAY")
    t:SetAllPoints(m); t:SetColorTexture(r, g, b, 1)
    return m
  end
  mark("TOPLEFT", 0, 1, 0, 1)
  mark("TOPRIGHT", 0, 0, 1, 1)
  -- the yellow mark sits "text size" units to the right of the left edge: that is how the overlay learns the size
  local y = mark("BOTTOMLEFT", 0, 1, 1, 0)
  local last
  local watch = CreateFrame("Frame")
  watch.t = 0
  watch:SetScript("OnUpdate", function(self, dt)
    self.t = self.t + dt
    if self.t < 0.5 then return end
    self.t = 0
    local _, size = f:GetFont()
    size = math.floor((size or 17) + 0.5)
    if size ~= last then last = size; y:ClearAllPoints(); y:SetPoint("BOTTOMLEFT", f, "BOTTOMLEFT", size, 0) end
  end)
end
-- The AI tab only shows what the AI says: message types, channels and colours do not apply to it. Take every message
-- group away from it (nothing foreign can leak into the tab) and grey the settings out so nobody tries to change them.
local function lockAiTab(f)
  if not f or f == DEFAULT_CHAT_FRAME or f.kkLocked then return end
  f.kkLocked = true
  pcall(function() if ChatFrame_RemoveAllMessageGroups then ChatFrame_RemoveAllMessageGroups(f) end end)
  pcall(function() if ChatFrame_RemoveAllChannels then ChatFrame_RemoveAllChannels(f) end end)
end
local function greyConfig()
  local cf = claudeFrame0()
  local cur = (FCF_GetCurrentChatFrame and FCF_GetCurrentChatFrame()) or SELECTED_CHAT_FRAME
  if not ChatConfigFrame or not ChatConfigFrame:IsShown() or not cur or cur ~= cf then
    if ChatConfigFrame and ChatConfigFrame.kkNote then ChatConfigFrame.kkNote:Hide() end
    return
  end
  local n = 0
  local function grey(region)
    local nm = region.GetName and region:GetName()
    local isSwatch = nm and nm:find("Color") and region.GetObjectType and region:GetObjectType() == "Button"
    if region.GetObjectType and (region:GetObjectType() == "CheckButton" or isSwatch) and region:IsEnabled() then
      pcall(function() region:Disable() end)
      region:SetAlpha(0.35)
      n = n + 1
    end
    if region.GetChildren then for _, c in ipairs({ region:GetChildren() }) do grey(c) end end
  end
  grey(ChatConfigFrame)
  if not ChatConfigFrame.kkNote then
    local fs = ChatConfigFrame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    fs:SetPoint("BOTTOM", ChatConfigFrame, "BOTTOM", 0, 14)
    ChatConfigFrame.kkNote = fs
  end
  ChatConfigFrame.kkNote:SetText("|cffffd100" .. TABNAME .. "|r tab: these settings do not apply (it only shows the AI).")
  ChatConfigFrame.kkNote:Show()
end
local lockWatcher = CreateFrame("Frame")
lockWatcher.t = 0
lockWatcher:SetScript("OnUpdate", function(self, dt)
  self.t = self.t + dt
  if self.t < 0.3 then return end
  self.t = 0
  if ChatConfigFrame and ChatConfigFrame:IsShown() then pcall(greyConfig) end
end)
local function claudeFrame()
  local f = claudeFrame0()
  addMarks(f)
  lockAiTab(f)
  return f
end
local function say(text, r, g, b)  -- notices only: the AI tab itself is painted by the overlay program
  DEFAULT_CHAT_FRAME:AddMessage(text, r or 0.6, g or 0.85, b or 1)
end

-- cut to n bytes without splitting a UTF-8 character
local function utf8cut(s, n)
  if #s <= n then return s end
  local i = n
  while i > 0 do
    local b = s:byte(i)
    if b < 0x80 then break end
    if b >= 0xC0 then
      local len = (b >= 0xF0 and 4) or (b >= 0xE0 and 3) or 2
      if i + len - 1 > n then return s:sub(1, i - 1) end
      break
    end
    i = i - 1
  end
  return s:sub(1, n)
end

local function sendToClaude(msg)
  msg = strtrim(msg or "")
  if msg == "" then say(L("Benutzung: einfach schreiben (im KI-Tab) oder /c Frage", "Usage: just type in the AI tab, or /c question")); return end
  local clean = msg:gsub("[|\n\r]", " ")
  if #clean > 230 then
    clean = utf8cut(clean, 230)
    say(L("Hinweis: Nachricht auf 230 Bytes gekuerzt.", "Note: message shortened to 230 bytes."), 1, 0.8, 0.4)
  end
  local seq = time()
  if seq <= (KKMapState.seq or 0) then seq = KKMapState.seq + 1 end
  KKMapState.seq, KKMapState.out, KKMapState.idx = seq, clean, 1
  pending = { seq = seq, t0 = GetTime() }
  stripOn = true; host:SetAlpha(1)
  render()
end

SLASH_KKCHAT1 = "/c"
SLASH_KKCHAT2 = "/ai"
SLASH_KKCHAT3 = "/claude"  -- old name, still works
SlashCmdList["KKCHAT"] = function(m) sendToClaude(m) end

-- Commands for the bridge ("!browser ..." is handled by wowclaude, not sent to the AI)
SLASH_KKTAB1 = "/aitab"
SLASH_KKTAB2 = "/claudetab"  -- old name, still works
SlashCmdList["KKTAB"] = function()  -- bring the AI tab to the front (used by tools that cannot click)
  local f = claudeFrame()
  if not f or f == DEFAULT_CHAT_FRAME then return end
  local ok = FCF_SelectDockFrame and pcall(FCF_SelectDockFrame, f)
  if not ok then
    local tab = _G[f:GetName() .. "Tab"]
    if tab and FCF_Tab_OnClick then pcall(FCF_Tab_OnClick, tab, "LeftButton") end
  end
end
SLASH_KKMEMORY1 = "/memos"
SLASH_KKMEMORY2 = "/memory"
SlashCmdList["KKMEMORY"] = function(msg) sendToClaude((("!memos " .. (msg or "")):gsub("%s+$", ""))) end
SLASH_KKHARNESS1 = "/harness"
SlashCmdList["KKHARNESS"] = function(msg)
  local w, v = strtrim(msg or ""):lower():match("^(%a+)%s*(%a*)$")
  if w == "wow" or w == "cli" then
    setOwnFlag(w, v)
    sendToClaude("!harness " .. w .. (v ~= "" and (" " .. v) or (KKMapDB and KKMapDB[w == "cli" and "ownCli" or "ownWow"] and " own" or " wow")))
  elseif KKHarnessFrame then
    if KKHarnessFrame:IsShown() then KKHarnessFrame:Hide() else KKHarnessFrame:Show() end
  end
end
SLASH_KKOL1 = "/ol"
SlashCmdList["KKOL"] = function() sendToClaude("!ol") end
SLASH_KKTERM1 = "/term"
SlashCmdList["KKTERM"] = function() sendToClaude("!term") end
SLASH_KKSCROLL1 = "/scroll"
SlashCmdList["KKSCROLL"] = function(msg) sendToClaude((("!scroll " .. (msg or "")):gsub("%s+$", ""))) end
SLASH_KKAIMODE1 = "/aimode"
local refreshLabels = function() end  -- replaced when the menu is built
local function stateOf(name)
  if KKMapDB and KKMapDB[name] == nil then KKMapDB[name] = (KKMapState and KKMapState[name]) and true or false end
  return KKMapDB and KKMapDB[name]
end
local function setOwnFlag(which, msg)
  local key = which == "cli" and "ownCli" or "ownWow"
  local m = strtrim(msg or ""):lower()
  if KKMapDB then
    if m == "own" then KKMapDB[key] = true elseif m == "wow" then KKMapDB[key] = false else KKMapDB[key] = not stateOf(key) end
  end
  refreshLabels()
end
local function setAccessFlag(msg)
  local m = strtrim(msg or ""):lower()
  if KKMapDB then
    if m == "on" or m == "1" or m == "yes" then KKMapDB.access = true
    elseif m == "off" or m == "0" or m == "no" then KKMapDB.access = false
    else KKMapDB.access = not stateOf("access") end
  end
  refreshLabels()
end
local function setCliFlag(msg)
  local m = strtrim(msg or ""):lower()
  if KKMapDB then
    if m == "cli" then KKMapDB.cli = true elseif m == "chat" then KKMapDB.cli = false else KKMapDB.cli = not stateOf("cli") end
  end
  refreshLabels()
end
SlashCmdList["KKAIMODE"] = function(msg) setCliFlag(msg); sendToClaude((("!aimode " .. (msg or "")):gsub("%s+$", ""))) end

-- Mouse wheel over the AI tab scrolls the terminal history in CLI mode (the game's own chat scrolling goes on as usual).
local lastWheel = 0
local function onWheel(self, delta)
  if not stateOf("cli") or not self or not self.GetID then return end
  local name = GetChatWindowInfo and GetChatWindowInfo(self:GetID())
  if not name or not name:lower():find("ai") then return end
  local now = GetTime()
  if now - lastWheel < 0.3 then return end
  lastWheel = now
  sendToClaude(delta > 0 and "!scroll up" or "!scroll down")
end
if FloatingChatFrame_OnMouseScroll then hooksecurefunc("FloatingChatFrame_OnMouseScroll", onWheel) end
if ChatFrame_OnMouseScroll then hooksecurefunc("ChatFrame_OnMouseScroll", onWheel) end
SLASH_KKKEY1 = "/k"
SlashCmdList["KKKEY"] = function(msg) sendToClaude((("!k " .. (msg or "")):gsub("%s+$", ""))) end

SLASH_KKACCESS1 = "/access"
SlashCmdList["KKACCESS"] = function(msg) setAccessFlag(msg); sendToClaude((("!access " .. (msg or "")):gsub("%s+$", ""))) end

SLASH_KKLOGIN1 = "/login"
SlashCmdList["KKLOGIN"] = function(msg) sendToClaude((("!login " .. (msg or "")):gsub("%s+$", ""))) end

SLASH_KKBROWSER1 = "/browser"
SLASH_KKBROWSER2 = "/wb"
SlashCmdList["KKBROWSER"] = function(msg)
  msg = strtrim(msg or "")
  if msg == "off" or msg == "close" then sendToClaude("!browser off")
  else sendToClaude((("!browser " .. msg):gsub("%s+$", ""))) end
end

-- Remember where a window was put (UIParent-relative, so it keeps its spot when the game window is resized)
local function savePos(f, key)
  local point, _, rel, x, y = f:GetPoint()
  KKMapDB.pos = KKMapDB.pos or {}
  KKMapDB.pos[key] = { point, rel, x, y }
end
local function restorePos(f, key)
  local p = KKMapDB.pos and KKMapDB.pos[key]
  if p then f:ClearAllPoints(); f:SetPoint(p[1], UIParent, p[2], p[3], p[4]) end
end

-- Rename the AI at any time: instant in the game, and the bridge learns it through "!name" (the answers carry it).
local function setAiName(n)
  n = strtrim(tostring(n or "")):gsub("[|\\\"]", ""):sub(1, 20)
  KKMapDB.aiName = (n ~= "") and n or nil
  sendToClaude("!name " .. n)
  say(L("KI-Name: ", "AI name: ") .. aiName(), 1, 0.82, 0)
end
StaticPopupDialogs["KKAINAME"] = {
  text = "Name of the AI (empty = WoW AI):", button1 = ACCEPT, button2 = CANCEL, hasEditBox = 1, maxLetters = 20,
  OnShow = function(self) local eb = self.editBox or self.EditBox; if eb then eb:SetText(KKMapDB.aiName or ""); eb:SetFocus() end end,
  OnAccept = function(self) local eb = self.editBox or self.EditBox; if eb then setAiName(eb:GetText()) end end,
  EditBoxOnEnterPressed = function(eb) setAiName(eb:GetText()); eb:GetParent():Hide() end,
  EditBoxOnEscapePressed = function(eb) eb:GetParent():Hide() end,
  timeout = 0, whileDead = 1, hideOnEscape = 1,
}
local function setPlayerName(n)
  n = strtrim(tostring(n or "")):gsub("[|\\\"]", ""):sub(1, 20)
  KKMapDB.playerName = (n ~= "") and n or nil
  sendToClaude("!me " .. n)
end
StaticPopupDialogs["KKPLAYERNAME"] = {
  text = "What should the AI call you? (empty = no name)", button1 = ACCEPT, button2 = CANCEL, hasEditBox = 1, maxLetters = 20,
  OnShow = function(self) local eb = self.editBox or self.EditBox; if eb then eb:SetText(KKMapDB.playerName or UnitName("player") or ""); eb:HighlightText(); eb:SetFocus() end end,
  OnAccept = function(self) local eb = self.editBox or self.EditBox; if eb then setPlayerName(eb:GetText()) end end,
  EditBoxOnEnterPressed = function(eb) setPlayerName(eb:GetText()); eb:GetParent():Hide() end,
  EditBoxOnEscapePressed = function(eb) eb:GetParent():Hide() end,
  timeout = 0, whileDead = 1, hideOnEscape = 1,
}
SLASH_KKME1 = "/nameme"
SLASH_KKME2 = "/kkme"  -- old name, still works
SlashCmdList["KKME"] = function(m) setPlayerName(m) end
SLASH_KKNAME1 = "/nameai"
SLASH_KKNAME2 = "/kkname"  -- old name, still works
SlashCmdList["KKNAME"] = function(m) setAiName(m) end

-- List of all commands (button "Commands" in the menu)
local COMMANDS = {
  "/wac  -  menu",
  "/ai text  (or /c text)  -  ask the AI",
  "/nameai name  -  rename the AI (empty = WoW AI)",
  "/nameme name  -  what the AI calls you (empty = no name)",
  "/browser [url]  -  open the browser  (/browser off = close)",
  "/aimode [chat|cli]  -  CLI mode: the tab shows your AI's own CLI",
  "/harness [wow|cli]  -  WoW AI harness or your AI's own, for the chat and the CLI separately",
  "/ol  -  open the overlay window (the AI shows lists and plans there)",
  "/term  -  open the CLI in a real window (scroll, copy, paste)",
  "/scroll up|down|end  -  look back in the CLI (or mouse wheel)",
  "/memos  -  what the AI saved about you  (/memos clear)",
  "/k up|down|enter|esc|tab|ctrl-c  -  send a key to the CLI",
  "/access [on|off]  -  let the AI use this computer (default: off)",
  "/login [code]  -  renew the AI login (page opens in the browser)",
  "/wm Name~Line1\nLine2  -  create a macro",
  "/strip always|auto|off  -  AI Bridge on / auto / off",
  "/strip move X Y  -  put the AI Bridge at pixel X,Y  |  /strip reset = corner",
  "/aitab  -  show the AI tab",
  "In the AI tab: just type, no /",
}
local cmdFrame = CreateFrame("Frame", "KKCmdFrame", UIParent, "BackdropTemplate")
cmdFrame:SetSize(420, 40 + #COMMANDS * 18)
cmdFrame:SetPoint("CENTER", UIParent, "CENTER", 0, 120)
cmdFrame:SetFrameStrata("DIALOG"); cmdFrame:SetMovable(true); cmdFrame:EnableMouse(true)
cmdFrame:RegisterForDrag("LeftButton"); cmdFrame:SetScript("OnDragStart", cmdFrame.StartMoving)
cmdFrame:SetScript("OnDragStop", cmdFrame.StopMovingOrSizing); cmdFrame:SetClampedToScreen(true)
cmdFrame:SetBackdrop({ bgFile = "Interface\\DialogFrame\\UI-DialogBox-Background", edgeFile = "Interface\\DialogFrame\\UI-DialogBox-Border",
  tile = true, tileSize = 32, edgeSize = 24, insets = { left = 6, right = 6, top = 6, bottom = 6 } })
local ct = cmdFrame:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge"); ct:SetPoint("TOPLEFT", 18, -14); ct:SetText("Commands")
for i, line in ipairs(COMMANDS) do
  local fs = cmdFrame:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  fs:SetPoint("TOPLEFT", 20, -34 - (i - 1) * 18); fs:SetJustifyH("LEFT"); fs:SetText(line)
end
local cc = CreateFrame("Button", nil, cmdFrame, "UIPanelCloseButton"); cc:SetPoint("TOPRIGHT", -4, -4)
cmdFrame:Hide()

-- Tips (button "Tips" in the menu)
local TIPS = {
  "NEVER cover these: the AI Bridge (text on top, coloured pixels",
  "below) and the 3 coloured pixels in the corners of the chat",
  "window (AI tab). No window, browser, map or tooltip on top of",
  "them. Otherwise your question does not arrive and the answer",
  "disappears.",
  " ",
  "Move the AI Bridge: drag its text bar (above the pixels) with",
  "the left mouse button. Back to the corner: /strip reset.",
  "Best place: the very top, outside your windows.",
  " ",
  "The AI tab can be moved and resized freely.",
  "Harness menu example: WoW chat = WoW AI (Warcraft help), CLI = Own: your local AI with its own setup works on your projects.",
  "Play in windowed or borderless mode, not fullscreen.",
  " ",
  "Login expired? The sign-in page opens by itself in the game",
  "browser (or type /login). One login covers chat and CLI mode.",
  "Longer lasting: create a one-year token with your AI's CLI",
  "(see the AI setup page) and paste it there",
  "(AI token). Or use 'Let my own AI set this up' there.",
}
local tipFrame = CreateFrame("Frame", "KKTipFrame", UIParent, "BackdropTemplate")
tipFrame:SetSize(430, 44 + #TIPS * 16)
tipFrame:SetPoint("CENTER", UIParent, "CENTER", 0, 80)
tipFrame:SetFrameStrata("DIALOG"); tipFrame:SetMovable(true); tipFrame:EnableMouse(true)
tipFrame:RegisterForDrag("LeftButton"); tipFrame:SetScript("OnDragStart", tipFrame.StartMoving)
tipFrame:SetScript("OnDragStop", tipFrame.StopMovingOrSizing); tipFrame:SetClampedToScreen(true)
tipFrame:SetBackdrop({ bgFile = "Interface\\DialogFrame\\UI-DialogBox-Background", edgeFile = "Interface\\DialogFrame\\UI-DialogBox-Border",
  tile = true, tileSize = 32, edgeSize = 24, insets = { left = 6, right = 6, top = 6, bottom = 6 } })
local tt = tipFrame:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge"); tt:SetPoint("TOPLEFT", 18, -14); tt:SetText("Tips")
for i, line in ipairs(TIPS) do
  local fs = tipFrame:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  fs:SetPoint("TOPLEFT", 20, -36 - (i - 1) * 16); fs:SetJustifyH("LEFT"); fs:SetText(line)
end
local tc = CreateFrame("Button", nil, tipFrame, "UIPanelCloseButton"); tc:SetPoint("TOPRIGHT", -4, -4)
tipFrame:Hide()

-- Tools and skills the AI has (button "Tools" in the menu)
local TOOLS = {
  "TOOLS",
  "Macro maker  -  the AI writes a real macro onto your cursor",
  "Overlay window  -  lists, builds, plans in its own window",
  "Show window  -  pictures, video, music, PDF, text: the AI shows",
  "    them in a small window without browser bar (screenshots work)",
  "Browser over the game  -  video, guide, wiki (ghost mode =",
  "    see-through and click-through; minimize = WAC button)",
  "Mouse and keyboard  -  the AI clicks and types for you",
  "    (switch on: AI setup page, Mouse and keyboard)",
  "Web research  -  looks facts up before it answers",
  "CLI mode  -  the tab runs your AI's own CLI",
  "    (/aimode cli; keys: /k up|down|enter|esc|tab|ctrl-c)",
  "Login helper  -  /login renews an expired AI login",
  "Computer access  -  YOUR choice (menu: AI access): the AI may",
  "    read/change files and run commands, like the original CLI",
  " ",
  "SKILLS",
  "Game version aware  -  Forever is not Classic; it knows which",
  "    client you play (Classic Era, TBC, Wrath, Cata, MoP, Retail)",
  "Character aware  -  notices when you switch characters",
  "Leveling macros, class builds, quest and trainer help",
  "Video guides  -  finds and opens them in the browser window",
  "Your own harness  -  edit what the AI is told: menu Harness",
}
local toolsFrame = CreateFrame("Frame", "KKToolsFrame", UIParent, "BackdropTemplate")
toolsFrame:SetSize(430, 44 + #TOOLS * 16)
toolsFrame:SetPoint("CENTER", UIParent, "CENTER", 0, 60)
toolsFrame:SetFrameStrata("DIALOG"); toolsFrame:SetMovable(true); toolsFrame:EnableMouse(true)
toolsFrame:RegisterForDrag("LeftButton"); toolsFrame:SetScript("OnDragStart", toolsFrame.StartMoving)
toolsFrame:SetScript("OnDragStop", toolsFrame.StopMovingOrSizing); toolsFrame:SetClampedToScreen(true)
toolsFrame:SetBackdrop({ bgFile = "Interface\\DialogFrame\\UI-DialogBox-Background", edgeFile = "Interface\\DialogFrame\\UI-DialogBox-Border",
  tile = true, tileSize = 32, edgeSize = 24, insets = { left = 6, right = 6, top = 6, bottom = 6 } })
local tlt = toolsFrame:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge"); tlt:SetPoint("TOPLEFT", 18, -14); tlt:SetText("Tools and skills")
for i, line in ipairs(TOOLS) do
  local fs = toolsFrame:CreateFontString(nil, "OVERLAY", (line == "TOOLS" or line == "SKILLS") and "GameFontNormal" or "GameFontHighlightSmall")
  fs:SetPoint("TOPLEFT", 20, -36 - (i - 1) * 16); fs:SetJustifyH("LEFT"); fs:SetText(line)
end
local tlc = CreateFrame("Button", nil, toolsFrame, "UIPanelCloseButton"); tlc:SetPoint("TOPRIGHT", -4, -4)
toolsFrame:Hide()

-- Harness submenu: WoW AI harness or the AI's own setup, separately for the game chat and the CLI
local harnessFrame = CreateFrame("Frame", "KKHarnessFrame", UIParent, "BackdropTemplate")
harnessFrame:SetSize(300, 212); harnessFrame:SetPoint("CENTER", UIParent, "CENTER", 0, 60)
harnessFrame:SetFrameStrata("DIALOG"); harnessFrame:SetMovable(true); harnessFrame:EnableMouse(true)
harnessFrame:RegisterForDrag("LeftButton"); harnessFrame:SetScript("OnDragStart", harnessFrame.StartMoving)
harnessFrame:SetScript("OnDragStop", harnessFrame.StopMovingOrSizing); harnessFrame:SetClampedToScreen(true)
harnessFrame:SetBackdrop({ bgFile = "Interface\\DialogFrame\\UI-DialogBox-Background", edgeFile = "Interface\\DialogFrame\\UI-DialogBox-Border",
  tile = true, tileSize = 32, edgeSize = 24, insets = { left = 6, right = 6, top = 6, bottom = 6 } })
local hft = harnessFrame:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge"); hft:SetPoint("TOPLEFT", 18, -14); hft:SetText("Harness")
local hfc = CreateFrame("Button", nil, harnessFrame, "UIPanelCloseButton"); hfc:SetPoint("TOPRIGHT", -4, -4)
local hfn = harnessFrame:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall"); hfn:SetPoint("TOPLEFT", 20, -148)
hfn:SetWidth(260); hfn:SetJustifyH("LEFT")
hfn:SetText("Own = your AI's own memory files, settings and tools (CLI: work on your own projects). WoW AI = the Warcraft harness.")
local hWow = CreateFrame("Button", nil, harnessFrame, "UIPanelButtonTemplate"); hWow:SetSize(260, 26); hWow:SetPoint("TOP", 0, -42)
local hCli = CreateFrame("Button", nil, harnessFrame, "UIPanelButtonTemplate"); hCli:SetSize(260, 26); hCli:SetPoint("TOP", 0, -74)
local hEdit = CreateFrame("Button", nil, harnessFrame, "UIPanelButtonTemplate"); hEdit:SetSize(260, 26); hEdit:SetPoint("TOP", 0, -106)
hEdit:SetText("Edit harness text"); hEdit:SetScript("OnClick", function() sendToClaude("!harness edit") end)
hWow:SetScript("OnClick", function() SlashCmdList["KKHARNESS"]("wow") end)
hCli:SetScript("OnClick", function() SlashCmdList["KKHARNESS"]("cli") end)
local function harnessLabels()
  local Y, G = "|cffffd100", "|cff808080"
  local w, c = stateOf("ownWow"), stateOf("ownCli")
  hWow:SetText("WoW chat:  " .. (w and G or Y) .. "WoW AI|r / " .. (w and Y or G) .. "Own|r")
  hCli:SetText("CLI:  " .. (c and G or Y) .. "WoW AI|r / " .. (c and Y or G) .. "Own|r")
end
harnessFrame:SetScript("OnShow", harnessLabels)
harnessFrame:Hide()
local baseRefresh = refreshLabels

-- Small addon menu (/wac)
local menu
local function buildMenu()
  if menu then return menu end
  local f = CreateFrame("Frame", "KKMenuFrame", UIParent, "BackdropTemplate")
  f:SetSize(220, 444)
  f:SetPoint("CENTER", UIParent, "CENTER", -260, 60)
  f:SetFrameStrata("DIALOG")
  f:SetMovable(true); f:EnableMouse(true); f:RegisterForDrag("LeftButton")
  f:SetScript("OnDragStart", f.StartMoving)
  f:SetScript("OnDragStop", function(self) self:StopMovingOrSizing(); savePos(self, "menu") end)
  f:SetClampedToScreen(true)
  restorePos(f, "menu")
  f:SetBackdrop({
    bgFile = "Interface\\DialogFrame\\UI-DialogBox-Background",
    edgeFile = "Interface\\DialogFrame\\UI-DialogBox-Border",
    tile = true, tileSize = 32, edgeSize = 24,
    insets = { left = 6, right = 6, top = 6, bottom = 6 },
  })
  local title = f:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
  title:SetPoint("TOPLEFT", 18, -16)
  title:SetText("WoW AI Chat")
  local close = CreateFrame("Button", nil, f, "UIPanelCloseButton")
  close:SetPoint("TOPRIGHT", -4, -4)
  local y = -48
  local function button(text, onClick)
    local bt = CreateFrame("Button", nil, f, "UIPanelButtonTemplate")
    bt:SetSize(184, 26)
    bt:SetPoint("TOP", f, "TOP", 0, y)
    bt:SetText(text)
    bt:SetScript("OnClick", onClick)
    y = y - 32
    return bt
  end
  button("Connect AI", function() sendToClaude("!setup") end)
  button("Browser", function() sendToClaude("!browser") end)
  button("CLI window", function() sendToClaude("!term") end)
  button("AI name", function() StaticPopup_Show("KKAINAME") end)
  button("Your name", function() StaticPopup_Show("KKPLAYERNAME") end)
  local stripBtn
  local function stripLabel() return "AI Bridge: " .. (KKMapDB.always and "always on" or "auto") end
  stripBtn = button(stripLabel(), function()
    KKMapDB.always = not KKMapDB.always
    KKMapDB.off = false
    stripBtn:SetText(stripLabel())
    if applyVisible then applyVisible() end
  end)
  local YEL, GREY = "|cffffd100", "|cff808080"
  local modeBtn = button("", function() setCliFlag(""); sendToClaude("!aimode") end)
  local accessBtn = button("", function() setAccessFlag(""); sendToClaude("!access") end)
  refreshLabels = function()
    local cli, acc = stateOf("cli"), stateOf("access")
    modeBtn:SetText("Chat mode:  " .. (cli and GREY or YEL) .. "WoW|r / " .. (cli and YEL or GREY) .. "CLI|r")
    accessBtn:SetText("AI access:  " .. (acc and YEL or GREY) .. "ON|r / " .. (acc and GREY or YEL) .. "OFF|r")
    harnessLabels()
  end
  refreshLabels()
  button("Harness", function() SlashCmdList["KKHARNESS"]("") end)
  button("Tools", function() if KKToolsFrame:IsShown() then KKToolsFrame:Hide() else KKToolsFrame:Show() end end)
  button("Tips", function() if KKTipFrame:IsShown() then KKTipFrame:Hide() else KKTipFrame:Show() end end)
  button("Commands", function() if KKCmdFrame:IsShown() then KKCmdFrame:Hide() else KKCmdFrame:Show() end end)
  f:Hide()
  menu = f
  return f
end
SLASH_KKMENU1 = "/wac"
SLASH_KKMENU2 = "/kkmenu"
SlashCmdList["KKMENU"] = function()
  local f = buildMenu()
  if f:IsShown() then f:Hide() else f:Show() end
end

-- Invisible click field in the bottom left corner of the screen: the gear on the WAC button (a program window outside the
-- game) posts a mouse click there, which opens the menu. No typing, no focus needed.
local gearHit = CreateFrame("Button", "KKGearHit", UIParent)
gearHit:SetFrameStrata("TOOLTIP")
gearHit:SetSize(24, 24)
gearHit:SetPoint("BOTTOMLEFT", UIParent, "BOTTOMLEFT", 0, 0)
gearHit:RegisterForClicks("LeftButtonUp")
gearHit:SetScript("OnClick", function() SlashCmdList["KKMENU"]() end)

-- Create or update a macro (name <= 16 chars, body <= 255 chars) and put it on the cursor.
local function createMacro(name, body, perChar)
  name = strtrim(tostring(name or "")):sub(1, 16)
  body = tostring(body or ""):gsub("\\n", "\n")
  if name == "" or body == "" then return false end
  if #body > 255 then say("KKMap: macro '" .. name .. "' too long (" .. #body .. "/255)", 1, 0.4, 0.4) return false end
  local idx = GetMacroIndexByName(name)
  if idx and idx > 0 then
    local ok, err = pcall(EditMacro, idx, name, nil, body)
    if not ok then say("KKMap: macro error: " .. tostring(err), 1, 0.4, 0.4) return false end
  else
    local ok, err = pcall(CreateMacro, name, "INV_MISC_QUESTIONMARK", body, perChar and true or false)
    if not ok then say("KKMap: macro error: " .. tostring(err), 1, 0.4, 0.4) return false end
  end
  local mi = GetMacroIndexByName(name)
  if mi and mi > 0 then pcall(PickupMacro, mi) end
  say("KKMap: macro '" .. name .. "' ready (" .. #body .. "/255). It is on your cursor: click an action bar slot, or find it in /macro.", 0.6, 1, 0.6)
  return true
end

-- The answer comes back through the overlay program, not through the game: the question only has to stay in the strip
-- long enough for the bridge to read it.
local function poll()
  if not pending then return end
  local age = GetTime() - pending.t0
  if age > 8 and not pending.read then pending.read = true; holdUntil = GetTime() + 2 end
  if age > 30 then  -- a busy bridge reads it right after its current answer; after that the text must not linger
    pending = nil
    KKMapState.out = ""  -- or it would be answered minutes later, when the strip shows up again
  end
end

local function isClaudeBox(eb)
  local cf = claudeFrame()
  if not eb or not cf then return false end
  if eb.chatFrame and eb.chatFrame == cf then return true end
  return eb:GetName() == cf:GetName() .. "EditBox"
end

-- Im Tab "Claude": normaler Text (ohne /) geht direkt an Claude
local function hookEditBoxes()
  for i = 1, NUM_CHAT_WINDOWS do
    local eb = _G["ChatFrame" .. i .. "EditBox"]
    if eb and not eb.kkHooked then
      eb.kkHooked = true
      eb:HookScript("OnShow", function(self)
        if isClaudeBox(self) then
          local function fix()
            local h = _G[self:GetName() .. "Header"]
            if not h then
              for _, r in ipairs({ self:GetRegions() }) do
                if r.GetObjectType and r:GetObjectType() == "FontString" then h = r; break end
              end
            end
            if h and h.SetText then h:SetText(aiName() .. ": "); self:SetTextInsets(h:GetStringWidth() + 18, 13, 0, 0) end
          end
          pcall(fix)
          if C_Timer and C_Timer.After then C_Timer.After(0, function() pcall(fix) end); C_Timer.After(0.1, function() pcall(fix) end) end
        end
      end)
      -- the handler only acts when the box currently belongs to the Claude tab (isClaudeBox); otherwise it
      -- calls the original handler unchanged. Kept on every box because some clients share one box between tabs.
      local orig = eb:GetScript("OnEnterPressed")
      eb:SetScript("OnEnterPressed", function(self, ...)
        local text = self:GetText() or ""
        if isClaudeBox(self) and text ~= "" and text:sub(1, 1) ~= "/" then
          local ok, err = pcall(sendToClaude, text)
          if not ok then say("KKMap Fehler: " .. tostring(err), 1, 0.4, 0.4) end
          pcall(function() if self.AddHistoryLine then self:AddHistoryLine(text) end end)
          pcall(function() self:SetText("") end)
          local okc = pcall(ChatEdit_OnEscapePressed, self)
          if not okc then pcall(function() self:ClearFocus() end) end
          return
        end
        if orig then return orig(self, ...) end
      end)
    end
  end
end

-- Im Claude-Tab zeigt die Eingabezeile "Claude:" statt "Sagen:"
if hooksecurefunc and ChatEdit_UpdateHeader then
  hooksecurefunc("ChatEdit_UpdateHeader", function(eb)
    pcall(function()
      if isClaudeBox(eb) then
        local h = _G[eb:GetName() .. "Header"]
        if h then
          h:SetText(aiName() .. ": ")
          eb:SetTextInsets(h:GetWidth() + 13, 13, 0, 0)
        end
      end
    end)
  end)
end

-- Eingabezeile im Claude-Tab beschriften: nach jedem Oeffnen der Chatbox (mehrere Wege, falls einer in diesem Client fehlt)
local function relabel(eb)
  if not isClaudeBox(eb) then return end
  local function fix()
    local h = _G[eb:GetName() .. "Header"]
    if h and h.SetText then h:SetText(aiName() .. ": "); eb:SetTextInsets(h:GetStringWidth() + 18, 13, 0, 0) end
  end
  pcall(fix)
  if C_Timer and C_Timer.After then
    C_Timer.After(0, function() pcall(fix) end)
    C_Timer.After(0.15, function() pcall(fix) end)
  end
end
if hooksecurefunc then
  for _, fname in ipairs({ "ChatEdit_ActivateChat", "ChatEdit_UpdateHeader", "ChatEdit_SetLastActiveWindow" }) do
    if _G[fname] then pcall(hooksecurefunc, fname, relabel) end
  end
end

-- Zuverlaessigster Weg: kurzer Ticker passt die Beschriftung an, solange die Claude-Eingabezeile offen ist
if C_Timer and C_Timer.NewTicker then
  C_Timer.NewTicker(0.15, function()
    local cf = claudeFrame()
    local eb = cf and _G[cf:GetName() .. "EditBox"]
    if not eb or not eb:IsShown() then return end
    local h = _G[eb:GetName() .. "Header"]
    if h and h:GetText() ~= aiName() then
      h:SetText(aiName())
      local suf = _G[eb:GetName() .. "HeaderSuffix"]
      eb:SetTextInsets(h:GetStringWidth() + ((suf and suf:GetStringWidth()) or 8) + 13, 13, 0, 0)
    end
  end)
end

local acc = 0
host:SetScript("OnUpdate", function(_, dt)
  acc = acc + dt
  poll()
  if acc >= 0.4 then acc = 0; if not KKMapDB.off then pcall(applyVisible); if stripOn then render() end end end
end)

SLASH_KKMAP1 = "/strip"
SLASH_KKMAP2 = "/kkmap"
-- /kkm Name~Text mit \n als Zeilenumbruch  (optional  Name~Text~char  = nur dieser Charakter)
SLASH_KKMACRO1 = "/wm"
SLASH_KKMACRO2 = "/kkm"
SlashCmdList["KKMACRO"] = function(msg)
  local name, body, scope = strsplit("~", msg or "", 3)
  if not name or name == "" or not body or body == "" then say("KKMap: /kkm Name~Text (\\n = newline)") return end
  createMacro(name, body, scope == "char")
end

SLASH_KKMAP1 = "/strip"
SLASH_KKMAP2 = "/kkmap"
SlashCmdList["KKMAP"] = function(msg)
  if msg == "frames" then KKMapDB.frames = not KKMapDB.frames; print("KKMap: button list " .. (KKMapDB.frames and "on" or "off")) return end
  local mx, my = msg:match("^move%s+(%d+)%s+(%d+)$")
  if mx then  -- /strip move X Y : place the strip X, Y pixels from the top-left corner (same thing as dragging it)
    local sc = host:GetEffectiveScale()
    local top = UIParent:GetTop() * UIParent:GetEffectiveScale() / sc
    KKMapDB.stripX, KKMapDB.stripY = math.min(tonumber(mx), 700), top - math.min(tonumber(my), 460)
    layout(); return
  end
  if msg == "reset" then KKMapDB.stripX, KKMapDB.stripY = nil, nil; layout(); print("KKMap: strip back in the corner") return end
  if msg == "always" then KKMapDB.always = true; KKMapDB.off = false; host:Show(); host:SetAlpha(1); stripOn = true; render(); print("KKMap: strip always visible") return end
  if msg == "auto" then KKMapDB.always = false; KKMapDB.off = false; host:Show(); print("KKMap: strip only when needed") return end
  if msg == "off" then KKMapDB.off = true; host:Hide()
  else KKMapDB.off = false; host:Show(); render() end
  print("KKMap: " .. (KKMapDB.off and "aus" or "an"))
end
local ev = CreateFrame("Frame")
ev:RegisterEvent("PLAYER_LOGIN")
ev:SetScript("OnEvent", function()
  claudeFrame()  -- creates / finds the AI tab and puts the corner marks on it
  hookEditBoxes()
  if KKMapDB.off then host:Hide() else render() end
end)
