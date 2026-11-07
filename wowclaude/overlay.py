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
import sys
import time
import urllib.parse
import urllib.request
from ctypes import wintypes
from pathlib import Path

from . import config
from .winproc import hidden

user32 = ctypes.windll.user32 if os.name == "nt" else None

GWL_EXSTYLE = -20
WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW = 0x80000, 0x20, 0x80
HWND_TOPMOST = -1
SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x10, 0x40
LWA_ALPHA = 0x2


def dpi_scale() -> float:
    """Display scale as a factor (1.0 = 100 %, 1.5 = 150 %). Makes this process DPI-aware first so the answer is real."""
    if sys.platform != "win32":
        return 1.0
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (OSError, AttributeError):
        pass
    try:
        return max(1.0, min(4.0, ctypes.windll.user32.GetDpiForSystem() / 96))
    except (OSError, AttributeError):
        return 1.0


SCALE = dpi_scale()
CHROME_BAR = round(34 * SCALE)  # height of Chrome's own app-window title bar (hidden behind the WoW frame); grows with the display scale

CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
]


CREATE_NO_WINDOW = 0x08000000


def find_browser() -> str | None:
    for c in CANDIDATES:
        if Path(c).exists():
            return c
    return shutil.which("chrome") or shutil.which("msedge")


def _window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    return pid.value


def _on_screen(x: int, y: int, w: int, h: int) -> bool:
    """Is the middle of the window on a connected monitor? (a monitor may have been unplugged since last time)"""
    vx, vy = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)  # virtual screen origin
    vw, vh = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
    cx, cy = x + w // 2, y + h // 2
    return vx <= cx < vx + vw and vy <= cy < vy + vh


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


def _game_hwnd() -> int:
    return (user32.FindWindowW("GxWindowClass", None) or user32.FindWindowW("GxWindowClassD3d", None)
            or user32.FindWindowW(None, "World of Warcraft"))


def keep_page_above_game(page: int) -> None:
    """Windows ignores 'topmost' for the Chrome page now and then, and the page then hides behind the game (only the
    frame is visible). If the game is above the page, put the game directly beneath it."""
    game = _game_hwnd()
    if not game or not page:
        return
    h = user32.GetWindow(wintypes.HWND(page), 3)  # GW_HWNDPREV: walk upwards
    n = 0
    while h and n < 400:
        if h == game:
            user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                            ctypes.c_int, wintypes.UINT]
            user32.SetWindowPos(wintypes.HWND(game), wintypes.HWND(page), 0, 0, 0, 0, 0x13)  # NOMOVE|NOSIZE|NOACTIVATE
            return
        h = user32.GetWindow(wintypes.HWND(h), 3)
        n += 1


def game_rect() -> tuple[int, int, int, int] | None:
    """Client area of the game window in screen pixels (without title bar and borders in windowed mode)."""
    hwnd = _game_hwnd()
    if not hwnd:
        return None
    r = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    if r.right - r.left < 100 or r.bottom - r.top < 100:  # minimized (client area collapses)
        return None
    return pt.x, pt.y, pt.x + r.right - r.left, pt.y + r.bottom - r.top


def game_minimized() -> bool:
    hwnd = _game_hwnd()
    return bool(hwnd and user32.IsIconic(hwnd))


def to_rel(g, x: int, y: int, w: int, h: int) -> list:
    """Window geometry as fractions of the game window, so it can follow when the game is moved or resized."""
    gw, gh = max(1, g[2] - g[0]), max(1, g[3] - g[1])
    return [(x - g[0]) / gw, (y - g[1]) / gh, w / gw, h / gh]


def from_rel(g, rel) -> tuple[int, int, int, int]:
    gw, gh = g[2] - g[0], g[3] - g[1]
    return (round(g[0] + rel[0] * gw), round(g[1] + rel[1] * gh), max(MIN_W, round(rel[2] * gw)), max(MIN_H, round(rel[3] * gh)))


def place(w: int, h: int, corner: str, margin: int = 24) -> tuple[int, int]:
    rect = game_rect()
    if rect is None:
        rect = (0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))
    l, t, r, b = rect
    x = l + margin if "l" in corner else r - w - margin
    y = t + margin + 40 if "t" in corner else b - h - margin
    return x, y


