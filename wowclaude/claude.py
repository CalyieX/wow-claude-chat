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
WEB_TOOLS = "WebSearch,WebFetch"  # default: the AI can look things up, never touch files or run commands
ACCESS_TOOLS = "Read,Glob,Grep,WebSearch,WebFetch,Bash,Edit,Write"  # only when the player switched computer access on


def computer_access() -> bool:
    """The player's own choice (menu button AI access, or the AI setup page): may the AI use this computer?"""
    return bool(config.load().get("computer_access"))


def own_harness(mode: str) -> bool:
    """Menu Harness: does the player want the AI's OWN setup (its own memory files, settings, tools) instead of the WoW AI harness?
    mode is "wow" (game chat) or "cli" (CLI mode); each one is set on its own."""
    return bool(config.load().get("own_harness_" + mode))


def run_tools() -> str:
    return ACCESS_TOOLS if computer_access() else WEB_TOOLS


def progress_label(tool: str, arg: str = "") -> str:
    """One short line for the chat while the AI works: what it is doing right now."""
    arg = (arg or "").replace(chr(10), " ").strip()[:40]
    names = {"WebSearch": "searching the web", "WebFetch": "reading a web page", "Read": "reading a file", "Glob": "looking for files",
             "Grep": "searching files", "Bash": "running a command", "Edit": "editing a file", "Write": "writing a file"}
    what = names.get(tool, "using " + tool)
    return what + (": " + arg if arg and tool in ("WebSearch", "WebFetch", "Bash") else "") + " ..."
TIMEOUT = 100  # seconds; the addon gives up after 120, so one run must fit in that


class AskTimeout(RuntimeError):
    """Claude did not answer in time. Never retried: a second run would only answer after the addon gave up."""

DEFAULT_NAME = "WoW AI"  # who writes when the player chose no name
DEFAULT_SYSTEM = (
    "You are an AI assistant chatting with a World of Warcraft player inside the game's chat window. "
    "Reply in the player's language. Keep chat answers to at most 3 short sentences, with no markdown, "
    "no lists and no emojis, because the chat window is small. Never mention the person's account, e-mail, "
    "user name or file paths, even if you can see them: you only know what the player tells you in this chat. The player's current game state may "
    "arrive in square brackets in front of the question. Use it, do not repeat it.\n"
    "If an answer needs more room (a list, a plan, a build), append a window to your reply:\n"
    "[[overlay Title]]\nplain line\n|cff00ff00green line|r\n[bar 0.6 00ff00] label (bar from 0 to 1, colour RRGGBB)\n[[/overlay]]\n"
    "Keep the sentence in the chat short and put the details into the window.\n\n"
    "GAME VERSION: every question starts with [Game state: ...] including 'Client <version> iface <number> <locale>' and the "
    "name of the game version. Answer for exactly that version. WoW Forever, Classic Era, Season of Discovery, Hardcore, "
    "Burning Crusade, Wrath, Cataclysm, Mists Classic and Retail differ in talents, trainers, quests, spells, drops and "
    "even macro rules. Never assume Classic Era knowledge for another version, and never guess from memory.\n"
    "CHARACTER: the state also names the character (name, level, class, zone). It is read fresh for every question, so when "
    "it differs from the earlier ones the player switched characters: forget class-specific details, macros and builds of "
    "the old character and answer for the new one.\n"
    "CLASSIC IS NOT FOREVER. WoW Forever has its own talents, trainers, quests, spell ranks and rules. Classic Era "
    "knowledge from your memory is WRONG for it more often than right.\n"
    "RESEARCH FIRST, EVERY TIME: game data goes out of date within days (patches, hotfixes, new seasons, changed talents). "
    "Before EVERY answer that contains a game fact (builds, talents, rotations, trainers, quests, drops, spells, prices, "
    "patch changes, events, class advice) you MUST search the web for the player's exact game version and use sources "
    "updated recently. Do not answer such questions from memory, not even when you feel sure. Name the source in a few "
    "words. If you cannot search, say plainly that you could not check and that the answer may be Classic knowledge "
    "or out of date; never present it as certain.\n"
    "YOUR TOOLS IN THIS ADDON (use them instead of describing what the player should do by hand):\n"
    "- macro: [[macro Name]]lines[[/macro]] creates a real macro on the player's cursor.\n"
    "- overlay window: [[overlay Title]]...[[/overlay]] for lists, builds, plans. It is a small panel over the game, not the "
    "browser: the player can drag and close it, the next one replaces it. Use it for what is too long for the chat; use the "
    "browser window only for web pages and videos.\n"
    "- WoW AI memos: [[remember short fact]] saves a fact about this character, [[remember all: short fact]] about the player "
    "for every character, [[forget text]] removes it. Saved facts come back in front of the questions as [WoW AI memos "
    "about this player ...]. Save only what the player told you or asked you to remember (class, role, goals, preferences, what they "
    "already did), one short fact each, never passwords, tokens or keys, and say in a few words that you saved it.\n"
    "- show window (PREFER it whenever you want to show the player something): [[show PATH-OR-LINK]] opens a small window over "
    "the game without a browser bar and shows images, video, music, PDF, HTML, Markdown, text, CSV and code. Links must be https "
    "and point straight to the file (image, mp4, mp3 ...); a local file works only when the player switched AI access on. It is a "
    "normal window (screenshots show it), so the player can work with it; the next [[show]] replaces it. Together with "
    "[[overlay Title]] (lists, builds, plans) this is your display. Use the browser window below only for real web pages "
    "(YouTube, wiki, guides, sites that need a login): it is the player's own browser, so open it only when a page is needed.\n"
    "- browser window over the game: [[play https://...]] (video, guide, wiki); [[play off]] closes it. In that window the "
    "ghost button makes it see-through and click-through, the dash minimizes it into the WAC button, X closes it.\n"
    "- addon menu and commands the player can use: /wac opens the menu (connect AI, browser, AI name, own name, strip, harness, tips, "
    "commands); /ai <text> asks you; /browser [address]; /nameai <name>; /nameme <name>; /aitab; /strip always|auto|off.\n"
    "- mouse and keyboard: [[click X Y]] / [[click X Y R]] / [[keys TEXT]] click and type in the game window without taking "
    "the player's own mouse (only when the player switched the tool on; the game state then lists the clickable elements "
    "with their positions). If it is off, tell the player where to switch it on: AI setup page, Mouse and keyboard.\n"
    "Be honest about limits: you cannot cast, target or move for the player (protected by the game), you do not see the "
    "screen unless the game state says so, and you never ask for passwords or personal data."
)

