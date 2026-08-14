"""Download service entry point used by the CLI."""

from __future__ import annotations

from tadabbur.config.models import Settings
from tadabbur.database import Repository, open_database
from tadabbur.downloader import run_download


def run_download_service(
    settings: Settings,
    *,
    video_id: str | None = None,
    limit: int = 1,
) -> str:
    db_path = settings.storage.database_path
    if not db_path.is_absolute():
        db_path = settings.project_dir / db_path
    conn = open_database(db_path)
    try:
        repo = Repository(conn)
        outcomes = run_download(settings, repo, video_id=video_id, limit=limit)
        return "\n".join(str(o) for o in outcomes) or "[DOWNLOAD] nothing to do"
    finally:
        conn.close()
