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
    hwnd = (user32.FindWindowW("GxWindowClass", None) or user32.FindWindowW("GxWindowClassD3d", None)
            or user32.FindWindowW(None, "World of Warcraft"))
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
    ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE) | WS_EX_TOOLWINDOW
    ex = ex | WS_EX_TRANSPARENT if click_through else ex & ~WS_EX_TRANSPARENT
    # Chrome draws through DirectComposition: a layered style makes the page invisible, so only use it for see-through
    see_through = opacity < 100
    ex = ex | WS_EX_LAYERED if see_through else ex & ~WS_EX_LAYERED
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex)
    if see_through:
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
    last = saved.get("url") or ""
    if last.startswith(("http://127.0.0.1", "http://localhost")):  # the AI setup page only lives while the bridge runs
        last = ""
    url = url or last or "https://www.google.com"
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
EDGE_SIZE, INSET, MARGIN = 24, 6, 9
KEY_RGB, KEY = (1, 2, 3), "#010203"  # border art size, backdrop inset, visible border thickness (content margin)
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


def slot_sprite(state: str = ""):
    """An empty-looking action bar button (64x64 sprite, the 36x36 slot in the middle) with the browser icon in it,
    built from the game's own action button textures: dark slot, icon, slot frame, hover glow, pressed look."""
    from PIL import Image, ImageChops

    out = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    out.alpha_composite(_art("UI-Quickslot.png"))
    icon = _art("INV_Misc_Map_01.png")
    icon = icon.crop((5, 5, 59, 59)).resize((36, 36), Image.LANCZOS)  # action buttons show texcoords 0.08-0.92
    out.alpha_composite(icon, (14, 14))
    out.alpha_composite(_art("UI-Quickslot2.png"))
    if state == "down":  # pressed: the icon dims slightly, like a pushed action button
        dim = Image.new("RGBA", (36, 36), (0, 0, 0, 90))
        out.alpha_composite(dim, (14, 14))
    if state == "hover":
        hl = _art("ButtonHilight-Square.png").resize((36, 36), Image.LANCZOS)
        region = out.crop((14, 14, 50, 50))
        rgb = ImageChops.add(region.convert("RGB"), hl.convert("RGB"))
        rgb.putalpha(region.getchannel("A"))
        out.paste(rgb, (14, 14))
    return out


CB = (6, 7, 25, 25)  # the red button inside the 32x32 UIPanelCloseButton texture (19x18)
BW, BH, BY = CB[2] - CB[0], CB[3] - CB[1], 8


def buttons(fw: int) -> dict:
    """Top-right buttons (x, y, w, h): close, minimize (green), ghost; the address bar ends left of them."""
    close = fw - 8 - BW
    mini = close - 4 - BW
    ghost = mini - 4 - BW
    return {n: (x, BY, BW, BH) for n, x in (("close", close), ("min", mini), ("ghost", ghost))}


def _button_art(kind: str, on: bool = False):
    """Button faces made from the game's own close-button art: red X (close), green dash (minimize), ghost."""
    from PIL import Image, ImageDraw, ImageOps

    base = _art("UI-Panel-MinimizeButton-Up.png").crop(CB)
    if kind == "close":
        return base
    px = base.load()
    for yy in range(base.height):  # wipe the gold X so a new glyph can be drawn
        for xx in range(base.width):
            r, g, b, a = px[xx, yy]
            if a and g > 55 and r > g:
                px[xx, yy] = (112, 22, 16, a)
    ImageDraw.Draw(base).rectangle((4, 4, 14, 13), fill=(112, 22, 16, 255))  # flat panel, no X shadow left
    r, g, b, a = base.split()
    if kind == "min":
        face = Image.merge("RGBA", (g, r, b, a))  # red -> green
        ImageDraw.Draw(face).rectangle((5, 8, 13, 9), fill=(242, 194, 48, 255))
        return face
    gray = ImageOps.grayscale(base.convert("RGB")).convert("RGB")  # ghost: dark steel button
    face = Image.merge("RGBA", (*[c.point(lambda v: int(v * 0.8)) for c in gray.split()], a))
    d = ImageDraw.Draw(face)
    fill = (150, 215, 255, 255) if on else (235, 235, 245, 255)
    d.ellipse((5, 3, 13, 10), fill=fill)
    d.rectangle((5, 7, 13, 13), fill=fill)
    for bx in (5, 8, 11):  # wavy hem
        d.polygon([(bx, 13), (bx + 3, 13), (bx + 1, 15)], fill=fill)
    d.rectangle((7, 7, 8, 8), fill=(30, 30, 50, 255))
    d.rectangle((10, 7, 11, 8), fill=(30, 30, 50, 255))
    return face


