"""Main loop: read the player's message from the strip, ask Claude, deliver the reply through the slots."""
from __future__ import annotations

import time
from pathlib import Path

from . import claude, config, decode, screen, slots


def read_state() -> decode.GameState | None:
    img = screen.grab_strip_area()
    return decode.decode(img) if img is not None else None


def _safe_read_state() -> decode.GameState | None:
    try:
        return read_state()
    except Exception as exc:  # noqa: BLE001 - a failed screenshot must never end the bridge
        print(f"screen read failed: {exc}", flush=True)
        return None


def handle_command(text: str) -> str | None:
    """In-game slash commands that the addon sends as "!name args" (never forwarded to the AI)."""
    parts = text.strip().split(None, 1)
    cmd, arg = parts[0].lower(), (parts[1].strip() if len(parts) > 1 else "")
    if cmd == "!browser":
        from . import overlay
        closing = arg in ("off", "close")
        problem = overlay.play("off" if closing else arg)
        if problem:
            return "Browser did not open: " + problem
        return "Browser closed." if closing else "Browser opened."
    if cmd == "!setup":
        from . import overlay, setup_ui
        url = setup_ui.start_background()
        problem = overlay.play(url, "640x520")
        if problem:
            return f"Could not open the window ({problem}). Open this address in any browser: {url}"
        return "AI setup opened in the browser window."
    return None


def deliver(root: Path, state: decode.GameState, reply: str) -> bool:
    reply, macros = claude.extract_macros(reply)
    reply, overlay = claude.extract_overlay(reply)
    reply, play = claude.extract_play(reply)
    from . import vinput
    reply, acts = vinput.extract(reply) if vinput.available() else (reply, [])
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
    if overlay:
        try:
            overlay["lines"] = slots.resolve_images(root, overlay["lines"], state.image_next)
        except Exception as exc:  # noqa: BLE001 - never lose the text because of a picture
            print(f"images failed: {exc}", flush=True)
    parts = claude.split_reply(reply or "...")
    parts[0] = claude.persona()[0] + ": " + parts[0]
    slot_next = state.slot_next
    for attempt in range(3):  # no confirmation: the addon may have been reloaded, so look at its slot counter again
        try:
            slots.publish(root, state.message_seq, state.message_idx or 1, parts, overlay, macros, slot_next)
        except OSError as exc:  # game or a scanner holds a file: wait a moment, try again
            print(f"could not write the reply ({exc}), retrying ...", flush=True)
            time.sleep(1.0)
            continue
        deadline = time.time() + 15
        while time.time() < deadline:
            time.sleep(0.5)
            fresh = _safe_read_state()
            if fresh is not None:
                if fresh.ack_seq == state.message_seq:
                    slots.reset_marker(root, state.message_idx or 1)  # silent again, so it cannot burn slots later
                    return True
                if fresh.message_seq > state.message_seq:
                    slots.reset_marker(root, state.message_idx or 1)  # the addon drops this answer anyway: keep it quiet
                    return True  # the player already wrote the next message: the answer is out, do not block the loop
                slot_next = fresh.slot_next
    slots.reset_marker(root, state.message_idx or 1)  # never confirmed: keep it from burning slots later
    return False


LOCK_PORT = 47831
_lock_socket = None


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
    session = claude.Session()
    last_seq: int | None = None
    print(f"wowclaude is running (game folder: {root}). Press Ctrl+C to stop.", flush=True)
    while True:
        if not screen.game_running():
            last_seq = None  # new game start: never answer an old message
            time.sleep(3)
            continue
        state = _safe_read_state()
        if state is None:
            time.sleep(poll)
            continue
        if last_seq is None:
            last_seq = state.message_seq
        elif state.message_seq != last_seq and state.message.strip():
            last_seq = state.message_seq
            question = state.message.strip()
            if state.context:
                question = "[Game state: " + state.context + "]\n" + question
            from . import vinput
            if vinput.available() and state.frames:
                question = vinput.frames_hint(state.frames) + question
            print(f"> {state.message.strip()}", flush=True)
            slots.reset_marker(root, state.message_idx or 1)
            try:
                cmd_reply = handle_command(state.message) if state.message.lstrip().startswith("!") else None
                reply = cmd_reply if cmd_reply is not None else session.ask(question, config.load().get("model"))
            except Exception as exc:  # noqa: BLE001 - tell the player, keep running
                reply = f"No answer from the AI: {exc}. No AI set up yet? Type /wac and press AI Setup."
            print(f"< {reply}", flush=True)
            try:
                delivered = deliver(root, state, reply)
            except Exception as exc:  # noqa: BLE001 - report, keep running
                print(f"delivery failed: {exc}", flush=True)
                delivered = False
            if not delivered:
                print("no confirmation from the game (is the addon loaded? try /reload in the game)", flush=True)
        time.sleep(poll)
