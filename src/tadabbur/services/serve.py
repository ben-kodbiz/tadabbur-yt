"""Simple local web server for the Tadabbur library display.

Serves the static web assets (HTML/CSS/JS) and the exported JSON, plus the
media files under ``/media/...``. Intended for local reference use only.
"""

from __future__ import annotations

import http.server
import mimetypes
import urllib.parse
from pathlib import Path

from tadabbur.config.models import Settings
from tadabbur.database import Repository, open_database
from tadabbur.exporters import export_web_data
from tadabbur.logging import stage_logger

logger = stage_logger("serve")

_DEFAULT_WEB_DIR = Path(__file__).resolve().parent.parent / "web"


class TadabburHandler(http.server.SimpleHTTPRequestHandler):
    """Serves web assets, exported JSON, and media files."""

    media_root: Path | None = None
    web_dir: Path | None = None
    data_dir: Path | None = None

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, directory=str(self.web_dir or _DEFAULT_WEB_DIR), **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        logger.info("[SERVE] %s", fmt % args)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)

        if path == "/" or path == "/index.html":
            self._serve_file(self.web_dir / "index.html")
            return
        if path.startswith("/media/"):
            self._serve_media(path.removeprefix("/media/"))
            return
        if path.startswith("/data/"):
            if self.data_dir is not None:
                self._serve_file(self.data_dir / path.removeprefix("/data/"))
                return
        self._serve_file(self.web_dir / path.lstrip("/"))

    def _serve_file(self, path: Path) -> None:
        path = path.resolve()
        if not path.is_file():
            self.send_error(404, "not found")
            return
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _serve_media(self, rel: str) -> None:
        if self.media_root is None:
            self.send_error(404, "media root not configured")
            return
        target = (self.media_root / rel).resolve()
        media_root = self.media_root.resolve()
        if not target.is_relative_to(media_root):
            self.send_error(403, "path outside media root")
            return
        self._serve_file(target)


def run_serve(settings: Settings, *, host: str = "127.0.0.1", port: int = 8000, mode: str = "library") -> None:
    """Export data then start the static server (blocking)."""
    db_path = settings.storage.database_path
    if not db_path.is_absolute():
        db_path = settings.project_dir / db_path

    exports_dir = settings.storage.resolved_exports_dir
    if not exports_dir.is_absolute():
        exports_dir = settings.project_dir / exports_dir
    media_root = settings.storage.resolved_media_dir
    if not media_root.is_absolute():
        media_root = settings.project_dir / media_root
    web_dir = settings.project_dir / "web"
    if not web_dir.exists():
        web_dir = _DEFAULT_WEB_DIR

    conn = open_database(db_path)
    try:
        repo = Repository(conn)
        export_web_data(settings, repo, mode=mode)
    finally:
        conn.close()

    handler = _make_handler(media_root=media_root, data_dir=exports_dir, web_dir=web_dir)
    logger.info("[SERVE] serving library at http://%s:%s (mode=%s)", host, port, mode)
    httpd = http.server.ThreadingHTTPServer((host, port), handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("[SERVE] shutting down")
        httpd.server_close()


def _make_handler(*, media_root: Path, data_dir: Path, web_dir: Path):
    """Build a handler class bound to the given directories."""
    attrs = {"media_root": media_root, "web_dir": web_dir, "data_dir": data_dir}
    return type("_BoundHandler", (TadabburHandler,), attrs)