STRIP_W, STRIP_H = 560, 70  # the addon's colour strip (top-left corner of the game): a window over it blinds the program


def _off_strip(x: int, y: int, rect) -> tuple[int, int]:
    """Move a window that would start on top of the colour strip below it (messages would stop arriving)."""
    if rect and rect[0] - 5 <= x < rect[0] + STRIP_W and rect[1] - 5 <= y < rect[1] + STRIP_H:
        return x, rect[1] + STRIP_H
    return x, y


_pinned: dict = {}


def _border(hwnd: int) -> int:
    """Chrome keeps an invisible resize border (7 px at 100 %) left, right and below the page: measure it so the
    page can be made to fill the frame without gaps."""
    if "b" in _pinned:
        return _pinned["b"]
    r = wintypes.RECT()
    user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(r))
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(wintypes.HWND(hwnd), ctypes.byref(pt))
    b = pt.x - r.left
    if 0 <= b <= 24:
        _pinned["b"] = b
        return b
    return 0


def pin(hwnd: int, x: int, y: int, w: int, h: int, opacity: int, click_through: bool) -> None:
    """Place the browser window: its top-left is (x, y), size w x (h + CHROME_BAR). The WoW frame covers the bar.

    Called every tick, but only touches the window when something changed (re-applying style, region and position
    4x per second made the page blink); the clip region is refreshed now and then because Chrome may reset it.
    """
    key = (hwnd, x, y, w, h, opacity, click_through)
    n = _pinned.get("n", 0) + 1
    if _pinned.get("key") == key and n % 20:
        _pinned["n"] = n
        # Chrome drops the clip region now and then (page load, navigation): its grey title bar would show: put it back
        probe = ctypes.windll.gdi32.CreateRectRgn(0, 0, 0, 0)
        has_region = user32.GetWindowRgn(wintypes.HWND(hwnd), ctypes.c_void_p(probe)) != 0
        box = wintypes.RECT()
        if has_region:
            ctypes.windll.gdi32.GetRgnBox(ctypes.c_void_p(probe), ctypes.byref(box))
        ctypes.windll.gdi32.DeleteObject(ctypes.c_void_p(probe))
        # it must be OUR region: Chrome sets its own (rounded corners) and that one shows the title bar
        b = _border(hwnd)
        if has_region and box.left == b and box.top == CHROME_BAR and box.right == b + w and box.bottom == CHROME_BAR + h:
            return
        rgn = ctypes.windll.gdi32.CreateRectRgn(b, CHROME_BAR, b + w, CHROME_BAR + h)
        user32.SetWindowRgn(wintypes.HWND(hwnd), ctypes.c_void_p(rgn), False)
        return
    _pinned.update(key=key, n=n)
    ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE) | WS_EX_TOOLWINDOW
    ex = ex | WS_EX_TRANSPARENT if click_through else ex & ~WS_EX_TRANSPARENT
    # Chrome draws through DirectComposition: a layered style makes the page invisible, so only use it for see-through
    see_through = opacity < 100
    ex = ex | WS_EX_LAYERED if see_through else ex & ~WS_EX_LAYERED
    if ex != user32.GetWindowLongW(hwnd, GWL_EXSTYLE):
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex)
    if see_through:
        user32.SetLayeredWindowAttributes(hwnd, 0, int(255 * max(10, min(100, opacity)) / 100), LWA_ALPHA)
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, wintypes.UINT]
    b = _border(hwnd)
    user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(HWND_TOPMOST), x - b, y - CHROME_BAR, w + 2 * b,
                        h + CHROME_BAR + b, SWP_NOACTIVATE | SWP_SHOWWINDOW)
    # Chrome's own title bar is the top CHROME_BAR pixels: cut them off
    rgn = ctypes.windll.gdi32.CreateRectRgn(b, CHROME_BAR, b + w, CHROME_BAR + h)
    user32.SetWindowRgn(wintypes.HWND(hwnd), ctypes.c_void_p(rgn), False)


