"""Ask Claude through the locally installed, logged-in `claude` command line tool (Claude Code)."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

from . import config

CREATE_NO_WINDOW = 0x08000000  # Windows: no console window for the child process

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
    base = DEFAULT_SYSTEM
    try:
        base += "\n\n" + (Path(__file__).parent / "macro_skill.md").read_text(encoding="utf-8")
    except OSError:
        pass
    from . import vinput
    if vinput.available():
        base += "\n\n" + vinput.SKILL
    try:
        lines = config.PERSONA.read_text(encoding="utf-8").splitlines()
        if lines and lines[0].strip():
            return lines[0].strip(), base + "\n\n" + "\n".join(lines[1:]).strip()
    except OSError:
        pass
    return "Claude", base


REMINDER = (
    "\n\n[wowclaude format reminder, not from the player: if the player wants a macro, do NOT explain how to type it. "
    "Reply with one short sentence plus a block exactly like [[macro Name]]first command line\nsecond command line[[/macro]] "
    "(use the player's game language for spell names). The addon creates the macro for the player. "
    "For lists or plans use [[overlay Title]]lines[[/overlay]]. "
    "To show a video or web page over the game (YouTube, Twitch, Netflix ...) put [[play https://full-url]] in the reply; "
    "[[play off]] closes it.]"
)

def reminder() -> str:
    from . import vinput
    extra = ("\n[You also have background input: [[click X Y]] / [[keys TEXT]] act in the game window without interrupting the player.]"
             if vinput.available() else "")
    return REMINDER + extra


MACRO_RE = re.compile(r"\[\[macro ([^\]\n]{1,40})\]\]\s*(.*?)\s*\[\[/macro\]\]", re.S)


def extract_macros(text: str) -> tuple[str, list[dict]]:
    """Pull all [[macro Name]]...[[/macro]] blocks out of a reply."""
    macros = [{"name": m.group(1).strip()[:16], "body": m.group(2).strip()} for m in MACRO_RE.finditer(text)]
    return MACRO_RE.sub("", text).strip(), macros[:6]


PLAY_RE = re.compile(r"\[\[play (off|https://[^\s\]]{4,300})\]\]")


def extract_play(text: str) -> tuple[str, str | None]:
    """Pull a [[play https://...]] (or [[play off]]) command out of a reply. Only https URLs are accepted."""
    m = PLAY_RE.search(text)
    return (PLAY_RE.sub("", text).strip(), m.group(1) if m else None)


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
    """WOWCLAUDE_CLAUDE or config.json "claude" (full path to the executable) > `claude` on PATH."""
    custom = os.environ.get("WOWCLAUDE_CLAUDE") or config.load().get("claude")
    if custom and (os.path.exists(custom) or shutil.which(custom)):
        return custom
    return shutil.which("claude")


def check_login() -> tuple[bool, str]:
    """Run one tiny question to see whether Claude Code is installed AND logged in."""
    from . import backends
    if backends.name() != "claude":
        return backends.check()
    exe = claude_path()
    if not exe:
        return False, ("The 'claude' command was not found. Install Claude Code "
                       "(https://claude.com/claude-code), then run `claude` once in a terminal and log in.")
    try:
        done = subprocess.run([exe, "-p", "--output-format", "text", "--tools", ""], input="Reply with the word ok.",
                              capture_output=True, text=True, encoding="utf-8", timeout=90,
                              creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"Could not run Claude Code: {exc}"
    out = (done.stdout or "").strip()
    if done.returncode == 0 and out:
        return True, "Claude Code works."
    return False, ("Claude Code is installed but not logged in (or has no access): " + (out or done.stderr or "no answer").strip()[:160]
                   + "\nFix: open a terminal, run `claude`, log in once, then try again.")


class Session:
    """One conversation that survives bridge restarts (session id kept in ~/.wowclaude/session.txt)."""

    def __init__(self) -> None:
        self.history: list = []
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
        from . import backends
        if backends.name() != "claude":
            answer = backends.ask(persona()[1], self.history, prompt + reminder(), model)
            self.history.append((prompt, answer))
            return answer
        exe = claude_path()
        if not exe:
            raise RuntimeError("the 'claude' command was not found (install Claude Code and log in)")
        try:
            return self._run(exe, prompt, model)
        except RuntimeError:
            if not self.started:
                self._new()  # a half-created session id must not be reused ("already in use")
                raise
            self._new()  # stale or unknown session: start a fresh one once
            return self._run(exe, prompt, model)

    def _run(self, exe: str, prompt: str, model: str | None) -> str:
        prompt = prompt + reminder()
        cmd = [exe, "-p", "--output-format", "text", "--tools", "", "--append-system-prompt", persona()[1]]
        cmd += ["--resume" if self.started else "--session-id", self.id]
        if model:
            cmd += ["--model", model]
        try:
            done = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                                  cwd=str(config.HOME), timeout=180,
                                  creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Claude did not answer within 3 minutes.") from exc
        out = (done.stdout or "").strip()
        if done.returncode != 0 or not out:
            raise RuntimeError((done.stderr or out or "claude failed").strip()[:200])
        self.started = True
        return out
