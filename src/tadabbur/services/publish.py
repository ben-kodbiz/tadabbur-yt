"""Service that runs publish jobs against a configured publisher.

Publishing is resumable and isolated: a failure marks the publish job as failed
(not the media/pipeline). The media stays READY_TO_PUBLISH so it can be retried.
"""

from __future__ import annotations

from tadabbur.config.models import Settings
from tadabbur.database import Repository
from tadabbur.logging import stage_logger, tag
from tadabbur.publishers import (
    FilesystemPublisher,
    InternetArchivePublisher,
    Publisher,
)
from tadabbur.status import FAILED, PUBLISHED, READY_TO_PUBLISH

logger = stage_logger("publish")


def get_publisher(settings: Settings, name: str, repo: Repository) -> Publisher:
    if name == "internet_archive":
        return InternetArchivePublisher()
    if name == "filesystem":
        pub_dir = settings.storage.resolved_exports_dir / "published"
        if not pub_dir.is_absolute():
            pub_dir = settings.project_dir / pub_dir
        return FilesystemPublisher(pub_dir)
    raise ValueError(f"unknown publisher: {name}")


def run_publish(
    settings: Settings,
    repo: Repository,
    *,
    publisher_name: str = "internet_archive",
    video_id: str | None = None,
    limit: int = 10,
) -> str:
    """Publish media in READY_TO_PUBLISH state (or a specific video)."""
    publisher = get_publisher(settings, publisher_name, repo)
    lines: list[str] = []

    if video_id:
        row = repo.get_media_by_external_id(video_id)
        rows = [row] if row and row["status"] == READY_TO_PUBLISH else []
        if not rows:
            return f"[PUBLISH] video={video_id} not found or not ready"
    else:
        rows = repo.list_media_by_status(READY_TO_PUBLISH, limit=limit)

    for row in rows:
        media_id = int(row["id"])
        job_id = repo.create_publish_job(media_id, publisher_name)

        try:
            result = publisher.publish(row, repo)
        except Exception as exc:  # noqa: BLE001
            repo.mark_publish_failure(job_id, str(exc))
            lines.append(f"{row['external_id']} -> PUBLISH_PENDING error={exc}")
            logger.error("[PUBLISH] video=%s failed: %s", row["external_id"], exc)
            continue

        if result.success:
            repo.mark_publish_success(job_id, result.external_url)
            repo.transition_media(media_id, PUBLISHED)
            lines.append(f"{row['external_id']} -> PUBLISHED url={result.external_url}")
            logger.info(
                tag("PUBLISH", "video=%s success url=%s"), row["external_id"], result.external_url
            )
        else:
            repo.mark_publish_failure(job_id, result.error or "unknown error")
            lines.append(f"{row['external_id']} -> PUBLISH_PENDING error={result.error}")
            logger.warning("[PUBLISH] video=%s pending: %s", row["external_id"], result.error)

    summary = "[PUBLISH] processed=%d" % len(rows)
    return "\n".join([summary, *lines])
