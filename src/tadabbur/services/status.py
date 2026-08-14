"""Status / inspection service."""

from __future__ import annotations

import json

from tadabbur.config.models import Settings
from tadabbur.database import Repository, open_database


def run_status(settings: Settings) -> str:
    db_path = _db(settings)
    conn = open_database(db_path)
    try:
        repo = Repository(conn)
        rows = repo._conn.execute(
            "SELECT status, COUNT(*) AS n FROM media GROUP BY status ORDER BY status"
        ).fetchall()
        lines = ["[STATUS]"]
        total = 0
        for row in rows:
            lines.append(f"  {row['status']}: {row['n']}")
            total += int(row["n"])
        lines.append(f"  TOTAL: {total}")
        lines.append(f"  SOURCES: {len(repo.list_sources())}")
        return "\n".join(lines)
    finally:
        conn.close()


def list_failed(settings: Settings) -> str:
    conn = open_database(_db(settings))
    try:
        repo = Repository(conn)
        rows = repo.list_failed()
        lines = [f"[FAILED] count={len(rows)}"]
        for row in rows:
            lines.append(
                f"  {row['external_id']} | {row['title'][:60]} | err={row['error_message']}"
            )
        return "\n".join(lines)
    finally:
        conn.close()


def inspect_media(settings: Settings, *, video_id: str) -> str:
    conn = open_database(_db(settings))
    try:
        repo = Repository(conn)
        row = repo.get_media_by_external_id(video_id)
        if row is None:
            return f"[INSPECT] video={video_id} not found"

        media = dict(row)
        media["files"] = [dict(f) for f in repo.list_media_files(int(row["id"]))]
        media["tags"] = [dict(t) for t in repo.tags_for_media(int(row["id"]))]
        media["classifications"] = [
            dict(c)
            for c in repo._conn.execute(
                "SELECT * FROM classifications WHERE media_id=?", (int(row["id"]),)
            ).fetchall()
        ]
        media["jobs"] = [
            dict(j)
            for j in repo._conn.execute(
                "SELECT * FROM processing_jobs WHERE media_id=? ORDER BY id DESC",
                (int(row["id"]),),
            ).fetchall()
        ]
        return json.dumps(media, indent=2, ensure_ascii=False, default=str)
    finally:
        conn.close()


def _db(settings: Settings):
    db_path = settings.storage.database_path
    if not db_path.is_absolute():
        db_path = settings.project_dir / db_path
    return db_path
