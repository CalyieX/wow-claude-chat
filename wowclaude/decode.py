"""Decode the colour strip that the KKMap addon draws in the top-left corner of the game window.

Layout: 4x4 pixel cells, 128 per row, 3 bytes (R, G, B) per cell. The first 8 cells are fixed
calibration colours; then 4 bytes length (LE), 4 bytes checksum, then UTF-8 text lines such as
``#msg|seq|slot|text`` or ``#ack|seq``.
"""
from __future__ import annotations

from dataclasses import dataclass

CELL = 4
COLS = 128
ROWS = 20
MAGIC = ((255, 0, 255), (0, 255, 255), (255, 255, 0), (0, 0, 0),
         (255, 255, 255), (255, 0, 0), (0, 255, 0), (0, 0, 255))


@dataclass(frozen=True)
class GameState:
    message_seq: int = 0
    message_idx: int = 0
    message: str = ""
    ack_seq: int = 0
    edit_active: bool = False
    addon_version: int = 0
    context: str = ""
    image_next: int = 1
    slot_next: int = 1


def _cell(px, ox: int, oy: int, i: int) -> tuple[int, int, int]:
    x = ox + (i % COLS) * CELL + CELL // 2
    y = oy + (i // COLS) * CELL + CELL // 2
    return tuple(int(v) for v in px[x, y][:3])


def _locate(image, search_w: int = 400, search_h: int = 400):
    px = image.convert("RGB").load()
    w, h = image.size
    for oy in range(0, max(0, min(search_h, h - CELL * ROWS))):
        for ox in range(0, max(0, min(search_w, w - CELL * COLS))):
            if tuple(px[ox, oy]) != MAGIC[0]:
                continue
            if (ox > 0 and tuple(px[ox - 1, oy]) == MAGIC[0]) or (oy > 0 and tuple(px[ox, oy - 1]) == MAGIC[0]):
                continue
            if all(_cell(px, ox, oy, i) == MAGIC[i] for i in range(8)):
                return px, ox, oy
    return None


def decode(image) -> GameState | None:
    """Decode the strip from a PIL image of the game window. None if no valid strip is visible."""
    found = _locate(image)
    if found is None:
        return None
    px, ox, oy = found
    raw = bytearray()
    for i in range(8, COLS * ROWS):
        raw.extend(_cell(px, ox, oy, i))
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
    st = {"message_seq": 0, "message_idx": 0, "message": "", "ack_seq": 0, "edit_active": False,
          "addon_version": 0, "context": "", "image_next": 1, "slot_next": 1}
    for line in body.decode("utf-8", "replace").split("\n"):
        p = line.split("|")
        key = p[0]
        if key == "#msg" and len(p) >= 2:
            st["message_seq"] = int(p[1]) if p[1].isdigit() else 0
            if len(p) >= 4 and p[2].isdigit():
                st["message_idx"] = int(p[2])
                st["message"] = "|".join(p[3:])
            else:
                st["message"] = "|".join(p[2:])
        elif key == "#ack" and len(p) == 2 and p[1].isdigit():
            st["ack_seq"] = int(p[1])
        elif key == "#edit" and len(p) == 2:
            st["edit_active"] = p[1] == "1"
        elif key == "#ver" and len(p) == 2 and p[1].isdigit():
            st["addon_version"] = int(p[1])
        elif key == "#img" and len(p) == 2 and p[1].isdigit():
            st["image_next"] = int(p[1])
        elif key == "#slot" and len(p) == 2 and p[1].isdigit():
            st["slot_next"] = int(p[1])
        elif key == "#ctx" and len(p) >= 2:
            st["context"] = " | ".join(p[1:])
    return GameState(**st)
