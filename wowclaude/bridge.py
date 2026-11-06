"""Main loop: read the player's message from the strip, ask Claude, show the answer in the chat overlay."""
from __future__ import annotations

import re
import time
from pathlib import Path

from . import claude, config, decode, screen


def read_state() -> decode.GameState | None:
    img = screen.grab_strip_area()
    return decode.decode(img) if img is not None else None


def _safe_read_state() -> decode.GameState | None:
    try:
        return read_state()
    except Exception as exc:  # noqa: BLE001 - a failed screenshot must never end the bridge
        print(f"screen read failed: {exc}", flush=True)
        return None


def _start_overlay() -> None:
    try:
        from . import chat_fake
        chat_fake.start()
    except Exception:  # noqa: BLE001 - the overlay is optional
        pass


def _post(kind: str, text: str) -> None:
    try:
        from . import chat_fake
        chat_fake.post(kind, text)
    except Exception:  # noqa: BLE001 - the overlay is optional, never block the answer
        pass


_last_context = [""]  # the game state line of the latest question (for /memory)


def handle_command(text: str) -> str | None:
    """In-game slash commands that the addon sends as "!name args" (never forwarded to the AI)."""
    parts = text.strip().split(None, 1)
    cmd, arg = parts[0].lower(), (parts[1].strip() if len(parts) > 1 else "")
    if cmd in ("!memos", "!memory"):
        from . import memory
        if arg.lower() == "clear":
            memory.clear(memory.character(_last_context[0]))
            return "WoW AI memos of this character deleted (the shared 'all characters' memos stay)."
        return memory.show(_last_context[0])
    if cmd == "!browser":
        from . import overlay
        closing = arg in ("off", "close")
        problem = overlay.play("off" if closing else arg)
        if problem:
            return "Browser did not open: " + problem
        return "Browser closed." if closing else "Browser opened."
    if cmd == "!aimode":
        from . import cli_mode
        want = arg.lower() if arg else ("chat" if cli_mode.active() else "cli")
        return cli_mode.set_mode("cli" if want == "cli" else "chat")
    if cmd == "!harness":
        words = arg.lower().split()
        if words and words[0] == "edit":  # the harness text lives here (menu Harness), not on the Connect AI page
            import subprocess
            import sys
            from pathlib import Path
            exe = Path(sys.executable).with_name("pythonw.exe")
            subprocess.Popen([str(exe if exe.exists() else sys.executable), "-m", "wowclaude", "harness"], creationflags=0x08000000)
            return "Harness editor opened in its own window."
        mode = words[0] if words and words[0] in ("wow", "cli") else ""
        if not mode:
            return "Harness: /harness wow  or  /harness cli  switches between the WoW AI harness and your AI's own setup."
        cfg = config.load()
        own = (words[1] in ("own", "mine", "on")) if len(words) > 1 else not cfg.get("own_harness_" + mode)
        if own:
            cfg["own_harness_" + mode] = True
        else:
            cfg.pop("own_harness_" + mode, None)
        config.save(cfg)
        try:
            from . import installer
            installer.write_state()
        except Exception:  # noqa: BLE001
            pass
        what = "WoW chat" if mode == "wow" else "CLI"
        return (f"{what}: " + ("your AI's own harness (its own memory files and settings)" if own else "the WoW AI harness") +
                (". Applies to the next question." if mode == "wow" else ". Applies when CLI mode starts again (/aimode chat, then /aimode cli)."))
    if cmd == "!ol":
        from . import panel_window
        panel_window.open_empty()
        return "Overlay window opened."  # (a None answer would show as unknown command)
    if cmd == "!term":
        return "The CLI window is for CLI mode: /aimode cli"
    if cmd == "!scroll":
        return "Scrolling works in CLI mode: /aimode cli"
    if cmd == "!k":
        return "CLI mode is off. Type /aimode cli to start it."
    if cmd == "!access":
        cfg = config.load()
        want = arg.lower() in ("on", "1", "yes") if arg else not cfg.get("computer_access")
        if want:
            cfg["computer_access"] = True
        else:
            cfg.pop("computer_access", None)
        config.save(cfg)
        try:
            from . import installer
            installer.write_state()
        except Exception:  # noqa: BLE001
            pass
        return ("AI access is ON: the AI may read and change files and run commands on this computer when you ask it. "
                "Switch it off again in the menu (/wac)." if want else "AI access is OFF: the AI can only search the web.")
    if cmd == "!login":
        from . import login
        return login.submit(arg) if arg else login.start()
    if cmd == "!setup":
        from . import overlay, setup_ui
        url = setup_ui.start_background()
        problem = overlay.play(url, "640x520")
        if problem:
            return f"Could not open the window ({problem}). Open this address in any browser: {url}"
        return "AI setup opened in the browser window."
    if cmd == "!me":
        cfg = config.load()
        who = claude.clean_name(arg)
        if who:
            cfg["player"] = who
        else:
            cfg.pop("player", None)
        config.save(cfg)
        return "Your name: " + (who or "(none)")
    if cmd == "!name":
        from . import installer
        name = claude.clean_name(arg)
        cfg = config.load()
        if name:
            cfg["name"] = name
        else:
            cfg.pop("name", None)
        config.save(cfg)
        root = config.client_root()
        if root:
            installer.write_name(root, name)
        return "Name: " + (name or claude.DEFAULT_NAME)
    return None


_CODES = re.compile(r"\|c[0-9a-fA-F]{8}|\|r")


