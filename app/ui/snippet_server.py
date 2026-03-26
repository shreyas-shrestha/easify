"""Minimal localhost HTTP UI for ~/.config/easify/snippets.json (Phase 3)."""

from __future__ import annotations

import json
import secrets
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.config.settings import Settings
from app.utils.log import get_logger

LOG = get_logger(__name__)

_INDEX_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><title>Easify snippets</title>
<style>
body{font-family:system-ui,sans-serif;max-width:720px;margin:24px auto;padding:0 16px;}
table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:8px;text-align:left;vertical-align:top;}
th{background:#f4f4f4}code{font-size:0.9em}.row{margin:16px 0}input,textarea{width:100%;box-sizing:border-box;}
button{padding:8px 14px;cursor:pointer}
.muted{color:#666;font-size:0.9em}
</style></head><body>
<h1>Easify snippets</h1>
<p class="muted">Editing <code id="path"></code> — localhost only. POST/DELETE require <code>X-Easify-Token</code> (see server log). Changes apply on the next snippet lookup (mtime reload).</p>
<div class="row"><h2>Add / update</h2>
<label>Key <input id="k" placeholder="thanks or slack:thanks"/></label>
<label>Value <textarea id="v" rows="4" placeholder="Expanded text"></textarea></label>
<p><button type="button" id="save">Save</button></p></div>
<h2>Entries</h2>
<div id="list">Loading…</div>
<script>
const TOKEN=__EASIFY_TOKEN_JSON__;
const pathEl=document.getElementById('path');
const listEl=document.getElementById('list');
const tokHeaders={'X-Easify-Token':TOKEN};
async function load(){
  const r=await fetch('/api/snippets',{headers:tokHeaders});
  if(!r.ok){listEl.textContent='Error: '+r.status+' '+await r.text();return;}
  const j=await r.json();
  pathEl.textContent=j.path||'';
  const s=j.snippets||{};
  const keys=Object.keys(s).sort();
  if(keys.length===0){listEl.textContent='(empty)';return;}
  let h='<table><tr><th>Key</th><th>Value</th><th></th></tr>';
  for(const k of keys){
    const v=(s[k]||'').replace(/</g,'&lt;');
    h+=`<tr><td><code>${k}</code></td><td>${v}</td><td><button data-k="${encodeURIComponent(k)}">Delete</button></td></tr>`;
  }
  h+='</table>';listEl.innerHTML=h;
  listEl.querySelectorAll('button[data-k]').forEach(b=>b.onclick=async()=>{
    if(!confirm('Delete '+decodeURIComponent(b.dataset.k)+'?'))return;
    await fetch('/api/snippets?key='+encodeURIComponent(decodeURIComponent(b.dataset.k)),{method:'DELETE',headers:tokHeaders});
    load();
  });
}
document.getElementById('save').onclick=async()=>{
  const k=document.getElementById('k').value.trim().toLowerCase();
  const v=document.getElementById('v').value;
  if(!k){alert('Key required');return;}
  const r=await fetch('/api/snippets',{method:'POST',headers:{'Content-Type':'application/json',...tokHeaders},
    body:JSON.stringify({key:k,value:v})});
  if(!r.ok){alert(await r.text());return;}
  document.getElementById('k').value='';document.getElementById('v').value='';
  load();
};
load();
</script></body></html>
"""


def _load_inner(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        raw_obj: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(raw_obj, dict) and "snippets" in raw_obj:
        inner = raw_obj["snippets"]
    elif isinstance(raw_obj, dict):
        inner = raw_obj
    else:
        return {}
    if not isinstance(inner, dict):
        return {}
    out: dict[str, str] = {}
    for kk, vv in inner.items():
        if isinstance(kk, str) and isinstance(vv, str):
            out[kk.strip().lower()] = vv
    return out


def _atomic_write(path: Path, inner: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"snippets": inner}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def run_snippet_ui(settings: Settings) -> None:
    path = settings.user_snippets_path()
    host = settings.ui_host
    port = settings.ui_port
    user_path = path
    secret = settings.ui_secret_token.strip() or secrets.token_urlsafe(24)
    if not settings.ui_secret_token.strip():
        LOG.warning(
            "EASIFY_UI_SECRET_TOKEN unset — generated ephemeral token (set env to pin). "
            "Use the same value in X-Easify-Token for API calls."
        )
    token_json = json.dumps(secret)
    index_html = _INDEX_HTML_TEMPLATE.replace("__EASIFY_TOKEN_JSON__", token_json)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            LOG.info("%s - " + fmt, self.address_string(), *args)

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _api_token_ok(self) -> bool:
            return self.headers.get("X-Easify-Token") == secret

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path or "/")
            if parsed.path in ("/", "/index.html"):
                b = index_html.encode("utf-8")
                self._send(HTTPStatus.OK, b, "text/html; charset=utf-8")
                return
            if parsed.path == "/api/snippets":
                if not self._api_token_ok():
                    self._send(HTTPStatus.FORBIDDEN, b"forbidden", "text/plain; charset=utf-8")
                    return
                inner = _load_inner(user_path)
                payload = json.dumps({"path": str(user_path), "snippets": inner}, ensure_ascii=False).encode(
                    "utf-8"
                )
                self._send(HTTPStatus.OK, payload, "application/json; charset=utf-8")
                return
            self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain; charset=utf-8")

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path or "/")
            if parsed.path != "/api/snippets":
                self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain; charset=utf-8")
                return
            if not self._api_token_ok():
                self._send(HTTPStatus.FORBIDDEN, b"forbidden", "text/plain; charset=utf-8")
                return
            n = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(n) if n > 0 else b"{}"
            try:
                data = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send(HTTPStatus.BAD_REQUEST, b"invalid json", "text/plain; charset=utf-8")
                return
            if not isinstance(data, dict):
                self._send(HTTPStatus.BAD_REQUEST, b"expected object", "text/plain; charset=utf-8")
                return
            key = data.get("key")
            val = data.get("value")
            if not isinstance(key, str) or not isinstance(val, str):
                self._send(HTTPStatus.BAD_REQUEST, b"key and value must be strings", "text/plain; charset=utf-8")
                return
            kk = key.strip().lower()
            if not kk:
                self._send(HTTPStatus.BAD_REQUEST, b"empty key", "text/plain; charset=utf-8")
                return
            inner = _load_inner(user_path)
            inner[kk] = val
            try:
                _atomic_write(user_path, inner)
            except OSError as e:
                self._send(HTTPStatus.INTERNAL_SERVER_ERROR, str(e).encode(), "text/plain; charset=utf-8")
                return
            self._send(HTTPStatus.OK, b"ok", "text/plain; charset=utf-8")

        def do_DELETE(self) -> None:  # noqa: N802
            parsed = urlparse(self.path or "/")
            if parsed.path != "/api/snippets":
                self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain; charset=utf-8")
                return
            if not self._api_token_ok():
                self._send(HTTPStatus.FORBIDDEN, b"forbidden", "text/plain; charset=utf-8")
                return
            qs = parse_qs(parsed.query or "")
            keys = qs.get("key", [])
            if not keys or not keys[0].strip():
                self._send(HTTPStatus.BAD_REQUEST, b"missing key", "text/plain; charset=utf-8")
                return
            kk = keys[0].strip().lower()
            inner = _load_inner(user_path)
            if kk not in inner:
                self._send(HTTPStatus.NOT_FOUND, b"no such key", "text/plain; charset=utf-8")
                return
            del inner[kk]
            try:
                _atomic_write(user_path, inner)
            except OSError as e:
                self._send(HTTPStatus.INTERNAL_SERVER_ERROR, str(e).encode(), "text/plain; charset=utf-8")
                return
            self._send(HTTPStatus.OK, b"ok", "text/plain; charset=utf-8")

    server = ThreadingHTTPServer((host, port), Handler)
    LOG.info("snippet UI http://%s:%s/ — X-Easify-Token: %s", host, port, secret)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOG.info("snippet UI stopped")
    finally:
        server.server_close()
