"""Harness import: take the player's OWN AI setup (instructions, memory, skills) into the WoW AI harness.

Sources are found in the normal folders of the AI programs - nothing is configured by hand:
  Claude Code   CLAUDE.md, the memory folder of the home folder (MEMORY.md + files), skills/*/SKILL.md
  Codex         AGENTS.md, MEMORY.md, skills (~/.agents/skills or ~/.codex/skills)

What goes into the text (a harness is sent with every question, so it has a size budget):
  1. the instructions file (persona, rules)                          - whole, up to INSTR_MAX
  2. the memory index (MEMORY.md)                                    - up to INDEX_MAX, plus the folder to read the rest from
  3. the skill list (name + one line + path)                         - up to SKILLS_MAX
Memory files and skills themselves are NOT copied: the AI reads them with its file tools when "AI access" is on, like in its
own program. Hooks, subagents and plugins belong to the program and are not imported.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

INSTR_MAX = 40_000
INDEX_MAX = 16_000
SKILLS_MAX = 10_000
MARK = "--- WoW part (game, tools) ---"


@dataclass
class Source:
    kind: str  # "claude" | "codex"
    label: str
    instructions_file: Path | None = None
    memory_index: Path | None = None
    memory_dir: Path | None = None
    skills: list[tuple[str, str, Path]] = field(default_factory=list)  # (name, one line, SKILL.md)

    def found(self) -> bool:
        return bool(self.instructions_file or self.memory_index or self.skills)


def _read(path: Path | None) -> str:
    if not path:
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return ""


def _skill_line(path: Path) -> tuple[str, str]:
    """(name, description) from the front matter of a SKILL.md; name falls back to the folder name."""
    text = _read(path)
    name, desc = path.parent.name, ""
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            key, _, val = line.partition(":")
            if key.strip() == "name" and val.strip():
                name = val.strip().strip("\"'")
            elif key.strip() == "description" and val.strip():
                desc = val.strip().strip("\"'>|")
    return name, " ".join(desc.split())[:140]


def _skills(folder: Path) -> list[tuple[str, str, Path]]:
    out = []
    try:
        for sub in sorted(folder.iterdir()):
            f = sub / "SKILL.md"
            if f.is_file():
                n, d = _skill_line(f)
                out.append((n, d, f))
    except OSError:
        pass
    return out


def claude_source(home: Path | None = None) -> Source:
    home = home or Path.home()
    cfg = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (home / ".claude"))
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(home))  # Claude Code names the memory folder of a working folder like this
    mem = cfg / "projects" / slug / "memory"
    src = Source("claude", "Claude Code")
    if (cfg / "CLAUDE.md").is_file():
        src.instructions_file = cfg / "CLAUDE.md"
    if (mem / "MEMORY.md").is_file():
        src.memory_index, src.memory_dir = mem / "MEMORY.md", mem
    src.skills = _skills(cfg / "skills")
    return src


def codex_source(home: Path | None = None) -> Source:
    home = home or Path.home()
    cfg = Path(os.environ.get("CODEX_HOME") or (home / ".codex"))
    src = Source("codex", "Codex")
    if (cfg / "AGENTS.md").is_file():
        src.instructions_file = cfg / "AGENTS.md"
    if (cfg / "MEMORY.md").is_file():
        src.memory_index, src.memory_dir = cfg / "MEMORY.md", cfg
    for folder in (home / ".agents" / "skills", cfg / "skills"):
        src.skills += [s for s in _skills(folder) if s[0] not in {x[0] for x in src.skills}]
    return src


def sources(home: Path | None = None) -> list[Source]:
    """The setups found on this computer (only those with something in them)."""
    return [s for s in (claude_source(home), codex_source(home)) if s.found()]


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rsplit("\n", 1)[0] + "\n[... cut: too long for the harness]"


def render(src: Source, game_part: str) -> str:
    """The harness text: the player's own part first, then the game part (so the AI still knows the game and its tools)."""
    parts = []
    instr = _read(src.instructions_file)
    if instr:
        parts.append(_cut(instr, INSTR_MAX))
    index = _read(src.memory_index)
    if index:
        block = "--- Your own memory (index) ---\n" + _cut(index, INDEX_MAX)
        if src.memory_dir:
            block += f"\nThe memory files are in: {src.memory_dir}\nRead the ones you need with your file tools (when AI access is on)."
        parts.append(block)
    if src.skills:
        lines, size = [], 0
        for name, desc, path in src.skills:
            line = f"- {name}: {desc} ({path})" if desc else f"- {name} ({path})"
            if size + len(line) > SKILLS_MAX:
                lines.append(f"[... {len(src.skills) - len(lines)} more skills]")
                break
            lines.append(line)
            size += len(line) + 1
        parts.append("--- Your own skills (read the SKILL.md when one fits) ---\n" + "\n".join(lines))
    return "\n\n".join(parts + [MARK, game_part]) if parts else game_part


def summary(src: Source) -> str:
    """One line for the editor: what was found."""
    bits = []
    if src.instructions_file:
        bits.append(f"instructions ({len(_read(src.instructions_file)) // 1000} KB)")
    if src.memory_index:
        bits.append("memory index")
    if src.skills:
        bits.append(f"{len(src.skills)} skills")
    return f"{src.label}: " + (", ".join(bits) or "nothing found")
