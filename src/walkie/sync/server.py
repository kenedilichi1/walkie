"""LAN download server: the phone pulls today's plan, route and voice track.

Serves `output/` only — never the repo. `/` is a landing page listing the
three files with their size (or a "missing" hint), so the phone only needs
the printed URL.
"""

from __future__ import annotations

import functools
import socket
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from walkie import config
from walkie.log import get_logger
from walkie.sync import SyncError

log = get_logger("sync")

FILES: tuple[tuple[str, str], ...] = (
    (
        str(config.TODAY_PLAN_PATH.relative_to(config.OUTPUT_DIR)),
        "today's walk plan (JSON)",
    ),
    (
        str(config.DEFAULT_WALK_GPX.relative_to(config.OUTPUT_DIR)),
        "route — import into OsmAnd",
    ),
    (
        str(config.WALK_AUDIO_PATH.relative_to(config.OUTPUT_DIR)),
        "voice cues (run: make voice)",
    ),
)


def lan_ip() -> str:
    """Best-effort LAN address (UDP connect sends no packets)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("10.255.255.255", 1))
            return str(sock.getsockname()[0])
    except OSError:
        return "127.0.0.1"


def index_html(directory: Path) -> bytes:
    """Landing page: one link per file, greyed-out with a hint if missing."""
    rows = []
    for rel, note in FILES:
        path = directory / rel
        if path.exists():
            size_kb = path.stat().st_size / 1024
            item = f'<a href="/{rel}">{rel}</a> — {size_kb:.0f} KB'
        else:
            item = f"<b>{rel}</b> — missing"
        rows.append(f"<li>{item}<br><small>{note}</small></li>")
    page = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>walkie</title></head><body>"
        "<h1>walkie</h1><p>Today's files — tap to download:</p>"
        f"<ul>{''.join(rows)}</ul>"
        "<p><small>Served from your laptop on your local network.</small></p>"
        "</body></html>"
    )
    return page.encode()


class _Handler(SimpleHTTPRequestHandler):
    """Serves `directory` only; `/` is the walkie landing page."""

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        if self.path in ("/", "/index.html"):
            body = index_html(Path(self.directory))
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, fmt: str, *args: object) -> None:
        log.info(f"{self.address_string()} {fmt % args}")


def start_server(
    directory: Path = config.OUTPUT_DIR,
    host: str = "0.0.0.0",
    port: int = 8000,
) -> ThreadingHTTPServer:
    """Bind without blocking — `serve()` runs the loop, tests call this."""
    if not directory.is_dir():
        raise SyncError(f"{directory} not found — run a walkie command first")
    handler = functools.partial(_Handler, directory=str(directory))
    try:
        return ThreadingHTTPServer((host, port), handler)
    except OSError as exc:
        raise SyncError(f"cannot listen on {host}:{port} — {exc}") from exc


def serve(
    directory: Path = config.OUTPUT_DIR,
    host: str = "0.0.0.0",
    port: int = 8000,
) -> None:
    """Block, serving `directory` to the LAN until Ctrl-C."""
    httpd = start_server(directory, host, port)
    bound_port = int(httpd.server_address[1])
    ip = lan_ip()
    log.info(
        f"Serving {directory} — open on your phone (same Wi-Fi):"
    )
    log.info(f"  http://{ip}:{bound_port}/")
    for rel, note in FILES:
        missing = "" if (directory / rel).exists() else "  [missing]"
        log.info(f"  http://{ip}:{bound_port}/{rel}  {note}{missing}")
    log.info("Press Ctrl-C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log.info("Server stopped.")
    finally:
        httpd.server_close()
