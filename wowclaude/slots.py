"""Return channel into the game without any keystrokes (idea from the MIT-licensed wow-ai project).

A LoadOnDemand addon's files are read from disk when it is loaded, so we pre-create SLOTS tiny
addons (KKR001..KKR200 with one Reply.lua each), write the reply into all of them, and tell the
in-game addon "a reply is ready" through a silent sound file: PlaySoundFile() reports whether a file
is playable, and an empty .wav is not. The addon then loads the next unused slot.
"""
from __future__ import annotations

import glob
import io
import os
import re
import shutil
import time
import wave
from pathlib import Path

SLOTS = 200
IMAGE_SLOTS = 24
IMAGE_SIZE = 512
ADDON_SRC = Path(__file__).parent / "addon" / "KKMap"


def _addons(root: Path) -> Path:
    return root / "Interface" / "AddOns"


def _silent_wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 800)
    return buf.getvalue()


def lua_string(text: str) -> str:
    out = []
    for ch in text:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\n")
        elif ord(ch) < 32:
            continue
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def reply_lua(seq: int, parts: list[str], overlay: dict | None = None, macros: list[dict] | None = None) -> str:
    body = ", ".join(lua_string(p) for p in parts)
    extra = ""
    if macros:
        items = ", ".join("{ name = %s, body = %s }" % (lua_string(m["name"]), lua_string(m["body"].replace("\n", "\\n")))
                          for m in macros)
        extra += f", macros = {{ {items} }}"
    if overlay:
        lines = ", ".join(lua_string(str(x)) for x in overlay.get("lines", []))
        extra += (f", overlay = {{ title = {lua_string(str(overlay.get('title', 'Claude')))}, "
                 f"lines = {{ {lines} }}, secs = {int(overlay.get('secs', 45))} }}")
    return f"KKReplyData = {{ seq = {int(seq)}, parts = {{ {body} }}{extra} }}\n"


def install(root: Path) -> dict:
    """Copy the KKMap addon, create the reply slots and the image slots. Safe to run again."""
    addons = _addons(root)
    if not addons.is_dir():
        raise FileNotFoundError(f"not a game client folder: {root}")
    target = addons / "KKMap"
    target.mkdir(exist_ok=True)
    for name in ("KKMap.lua", "KKMap.toc"):
        shutil.copyfile(ADDON_SRC / name, target / name)
    toc = "## Interface: 11508, 11509, 11510, 20505, 30403, 40402, 40403, 50503, 50504, 16001\n## Title: {name}\n## LoadOnDemand: 1\nReply.lua\n"
    created = 0
    for i in range(1, SLOTS + 1):
        name = f"KKR{i:03d}"
        folder = addons / name
        folder.mkdir(exist_ok=True)
        if not (folder / f"{name}.toc").exists():
            (folder / f"{name}.toc").write_text(toc.format(name=name), encoding="utf-8")
            created += 1
        if not (folder / "Reply.lua").exists():
            (folder / "Reply.lua").write_text("KKReplyData = nil\n", encoding="utf-8")
    sig = target / "sig"
    sig.mkdir(exist_ok=True)
    for i in range(1, SLOTS + 1):
        f = sig / f"{i:03d}.wav"
        if not f.exists():
            f.write_bytes(b"")
    install_images(root)
    enabled = 0
    for path in glob.glob(str(root / "WTF" / "Account" / "*" / "*" / "*" / "AddOns.txt")):
        p = Path(path)
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        have = {ln.split(":")[0].strip() for ln in lines}
        add = [f"KKR{i:03d}: enabled" for i in range(1, SLOTS + 1) if f"KKR{i:03d}" not in have]
        if add:
            p.write_text("\n".join(lines + add) + "\n", encoding="utf-8")
            enabled += 1
    return {"slots_created": created, "characters_enabled": enabled}


def publish(root: Path, seq: int, idx: int, parts: list[str], overlay: dict | None = None,
            macros: list[dict] | None = None) -> None:
    """Write the reply into every slot, then flip the silent-sound marker ``idx`` to playable."""
    addons = _addons(root)
    content = reply_lua(seq, parts, overlay, macros).encode("utf-8")
    def write(i: int) -> None:
        target = addons / f"KKR{i:03d}" / "Reply.lua"
        tmp = target.with_suffix(".tmp")
        for attempt in range(5):  # a virus scanner may hold a file for a moment
            try:
                tmp.write_bytes(content)
                os.replace(tmp, target)
                return
            except PermissionError:
                time.sleep(0.2 * (attempt + 1))
        tmp.write_bytes(content)
        os.replace(tmp, target)

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=16) as pool:  # 200 small files: one after the other took 20+ s with a scanner
        list(pool.map(write, range(1, SLOTS + 1)))
    marker = addons / "KKMap" / "sig" / f"{((int(idx) - 1) % SLOTS) + 1:03d}.wav"
    tmp = marker.with_suffix(".tmp")
    tmp.write_bytes(_silent_wav())
    os.replace(tmp, marker)


def reset_marker(root: Path, idx: int) -> None:
    """Make the marker for ``idx`` silent again. A marker left playable from an earlier answer would make the
    addon think a reply is ready and burn one reply slot every poll while the new answer is still being written."""
    marker = _addons(root) / "KKMap" / "sig" / f"{((int(idx) - 1) % SLOTS) + 1:03d}.wav"
    try:
        marker.write_bytes(b"")
    except OSError:
        pass


def install_images(root: Path) -> int:
    from PIL import Image
    folder = _addons(root) / "KKMap" / "img"
    folder.mkdir(parents=True, exist_ok=True)
    made = 0
    for i in range(1, IMAGE_SLOTS + 1):
        target = folder / f"{i:03d}.tga"
        if not target.exists():
            Image.new("RGBA", (4, 4), (0, 0, 0, 255)).save(target, format="TGA")
            made += 1
    return made


def write_image(root: Path, src: str | os.PathLike, idx: int) -> None:
    from PIL import Image
    if not 1 <= int(idx) <= IMAGE_SLOTS:
        raise ValueError("image slot out of range")
    im = Image.open(src).convert("RGBA")
    im.thumbnail((IMAGE_SIZE, IMAGE_SIZE))
    canvas = Image.new("RGBA", (IMAGE_SIZE, IMAGE_SIZE), (0, 0, 0, 0))
    canvas.paste(im, ((IMAGE_SIZE - im.width) // 2, (IMAGE_SIZE - im.height) // 2))
    target = _addons(root) / "KKMap" / "img" / f"{int(idx):03d}.tga"
    tmp = target.with_suffix(".tmp")
    canvas.save(tmp, format="TGA")
    os.replace(tmp, target)


def resolve_images(root: Path, lines: list[str], next_idx: int) -> list[str]:
    """Turn overlay lines ``[img PATH]`` into ``[img N]`` after writing the picture into slot N."""
    out, idx = [], int(next_idx or 1)
    for line in lines:
        m = re.match(r"^\[img\s+(.+?)\]\s*$", line)
        if not m:
            out.append(line)
            continue
        if idx > IMAGE_SLOTS:
            out.append("(image slots used up - they reset on the next reload)")
            continue
        try:
            write_image(root, m.group(1).strip().strip('"'), idx)
        except (OSError, ValueError) as exc:
            out.append("(image not readable: " + str(exc)[:60] + ")")
            continue
        out.append(f"[img {idx}]")
        idx += 1
    return out
