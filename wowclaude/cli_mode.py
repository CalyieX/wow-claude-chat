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
from pathlib import Path

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


def window_size() -> tuple[int, int]:
    """Columns and rows of the CLI window (written by the window itself)."""
    try:
        d = json.loads((config.HOME / "termsize.json").read_text(encoding="utf-8"))
        return max(20, min(200, int(d["cols"]))), max(5, min(60, int(d["rows"])))
    except (OSError, ValueError, KeyError):
        return 110, 30


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


def harness_text(window: bool = False) -> str:
    """The same harness the chat mode uses (name, game knowledge, tools, memos rules), plus a note for the terminal."""
    if window:
        return claude.persona()[1] + (
            "\n\nYou run inside a real terminal window next to the World of Warcraft window. You are the AI of the WoW AI addon, "
            "with the name given above: never say you are Claude, Codex or ChatGPT. Here the player works with you like in any command "
            "line tool; the game chat is a separate conversation.")
    return claude.persona()[1] + (
        "\n\nYou run inside a terminal that is shown in a small tab of the World of Warcraft chat window. You are the AI of the "
        "WoW AI addon, with the name given above: never say you are Claude, Codex or ChatGPT; if asked who you are, give that name. "
        "Keep answers short, the tab is small. The player types in the game chat; a [Game state: ...] line "
        "comes in front of the first message and whenever it changes: use it, never ask for what it tells you.")


def harness_file(window: bool = False):
    """The harness as a file (a command line is too short for it)."""
    path = config.HOME / ("win_harness.txt" if window else "cli_harness.txt")
    path.write_text(harness_text(window), encoding="utf-8")
    return path


def command(window: bool = False) -> list[str] | None:
    """The command line of the tool in use (None: this backend has no command line tool)."""
    from . import backends
    key = "win" if window else "cli"  # the CLI chat (tab) and the CLI window have their own WoW AI / Own switch
    b = backends.name()
    if b == "claude":
        exe = claude.claude_path()
        if not exe:
            return None
        if claude.own_harness(key):  # the AI's own setup (memory files, settings, tools): work on your own projects
            return [exe]
        cmd = [exe, "--setting-sources", "", "--append-system-prompt-file", str(harness_file(window))]  # not the player's own settings
        if not claude.computer_access():
            cmd += ["--tools", claude.WEB_TOOLS, "--allowedTools", claude.WEB_TOOLS]
        return cmd
    if b == "codex":
        exe = shutil.which("codex")
        if not exe:
            return None
        if claude.own_harness(key):
            return [exe, "--search", "-c", "projects." + json.dumps(str(Path.home())) + '.trust_level="trusted"']
        cmd = [exe, "--search"] + ([] if claude.computer_access() else ["-s", "read-only"])
        folder = str(Path.home()) if claude.computer_access() else claude.neutral_cwd()  # chosen by the "AI access" switch
        cmd += ["-c", "projects." + json.dumps(folder) + '.trust_level="trusted"']  # no "trust this folder?" question
        text = harness_text(window)
        if len(text) < 20000:  # Windows command lines are limited: a longer harness is left out rather than breaking the start
            cmd += ["-c", "developer_instructions=" + json.dumps(text)]  # a TOML string accepts the same escapes
        return cmd
    return None


def prepare_config(cwd: str) -> None:
    """The tool's first-run screens ignore a token (it would ask to sign in again): mark the first run as done, and trust the
    neutral working folder (it holds nothing). The folder of the player's own files (computer access) stays a real question."""
    import os
    from pathlib import Path
    home = claude._clean_env("cli").get("CLAUDE_CONFIG_DIR") or ""  # the same folder the tool will use (config "claude_home")
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


def _log(text: str) -> None:
    try:
        with open(config.HOME / "cli.log", "a", encoding="utf-8") as f:
            f.write(time.strftime("%H:%M:%S ") + text + "\n")
    except OSError:
        pass


