"""Browser overlay: a small always-on-top browser window (YouTube, Netflix, Twitter ...) over the game.

WoW addons cannot show web pages, so this opens a normal Chrome/Edge "app" window (own profile, so logins and
Netflix/Widevine work) and pins it above the game: always on top, adjustable opacity, optional click-through
(mouse goes to the game, the video keeps playing). The game must run in windowed or borderless mode.

    wowclaude overlay https://www.youtube.com --corner br --size 480x270 --opacity 90
    wowclaude overlay https://www.netflix.com --click-through
"""
from __future__ import annotations

import ctypes
import json
import os
import base64
import shutil
import socket
import subprocess
import time
import urllib.parse
import urllib.request
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


def pin(hwnd: int, x: int, y: int, w: int, h: int, opacity: int, click_through: bool) -> None:
    """Place the browser window: its top-left is (x, y), size w x (h + CHROME_BAR). The WoW frame covers the bar."""
    ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE) | WS_EX_LAYERED | WS_EX_TOOLWINDOW
    ex = ex | WS_EX_TRANSPARENT if click_through else ex & ~WS_EX_TRANSPARENT
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex)
    user32.SetLayeredWindowAttributes(hwnd, 0, int(255 * max(10, min(100, opacity)) / 100), LWA_ALPHA)
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, wintypes.UINT]
    user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(HWND_TOPMOST), x, y - CHROME_BAR, w, h + CHROME_BAR,
                        SWP_NOACTIVATE | SWP_SHOWWINDOW)
    # Chrome's own title bar is the top CHROME_BAR pixels: cut them off (re-applied, Chrome resets the region)
    rgn = ctypes.windll.gdi32.CreateRectRgn(0, CHROME_BAR, w, h + CHROME_BAR)
    user32.SetWindowRgn(wintypes.HWND(hwnd), ctypes.c_void_p(rgn), False)


def _kill_profile_browsers(profile: Path) -> None:
    """A browser already running on our own profile would swallow the new window (and the debug port): close it."""
    cmd = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*" + profile.name + "*' -and "
           "$_.Name -match 'chrome|msedge|brave' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, timeout=20,
                       creationflags=0x08000000)
        time.sleep(1.0)
    except (OSError, subprocess.SubprocessError):
        pass


def free_port() -> int:
    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        return sk.getsockname()[1]


