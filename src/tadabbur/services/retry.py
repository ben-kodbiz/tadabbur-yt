"""Retry service."""

from __future__ import annotations

from pathlib import Path

from tadabbur.config.models import Settings
from tadabbur.database import Repository, open_database
from tadabbur.downloader.manager import _cleanup_partial_outputs
from tadabbur.jobs.paths import series_directory
from tadabbur.metadata.series import series_info
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
            si = series_info(row["title"])
            _cleanup_partial_outputs(
                series_directory(
                    settings,
                    speaker=row["uploader"] or row["channel"],
                    series_folder=si.folder,
                ),
                row["external_id"],
            )
            repo.transition_media(int(row["id"]), QUEUED)
            # Reset the attempt budget so the item actually retries
            # (otherwise count_media_failures exceeds max_attempts forever).
            repo.clear_download_attempts(int(row["id"]))
            lines.append(f"{row['external_id']} -> QUEUED")
            count += 1

        return f"[RETRY] requeued={count}\n" + "\n".join(lines)
    finally:
        conn.close()
