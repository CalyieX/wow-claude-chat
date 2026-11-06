"""CLI mode: the AI tab shows the ORIGINAL command line tool (Claude Code or Codex), running in a hidden terminal.

The tool runs in a pseudo terminal (ConPTY via the optional package pywinpty); its screen is read with pyte and painted
into the AI tab by the chat overlay (event kind "cli"). What you type in the AI tab goes into the tool; keys that cannot
be typed in the game chat (arrows, Esc, Tab, Ctrl+C ...) are sent with  /k up|down|left|right|enter|esc|tab|space|ctrl-c|<char>.

Off by default (menu: AI mode). The tool keeps its own login and its own permission questions. Without computer access
(menu: AI access) Claude Code is started with web tools only.
"""
from __future__ import annotations

import json
import shutil
import threading
import time

from . import claude, config

DEFAULT_SIZE = (60, 14)  # columns, rows until the overlay reports the real size of the tab
SIZE_FILE = config.HOME / "tabsize.json"
KEYS = {"up": "\x1b[A", "down": "\x1b[B", "right": "\x1b[C", "left": "\x1b[D", "enter": "\r", "esc": "\x1b", "tab": "\t",
        "space": " ", "ctrl-c": "\x03", "ctrl-d": "\x04", "backspace": "\x7f", "shift-tab": "\x1b[Z", "pgup": "\x1b[5~", "pgdn": "\x1b[6~"}
MISSING = ("CLI mode needs two small helper packages. Close the game's AI program and run once:  py -3 -m pip install pywinpty pyte  "
           "(then switch AI mode on again).")


def available() -> tuple[bool, str]:
    try:
        import pyte  # noqa: F401
        import winpty  # noqa: F401
    except ImportError:
        return False, MISSING
    return True, ""


def tab_size() -> tuple[int, int]:
    """Columns and rows that fit into the AI tab (written by the chat overlay), else a small default."""
    try:
        d = json.loads((config.HOME / "termsize.json").read_text(encoding="utf-8"))
        if time.time() - float(d["time"]) < 4:  # the CLI window is open: the tool uses its size
            return max(20, min(200, int(d["cols"]))), max(5, min(60, int(d["rows"])))
    except (OSError, ValueError, KeyError):
        pass
    try:
        d = json.loads(SIZE_FILE.read_text(encoding="utf-8"))
        return max(20, min(200, int(d["cols"]))), max(5, min(60, int(d["rows"])))
    except (OSError, ValueError, KeyError):
        return DEFAULT_SIZE


def harness_text() -> str:
    """The same harness the chat mode uses (name, game knowledge, tools, memos rules), plus a note for the terminal."""
    return claude.persona()[1] + (
        "\n\nYou run inside a terminal that is shown in a small tab of the World of Warcraft chat window. You are the AI of the "
        "WoW AI addon, with the name given above: never say you are Claude, Codex or ChatGPT; if asked who you are, give that name. "
        "Keep answers short, the tab is small. The player types in the game chat; the game state line is not added here, "
        "so ask when you need the character or zone.")


def harness_file():
    """The harness as a file (a command line is too short for it)."""
    path = config.HOME / "cli_harness.txt"
    path.write_text(harness_text(), encoding="utf-8")
    return path


def command() -> list[str] | None:
    """The command line of the tool in use (None: this backend has no command line tool)."""
    from . import backends
    b = backends.name()
    if b == "claude":
        exe = claude.claude_path()
        if not exe:
            return None
        if claude.own_harness("cli"):  # the AI's own setup (memory files, settings, tools): work on your own projects
            return [exe]
        cmd = [exe, "--setting-sources", "", "--append-system-prompt-file", str(harness_file())]  # not the player's own settings
        if not claude.computer_access():
            cmd += ["--tools", claude.WEB_TOOLS, "--allowedTools", claude.WEB_TOOLS]
        return cmd
    if b == "codex":
        exe = shutil.which("codex")
        if not exe:
            return None
        if claude.own_harness("cli"):
            return [exe, "--search", "-c", "projects." + json.dumps(str(Path.home())) + '.trust_level="trusted"']
        cmd = [exe, "--search"] + ([] if claude.computer_access() else ["-s", "read-only"])
        folder = str(Path.home()) if claude.computer_access() else claude.neutral_cwd()  # chosen by the "AI access" switch
        cmd += ["-c", "projects." + json.dumps(folder) + '.trust_level="trusted"']  # no "trust this folder?" question
        text = harness_text()
        if len(text) < 20000:  # Windows command lines are limited: a longer harness is left out rather than breaking the start
            cmd += ["-c", "developer_instructions=" + json.dumps(text)]  # a TOML string accepts the same escapes
        return cmd
    return None