def _page_ws(port: int) -> tuple[str, str] | None:
    """(websocket url, current page url) of the browser's page, via the DevTools HTTP endpoint."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=1.5) as r:
            for t in json.loads(r.read().decode("utf-8")):
                if t.get("type") == "page":
                    return t["webSocketDebuggerUrl"], t.get("url", "")
    except (OSError, ValueError, KeyError):
        pass
    return None


def navigate(port: int, text: str) -> bool:
    """Send the browser to ``text``: a URL, a domain, or search words (Google). Uses the DevTools protocol (stdlib only)."""
    text = text.strip()
    if not text:
        return False
    if " " in text or ("." not in text and not text.startswith(("http://", "https://", "localhost"))):
        url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(text)
    else:
        url = text if text.startswith(("http://", "https://")) else "https://" + text
    found = _page_ws(port)
    if not found:
        return False
    host_path = found[0].split("://", 1)[1]
    host, _, path = host_path.partition("/")
    h, _, prt = host.partition(":")
    try:
        sk = socket.create_connection((h, int(prt or 80)), timeout=3)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f"GET /{path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\nOrigin: http://{host}\r\n\r\n")
        sk.sendall(req.encode())
        sk.recv(4096)
        payload = json.dumps({"id": 1, "method": "Page.navigate", "params": {"url": url}}).encode()
        mask = os.urandom(4)
        n = len(payload)
        head = bytes([0x81, 0x80 | (n if n < 126 else 126)]) + (n.to_bytes(2, "big") if n >= 126 else b"")
        sk.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))
        sk.settimeout(2)
        try:
            sk.recv(4096)
        except OSError:
            pass
        sk.close()
    except OSError:
        return False
    save_state(url=url)
    return True


STATE_FILE = config.HOME / "overlay.json"
MIN_W, MIN_H = 240, 135


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(**kw) -> None:
    st = load_state()
    st.update(kw)
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(st), encoding="utf-8")
    except OSError:
        pass


def run(url: str | None = None, corner: str | None = None, size: str | None = None, opacity: int = 100,
        click_through: bool = False) -> int:
    if os.name != "nt":
        print("The overlay is Windows only.")
        return 2
    exe = find_browser()
    if not exe:
        print("No Chrome/Edge/Brave found.")
        return 2
    saved = load_state()
    url = url or saved.get("url") or "https://www.youtube.com"
    if size:
        w, h = (int(v) for v in size.lower().split("x"))
    else:
        w, h = int(saved.get("w", 480)), int(saved.get("h", 270))
    if corner or "x" not in saved:
        x, y = place(w, h + TOP + EDGE, corner or "br")
    else:
        x, y = int(saved["x"]), int(saved["y"])  # remembered position (browser window top-left)
    save_state(url=url, x=x, y=y, w=w, h=h)
    profile = config.HOME / "overlay-profile"
    profile.mkdir(parents=True, exist_ok=True)
    _kill_profile_browsers(profile)
    port = free_port()
    before = set(_windows())
    subprocess.Popen([exe, f"--app={url}", f"--user-data-dir={profile}", f"--window-size={w},{h + CHROME_BAR}",
                      f"--window-position={x},{y - CHROME_BAR}", "--autoplay-policy=no-user-gesture-required",
                      "--no-first-run", "--disable-features=Translate", f"--remote-debugging-port={port}",
                      "--remote-allow-origins=*"],
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
    print(f"Overlay running ({w}x{h}, debug port {port}). Drag the title bar to move, the corner to resize, X to close; "
          "position and size are remembered. Log in once in this window (own profile).", flush=True)
    frame_loop(hwnd, x, y, w, h, opacity, click_through, port)
    return 0


# The frame is built from the game's own UI textures (DialogFrame/UI-DialogBox-*, UIPanelCloseButton art, chat
# resize grabber), assembled exactly like the in-game overlay window (Backdrop: edgeSize 24, tile 32, insets 6).
# It is a per-pixel-alpha window, so the translucent dark background shows the game behind it, like the real thing.
ART = Path(__file__).parent / "art"
EDGE_SIZE, INSET, MARGIN = 24, 6, 8  # border art size, backdrop inset, visible border thickness (content margin)
EDGE = MARGIN  # frame thickness left/right/bottom
TOP = 30  # top strip with the address bar and the close button; the browser area starts below it


def _art(name: str):
    from PIL import Image
    return Image.open(ART / name).convert("RGBA")


LABEL = "WoW Browser"
WINFONTS = Path(r"C:/Windows/Fonts")


def _font(size: int):
    """WoW's own UI font (Friz Quadrata) if it can be found, else the closest Windows serif. The game's font is
    not redistributed here: put FRIZQT__.TTF into ~/.wowclaude/ (or <game>/Fonts/) to get it exactly."""
    from PIL import ImageFont
    cands = [config.HOME / "FRIZQT__.TTF", WINFONTS / "FRIZQT__.TTF"]
    try:
        root = config.client_root(None)
        if root:
            cands.append(Path(root) / "Fonts" / "FRIZQT__.TTF")
    except Exception:  # noqa: BLE001
        pass
    cands += [WINFONTS / "constan.ttf", WINFONTS / "pala.ttf"]
    for c in cands:
        try:
            if c.exists():
                return ImageFont.truetype(str(c), size)
        except OSError:
            continue
    return ImageFont.load_default()


def label_width() -> int:
    return int(_font(13).getlength(LABEL)) + 22


def compose(fw: int, fh: int, top: int, hover: str = "", down: str = ""):
    """Render the whole frame as an RGBA image; the content window area is fully transparent."""
    from PIL import Image, ImageChops

    out = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
    tile = _art("UI-DialogBox-Background.png").resize((32, 32))
    bg = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
    for yy in range(INSET, fh - INSET, 32):
        for xx in range(INSET, fw - INSET, 32):
            bg.paste(tile, (xx, yy))
    mask = Image.new("L", (fw, fh), 0)
    mask.paste(255, (INSET, INSET, fw - INSET, fh - INSET))
    mask.paste(0, (MARGIN, top, fw - MARGIN, fh - MARGIN))  # cut out the browser area
    bg.putalpha(ImageChops.multiply(bg.getchannel("A"), mask))
    out.alpha_composite(bg)
    # border: 8 pieces of 32 px in a 256x32 strip: left, right, top, bottom (stored rotated), TL, TR, BL, BR
    sheet = _art("UI-DialogBox-Border.png")
    piece = lambda i: sheet.crop((i * 32, 0, i * 32 + 32, 32)).resize((EDGE_SIZE, EDGE_SIZE), Image.LANCZOS)
    left, right = piece(0), piece(1)
    topp = piece(2).transpose(Image.TRANSPOSE)
    botp = piece(3).transpose(Image.TRANSPOSE)
    e = EDGE_SIZE
    for yy in range(e, fh - e, e):
        out.alpha_composite(left, (0, yy))
        out.alpha_composite(right, (fw - e, yy))
    for xx in range(e, fw - e, e):
        out.alpha_composite(topp, (xx, 0))
        out.alpha_composite(botp, (xx, fh - e))
    out.alpha_composite(piece(4), (0, 0))
    out.alpha_composite(piece(5), (fw - e, 0))
    out.alpha_composite(piece(6), (0, fh - e))
    out.alpha_composite(piece(7), (fw - e, fh - e))
    # close button: the red square of UIPanelCloseButton (art bbox 6,7..25,25 of the 32x32 texture), 3 px from the
    # right and 2 px from the top edge, like in the in-game overlay window
    cb = (6, 7, 25, 25)
    bx, by = fw - 3 - (cb[2] - cb[0]), 2
    out.alpha_composite(_art("UI-Panel-MinimizeButton-Down.png" if down == "close" else "UI-Panel-MinimizeButton-Up.png").crop(cb),
                        (bx, by))
    if hover == "close":
        box = (bx, by, bx + cb[2] - cb[0], by + cb[3] - cb[1])
        region = out.crop(box)
        hl = _art("UI-Panel-MinimizeButton-Highlight.png").crop(cb)
        rgb = ImageChops.add(region.convert("RGB"), hl.convert("RGB"))
        rgb.putalpha(ImageChops.lighter(region.getchannel("A"), hl.getchannel("A")))
        out.paste(rgb, box[:2])
    from PIL import ImageDraw
    draw = ImageDraw.Draw(out)
    font = _font(13)
    ty = TOP // 2 + 4
    draw.text((15, ty + 1), LABEL, font=font, fill=(0, 0, 0, 255), anchor="lm")  # WoW-style drop shadow
    draw.text((14, ty), LABEL, font=font, fill=(255, 209, 0, 255), anchor="lm")
    out.alpha_composite(_art("UI-ChatIM-SizeGrabber-Up.png").resize((18, 18), Image.LANCZOS), (fw - 4 - 18, fh - 4 - 18))
    return out


def update_layered(hwnd: int, img, x: int, y: int) -> None:
    """Show a premultiplied-alpha RGBA image as the content of a layered window (UpdateLayeredWindow)."""
    from PIL import Image

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class SIZE(ctypes.Structure):
        _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

    class BLEND(ctypes.Structure):
        _fields_ = [("op", ctypes.c_ubyte), ("flags", ctypes.c_ubyte), ("alpha", ctypes.c_ubyte),
                    ("fmt", ctypes.c_ubyte)]

    class BMI(ctypes.Structure):
        _fields_ = [("size", ctypes.c_uint32), ("w", ctypes.c_int32), ("h", ctypes.c_int32),
                    ("planes", ctypes.c_uint16), ("bits", ctypes.c_uint16), ("comp", ctypes.c_uint32),
                    ("img", ctypes.c_uint32), ("xp", ctypes.c_int32), ("yp", ctypes.c_int32),
                    ("used", ctypes.c_uint32), ("imp", ctypes.c_uint32)]

    gdi, u = ctypes.windll.gdi32, user32
    vp = ctypes.c_void_p
    u.GetDC.restype = vp
    u.GetDC.argtypes = [vp]
    u.ReleaseDC.argtypes = [vp, vp]
    gdi.CreateCompatibleDC.restype = vp
    gdi.CreateCompatibleDC.argtypes = [vp]
    gdi.CreateDIBSection.restype = vp
    gdi.CreateDIBSection.argtypes = [vp, ctypes.POINTER(BMI), ctypes.c_uint, ctypes.POINTER(vp), vp, ctypes.c_uint]
    gdi.SelectObject.restype = vp
    gdi.SelectObject.argtypes = [vp, vp]
    gdi.DeleteObject.argtypes = [vp]
    gdi.DeleteDC.argtypes = [vp]
    u.UpdateLayeredWindow.argtypes = [vp, vp, ctypes.POINTER(POINT), ctypes.POINTER(SIZE), vp, ctypes.POINTER(POINT),
                                      ctypes.c_uint32, ctypes.POINTER(BLEND), ctypes.c_uint32]
    w, h = img.size
    r, g, b, a = img.convert("RGBa").split()
    data = Image.merge("RGBA", (b, g, r, a)).tobytes()
    bmi = BMI(40, w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    bits = vp()
    screen = u.GetDC(None)
    mem = gdi.CreateCompatibleDC(screen)
    bmp = gdi.CreateDIBSection(mem, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    ctypes.memmove(bits, data, len(data))
    old = gdi.SelectObject(mem, bmp)
    u.UpdateLayeredWindow(hwnd, screen, ctypes.byref(POINT(x, y)), ctypes.byref(SIZE(w, h)), mem,
                          ctypes.byref(POINT(0, 0)), 0, ctypes.byref(BLEND(0, 0, 255, 1)), 2)
    gdi.SelectObject(mem, old)
    gdi.DeleteObject(bmp)
    gdi.DeleteDC(mem)
    u.ReleaseDC(None, screen)


def frame_loop(hwnd: int, x: int, y: int, w: int, h: int, opacity: int, click_through: bool, port: int = 0) -> None:
    """Draw the WoW frame above the browser window (per-pixel alpha; the browser area is see-through and clickable)."""
    import tkinter as tk

    GWL_STYLE, WS_CAPTION, WS_THICKFRAME, WS_BORDER = -16, 0xC00000, 0x40000, 0x800000
    st = user32.GetWindowLongW(hwnd, GWL_STYLE) & ~(WS_CAPTION | WS_THICKFRAME | WS_BORDER)
    user32.SetWindowLongW(hwnd, GWL_STYLE, st)
    S = {"x": x, "y": y, "w": w, "h": h, "hover": "", "down": ""}  # browser window top-left and CONTENT size
    top = TOP
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.update_idletasks()
    user32.GetParent.restype = ctypes.c_void_p
    top_hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW(ctypes.c_void_p(top_hwnd), GWL_EXSTYLE,
                          user32.GetWindowLongW(ctypes.c_void_p(top_hwnd), GWL_EXSTYLE) | WS_EX_LAYERED | WS_EX_TOOLWINDOW)
    cache: dict = {}
    # address bar: a small dark entry in the top strip (type a URL or search words, Enter)
    bar = tk.Toplevel(root)
    bar.overrideredirect(True)
    bar.attributes("-topmost", True)
    bar.configure(bg="#2a2417")
    var = tk.StringVar(value=load_state().get("url", ""))
    entry = tk.Entry(bar, textvariable=var, bg="#0d0c09", fg="#ffd100", insertbackground="#ffd100", relief="flat",
                     font=("Arial", 9), highlightthickness=1, highlightbackground="#5c5c5c", highlightcolor="#b4b4b4",
                     selectbackground="#5c4a1a", selectforeground="#ffffff")
    entry.pack(fill="both", expand=True, padx=1, pady=1)

    def go(_e=None):
        if port and navigate(port, var.get()):
            drag_focus_back()
        return "break"

    def drag_focus_back() -> None:
        root.focus_force()

    entry.bind("<Return>", go)
    entry.bind("<Button-1>", lambda e: (bar.focus_force(), entry.focus_set()))
    entry.bind("<Escape>", lambda e: drag_focus_back())

    def place_bar() -> None:
        fw = S["w"] + 2 * EDGE
        lw = label_width()
        bar.geometry(f"{max(60, fw - lw - 34)}x18+{S['x'] - EDGE + lw}+{S['y'] - TOP + 10}")

    def dims():
        return S["w"] + 2 * EDGE, S["h"] + TOP + EDGE

    def draw() -> None:
        fw, fh = dims()
        cache["img"] = compose(fw, fh, top, S["hover"], S["down"])
        update_layered(top_hwnd, cache["img"], S["x"] - EDGE, S["y"] - TOP)

    def layout() -> None:
        fw, fh = dims()
        root.geometry(f"{fw}x{fh}+{S['x'] - EDGE}+{S['y'] - TOP}")
        draw()
        place_bar()

    def zone(e) -> str:
        fw, fh = dims()
        if fw - 30 <= e.x <= fw - 1 and 0 <= e.y <= 26:
            return "close"
        if e.x >= fw - 24 and e.y >= fh - 24:
            return "grip"
        if e.y < top:
            return "bar"
        return ""

    drag: dict = {}

    def down(e):
        z = zone(e)
        drag.update(z=z, dx=e.x_root - (S["x"] - EDGE), dy=e.y_root - (S["y"] - TOP),
                    gx=e.x_root, gy=e.y_root, w=S["w"], h=S["h"])
        if z == "close":
            S["down"] = "close"
            draw()

    def move(e):
        z = drag.get("z")
        if z == "bar":
            S["x"], S["y"] = e.x_root - drag["dx"] + EDGE, e.y_root - drag["dy"] + TOP
            root.geometry(f"+{S['x'] - EDGE}+{S['y'] - TOP}")
            place_bar()
            update_layered(top_hwnd, cache["img"], S["x"] - EDGE, S["y"] - TOP)
        elif z == "grip":
            S["w"] = max(MIN_W, drag["w"] + e.x_root - drag["gx"])
            S["h"] = max(MIN_H, drag["h"] + e.y_root - drag["gy"])
            layout()

    def release(e):
        was = drag.get("z")
        if was == "close":
            S["down"] = ""
            draw()
            if zone(e) == "close":
                save_state(x=S["x"], y=S["y"], w=S["w"], h=S["h"])
                user32.PostMessageW(wintypes.HWND(hwnd), 0x0010, 0, 0)
        elif was:
            save_state(x=S["x"], y=S["y"], w=S["w"], h=S["h"])
        drag.clear()

    def hover(e):
        want = "close" if zone(e) == "close" else ""
        if want != S["hover"]:
            S["hover"] = want
            draw()

    root.bind("<Button-1>", down)
    root.bind("<B1-Motion>", move)
    root.bind("<ButtonRelease-1>", release)
    root.bind("<Motion>", hover)
    root.bind("<Leave>", lambda e: (S.update(hover=""), draw()) if S["hover"] else None)
    layout()

    def tick():
        if not user32.IsWindow(wintypes.HWND(hwnd)):
            save_state(x=S["x"], y=S["y"], w=S["w"], h=S["h"])
            root.destroy()
            return
        pin(hwnd, S["x"], S["y"], S["w"], S["h"], opacity, click_through)
        user32.SetWindowPos(ctypes.c_void_p(top_hwnd), wintypes.HWND(HWND_TOPMOST), 0, 0, 0, 0, 0x13)  # NOMOVE|NOSIZE|NOACTIVATE
        bar.attributes("-topmost", True)
        bar.lift()
        n = cache.get("n", 0) + 1
        cache["n"] = n
        if port and n % 8 == 0 and root.focus_get() is not entry:  # keep the address bar in sync with the page
            found = _page_ws(port)
            if found and found[1] and found[1] != var.get() and not found[1].startswith("chrome-error"):
                var.set(found[1])
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