class CliMode:
    def __init__(self, window: bool = False) -> None:
        self.window = window  # False: the tab in the game chat; True: its own session in the CLI window
        self.key = "win" if window else "cli"
        self.stem = "win" if window else "cli"
        self.proc = None
        self.screen = None
        self.stream = None
        self.size = DEFAULT_SIZE
        self.dirty = threading.Event()
        self.lock = threading.Lock()
        self.stop_flag = False
        self.hidden = False  # chat mode: the tool keeps running (its conversation stays) but the tab shows the chat
        self.repost = False
        self.gen = 0  # one number per start(): the loops of an earlier start end by themselves

    # -- lifecycle ---------------------------------------------------------------------------------------------
    def running(self) -> bool:
        return bool(self.proc is not None and self.proc.isalive())

    def start(self) -> str:
        if not config.ai_loaded():
            return "No AI loaded. Open AI Setup (/kk) and load one."
        ok, why = available()
        if not ok:
            return why
        cmd = command(self.window)
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
        cols, rows = window_size() if self.window else tab_size()
        self.size = (cols, rows)
        self.screen = pyte.HistoryScreen(cols, rows, history=2000)  # keeps what scrolled off the top
        self.offset = 0
        self.stream = pyte.Stream(self.screen)
        cwd = str(Path.home()) if claude.computer_access() or claude.own_harness(self.key) else claude.neutral_cwd()
        prepare_config(cwd)
        from . import login
        env = login.no_browser_env()  # a /login inside the tool must not open the normal browser
        self.proc = winpty.PtyProcess.spawn(cmd, dimensions=(rows, cols), cwd=cwd, env=env)
        self.stop_flag = False
        self.gen += 1
        gen = self.gen
        threading.Thread(target=self._read, args=(gen,), daemon=True).start()
        self.started = time.time()
        threading.Thread(target=self._paint_loop, args=(gen,), daemon=True).start()
        if self.window:
            threading.Thread(target=self._input_loop, args=(gen,), daemon=True).start()
        return ""

    def hide(self) -> None:
        """Back to the normal chat tab without ending the tool: switching back finds the conversation as it was."""
        self.hidden = True
        self._post(None)

    def show(self) -> None:
        self.hidden = False
        self.repost = True
        self.dirty.set()

    def stop(self) -> None:
        self.hidden = False
        self.stop_flag = True
        try:
            if self.proc is not None:
                self.proc.terminate(force=True)
        except Exception:  # noqa: BLE001 - already gone
            pass
        self.proc = None
        if not self.window:
            self._post(None)

    # -- terminal -> screen -------------------------------------------------------------------------------------
    def _read(self, gen: int) -> None:
        proc = self.proc
        while not self.stop_flag and proc is not None and self.gen == gen:
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
            (config.HOME / "win_screen.json").write_text(json.dumps({"text": "\n".join(hist + disp), "time": time.time()}),
                                                         encoding="utf-8")
        except OSError:
            pass

    def _input_loop(self, gen: int) -> None:
        """Keys typed in the CLI window go straight into the tool."""
        path = config.HOME / "win_in.jsonl"
        pos = path.stat().st_size if path.exists() else 0
        checked = 0.0
        while not self.stop_flag and self.gen == gen:
            time.sleep(0.05)
            if time.time() - checked > 1.0:  # "Unload" in the AI setup ends a running tool session too
                checked = time.time()
                if not config.ai_loaded() and self.running():
                    _log("AI unloaded: tool session ended")
                    self.stop()
                    return
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
            if raw and not self.running():  # the tool ended or never came up: a typed key starts it again instead of vanishing
                self.start()
                return  # start() runs a fresh input loop
            if raw:
                try:
                    self.proc.write(raw)
                except Exception as exc:  # noqa: BLE001
                    _log("input loop ended: " + repr(exc))
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

    def _window_loop(self, gen: int) -> None:
        """The CLI window's own session: feed its screen file; end the tool when the window is gone."""
        seen = False
        while not self.stop_flag and self.gen == gen:
            self.dirty.wait(0.5)
            self.dirty.clear()
            self._resize_if_needed()
            self._dump()
            from . import term_window
            if term_window.alive(6):
                seen = True
            elif seen or time.time() - self.started > 25:
                self.stop()
                break
            if not self.running():
                break
            time.sleep(0.1)

    def _paint_loop(self, gen: int) -> None:
        if self.window:
            return self._window_loop(gen)
        last = ""
        checked = 0.0
        while not self.stop_flag and self.gen == gen:
            self.dirty.wait(0.05)  # short: the scroll bar over the tab writes cli_scroll.json and wants a quick answer
            if self._apply_scroll_file():
                self.dirty.set()
            if not self.dirty.is_set() and time.time() - checked < 0.5:
                continue
            checked = time.time()
            self.dirty.clear()
            self._resize_if_needed()
            text = self._lines()
            self._publish_state()
            if "Enter to confirm" in text or "Esc to cancel" in text:  # the tool waits for an answer
                text += chr(10) + "[It asks a question: open the CLI window (/term) or use /k up|down|enter]"
            if "Not logged in" in text or "/login" in text:
                text += chr(10) + "[Not logged in: type  /login  in the game chat - the sign-in page opens in the game browser]"
            if not self.running():
                text += "\n[the command line tool ended - type anything to start it again, /aimode chat to leave]"
            if self.repost:
                self.repost, last = False, ""
            if text != last and not self.hidden:
                last = text
                self._post(text)
            time.sleep(0.08)  # about twelve repaints a second at most
            if not self.running():
                break

    def _publish_state(self) -> None:
        """How much there is to scroll in the tab: the scroll bar over the tab (chat_fake) reads this."""
        with self.lock:
            top = len(self.screen.history.top)
            disp = [ln.rstrip() for ln in self.screen.display]
            while disp and not disp[-1]:
                disp.pop()
            state = {"total": top + len(disp), "fit": self.screen.lines, "offset": min(self.offset, top)}
        if state != getattr(self, "_state_sent", None):
            self._state_sent = state
            try:
                (config.HOME / "cli_state.json").write_text(json.dumps(state), encoding="utf-8")
            except OSError:
                pass

    def _apply_scroll_file(self) -> bool:
        """The scroll bar over the tab asked for a position (cli_scroll.json): True when the view changed."""
        f = config.HOME / "cli_scroll.json"
        try:
            stamp = f.stat().st_mtime_ns
        except OSError:
            return False
        if stamp == getattr(self, "_scroll_stamp", 0):
            return False
        self._scroll_stamp = stamp
        try:
            want = int(json.loads(f.read_text(encoding="utf-8")).get("offset", 0))
        except (OSError, ValueError, TypeError):
            return False
        with self.lock:
            new = max(0, min(want, len(self.screen.history.top)))
            changed = new != self.offset
            self.offset = new
        return changed

    def _resize_if_needed(self) -> None:
        cols, rows = window_size() if self.window else tab_size()
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
        if not config.ai_loaded():
            return "No AI loaded. Open AI Setup (/kk) and load one."
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
_win = CliMode(window=True)


