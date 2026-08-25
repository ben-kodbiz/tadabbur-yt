"""End-to-end single-video processing pipeline service."""

from __future__ import annotations

from tadabbur.config.models import Settings
from tadabbur.database import Repository, open_database
from tadabbur.downloader import run_download as engine_run_download
from tadabbur.services.classification import run_classification
from tadabbur.services.tagging import run_tagging
from tadabbur.status import FAILED, QUEUED
from tadabbur.validator import run_validation


def run_process(settings: Settings, *, video_id: str) -> str:
    """Run classify -> download -> tag -> validate for a single video id."""
    db_path = settings.storage.database_path
    if not db_path.is_absolute():
        db_path = settings.project_dir / db_path
    conn = open_database(db_path)
    try:
        repo = Repository(conn)
        return _process(repo, settings, video_id)
    finally:
        conn.close()


def _process(repo: Repository, settings: Settings, video_id: str) -> str:
    row = repo.get_media_by_external_id(video_id)
    if row is None:
        return f"[PIPELINE] video={video_id} not found"

    current = row["status"]
    if current == "DISCOVERED":
        run_classification(settings, video_id=video_id)

    row = repo.get_media_by_external_id(video_id)
    if row["status"] == QUEUED:
        outcomes = engine_run_download(settings, repo, video_id=video_id)
        if not outcomes or outcomes[0].status == FAILED:
            return f"[PIPELINE] video={video_id} download failed"

    row = repo.get_media_by_external_id(video_id)
    if row["status"] == "PROCESSED":
        run_tagging(settings, video_id=video_id)

    row = repo.get_media_by_external_id(video_id)
    if row["status"] == "TAGGED":
        run_validation(settings, video_id=video_id)

    final = repo.get_media_by_external_id(video_id)
    return f"[PIPELINE] video={video_id} status={final['status']}"
