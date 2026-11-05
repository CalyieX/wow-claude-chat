"""Settings in ~/.wowclaude/ and automatic detection of the game folder."""
from __future__ import annotations

import json
import os
import string
from pathlib import Path

HOME = Path.home() / ".wowclaude"
CONFIG = HOME / "config.json"
PERSONA = HOME / "persona.txt"
SESSION = HOME / "session.txt"

FLAVOURS = ("_forever_", "_classic_era_", "_classic_", "_anniversary_")


def load() -> dict:
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(cfg: dict) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def _is_client(p: Path) -> bool:
    return (p / "Interface" / "AddOns").is_dir() and (p / "Wow.exe").exists()


def find_clients() -> list[Path]:
    """All game client folders found in the usual places (every drive)."""
    found: list[Path] = []
    bases: list[Path] = []
    for drive in string.ascii_uppercase:
        root = Path(f"{drive}:/")
        if not root.exists():
            continue
        for rel in ("World of Warcraft", "Program Files (x86)/World of Warcraft",
                    "Program Files/World of Warcraft", "Games/World of Warcraft", "Blizzard/World of Warcraft"):
            bases.append(root / rel)
    for base in bases:
        for flavour in FLAVOURS:
            cand = base / flavour
            if _is_client(cand) and cand not in found:
                found.append(cand)
    return found


def client_root(explicit: str | os.PathLike | None = None) -> Path | None:
    """Explicit path > WOWCLAUDE_ROOT > saved config > first client found."""
    for cand in (explicit, os.environ.get("WOWCLAUDE_ROOT"), load().get("wow_root")):
        if cand and _is_client(Path(cand)):
            return Path(cand)
    clients = find_clients()
    return clients[0] if clients else None
