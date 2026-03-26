"""Localhost HTTP hooks while `easify run` is active (push snippet reload from `easify ui`)."""

from __future__ import annotations

import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING

from app.utils.log import get_logger

if TYPE_CHECKING:
    from app.config.settings import Settings
    from app.engine.service import ExpansionService

LOG = get_logger(__name__)


def start_snippet_reload_hook_server(
    service: "ExpansionService",
    settings: "Settings",
    *,
    stop: threading.Event,
) -> None:
    port = int(settings.snippet_reload_listen_port)
    if port <= 0:
        return
    host = "127.0.0.1"
    token = settings.ui_secret_token.strip()
    if not token:
        LOG.warning(
            "EASIFY_UI_SECRET_TOKEN unset — snippet reload hook allows unauthenticated POST "
            "from 127.0.0.1 only (set token for stricter checks)"
        )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:
            LOG.info("%s - " + fmt, self.address_string(), *args)

        def _fail(self, code: int, msg: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)

        def _ok(self, body: bytes = b"ok") -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/hooks/reload-snippets":
                self._fail(HTTPStatus.NOT_FOUND, b"not found")
                return
            cli = str(self.client_address[0] if self.client_address else "")
            host_ok = cli in ("127.0.0.1", "::1") or cli.startswith("127.")
            if token:
                if self.headers.get("X-Easify-Token") != token:
                    self._fail(HTTPStatus.FORBIDDEN, b"forbidden")
                    return
            elif not host_ok:
                self._fail(HTTPStatus.FORBIDDEN, b"forbidden")
                return
            n = int(self.headers.get("Content-Length", "0") or "0")
            if n > 65536:
                self._fail(HTTPStatus.BAD_REQUEST, b"body too large")
                return
            if n > 0:
                self.rfile.read(n)
            service.reload_snippets_hot()
            self._ok()

    try:
        srv = ThreadingHTTPServer((host, port), Handler)
    except OSError as e:
        LOG.warning(
            "snippet reload hook: cannot bind %s:%s (%s) — set EASIFY_SNIPPET_RELOAD_LISTEN_PORT=0 to silence",
            host,
            port,
            e,
        )
        return

    def serve() -> None:
        LOG.info(
            "snippet reload hook http://%s:%s/ POST /hooks/reload-snippets (same X-Easify-Token as snippet UI)",
            host,
            port,
        )
        srv.serve_forever(poll_interval=0.5)

    threading.Thread(target=serve, daemon=True, name="easify-reload-hook").start()

    def watch_stop() -> None:
        stop.wait()
        try:
            srv.shutdown()
        except Exception:
            pass

    threading.Thread(target=watch_stop, daemon=True, name="easify-reload-hook-stop").start()
