"""Put the KKMap addon into the game folder (and take it out again).

There is nothing else to install: answers come back through the overlay program (chat_fake), not through the game.
Older versions also created 300 "reply slot" addons (KKR001..KKR300) and silent sound markers; install() removes them.
"""
from __future__ import annotations

import glob
import re
import shutil
from pathlib import Path

ADDON_SRC = Path(__file__).parent / "addon" / "KKMap"
FILES = ("KKMap.lua", "KKMap.toc", "Name.lua")
_OLD_SLOT = re.compile(r"\s*KKR\d{3}\s*:")


def _addons(root: Path) -> Path:
    return root / "Interface" / "AddOns"


def _account_lists(root: Path) -> list[Path]:
    return [Path(p) for p in glob.glob(str(root / "WTF" / "Account" / "*" / "*" / "*" / "AddOns.txt"))]


def write_name(root: Path, name: str) -> None:
    """The name the AI writes with: the addon reads Name.lua when the game (re)loads."""
    from . import claude
    clean = claude.clean_name(name) or claude.DEFAULT_NAME
    folder = _addons(root) / "KKMap"
    if folder.is_dir():
        (folder / "Name.lua").write_text('KKAiName = "' + clean.replace("\\", "").replace('"', "") + '"\n', encoding="utf-8")


def remove_old_slots(root: Path) -> int:
    """Delete the reply-slot addons and sound markers of earlier versions. Returns how many folders went."""
    addons = _addons(root)
    removed = 0
    for folder in addons.glob("KKR[0-9][0-9][0-9]"):
        if folder.is_dir():
            shutil.rmtree(folder, ignore_errors=True)
            removed += 1
    for old in ("sig", "img"):
        shutil.rmtree(addons / "KKMap" / old, ignore_errors=True)
    for p in _account_lists(root):
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        keep = [ln for ln in lines if not _OLD_SLOT.match(ln)]
        if len(keep) != len(lines):
            p.write_text("\n".join(keep) + "\n", encoding="utf-8")
    return removed


def install(root: Path, name: str = "") -> dict:
    """Copy the addon (three small files). Safe to run again; keeps an existing tab name."""
    addons = _addons(root)
    if not addons.is_dir():
        raise FileNotFoundError(f"not a game client folder: {root}")
    target = addons / "KKMap"
    target.mkdir(exist_ok=True)
    keep_name = (target / "Name.lua").read_text(encoding="utf-8") if (target / "Name.lua").exists() else None
    for f in FILES:
        shutil.copyfile(ADDON_SRC / f, target / f)
    if keep_name:
        (target / "Name.lua").write_text(keep_name, encoding="utf-8")
    if name:
        write_name(root, name)
    return {"old_slots_removed": remove_old_slots(root)}


def uninstall(root: Path) -> dict:
    """Remove the addon (and any leftover reply slots) from a game folder."""
    removed = remove_old_slots(root)
    if (_addons(root) / "KKMap").is_dir():
        shutil.rmtree(_addons(root) / "KKMap", ignore_errors=True)
        removed += 1
    cleaned = 0
    for p in _account_lists(root):
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        keep = [ln for ln in lines if not re.match(r"\s*KKMap\s*:", ln)]
        if len(keep) != len(lines):
            p.write_text("\n".join(keep) + "\n", encoding="utf-8")
            cleaned += 1
    return {"folders_removed": removed, "character_files_cleaned": cleaned}