def deliver(state: decode.GameState, reply: str) -> None:
    """Show the answer in the chat overlay. Macros are typed into the game when input control is on, otherwise the
    command to type is shown with the answer."""
    reply, macros = claude.extract_macros(reply)
    reply, overlay = claude.extract_overlay(reply)
    reply, play = claude.extract_play(reply)
    reply, show = claude.extract_show(reply)
    from . import vinput
    reply, acts = vinput.extract(reply) if vinput.available() else (reply, [])
    from . import memory
    reply, mem_acts = memory.extract(reply)
    mem_notes = memory.apply(state.context, mem_acts) if mem_acts else []
    for act in acts:
        try:
            print(f"input {act}: {'ok' if vinput.run(act) else 'failed'}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"input failed: {exc}", flush=True)
    if play:
        try:
            from . import overlay as ov
            ov.play(play)
        except Exception as exc:  # noqa: BLE001 - the text answer must still arrive
            print(f"overlay failed: {exc}", flush=True)
    note = ""
    if show:  # the media window (images, video, music, PDF, text ...), no browser
        try:
            from . import media_window
            why = media_window.show(show)
            note = f"\n(could not show it: {why})" if why else ""
        except Exception as exc:  # noqa: BLE001 - the text answer must still arrive
            print(f"show failed: {exc}", flush=True)
            note = "\n(could not open the show window)"
    text = reply or "..."
    text += note
    if overlay:  # lists, builds, plans: the panel window over the game (no browser); if it cannot open, the lines join the answer
        try:
            from . import panel_window
            panel_window.show(str(overlay.get("title", "")), overlay.get("lines", []))
        except Exception as exc:  # noqa: BLE001
            print(f"panel failed: {exc}", flush=True)
            lines = [_CODES.sub("", str(x)) for x in overlay.get("lines", []) if not str(x).startswith("[img")]
            text += "\n" + _CODES.sub("", str(overlay.get("title", ""))) + "\n" + "\n".join(lines)
    for m in macros:
        cmd = f"/kkm {m['name']}~{m['body']}" + ("~char" if m.get("char") else "")
        if vinput.available() and vinput.run("keys {Enter}" + cmd + "{Enter}"):
            text += f"\n(macro '{m['name']}' created - find it in /macro)"
        else:
            text += f"\nMacro '{m['name']}': type  {cmd}"
    if mem_notes:
        text += "\n(" + mem_notes[0] + ")"
    _post("ai", claude.persona()[0] + ": " + text.strip())


CLI_BYPASS = ("!ol", "!harness", "!aimode", "!access", "!setup", "!browser", "!login", "!name", "!me")  # still handled by the bridge in CLI mode
LOCK_PORT = 47831
_lock_socket = None


FRESH_SECONDS = 25


def is_fresh(seq: int, now: float | None = None) -> bool:
    """The addon uses the send time (epoch seconds) as message number: a message sent within the last seconds is new."""
    return 0 <= (now if now is not None else time.time()) - int(seq) <= FRESH_SECONDS


def acquire_lock():
    """Only one bridge per PC: a second one would answer every question twice. Returns the socket, or None if taken."""
    import socket
    global _lock_socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", LOCK_PORT))  # no SO_REUSEADDR: a second bind must fail
    except OSError:
        sock.close()
        return None
    _lock_socket = sock  # kept alive for the whole run; the OS frees it when the program ends, even on a crash
    return sock


def run(root: Path, poll: float = 0.6) -> None:
    if acquire_lock() is None:
        print("wowclaude is already running on this PC (close the other window first).", flush=True)
        return
    overlay_check = 0.0
    session = claude.Session()
    last_seq: int | None = None
    print(f"wowclaude is running (game folder: {root}). Press Ctrl+C to stop.", flush=True)
    while True:
        if not screen.game_running():
            last_seq = None  # new game start: never answer an old message
            time.sleep(3)
            continue
        if time.time() - overlay_check > 10:  # the chat overlay lives and dies with the bridge
            overlay_check = time.time()
            _start_overlay()
        state = _safe_read_state()
        if state is None:
            time.sleep(poll)
            continue
        if last_seq is None:
            # first reading after a game start: an old message is skipped, but one that was sent just now (the player
            # typed /browser right after the start) is not, or the very first message after a restart would be lost
            last_seq = 0 if (state.message.strip() and is_fresh(state.message_seq)) else state.message_seq
        elif state.message_seq != last_seq and state.message.strip():
            last_seq = state.message_seq
            question = state.message.strip()
            if state.context:
                _last_context[0] = state.context
                from . import memory as _mem
                question = _mem.prompt_block(state.context) + question
                ver = claude.flavor(state.context)
                question = "[Game state: " + state.context + (" | Game version: " + ver if ver else "") + "]\n" + question
            from . import vinput
            if vinput.available() and state.frames:
                question = vinput.frames_hint(state.frames) + question
            from . import cli_mode
            if cli_mode.active() and not state.message.lstrip().lower().startswith(CLI_BYPASS):
                try:  # CLI mode: the original command line tool answers in the tab by itself
                    note = cli_mode.handle(state.message.strip())
                except Exception as exc:  # noqa: BLE001
                    note = "CLI mode: " + str(exc)[:100]
                if note:
                    _post("sys", note)
                time.sleep(poll)
                continue
            print(f"> {state.message.strip()}", flush=True)
            _post("user", "You: " + state.message.strip())
            _post("think", "thinking ...")
            try:
                cmd_reply = handle_command(state.message) if state.message.lstrip().startswith("!") else None
                reply = cmd_reply if cmd_reply is not None else session.ask(question, config.load().get("model"))
            except Exception as exc:  # noqa: BLE001 - tell the player, keep running
                from . import login
                reply = login.explain(exc)
            print(f"< {reply}", flush=True)
            try:
                deliver(state, reply)
            except Exception as exc:  # noqa: BLE001 - report, keep running
                print(f"delivery failed: {exc}", flush=True)
        time.sleep(poll)
