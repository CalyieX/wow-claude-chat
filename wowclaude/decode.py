"""Decode the colour strip that the KKMap addon draws in the top-left corner of the game window.

Layout: square cells (1 to 4 pixels, detected automatically), 128 cells per row, 3 bytes (R, G, B) per cell.
The first 8 cells are fixed calibration colours; then 4 bytes length (LE), 4 bytes checksum, then UTF-8 text
lines such as ``#msg|seq|1|text`` or ``#edit|1``.
"""
from __future__ import annotations

from dataclasses import dataclass

COLS = 128
MAX_ROWS = 40
MAGIC = ((255, 0, 255), (0, 255, 255), (255, 255, 0), (0, 0, 0),
         (255, 255, 255), (255, 0, 0), (0, 255, 0), (0, 0, 255))


@dataclass(frozen=True)
class GameState:
    message_seq: int = 0
    message: str = ""
    edit_active: bool = False
    addon_version: int = 0
    context: str = ""
    frames: tuple = ()  # (name, kind, text, centre_x, centre_y) of visible clickable frames


def _cell(px, ox: int, oy: int, i: int, cell: int) -> tuple[int, int, int]:
    x = ox + (i % COLS) * cell + cell // 2
    y = oy + (i // COLS) * cell + cell // 2
    return tuple(int(v) for v in px[x, y][:3])


def _cell_size(px, ox: int, oy: int, width: int) -> int:
    """Width in pixels of the first (magenta) calibration cell = the cell size."""
    n = 0
    while n < 8 and ox + n < width and tuple(px[ox + n, oy][:3]) == MAGIC[0]:
        n += 1
    return n


def _locate(image, search_w: int = 400, search_h: int = 400):
    px = image.convert("RGB").load()
    w, h = image.size
    for oy in range(0, max(0, min(search_h, h - 4))):
        for ox in range(0, max(0, min(search_w, w - 8))):
            if tuple(px[ox, oy]) != MAGIC[0]:
                continue
            if (ox > 0 and tuple(px[ox - 1, oy]) == MAGIC[0]) or (oy > 0 and tuple(px[ox, oy - 1]) == MAGIC[0]):
                continue
            cell = _cell_size(px, ox, oy, w)
            if cell < 1 or ox + COLS * cell > w:
                continue
            if all(_cell(px, ox, oy, i, cell) == MAGIC[i] for i in range(8)):
                return px, ox, oy, cell, w, h
    return None


def decode(image) -> GameState | None:
    """Decode the strip from a PIL image of the game window. None if no valid strip is visible."""
    found = _locate(image)
    if found is None:
        return None
    px, ox, oy, cell, w, h = found
    rows = max(0, min(MAX_ROWS, (h - oy) // cell))
    raw = bytearray()
    need = None
    for i in range(8, COLS * rows):
        raw.extend(_cell(px, ox, oy, i, cell))
        if need is None and len(raw) >= 8:  # length + checksum are in: now we know how much more to read
            length = int.from_bytes(raw[0:4], "little")
            if length <= 0 or length > COLS * rows * 3:
                return None
            need = 8 + length
        if need is not None and len(raw) >= need:
            break
    length = int.from_bytes(raw[0:4], "little")
    checksum = int.from_bytes(raw[4:8], "little")
    body = bytes(raw[8:8 + length])
    if length <= 0 or len(body) != length:
        return None
    s = 0
    for b in body:
        s = (s * 31 + b) % 16777216
    if s != checksum:
        return None
    st = {"message_seq": 0, "message": "", "edit_active": False,
          "addon_version": 0, "context": "", "frames": []}
    for line in body.decode("utf-8", "replace").split("\n"):
        p = line.split("|")
        key = p[0]
        if key == "#msg" and len(p) >= 2:
            st["message_seq"] = int(p[1]) if p[1].isdigit() else 0
            if len(p) >= 4 and p[2].isdigit():  # #msg|seq|1|text (the middle field is a leftover of older versions)
                st["message"] = "|".join(p[3:])
            else:
                st["message"] = "|".join(p[2:])
        elif key == "#edit" and len(p) == 2:
            st["edit_active"] = p[1] == "1"
        elif key == "#ver" and len(p) == 2 and p[1].isdigit():
            st["addon_version"] = int(p[1])
        elif key == "#ctx" and len(p) >= 2:
            st["context"] = " | ".join(p[1:])
        elif len(p) == 7 and not key.startswith("#") and all(v.lstrip("-").isdigit() for v in p[3:]):
            x, y, w, h = (int(v) for v in p[3:])
            st["frames"].append((p[0], p[1], p[2], x + w // 2, y + h // 2))
    st["frames"] = tuple(st["frames"])
    return GameState(**st)
