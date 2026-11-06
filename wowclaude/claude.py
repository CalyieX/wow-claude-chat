"""Ask Claude through the locally installed, logged-in `claude` command line tool (Claude Code)."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from . import config
from .winproc import hidden

CREATE_NO_WINDOW = 0x08000000  # Windows: no console window for the child process
TIMEOUT = 100  # seconds; the addon gives up after 120, so one run must fit in that


class AskTimeout(RuntimeError):
    """Claude did not answer in time. Never retried: a second run would only answer after the addon gave up."""

DEFAULT_SYSTEM = (
    "You are an AI assistant chatting with a World of Warcraft player inside the game's chat window. "
    "Reply in the player's language. Keep chat answers to at most 3 short sentences, with no markdown, "
    "no lists and no emojis, because the chat window is small. Never mention the person's account, e-mail, "
    "user name or file paths, even if you can see them: you only know what the player tells you in this chat. The player's current game state may "
    "arrive in square brackets in front of the question. Use it, do not repeat it.\n"
    "If an answer needs more room (a list, a plan, a build), append a window to your reply:\n"
    "[[overlay Title]]\nplain line\n|cff00ff00green line|r\n[bar 0.6 00ff00] label (bar from 0 to 1, colour RRGGBB)\n[[/overlay]]\n"
    "Keep the sentence in the chat short and put the details into the window."
)

OVERLAY_RE = re.compile(r"\[\[overlay(?: ([^\]\n]*))?\]\](.*?)\[\[/overlay\]\]", re.S)
CHUNK = 380
MAX_CHUNKS = 6


RESERVED_TABS = {"general", "allgemein", "combat log", "kampflog", "trade", "handel", "localdefense", "lokale verteidigung",
                 "lookingforgroup", "gruppensuche", "whisper", "fluestern", "flüstern", "guild", "gilde", "officer", "offizier"}


def clean_name(raw) -> str:
    """The AI's name as shown in the tab and before answers: one short line, no control or separator characters."""
    name = re.sub(r"[\x00-\x1f|\\]", "", str(raw or "")).strip()[:20]
    return "" if name.lower() in RESERVED_TABS else name  # a real game tab (General ...) must never be taken over


def persona() -> tuple[str, str]:
    """(name shown in the chat, system prompt). The name comes from config.json "name" (AI setup page); persona.txt is
    then all extra instructions. Old style without a name in config.json: the first line of persona.txt is the name.
    With neither, the name follows the backend (ChatGPT, Claude, Ollama ...)."""
    from . import backends
    name = clean_name(config.load().get("name"))
    extra = ""
    try:
        lines = config.PERSONA.read_text(encoding="utf-8").splitlines()
        if name:
            extra = "\n".join(lines).strip()
        elif lines and clean_name(lines[0]):
            name, extra = clean_name(lines[0]), "\n".join(lines[1:]).strip()
    except OSError:
        pass
    name = name or backends.label()
    base = DEFAULT_SYSTEM + f"\nYour name is {name}. Answer as {name}."
    try:
        base += "\n\n" + (Path(__file__).parent / "macro_skill.md").read_text(encoding="utf-8")
    except OSError:
        pass
    from . import vinput
    if vinput.available():
        base += "\n\n" + vinput.SKILL
    return name, (base + "\n\n" + extra) if extra else base


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
    title = (m.group(1) or "AI").strip() or "AI"
    secs = 45
    tail = re.search(r"\|(\d{1,3})$", title)
    if tail:
        secs, title = max(5, min(300, int(tail.group(1)))), title[:tail.start()].strip() or "AI"
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
    if os.name == "nt":  # prefer the native claude.exe: a .cmd wrapper cuts arguments at the first line break
        native = Path.home() / ".local" / "bin" / "claude.exe"
        if native.exists():
            return str(native)
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
    config.HOME.mkdir(parents=True, exist_ok=True)
    try:
        code, out, err = _exec([exe, "-p", "--output-format", "text", "--tools", "", "--strict-mcp-config",
                                *ISOLATION, "--no-session-persistence"], "Reply with the word ok.", 90)
    except (OSError, AskTimeout) as exc:
        return False, f"Could not run Claude Code: {exc}"
    out = (out or "").strip()
    if code == 0 and out:
        return True, "Claude Code works."
    return False, ("Claude Code is installed but not logged in (or has no access): " + (out or err or "no answer").strip()[:160]
                   + chr(10) + "Fix: open a terminal, run `claude`, log in once, then try again.")


