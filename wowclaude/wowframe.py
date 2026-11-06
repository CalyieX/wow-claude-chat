"""The WoW frame of the browser overlay (same textures, same title strip, red X) around a plain Tk window.

Used by the panel, the harness editor and the CLI window, so every window over the game looks alike.
Drag the title strip to move it, the corner to resize it, X closes it. Put your widgets into ``win.inner``.
"""
from __future__ import annotations

from typing import Callable

DARK = "#15130e"  # the window colour: title strip, margins and content all use it (no black bands)
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
THUMB = "red"  # "red" (like the frame buttons) or "gold" (WoW yellow)


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
        r.title("WoW AI - " + title)  # a real window title: tools (screen readers, automation) can find the window
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
        frame = overlay.compose(self.w, self.h, overlay.TOP, names=("close",), label=self.title, tile_bg=False)
        # outside the rounded border: a key colour the window treats as see-through (no black corners); inside: one window colour
        base = Image.new("RGB", (self.w, self.h), overlay.KEY_RGB)
        inset = overlay.INSET
        base.paste((21, 19, 14), (inset, inset, self.w - inset, self.h - inset))  # window colour, also under the title strip
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


def scroll_image(w: int, h: int, first: float, last: float):
    """The whole scroll bar as one image (drawn 4x big, scaled down: smooth, exactly symmetric, no corners): a pill-shaped
    dark track with a thin transparent-yellow edge, round red buttons with a gold arrow at both ends, a gold thumb with
    round ends, a 3D shading and a reflection. Everything is centred on the same axis."""
    from PIL import Image, ImageDraw
    S = 4
    W2, H2 = w * S, h * S
    im = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, W2 - 1, H2 - 1), radius=W2 // 2, fill=(12, 11, 9, 255), outline=(97, 80, 9, 255), width=S)  # gold at ~35 %
    bd = (w - 4) * S  # button diameter, 2 px of track around it
    for cy in (w * S // 2, H2 - w * S // 2):
        x0, y0 = (W2 - bd) // 2, cy - bd // 2
        d.ellipse((x0, y0, x0 + bd - 1, y0 + bd - 1), fill=(82, 2, 0, 255), outline=(201, 162, 39, 255), width=S // 2)
        d.ellipse((x0 + S, y0 + S, x0 + bd - 1 - S, y0 + bd // 2), outline=None, fill=(112, 4, 0, 255))  # upper sheen
    s = bd // 5
    cx = W2 // 2
    cy1, cy2 = w * S // 2, H2 - w * S // 2
    d.polygon([(cx - s, cy1 + s // 2), (cx + s, cy1 + s // 2), (cx, cy1 - s // 2 - 1)], fill=(255, 209, 0, 255))
    d.polygon([(cx - s, cy2 - s // 2), (cx + s, cy2 - s // 2), (cx, cy2 + s // 2 + 1)], fill=(255, 209, 0, 255))
    t0, t1 = w, h - w
    if last - first < 0.999 and t1 - t0 > 8:  # thumb only when there is something to scroll
        y0 = t0 + round(first * (t1 - t0))
        y1 = max(y0 + w + 4, t0 + round(last * (t1 - t0)))
        y1 = min(y1, t1)
        y0 = max(t0, min(y0, y1 - (w + 4)))
        tw = (w - 6) * S
        x0 = (W2 - tw) // 2
        th = (y1 - y0) * S
        thumb = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
        px = thumb.load()
        for x in range(tw):  # cylinder shading across the width: dark gold at the edges, bright gold in the middle
            u = x / (tw - 1) * 2 - 1
            k = (1 - u * u) ** 0.5
            if THUMB == "gold":
                col = (int(110 + 145 * k), int(78 + 131 * k), int(0 + 10 * k), 255)
            else:  # red, shaded like the frame's red buttons: dark at the edges, bright in the middle
                col = (int(40 + 100 * k), int(0 + 2 * k), 0, 255)  # the frame buttons' red: (82,2,0) .. (140,0,0)
            for y in range(th):
                px[x, y] = col
        td = ImageDraw.Draw(thumb)
        hx = int(tw * 0.3)
        td.line((hx, tw // 2, hx, th - tw // 2), fill=(255, 245, 190, 255) if THUMB == "gold" else (205, 70, 55, 255), width=max(2, S))  # reflection
        mask = Image.new("L", (tw, th), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, tw - 1, th - 1), radius=tw // 2, fill=255)
        edge = Image.new("L", (tw, th), 0)
        ImageDraw.Draw(edge).rounded_rectangle((0, 0, tw - 1, th - 1), radius=tw // 2, outline=255, width=S)
        im.paste(thumb, (x0, y0 * S), mask)
        im.paste(Image.new("RGBA", (tw, th), (58, 40, 0, 255) if THUMB == "gold" else (22, 0, 0, 255)), (x0, y0 * S), edge)
    return im.resize((w, h), Image.LANCZOS)


class WowScrollbar:
    """A scroll bar in the frame's style (see scroll_image).

    Use like tk.Scrollbar: ``sb = WowScrollbar(parent, text.yview)``, ``text.configure(yscrollcommand=sb.set)``, ``sb.pack(...)``.
    """
    WIDTH = 16

    def __new__(cls, parent, command):
        import tkinter as tk
        from PIL import ImageTk
        W = cls.WIDTH
        c = tk.Canvas(parent, width=W, bg=DARK, highlightthickness=0, bd=0)
        state = {"first": 0.0, "last": 1.0, "drag": None}

        def track() -> tuple[int, int]:
            return W, max(W + 10, c.winfo_height() - W)

        def draw(*_a) -> None:
            h = max(c.winfo_height(), 2 * W + 10)
            c.delete("all")
            c.photo = ImageTk.PhotoImage(scroll_image(W, h, state["first"], state["last"]))
            c.create_image(0, 0, image=c.photo, anchor="nw")

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
