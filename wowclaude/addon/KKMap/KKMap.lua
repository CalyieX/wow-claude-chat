-- KKMap: Farbstreifen oben links mit allen sichtbaren Frames (Pixelkoordinaten, Fenster-Client-Ursprung oben links).
-- Format: Zellen 4x4 Pixel, 128 Zellen pro Zeile, 3 Bytes (R,G,B) pro Zelle.
-- Zellen 0..7 = feste Kalibrierfarben, danach: 4 Byte Länge (LE), 4 Byte Prüfsumme, dann UTF-8-Text.
-- Textzeilen: name|typ|text|x|y|b|h   (Pixel). Erste Zeile: #screen|breite|höhe
-- The strip is tiny: 1 pixel per cell, 128 cells per row, only as many rows as the data needs (about 4).
-- The decoder detects the cell size itself, so this can be changed (2 is more robust on odd UI scales).
local CELL, COLS, ROWS = 1, 128, 40
-- The chat bridge does not need the list of clickable buttons; /kkmap frames turns it on for tools that do.
local MAGIC = {{255,0,255},{0,255,255},{255,255,0},{0,0,0},{255,255,255},{255,0,0},{0,255,0},{0,0,255}}
KKMapDB = KKMapDB or {}
local DE = GetLocale() == "deDE"
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
  host:ClearAllPoints(); host:SetPoint("TOPLEFT", UIParent, "TOPLEFT", 0, 0)
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
  s = tostring(s or ""):gsub("[|\n\r]", " ")
  return s:sub(1, 40)
end

local STRATA = { WORLD = 1, BACKGROUND = 2, LOW = 3, MEDIUM = 4, HIGH = 5, DIALOG = 6, FULLSCREEN = 7, FULLSCREEN_DIALOG = 8, TOOLTIP = 9 }

local function labelOf(f)
  local text = f.GetText and f:GetText()
  if text and text ~= "" then return text end
  if f.GetRegions then
    for _, r in ipairs({ f:GetRegions() }) do
      if r.GetObjectType and r:GetObjectType() == "FontString" then
        local t = r:GetText()
        if t and t ~= "" then return t end
      end
    end
  end
  return ""
end

KKImgNext = KKImgNext or 1
KKSlotNext = KKSlotNext or 1

local function ctxLine()
  local function c(v) return (tostring(v or "")):gsub("[|\n\r]", " ") end
  local xp, xpm = UnitXP("player") or 0, UnitXPMax("player") or 0
  local parts = {
    c(UnitName("player")), "Stufe " .. c(UnitLevel("player")), c((UnitClass("player"))),
    c(GetZoneText()), c(GetSubZoneText()), "XP " .. xp .. "/" .. xpm,
    "Kupfer " .. c(GetMoney()),
    UnitAffectingCombat("player") and "im Kampf" or "ruhig",
    "Pet " .. c(UnitName("pet") or "keins"),
  }
  return "#ctx|" .. table.concat(parts, "|")
end

local function safeCtx()
  local ok, r = pcall(ctxLine)
  if ok then return r end
  return "#ctx|Fehler " .. string.sub(tostring(r), 1, 120):gsub("|", "/")
end

