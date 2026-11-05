"""Local setup page for the AI behind the chat: backend, model, API key, persona. Opens in the WoW browser overlay.

Runs a tiny web server on 127.0.0.1 only (random port, one-time token in the URL). Nothing leaves your computer
except what the chosen backend itself sends. API keys you type here are stored in ~/.wowclaude/config.json.
"""
from __future__ import annotations

import json
import secrets
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import backends, claude, config

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>WoW Browser - AI setup</title>
<style>
body{background:#0c0b09;color:#e8d9a8;font:14px/1.4 Georgia,serif;margin:0;padding:18px;max-width:640px}
h1{color:#ffd100;font-size:20px;margin:0 0 12px;font-weight:normal;border-bottom:1px solid #5a4a28;padding-bottom:6px}
label{display:block;margin:12px 0 3px;color:#b9a064}
input,select,textarea{width:100%;box-sizing:border-box;background:#15130e;color:#ffd100;border:1px solid #5c5c5c;
 padding:6px;font:13px Arial,sans-serif;border-radius:2px}
textarea{height:110px}
button{margin-top:16px;background:#5c1a10;color:#ffd100;border:1px solid #c9a227;padding:8px 18px;font:14px Georgia,serif;
 cursor:pointer;border-radius:3px}
button:hover{background:#7d2417}
#msg{margin-top:12px;min-height:20px}.ok{color:#7fd17f}.bad{color:#ff8a80}
small{color:#8c7b4d;display:block;margin-top:2px}
</style></head><body>
<h1>AI setup</h1>
<label>Backend</label><select id="backend"></select>
<small id="hint"></small>
<div id="modelrow"><label>Model (empty = default)</label><input id="model"></div>
<div id="baserow"><label>API address (OpenAI-compatible)</label><input id="base_url"></div>
<div id="keyrow"><label>API key <span id="keystate"></span></label><input id="api_key" type="password" autocomplete="off"
 placeholder="leave empty to keep the saved key"><small>Stored only in ~/.wowclaude/config.json on this computer.</small></div>
<div id="cmdrow"><label>Command (reads the prompt on stdin)</label><input id="command" placeholder="ollama run llama3.1"></div>
<label>Persona (first line = name shown before answers, the rest is added to the instructions)</label>
<textarea id="persona"></textarea>
<button id="save">Save and test</button><div id="msg"></div>
<script>
const T=new URLSearchParams(location.search).get("t");
const $=id=>document.getElementById(id);
const HINTS={claude:"Uses the Claude Code you are logged into (no API key).",codex:"Uses the Codex CLI you are logged into (ChatGPT login).",
 command:"Any local command, e.g. ollama run llama3.1.","openai-compatible":"Any OpenAI-style API: set address, key and model."};
async function api(path,body){const r=await fetch(path+"?t="+T,{method:body?"POST":"GET",body:body?JSON.stringify(body):undefined});return r.json()}
function show(){const b=$("backend").value,isApi=!["claude","codex","command"].includes(b);
 $("hint").textContent=HINTS[b]||"OpenAI-compatible API ("+b+"). Local servers (ollama, lmstudio) need no key.";
 $("modelrow").style.display=(b==="claude"||b==="command")?"none":"block";$("baserow").style.display=b==="openai-compatible"?"block":"none";
 $("keyrow").style.display=isApi?"block":"none";$("cmdrow").style.display=b==="command"?"block":"none"}
(async()=>{const s=await api("/state");const sel=$("backend");
 for(const b of s.backends){const o=document.createElement("option");o.value=o.textContent=b;sel.appendChild(o)}
 sel.value=s.backend;$("model").value=s.model||"";$("base_url").value=s.base_url||"";$("command").value=s.command||"";
 $("persona").value=s.persona||"";$("keystate").textContent=s.has_key?"(saved)":"";show();sel.onchange=show;
 recheck()})();
async function recheck(){$("msg").textContent="Checking the AI ...";$("msg").className="";
 try{const r=await api("/check");$("msg").textContent=r.status;$("msg").className=r.ok?"ok":"bad"}catch(e){$("msg").textContent="Check failed: "+e;$("msg").className="bad"}}
$("save").onclick=async()=>{$("msg").textContent="Saving ...";$("msg").className="";
 const r=await api("/save",{backend:$("backend").value,model:$("model").value,base_url:$("base_url").value,
  api_key:$("api_key").value,command:$("command").value,persona:$("persona").value});
 $("msg").textContent=r.status;$("msg").className=r.ok?"ok":"bad";if(r.has_key)$("keystate").textContent="(saved)";$("api_key").value="";await recheck()};
</script></body></html>"""


def _state() -> dict:
    cfg = config.load()
    prefix, rest = "", ""
    try:
        lines = config.PERSONA.read_text(encoding="utf-8").splitlines()
        prefix, rest = (lines[0] if lines else ""), "\n".join(lines[1:])
    except OSError:
        pass
    return {"backends": ["claude", "codex", "command", "openai-compatible", *backends.PRESETS],
            "backend": backends.name(), "model": cfg.get("model", ""), "base_url": cfg.get("base_url", ""),
            "command": cfg.get("command", ""), "has_key": bool(cfg.get("api_key")),
            "persona": (prefix + "\n" + rest).strip("\n") if prefix else rest}


def _check() -> dict:
    """Slow (Claude Code answers a real question): the page asks separately, after it has loaded."""
    ok, status = claude.check_login() if backends.name() == "claude" else backends.check()
    return {"ok": ok, "status": status}


def apply(data: dict) -> dict:
    """Write the settings from the page into config.json / persona.txt and report whether the backend is usable."""
    cfg = config.load()
    backend = str(data.get("backend", "claude")).strip().lower()
    if backend not in ["claude", "codex", "command", "openai-compatible", *backends.PRESETS]:
        return {"ok": False, "status": f"Unknown backend: {backend}"}
    cfg["backend"] = backend
    for k in ("model", "base_url", "command"):
        v = str(data.get(k, "")).strip()
        if v:
            cfg[k] = v
        else:
            cfg.pop(k, None)
    key = str(data.get("api_key", "")).strip()
    if key:
        cfg["api_key"] = key
    config.save(cfg)
    persona = str(data.get("persona", "")).strip("\n")
    config.HOME.mkdir(parents=True, exist_ok=True)
    if persona:
        config.PERSONA.write_text(persona + "\n", encoding="utf-8")
    elif config.PERSONA.exists():
        config.PERSONA.unlink()
    return {"ok": True, "status": "Saved. Checking ...", "has_key": bool(cfg.get("api_key"))}


_running: dict = {}


def start_background() -> str:
    """Start the setup page server inside this process (once) and return its URL (with the one-time token)."""
    if "url" in _running:
        return _running["url"]
    token = secrets.token_urlsafe(16)
    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        port = sk.getsockname()[1]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002 - quiet
            pass

        def _ok(self) -> bool:
            q = parse_qs(urlparse(self.path).query)
            return self.headers.get("Host", "").split(":")[0] in ("127.0.0.1", "localhost") and q.get("t") == [token]

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self._ok():
                return self._send(403, b"forbidden", "text/plain")
            if urlparse(self.path).path == "/check":
                return self._send(200, json.dumps(_check()).encode(), "application/json")
            if urlparse(self.path).path == "/state":
                return self._send(200, json.dumps(_state()).encode(), "application/json")
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")

        def do_POST(self):
            if not self._ok() or urlparse(self.path).path != "/save":
                return self._send(403, b"forbidden", "text/plain")
            n = int(self.headers.get("Content-Length", "0") or 0)
            try:
                out = apply(json.loads(self.rfile.read(min(n, 100000)).decode("utf-8")))
            except (ValueError, OSError) as exc:
                out = {"ok": False, "status": f"Could not save: {exc}"}
            self._send(200, json.dumps(out).encode(), "application/json")

    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _running["url"] = f"http://127.0.0.1:{port}/?t={token}"
    return _running["url"]


def serve() -> int:
    """`wowclaude config`: run the page and open it in the WoW browser overlay."""
    url = start_background()
    print(f"AI setup page: {url}  (Ctrl+C to stop)", flush=True)
    subprocess.Popen([sys.executable, "-m", "wowclaude", "overlay", url, "--size", "640x520"],
                     creationflags=0x08000000 if sys.platform == "win32" else 0)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    return 0
