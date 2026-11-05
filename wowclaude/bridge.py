"""Main loop: read the player's message from the strip, ask Claude, deliver the reply through the slots."""
from __future__ import annotations

import time
from pathlib import Path

from . import claude, config, decode, screen, slots


def read_state() -> decode.GameState | None:
    img = screen.grab_strip_area()
    return decode.decode(img) if img is not None else None


def handle_command(text: str) -> str | None:
    """In-game slash commands that the addon sends as "!name args" (never forwarded to the AI)."""
    parts = text.strip().split(None, 1)
    cmd, arg = parts[0].lower(), (parts[1].strip() if len(parts) > 1 else "")
    if cmd == "!browser":
        from . import overlay
        overlay.play("off" if arg in ("off", "close") else arg)
        return "Browser closed." if arg in ("off", "close") else "Browser opened."
    if cmd == "!setup":
        from . import overlay, setup_ui
        overlay.play(setup_ui.start_background(), "640x520")
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
    slots.publish(root, state.message_seq, state.message_idx or 1, parts, overlay, macros)
    deadline = time.time() + 15
    while time.time() < deadline:
        time.sleep(0.5)
        fresh = read_state()
        if fresh is not None and fresh.ack_seq == state.message_seq:
            return True
    return False


def run(root: Path, poll: float = 0.6) -> None:
    session = claude.Session()
    model = config.load().get("model")
    last_seq: int | None = None
    print(f"wowclaude is running (game folder: {root}). Press Ctrl+C to stop.", flush=True)
    while True:
        if not screen.game_running():
            last_seq = None  # new game start: never answer an old message
            time.sleep(3)
            continue
        state = read_state()
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
                reply = cmd_reply if cmd_reply is not None else session.ask(question, model)
            except Exception as exc:  # noqa: BLE001 - tell the player, keep running
                reply = f"Error: {exc}"
            print(f"< {reply}", flush=True)
            if not deliver(root, state, reply):
                print("no confirmation from the game (is the addon loaded? try /reload in the game)", flush=True)
        time.sleep(poll)