# interface number (from GetBuildInfo) -> what the player is running
FLAVORS = (
    (16000, 16999, "WoW Forever (Blizzard's Forever client, not Classic Era)"),
    (11500, 11599, "Classic Era (Season of Discovery / Hardcore / Anniversary use this client too)"),
    (20500, 20599, "Burning Crusade Classic"),
    (30400, 30499, "Wrath of the Lich King Classic"),
    (40400, 40499, "Cataclysm Classic"),
    (50500, 50599, "Mists of Pandaria Classic"),
    (100000, 999999, "Retail (current expansion)"),
)


def flavor(context: str) -> str:
    """Name of the game version from the 'iface N' part of the game state ('' when it is not there)."""
    m = re.search(r"iface (\d{4,6})", context or "")
    if not m:
        return ""
    n = int(m.group(1))
    return next((label for lo, hi, label in FLAVORS if lo <= n <= hi), "unknown version")

OVERLAY_RE = re.compile(r"\[\[overlay(?: ([^\]\n]*))?\]\](.*?)\[\[/overlay\]\]", re.S)
CHUNK = 380
MAX_CHUNKS = 6


RESERVED_TABS = {"general", "allgemein", "combat log", "kampflog", "trade", "handel", "localdefense", "lokale verteidigung",
                 "lookingforgroup", "gruppensuche", "whisper", "fluestern", "flüstern", "guild", "gilde", "officer", "offizier"}


def clean_name(raw) -> str:
    """The AI's name as shown in the tab and before answers: one short line, no control or separator characters."""
    name = re.sub(r"[\x00-\x1f|\\]", "", str(raw or "")).strip()[:20]
    return "" if name.lower() in RESERVED_TABS else name  # a real game tab (General ...) must never be taken over