def _painted(hwnd: int, w: int, h: int) -> bool:
    """True when the browser window really contains a picture (a blank Chrome window prints as one flat colour)."""
    from PIL import Image
    gdi = ctypes.windll.gdi32
    user32.GetDC.restype = ctypes.c_void_p
    hdc = user32.GetDC(None)
    gdi.CreateCompatibleDC.restype = ctypes.c_void_p
    mdc = gdi.CreateCompatibleDC(ctypes.c_void_p(hdc))
    gdi.CreateCompatibleBitmap.restype = ctypes.c_void_p
    bmp = gdi.CreateCompatibleBitmap(ctypes.c_void_p(hdc), w, h)
    gdi.SelectObject(ctypes.c_void_p(mdc), ctypes.c_void_p(bmp))
    try:
        user32.PrintWindow(wintypes.HWND(hwnd), ctypes.c_void_p(mdc), 2)

        class BI(ctypes.Structure):
            _fields_ = [("s", wintypes.DWORD), ("w", wintypes.LONG), ("h", wintypes.LONG), ("p", wintypes.WORD),
                        ("b", wintypes.WORD), ("c", wintypes.DWORD), ("z", wintypes.DWORD), ("x", wintypes.LONG),
                        ("y", wintypes.LONG), ("u", wintypes.DWORD), ("i", wintypes.DWORD)]

        bi = BI(ctypes.sizeof(BI), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        buf = ctypes.create_string_buffer(w * h * 4)
        gdi.GetDIBits(ctypes.c_void_p(mdc), ctypes.c_void_p(bmp), 0, h, buf, ctypes.byref(bi), 0)
        im = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")
        seen = {im.getpixel((x, y)) for x in range(CHROME_BAR, w - 10, 23) for y in range(CHROME_BAR + 10, h - 10, 17)}
        return len(seen) > 1
    except Exception:  # noqa: BLE001 - if we cannot tell, assume it is fine
        return True
    finally:
        gdi.DeleteObject(ctypes.c_void_p(bmp))
        gdi.DeleteDC(ctypes.c_void_p(mdc))
        user32.ReleaseDC(None, ctypes.c_void_p(hdc))


def _wait_painted(hwnd: int, w: int, h: int, seconds: float = 8.0) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if _painted(hwnd, w, h):
            return True
        time.sleep(0.15)
    return False


def _kill_profile_browsers(profile: Path) -> None:
    """A browser already running on our own profile would swallow the new window (and the debug port): close it."""
    # WQL filter on the name (fast) instead of looking at every process; "K" is printed per closed process
    # Closed politely first (CloseMainWindow, up to 4 s): a killed Chrome loses the cookies and logins of the last ~30 s.
    cmd = ("$ids = @(Get-CimInstance Win32_Process -Filter \"Name='chrome.exe' OR Name='msedge.exe' OR Name='brave.exe'\" | "
           "Where-Object { $_.CommandLine -like '*" + profile.name + "*' } | ForEach-Object { $_.ProcessId }); "
           "foreach ($i in $ids) { Get-Process -Id $i -ErrorAction SilentlyContinue | ForEach-Object { [void]$_.CloseMainWindow() } }; "
           "$end = (Get-Date).AddSeconds(4); "
           "while ((Get-Date) -lt $end -and @(Get-Process -Id $ids -ErrorAction SilentlyContinue).Count -gt 0) { Start-Sleep -Milliseconds 150 }; "
           "foreach ($i in $ids) { Stop-Process -Id $i -Force -ErrorAction SilentlyContinue }; "
           "if ($ids.Count -gt 0) { 'K' }")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=25,
                           **hidden())
        if "K" in (r.stdout or ""):
            time.sleep(0.5)  # only wait when something was really closed
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


def _cdp(port: int, method: str, params: dict) -> bool:
    """Send one DevTools protocol command to the browser's page (stdlib websocket client)."""
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
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        sk.sendall(req.encode())
        sk.recv(4096)
        payload = json.dumps({"id": 1, "method": method, "params": params}).encode()
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
    return True


PAGE: dict = {"found": None, "t": 0.0}  # last (ws url, page url) seen by the poller thread; the Tk thread only reads this


def start_poller(port: int, every: float = 2.0) -> "threading.Thread":
    """Ask the browser for its page in the background, so the window never waits on DevTools (it can be slow or stuck)."""
    import threading

    def loop() -> None:
        while True:
            PAGE["found"] = _page_ws(port)
            PAGE["t"] = time.time()
            time.sleep(every)

    t = threading.Thread(target=loop, daemon=True, name="overlay-page-poller")
    t.start()
    return t