local function collect()
  local _, ph = pxPerUnit()
  local pw = select(1, GetPhysicalScreenSize())
  local top = UIParent:GetTop() * UIParent:GetEffectiveScale() * (ph / 768)
  local entries = {}
  local f = KKMapDB.frames and EnumerateFrames() or nil
  local n = 0
  while f and n < 1500 do
    n = n + 1
    if f ~= host and f ~= UIParent and f.IsVisible and f:IsVisible() and f.GetLeft and f:GetLeft() then
      local typ = f.GetObjectType and f:GetObjectType() or "?"
      local clickable = (typ == "Button" or typ == "CheckButton" or typ == "EditBox" or typ == "Slider")
      if clickable then
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
  local lines = { "#ver|25", "#screen|" .. pw .. "|" .. ph, "#msg|" .. (KKMapState.seq or 0) .. "|" .. (KKMapState.idx or 0) .. "|" .. (KKMapState.out or ""), "#ack|" .. (KKMapState.ack or 0), "#edit|" .. ((ChatEdit_GetActiveWindow and ChatEdit_GetActiveWindow()) and 1 or 0), safeCtx(), "#img|" .. KKImgNext, "#slot|" .. KKSlotNext }
  for i = 1, math.min(#entries, 300) do lines[#lines + 1] = entries[i].line end
  return table.concat(lines, "\n")
end

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
end

KKMapState = KKMapState or { seq = 0, out = "", idx = 0, ack = 0 }
KKMapDB.n = KKMapDB.n or 0
local SIG = "Interface\\AddOns\\KKMap\\sig\\"
local chatFrame
local pending
local nextSlot = 1

-- Streifen nur bei Bedarf sichtbar (Antwort offen, Chatbox offen, kurz nach Zustellung) + dezente Leiste darunter.
-- Die Leiste liegt NUR unter dem Streifen: Ursprung (0,0) und Zellen bleiben unberuehrt.
local holdUntil, stripOn, lastEdit = 0, true, false
local deco = CreateFrame("Frame", nil, host, "BackdropTemplate")
deco:SetPoint("TOPLEFT", host, "BOTTOMLEFT", 0, 0)
deco:SetSize(300, 14)
deco:SetBackdrop({ bgFile = "Interface\\Buttons\\WHITE8X8", edgeFile = "Interface\\Buttons\\WHITE8X8", edgeSize = 1 })
deco:SetBackdropColor(0.06, 0.05, 0.03, 0.85)
deco:SetBackdropBorderColor(0.85, 0.65, 0.2, 1)
deco.fs = deco:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
deco.fs:SetPoint("LEFT", deco, "LEFT", 6, 0)
deco.fs:SetTextColor(0.9, 0.8, 0.5)
local function applyVisible()
  local ae = (ChatEdit_GetActiveWindow and ChatEdit_GetActiveWindow()) and true or false
  if lastEdit and not ae then holdUntil = math.max(holdUntil, GetTime() + 2) end
  lastEdit = ae
  local want = KKMapDB.always or pending ~= nil or ae or GetTime() < holdUntil
  if pending ~= nil then deco.fs:SetText(L("K&K WoW AI Chat | denkt ...  (Streifen nicht verdecken)", "K&K WoW AI Chat | thinking ...  (do not cover the strip)"))
  elseif ae then deco.fs:SetText(L("K&K WoW AI Chat | aktiv", "K&K WoW AI Chat | active"))
  else deco.fs:SetText("K&K WoW AI Chat") end
  deco:SetWidth(math.max(120, deco.fs:GetStringWidth() + 14))
  if want and not stripOn then stripOn = true; host:SetAlpha(1); render()
  elseif not want and stripOn then stripOn = false; host:SetAlpha(0) end
end

local function claudeFrame()
  if chatFrame then return chatFrame end
  for i = 1, NUM_CHAT_WINDOWS do
    local name = GetChatWindowInfo(i)
    if name == "Claude" then chatFrame = _G["ChatFrame" .. i]; return chatFrame end
  end
  local ok, f = pcall(FCF_OpenNewWindow, "Claude")
  chatFrame = (ok and f) or DEFAULT_CHAT_FRAME
  if chatFrame ~= DEFAULT_CHAT_FRAME and FCF_SetChatWindowFontSize then pcall(FCF_SetChatWindowFontSize, nil, chatFrame, 16) end
  return chatFrame
end
local function say(text, r, g, b) claudeFrame():AddMessage(text, r or 0.6, g or 0.85, b or 1) end

local function sendToClaude(msg)
  msg = strtrim(msg or "")
  if msg == "" then say(L("Benutzung: einfach schreiben (im Tab Claude) oder /c Frage", "Usage: just type in the Claude tab, or /c question")); return end
  local clean = msg:gsub("[|\n\r]", " "):sub(1, 230)
  local seq = time()
  if seq <= (KKMapState.seq or 0) then seq = KKMapState.seq + 1 end
  KKMapDB.n = (KKMapDB.n or 0) + 1
  local idx = ((KKMapDB.n - 1) % 200) + 1
  KKMapState.seq, KKMapState.out, KKMapState.idx = seq, clean, idx
  pending = { seq = seq, idx = idx, t0 = GetTime() }
  say(L("Du: ", "You: ") .. msg, 1, 1, 0.6)
  say(L("Claude denkt ...", "Claude is thinking ..."), 0.6, 0.6, 0.6)
  stripOn = true; host:SetAlpha(1)
  render()
end

SLASH_KKCHAT1 = "/c"
SLASH_KKCHAT2 = "/claude"
SlashCmdList["KKCHAT"] = sendToClaude

-- Rueckweg ohne Tasten: stiller Sound-Marker meldet "Antwort liegt bereit", dann naechsten Slot laden
local function loadAddon(name)
  if C_AddOns and C_AddOns.LoadAddOn then return C_AddOns.LoadAddOn(name) end
  return LoadAddOn(name)
end

-- Overlay-Fenster: Claude kann dir hier etwas zeigen (Titel + Textzeilen, WoW-Farbcodes erlaubt)
local overlay
local function buildOverlay()
  if overlay then return overlay end
  local f = CreateFrame("Frame", "KKOverlayFrame", UIParent, "BackdropTemplate")
  f:SetSize(460, 200)
  f:SetPoint("CENTER", UIParent, "CENTER", 260, 60)
  f:SetFrameStrata("DIALOG")
  f:SetMovable(true); f:EnableMouse(true); f:RegisterForDrag("LeftButton")
  f:SetScript("OnDragStart", f.StartMoving)
  f:SetScript("OnDragStop", f.StopMovingOrSizing)
  f:SetClampedToScreen(true)
  f:SetBackdrop({
    bgFile = "Interface\\DialogFrame\\UI-DialogBox-Background",
    edgeFile = "Interface\\DialogFrame\\UI-DialogBox-Border",
    tile = true, tileSize = 32, edgeSize = 24,
    insets = { left = 6, right = 6, top = 6, bottom = 6 },
  })
  f.title = f:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
  f.title:SetPoint("TOPLEFT", 18, -16)
  f.title:SetPoint("RIGHT", f, "RIGHT", -40, 0)
  f.title:SetJustifyH("LEFT")
  f.body = CreateFrame("Frame", nil, f)
  f.body:SetPoint("TOPLEFT", f.title, "BOTTOMLEFT", 0, -10)
  f.body:SetSize(424, 10)
  f.rows = {}
  local close = CreateFrame("Button", nil, f, "UIPanelCloseButton")
  close:SetPoint("TOPRIGHT", -4, -4)
  -- Groesse aendern: Griff unten rechts ziehen (klein bis gross)
  f:SetResizable(true)
  if f.SetResizeBounds then f:SetResizeBounds(180, 80, 900, 800)
  elseif f.SetMinResize then f:SetMinResize(180, 80); if f.SetMaxResize then f:SetMaxResize(900, 800) end end
  f:SetClipsChildren(true)
  local grip = CreateFrame("Button", nil, f)
  grip:SetSize(18, 18)
  grip:SetPoint("BOTTOMRIGHT", -4, 4)
  grip:SetNormalTexture("Interface\\ChatFrame\\UI-ChatIM-SizeGrabber-Up")
  grip:SetHighlightTexture("Interface\\ChatFrame\\UI-ChatIM-SizeGrabber-Highlight")
  grip:SetPushedTexture("Interface\\ChatFrame\\UI-ChatIM-SizeGrabber-Down")
  grip:SetScript("OnMouseDown", function() f:StartSizing("BOTTOMRIGHT") end)
  grip:SetScript("OnMouseUp", function() f:StopMovingOrSizing(); KKMapDB.overlaySize = { f:GetWidth(), f:GetHeight() } end)
  f:SetScript("OnSizeChanged", function(self, w)
    self.body:SetWidth(math.max(60, w - 36))
    if self.data and self.renderRows then self.renderRows(self, self.data.lines or {}) end
  end)
  -- Doppelklick auf den Titel: einklappen / ausklappen
  f:SetScript("OnMouseDown", function(self, button)
    if button == "RightButton" then
      self.collapsed = not self.collapsed
      self.body:SetShown(not self.collapsed)
      if self.collapsed then self.fullH = self:GetHeight(); self:SetHeight(48) else self:SetHeight(self.fullH or 200) end
    end
  end)
  f:Hide()
  overlay = f
  return f
end

-- Zeilen zeichnen: Text oder Balken  "[bar 0.75 00ff00] Beschriftung"  (0..1, Farbe RRGGBB)
local function renderRows(f, lines)
  local w = f.body:GetWidth()
  local y = 0
  for _, r in ipairs(f.rows) do r.fs:Hide(); r.bar:Hide(); if r.tex then r.tex:Hide() end end
  for i, line in ipairs(lines) do
    local r = f.rows[i]
    if not r then
      r = {}
      r.fs = f.body:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
      local font, _, flags = r.fs:GetFont()
      r.fs:SetFont(font, 15, flags)
      r.fs:SetJustifyH("LEFT"); r.fs:SetJustifyV("TOP")
      r.bar = CreateFrame("Frame", nil, f.body)
      r.bar.bg = r.bar:CreateTexture(nil, "BACKGROUND")
      r.bar.bg:SetAllPoints(); r.bar.bg:SetColorTexture(0.08, 0.08, 0.08, 0.9)
      r.bar.fill = r.bar:CreateTexture(nil, "ARTWORK")
      r.bar.fill:SetPoint("TOPLEFT"); r.bar.fill:SetPoint("BOTTOMLEFT")
      r.bar.lbl = r.bar:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
      r.bar.lbl:SetPoint("LEFT", 6, 0)
      f.rows[i] = r
    end
    local imgn = line:match("^%[img%s+(%d+)%]%s*$")
    if imgn then
      if not r.tex then r.tex = f.body:CreateTexture(nil, "ARTWORK") end
      local side = math.min(w, 420)
      r.tex:ClearAllPoints()
      r.tex:SetPoint("TOPLEFT", f.body, "TOPLEFT", 0, -y)
      r.tex:SetSize(side, side)
      r.tex:SetTexture("Interface" .. string.char(92) .. "AddOns" .. string.char(92) .. "KKMap" .. string.char(92) .. "img" .. string.char(92) .. string.format("%03d", tonumber(imgn)) .. ".tga")
      r.tex:Show()
      if tonumber(imgn) >= KKImgNext then KKImgNext = tonumber(imgn) + 1 end
      y = y + side + 4
    end
    local frac, hex, label = nil, nil, nil
    if not imgn then frac, hex, label = line:match("^%[bar%s+([%d%.]+)%s+(%x%x%x%x%x%x)%]%s*(.*)$") end
    if imgn then
      -- Bildzeile ist schon gezeichnet
    elseif frac then
      local fr = math.min(1, math.max(0, tonumber(frac) or 0))
      r.bar:ClearAllPoints()
      r.bar:SetPoint("TOPLEFT", f.body, "TOPLEFT", 0, -y)
      r.bar:SetSize(w, 18)
      r.bar.fill:SetColorTexture(tonumber(hex:sub(1, 2), 16) / 255, tonumber(hex:sub(3, 4), 16) / 255, tonumber(hex:sub(5, 6), 16) / 255, 0.85)
      r.bar.fill:SetWidth(math.max(1, w * fr))
      r.bar.lbl:SetText(label)
      r.bar:Show()
      y = y + 22
    else
      r.fs:ClearAllPoints()
      r.fs:SetPoint("TOPLEFT", f.body, "TOPLEFT", 0, -y)
      r.fs:SetWidth(w)
      r.fs:SetText(line)
      r.fs:Show()
      y = y + math.max(r.fs:GetStringHeight(), 16) + 2
    end
  end
  f.body:SetHeight(math.max(y, 1))
  f.contentH = y
end

function KKShowOverlay(data)
  if not data then return end
  local f = buildOverlay()
  KKMapDB.lastOverlay = data
  f.title:SetText(data.title or "Claude")
  f.data = data
  f.renderRows = renderRows
  renderRows(f, data.lines or {})
  f.collapsed = false
  f.body:Show()
  local size = KKMapDB.overlaySize
  if size then
    f:SetSize(size[1], size[2])
  else
    f:SetHeight(math.min(700, 60 + f.title:GetStringHeight() + (f.contentH or 40) + 20))
  end
  f:Show()
  -- nicht dauerhaft: schliesst nach data.secs (Standard 45 s) von selbst; /kko oeffnet es wieder
  f.token = (f.token or 0) + 1
  local token = f.token
  local function autoClose()
    if f.token ~= token then return end
    if MouseIsOver(f) then C_Timer.After(10, autoClose) else f:Hide() end
  end
  C_Timer.After(data.secs or 45, autoClose)
end

SLASH_KKOVERLAY1 = "/kko"
SlashCmdList["KKOVERLAY"] = function()
  local f = buildOverlay()
  if f:IsShown() then f:Hide() elseif KKMapDB.lastOverlay then KKShowOverlay(KKMapDB.lastOverlay) else print(L("Kein Overlay vorhanden.", "No overlay yet.")) end
end

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

local function deliver()
  local name = string.format("KKR%03d", nextSlot)
  nextSlot = nextSlot + 1
  KKSlotNext = nextSlot
  KKReplyData = nil
  loadAddon(name)
  local d = KKReplyData
  if d and pending and d.seq == pending.seq then
    for _, part in ipairs(d.parts or {}) do say(part) end
    if d.overlay then KKShowOverlay(d.overlay) end
    for _, m in ipairs(d.macros or {}) do createMacro(m.name, m.body, m.char) end
    KKMapState.ack = d.seq
    pending = nil
    holdUntil = GetTime() + 4
    if nextSlot >= 197 and not InCombatLockdown() and C_Timer and C_Timer.After then
      C_Timer.After(4, function() if not pending and ReloadUI then ReloadUI() end end)
    end
    if nextSlot > 190 then
      say("KKMap: " .. math.max(0, 201 - nextSlot) .. L(" Antworten frei, dann automatischer Reload.", " replies left, then an automatic reload."), 1, 0.8, 0.4)
    end
  end
end

local pollAcc = 0
local function poll(dt)
  if not pending then return end
  pollAcc = pollAcc + dt
  if pollAcc < 0.5 then return end
  pollAcc = 0
  local willPlay = PlaySoundFile(SIG .. string.format("%03d", pending.idx) .. ".wav", "Master")
  if willPlay then
    deliver()
  elseif GetTime() - pending.t0 > 120 then
    say(L("Claude antwortet nicht (Zeitueberschreitung). Laeuft die Bruecke?", "Claude did not answer (timeout). Is the bridge running?"), 1, 0.4, 0.4)
    pending = nil
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
            if h and h.SetText then h:SetText("Claude: "); self:SetTextInsets(h:GetStringWidth() + 18, 13, 0, 0) end
          end
          pcall(fix)
          if C_Timer and C_Timer.After then C_Timer.After(0, function() pcall(fix) end); C_Timer.After(0.1, function() pcall(fix) end) end
        end
      end)
      local orig = eb:GetScript("OnEnterPressed")
      eb:SetScript("OnEnterPressed", function(self, ...)
        local text = self:GetText() or ""
        if KKMapDB.dbg then say("KKDBG hook " .. tostring(self:GetName()) .. " cf=" .. tostring(self.chatFrame and self.chatFrame:GetName()) .. " claude=" .. tostring(claudeFrame():GetName()) .. " text=" .. text) end
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
          h:SetText("Claude: ")
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
    if h and h.SetText then h:SetText("Claude: "); eb:SetTextInsets(h:GetStringWidth() + 18, 13, 0, 0) end
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
    if h and h:GetText() ~= "Claude" then
      h:SetText("Claude")
      local suf = _G[eb:GetName() .. "HeaderSuffix"]
      eb:SetTextInsets(h:GetStringWidth() + ((suf and suf:GetStringWidth()) or 8) + 13, 13, 0, 0)
    end
  end)
