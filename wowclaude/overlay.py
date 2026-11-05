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
CHROME_BAR = 34  # height of Chrome's own app-window title bar (hidden behind the WoW frame)

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


_clipped: set = set()


def pin(hwnd: int, x: int, y: int, w: int, h: int, opacity: int, click_through: bool) -> None:
    ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE) | WS_EX_LAYERED | WS_EX_TOOLWINDOW
    ex = ex | WS_EX_TRANSPARENT if click_through else ex & ~WS_EX_TRANSPARENT
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex)
    user32.SetLayeredWindowAttributes(hwnd, 0, int(255 * max(10, min(100, opacity)) / 100), LWA_ALPHA)
    # Chrome draws its own title bar inside the client area: move the window up and clip that strip away.
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, wintypes.UINT]
    gdi32 = ctypes.windll.gdi32
    gdi32.CreateRectRgn.restype = wintypes.HANDLE
    if (hwnd, w, h) not in _clipped:
        rgn = gdi32.CreateRectRgn(0, CHROME_BAR, w, h + CHROME_BAR)
        user32.SetWindowRgn(wintypes.HWND(hwnd), rgn, True)
        _clipped.add((hwnd, w, h))
    user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(HWND_TOPMOST), x, y - CHROME_BAR, w, h + CHROME_BAR, SWP_NOACTIVATE | SWP_SHOWWINDOW)


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
    print(f"Overlay running ({w}x{h}, {opacity}% opacity{', click-through' if click_through else ''}). "
          "Close it with the X in the frame. Log in once in this window (own profile).")
    frame_loop(hwnd, x, y, w, h, opacity, click_through)
    return 0


GOLD, DARK, TXT = "#d9a633", "#100d08", "#e6cc80"
BAR, EDGE = 20, 3


def frame_loop(hwnd: int, x: int, y: int, w: int, h: int, opacity: int, click_through: bool) -> None:
    """Wrap the browser window in a WoW-style frame (dark panel, gold border, title bar with X)."""
    import tkinter as tk

    GWL_STYLE, WS_CAPTION, WS_THICKFRAME, WS_BORDER = -16, 0xC00000, 0x40000, 0x800000
    st = user32.GetWindowLongW(hwnd, GWL_STYLE) & ~(WS_CAPTION | WS_THICKFRAME | WS_BORDER)
    user32.SetWindowLongW(hwnd, GWL_STYLE, st)
    pos = {"x": x, "y": y}
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    fw, fh = w + 2 * EDGE, h + BAR + 2 * EDGE
    root.geometry(f"{fw}x{fh}+{x - EDGE}+{y - BAR - EDGE}")
    root.configure(bg=GOLD)
    inner = tk.Frame(root, bg=DARK)
    inner.place(x=1, y=1, width=fw - 2, height=fh - 2)
    bar = tk.Frame(inner, bg=DARK, height=BAR)
    bar.pack(fill="x")
    title = tk.Label(bar, text="K&K WoW AI Chat", bg=DARK, fg=TXT, font=("Friz Quadrata TT", 9, "bold"))
    title.pack(side="left", padx=6)
    close = tk.Label(bar, text=" X ", bg=DARK, fg=TXT, font=("Arial", 9, "bold"), cursor="hand2")
    close.pack(side="right")
    close.bind("<Button-1>", lambda e: user32.PostMessageW(wintypes.HWND(hwnd), 0x0010, 0, 0))
    close.bind("<Enter>", lambda e: close.config(bg="#6b1d1d"))
    close.bind("<Leave>", lambda e: close.config(bg=DARK))
    drag = {}

    def down(e):
        drag["dx"], drag["dy"] = e.x_root - root.winfo_x(), e.y_root - root.winfo_y()

    def move(e):
        nx, ny = e.x_root - drag["dx"], e.y_root - drag["dy"]
        root.geometry(f"+{nx}+{ny}")
        pos["x"], pos["y"] = nx + EDGE, ny + BAR + EDGE

    for wdg in (bar, title):
        wdg.bind("<Button-1>", down)
        wdg.bind("<B1-Motion>", move)

    def tick():
        if not user32.IsWindow(wintypes.HWND(hwnd)):
            root.destroy()
            return
        pin(hwnd, pos["x"], pos["y"], w, h, opacity, click_through)
        root.after(250, tick)

    tick()
    root.mainloop()


def play(url: str) -> None:
    """Called by the bridge for [[play URL]]: start the overlay in the background, or close it for ``off``."""
    if url == "off":
        for hwnd, title in _windows().items():
            if (config.HOME / "overlay-profile").exists() and hwnd in _ours:
                user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
        _ours.clear()
        return
    import sys
    before = set(_windows())
    subprocess.Popen([sys.executable, "-m", "wowclaude", "overlay", url], creationflags=0x08000000)
    for _ in range(40):
        time.sleep(0.5)
        new = set(_windows()) - before
        if new:
            _ours.update(new)
            break


_ours: set[int] = set()