def restart_for_harness(which: str) -> str:
    """The harness of a running CLI session changed: end it and start it again with the new one (applied now)."""
    from . import term_window
    if which == "cli" and active() and _cli.running():
        _cli.stop()
        return _cli.start() or ""
    if which == "win" and term_window.alive() and _win.running():
        _win.stop()
        return _win.start() or ""
    return ""


def open_window() -> str:
    """Open the real CLI window (scroll, select, copy, paste, type). No console window."""
    import subprocess
    import sys
    from pathlib import Path
    from . import term_window
    if term_window.alive():
        return "The CLI window is already open."
    (config.HOME / "term.close").unlink(missing_ok=True)  # an old close request must not shut the new window
    why = _win.start()  # the window has its own tool session (its own WoW AI / Own switch)
    if why:
        return why
    exe = Path(sys.executable).with_name("pythonw.exe")
    subprocess.Popen([str(exe if exe.exists() else sys.executable), "-m", "wowclaude", "term"], creationflags=0x08000000)
    return "CLI window opened. Click into it to type, copy and paste; click the game to play on."


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
        if _cli.running():  # it kept running in the background: show the conversation as it was
            _cli.show()
            return "CLI mode on (the conversation is still there). /aimode chat leaves CLI mode."
        why = _cli.start()
        if why:
            return why
        return ("CLI mode on. The tab works as before; for arrow keys, scrolling and copy/paste open the CLI window "
                "(menu: CLI window). /aimode chat leaves CLI mode.")
    cfg.pop("ai_mode", None)
    config.save(cfg)
    _write_state()
    if _cli.running():
        _cli.hide()  # keep the CLI conversation alive for the way back
    else:
        _cli.stop()
    return "Chat mode on."


_last_context = [""]


def with_state(text: str, context: str) -> str:
    """The tool gets no game-state line like the chat mode: put it in front of the message when it is new or changed,
    with the WoW AI memos (not with the AI's own harness)."""
    if not context or context == _last_context[0] or claude.own_harness("cli"):
        return text
    _last_context[0] = context
    memos = ""
    try:
        from . import memory
        memos = memory.prompt_block(context).replace("\n", " ")
    except Exception:  # noqa: BLE001 - memos are a convenience
        pass
    return f"[Game state: {context}] {memos}{text}"


def handle(text: str, context: str = "") -> str | None:
    """A message from the game while CLI mode is on. Returns a short note for the chat, or None (it went to the tool)."""
    t = text.strip()
    if t.lower().startswith("!term"):
        return open_window()
    if t.lower().startswith("!scroll"):
        return _cli.scroll(t[7:]) or None
    if t.lower().startswith("!k "):
        return _cli.send_key(t[3:].strip()) or None
    return _cli.send_line(with_state(t, context)) or None
