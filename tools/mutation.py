import shutil, subprocess, sys, os, pathlib
"""Mutation testing: one small bug at a time is put into a copy of the repo; the test suite must then fail (KILLED).
Usage:  py -3 tools/mutation.py [M30 M31 ...]    (no argument = all mutants, about a minute each)
Optional: MW=<work directory> (default: a temp folder)."""
import tempfile
SRC = pathlib.Path(__file__).resolve().parent.parent
W = pathlib.Path(os.environ.get("MW") or os.path.join(tempfile.gettempdir(), "wowclaude-mutants"))
M = [
 ("M01 retry on every error", "wowclaude/claude.py", "if not (self.started and stale) or t_end - time.time() < 20:", "if not self.started or t_end - time.time() < 20:"),
 ("M02 drop 'already in use'", "wowclaude/claude.py", ' or "already in use" in low', ''),
 ("M03 drop 'session not found'", "wowclaude/claude.py", ' or "session not found" in low', ''),
 ("M04 no budget guard", "wowclaude/claude.py", "or t_end - time.time() < 20:", ":"),
 ("M05 no _new before retry", "wowclaude/claude.py", "                self._new()\n                return self._run(exe, prompt, model, t_end)", "                return self._run(exe, prompt, model, t_end)"),
 ("M06 no finally _new", "wowclaude/claude.py", "            if not self.started:\n                self._new()  #", "            if False:\n                self._new()  #"),
 ("M07 timeout msg fixed TIMEOUT", "wowclaude/claude.py", "within {round(timeout or TIMEOUT)} seconds", "within {TIMEOUT} seconds"),
 ("M08 retry floor 5s", "wowclaude/claude.py", "left = max(5.0, t_end - time.time())", "left = max(5.0, t_end - time.time())"),  # no-op control
 ("M09 expiry msg off", "wowclaude/claude.py", 'if "expired" in low or "log in" in low or "login" in low or "authenticate" in low:', 'if False:'),
 ("M10 login check wide 'session'", "wowclaude/claude.py", '"invalid session" in low', '"session" in low'),
 ("M11 marker not reset on next-msg", "wowclaude/bridge.py", "                    slots.reset_marker(root, state.message_idx or 1)  # the addon drops", "                    pass  # the addon drops"),
 ("M12 marker not reset on unconfirmed", "wowclaude/bridge.py", "    slots.reset_marker(root, state.message_idx or 1)  # never confirmed", "    pass  # never confirmed"),
 ("M13 no reset on ack", "wowclaude/bridge.py", "                    slots.reset_marker(root, state.message_idx or 1)  # silent again", "                    pass  # silent again"),
 ("M14 utf8cut plain", "wowclaude/addon/KKMap/KKMap.lua", "    clean = utf8cut(clean, 230)", "    clean = clean:sub(1, 230)"),
 ("M15 utf8cut no hint", "wowclaude/addon/KKMap/KKMap.lua", '    say(L("Hinweis: Nachricht auf 230 Bytes gekuerzt.", "Note: message shortened to 230 bytes."), 1, 0.8, 0.4, true)', ''),
 ("M16 utf8cut off-by-one (len check >=)", "wowclaude/addon/KKMap/KKMap.lua", "if i + len - 1 > n then return s:sub(1, i - 1) end", "if i + len - 1 > n + 1 then return s:sub(1, i - 1) end"),
 ("M17 command backend raw subprocess", "wowclaude/backends.py", "code, out, err = claude._exec(cmd, text)", "r = subprocess.run(cmd, input=text, capture_output=True, text=True, timeout=180); code, out, err = r.returncode, r.stdout, r.stderr"),
 ("M18 api timeout 180", "wowclaude/backends.py", "timeout=100", "timeout=180"),
 ("M19 codex via raw run", "wowclaude/backends.py", 'code, out, err = claude._exec(cmd + ["-"], text)', 'r = subprocess.run(cmd + ["-"], input=text, capture_output=True, text=True, timeout=180); code, out, err = r.returncode, r.stdout, r.stderr'),
 ("M20 check_login drop strict-mcp", "wowclaude/claude.py", '"--tools", "", "--strict-mcp-config",\n                                "--no-session-persistence"]', '"--tools", "",\n                                "--no-session-persistence"]'),
 ("M21 check_login ok even on empty", "wowclaude/claude.py", "if code == 0 and out:", "if code == 0:"),
 ("M22 doctor no sample", "wowclaude/__main__.py", "            img.save(sample)", "            pass"),
 ("M23 lua ack not sent (find)", "wowclaude/addon/KKMap/KKMap.lua", "ack", "ack"),  # control, skipped
 ("M24 exec no tree kill", "wowclaude/claude.py", 'subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)]', 'subprocess.run(["taskkill", "/F", "/PID", str(proc.pid)]'),
 ("M25 slots marker not written (publish)", "wowclaude/slots.py", "    tmp.write_bytes(_silent_wav())\n    os.replace(tmp, marker)", "    pass"),
 ("M26 split_reply no limit", "wowclaude/claude.py", "MAX_CHUNKS = 6", "MAX_CHUNKS = 60"),

 ("M30 burn: advance on empty slot", "wowclaude/addon/KKMap/KKMap.lua", "  if d == nil then  -- nothing", "  if false then  -- nothing"),
 ("M31 no backoff", "wowclaude/addon/KKMap/KKMap.lua", "math.min(4, 0.5 * 2 ^ math.min(misses, 3))", "0.5"),
 ("M32 misses never counted", "wowclaude/addon/KKMap/KKMap.lua", "    misses = misses + 1\n    return", "    return"),
 ("M33 restricted frames unguarded", "wowclaude/addon/KKMap/KKMap.lua", "usable = okm and vis and left and true or false", "usable = f:IsVisible() and f:GetLeft() and true or false"),
 ("M34 no neutral cwd", "wowclaude/claude.py", "cwd=neutral_cwd()", "cwd=str(config.HOME)"),
 ("M36 page not put above game", "wowclaude/overlay.py", "            user32.SetWindowPos(wintypes.HWND(game), wintypes.HWND(page), 0, 0, 0, 0, 0x13)", "            pass"),
 ("M35 no setting-sources", "wowclaude/claude.py", 'ISOLATION = ["--setting-sources", ""]', 'ISOLATION = []'),
]
only = sys.argv[1:]
for name, f, a, b in M:
    if only and not any(name.startswith(o) for o in only): continue
    if a == b: continue
    if W.exists(): shutil.rmtree(W)
    shutil.copytree(SRC, W, ignore=shutil.ignore_patterns(".git","build","__pycache__",".pytest_cache","*.egg-info"))
    p = W/f; t = p.read_text(encoding="utf-8")
    if a not in t: print(name, "PATTERN NOT FOUND"); continue
    p.write_text(t.replace(a,b,1), encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(W))
    r = subprocess.run([sys.executable,"-m","pytest","-q","-x","-p","no:cacheprovider","tests"], cwd=W, env=env, capture_output=True, text=True,
                       creationflags=0x08000000 if os.name == "nt" else 0)  # no console window popping up over the game
    tail = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-200:]
    print(name, "KILLED" if r.returncode else "SURVIVED", "|", tail, flush=True)