def builtin_tools() -> str:
    """The built-in tool text that follows the general instructions (macros, browser window): the part you can edit."""
    try:
        return "\n\n" + (Path(__file__).parent / "macro_skill.md").read_text(encoding="utf-8")
    except OSError:
        return ""


def input_tool_text() -> str:
    """Mouse and keyboard tool text: always added by the program (never part of the editable harness) while the tool is on."""
    from . import vinput
    return ("\n\n" + vinput.SKILL) if vinput.available() else ""


def builtin_harness() -> str:
    """The harness that ships with the program: what the AI is told about the game, the research rule and its tools."""
    return DEFAULT_SYSTEM + builtin_tools()


def custom_harness() -> str | None:
    """The player's own edited harness (AI setup page), or None to use the built-in one."""
    try:
        text = config.HARNESS.read_text(encoding="utf-8").strip()
    except (OSError, ValueError):  # missing, or saved in a non-UTF-8 editor: use the built-in one
        return None
    return text or None


def persona_name_in_file() -> bool:
    """True if persona.txt (old style) carries the AI's name in its first line."""
    try:
        lines = config.PERSONA.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    return bool(lines and clean_name(lines[0]) and clean_name(lines[0]) != DEFAULT_NAME)


def default_name() -> str:
    """Who writes when the player chose no name: "Own AI" while the AI's own setup is on (the one in use: CLI chat or WoW chat),
    else "WoW AI"."""
    mode = "cli" if config.load().get("ai_mode") == "cli" else "wow"
    return "Own AI" if own_harness(mode) else DEFAULT_NAME


def persona() -> tuple[str, str]:
    """(name shown in the chat, system prompt). The name comes from config.json "name" (AI setup page); persona.txt is
    then all extra instructions. Old style without a name in config.json: the first line of persona.txt is the name.
    With neither, the name is "WoW AI"."""
    name = clean_name(config.load().get("name"))
    extra = ""
    try:
        lines = config.PERSONA.read_text(encoding="utf-8").splitlines()
        if name:
            extra = "\n".join(lines).strip()
        elif lines and clean_name(lines[0]):
            first = clean_name(lines[0])
            if first == DEFAULT_NAME:  # the default name kept in the file is no chosen name: "Own AI" must still show while own is on
                extra = "\n".join(lines[1:]).strip()
            else:
                name, extra = first, "\n".join(lines[1:]).strip()
    except OSError:
        pass
    name = name or default_name()
    custom = custom_harness()
    base = (custom if custom is not None else DEFAULT_SYSTEM) + f"\nYour name is {name}. Answer as {name}."
    player = clean_name(config.load().get("player"))
    if player:
        base += f"\nThe player's name is {player}. Call them {player}."
    base += ("\nCOMPUTER ACCESS: ON. The player allowed you to read and change files and run commands on their computer. Do it only "
             "when they ask, say in one sentence what you did, and ask before deleting anything."
             if computer_access() else
             "\nCOMPUTER ACCESS: OFF. You cannot touch the player's computer; you can only search the web. If they want more, "
             "tell them to switch AI access on in the menu (/wac).")
    if custom is None:
        base += builtin_tools()
    base += input_tool_text()
    return name, (base + "\n\n" + extra) if extra else base


REMINDER = (
    "\n\n[wowclaude reminder, not from the player: WoW Forever is NOT Classic. Search the web first for any game fact "
    "and answer for the game version in the game state; never from memory. "
    "Format: if the player wants a macro, do NOT explain how to type it. "
    "Reply with one short sentence plus a block exactly like [[macro Name]]first command line\nsecond command line[[/macro]] "
    "(use the player's game language for spell names). The addon creates the macro for the player. "
    "For lists or plans use [[overlay Title]]lines[[/overlay]]; to show a picture, video, song, PDF or document use [[show link-or-path]] (preferred over the browser). "
    "To show a video or web page over the game (YouTube, Twitch, Netflix ...) put [[play https://full-url]] in the reply; "
    "[[play off]] closes it.]"
)

