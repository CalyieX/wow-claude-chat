"""Fallback artwork for the WoW-style window frame, drawn in code. The shipped art/*.png (Blizzard interface textures, see README) takes precedence.

The frame, buttons and the action-bar slot look like the game's own windows, but every pixel here is generated.
If you want the exact in-game look, drop the original textures (same file names) into ``~/.wowclaude/art/``; they
win over the generated ones. They are never part of this repository.
"""
from __future__ import annotations

from PIL import Image, ImageDraw

NAMES = (
    "UI-DialogBox-Background.png", "UI-DialogBox-Border.png", "UI-Panel-MinimizeButton-Up.png",
    "UI-Panel-MinimizeButton-Down.png", "UI-Panel-MinimizeButton-Highlight.png", "INV_Misc_Map_01.png",
    "UI-Quickslot.png", "UI-Quickslot2.png", "UI-Quickslot-Depress.png", "ButtonHilight-Square.png",
    "UI-ChatIM-SizeGrabber-Up.png",
)

LINE = ((190, 190, 190, 255), (120, 118, 112, 255), (52, 50, 46, 255))  # lit edge, body, shadow


def _background() -> Image.Image:
    im = Image.new("RGBA", (64, 64), (22, 18, 14, 238))
    px = im.load()
    for y in range(64):
        for x in range(64):
            n = ((x * 7 + y * 13) % 5) - 2  # faint grain, tiles seamlessly because 64 is a multiple of its period
            r, g, b, a = px[x, y]
            px[x, y] = (max(0, r + n), max(0, g + n), max(0, b + n), a)
    return im


def _border() -> Image.Image:
    """Eight 32x32 pieces: left, right, top, bottom (stored rotated), then the four corners."""
    sheet = Image.new("RGBA", (256, 32), (0, 0, 0, 0))

    def vline(d: ImageDraw.ImageDraw, ox: int, x: int, y0: int, y1: int) -> None:
        for k, col in enumerate(LINE):
            d.line([(ox + x + k, y0), (ox + x + k, y1)], fill=col)

    def hline(d: ImageDraw.ImageDraw, ox: int, y: int, x0: int, x1: int) -> None:
        for k, col in enumerate(LINE):
            d.line([(ox + x0, y + k), (ox + x1, y + k)], fill=col)

    d = ImageDraw.Draw(sheet)
    vline(d, 0, 6, 0, 31)    # left
    vline(d, 32, 23, 0, 31)  # right
    vline(d, 64, 6, 0, 31)   # top (transposed when used)
    vline(d, 96, 23, 0, 31)  # bottom (transposed when used)
    hline(d, 128, 6, 6, 31); vline(d, 128, 6, 6, 31)    # top-left
    hline(d, 160, 6, 0, 25); vline(d, 160, 23, 6, 31)   # top-right
    hline(d, 192, 23, 6, 31); vline(d, 192, 6, 0, 25)   # bottom-left
    hline(d, 224, 23, 0, 25); vline(d, 224, 23, 0, 25)  # bottom-right
    for ox, cx, cy in ((128, 7, 7), (160, 24, 7), (192, 7, 24), (224, 24, 24)):  # a small rivet in every corner
        d.ellipse((ox + cx - 2, cy - 2, ox + cx + 2, cy + 2), fill=(214, 178, 70, 255), outline=(60, 44, 10, 255))
    return sheet


def _button(state: str) -> Image.Image:
    """The red round-cornered button inside the 32x32 close-button texture (19x18 at 6,7)."""
    im = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    body = {"up": (176, 32, 22, 255), "down": (118, 20, 14, 255)}[state]
    d.rounded_rectangle((6, 7, 24, 24), radius=3, fill=body, outline=(40, 8, 6, 255))
    d.line([(7, 8), (23, 8)], fill=(235, 120, 100, 255))  # light on the upper edge
    gold = (242, 194, 48, 255)
    d.line([(10, 11), (20, 21)], fill=gold, width=2)
    d.line([(20, 11), (10, 21)], fill=gold, width=2)
    return im


def _highlight() -> Image.Image:
    im = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle((6, 7, 24, 24), radius=3, fill=(90, 80, 40, 255))
    return im


def _map_icon() -> Image.Image:
    im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle((4, 4, 59, 59), fill=(196, 164, 104, 255))
    for i, col in enumerate(((120, 90, 50, 255), (150, 116, 68, 255))):  # worn edge
        d.rectangle((4 + i, 4 + i, 59 - i, 59 - i), outline=col)
    d.line([(14, 40), (26, 30), (36, 38), (50, 20)], fill=(110, 80, 44, 255), width=2)  # a route
    red = (200, 36, 28, 255)
    d.line([(38, 14), (52, 28)], fill=red, width=5)
    d.line([(52, 14), (38, 28)], fill=red, width=5)
    return im


def _slot(kind: str) -> Image.Image:
    im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if kind == "bg":
        d.rectangle((14, 14, 49, 49), fill=(18, 18, 20, 255))
    elif kind == "frame":
        d.rectangle((12, 12, 51, 51), outline=(150, 142, 120, 255))
        d.rectangle((13, 13, 50, 50), outline=(70, 64, 52, 255))
        d.rectangle((11, 11, 52, 52), outline=(30, 28, 24, 255))
    else:  # pressed
        d.rectangle((14, 14, 49, 49), fill=(0, 0, 0, 110))
    return im


def _hilight() -> Image.Image:
    return Image.new("RGBA", (64, 64), (84, 84, 62, 255))


def _grabber() -> Image.Image:
    im = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for off in (4, 8, 12):
        d.line([(15, off), (off, 15)], fill=(214, 178, 70, 255))
        d.line([(15, off + 1), (off + 1, 15)], fill=(52, 44, 20, 255))
    return im


_MAKERS = {
    "UI-DialogBox-Background.png": _background,
    "UI-DialogBox-Border.png": _border,
    "UI-Panel-MinimizeButton-Up.png": lambda: _button("up"),
    "UI-Panel-MinimizeButton-Down.png": lambda: _button("down"),
    "UI-Panel-MinimizeButton-Highlight.png": _highlight,
    "INV_Misc_Map_01.png": _map_icon,
    "UI-Quickslot.png": lambda: _slot("bg"),
    "UI-Quickslot2.png": lambda: _slot("frame"),
    "UI-Quickslot-Depress.png": lambda: _slot("down"),
    "ButtonHilight-Square.png": _hilight,
    "UI-ChatIM-SizeGrabber-Up.png": _grabber,
}


def generate(name: str) -> Image.Image:
    return _MAKERS[name]()
