"""Validation service entry point used by the CLI."""

from __future__ import annotations

from tadabbur.config.models import Settings
from tadabbur.database import Repository, open_database
from tadabbur.validator import run_validation


def run_validation_service(settings: Settings, *, video_id: str | None = None) -> str:
    db_path = settings.storage.database_path
    if not db_path.is_absolute():
        db_path = settings.project_dir / db_path
    conn = open_database(db_path)
    try:
        repo = Repository(conn)
        return run_validation(settings, repo, video_id=video_id)
    finally:
        conn.close()