def reminder() -> str:
    if own_harness("cli" if config.load().get("ai_mode") == "cli" else "wow"):
        return ""  # Own: no WoW reminder - the player talks to their own AI as in its own program
    from . import vinput
    extra = ("\n[You also have background input: [[click X Y]] / [[keys TEXT]] act in the game window without interrupting the player.]"
             if vinput.available() else "")
    base = REMINDER
    if own_harness("cli" if config.load().get("ai_mode") == "cli" else "wow"):
        base = base.replace("[wowclaude reminder, not from the player: WoW Forever is NOT Classic.",
                            "[addon note, not from the player: the player talks to you from inside World of Warcraft; stay yourself, the player's own AI. "
                            "WoW Forever is NOT Classic.")
    return base + extra


MACRO_RE = re.compile(r"\[\[macro ([^\]\n]{1,40})\]\]\s*(.*?)\s*\[\[/macro\]\]", re.S)


def extract_macros(text: str) -> tuple[str, list[dict]]:
    """Pull all [[macro Name]]...[[/macro]] blocks out of a reply."""
    macros = [{"name": m.group(1).strip()[:16], "body": m.group(2).strip()} for m in MACRO_RE.finditer(text)]
    return MACRO_RE.sub("", text).strip(), macros[:6]


SHOW_RE = re.compile(r"\[\[show ([^\]\n]{3,300})\]\]")


