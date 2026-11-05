"""Run the real KKMap.lua inside lupa with a fake WoW API and read back the colour strip it draws.

This closes the loop the pure-Python tests could not: the Lua encoder and the Python decoder must agree.
"""
from __future__ import annotations

from pathlib import Path

LUA_PRELUDE = r'''
cellsLog = {}  -- texture -> texture (set of textures that got a colour)
local function newObj(kind)
  local o = { __kind = kind, __shown = true, __text = "", __scripts = {}, __points = {} }
  local mt = {}
  mt.__index = function(t, k)
    if k == "CreateTexture" then
      return function(self) local tex = newObj("Texture"); tex.__parent = self; return tex end
    elseif k == "CreateFontString" then
      return function(self) return newObj("FontString") end
    elseif k == "SetColorTexture" then
      return function(self, r, g, b) self.__rgb = { r, g, b }; cellsLog[self] = self end
    elseif k == "SetPoint" then
      return function(self, point, rel, relPoint, x, y)
        if type(rel) == "table" and rel.__kind == "Texture" then rel = nil end
        self.__point = { point, x or 0, y or 0 }
      end
    elseif k == "Hide" then return function(self) self.__shown = false end
    elseif k == "Show" then return function(self) self.__shown = true end
    elseif k == "IsShown" or k == "IsVisible" then return function(self) return self.__shown end
    elseif k == "SetText" then return function(self, t) self.__text = t end
    elseif k == "GetText" then return function(self) return self.__text end
    elseif k == "SetScript" or k == "HookScript" then return function(self, name, fn) self.__scripts[name] = fn end
    elseif k == "GetScript" then return function(self, name) return self.__scripts[name] end
    elseif k == "GetWidth" or k == "GetHeight" or k == "GetLeft" or k == "GetTop" or k == "GetRight"
        or k == "GetBottom" or k == "GetScale" or k == "GetEffectiveScale" or k == "GetAlpha" then
      return function() return 100 end
    elseif k == "GetObjectType" then return function(self) return self.__kind end
    elseif k == "GetName" then return function() return "Stub" end
    elseif k == "GetPoint" then return function() return "CENTER", nil, "CENTER", 0, 0 end
    elseif k == "GetRegions" or k == "GetChildren" then return function() return end
    elseif k == "GetStringWidth" then return function() return 50 end
    elseif k == "IsMouseOver" or k == "IsMouseEnabled" then return function() return false end
    elseif k == "GetParent" then return function(self) return self.__parent end
    elseif k == "AddMessage" then return function(self, text) local log = rawget(self, "__log") or {}; rawset(self, "__log", log); table.insert(log, text) end
    end
    return function(...) return nil end
  end
  return setmetatable(o, mt)
end

UIParent = newObj("Frame")
DEFAULT_CHAT_FRAME = newObj("ChatFrame")
NUM_CHAT_WINDOWS = 0
KKMapDB = nil
KKMapState = nil
function GetLocale() return "enUS" end
function GetPhysicalScreenSize() return 2560, 1440 end
function GetTime() return 1000 end
function time() return 1700000000 end
AllFrames = {}
function CreateFrame(kind, name, parent) local f = newObj(kind); f.__parent = parent; if name then _G[name] = f end; AllFrames[#AllFrames + 1] = f; return f end
function EnumerateFrames(f) return nil end
function InCombatLockdown() return false end
function GetAddOnInfo() return nil end
function IsAddOnLoaded() return false end
function LoadAddOn() return true end
function UnitName() return "Tester" end
function GetRealmName() return "Realm" end
function UnitLevel() return 10 end
function UnitClass() return "Warrior", "WARRIOR" end
function GetZoneText() return "Tirisfal Glades" end
function GetSubZoneText() return "Brill" end
function GetMoney() return 12345 end
function UnitHealth() return 50 end
function UnitHealthMax() return 100 end
function UnitPower() return 10 end
function UnitPowerMax() return 100 end
function UnitPowerType() return 0, "MANA" end
function UnitXP() return 100 end
function UnitXPMax() return 1000 end
function GetNumGroupMembers() return 0 end
function IsInGroup() return false end
function UnitAffectingCombat() return false end
C_Timer = { After = function(sec, fn) end }
SlashCmdList = {}
C_AddOns = nil
strtrim = function(s) return (s:gsub("^%s+", ""):gsub("%s+$", "")) end
tinsert = table.insert
wipe = function(t) for k in pairs(t) do t[k] = nil end return t end
function hooksecurefunc() end
function PlaySoundFile() return false end
function print() end
function date() return "00:00" end
BackdropTemplateMixin = {}
STANDARD_TEXT_FONT = "Fonts\\FRIZQT__.TTF"
'''

LUA_READBACK = r'''
function __fire(event)
  for _, f in ipairs(AllFrames) do
    local h = f.__scripts and f.__scripts.OnEvent
    if h then h(f, event) end
  end
end

function __strip()
  local out = {}
  for _, c in pairs(cellsLog) do
    if c.__shown and c.__rgb and c.__point then
      out[#out + 1] = { c.__point[2], -c.__point[3], c.__rgb[1], c.__rgb[2], c.__rgb[3] }
    end
  end
  return out
end
'''


def run_addon(lua_path: Path):
    """Load KKMap.lua with a fake API and return (lua_runtime, list of (col,row,r,g,b) strip cells)."""
    import lupa
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(LUA_PRELUDE)
    lua.execute(LUA_READBACK)
    code = lua_path.read_text(encoding="utf-8")
    fn = lua.eval("function(src) local f, err = load(src, '@KKMap.lua'); if not f then error(err) end; return f end")
    chunk = fn(code)
    chunk()
    lua.eval("function() __fire('PLAYER_LOGIN') end")()
    return lua


def strip_image(lua, width: int = 700, height: int = 120):
    """Draw the strip cells (1 px each, as the addon does) onto a black image the Python decoder can read."""
    from PIL import Image
    im = Image.new("RGB", (width, height), (10, 10, 10))
    px = im.load()
    for cell in lua.eval("__strip()").values():
        col, row, r, g, b = cell[1], cell[2], cell[3], cell[4], cell[5]
        px[int(col), int(row)] = (round(r * 255), round(g * 255), round(b * 255))
    return im
