"""Export service entry point."""

from __future__ import annotations

from tadabbur.config.models import Settings
from tadabbur.database import Repository, open_database
from tadabbur.exporters import export_web_data


def run_export_service(settings: Settings) -> str:
    db_path = settings.storage.database_path
    if not db_path.is_absolute():
        db_path = settings.project_dir / db_path
    conn = open_database(db_path)
    try:
        repo = Repository(conn)
        result = export_web_data(settings, repo)
        return str(result)
    finally:
        conn.close()