def prepare_config(cwd: str) -> None:
    """The tool's first-run screens ignore a token (it would ask to sign in again): mark the first run as done, and trust the
    neutral working folder (it holds nothing). The folder of the player's own files (computer access) stays a real question."""
    import os
    from pathlib import Path
    home = os.environ.get("CLAUDE_CONFIG_DIR") or ""
    path = (Path(home) / ".claude.json") if home else (Path.home() / ".claude.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        return
    changed = False
    if not data.get("hasCompletedOnboarding"):
        data["hasCompletedOnboarding"] = True
        data.setdefault("theme", "dark")
        changed = True
    if True:  # the folder is either the empty neutral one or the player's home, chosen by switching "AI access" on
        proj = data.setdefault("projects", {}).setdefault(cwd.replace("\\", "/"), {})
        if not proj.get("hasTrustDialogAccepted"):
            proj["hasTrustDialogAccepted"] = True
            changed = True
    if changed:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass


class CliMode:
    def __init__(self) -> None:
        self.proc = None
        self.screen = None
        self.stream = None
        self.size = DEFAULT_SIZE
        self.dirty = threading.Event()
        self.lock = threading.Lock()
        self.stop_flag = False

    # -- lifecycle ---------------------------------------------------------------------------------------------
    def running(self) -> bool:
        return bool(self.proc is not None and self.proc.isalive())

    def start(self) -> str:
        ok, why = available()
        if not ok:
            return why
        cmd = command()
        if not cmd:
            return "CLI mode needs the Claude Code or Codex login (Connect AI). Other AIs have no command line tool."
        if self.running():
            return ""
        from . import login
        if not login.logged_in():  # sign in through the game browser first, then the tool starts logged in
            return login.start()
        import pyte
        import winpty
        from pathlib import Path
        cols, rows = tab_size()
        self.size = (cols, rows)
        self.screen = pyte.HistoryScreen(cols, rows, history=2000)  # keeps what scrolled off the top
        self.offset = 0
        self.stream = pyte.Stream(self.screen)
        cwd = str(Path.home()) if claude.computer_access() or claude.own_harness("cli") else claude.neutral_cwd()
        prepare_config(cwd)
        from . import login
        env = login.no_browser_env()  # a /login inside the tool must not open the normal browser
        self.proc = winpty.PtyProcess.spawn(cmd, dimensions=(rows, cols), cwd=cwd, env=env)
        self.stop_flag = False
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._paint_loop, daemon=True).start()
        threading.Thread(target=self._input_loop, daemon=True).start()
        return ""

    def stop(self) -> None:
        self.stop_flag = True
        try:
            if self.proc is not None:
                self.proc.terminate(force=True)
        except Exception:  # noqa: BLE001 - already gone
            pass
        self.proc = None
        self._post(None)

    # -- terminal -> screen -------------------------------------------------------------------------------------
    def _read(self) -> None:
        proc = self.proc
        while not self.stop_flag and proc is not None:
            try:
                data = proc.read(4096)
            except EOFError:
                break
            except Exception:  # noqa: BLE001
                break
            if data:
                with self.lock:
                    self.stream.feed(data)
                    self.offset = 0  # new output: show the live screen again
                self.dirty.set()
        self.dirty.set()

    def _lines(self) -> str:
        with self.lock:
            cols = self.screen.columns
            rows = self.screen.lines
            hist = ["".join(line[x].data for x in range(cols)).rstrip() for line in self.screen.history.top]
            disp = [ln.rstrip() for ln in self.screen.display]
            offset = min(self.offset, len(hist))
        full = hist + disp
        end = len(full) - offset
        lines = full[max(0, end - rows + (1 if offset else 0)):end]  # one row less when the hint line is added
        if offset == 0:
            while lines and not lines[-1]:
                lines.pop()
        else:
            lines.append("[scrolled back: /scroll down or /scroll end]")
        return "\n".join(lines)

    def _dump(self) -> None:
        """Everything incl. scrollback for the CLI window (term_window.py)."""
        with self.lock:
            cols = self.screen.columns
            hist = ["".join(line[x].data for x in range(cols)).rstrip() for line in self.screen.history.top]
            disp = [ln.rstrip() for ln in self.screen.display]
        while disp and not disp[-1]:
            disp.pop()
        try:
            (config.HOME / "cli_screen.json").write_text(json.dumps({"text": "\n".join(hist + disp), "time": time.time()}),
                                                         encoding="utf-8")
        except OSError:
            pass

    def _input_loop(self) -> None:
        """Keys typed in the CLI window go straight into the tool."""
        path = config.HOME / "cli_in.jsonl"
        pos = path.stat().st_size if path.exists() else 0
        while not self.stop_flag and self.running():
            time.sleep(0.05)
            try:
                size = path.stat().st_size
                if size < pos:
                    pos = 0
                if size == pos:
                    continue
                with open(path, "rb") as f:
                    f.seek(pos)
                    chunk = f.read()
                pos += len(chunk)
            except OSError:
                continue
            raw = "".join(json.loads(ln).get("raw", "") for ln in chunk.decode("utf-8", "replace").splitlines() if ln.strip())
            if raw:
                try:
                    self.proc.write(raw)
                except Exception:  # noqa: BLE001
                    break
                self.dirty.set()

    def scroll(self, how: str) -> str:
        """Look at what scrolled off the top (mouse wheel in the tab, /scroll up|down|end). The tool itself is not touched."""
        how = how.strip().lower()
        with self.lock:
            step = max(1, self.screen.lines // 2)
            top = len(self.screen.history.top)
            if how == "up":
                self.offset = min(top, self.offset + step)
            elif how == "down":
                self.offset = max(0, self.offset - step)
            elif how in ("end", "bottom", "live"):
                self.offset = 0
            else:
                return "Use: /scroll up, /scroll down or /scroll end"
        self.dirty.set()
        return ""

    def _paint_loop(self) -> None:
        last = ""
        while not self.stop_flag:
            self.dirty.wait(0.5)
            self.dirty.clear()
            self._resize_if_needed()
            self._dump()
            text = self._lines()
            if "Not logged in" in text or "/login" in text:
                text += chr(10) + "[Not logged in: type  /login  in the game chat - the sign-in page opens in the game browser]"
            if not self.running():
                text += "\n[the command line tool ended - type anything to start it again, /aimode chat to leave]"
            if text != last:
                last = text
                self._post(text)
            time.sleep(0.25)  # at most four repaints a second
            if not self.running():
                break

    def _resize_if_needed(self) -> None:
        cols, rows = tab_size()
        if (cols, rows) != self.size and self.running():
            self.size = (cols, rows)
            try:
                self.proc.setwinsize(rows, cols)
                with self.lock:
                    self.screen.resize(rows, cols)
            except Exception:  # noqa: BLE001 - a failed resize keeps the old size
                pass

    @staticmethod
    def _post(text: str | None) -> None:
        try:
            from . import chat_fake
            chat_fake.post("cli", text or "")
        except Exception:  # noqa: BLE001 - no overlay, nothing to show
            pass

    # -- player -> terminal -------------------------------------------------------------------------------------
    def send_line(self, text: str) -> str:
        why = self.start() if not self.running() else ""
        if why:
            return why
        self.proc.write(text)
        time.sleep(0.4)  # Enter as its own write: sent together with the text, the tool takes it for pasted text
        self.proc.write("\r")
        self.dirty.set()
        return ""

    def send_key(self, name: str) -> str:
        why = self.start() if not self.running() else ""
        if why:
            return why
        key = KEYS.get(name.strip().lower(), name if len(name) == 1 else "")
        if not key:
            return "Unknown key. Use: " + ", ".join(sorted(KEYS)) + " or a single character."
        self.proc.write(key)
        self.dirty.set()
        return ""


_cli = CliMode()


def open_window() -> str:
    """Open the CLI window: a page in the game's overlay window (always on top, scroll, select, copy, paste, type)."""
    from . import overlay, setup_ui
    url = setup_ui.start_background() + "&view=term"
    problem = overlay.play(url, "760x460")
    if problem:
        return f"Could not open the window ({problem}). Open this address in any browser: {url}"
    return "CLI window opened in the browser window. Click into it to type, copy and paste; click the game to play on."


def active() -> bool:
    return config.load().get("ai_mode") == "cli"


def _write_state() -> None:
    try:
        from . import installer
        installer.write_state()
    except Exception:  # noqa: BLE001 - the menu colours are a convenience
        pass


def set_mode(mode: str) -> str:
    cfg = config.load()
    if mode == "cli":
        ok, why = available()
        if not ok:
            return why
        if not command():
            return "CLI mode needs the Claude Code or Codex login (Connect AI)."
        cfg["ai_mode"] = "cli"
        config.save(cfg)
        _write_state()
        why = _cli.start()
        return why or "CLI mode on: this tab now shows the command line tool. Type to talk to it, /k up|down|enter|esc for keys, /aimode chat to leave."
    cfg.pop("ai_mode", None)
    config.save(cfg)
    _write_state()
    _cli.stop()
    return "Chat mode on."


def handle(text: str) -> str | None:
    """A message from the game while CLI mode is on. Returns a short note for the chat, or None (it went to the tool)."""
    t = text.strip()
    if t.lower().startswith("!term"):
        return open_window()
    if t.lower().startswith("!scroll"):
        return _cli.scroll(t[7:]) or None
    if t.lower().startswith("!k "):
        return _cli.send_key(t[3:].strip()) or None
    return _cli.send_line(t) or None
