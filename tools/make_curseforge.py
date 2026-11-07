"""Build the CurseForge upload: dist/KKMap-<version>.zip with one top-level KKMap folder (no Name.lua override of users)."""
import re
import sys
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parent.parent
src = root / "wowclaude" / "addon" / "KKMap"
toc = (src / "KKMap.toc").read_text(encoding="utf-8")
ver = re.search(r"## Version:\s*(\S+)", toc).group(1)
out = root / "dist" / f"KKMap-{ver}.zip"
out.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for f in ("KKMap.toc", "Name.lua", "State.lua", "KKMap.lua"):  # every file the .toc lists
        z.write(src / f, f"KKMap/{f}")
    z.write(root / "LICENSE", "KKMap/LICENSE")
print(out)
