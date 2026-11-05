"""Optional background input for the AI: qo-virtual-mouse (AutoHotkey UIAccess).

Clicks and keys are posted to the game window WITHOUT taking focus and without moving the player's cursor, so the
player is not interrupted. Only available when the qo-virtual-mouse skill is installed; otherwise the AI is told
nothing about it. Reply commands:  [[click X Y]]  [[click X Y R]]  [[keys TEXT]]   (X/Y = game client pixels)
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

AHK = r"C:\Program Files\AutoHotkey\v2\AutoHotkey64_UIA.exe"
TITLE = "World of Warcraft"
MAX_ACTIONS = 5
INPUT_RE = re.compile(r"\[\[(click \d{1,5} \d{1,5}(?: [LRM])?|keys [^\]\n]{1,80})\]\]")


def script() -> Path | None:
    cands = [os.environ.get("WOWCLAUDE_VMOUSE"),
             str(Path.home() / ".claude" / "skills" / "qo-virtual-mouse" / "scripts" / "vmouse.ps1")]
    for c in cands:
        if c and Path(c).exists() and Path(AHK).exists():
            return Path(c)
    return None


def available() -> bool:
    return script() is not None


def extract(text: str) -> tuple[str, list[str]]:
    """Split [[click ..]] / [[keys ..]] commands out of a reply (at most MAX_ACTIONS)."""
    cmds = [m.group(1) for m in INPUT_RE.finditer(text)][:MAX_ACTIONS]
    return INPUT_RE.sub("", text).strip(), cmds


def run(cmd: str) -> bool:
    sc = script()
    if sc is None:
        return False
    parts = cmd.split(" ", 1)
    if parts[0] == "click":
        a = parts[1].split()
        args = ["-Action", "click", "-Title", TITLE, "-X", a[0], "-Y", a[1]] + (["-Button", a[2]] if len(a) > 2 else [])
    else:
        args = ["-Action", "type", "-Title", TITLE, "-Text", parts[1]]
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(sc), *args],
                       capture_output=True, text=True, timeout=20, creationflags=0x08000000)
    return r.returncode == 0


SKILL = """
BACKGROUND INPUT (you have your own virtual mouse and keyboard; the player is not interrupted)
You can act in the game window without taking focus or moving the player's cursor:
[[click X Y]]   left click at game-window pixel X,Y (client coordinates; the frame list in the game state gives exact centres)
[[click X Y R]] right click        [[keys TEXT]]   send keys, AutoHotkey syntax, e.g. [[keys {Esc}]]
You decide when to use it. Use it only when the player asked for an action in the interface (open a window, click a
button) and no macro or answer is enough. At most 5 commands per reply, say in one sentence what you did, never click
blindly: if you do not know the exact position, say so instead. Protected combat actions (casting, targeting, movement)
cannot be triggered this way; make a macro for those.
"""
