"""Discovery service entry point used by the CLI."""

from __future__ import annotations

from tadabbur.config.models import Settings
from tadabbur.database import Repository, open_database
from tadabbur.discovery import run_discovery


def run_discovery(
    settings: Settings,
    *,
    source_id: str | None = None,
    dry_run: bool = False,
    max_entries: int = 50,
) -> str:
    db_path = settings.storage.database_path
    if not db_path.is_absolute():
        db_path = settings.project_dir / db_path
    conn = open_database(db_path)
    try:
        repo = Repository(conn)
        result = run_discovery(
            settings,
            repo,
            source_id=source_id,
            dry_run=dry_run,
            max_entries=max_entries,
        )
        return str(result)
    finally:
        conn.close()
