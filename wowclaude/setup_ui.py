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
button.small{margin:3px 4px 0 0;padding:4px 10px;font-size:12px}
.card{display:block;width:100%;text-align:left;margin-top:8px}details{margin-top:14px}summary{cursor:pointer;color:#c9a227}
</style></head><body>
<h1>AI setup</h1>
<div id="found"></div>
<label>Other AIs (you need an account or key there)</label><div id="others"></div>
<details id="adv"><summary>Choose by hand / more options</summary>
<label>Backend</label><select id="backend"></select>
<small id="hint"></small>
<div id="modelrow"><label>Model (empty = default)</label><input id="model"></div>
<div id="baserow"><label>API address (OpenAI-compatible)</label><input id="base_url"></div>
<div id="keyrow"><label>API key <span id="keystate"></span></label><input id="api_key" type="password" autocomplete="off"
 placeholder="leave empty to keep the saved key"><small>Stored only in ~/.wowclaude/config.json on this computer.</small><small id="keylink"></small></div>
<div id="cmdrow"><label>Command (reads the prompt on stdin)</label><input id="command" placeholder="ollama run llama3.1"></div>
<label>Extra instructions (optional, e.g. how it should talk)</label>
<textarea id="persona"></textarea>
</details>
<details><summary>Computer access (your choice)</summary>
<small>Off by default: the AI can only search the web. When you switch it on, the AI (Claude Code / Codex login only) may read and change files and run commands on this computer when you ask it, like the original command line tool. The same switch is in the game menu (/wac, AI access).</small>
<label><input type="checkbox" id="access" style="width:auto"> Let the AI use this computer</label></details>
<details><summary>Mouse and keyboard (tool for the AI)</summary>
<small>Lets the AI click and type in the game window for you (open a window, press a button, fill a field) without using your own mouse. Combat actions stay protected by the game. Off by default.</small>
<label><input type="checkbox" id="inputctl" style="width:auto"> Allow the AI to use mouse and keyboard in the game</label></details>
<details><summary>Harness (what your AI is told)</summary>
<small>This is the text your AI receives before every question: game version, research rule, macros, browser window ... Edit it as you like; the AI reads it fresh each time. "Reset" goes back to the built-in version that comes with the program.</small>
<textarea id="harness" style="height:240px"></textarea>
<button id="hreset" type="button" class="small">Reset to built-in</button><small id="hstate"></small></details>
<details><summary>Let my own AI set this up</summary>
<small>Copy this text into an AI that can edit files on your PC (Claude Code, Codex ...). It writes the settings for you.</small>
<textarea id="aiprompt" readonly style="height:130px"></textarea><button id="copy" type="button">Copy</button></details>
<button id="save">Save and test</button><div id="msg"></div>
<script>
const T=new URLSearchParams(location.search).get("t");
const $=id=>document.getElementById(id);
const HINTS={claude:"Uses the Claude Code you are logged into (no API key).",codex:"Uses the Codex CLI you are logged into (ChatGPT login).",
 command:"Any local command, e.g. ollama run llama3.1.","openai-compatible":"Any OpenAI-style API: set address, key and model."};
async function api(path,body){const r=await fetch(path+"?t="+T,{method:body?"POST":"GET",body:body?JSON.stringify(body):undefined});return r.json()}
const KEYS={openrouter:"https://openrouter.ai/keys",openai:"https://platform.openai.com/api-keys",anthropic:"https://console.anthropic.com/settings/keys",
 gemini:"https://aistudio.google.com/apikey",groq:"https://console.groq.com/keys",deepseek:"https://platform.deepseek.com/api_keys",
 mistral:"https://console.mistral.ai/api-keys",xai:"https://console.x.ai",together:"https://api.together.ai/settings/api-keys",
 perplexity:"https://www.perplexity.ai/settings/api",cerebras:"https://cloud.cerebras.ai"};
function show(){const b=$("backend").value,isApi=!["claude","codex","command"].includes(b);
 $("hint").textContent=HINTS[b]||"OpenAI-compatible API ("+b+"). Local servers (ollama, lmstudio) need no key.";
 $("modelrow").style.display=(b==="claude"||b==="command")?"none":"block";$("baserow").style.display=b==="openai-compatible"?"block":"none";
 $("keyrow").style.display=isApi?"block":"none";$("keylink").innerHTML=KEYS[b]?"No key yet? Create one here (copy the address into your browser): <b>"+KEYS[b]+"</b>":"";$("cmdrow").style.display=b==="command"?"block":"none"}
(async()=>{const s=await api("/state");const sel=$("backend");
 for(const b of s.backends){const o=document.createElement("option");o.value=o.textContent=b;sel.appendChild(o)}
 sel.value=s.backend;
 const F=$("found");
 if(s.found.length){F.innerHTML="<label>Found on this PC - click to use</label>";
  s.found.forEach((f,i)=>{const b=document.createElement("button");b.className="card";b.textContent=(i?"":"★ ")+f.label;
   b.onclick=()=>{sel.value=f.backend;show();$("save").click()};F.appendChild(b)})}
 else{F.innerHTML="<label>Nothing found on this PC yet</label><small>Easiest: install Claude Code and log in, or install Ollama. Or open the options below and enter an API key.</small>";$("adv").open=true}const O=$("others"),have=s.found.map(f=>f.backend);
 s.backends.filter(b=>!have.includes(b)&&b!=="command").forEach(b=>{const x=document.createElement("button");x.className="small";x.textContent=b;
  x.onclick=()=>{sel.value=b;show();$("adv").open=true;$("api_key").focus()};O.appendChild(x)});
 $("model").value=s.model||"";$("base_url").value=s.base_url||"";$("command").value=s.command||"";
 $("inputctl").checked=!!s.input_control;$("access").checked=!!s.computer_access;$("harness").value=s.harness;$("hstate").textContent=s.harness_custom?"Using your edited harness.":"Using the built-in harness.";
 $("hreset").onclick=async()=>{const r=await api("/save",{backend:$("backend").value,harness_reset:true});$("msg").textContent=r.status;const s2=await api("/state");$("harness").value=s2.harness;$("hstate").textContent="Using the built-in harness."};
 $("aiprompt").value=s.prompt;$("copy").onclick=()=>{$("aiprompt").select();document.execCommand("copy")};$("persona").value=s.persona||"";$("keystate").textContent=s.has_key?"(saved)":"";show();sel.onchange=show;
 recheck()})();
async function recheck(){$("msg").textContent="Checking the AI ...";$("msg").className="";
 try{const r=await api("/check");$("msg").textContent=r.status;$("msg").className=r.ok?"ok":"bad"}catch(e){$("msg").textContent="Check failed: "+e;$("msg").className="bad"}}
$("save").onclick=async()=>{$("msg").textContent="Saving ...";$("msg").className="";
 const r=await api("/save",{backend:$("backend").value,model:$("model").value,base_url:$("base_url").value,
  api_key:$("api_key").value,command:$("command").value,persona:$("persona").value,harness:$("harness").value,input_control:$("inputctl").checked,computer_access:$("access").checked});
 $("msg").textContent=r.status;$("msg").className=r.ok?"ok":"bad";if(r.has_key)$("keystate").textContent="(saved)";$("api_key").value="";await recheck()};
</script></body></html>"""


def ai_prompt() -> str:
    """Text the user can hand to their own AI agent so that it configures this program."""
    return ("Please set up the WoW AI chat program for me. Edit the JSON file ~/.wowclaude/config.json in my home folder (create it if missing, keep "
            "other keys). Set \"backend\" to one of: claude (Claude Code login), codex (ChatGPT login), ollama, lmstudio, "
            "openrouter, openai, anthropic, gemini, groq, deepseek, mistral, xai, together, perplexity, cerebras, or "
            "\"openai-compatible\" (then also set \"base_url\"), or \"command\" (then set \"command\" to a shell command "
            "that reads the prompt on stdin and prints the answer). Optional keys: \"model\". For API backends put the key "
            "in the environment variable named for the service (e.g. OPENROUTER_API_KEY) rather than in the file. "
            "Tip: set up a long-lived login so it does not expire every few weeks - for Claude Code run `claude setup-token` "
            "(a login valid for a year) and store the token it prints in the environment variable CLAUDE_CODE_OAUTH_TOKEN; "
            "for other services create a long-lived API key. If my login has expired, set this up yourself: run the command, the user only has to confirm in the browser window it opens. "
            "Afterwards run: py -3 -m wowclaude doctor --deep  and tell me whether the AI answered.")


def _state() -> dict:
    cfg = config.load()
    name, rest = claude.clean_name(cfg.get("name")), ""
    try:
        lines = config.PERSONA.read_text(encoding="utf-8").splitlines()
        if name:
            rest = "\n".join(lines)
        else:  # old style: the first line of persona.txt was the name
            name, rest = claude.clean_name(lines[0] if lines else ""), "\n".join(lines[1:])
    except OSError:
        pass
    return {"backends": ["claude", "codex", "command", "openai-compatible", *backends.PRESETS],
            "backend": backends.name(), "model": cfg.get("model", ""), "base_url": cfg.get("base_url", ""),
            "command": cfg.get("command", ""), "has_key": bool(cfg.get("api_key")),
            "name": name, "persona": rest.strip("\n"), "found": backends.detect(), "prompt": ai_prompt(),
            "harness": claude.custom_harness() or claude.builtin_harness(), "harness_custom": claude.custom_harness() is not None,
            "input_control": bool(cfg.get("input_control")), "computer_access": bool(cfg.get("computer_access"))}


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
    name = claude.clean_name(cfg.get("name"))  # the name is set in the game menu (AI name), not on this page
    if "name" in data:
        name = claude.clean_name(data.get("name"))
        if name:
            cfg["name"] = name
        else:
            cfg.pop("name", None)
    if "computer_access" in data:
        if data.get("computer_access"):
            cfg["computer_access"] = True
        else:
            cfg.pop("computer_access", None)
    if "input_control" in data:
        if data.get("input_control"):
            cfg["input_control"] = True
        else:
            cfg.pop("input_control", None)
    key = str(data.get("api_key", "")).strip()
    if key:
        cfg["api_key"] = key
    config.save(cfg)
    try:  # the AI's name lives in the addon's Name.lua (applies after /reload)
        from . import installer
        root = config.client_root()
        if root:
            installer.write_name(root, name)
    except OSError:
        pass
    if data.get("harness_reset"):
        config.HARNESS.unlink(missing_ok=True)
    elif "harness" in data:  # text equal to the built-in one (or empty) means: no custom harness
        text = str(data.get("harness", "")).strip()
        if not text or text == claude.builtin_harness().strip():
            config.HARNESS.unlink(missing_ok=True)
        else:
            config.HOME.mkdir(parents=True, exist_ok=True)
            config.HARNESS.write_text(text + "\n", encoding="utf-8")
    persona = str(data.get("persona", "")).strip("\n")
    config.HOME.mkdir(parents=True, exist_ok=True)
    if persona and not name:  # no name set: persona() reads the first line as the name, so keep "Claude" there
        config.PERSONA.write_text("Claude\n" + persona + "\n", encoding="utf-8")
    elif persona:
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
                     creationflags=0x08000000 if sys.platform == "win32" else 0)  # 0x08000000 = CREATE_NO_WINDOW
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    return 0