end

SLASH_KKIMG1 = "/kkimg"
SlashCmdList["KKIMG"] = function(msg)
  local n = tonumber(msg) or 1
  if not KKImgFrame then
    local f = CreateFrame("Frame", "KKImgFrame", UIParent, "BackdropTemplate")
    f:SetSize(280, 280); f:SetPoint("CENTER"); f:SetFrameStrata("DIALOG")
    f:SetMovable(true); f:EnableMouse(true); f:RegisterForDrag("LeftButton")
    f:SetScript("OnDragStart", f.StartMoving); f:SetScript("OnDragStop", f.StopMovingOrSizing)
    f.tex = f:CreateTexture(nil, "ARTWORK"); f.tex:SetPoint("CENTER"); f.tex:SetSize(256, 256)
    local c = CreateFrame("Button", nil, f, "UIPanelCloseButton"); c:SetPoint("TOPRIGHT", 0, 0)
  end
  KKImgFrame.tex:SetTexture("Interface" .. string.char(92) .. "AddOns" .. string.char(92) .. "KKMap" .. string.char(92) .. "img" .. string.char(92) .. string.format("%03d", n) .. ".tga")
  KKImgFrame:Show()
  say("KKMap: image " .. n)
end

SLASH_KKHDR1 = "/kkhdr"
SlashCmdList["KKHDR"] = function()
  local eb = _G["ChatFrame4EditBox"]
  if not eb then say("kein ChatFrame4EditBox") return end
  say("hdr global=" .. tostring(_G["ChatFrame4EditBoxHeader"] ~= nil) .. " .header=" .. tostring(eb.header ~= nil) .. " .prompt=" .. tostring(eb.prompt ~= nil))
  for i, r in ipairs({ eb:GetRegions() }) do
    say(i .. " " .. tostring(r:GetObjectType()) .. " " .. tostring(r.GetName and r:GetName()) .. " '" .. tostring(r.GetText and r:GetText()) .. "'")
  end
  say("UpdateHeader=" .. tostring(ChatEdit_UpdateHeader ~= nil) .. " Activate=" .. tostring(ChatEdit_ActivateChat ~= nil) .. " mixin=" .. tostring(ChatFrameEditBoxMixin ~= nil))
