"""Upload pipeline discovery: register sources, scan metadata, dedup.

Identity is ``platform + original_media_id`` — never the title.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tadabbur.config.models import Settings
from tadabbur.downloader.client import YtDlpClient, YtDlpError
from tadabbur.jobs.paths import normalize_upload_date
from tadabbur.logging import stage_logger
from tadabbur.uploader.models import MediaState, UploadRightsStatus
from tadabbur.uploader.repository import UploaderRepository

logger = stage_logger("up-discover")


@dataclass
class UpDiscoveryResult:
    discovered: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)
    sources_checked: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"[UP-DISCOVER] sources={len(self.sources_checked)} "
            f"new={len(self.discovered)} duplicates={len(self.duplicates)} "
            f"errors={len(self.errors)}"
        )


def sync_sources(settings: Settings, repo: UploaderRepository) -> int:
    """Register/refresh configured ingestion sources as upload-pipeline sources.

    Default rights status is manual_review_required — never auto-approve.
    """
    count = 0
    for source in settings.enabled_sources:
        repo.upsert_source(
            source_key=source.id,
            name=source.name,
            platform=source.platform,
            channel_url=source.channel_url,
            attribution_text=f"Original source: {source.name}",
            default_rights_status=UploadRightsStatus.MANUAL_REVIEW_REQUIRED,
            enabled=source.enabled,
        )
        count += 1
    return count


def discover_from_channel(
    settings: Settings,
    repo: UploaderRepository,
    client: YtDlpClient | None = None,
    *,
    max_entries: int = 50,
) -> UpDiscoveryResult:
    """Scan all registered enabled sources for new media metadata."""
    result = UpDiscoveryResult()
    client = client or YtDlpClient(settings)

    if not client.available():
        result.errors.append("yt-dlp binary not available")
        return result

    for src_row in repo.list_sources(enabled_only=True):
        source_key = src_row["source_key"]
        channel_url = src_row["channel_url"]
        if not channel_url:
            continue
        result.sources_checked.append(source_key)

        try:
            entries = client.discover_channel(channel_url, max_entries=max_entries)
        except (YtDlpError, OSError) as exc:
            logger.error("[UP-DISCOVER] source=%s error=%s", source_key, exc)
            result.errors.append(f"{source_key}: {exc}")
            continue

        for entry in entries:
            vid = str(entry.get("id") or "")
            if not vid:
                continue

            # Level-1 duplicate check: platform + original_media_id.
            existing = repo.find_media_item("youtube", vid)
            if existing is not None:
                result.duplicates.append(vid)
                continue

            # Level-2 duplicate check: original URL.
            url = entry.get("webpage_url") or f"https://www.youtube.com/watch?v={vid}"
            if repo.find_by_original_url(url) is not None:
                result.duplicates.append(vid)
                continue

            mid = repo.insert_media_item(
                source_id=int(src_row["id"]),
                platform="youtube",
                original_media_id=vid,
                original_url=url,
                original_title=entry.get("title"),
                uploader_name=entry.get("uploader") or entry.get("channel"),
                published_at=normalize_upload_date(entry.get("upload_date")),
                duration_seconds=entry.get("duration"),
                rights_status=src_row["default_rights_status"]
                or UploadRightsStatus.MANUAL_REVIEW_REQUIRED,
                state=MediaState.DISCOVERED,
            )
            if mid is None:
                result.duplicates.append(vid)
                continue

            result.discovered.append(vid)
            logger.info("[UP-DISCOVER] new=%s title=%r", vid, entry.get("title"))

    return result
