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

_AUTH = re.compile(r"oauth|authenticat|not logged in|please log ?in|login required|unauthori[sz]ed|\b401\b|expired|credentials", re.I)
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


def no_browser_env() -> dict:
    """The login must open ONLY in the game browser: the tool is told to use a do-nothing 'browser' (BROWSER variable)."""
    import sys
    from pathlib import Path
    exe = Path(sys.executable).with_name("pythonw.exe")  # a windowless program that ignores the address: no black pop-up
    noop = str(exe if exe.exists() else sys.executable)
    env = claude._clean_env()
    env["BROWSER"] = noop
    return env


def logged_in() -> bool:
    """True unless the tool says it is not logged in (Claude only: `claude auth status`; unknown counts as logged in)."""
    import json
    if backends.name() == "codex":  # `codex login status` prints "Logged in ..." and exits 0 when signed in
        exe = shutil.which("codex")
        if not exe:
            return True
        try:
            return subprocess.run([exe, "login", "status"], capture_output=True, timeout=20, cwd=claude.neutral_cwd(),
                                  env=claude._clean_env(), **hidden()).returncode == 0
        except Exception:  # noqa: BLE001
            return True
    exe = claude.claude_path()
    if not exe or backends.name() != "claude":
        return True
    if claude._clean_env().get("CLAUDE_CODE_OAUTH_TOKEN"):  # signed in with a token: nothing to log in
        return True
    try:
        out = subprocess.run([exe, "auth", "status"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=20, cwd=claude.neutral_cwd(), env=claude._clean_env(), **hidden()).stdout
        return bool(json.loads(out).get("loggedIn", True))
    except Exception:  # noqa: BLE001 - cannot tell: let the tool itself ask
        return True


_TOKEN = re.compile(r"sk-ant-[A-Za-z0-9_-]{40,}")
_tok: dict = {}  # the running one-year-token sign-in: {"pty": process, "screen": pyte screen, "token": str}


def _token_signin() -> str:
    """Claude: `claude setup-token` in a hidden terminal. It shows the sign-in page and asks for the code; when it has
    printed the one-year token, the token is stored (config "claude_token") and works for chat AND CLI mode."""
    import pyte
    import winpty
    from . import overlay
    old = _tok.get("pty")
    if old is not None and old.isalive():
        return "The sign-in is already running: finish it in the browser window."
    screen = pyte.Screen(600, 40)
    stream = pyte.Stream(screen)
    proc = winpty.PtyProcess.spawn([claude.claude_path(), "setup-token"], dimensions=(40, 600), cwd=claude.neutral_cwd(),
                                   env=no_browser_env())
    _tok.clear()
    _tok.update({"pty": proc, "screen": screen, "token": ""})
    opened = threading.Event()

    def text() -> str:
        return "\n".join(line.rstrip() for line in screen.display)

    def reader() -> None:
        shown = False
        while True:
            try:
                data = proc.read(4096)
            except Exception:  # noqa: BLE001 - the terminal closed
                break
            if not data:
                continue
            stream.feed(data)
            body = text()
            if not shown:
                m = _URL.search(body)
                if m:
                    shown = True
                    overlay.play(m.group(0).rstrip(".,)"), "640x560")  # the in-game browser shows the sign-in page
                    opened.set()
            m = _TOKEN.search(body.replace(chr(10), ""))
            if m and not _tok.get("token"):
                _tok["token"] = m.group(0)
                _save_token(m.group(0))
        opened.set()

    threading.Thread(target=reader, daemon=True).start()
    opened.wait(25)
    return ("The sign-in page is open in the game browser: sign in there. The page shows a code: copy it and type "
            "/login <code> in the game chat. That gives you a login that lasts a year, for chat and CLI mode.")


def _save_token(token: str) -> None:
    cfg = config.load()
    cfg["claude_token"] = token
    config.save(cfg)
    try:
        from . import chat_fake
        chat_fake.post("sys", "Signed in for a year. Chat and CLI mode both use it.")
    except Exception:  # noqa: BLE001 - the overlay is optional
        pass
    try:  # the token ends the waiting sign-in terminal
        _tok["pty"].terminate(force=True)
    except Exception:  # noqa: BLE001
        pass


def _token_submit(code: str) -> str:
    import time
    proc = _tok.get("pty")
    if proc is None or not proc.isalive():
        return "No sign-in is waiting for a code. Type /login to start one."
    proc.write(code)
    time.sleep(0.4)
    proc.write(chr(13))
    for _ in range(60):
        if _tok.get("token"):
            return "Signed in for a year. Ask your question again."
        time.sleep(0.5)
    return "Code sent, still working. Ask again in a moment."


def _token_available() -> bool:
    if backends.name() != "claude" or not claude.claude_path():
        return False
    from . import cli_mode
    return cli_mode.available()[0]


def start() -> str:
    """Start the login and open its page in the overlay browser. Returns the sentence for the chat."""
    if _token_available():  # preferred: one-year token (no repeated sign-ins), shared by chat and CLI mode
        return _token_signin()
    cmd = command()
    if not cmd:
        return "This AI uses a key, not a login: open the menu (/wac), choose Connect AI and check the key."
    if _running and _running[0].poll() is None:
        return "The login is already running: finish it in the browser window."
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace", cwd=claude.neutral_cwd(), env=no_browser_env(), **hidden())
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
    if _tok.get("pty") is not None and _tok["pty"].isalive():
        return _token_submit(code)
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


_NET = re.compile(r"timed? ?out|connection|could not resolve|getaddrinfo|network|unreachable|ssl|econn|enotfound|name or service", re.I)
_KEY = re.compile(r"api key|invalid.*key|incorrect.*key|\b40[13]\b|forbidden|permission|quota|insufficient|billing|rate limit|\b429\b", re.I)


def explain(exc: Exception) -> str:
    """One plain sentence for the chat: what went wrong and what to do (never just 'it does not answer')."""
    text = str(exc)
    if "not found" in text.lower():
        return "The AI program was not found. Open /wac and choose Connect AI to pick another one."
    if isinstance(exc, claude.AskTimeout) or re.search(r"timed? ?out", text, re.I) and "connect" not in text.lower():
        return "The AI took too long to answer. Ask again, or try a shorter question."
    if is_auth_error(text):
        if command():
            return "Your AI login has expired. " + start()  # the login page opens by itself
        return "The AI refused the login or key. Open /wac, choose Connect AI and check it."
    if _KEY.search(text):
        return "The AI service refused the request (key, quota or limit). Open /wac, choose Connect AI and check the key and your balance."
    if _NET.search(text):
        return "No connection to the AI service. Check your internet connection and ask again."
    if "not found" in text.lower():
        return "The AI program was not found. Open /wac and choose Connect AI to pick another one."
    return "The AI did not answer (" + text.strip().replace(chr(10), " ")[:90] + "). Open /wac and choose Connect AI if it keeps happening."
