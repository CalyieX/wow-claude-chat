"""Ask Claude through the locally installed, logged-in `claude` command line tool (Claude Code)."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid

from . import config

DEFAULT_SYSTEM = (
    "You are Claude, chatting with a World of Warcraft player inside the game's chat window. "
    "Reply in the player's language. Keep chat answers to at most 3 short sentences, with no markdown, "
    "no lists and no emojis, because the chat window is small. The player's current game state may "
    "arrive in square brackets in front of the question. Use it, do not repeat it.\n"
    "If an answer needs more room (a list, a plan, a build), append a window to your reply:\n"
    "[[overlay Title]]\nplain line\n|cff00ff00green line|r\n[bar 0.6 00ff00] label (bar from 0 to 1, colour RRGGBB)\n[[/overlay]]\n"
    "Keep the sentence in the chat short and put the details into the window."
)

OVERLAY_RE = re.compile(r"\[\[overlay(?: ([^\]\n]*))?\]\](.*?)\[\[/overlay\]\]", re.S)
CHUNK = 380
MAX_CHUNKS = 6


def persona() -> tuple[str, str]:
    """(reply prefix, system prompt). persona.txt: first line = prefix, the rest is added to the prompt."""
    try:
        lines = config.PERSONA.read_text(encoding="utf-8").splitlines()
        if lines and lines[0].strip():
            return lines[0].strip(), DEFAULT_SYSTEM + "\n\n" + "\n".join(lines[1:]).strip()
    except OSError:
        pass
    return "Claude", DEFAULT_SYSTEM


def extract_overlay(text: str) -> tuple[str, dict | None]:
    m = OVERLAY_RE.search(text)
    if not m:
        return text, None
    lines = [ln.rstrip() for ln in m.group(2).strip().splitlines()]
    title = (m.group(1) or "Claude").strip() or "Claude"
    secs = 45
    tail = re.search(r"\|(\d{1,3})$", title)
    if tail:
        secs, title = max(5, min(300, int(tail.group(1)))), title[:tail.start()].strip() or "Claude"
    return (text[:m.start()] + text[m.end():]).strip(), {"title": title, "lines": lines[:60], "secs": secs}


def split_reply(text: str, chunk: int = CHUNK) -> list[str]:
    text = " ".join(text.split())
    chunks: list[str] = []
    while text and len(chunks) < MAX_CHUNKS:
        if len(text) <= chunk:
            chunks.append(text)
            text = ""
            break
        cut = text.rfind(" ", 0, chunk)
        cut = cut if cut > 40 else chunk
        chunks.append(text[:cut])
        text = text[cut:].lstrip()
    if text:
        chunks[-1] = chunks[-1][: chunk - 12].rstrip() + " (...)"
    return chunks


def claude_path() -> str | None:
    return shutil.which("claude")


class Session:
    """One conversation that survives bridge restarts (session id kept in ~/.wowclaude/session.txt)."""

    def __init__(self) -> None:
        try:
            self.id, self.started = config.SESSION.read_text(encoding="utf-8").strip(), True
        except OSError:
            self.id, self.started = "", False
        if not self.id:
            self._new()

    def _new(self) -> None:
        self.id, self.started = str(uuid.uuid4()), False
        config.HOME.mkdir(parents=True, exist_ok=True)
        config.SESSION.write_text(self.id, encoding="utf-8")

    def ask(self, prompt: str, model: str | None = None) -> str:
        exe = claude_path()
        if not exe:
            raise RuntimeError("the 'claude' command was not found (install Claude Code and log in)")
        try:
            return self._run(exe, prompt, model)
        except RuntimeError:
            if not self.started:
                raise
            self._new()  # stale or unknown session: start a fresh one once
            return self._run(exe, prompt, model)

    def _run(self, exe: str, prompt: str, model: str | None) -> str:
        cmd = [exe, "-p", "--output-format", "text", "--tools", "", "--append-system-prompt", persona()[1]]
        cmd += ["--resume" if self.started else "--session-id", self.id]
        if model:
            cmd += ["--model", model]
        done = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                              cwd=str(config.HOME), timeout=180,
                              creationflags=0x08000000 if os.name == "nt" else 0)
        out = (done.stdout or "").strip()
        if done.returncode != 0 or not out:
            raise RuntimeError((done.stderr or out or "claude failed").strip()[:200])
        self.started = True
        return out