def extract_show(text: str) -> tuple[str, str | None]:
    """Pull a [[show PATH-OR-LINK]] out of a reply (the media window opens it)."""
    m = SHOW_RE.search(text)
    return (SHOW_RE.sub("", text).strip(), m.group(1).strip() if m else None)


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
    title = (m.group(1) or DEFAULT_NAME).strip() or DEFAULT_NAME
    secs = 45
    tail = re.search(r"\|(\d{1,3})$", title)
    if tail:
        secs, title = max(5, min(300, int(tail.group(1)))), title[:tail.start()].strip() or DEFAULT_NAME
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
        code, out, err = _exec([exe, "-p", "--output-format", "text", "--tools", WEB_TOOLS, "--allowedTools", WEB_TOOLS, "--strict-mcp-config",
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


def _clean_env(mode: str = "wow") -> dict:
    """The player's own CLAUDE.md files and auto-memory must not shape (or leak into) game chat answers."""
    env = dict(os.environ)
    if not own_harness(mode):  # the own harness keeps the AI's memory files
        env["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] = "1"
        env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        env.pop(var, None)  # the Claude login is the subscription: a stray API key must not answer for it
    token = config.load().get("claude_token")  # one-year token (claude setup-token) entered on the AI setup page: chat AND CLI mode
    if token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = str(token)
    home = config.load().get("claude_home")  # optional own login folder: other Claude apps cannot overwrite this login
    if home and not own_harness(mode):  # the own harness is the AI exactly as the player has it: its normal config folder and login
        env["CLAUDE_CONFIG_DIR"] = str(home)
    own_dir = config.load().get("own_config_dir")  # the Claude folder chosen on the Own AI tab (only when there are several)
    if own_dir and own_harness(mode):
        env["CLAUDE_CONFIG_DIR"] = str(own_dir)
    return env


def _exec(cmd: list, prompt: str, timeout: float | None = None) -> tuple:
    """Run the command with a hard time limit. On timeout the whole process tree is killed (a .cmd wrapper would
    otherwise keep running) and AskTimeout is raised. Returns (exit code, stdout, stderr)."""
    if "stream-json" in cmd:  # a normal question: tool use is shown in the chat while the AI works
        return _exec_stream(cmd, prompt, timeout or TIMEOUT, _progress, cwd=str(Path.home()) if computer_access() or own_harness("wow") else None)
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


def _progress(text: str) -> None:
    try:
        from . import chat_fake
        chat_fake.post("think", text)
    except Exception:  # noqa: BLE001 - no overlay, no progress line
        pass


def _exec_stream(cmd: list, prompt: str, timeout: float, on_progress, cwd: str | None = None) -> tuple:
    """Like _exec, but for `--output-format stream-json`: every tool the AI starts is reported to on_progress as a
    short line, the final text comes from the "result" event. Returns (exit code, final text, stderr)."""
    import json
    import threading
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace", cwd=cwd or neutral_cwd(), env=_clean_env(), **hidden())
    result: list = []
    errbuf: list = []

    def read_out() -> None:
        for line in proc.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("type") == "assistant":
                for blk in (ev.get("message") or {}).get("content") or []:
                    if isinstance(blk, dict) and blk.get("type") == "tool_use":
                        inp = blk.get("input") or {}
                        try:
                            on_progress(progress_label(blk.get("name", ""), str(inp.get("query") or inp.get("url") or inp.get("command") or "")))
                        except Exception:  # noqa: BLE001 - progress is a courtesy
                            pass
            elif ev.get("type") == "result":
                result.append(ev)

    t1 = threading.Thread(target=read_out, daemon=True)
    t2 = threading.Thread(target=lambda: errbuf.append(proc.stderr.read()), daemon=True)
    t1.start()
    t2.start()
    try:
        proc.stdin.write(prompt)
        proc.stdin.close()
    except OSError:
        pass
    t1.join(timeout)
    if t1.is_alive():
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, **hidden())
        else:
            proc.kill()
        raise AskTimeout(f"Claude did not answer within {round(timeout)} seconds.")
    proc.wait(10)
    t2.join(2)
    ev = result[-1] if result else {}
    text = str(ev.get("result") or "")
    code = proc.returncode if not ev.get("is_error") else (proc.returncode or 1)
    return code, text, "".join(errbuf)


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
        self._mode_file().write_text("own" if own_harness("wow") else "wow", encoding="utf-8")

    @staticmethod
    def _mode_file():
        return config.HOME / "session_mode.txt"

    def _sync_harness(self) -> None:
        """A session keeps the harness it started with (a resumed conversation goes on as WoW AI): switching WoW AI / Own starts a new one."""
        want = "own" if own_harness("wow") else "wow"
        try:
            have = self._mode_file().read_text(encoding="utf-8").strip()
        except OSError:
            have = "wow"
        if self.started and have != want:
            self._new()
            self.history = []

    def ask(self, prompt: str, model: str | None = None) -> str:
        if not config.ai_loaded():
            raise RuntimeError("No AI loaded. Open AI Setup (/kk) and load one.")
        started = time.time()
        try:
            answer = self._ask(prompt, model)
        except Exception as exc:
            config.record_answer(False, time.time() - started, str(exc))
            raise
        config.record_answer(True, time.time() - started)
        return answer

    def _ask(self, prompt: str, model: str | None = None) -> str:
        from . import backends
        self._sync_harness()
        if backends.name() != "claude":
            if own_harness("wow"):  # plain API / command backends have no folder: the player's own instructions go in as text
                from . import harness_import
                system = harness_import.api_system(config.load()) if backends.name() not in ("codex", "command") else ""
            else:
                system = persona()[1]
            answer = backends.ask(system, self.history, prompt + reminder(), model)
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
                    raise RuntimeError("Not signed in (Claude login expired). Type  /login  in the game chat: the sign-in page "
                                       "opens in the game browser. (Or run `claude` once in a terminal and log in.)") from exc
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
        if own_harness("wow"):  # the AI's own setup: its memory files, settings and tools; only the answer format is ours
            cmd = [exe, "-p", "--output-format", "stream-json", "--verbose", "--permission-mode", "acceptEdits"]
        else:
            tools = run_tools()
            cmd = [exe, "-p", "--output-format", "stream-json", "--verbose", "--tools", tools, "--allowedTools", tools, "--strict-mcp-config",
                   *ISOLATION, "--append-system-prompt-file", str(sysfile)]
            if computer_access():
                cmd += ["--permission-mode", "acceptEdits"]
        cmd += ["--resume" if self.started else "--session-id", self.id]
        if model:
            cmd += ["--model", model]
        left = max(5.0, t_end - time.time()) if t_end else TIMEOUT  # (a retry only starts with >= 20 s left)
        env_dir = _clean_env().get("CLAUDE_CONFIG_DIR") or "normal folder"
        print(f"[ask] harness={'own' if own_harness('wow') else 'wow'} session={'resume' if self.started else 'new'} config={env_dir} "
              f"system_prompt={'--append-system-prompt-file' in cmd}", flush=True)  # one line in bridge.log: what this question really ran with
        code, out, err = _exec(cmd, prompt, left)
        out = (out or "").strip()
        if code != 0 or not out:
            raise RuntimeError((err or out or "claude failed").strip()[:200])
        self.started = True
        return out
