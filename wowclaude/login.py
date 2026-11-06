"""Log in again from inside the game: the login page of the AI service opens in the WoW browser window.

When an answer fails because the login of Claude Code / Codex expired, the bridge starts the service's own login command
(`claude auth login`, `codex login`), takes the address it prints and opens it in the overlay browser. The player signs in
there; the command finishes by itself and the next question works again.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import threading

from . import backends, claude, config
from .winproc import hidden

_AUTH = re.compile(r"oauth|authenticat|not logged in|log ?in|unauthori[sz]ed|\b401\b|expired|credentials", re.I)
_URL = re.compile(r"https://[^\s\"'<>]+")
_running: list = []


def is_auth_error(text: str) -> bool:
    return bool(_AUTH.search(text or ""))


def command() -> list[str] | None:
    """The login command of the AI service in use (None: this backend has no login, e.g. an API key)."""
    b = backends.name()
    if b == "claude":
        exe = claude.claude_path()
        return [exe, "auth", "login"] if exe else None
    if b == "codex":
        exe = shutil.which("codex")
        return [exe, "login"] if exe else None
    return None


def start() -> str:
    """Start the login and open its page in the overlay browser. Returns the sentence for the chat."""
    cmd = command()
    if not cmd:
        return "This AI uses a key, not a login: open the menu (/wac), choose Connect AI and check the key."
    if _running and _running[0].poll() is None:
        return "The login is already running: finish it in the browser window."
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace", cwd=claude.neutral_cwd(), env=claude._clean_env(), **hidden())
    _running[:] = [proc]
    found = threading.Event()

    def reader() -> None:
        from . import overlay
        opened = False
        for line in proc.stdout:  # the command prints the page address, then waits for the player to finish
            m = _URL.search(line)
            if m and not opened:
                opened = True
                overlay.play(m.group(0).rstrip(".,)"), "640x560")  # the in-game browser shows the login page
                found.set()
        found.set()

    threading.Thread(target=reader, daemon=True).start()
    found.wait(20)
    if proc.poll() is not None and proc.returncode == 0:
        return "You are logged in again. Ask your question again."
    return ("The login page is open in the game browser: sign in there. If the page shows a code, copy it and type "
            "/login <code> in the game chat. Then ask your question again.")


def submit(code: str) -> str:
    """The code shown after signing in (Claude Code asks for it when no local callback is possible)."""
    code = (code or "").strip()
    if not _running or _running[0].poll() is not None:
        return "No login is waiting for a code. Type /login to start one."
    try:
        _running[0].stdin.write(code + chr(10))
        _running[0].stdin.flush()
    except OSError:
        return "The login ended already. Ask your question again."
    try:
        _running[0].wait(30)
    except subprocess.TimeoutExpired:
        return "Code sent, the login is still working. Ask again in a moment."
    ok = _running[0].returncode == 0
    return "Logged in again. Ask your question again." if ok else "That code did not work. Type /login to start over."