def in_background(fn, *args) -> None:
    """Run a DevTools call off the Tk thread (fire and forget)."""
    import threading
    threading.Thread(target=fn, args=args, daemon=True).start()


def history_step(port: int, step: int) -> bool:
    """Back (-1) or forward (+1) in the page's history."""
    return _cdp(port, "Runtime.evaluate", {"expression": "history.go(%d)" % (-1 if step < 0 else 1)})


def navigate(port: int, text: str) -> bool:
    """Send the browser to ``text``: a URL, a domain, or search words (Google). Uses the DevTools protocol (stdlib only)."""
    text = text.strip()
    if not text:
        return False
    if " " in text or ("." not in text and not text.startswith(("http://", "https://", "localhost"))):
        url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(text)
    else:
        url = text if text.startswith(("http://", "https://")) else "https://" + text
    if not _cdp(port, "Page.navigate", {"url": url}):
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


ALIVE_FILE = STATE_FILE.parent / "overlay.alive"


def touch_alive() -> None:
    try:
        ALIVE_FILE.write_text(str(time.time()))
    except OSError:
        pass


def overlay_alive(max_age: float = 2.5) -> bool:
    try:
        return time.time() - float(ALIVE_FILE.read_text()) < max_age
    except (OSError, ValueError):
        return False


def save_state(**kw) -> None:
    st = load_state()
    st.update(kw)
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(st), encoding="utf-8")
    except OSError:
        pass


def bookmarks() -> list[dict]:
    """The saved pages: [{"title", "url"}], in the order they were added."""
    out = []
    for b in load_state().get("bookmarks") or []:
        if isinstance(b, dict) and str(b.get("url", "")).startswith(("http://", "https://")):
            out.append({"title": str(b.get("title") or b["url"]), "url": b["url"]})
    return out


def add_bookmark(url: str, title: str = "") -> bool:
    """Save a page (once per address). False for addresses that make no sense to keep."""
    if not url.startswith(("http://", "https://")) or any(b["url"] == url for b in bookmarks()):
        return False
    host = urllib.parse.urlparse(url).netloc.removeprefix("www.")
    save_state(bookmarks=bookmarks() + [{"title": (title or host or url)[:40], "url": url}])
    return True


def remove_bookmark(url: str) -> None:
    save_state(bookmarks=[b for b in bookmarks() if b["url"] != url])


def reload_page(port: int) -> bool:
    return _cdp(port, "Page.reload", {})


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
    # no address given (/browser, button): come back to the page the browser was closed on, else the search engine
    url = url or saved.get("last_page") or "https://www.google.com"
    g0 = game_rect()
    rel = saved.get("rel")
    if size:
        w, h = (int(v) for v in size.lower().split("x"))
    elif rel and g0:
        w, h = from_rel(g0, rel)[2:]
    else:
        w, h = int(saved.get("w", 480)), int(saved.get("h", 270))
    if corner or "x" not in saved:
        x, y = place(w, h + TOP + EDGE, corner or "br")
    elif rel and g0:
        x, y = from_rel(g0, rel)[:2]
    else:
        x, y = int(saved["x"]), int(saved["y"])  # remembered position (browser window top-left)
    if not corner and not _on_screen(x, y, w, h):
        x, y = place(w, h + TOP + EDGE, "br")  # remembered spot is gone (monitor unplugged): back into the game
    x, y = _off_strip(x, y, g0)
    save_state(url=url, x=x, y=y, w=w, h=h)
    profile = config.HOME / "overlay-profile"
    profile.mkdir(parents=True, exist_ok=True)
    hwnd, port = 0, 0
    t0 = time.time()
    marks: list[str] = []
    for attempt in range(3):  # Chrome sometimes opens a window that never paints (stays blank): then start it again
        _kill_profile_browsers(profile)
        marks.append(f"cleanup {time.time() - t0:.1f}s")
        port = free_port()
        before = set(_windows())
        proc = subprocess.Popen(
            [exe, f"--app={url}", f"--user-data-dir={profile}", f"--window-size={w},{h + CHROME_BAR}",
             f"--window-position={x},{y - CHROME_BAR}", "--autoplay-policy=no-user-gesture-required",
             "--no-first-run", "--disable-features=Translate,CalculateNativeWinOcclusion",
             "--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding",
             f"--remote-debugging-port={port}"],
            creationflags=CREATE_NO_WINDOW)
        hwnd = 0
        for _ in range(300):
            time.sleep(0.1)
            new = set(_windows()) - before
            mine = [h_ for h_ in new if _window_pid(h_) == proc.pid]  # not another Chrome-based app that opened meanwhile
            if mine or (new and _ > 100):
                hwnd = sorted(mine or new)[0]
                break
        if not hwnd:
            print("Browser window did not appear.")
            return 1
        marks.append(f"window {time.time() - t0:.1f}s")
        if _wait_painted(hwnd, w, h + CHROME_BAR):
            break
        print(f"Browser window stayed blank (try {attempt + 1}/3), restarting it ...", flush=True)
    marks.append(f"painted {time.time() - t0:.1f}s")
    print("timing:", ", ".join(marks), flush=True)
    print(f"Overlay running ({w}x{h}, debug port {port}). Drag the title bar to move, the corner to resize, X to close; "
          "position and size are remembered. Log in once in this window (own profile).", flush=True)
    frame_loop(hwnd, x, y, w, h, opacity, click_through, port)
    return 0


