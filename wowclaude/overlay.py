"""Browser overlay: a small always-on-top browser window (YouTube, Netflix, Twitter ...) over the game.

WoW addons cannot show web pages, so this opens a normal Chrome/Edge "app" window (own profile, so logins and
Netflix/Widevine work) and pins it above the game: always on top, adjustable opacity, optional click-through
(mouse goes to the game, the video keeps playing). The game must run in windowed or borderless mode.

    wowclaude overlay https://www.youtube.com --corner br --size 480x270 --opacity 90
    wowclaude overlay https://www.netflix.com --click-through
"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import time
from ctypes import wintypes
from pathlib import Path

from . import config

user32 = ctypes.windll.user32 if os.name == "nt" else None

GWL_EXSTYLE = -20
WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW = 0x80000, 0x20, 0x80
HWND_TOPMOST = -1
SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x10, 0x40
LWA_ALPHA = 0x2

CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
]


def find_browser() -> str | None:
    for c in CANDIDATES:
        if Path(c).exists():
            return c
    return shutil.which("chrome") or shutil.which("msedge")


def _windows() -> dict[int, str]:
    out: dict[int, str] = {}
    cb = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def each(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            cls = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(hwnd, cls, 64)
            if cls.value == "Chrome_WidgetWin_1":
                out[int(hwnd)] = buf.value
        return True

    user32.EnumWindows(cb(each), 0)
    return out


def game_rect() -> tuple[int, int, int, int] | None:
    hwnd = user32.FindWindowW("GxWindowClass", None) or user32.FindWindowW("GxWindowClassD3d", None)
    if not hwnd:
        return None
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def place(w: int, h: int, corner: str, margin: int = 24) -> tuple[int, int]:
    rect = game_rect()
    if rect is None:
        rect = (0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))
    l, t, r, b = rect
    x = l + margin if "l" in corner else r - w - margin
    y = t + margin + 40 if "t" in corner else b - h - margin
    return x, y


def pin(hwnd: int, x: int, y: int, w: int, h: int, opacity: int, click_through: bool) -> None:
    ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE) | WS_EX_LAYERED | WS_EX_TOOLWINDOW
    ex = ex | WS_EX_TRANSPARENT if click_through else ex & ~WS_EX_TRANSPARENT
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex)
    user32.SetLayeredWindowAttributes(hwnd, 0, int(255 * max(10, min(100, opacity)) / 100), LWA_ALPHA)
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, wintypes.UINT]
    user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(HWND_TOPMOST), x, y, w, h, SWP_NOACTIVATE | SWP_SHOWWINDOW)


def run(url: str, corner: str = "br", size: str = "480x270", opacity: int = 90,
        click_through: bool = False) -> int:
    if os.name != "nt":
        print("The overlay is Windows only.")
        return 2
    exe = find_browser()
    if not exe:
        print("No Chrome/Edge/Brave found.")
        return 2
    w, h = (int(v) for v in size.lower().split("x"))
    x, y = place(w, h, corner)
    profile = config.HOME / "overlay-profile"
    profile.mkdir(parents=True, exist_ok=True)
    before = set(_windows())
    subprocess.Popen([exe, f"--app={url}", f"--user-data-dir={profile}", f"--window-size={w},{h}",
                      f"--window-position={x},{y}", "--autoplay-policy=no-user-gesture-required",
                      "--no-first-run", "--disable-features=Translate"],
                     creationflags=0x08000000)
    hwnd = 0
    for _ in range(60):
        time.sleep(0.5)
        new = set(_windows()) - before
        if new:
            hwnd = sorted(new)[0]
            break
    if not hwnd:
        print("Browser window did not appear.")
        return 1
    time.sleep(1.0)
    pin(hwnd, x, y, w, h, opacity, click_through)
    print(f"Overlay running ({w}x{h}, {opacity}% opacity{', click-through' if click_through else ''}). "
          "Close the window to stop. Log in once in this window (own profile).")
    return 0
