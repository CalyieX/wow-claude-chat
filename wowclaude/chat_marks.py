"""Find the two corner marks the addon puts on the chat tab, and paint the chat text for the overlay.

The addon draws a magenta square in the top-left and a cyan square in the bottom-right corner of the tab.
A screenshot of the game shows where the tab is; the overlay then paints the answers over that rectangle.
Pure Pillow, no game access: it works on any image.
"""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

TOP_LEFT = (255, 0, 255)
BOTTOM_RIGHT = (0, 255, 255)
TOLERANCE = 40
MIN_MARK = 3
MAX_MARK = 24


def _mask(img: Image.Image, colour: tuple[int, int, int]) -> Image.Image:
    r, g, b = img.convert("RGB").split()
    out = None
    for chan, want in zip((r, g, b), colour):
        m = chan.point(lambda v, w=want: 255 if abs(v - w) <= TOLERANCE else 0)
        out = m if out is None else Image.composite(out, Image.new("L", m.size, 0), m)
    return out


def _box(img: Image.Image, colour) -> tuple[int, int, int, int] | None:
    box = _mask(img, colour).getbbox()
    if box is None:
        return None
    w, h = box[2] - box[0], box[3] - box[1]
    if not (MIN_MARK <= w <= MAX_MARK and MIN_MARK <= h <= MAX_MARK):
        return None  # a big magenta/cyan area is scenery, not our mark
    return box


def find_frame(img: Image.Image) -> tuple[int, int, int, int] | None:
    """(left, top, right, bottom) between the two marks inside ``img``, or None when a mark is missing."""
    a, b = _box(img, TOP_LEFT), _box(img, BOTTOM_RIGHT)
    if a is None or b is None:
        return None
    left, top, right, bottom = a[0], a[1], b[2], b[3]
    if right - left < 40 or bottom - top < 20:
        return None
    return left, top, right, bottom


def wrap(text: str, width_px: int, font) -> list[str]:
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


_FONT = None


def default_font():
    global _FONT
    if _FONT is None:
        _FONT = ImageFont.load_default(size=14)
    return _FONT


COLOURS = {"user": (255, 255, 153), "ai": (153, 217, 255), "sys": (170, 170, 170), "think": (200, 200, 120)}


def render(entries: list[tuple[str, str]], size: tuple[int, int], font=None, scroll: int = 0) -> Image.Image:
    """Dark box ``size`` with the newest entries at the bottom. ``entries`` = [(kind, text)]; ``scroll`` = lines up."""
    font = font or default_font()
    img = Image.new("RGB", size, (12, 12, 16))
    draw = ImageDraw.Draw(img)
    lh = int(font.size * 1.3) if hasattr(font, "size") else 16
    rows: list[tuple[str, str]] = []
    for kind, text in entries:
        rows += [(kind, ln) for ln in wrap(text, size[0] - 12, font)]
    fit = max(1, (size[1] - 8) // lh)
    end = len(rows) - max(0, scroll)
    for i, (kind, ln) in enumerate(rows[max(0, end - fit):max(0, end)]):
        draw.text((6, 4 + i * lh), ln, fill=COLOURS.get(kind, (255, 255, 255)), font=font)
    return img
