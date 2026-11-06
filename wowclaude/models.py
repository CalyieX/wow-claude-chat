"""Which models the loaded AI can use right now - always read live from the AI itself, never a list kept in this program.

  Claude Code   the aliases sonnet / opus / haiku (always the newest of each), plus the extra models the account unlocked
                (Claude Code keeps them in its own .claude.json cache, refreshed by Claude Code)
  Codex         the model cache of the account (~/.codex/models_cache.json, refreshed by Codex from the server)
  API / Ollama  the /models endpoint of the provider (needs the key / the local program running)
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from . import backends, config


def _json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def claude_models(home: Path | None = None) -> list[tuple[str, str]]:
    home = home or Path.home()
    out = [("sonnet", "Sonnet - the newest Sonnet"), ("opus", "Opus - the newest Opus"), ("haiku", "Haiku - the newest, fastest and cheapest")]
    cfg_dir = Path(config.load().get("own_config_dir") or os.environ.get("CLAUDE_CONFIG_DIR") or home)
    for f in (cfg_dir / ".claude.json", home / ".claude.json"):
        data = _json(f)
        if isinstance(data, dict):
            for m in data.get("additionalModelOptionsCache") or []:
                if isinstance(m, dict) and m.get("value"):
                    out.append((str(m["value"]), f'{m.get("label", m["value"])} - {m.get("description", "")}'.strip(" -")))
            break
    return out


_ROW = re.compile(r"^\s*[>\u203a\u276f]?\s*(\d+)\.\s+(.+?)(?:\s{2,}(.*))?$")
_MARKS = "\u221a\u2714\u2713"


def parse_claude_picker(lines: list[str]) -> list[tuple[str, str, bool]]:
    """The rows of Claude Code's /model dialog: (name, description, is_current). name is as shown ("Sonnet", "Fable", ...)."""
    rows, inside = [], False
    for line in lines:
        if "Select model" in line:
            inside = True
            continue
        if not inside:
            continue
        if "Enter to" in line or "Esc to" in line:
            break
        m = _ROW.match(line.rstrip())
        if m:
            name = m.group(2).strip()
            cur = any(c in name for c in _MARKS)
            name = re.sub(r"\s*[" + _MARKS + r"]\s*$", "", name).strip()
            rows.append((name, (m.group(3) or "").strip(), cur))
    return rows


def claude_cli_models(timeout: float = 45.0) -> list[tuple[str, str]]:
    """The list exactly as Claude Code shows it in /model (concrete versions, what the account really has): the CLI is
    started hidden, /model typed, the dialog read from its screen. [] when that is not possible (no pywinpty/pyte, not logged in)."""
    try:
        import threading
        import time

        import pyte
        import winpty
    except ImportError:
        return []
    from . import claude
    exe = claude.claude_path()
    if not exe:
        return []
    screen = pyte.Screen(140, 45)
    stream = pyte.Stream(screen)
    try:
        proc = winpty.PtyProcess.spawn([exe], dimensions=(45, 140), cwd=str(Path.home()), env=claude._clean_env("wow"))
    except Exception:  # noqa: BLE001
        return []

    def reader() -> None:
        while True:
            try:
                data = proc.read(4096)
            except Exception:  # noqa: BLE001
                return
            if data:
                stream.feed(data)

    threading.Thread(target=reader, daemon=True).start()

    def text() -> list[str]:
        return [ln.rstrip() for ln in screen.display]

    def wait_for(needle: str, secs: float) -> bool:
        end = time.time() + secs
        while time.time() < end:
            if any(needle in ln for ln in text()):
                return True
            time.sleep(0.3)
        return False

    rows: list[tuple[str, str, bool]] = []
    try:
        end = time.time() + timeout / 2
        ready = False
        while time.time() < end:  # until the prompt is there; a one-time start dialog is answered with its safe default
            lines = text()
            if any("No, keep browser tools off" in ln for ln in lines):
                proc.write("\r")
                time.sleep(1.5)
            elif (any(ln.lstrip().startswith((">", "❯")) for ln in lines) and any(ln.startswith("──") for ln in lines)
                  and not any("Enter to" in ln or "Esc to" in ln for ln in lines)):
                ready = True  # the input prompt between its two rules, and no start dialog on screen
                time.sleep(1.5)
                break
            time.sleep(0.4)
        if ready:
            time.sleep(1.0)
            proc.write("/model")
            time.sleep(1.5)
            proc.write("\r")
            if not wait_for("Select model", 4):
                proc.write("\r")
            if wait_for("Esc to", timeout / 2):
                rows = parse_claude_picker(text())
    finally:
        try:
            proc.write("\x1b")
            time.sleep(0.3)
            proc.terminate(force=True)
        except Exception:  # noqa: BLE001
            pass
    known = {v.lower(): v for v, _ in claude_models()}
    out = []
    for name, desc, _cur in rows:
        low = name.lower().split()[0] if name else ""
        if low in ("default", "more"):
            continue  # "the AI's own default" has its own button; "More models" is not a model
        value = known.get(low) or next((v for v in known.values() if low in v.lower()), low)
        out.append((value, f"{name} - {desc}" if desc else name))
    return out


def codex_models(home: Path | None = None) -> list[tuple[str, str]]:
    home = home or Path.home()
    data = _json(Path(os.environ.get("CODEX_HOME") or (home / ".codex")) / "models_cache.json")
    models = [m for m in (data or {}).get("models", []) if isinstance(m, dict) and m.get("visibility", "list") == "list"]
    models.sort(key=lambda m: m.get("priority", 99))
    return [(str(m["slug"]), f'{m.get("display_name", m["slug"])}' + (f' - {m["description"]}' if m.get("description") else "")) for m in models]


def api_models() -> list[tuple[str, str]]:
    import urllib.request
    base, _model, key = backends._api_settings()
    req = urllib.request.Request(base + "/models", headers={"Authorization": f"Bearer {key}"} if key else {})
    with urllib.request.urlopen(req, timeout=8) as r:  # noqa: S310 - the provider the player configured
        data = json.loads(r.read().decode("utf-8"))
    ids = sorted(str(m.get("id")) for m in data.get("data", data if isinstance(data, list) else []) if isinstance(m, dict) and m.get("id"))
    return [(i, i) for i in ids]


def available(backend: str | None = None) -> tuple[list[tuple[str, str]], str]:
    """([(id, label)], note). The note says where the list came from or why it is empty."""
    b = backend or backends.name()
    try:
        if b == "claude":
            return claude_models(), "Claude Code: newest of each family plus what your account unlocked."
        if b == "codex":
            ms = codex_models()
            return ms, ("Codex: what your account can use (read from Codex itself)." if ms else "Codex has not loaded its model list yet: open Codex once.")
        if b in backends.PRESETS or b == "openai-compatible":
            ms = api_models()
            return ms, f"{b}: live from the provider."
    except Exception as exc:  # noqa: BLE001 - offline, bad key, program not running: say it, do not crash the popup
        return [], f"{b}: the list could not be read ({str(exc)[:80]})."
    return [], f"{b}: no model list available - type the name with /model <name>."
