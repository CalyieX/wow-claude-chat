"""WoW AI memos: a small memory about the player: short facts the AI saves itself, one file per character plus one for all characters.

Files live in ~/.wowclaude/memos/ (plain text, one fact per line, you can read and edit them). The AI writes with
[[remember a fact]] (this character) or [[remember all: a fact]] (every character) and removes with [[forget text]].
The saved facts go in front of every question. Nothing from the player's own Claude files is used here.
"""
from __future__ import annotations

import re

from . import config

DIR = config.HOME / "memos"
MAX_LINES = 30
MAX_LINE = 200
ACTION_RE = re.compile(r"\[\[(remember|forget)(?: ([^\]\n]{1,300}))?\]\]")
SAFE = re.compile(r"[^A-Za-z0-9_-]")
SECRET = re.compile(r"password|passwort|kennwort|token|api[ _-]?key|sk-[a-z]{2,}-", re.I)


def character(context: str) -> str:
    """The character name: the first field of the game state line ('Name | Level 10 | ...')."""
    name = SAFE.sub("", (context or "").split("|")[0].strip().replace(" ", "_"))[:24]
    return name or "general"


def _path(char: str):
    return DIR / f"{char}.md"


def read(char: str) -> list[str]:
    try:
        return [ln.strip() for ln in _path(char).read_text(encoding="utf-8").splitlines() if ln.strip()]
    except OSError:
        return []


def _write(char: str, lines: list[str]) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    _path(char).write_text("\n".join(lines[-MAX_LINES:]) + ("\n" if lines else ""), encoding="utf-8")


def remember(char: str, text: str) -> bool:
    text = " ".join(str(text).split())[:MAX_LINE]
    if not text or SECRET.search(text):  # secrets never go into a file
        return False
    lines = read(char)
    if text.lower() in (x.lower() for x in lines):
        return True
    _write(char, lines + [text])
    return True


def forget(char: str, text: str) -> int:
    key = " ".join(str(text).split()).lower()
    lines = read(char)
    keep = [x for x in lines if key not in x.lower()]
    if len(keep) != len(lines):
        _write(char, keep)
    return len(lines) - len(keep)


def clear(char: str) -> None:
    try:
        _path(char).unlink()
    except OSError:
        pass


def prompt_block(context: str) -> str:
    """The saved facts as a block in front of the question (empty when nothing is saved)."""
    char = character(context)
    parts = []
    general = read("general")
    if general:
        parts.append("All characters: " + "; ".join(general))
    if char != "general":
        mine = read(char)
        if mine:
            parts.append(f"{char}: " + "; ".join(mine))
    if not parts:
        return ""
    return "[WoW AI memos about this player (saved earlier by you): " + " | ".join(parts) + "]\n"


def extract(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Split [[remember ...]] / [[forget ...]] out of a reply (at most 5 actions)."""
    acts = [(m.group(1), (m.group(2) or "").strip()) for m in ACTION_RE.finditer(text)]
    return ACTION_RE.sub("", text).strip(), acts[:5]


def apply(context: str, acts: list[tuple[str, str]]) -> list[str]:
    """Carry out the actions; returns short notes for the chat."""
    char, notes = character(context), []
    for action, text in acts:
        target = char
        if text.lower().startswith("all:"):
            target, text = "general", text[4:].strip()
        if action == "remember":
            if remember(target, text):
                notes.append("saved to WoW AI memos")
        elif forget(target, text):
            notes.append("removed from WoW AI memos")
    return notes


def show(context: str) -> str:
    """For the player: what is saved (command /memos)."""
    char = character(context)
    lines = [f"All: {x}" for x in read("general")] + ([f"{char}: {x}" for x in read(char)] if char != "general" else [])
    return "WoW AI memos: " + (" | ".join(lines) if lines else "nothing saved yet. Tell the AI to remember something.") + \
        "  (/memos clear deletes them)"
