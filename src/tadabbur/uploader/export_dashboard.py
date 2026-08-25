"""Read-only tracking dashboard export: pipeline.db -> static HTML/JS/CSS site.

The frontend never touches the database; it reads exported JSON only.
Regenerate anytime with ``upipeline export-dashboard``.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from tadabbur.logging import stage_logger
from tadabbur.uploader.config import UploadPipelineSettings
from tadabbur.uploader.database import open_database
from tadabbur.uploader.models import APPROVED_FOR_UPLOAD
from tadabbur.uploader.repository import UploaderRepository

logger = stage_logger("up-dashexport")

WEB_DIR = Path(__file__).parent / "dashboard_web"


def export_dashboard(
    ingest_project_dir: Path,
    up_settings: UploadPipelineSettings,
    repo: UploaderRepository,
) -> Path:
    """Write the static dashboard into <base>/dashboard/. Returns its path."""
    out = ingest_project_dir / up_settings.base_dir / "dashboard"
    out.mkdir(parents=True, exist_ok=True)

    conn = repo._conn
    items = conn.execute(
        """
        SELECT m.id, m.original_media_id, m.original_url, m.original_title,
               m.uploader_name, m.published_at, m.duration_seconds,
               m.rights_status, m.state, m.upload_status,
               m.rights_reviewed_at, m.permission_reference,
               s.source_key, s.name AS source_name,
               u.platform_video_id, u.platform_url, u.title_used,
               u.uploaded_at, u.attempt_count, u.error_message AS upload_error,
               f.size_bytes AS original_size,
               op.size_bytes AS audio_size,
               mp4.size_bytes AS video_size
        FROM media_items m
        JOIN sources s ON s.id = m.source_id
        LEFT JOIN uploads u ON u.media_item_id = m.id AND u.platform = 'youtube'
        LEFT JOIN files f  ON f.media_item_id = m.id AND f.file_type = 'original_media'
        LEFT JOIN files op ON op.media_item_id = m.id AND op.file_type = 'processed_opus'
        LEFT JOIN files mp4 ON mp4.media_item_id = m.id
                             AND mp4.file_type = 'youtube_mp4'
        ORDER BY COALESCE(u.uploaded_at, m.updated_at) DESC, m.id DESC
        """
    ).fetchall()

    def _row(r) -> dict:
        approved = r["rights_status"] in APPROVED_FOR_UPLOAD
        uploaded = bool(r["platform_video_id"])
        return {
            "id": r["id"],
            "media_id": r["original_media_id"],
            "title": r["title_used"] or r["original_title"],
            "original_title": r["original_title"],
            "speaker": r["uploader_name"],
            "source_key": r["source_key"],
            "source_name": r["source_name"],
            "source_url": r["original_url"],
            "published_at": r["published_at"],
            "duration_seconds": r["duration_seconds"],
            "rights_status": r["rights_status"],
            "upload_authorized": approved,
            "state": r["state"],
            "upload_status": r["upload_status"] or "not_queued",
            "uploaded": uploaded,
            "platform_video_id": r["platform_video_id"],
            "platform_url": r["platform_url"],
            "uploaded_at": r["uploaded_at"],
            "attempts": r["attempt_count"] or 0,
            "error": r["upload_error"],
            "reviewed_at": r["rights_reviewed_at"],
            "permission_reference": r["permission_reference"],
            "sizes_mb": {
                "original": round((r["original_size"] or 0) / 1e6, 1),
                "audio": round((r["audio_size"] or 0) / 1e6, 1),
                "video": round((r["video_size"] or 0) / 1e6, 1),
            },
        }

    data = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "items": [_row(r) for r in items],
    }
    (out / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                   encoding="utf-8")

    # copy static assets
    for name in ("index.html", "style.css", "app.js"):
        src = WEB_DIR / name
        if src.exists():
            shutil.copy2(src, out / name)

    logger.info("[UP-DASH] wrote %s (%d items)", out, len(data["items"]))
    return out