# The frame is built from the game's own UI textures (DialogFrame/UI-DialogBox-*, UIPanelCloseButton art, chat
# resize grabber), assembled exactly like the in-game overlay window (Backdrop: edgeSize 24, tile 32, insets 6).
# It is a per-pixel-alpha window, so the translucent dark background shows the game behind it, like the real thing.
EDGE_SIZE, INSET, MARGIN = 24, 6, 9
KEY_RGB, KEY = (1, 2, 3), "#010203"  # border art size, backdrop inset, visible border thickness (content margin)
EDGE = MARGIN  # frame thickness left/right/bottom
TOP = max(40, CHROME_BAR + 6)  # top strip with the address bar and buttons; Chrome draws its first 7 rows over the frame edge, so they must lie under the opaque part (TOP >= CHROME_BAR + 5)


_art_cache: dict = {}


PACKAGED_ART = Path(__file__).parent / "art"


def _art(name: str):
    """Frame texture: your own copy in ~/.wowclaude/art/, else the WoW textures shipped in wowclaude/art/, else the
    artwork drawn in code (frame_art.py)."""
    from PIL import Image
    if name not in _art_cache:
        _art_cache[name] = None
        for folder in (config.HOME / "art", PACKAGED_ART):
            try:
                if (folder / name).is_file():
                    _art_cache[name] = Image.open(folder / name).convert("RGBA")
                    break
            except OSError:
                continue
        if _art_cache[name] is None:
            from . import frame_art
            _art_cache[name] = frame_art.generate(name)
    return _art_cache[name].copy()


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
    out.alpha_composite(Image.new("RGBA", (36, 36), (16, 34, 92, 255)), (14, 14))  # plain dark blue background (no icon)
    out.alpha_composite(_art("UI-Quickslot2.png"))
    from PIL import ImageDraw  # a yellow globe (the browser symbol), drawn 4x larger and scaled down for smooth lines
    big = Image.new("RGBA", (144, 144), (0, 0, 0, 0))
    g = ImageDraw.Draw(big)
    gold, dark, c, r, L = (255, 209, 0, 255), (0, 0, 0, 255), 72, 34, 68
    for col, grow in ((dark, 5), (gold, 0)):  # black outline first, then the yellow lines on top
        for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):  # four spikes (north, east, south, west) like a compass star
            nx, ny, hw = -dy, dx, 9 + grow
            bx, by = c + dx * (r - 2), c + dy * (r - 2)
            g.polygon([(bx + nx * hw, by + ny * hw), (c + dx * (L + grow), c + dy * (L + grow)), (bx - nx * hw, by - ny * hw)], fill=col)
        w = 8 + 2 * grow
        g.ellipse((c - r, c - r, c + r, c + r), outline=col, width=w)
        g.ellipse((c - r // 2, c - r, c + r // 2, c + r), outline=col, width=w - 2)  # meridian
        g.line((c - r, c, c + r, c), fill=col, width=w - 2)  # equator
    out.alpha_composite(big.resize((36, 36), Image.LANCZOS), (14, 14))
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
BW, BH, BY = CB[2] - CB[0], CB[3] - CB[1], 14


def buttons(fw: int) -> dict:
    """Top-right buttons (x, y, w, h): close, minimize (green), ghost; the address bar ends left of them."""
    close = fw - 16 - BW  # same gap to the right border as the label has to the left one
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


def compose(fw: int, fh: int, top: int, hover: str = "", down: str = "", ghost: bool = False,
            names: tuple = (), label: str = "", tile_bg: bool = True):
    """Render the whole frame as an RGBA image; the content window area is fully transparent."""
    from PIL import Image, ImageChops, ImageDraw

    out = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
    # background only in the top strip (the page fills everything else, no grey seam beside the border)
    tile = _art("UI-DialogBox-Background.png").resize((32, 32))
    bg = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
    for yy in range(INSET, top if tile_bg else INSET, 32):  # (other windows paint their own window colour instead)
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
        if names and name not in names:  # other windows (panel, editor) show only the buttons they have
            continue
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
    draw.text((15, ty + 1), label or LABEL, font=font, fill=(0, 0, 0, 255), anchor="lm")  # WoW-style drop shadow
    draw.text((14, ty), label or LABEL, font=font, fill=(255, 209, 0, 255), anchor="lm")
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


def initial_state(x: int, y: int, w: int, h: int, saved: dict) -> dict:
    """Start state of the frame. Ghost mode is never restored: a freshly opened browser that is see-through and
    click-through looks as if it did not open at all."""
    return {"x": x, "y": y, "w": w, "h": h, "hover": "", "down": "", "ghost": False, "min": False}


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
    S = initial_state(x, y, w, h, saved)
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
    if port:
        start_poller(port)
    def bar_button(glyph, command):
        btn = tk.Button(bar, text=glyph, command=command, width=2, relief="flat",
                        bg="#2a2417", fg="#ffd100", activebackground="#5c4a1a", activeforeground="#ffffff",
                        font=("Arial", 7), bd=0, highlightthickness=0, takefocus=0)
        btn.pack(side="left", fill="y")
        return btn

    def open_url(u):
        if port:
            in_background(navigate, port, u)

    def bookmark_menu():
        """The saved pages: click one to open it; add the current page; remove one."""
        m = tk.Menu(bar, tearoff=0, bg="#15130e", fg="#ffd100", activebackground="#5c4a1a", activeforeground="#ffffff", bd=1)
        cur = (PAGE["found"] or ("", ""))[1]
        can_add = cur.startswith(("http://", "https://")) and not any(b["url"] == cur for b in bookmarks())
        m.add_command(label="+ Add this page", state="normal" if can_add else "disabled",
                      command=lambda: add_bookmark(cur))
        saved = bookmarks()
        if saved:
            m.add_separator()
        for b in saved:
            m.add_command(label=b["title"], command=lambda u=b["url"]: open_url(u))
        if saved:
            m.add_separator()
            rm = tk.Menu(m, tearoff=0, bg="#15130e", fg="#ffd100", activebackground="#5c4a1a", activeforeground="#ffffff")
            for b in saved:
                rm.add_command(label=b["title"], command=lambda u=b["url"]: remove_bookmark(u))
            m.add_cascade(label="Remove", menu=rm)
        return m

    def show_bookmarks():
        m = bookmark_menu()
        x, y = bar.winfo_rootx(), bar.winfo_rooty() + bar.winfo_height()
        try:
            m.tk_popup(x, y)
        finally:
            m.grab_release()

    bar_button("▾", show_bookmarks)  # saved pages
    for glyph, step in (("◀", -1), ("▶", 1)):  # back / forward in the page history
        bar_button(glyph, lambda st=step: port and in_background(history_step, port, st))
    bar_button("⟳", lambda: port and in_background(reload_page, port))  # reload
    entry = tk.Entry(bar, textvariable=var, bg="#0d0c09", fg="#ffd100", insertbackground="#ffd100", relief="flat",
                     font=("Arial", 9), highlightthickness=1, highlightbackground="#5c5c5c", highlightcolor="#b4b4b4",
                     selectbackground="#5c4a1a", selectforeground="#ffffff")
    entry.pack(fill="both", expand=True, padx=1, pady=1)

    def go(_e=None):
        if port:
            in_background(navigate, port, var.get())
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
                              user32.GetWindowLongW(ctypes.c_void_p(FL["h"]), GWL_EXSTYLE) | WS_EX_LAYERED | WS_EX_TOOLWINDOW | 0x08000000)
    sprites = {s: slot_sprite(s) for s in ("", "hover", "down")}
    rect = game_rect() or (0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))
    S["bx"] = int(saved.get("bx", rect[2] - 150))  # top-left of the 64x64 sprite; the slot itself is 14 px inside
    S["by"] = int(saved.get("by", rect[1] + 80))
    S["rel"], S["brel"], S["g"], S["hid"] = saved.get("rel"), saved.get("brel"), game_rect(), False
    if S["g"] and S["brel"]:  # the minimized-button spot follows the game window as well
        S["bx"] = round(S["g"][0] + S["brel"][0] * (S["g"][2] - S["g"][0]))
        S["by"] = round(S["g"][1] + S["brel"][1] * (S["g"][3] - S["g"][1]))
    if S["g"] and not S["rel"]:
        S["rel"] = to_rel(S["g"], S["x"], S["y"], S["w"], S["h"])
    if S["g"] and not S["brel"]:
        S["brel"] = to_rel(S["g"], S["bx"], S["by"], 64, 64)[:2]
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
        g = game_rect()
        extra = {}
        if g:
            S["rel"] = to_rel(g, S["x"], S["y"], S["w"], S["h"])
            S["brel"] = to_rel(g, S["bx"], S["by"], 64, 64)[:2]
            S["g"] = g
            extra = {"rel": S["rel"], "brel": S["brel"]}
        save_state(x=S["x"], y=S["y"], w=S["w"], h=S["h"], ghost=S["ghost"], bx=S["bx"], by=S["by"], **extra)

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
        bw, bh = max(60, gx - 4 - lw), 18
        bx, by = S["x"] - EDGE + lw, S["y"] - TOP + 14
        bar.geometry(f"{bw}x{bh}+{bx}+{by}")
        # Tk applies geometry lazily and sometimes not at all for a borderless window after the game was resized:
        # put the window where it belongs with the Win32 call as well, and re-check this on every tick.
        bar.update_idletasks()
        bh_ = user32.GetParent(bar.winfo_id()) or bar.winfo_id()
        user32.SetWindowPos(ctypes.c_void_p(bh_), wintypes.HWND(HWND_TOPMOST), bx, by, bw, bh, 0x10)  # NOACTIVATE
        S["bar"] = (bx, by, bw, bh, bh_)

    def bar_ok() -> bool:
        b = S.get("bar")
        if not b:
            return True
        r = wintypes.RECT()
        user32.GetWindowRect(ctypes.c_void_p(b[4]), ctypes.byref(r))
        return (r.left, r.top, r.right - r.left, r.bottom - r.top) == b[:4]

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
            S["x"], S["y"] = _off_strip(e.x_root - drag["dx"] + EDGE, e.y_root - drag["dy"] + TOP, game_rect())  # never over the strip
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
                found = PAGE["found"] if port else None
                if found and found[1].startswith(("http://", "https://")):
                    save_state(last_page=found[1])  # closed with X: open this page again next time
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

    def frame_ok() -> bool:
        r = wintypes.RECT()
        user32.GetWindowRect(ctypes.c_void_p(top_hwnd), ctypes.byref(r))
        fw, fh = dims()
        return (r.left, r.top, r.right - r.left, r.bottom - r.top) == (S["x"] - EDGE, S["y"] - TOP, fw, fh)

    def tick():
        """Never let one failed round stop the loop: the frame must keep following the browser."""
        try:
            _tick()
        except tk.TclError:
            raise  # window destroyed: end
        except Exception as exc:  # noqa: BLE001
            try:
                with open(config.HOME / "overlay.log", "a", encoding="utf-8") as f:
                    f.write(f"tick error: {exc!r}\n")
            except OSError:
                pass
            root.after(500, tick)

    def _tick():
        touch_alive()  # tells the always-on WAC button (chat_fake) that the browser window is up
        if not user32.IsWindow(wintypes.HWND(hwnd)):
            persist()
            root.destroy()
            return
        if game_minimized():  # integrated look: nothing floats over the desktop while the game is minimized
            if not S["hid"]:
                S["hid"] = True
                user32.ShowWindow(wintypes.HWND(hwnd), 0)
                root.withdraw()
                bar.withdraw()
                fl.withdraw()
            root.after(400, tick)
            return
        if S["hid"]:
            S["hid"] = False
            set_min(S["min"])
        g = game_rect()
        if g and g != S["g"] and not drag and not fdrag:  # game window moved or resized: keep the same spot, scale with it
            if S["rel"]:
                S["x"], S["y"], S["w"], S["h"] = from_rel(g, S["rel"])
            if S["brel"]:
                S["bx"] = round(g[0] + S["brel"][0] * (g[2] - g[0]))
                S["by"] = round(g[1] + S["brel"][1] * (g[3] - g[1]))
            S["g"] = g
            if S["min"]:
                fl.geometry(f"64x64+{S['bx']}+{S['by']}")
                fl_draw()
            else:
                layout()
        if not S["min"]:
            ghost = S["ghost"]
            pin(hwnd, S["x"], S["y"], S["w"], S["h"], 35 if ghost else opacity, click_through or ghost)
            keep_page_above_game(hwnd)
            user32.SetWindowPos(ctypes.c_void_p(top_hwnd), wintypes.HWND(HWND_TOPMOST), 0, 0, 0, 0, 0x13)
            if ghost:  # ghost mode is click-through: a lone address bar floating over the game would only be a stray dark box
                if bar.state() != "withdrawn":
                    bar.withdraw()
            else:
                if bar.state() == "withdrawn":
                    bar.deiconify()
                    place_bar()
            bar.attributes("-topmost", True)
            bar.lift()
            if not frame_ok():  # frame lost its place (or its picture): redo the whole layout
                layout()
            if not ghost and not bar_ok():  # the bar drifted away from the frame: put it back
                place_bar()
            n = cache.get("n", 0) + 1
            cache["n"] = n
            if port and n % 4 == 0 and root.focus_get() is not entry:  # keep the address bar in sync with the page
                found = PAGE["found"]
                if found and found[1] and found[1] != var.get() and not found[1].startswith("chrome-error"):
                    var.set(found[1])
                if found and found[1].startswith(("http://", "https://")) and found[1] != load_state().get("last_page"):
                    save_state(last_page=found[1])  # the page to come back to when the browser is opened again
        else:
            user32.SetWindowPos(ctypes.c_void_p(FL["h"]), wintypes.HWND(HWND_TOPMOST), 0, 0, 0, 0, 0x53)
        root.after(250, tick)

    tick()
    root.mainloop()


