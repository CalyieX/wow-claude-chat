"""Find the three corner marks the addon puts on the chat tab, and paint the chat text for the overlay.

The addon draws a magenta square on the tab's top-left, a cyan one on its top-right and a yellow one on its
bottom-left corner. A screenshot of the game shows where the tab is; the overlay then paints the answers over
that rectangle. Pure Pillow, no game access: it works on any image.
"""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFilter, ImageFont

TOP_LEFT = (255, 0, 255)
TOP_RIGHT = (0, 255, 255)
YELLOW = (255, 255, 0)
TOLERANCE = 40
MIN_MARK = 3
MAX_MARK = 48  # 4 UI units: up to ~12 px per unit on very high display scales
MIN_FONT, MAX_FONT = 10, 96


def _mask(img: Image.Image, colour: tuple[int, int, int]) -> Image.Image:
    r, g, b = img.convert("RGB").split()
    out = None
    for chan, want in zip((r, g, b), colour):
        m = chan.point(lambda v, w=want: 255 if abs(v - w) <= TOLERANCE else 0)
        out = m if out is None else Image.composite(out, Image.new("L", m.size, 0), m)
    return out


def _box(img: Image.Image, colour, region=None) -> tuple[int, int, int, int] | None:
    """Bounding box of the one solid square of ``colour`` (stray pixels of the same colour are ignored).

    ``region`` = (l, t, r, b) limits the search; the returned box is in full-image coordinates.
    """
    ox, oy = (region[0], region[1]) if region else (0, 0)
    sub = img.crop(region) if region else img
    solid = _mask(sub, colour).filter(ImageFilter.MinFilter(MIN_MARK))  # only blocks >= MIN_MARK wide survive
    box = solid.getbbox()
    if box is None:
        return None
    pad = MIN_MARK // 2
    box = (box[0] - pad + ox, box[1] - pad + oy, box[2] + pad + ox, box[3] + pad + oy)
    w, h = box[2] - box[0], box[3] - box[1]
    if not (MIN_MARK <= w <= MAX_MARK and MIN_MARK <= h <= MAX_MARK):
        return None  # a big magenta/cyan area is scenery, not our mark
    return box


def find_marks(img: Image.Image) -> tuple[tuple[int, int, int, int], int] | None:
    """((left, top, right, bottom), font_px) of the tab, or None.

    Top-left magenta, top-right cyan and bottom-left yellow square. The yellow one sits ``font size`` pixels to the
    right of the tab's left edge: that is how the addon tells the overlay the tab's text size (so the size menu of
    the real tab keeps working). Magenta is searched everywhere; the others only along its row and column, so
    yellow or cyan scenery elsewhere (gold frames, water) cannot confuse it.
    """
    a = _box(img, TOP_LEFT)
    if a is None:
        return None
    w, h = img.size
    row = (a[2], max(0, a[1] - 4), w, min(h, a[3] + 4))
    col = (max(0, a[0] - 4), a[3], min(w, a[0] + MAX_FONT + MAX_MARK), h)
    c = _box(img, TOP_RIGHT, row) if row[2] > row[0] else None
    y = _box(img, YELLOW, col) if col[3] > col[1] else None
    if c is None or y is None:
        return None
    left, top, right, bottom = a[0], a[1], c[2], y[3]
    if right - left < 40 or bottom - top < 20:
        return None
    font = max(MIN_FONT, min(MAX_FONT, y[0] - a[0]))
    return (left, top, right, bottom), font


def find_frame(img: Image.Image) -> tuple[int, int, int, int] | None:
    found = find_marks(img)
    return found[0] if found else None


_WRAPS: dict = {}


def wrap(text: str, width_px: int, font) -> list[str]:
    """Line breaks for ``text`` (remembered: the same text at the same width is wrapped once, which keeps scrolling smooth)."""
    key = (text, width_px, id(font))
    hit = _WRAPS.get(key)
    if hit is None:
        if len(_WRAPS) > 2000:
            _WRAPS.clear()
        hit = _WRAPS[key] = _wrap(text, width_px, font)
    return hit


def _wrap(text: str, width_px: int, font) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split(" "):
            trial = (cur + " " + word).strip()
            if font.getlength(trial) <= width_px or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


_FONTS: dict[int, object] = {}


def default_font(size: int = 17):
    """The game's own chat font where it exists (Arial Narrow on German clients), else Pillow's default."""
    size = max(10, min(96, int(size)))
    if size not in _FONTS:
        for path in (r"C:\Windows\Fonts\ARIALN.TTF", r"C:\Windows\Fonts\arial.ttf"):
            try:
                _FONTS[size] = ImageFont.truetype(path, size)
                break
            except OSError:
                continue
        else:
            _FONTS[size] = ImageFont.load_default(size=size)
    return _FONTS[size]


COLOURS = {"user": (255, 255, 153), "ai": (153, 217, 255), "sys": (170, 170, 170), "think": (200, 200, 120)}


def row_metrics(entries: list[tuple[str, str]], size: tuple[int, int], font_size: int = 17, bar_w: int = 0,
                font=None) -> tuple[int, int]:
    """(wrapped rows in all, rows that fit on screen) for a box of ``size``; ``bar_w`` px on the right stay free."""
    font = font or default_font(font_size)
    lh = int(font.size * 1.3) if hasattr(font, "size") else 16
    n = sum(len(wrap(text, size[0] - 12 - bar_w, font)) for _kind, text in entries)
    return n, max(1, (size[1] - 8) // lh)


def render(entries: list[tuple[str, str]], size: tuple[int, int], font=None, scroll: int = 0,
           bg: tuple = (12, 12, 16, 255), shadow: bool = False, font_size: int = 17, bar_w: int = 0) -> Image.Image:
    """Dark box ``size`` with the newest entries at the bottom. ``entries`` = [(kind, text)]; ``scroll`` = lines up.
    With ``bar_w`` > 0 a scroll bar in the game's style is drawn on the right when there is more text than fits."""
    font = font or default_font(font_size)
    img = Image.new("RGBA", size, bg)
    draw = ImageDraw.Draw(img, "RGBA")
    lh = int(font.size * 1.3) if hasattr(font, "size") else 16
    rows: list[tuple[str, str]] = []
    for kind, text in entries:
        rows += [(kind, ln) for ln in wrap(text, size[0] - 12 - bar_w, font)]
    fit = max(1, (size[1] - 8) // lh)
    scroll = max(0, min(scroll, max(0, len(rows) - fit)))
    end = len(rows) - scroll
    shown = rows[max(0, end - fit):max(0, end)]
    top = size[1] - 4 - len(shown) * lh  # newest line at the bottom, like a chat
    for i, (kind, ln) in enumerate(shown):
        if shadow:
            draw.text((7, top + i * lh + 1), ln, fill=(0, 0, 0, 255), font=font)
        draw.text((6, top + i * lh), ln, fill=COLOURS.get(kind, (255, 255, 255)) + (255,), font=font)
    return img
