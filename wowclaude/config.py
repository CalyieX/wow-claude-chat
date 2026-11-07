"""Settings in ~/.wowclaude/ and automatic detection of the game folder."""
from __future__ import annotations

import json
import time
import os
import string
from pathlib import Path

HOME = Path.home() / ".wowclaude"
CONFIG = HOME / "config.json"
PERSONA = HOME / "persona.txt"
HARNESS = HOME / "harness.txt"  # optional: replaces the built-in instructions (edited on the AI setup page)
SESSION = HOME / "session.txt"

FLAVOURS = ("_forever_", "_classic_era_", "_classic_", "_anniversary_")


def load() -> dict:
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def model_for(backend: str) -> str | None:
    """The model chosen for this AI (Own AI tab), else the general one from the AI Setup page, else None = the AI's default."""
    c = load()
    return (c.get("models") or {}).get(backend) or c.get("model") or None


def ai_loaded() -> bool:
    """False after "Unload" in the AI setup: nothing answers until an AI is loaded again."""
    return not load().get("ai_off")


LAST_ANSWER = HOME / "last_answer.json"


def record_answer(ok: bool, seconds: float, error: str = "") -> None:
    """The result of the last real question to the AI (chat, CLI start or Test now): the setup window shows it live."""
    try:
        from . import backends, harness_import
        cfg = load()
        b = backends.name()
        rec = {"t": time.time(), "ok": bool(ok), "seconds": round(float(seconds), 1), "backend": b,
               "model": harness_import.model_of(b, cfg), "error": str(error)[:160]}
        HOME.mkdir(parents=True, exist_ok=True)
        LAST_ANSWER.write_text(json.dumps(rec), encoding="utf-8")
    except Exception:  # noqa: BLE001 - a status file must never break an answer
        pass


def last_answer() -> dict:
    try:
        return json.loads(LAST_ANSWER.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(cfg: dict) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    if cfg.get("api_key"):
        _private(CONFIG)


def _private(path: Path) -> None:
    """The API key sits in this file: make it readable by this user only (best effort)."""
    try:
        if os.name == "nt":
            import subprocess
            subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", os.environ.get("USERNAME", "") + ":F"],
                           capture_output=True, timeout=10, creationflags=0x08000000)
        else:
            path.chmod(0o600)
    except (OSError, ValueError, Exception):  # noqa: BLE001 - never fail a save over permissions
        pass


def _is_client(p: Path) -> bool:
    return (p / "Interface" / "AddOns").is_dir() and any(p.glob("Wow*.exe"))


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