def play(url: str, size: str | None = None) -> str:
    """Called by the bridge for [[play URL]] / "/browser": start the overlay in the background ("" = search engine),
    or close it for ``off``. Returns "" when it started, else a short reason (also written to overlay.log)."""
    if url == "off":
        _kill_profile_browsers(config.HOME / "overlay-profile")
        return ""
    import sys
    args = [sys.executable, "-m", "wowclaude", "overlay"] + ([url] if url else []) + (["--size", size] if size else [])
    config.HOME.mkdir(parents=True, exist_ok=True)
    log = open(config.HOME / "overlay.log", "a", encoding="utf-8")  # a failing overlay leaves a trace here
    logfile = config.HOME / "overlay.log"
    start = logfile.stat().st_size  # byte offset: only what the new overlay writes counts
    proc = subprocess.Popen(args, creationflags=CREATE_NO_WINDOW, stdout=log, stderr=log)
    for _ in range(80):  # return as soon as the overlay reports it runs; one that cannot start ends within a moment
        time.sleep(0.1)
        if proc.poll() is not None:
            break
        try:
            with open(logfile, "rb") as fh:
                fh.seek(start)
                if b"Overlay running" in fh.read():
                    return ""
        except OSError:
            pass
    if proc.poll() is not None:
        log.flush()
        try:
            tail = (config.HOME / "overlay.log").read_text(encoding="utf-8", errors="replace").strip().splitlines()[-1]
        except (OSError, IndexError):
            tail = "the browser window did not start"
        return tail[:160]
    return ""


