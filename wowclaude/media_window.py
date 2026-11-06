"""Media viewer: the AI shows a file or a direct media link over the game ([[show PATH-OR-URL]]).

Images, video, music, PDF, HTML, Markdown, text, CSV and code in one small window WITHOUT a browser bar (a Chrome/Edge
app window with its own profile; the page is generated here). It is a normal opaque window: screenshots show it, so you can
work with what the AI displays. The browser overlay (/browser) stays free for web pages.
Local files are only shown when the player switched AI access on; https links always.
"""
from __future__ import annotations

import csv
import html
import io
import re
import subprocess
import time
from pathlib import Path

from . import claude, config

DIR = config.HOME / "media"
IMG = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".avif", ".ico"}
VID = {".mp4", ".webm", ".mkv", ".mov", ".m4v", ".ogv"}
AUD = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".opus"}
CSS = ("html,body{margin:0;height:100%;background:#15130e;color:#f0e6c8;font:14px Segoe UI,Arial,sans-serif}"
       "body{display:flex;flex-direction:column;align-items:center;justify-content:center;overflow:auto}"
       "img,video{max-width:100%;max-height:100vh}h1,h2,h3{color:#ffd100;font-family:Georgia,serif}"
       "a{color:#ffd100}pre{white-space:pre-wrap;text-align:left;margin:0;padding:12px;width:100%;box-sizing:border-box}"
       "table{border-collapse:collapse;margin:12px}td,th{border:1px solid #5c5c5c;padding:4px 8px}th{color:#ffd100}"
       ".doc{align-self:stretch;padding:14px 18px;text-align:left}embed,iframe{width:100%;height:100vh;border:0;background:#fff}"
       "audio{width:90%;margin-top:14px}.t{color:#ffd100;font:16px Georgia,serif;margin-bottom:6px}")


def kind(source: str) -> str:
    ext = Path(source.split("?")[0]).suffix.lower()
    if ext in IMG:
        return "image"
    if ext in VID:
        return "video"
    if ext in AUD:
        return "audio"
    return {".pdf": "pdf", ".html": "html", ".htm": "html", ".md": "md", ".markdown": "md", ".csv": "csv"}.get(ext, "text")


def markdown(text: str) -> str:
    """Small Markdown: headings, bold, italic, code, links, lists, tables, paragraphs. Everything else stays text."""
    out, in_list, in_code = [], False, False
    rows: list[list[str]] = []

    def inline(s: str) -> str:
        s = html.escape(s)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
        s = re.sub(r"\*([^*]+)\*", r"<i>\1</i>", s)
        return re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', s)

    def flush_table() -> None:
        nonlocal rows
        if rows:
            body = "".join("<tr>" + "".join(f"<{'th' if i == 0 else 'td'}>{inline(c)}</{'th' if i == 0 else 'td'}>" for c in r) + "</tr>"
                           for i, r in enumerate(rows))
            out.append(f"<table>{body}</table>")
            rows = []

    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            out.append("<pre>" if in_code else "</pre>")
            continue
        if in_code:
            out.append(html.escape(line))
            continue
        if re.match(r"^\s*\|.*\|\s*$", line):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                rows.append(cells)
            continue
        flush_table()
        m = re.match(r"^(#{1,3})\s+(.*)", line)
        li = re.match(r"^\s*[-*]\s+(.*)", line)
        if li and not in_list:
            out.append("<ul>")
            in_list = True
        if not li and in_list:
            out.append("</ul>")
            in_list = False
        if m:
            out.append(f"<h{len(m.group(1))}>{inline(m.group(2))}</h{len(m.group(1))}>")
        elif li:
            out.append(f"<li>{inline(li.group(1))}</li>")
        elif line.strip():
            out.append(f"<p>{inline(line)}</p>")
    flush_table()
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def page(source: str, title: str = "") -> str | None:
    """The HTML for a file or https link, or None when it must not be shown (local file without AI access, missing file)."""
    remote = source.lower().startswith("https://")
    k = kind(source)
    if not remote:
        p = Path(source).expanduser()
        if not claude.computer_access() and DIR not in p.resolve().parents:
            return None  # a local file is the player's: only with AI access on
        if not p.is_file():
            return None
        src = p.resolve().as_uri()
    else:
        src = source
    head = f'<div class="t">{html.escape(title)}</div>' if title else ""
    if k == "image":
        body = f'{head}<img src="{src}">'
    elif k == "video":
        body = f'{head}<video src="{src}" controls autoplay></video>'
    elif k == "audio":
        body = f'{head}<div class="t">{html.escape(title or Path(source).name)}</div><audio src="{src}" controls autoplay></audio>'
    elif k == "pdf":
        body = f'<embed src="{src}" type="application/pdf">'
    elif k == "html":
        body = f'<iframe src="{src}" sandbox="allow-scripts"></iframe>'
    else:
        if remote:
            return None  # text-like files are read from disk only
        text = Path(source).expanduser().read_text(encoding="utf-8", errors="replace")[:400_000]
        if k == "md":
            body = f'{head}<div class="doc">{markdown(text)}</div>'
        elif k == "csv":
            rows = list(csv.reader(io.StringIO(text)))[:500]
            body = head + "<table>" + "".join(
                "<tr>" + "".join(f"<{'th' if i == 0 else 'td'}>{html.escape(c)}</{'th' if i == 0 else 'td'}>" for c in r) + "</tr>"
                for i, r in enumerate(rows)) + "</table>"
        else:
            body = f"{head}<pre>{html.escape(text)}</pre>"
    return f'<!doctype html><meta charset="utf-8"><title>{html.escape(title or "WoW AI")}</title><style>{CSS}</style>{body}'


def show(source: str, title: str = "") -> str:
    """Open the viewer. Returns "" on success, else a short reason."""
    from . import overlay
    exe = overlay.find_browser()
    if not exe:
        return "no Chrome/Edge/Brave found"
    content = page(source.strip(), title)
    if content is None:
        return "that file cannot be shown (local files need AI access on, links must be https)"
    DIR.mkdir(parents=True, exist_ok=True)
    f = DIR / "view.html"
    f.write_text(content, encoding="utf-8")
    profile = config.HOME / "panel-profile"
    profile.mkdir(parents=True, exist_ok=True)
    overlay._kill_profile_browsers(profile)  # replaces the previous one; the browser overlay (own profile) is untouched
    g = overlay.game_rect()
    w, h = 760, 520
    x, y = (g[2] - w - 40, g[1] + 90) if g else (120, 100)
    before = set(overlay._windows())
    proc = subprocess.Popen([exe, f"--app={f.resolve().as_uri()}?t={int(time.time())}", f"--user-data-dir={profile}",
                             f"--window-size={w},{h}", f"--window-position={max(0, x)},{max(0, y)}", "--autoplay-policy=no-user-gesture-required",
                             "--no-first-run", "--disable-features=Translate"], creationflags=0x08000000)
    for _ in range(100):
        time.sleep(0.1)
        mine = [hw for hw in set(overlay._windows()) - before if overlay._window_pid(hw) == proc.pid]
        if mine:
            import ctypes
            u = ctypes.windll.user32
            u.SetWindowPos(ctypes.c_void_p(mine[0]), ctypes.c_void_p(-1), 0, 0, 0, 0, 0x13)  # topmost, no move/size/activate
            return ""
    return "the viewer window did not appear"