def compose(fw: int, fh: int, top: int, hover: str = "", down: str = "", ghost: bool = False):
    """Render the whole frame as an RGBA image; the content window area is fully transparent."""
    from PIL import Image, ImageChops, ImageDraw

    out = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
    # background only in the top strip (the page fills everything else, no grey seam beside the border)
    tile = _art("UI-DialogBox-Background.png").resize((32, 32))
    bg = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
    for yy in range(INSET, top, 32):
        for xx in range(INSET, fw - INSET, 32):
            bg.paste(tile, (xx, yy))
    mask = Image.new("L", (fw, fh), 0)
    mask.paste(255, (INSET, INSET, fw - INSET, top))
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
    # buttons: ghost | minimize (green) | close (red), all inside the top strip
    hl = _art("UI-Panel-MinimizeButton-Highlight.png").crop(CB)
    for name, (bx, by, bw, bh) in buttons(fw).items():
        face = _button_art("close" if (name == "close" and down == "close") else name, ghost and name == "ghost")
        if name == "close" and down == "close":
            face = _art("UI-Panel-MinimizeButton-Down.png").crop(CB)
        out.alpha_composite(face, (bx, by))
        if hover == name:
            region = out.crop((bx, by, bx + bw, by + bh))
            rgb = ImageChops.add(region.convert("RGB"), hl.convert("RGB"))
            rgb.putalpha(ImageChops.lighter(region.getchannel("A"), hl.getchannel("A")))
            out.paste(rgb, (bx, by))
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
    """Draw the WoW frame above the browser window (per-pixel alpha; the browser area is see-through and clickable).

    Top strip: label, address bar, ghost (see-through + click-through mode), minimize (becomes a draggable
    button that remembers its spot), close. Position, size, button spot and ghost mode survive restarts.
    """
    import tkinter as tk
    from PIL import ImageTk

    GWL_STYLE, WS_CAPTION, WS_THICKFRAME, WS_BORDER = -16, 0xC00000, 0x40000, 0x800000
    st = user32.GetWindowLongW(hwnd, GWL_STYLE) & ~(WS_CAPTION | WS_THICKFRAME | WS_BORDER)
    user32.SetWindowLongW(hwnd, GWL_STYLE, st)
    saved = load_state()
    S = {"x": x, "y": y, "w": w, "h": h, "hover": "", "down": "", "ghost": bool(saved.get("ghost")), "min": False}
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
    var = tk.StringVar(value=saved.get("url", ""))
    entry = tk.Entry(bar, textvariable=var, bg="#0d0c09", fg="#ffd100", insertbackground="#ffd100", relief="flat",
                     font=("Arial", 9), highlightthickness=1, highlightbackground="#5c5c5c", highlightcolor="#b4b4b4",
                     selectbackground="#5c4a1a", selectforeground="#ffffff")
    entry.pack(fill="both", expand=True, padx=1, pady=1)

    def go(_e=None):
        if port and navigate(port, var.get()):
            root.focus_force()
        return "break"

    entry.bind("<Return>", go)
    entry.bind("<Button-1>", lambda e: (bar.focus_force(), entry.focus_set()))
    entry.bind("<Escape>", lambda e: root.focus_force())

    # floating button shown while minimized: an action-bar slot, draggable onto an empty slot, click restores
    fl = tk.Toplevel(root)
    fl.overrideredirect(True)
    fl.attributes("-topmost", True)
    fl.geometry("64x64+0+0")
    FL = {"h": 0}

    def fl_layered() -> None:
        """(Re)apply the layered style: Tk may create a new native window when it is shown again."""
        fl.update_idletasks()
        FL["h"] = user32.GetParent(fl.winfo_id()) or fl.winfo_id()
        user32.SetWindowLongW(ctypes.c_void_p(FL["h"]), GWL_EXSTYLE,
                              user32.GetWindowLongW(ctypes.c_void_p(FL["h"]), GWL_EXSTYLE) | WS_EX_LAYERED | WS_EX_TOOLWINDOW)
    sprites = {s: slot_sprite(s) for s in ("", "hover", "down")}
    rect = game_rect() or (0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))
    S["bx"] = int(saved.get("bx", rect[2] - 150))  # top-left of the 64x64 sprite; the slot itself is 14 px inside
    S["by"] = int(saved.get("by", rect[1] + 80))
    fdrag: dict = {}

    def keep_on_game() -> None:
        """A remembered button spot outside the game window (moved window, other monitor) would be invisible: pull it back in."""
        r = game_rect() or rect
        if not (r[0] - 20 <= S["bx"] <= r[2] - 44 and r[1] - 20 <= S["by"] <= r[3] - 44):
            S["bx"], S["by"] = r[2] - 150, r[1] + 80

    def fl_draw(state: str = "") -> None:
        fl.geometry(f"64x64+{S['bx']}+{S['by']}")
        fl.update_idletasks()
        update_layered(FL["h"], sprites[state], S["bx"], S["by"])

    def persist() -> None:
        save_state(x=S["x"], y=S["y"], w=S["w"], h=S["h"], ghost=S["ghost"], bx=S["bx"], by=S["by"])

    def set_min(on: bool) -> None:
        S["min"] = on
        if on:
            keep_on_game()
            user32.ShowWindow(wintypes.HWND(hwnd), 0)
            root.withdraw()
            bar.withdraw()
            fl.deiconify()
            fl_layered()
            fl_draw()
            user32.SetWindowPos(ctypes.c_void_p(FL["h"]), wintypes.HWND(HWND_TOPMOST), 0, 0, 0, 0, 0x53)
        else:
            fl.withdraw()
            root.deiconify()
            bar.deiconify()
            user32.ShowWindow(wintypes.HWND(hwnd), 4)
            layout()

    def fl_down(e):
        fdrag.update(dx=e.x_root - S["bx"], dy=e.y_root - S["by"], sx=e.x_root, sy=e.y_root, moved=False)
        fl_draw("down")

    def fl_move(e):
        if abs(e.x_root - fdrag["sx"]) + abs(e.y_root - fdrag["sy"]) > 4:
            fdrag["moved"] = True
        if fdrag["moved"]:
            S["bx"], S["by"] = e.x_root - fdrag["dx"], e.y_root - fdrag["dy"]
            fl_draw("down")

    def fl_up(_e):
        persist()
        if not fdrag.get("moved"):
            set_min(False)
        else:
            fl_draw()

    fl.bind("<Button-1>", fl_down)
    fl.bind("<B1-Motion>", fl_move)
    fl.bind("<ButtonRelease-1>", fl_up)
    fl.bind("<Enter>", lambda e: fl_draw("hover") if not fdrag else None)
    fl.bind("<Leave>", lambda e: fl_draw() if not fdrag else None)
    fl.withdraw()

    def place_bar() -> None:
        fw = S["w"] + 2 * EDGE
        lw = label_width()
        gx = buttons(fw)["ghost"][0]
        bar.geometry(f"{max(60, gx - 4 - lw)}x18+{S['x'] - EDGE + lw}+{S['y'] - TOP + 10}")

    def dims():
        return S["w"] + 2 * EDGE, S["h"] + TOP + EDGE

    def draw() -> None:
        fw, fh = dims()
        cache["img"] = compose(fw, fh, top, S["hover"], S["down"], S["ghost"])
        update_layered(top_hwnd, cache["img"], S["x"] - EDGE, S["y"] - TOP)

    def layout() -> None:
        fw, fh = dims()
        root.geometry(f"{fw}x{fh}+{S['x'] - EDGE}+{S['y'] - TOP}")
        draw()
        place_bar()

    def zone(e) -> str:
        fw, fh = dims()
        for name, (bx, by, bw, bh) in buttons(fw).items():
            if bx - 1 <= e.x <= bx + bw + 1 and by - 1 <= e.y <= by + bh + 1:
                return name
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
                persist()
                user32.PostMessageW(wintypes.HWND(hwnd), 0x0010, 0, 0)
        elif was == "min" and zone(e) == "min":
            persist()
            set_min(True)
        elif was == "ghost" and zone(e) == "ghost":
            S["ghost"] = not S["ghost"]
            draw()
            persist()
        elif was:
            persist()
        drag.clear()

    def hover(e):
        z = zone(e)
        want = z if z in ("close", "min", "ghost") else ""
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
            persist()
            root.destroy()
            return
        if not S["min"]:
            ghost = S["ghost"]
            pin(hwnd, S["x"], S["y"], S["w"], S["h"], 35 if ghost else opacity, click_through or ghost)
            user32.SetWindowPos(ctypes.c_void_p(top_hwnd), wintypes.HWND(HWND_TOPMOST), 0, 0, 0, 0, 0x13)
            bar.attributes("-topmost", True)
            bar.lift()
            n = cache.get("n", 0) + 1
            cache["n"] = n
            if port and n % 8 == 0 and root.focus_get() is not entry:  # keep the address bar in sync with the page
                found = _page_ws(port)
                if found and found[1] and found[1] != var.get() and not found[1].startswith("chrome-error"):
                    var.set(found[1])
        else:
            user32.SetWindowPos(ctypes.c_void_p(FL["h"]), wintypes.HWND(HWND_TOPMOST), 0, 0, 0, 0, 0x53)
        root.after(250, tick)

    tick()
    root.mainloop()


def play(url: str, size: str | None = None) -> None:
    """Called by the bridge for [[play URL]] / "/browser": start the overlay in the background ("" = last page),
    or close it for ``off``."""
    if url == "off":
        _kill_profile_browsers(config.HOME / "overlay-profile")
        return
    import sys
    args = [sys.executable, "-m", "wowclaude", "overlay"] + ([url] if url else []) + (["--size", size] if size else [])
    subprocess.Popen(args, creationflags=0x08000000)


_ours: set[int] = set()
