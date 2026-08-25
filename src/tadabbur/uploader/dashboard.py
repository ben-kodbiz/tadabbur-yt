"""Minimal local web dashboard for rights review and queue visibility (§25).

Stdlib-only (http.server), consistent with the ingestion `serve` command.
Pages: /overview, /review (+ approve/block/archive actions).
Read-only elsewhere by design; the DB remains the source of truth.
"""

from __future__ import annotations

import html
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from tadabbur.config.models import Settings
from tadabbur.logging import stage_logger
from tadabbur.uploader.config import UploadPipelineSettings
from tadabbur.uploader.database import open_database
from tadabbur.uploader.models import MediaState
from tadabbur.uploader.repository import UploaderRepository

logger = stage_logger("up-dashboard")

_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>Upload Pipeline</title>
<style>
body{{font-family:system-ui;margin:2rem;background:#f5f6f7;color:#222}}
table{{border-collapse:collapse;width:100%;background:#fff}}
th,td{{border:1px solid #ddd;padding:6px 10px;text-align:left;font-size:.9em}}
tr:nth-child(even){{background:#fafafa}}
form{{display:inline}}
button{{cursor:pointer;padding:2px 8px}}
.ok{{color:#1b5e20}}.warn{{color:#b26a00}}
nav a{{margin-right:1rem}}
</style></head><body>
<nav><a href="/overview">Overview</a><a href="/review">Review</a></nav>
{body}
</body></html>"""


def _esc(s) -> str:
    return html.escape(str(s or ""))


def render_overview(repo: UploaderRepository) -> str:
    rows = repo.summary()
    body = ["<h1>Overview</h1><table><tr><th>State</th><th>Items</th></tr>"]
    for state, n in sorted(rows.items()):
        cls = "ok" if state == "UPLOADED" else ("warn" if n else "")
        body.append(f'<tr class="{cls}"><td>{_esc(state)}</td><td>{n}</td></tr>')
    body.append("</table>")
    return _PAGE.format(body="\n".join(body))


def render_review(repo: UploaderRepository, message: str | None = None) -> str:
    rows = repo.list_media_by_state(MediaState.DISCOVERED, MediaState.RIGHTS_REVIEW)
    parts = [f"<h1>Rights Review ({len(rows)})</h1>"]
    if message:
        parts.append(f"<p class='ok'>{_esc(message)}</p>")
    parts.append(
        "<table><tr><th>ID</th><th>Title</th><th>Status</th>"
        "<th>Actions</th></tr>"
    )
    for r in rows:
        mid = r["id"]
        actions = "".join(
            f"""
<form method="post" action="/review">
<input type="hidden" name="id" value="{mid}">
<input type="hidden" name="action" value="{action}">
<button>{label}</button></form>&nbsp;"""
            for action, label in (
                ("approve", "approve"),
                ("archive", "archive-only"),
                ("block", "block"),
            )
        )
        parts.append(
            f"<tr><td>{mid}</td><td>{_esc((r['original_title'] or '')[:60])}</td>"
            f"<td>{_esc(r['rights_status'])}</td><td>{actions}</td></tr>"
        )
    parts.append("</table>")
    return _PAGE.format(body="\n".join(parts))


def make_handler(settings: Settings, up_settings: UploadPipelineSettings):
    conn = open_database(up_settings.resolve_database_path(settings.project_dir))
    repo = UploaderRepository(conn)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # quiet
            logger.debug(fmt, *args)

        def _send(self, body: str, status: int = 200) -> None:
            data = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/review":
                self._send(render_review(repo))
            elif path in ("/", "/overview"):
                self._send(render_overview(repo))
            else:
                self._send(_PAGE.format(body="<h1>404</h1>"), 404)

        def do_POST(self) -> None:
            from tadabbur.uploader.models import UploadRightsStatus as RS

            path = urlparse(self.path).path
            if path != "/review":
                self._send(_PAGE.format(body="<h1>404</h1>"), 404)
                return
            length = int(self.headers.get("Content-Length") or 0)
            form = parse_qs(self.rfile.read(length).decode())
            item_id = int(form.get("id", ["0"])[0])
            action = form.get("action", [""])[0]

            msg = "unknown action"
            mapping = {
                "approve": (None, MediaState.DOWNLOAD_PENDING),
                "archive": (RS.UPLOAD_NOT_AUTHORIZED, MediaState.ARCHIVED),
                "block": (RS.UPLOAD_NOT_AUTHORIZED, MediaState.BLOCKED),
            }
            if action in mapping:
                status_choice, new_state = mapping[action]
                row = repo.get_media_item(item_id)
                if row is not None:
                    if row["state"] == MediaState.DISCOVERED:
                        repo.transition(item_id, MediaState.RIGHTS_REVIEW)
                    chosen = status_choice or RS.PERMISSION_CONFIRMED
                    ok_state = repo.transition(item_id, new_state)
                    if ok_state:
                        repo.review_rights(
                            item_id,
                            rights_status=chosen,
                            notes=f"dashboard:{action}",
                        )
                        msg = f"item {item_id} -> {chosen} ({new_state})"
                    else:
                        msg = f"invalid transition for {item_id}"
                else:
                    msg = f"item {item_id} not found"
            self._send(render_review(repo, msg))

    return Handler


def serve_dashboard(
    settings: Settings,
    up_settings: UploadPipelineSettings,
    *,
    host: str = "127.0.0.1",
    port: int = 8767,
) -> None:
    handler = make_handler(settings, up_settings)
    server = HTTPServer((host, port), handler)
    logger.info("[UP-DASHBOARD] listening on http://%s:%d", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
