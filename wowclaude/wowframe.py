"""The WoW frame of the browser overlay (same textures, same title strip, red X) around a plain Tk window.

Used by the panel, the harness editor and the CLI window, so every window over the game looks alike.
Drag the title strip to move it, the corner to resize it, X closes it. Put your widgets into ``win.inner``.
"""
from __future__ import annotations

from typing import Callable

DARK = "#0e0d09"
STATE = None  # ~/.wowclaude/windows.json: position and size of every window, as fractions of the game window


def _state_file():
    from . import config
    return config.HOME / "windows.json"


def _load(key: str):
    import json
    try:
        return json.loads(_state_file().read_text(encoding="utf-8")).get(key)
    except (OSError, ValueError):
        return None


def _save(key: str, rel) -> None:
    import json
    f = _state_file()
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data[key] = rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data), encoding="utf-8")
MIN_W, MIN_H = 320, 200


class FramedWindow:
    def __init__(self, title: str, w: int = 760, h: int = 520, x: int | None = None, y: int | None = None,
                 on_close: Callable[[], None] | None = None, key: str = "") -> None:
        import tkinter as tk
        from . import overlay
        self.key = key
        g = overlay.game_rect()
        saved = _load(key) if key else None
        if saved and g:  # like the browser window: back where it was, relative to the game window
            sx, sy, sw, sh = overlay.from_rel(g, saved)
            if overlay._on_screen(sx, sy, sw, sh):
                x, y, w, h = sx, sy, max(MIN_W, sw), max(MIN_H, sh)
        if x is None or y is None:
            x, y = (g[2] - w - 30, g[1] + 80) if g else (120, 90)
        self.title, self.w, self.h, self.on_close = title, w, h, on_close
        self.root = tk.Tk()
        r = self.root
        r.overrideredirect(True)
        r.attributes("-topmost", True)
        from . import overlay as _ov
        r.configure(bg=_ov.KEY)
        r.attributes("-transparentcolor", _ov.KEY)
        r.geometry(f"{w}x{h}+{x}+{y}")
        self.canvas = tk.Canvas(r, width=w, height=h, bg=_ov.KEY, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=DARK)
        self._win = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self._item = None
        self._photo = None
        self._pending = None
        self._drag: dict = {}
        self.canvas.bind("<Configure>", self._configure)
        self.canvas.bind("<Button-1>", self._down)
        self.canvas.bind("<B1-Motion>", self._move)
        self.canvas.bind("<ButtonRelease-1>", lambda e: (self.remember(), self._drag.clear()))
        r.after(50, self.focus)
        self.rel = None  # position and size as fractions of the game window: the window follows the game like the browser does
        self._game = None
        r.after(400, self._follow)

    def focus(self) -> None:
        try:
            self.root.focus_force()
        except Exception:  # noqa: BLE001
            pass

    def set_title(self, title: str) -> None:
        if title != self.title:
            self.title = title
            self._draw()

    def _follow(self) -> None:
        """The game window was moved or resized: move and scale this window with it (same fractions as before)."""
        try:
            from . import overlay
            g = overlay.game_rect()
            if self.rel is None:
                if g:
                    self.rel = overlay.to_rel(g, self.root.winfo_x(), self.root.winfo_y(), self.w, self.h)
                    self._game = g
            elif g and g != self._game and not self._drag:
                self._game = g
                x, y, w, h = overlay.from_rel(g, self.rel)
                self.root.geometry(f"{max(MIN_W, w)}x{max(MIN_H, h)}+{x}+{y}")
        except Exception:  # noqa: BLE001 - following is a convenience
            pass
        try:
            self.root.after(400, self._follow)
        except Exception:  # noqa: BLE001 - window closed
            pass

    def remember(self) -> None:
        """Position and size, relative to the game window (so it follows when the game is moved or resized)."""
        if not self.key:
            return
        from . import overlay
        g = overlay.game_rect()
        if g:
            try:
                self.rel = overlay.to_rel(g, self.root.winfo_x(), self.root.winfo_y(), self.w, self.h)
                self._game = g
                _save(self.key, self.rel)
            except Exception:  # noqa: BLE001 - remembering is a convenience
                pass

    def close(self) -> None:
        self.remember()
        if self.on_close:
            try:
                self.on_close()
            except Exception:  # noqa: BLE001
                pass
        self.root.destroy()

    # -- drawing -------------------------------------------------------------------------------------------------
    def _configure(self, e) -> None:
        self.w, self.h = e.width, e.height
        if self._pending:
            self.root.after_cancel(self._pending)
        self._pending = self.root.after(40, self._draw)  # one redraw after a resize, not one per pixel

    def _draw(self) -> None:
        from PIL import Image, ImageTk
        from . import overlay
        self._pending = None
        frame = overlay.compose(self.w, self.h, overlay.TOP, names=("close",), label=self.title)
        # outside the rounded border: a key colour the window treats as see-through (no black corners); inside: the
        # dialog's own dark texture like the browser frame, not flat black
        base = Image.new("RGB", (self.w, self.h), overlay.KEY_RGB)
        tile = overlay._art("UI-DialogBox-Background.png").convert("RGB").resize((32, 32))
        inset = overlay.INSET
        for yy in range(inset, self.h - inset, 32):
            for xx in range(inset, self.w - inset, 32):
                base.paste(tile.crop((0, 0, min(32, self.w - inset - xx), min(32, self.h - inset - yy))), (xx, yy))
        alpha = frame.getchannel("A").point(lambda v: 255 if v >= 110 else 0)  # hard edge: no key-colour fringe
        base.paste(frame.convert("RGB"), (0, 0), alpha)
        self._photo = ImageTk.PhotoImage(base)
        if self._item is None:
            self._item = self.canvas.create_image(0, 0, image=self._photo, anchor="nw")
            self.canvas.tag_lower(self._item)
        else:
            self.canvas.itemconfigure(self._item, image=self._photo)
        inset = overlay.INSET + 10
        self.canvas.coords(self._win, inset, overlay.TOP)
        self.canvas.itemconfigure(self._win, width=max(10, self.w - 2 * inset), height=max(10, self.h - overlay.TOP - inset))

    # -- mouse ---------------------------------------------------------------------------------------------------
    def _down(self, e) -> None:
        from . import overlay
        bx, by, bw, bh = overlay.buttons(self.w)["close"]
        if bx <= e.x <= bx + bw and by <= e.y <= by + bh:
            self.close()
        elif e.x > self.w - 28 and e.y > self.h - 28:
            self._drag = {"mode": "size", "x": e.x_root, "y": e.y_root, "w": self.w, "h": self.h}
        elif e.y < overlay.TOP:
            self._drag = {"mode": "move", "x": e.x_root - self.root.winfo_x(), "y": e.y_root - self.root.winfo_y()}
        else:
            self._drag = {}
        self.focus()

    def _move(self, e) -> None:
        d = self._drag
        if d.get("mode") == "move":
            self.root.geometry(f"+{e.x_root - d['x']}+{e.y_root - d['y']}")
        elif d.get("mode") == "size":
            nw, nh = max(MIN_W, d["w"] + e.x_root - d["x"]), max(MIN_H, d["h"] + e.y_root - d["y"])
            self.root.geometry(f"{nw}x{nh}")


