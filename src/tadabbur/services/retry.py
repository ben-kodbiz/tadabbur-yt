"""Retry service."""

from __future__ import annotations

from pathlib import Path

from tadabbur.config.models import Settings
from tadabbur.database import Repository, open_database
from tadabbur.downloader.manager import _cleanup_partial_outputs
from tadabbur.jobs.paths import media_directory
from tadabbur.status import FAILED, QUEUED


def run_retry(settings: Settings, *, failed: bool = False, video_id: str | None = None) -> str:
    db_path = settings.storage.database_path
    if not db_path.is_absolute():
        db_path = settings.project_dir / db_path
    conn = open_database(db_path)
    try:
        repo = Repository(conn)
        lines: list[str] = []
        count = 0

        if video_id:
            row = repo.get_media_by_external_id(video_id)
            if row is None:
                return f"[RETRY] video={video_id} not found"
            if row["status"] != FAILED:
                return f"[RETRY] video={video_id} is not in FAILED state"
            rows = [row]
        elif failed:
            rows = repo.list_failed()
        else:
            rows = repo.list_failed()

        for row in rows:
            _cleanup_partial_outputs(
                media_directory(
                    settings,
                    speaker=row["uploader"] or row["channel"],
                    source_id=row["source_id"],
                    video_id=row["external_id"],
                    published_at=row["published_at"],
                ),
                row["external_id"],
            )
            repo.transition_media(int(row["id"]), QUEUED)
            lines.append(f"{row['external_id']} -> QUEUED")
            count += 1

        return f"[RETRY] requeued={count}\n" + "\n".join(lines)
    finally:
        conn.close()
