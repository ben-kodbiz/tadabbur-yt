"""Upload queue: database-driven, approval-gated, hard-limited (§18/§34).

Never scan folders to upload; only DB records in READY_FOR_UPLOAD with
approved rights enter the queue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tadabbur.audio.ffmpeg import available as ffmpeg_available
from tadabbur.logging import stage_logger
from tadabbur.uploader.config import UploadPipelineSettings
from tadabbur.uploader.models import (
    APPROVED_FOR_UPLOAD,
    FailureCategory,
    MediaState,
)
from tadabbur.uploader.repository import UploaderRepository

logger = stage_logger("up-queue")


@dataclass
class QueueEntry:
    media_item_id: int
    title: str
    rights_status: str
    video_path: Path | None = None


@dataclass
class QueuePlan:
    entries: list[QueueEntry] = field(default_factory=list)
    rejected: list[tuple[int, str]] = field(default_factory=list)  # (id, reason)


def build_queue_plan(
    up_settings: UploadPipelineSettings,
    repo: UploaderRepository,
    *,
    limit: int | None = None,
) -> QueuePlan:
    """Collect upload-eligible items and validate each one."""
    plan = QueuePlan()
    effective_limit = min(
        limit or up_settings.upload.max_uploads_per_run,
        up_settings.upload.max_uploads_per_run,
    )
    rows = repo.list_upload_queue(limit=effective_limit)

    for row in rows:
        item_id = int(row["id"])
        reason = _preupload_check(repo, int(row["id"]))
        if reason is not None:
            plan.rejected.append((item_id, reason))
            continue
        f = repo.get_file(item_id, "youtube_mp4")
        plan.entries.append(QueueEntry(
            media_item_id=item_id,
            title=row["original_title"] or "",
            rights_status=row["rights_status"],
            video_path=Path(f["path"]) if f else None,
        ))
    return plan


def _preupload_check(repo: UploaderRepository, media_item_id: int) -> str | None:
    """Return rejection reason, or None if the item may be uploaded."""
    row = repo.get_media_item(media_item_id)
    if row is None:
        return "item not found"
    # Level 1+2 of policy gate: rights must be explicitly approved.
    if row["rights_status"] not in APPROVED_FOR_UPLOAD:
        return f"rights_status={row['rights_status']} not approved"
    if row["state"] != MediaState.READY_FOR_UPLOAD:
        return f"state={row['state']} not ready"
    f = repo.get_file(media_item_id, "youtube_mp4")
    if f is None:
        return "no rendered youtube mp4 recorded"
    p = Path(f["path"])
    if not p.exists():
        return "mp4 missing on disk"
    if ffmpeg_available() is False:
        return "ffmpeg unavailable"  # needed for post-upload verification
    return None


def uploads_today_count(repo: UploaderRepository) -> int:
    since = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
    row = repo._conn.execute(
        "SELECT COUNT(*) c FROM uploads WHERE uploaded_at >= ?", (since,)
    ).fetchone()
    return int(row["c"])


class DailyLimitReached(Exception):
    pass


def check_daily_limit(up_settings: UploadPipelineSettings, repo: UploaderRepository) -> None:
    """§34 hard daily cap. Raise before any upload happens."""
    used = uploads_today_count(repo)
    remaining = max(0, up_settings.upload.max_uploads_per_day - used)
    if remaining <= 0:
        raise DailyLimitReached(
            f"daily upload limit reached ({used}/{up_settings.upload.max_uploads_per_day})"
        )


def record_upload_attempt(repo: UploaderRepository, media_item_id: int,
                          error: str | None = None) -> None:
    """Track attempts even for failures; platform id stored only on success."""
    repo.ensure_upload_record(media_item_id)
    repo._conn.execute(
        """
        UPDATE uploads SET
            attempt_count = attempt_count + 1,
            upload_status = CASE WHEN ? IS NULL THEN 'uploaded' ELSE 'failed' END,
            uploaded_at = CASE WHEN ? IS NULL
                          THEN strftime('%Y-%m-%dT%H:%M:%fZ','now')
                          ELSE uploaded_at END,
            error_message = ?
        WHERE media_item_id = ?
        """,
        (error, error, error, media_item_id),
    )
    repo._conn.commit()


def mark_upload_failed(repo: UploaderRepository, media_item_id: int,
                       category: str, message: str) -> None:
    repo.set_upload_status(media_item_id, "failed")
    logger.error("[UP-QUEUE] item=%s upload failed (%s): %s",
                 media_item_id, category, message[:300])