_ART: dict = {}


def _scroll_art(w: int):
    """Scroll bar parts in the frame's own colours: the thumb is a rounded, shaded steel rod like the frame rim, the arrow buttons are the frame's red buttons with a gold arrow. None if the art is missing."""
    if w in _ART:
        return _ART[w]
    _ART[w] = None
    try:
        from PIL import Image, ImageChops, ImageDraw, ImageTk
        from . import overlay
        S = 4  # draw big, scale down: smooth round ends

        def thumb(h: int):
            h = max(h, w * 2 + 2)
            W2, H2 = w * S, h * S
            tex = Image.new("RGBA", (W2, H2), (150, 148, 150, 255))  # the frame border is steel grey: same metal, shaded below
            # 3D: cylinder shading across the width, a bright reflection line left of centre, darker rim
            shade = Image.new("L", (W2, H2))
            sd = ImageDraw.Draw(shade)
            for x in range(W2):
                u = x / (W2 - 1) * 2 - 1  # -1 .. 1
                v = 0.62 + 0.38 * (1 - u * u) ** 0.5 - 0.18 * max(0.0, u)  # light from the left
                sd.line((x, 0, x, H2), fill=max(0, min(255, int(v * 255))))
            lit = ImageChops.multiply(tex.convert("RGB"), Image.merge("RGB", (shade, shade, shade)))
            hl = ImageDraw.Draw(lit)
            hx = int(W2 * 0.3)
            hl.line((hx, W2 // 2, hx, H2 - W2 // 2), fill=(235, 235, 240), width=max(2, S))  # reflection
            mask = Image.new("L", (W2, H2), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, W2 - 1, H2 - 1), radius=W2 // 2, fill=255)  # round ends
            edge = Image.new("L", (W2, H2), 0)
            ImageDraw.Draw(edge).rounded_rectangle((0, 0, W2 - 1, H2 - 1), radius=W2 // 2, outline=255, width=S)
            out = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
            out.paste(lit.convert("RGBA"), (0, 0), mask)
            out.paste(Image.new("RGBA", (W2, H2), (12, 11, 10, 255)), (0, 0), edge)  # dark outline
            return ImageTk.PhotoImage(out.resize((w, h), Image.LANCZOS))

        def button(up: bool):
            base = overlay._art("UI-Panel-MinimizeButton-Up.png").crop(overlay.CB).convert("RGBA")
            px = base.load()
            for yy in range(base.height):  # wipe the gold X, keep the red button
                for xx in range(base.width):
                    r, g, b, a = px[xx, yy]
                    if a and g > 55 and r > g:
                        px[xx, yy] = (112, 22, 16, a)
            big = base.resize((base.width * 4, base.height * 4), Image.LANCZOS)
            d = ImageDraw.Draw(big)
            cx, cy, s = big.width // 2, big.height // 2, big.width // 5
            pts = [(cx - s, cy + s // 2), (cx + s, cy + s // 2), (cx, cy - s // 2 - 2)] if up else                 [(cx - s, cy - s // 2), (cx + s, cy - s // 2), (cx, cy + s // 2 + 2)]
            d.polygon(pts, fill=(255, 209, 0, 255))
            return ImageTk.PhotoImage(big.resize((w, round(w * base.height / base.width)), Image.LANCZOS))

        _ART[w] = {"up": button(True), "down": button(False), "thumb": thumb}
    except Exception:  # noqa: BLE001 - fall back to the drawn bar
        pass
    return _ART[w]


class WowScrollbar:
    """A scroll bar drawn like the game's: dark track, gold-edged arrow buttons, brown thumb with a light edge.

    Use like tk.Scrollbar: ``sb = WowScrollbar(parent, text.yview)``, ``text.configure(yscrollcommand=sb.set)``, ``sb.pack(...)``.
    """
    WIDTH = 14

    def __new__(cls, parent, command):
        import tkinter as tk
        c = tk.Canvas(parent, width=cls.WIDTH, bg="#120d07", highlightthickness=1, highlightbackground="#4a4846", bd=0)
        state = {"first": 0.0, "last": 1.0, "drag": None}
        W = cls.WIDTH

        def track() -> tuple[int, int]:
            return W, max(W + 10, c.winfo_height() - W)

        art = _scroll_art(W)

        def draw(*_a) -> None:
            c.delete("all")
            h = max(c.winfo_height(), 2 * W + 10)
            if art:  # the Blender-rendered parts (rounded brass thumb, red buttons with a gold arrow)
                c.create_rectangle(2, W, W - 2, h - W, fill="#0c0b09", outline="")
                c.create_image(0, 0, image=art["up"], anchor="nw")
                c.create_image(0, h - W, image=art["down"], anchor="nw")
                t0, t1 = W, max(W + 10, h - W)
                if state["last"] - state["first"] < 0.999:
                    y0 = t0 + int(state["first"] * (t1 - t0))
                    y1 = max(y0 + 2 * W, t0 + int(state["last"] * (t1 - t0)))
                    c.thumb_img = art["thumb"](y1 - y0)  # keep a reference
                    c.create_image(0, y0, image=c.thumb_img, anchor="nw")
                return
            for y, up in ((0, True), (h - W, False)):  # arrow buttons (drawn in code when the art is missing)
                c.create_rectangle(1, y + 1, W - 1, y + W - 1, fill="#3a1a10", outline="#c9a227")
                cx, cy = W // 2, y + W // 2
                pts = (cx - 4, cy + 2, cx + 4, cy + 2, cx, cy - 3) if up else (cx - 4, cy - 2, cx + 4, cy - 2, cx, cy + 3)
                c.create_polygon(*pts, fill="#ffd100", outline="")
            t0, t1 = track()
            span = t1 - t0
            y0 = t0 + int(state["first"] * span)
            y1 = max(y0 + 14, t0 + int(state["last"] * span))
            if state["last"] - state["first"] < 0.999:  # thumb only when there is something to scroll
                c.create_rectangle(2, y0, W - 2, y1, fill="#6b4a1c", outline="#e6cf8a")
                c.create_line(4, y0 + 2, W - 4, y0 + 2, fill="#a8823a")
                mid = (y0 + y1) // 2
                for dy in (-3, 0, 3):
                    c.create_line(6, mid + dy, W - 6, mid + dy, fill="#2a1a08")

        def set_(first, last) -> None:
            state["first"], state["last"] = float(first), float(last)
            draw()

        def press(e) -> None:
            h = c.winfo_height()
            if e.y < W:
                command("scroll", -1, "units")
            elif e.y > h - W:
                command("scroll", 1, "units")
            else:
                t0, t1 = track()
                y0 = t0 + state["first"] * (t1 - t0)
                y1 = t0 + state["last"] * (t1 - t0)
                if y0 <= e.y <= y1:
                    state["drag"] = (e.y, state["first"])
                else:
                    command("scroll", -1 if e.y < y0 else 1, "pages")

        def drag(e) -> None:
            if state["drag"]:
                t0, t1 = track()
                y, first = state["drag"]
                command("moveto", max(0.0, min(1.0, first + (e.y - y) / max(1, t1 - t0))))

        def release(_e) -> None:
            state["drag"] = None

        c.bind("<Configure>", draw)
        c.bind("<Button-1>", press)
        c.bind("<B1-Motion>", drag)
        c.bind("<ButtonRelease-1>", release)
        c.set = set_  # type: ignore[attr-defined]
        return c