def neutral_cwd() -> str:
    """Run Claude in the root of the system drive, not in the user's profile: a path inside the profile folder would leak the Windows user name."""
    return (os.path.splitdrive(str(config.HOME))[0] + os.sep) if os.name == "nt" else "/"


ISOLATION = ["--setting-sources", ""]  # no user/project settings, hooks or memory files shape the chat answers


def _clean_env() -> dict:
    """The player's own CLAUDE.md files and auto-memory must not shape (or leak into) game chat answers."""
    env = dict(os.environ)
    env["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] = "1"
    env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
    return env


def _exec(cmd: list, prompt: str, timeout: float | None = None) -> tuple:
    """Run the command with a hard time limit. On timeout the whole process tree is killed (a .cmd wrapper would
    otherwise keep running) and AskTimeout is raised. Returns (exit code, stdout, stderr)."""
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace", cwd=neutral_cwd(), env=_clean_env(),
                            **hidden())
    try:
        out, err = proc.communicate(prompt, timeout=timeout or TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, **hidden())
        else:
            proc.kill()
        try:
            proc.communicate(timeout=5)
        except Exception:  # noqa: BLE001 - nothing more to collect
            pass
        raise AskTimeout(f"Claude did not answer within {round(timeout or TIMEOUT)} seconds.") from exc
    return proc.returncode, out, err


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
        t_end = time.time() + TIMEOUT  # one shared budget for the run and a possible retry: the addon gives up at 120 s
        try:
            try:
                return self._run(exe, prompt, model, t_end)
            except AskTimeout:
                raise
            except RuntimeError as exc:
                low = str(exc).lower()
                if "expired" in low or "log in" in low or "login" in low or "authenticate" in low:
                    raise RuntimeError("Claude login expired: run `claude` once in a terminal and log in again.") from exc
                stale = ("no conversation found" in low or "already in use" in low or "session not found" in low
                         or "invalid session" in low or "unknown session" in low)
                if not (self.started and stale) or t_end - time.time() < 20:
                    raise  # only a stale session is worth a second run, and only if enough of the budget is left
                self._new()
                return self._run(exe, prompt, model, t_end)
        finally:
            if not self.started:
                self._new()  # an aborted first run may have claimed the id ("Session ID already in use" next time)

    def _run(self, exe: str, prompt: str, model: str | None, t_end: float | None = None) -> str:
        prompt = prompt + reminder()
        # system prompt via a file: multi-line arguments are mangled by Windows .cmd wrappers
        sysfile = config.HOME / "system_prompt.txt"
        config.HOME.mkdir(parents=True, exist_ok=True)
        sysfile.write_text(persona()[1], encoding="utf-8")
        cmd = [exe, "-p", "--output-format", "text", "--tools", "", "--strict-mcp-config", *ISOLATION,
               "--append-system-prompt-file", str(sysfile)]
        cmd += ["--resume" if self.started else "--session-id", self.id]
        if model:
            cmd += ["--model", model]
        left = max(5.0, t_end - time.time()) if t_end else TIMEOUT  # (a retry only starts with >= 20 s left)
        code, out, err = _exec(cmd, prompt, left)
        out = (out or "").strip()
        if code != 0 or not out:
            raise RuntimeError((err or out or "claude failed").strip()[:200])
        self.started = True
        return out