end

-- Notweg: Antwort per /kkc (getippt von der Bruecke) wirkt wie eine zugestellte Antwort
SLASH_KKREPLY1 = "/kkc"
SlashCmdList["KKREPLY"] = function(msg)
  say(msg)
  if pending then KKMapState.ack = pending.seq; pending = nil end
end

local acc = 0
host:SetScript("OnUpdate", function(_, dt)
  acc = acc + dt
  poll(dt)
  if acc >= 0.4 then acc = 0; if not KKMapDB.off then pcall(applyVisible); if stripOn then render() end end end
end)

SLASH_KKMAP1 = "/kkmap"
-- /kkm Name~Text mit \n als Zeilenumbruch  (optional  Name~Text~char  = nur dieser Charakter)
SLASH_KKDBG1 = "/kkdbg"
SlashCmdList["KKDBG"] = function() KKMapDB.dbg = not KKMapDB.dbg; say("KKMap dbg " .. tostring(KKMapDB.dbg)) end
SLASH_KKMACRO1 = "/kkm"
SlashCmdList["KKMACRO"] = function(msg)
  local name, body, scope = strsplit("~", msg or "", 3)
  if not name or name == "" or not body or body == "" then say("KKMap: /kkm Name~Text (\\n = newline)") return end
  createMacro(name, body, scope == "char")
end

SlashCmdList["KKMAP"] = function(msg)
  if msg == "frames" then KKMapDB.frames = not KKMapDB.frames; print("KKMap: button list " .. (KKMapDB.frames and "on" or "off")) return end
  if msg == "always" then KKMapDB.always = true; KKMapDB.off = false; host:Show(); host:SetAlpha(1); stripOn = true; render(); print("KKMap: strip always visible") return end
  if msg == "auto" then KKMapDB.always = false; KKMapDB.off = false; host:Show(); print("KKMap: strip only when needed") return end
  if msg == "off" then KKMapDB.off = true; host:Hide()
  else KKMapDB.off = false; host:Show(); render() end
  print("KKMap: " .. (KKMapDB.off and "aus" or "an"))
end
local ev = CreateFrame("Frame")
ev:RegisterEvent("PLAYER_LOGIN")
ev:SetScript("OnEvent", function()
  KKMapDB.dbg = false
  claudeFrame()
  hookEditBoxes()
  if KKMapDB.off then host:Hide() else render() end
end)
