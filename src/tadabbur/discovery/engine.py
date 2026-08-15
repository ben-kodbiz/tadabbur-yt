"""Discovery engine: fetch channel metadata, normalize, dedup, insert."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from tadabbur.config.models import Settings, Source
from tadabbur.database import Repository
from tadabbur.downloader.client import YtDlpClient, YtDlpError
from tadabbur.jobs.paths import normalize_upload_date
from tadabbur.logging import stage_logger, tag
from tadabbur.metadata.series import series_info

logger = stage_logger("discovery")

_STATUS = "DISCOVERED"


@dataclass
class DiscoveryResult:
    discovered: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    sources_checked: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        lines = [
            "[DISCOVER] sources_checked=%d" % len(self.sources_checked),
            "[DISCOVER] discovered=%d duplicates=%d errors=%d"
            % (len(self.discovered), len(self.duplicates), len(self.errors)),
        ]
        for vid in self.discovered:
            lines.append(f"[DISCOVER] new={vid}")
        for err in self.errors:
            lines.append(f"[DISCOVER] error={err}")
        return "\n".join(lines)


def normalize_video_id(raw: str) -> str:
    """Extract a canonical 11-char YouTube video id from a URL or id."""
    vid = raw.strip()
    m = re.search(r"(?:v=|youtu\.be/|shorts/|live/)([\w-]{11})", vid)
    if m:
        return m.group(1)
    if re.fullmatch(r"[\w-]{11}", vid):
        return vid
    raise ValueError(f"cannot normalize video id from {raw!r}")


def build_media_record(source: Source, entry: dict) -> dict:
    """Normalize a raw yt-dlp playlist entry into a media record."""
    raw_id = str(entry.get("id") or "")
    try:
        video_id = normalize_video_id(raw_id)
    except ValueError:
        video_id = raw_id

    url = entry.get("webpage_url") or f"https://www.youtube.com/watch?v={video_id}"
    title = str(entry.get("title") or "(untitled)")
    si = series_info(title)
    return {
        "source_id": source.id,
        "external_id": video_id,
        "url": url,
        "title": title,
        "description": (entry.get("description") or None),
        "uploader": (entry.get("uploader") or entry.get("channel") or None),
        "channel": (entry.get("channel") or source.name),
        "published_at": normalize_upload_date(entry.get("upload_date")),
        "duration": entry.get("duration"),
        "thumbnail_url": (entry.get("thumbnail") or None),
        "series_key": si.folder if si.is_series else None,
        "session_number": si.session_number if si.is_series else None,
        "status": _STATUS,
        "rights_status": source.rights_status,
        "publication_policy": bool(source.publication_policy),
    }


def run_discovery(
    settings: Settings,
    repo: Repository,
    client: YtDlpClient | None = None,
    *,
    source_id: str | None = None,
    dry_run: bool = False,
    max_entries: int = 50,
) -> DiscoveryResult:
    """Discover new media metadata from configured sources."""
    result = DiscoveryResult()
    client = client or YtDlpClient(settings)

    if not client.available():
        logger.error("[DISCOVER] yt-dlp binary not available")
        result.errors.append("yt-dlp binary not available")
        return result

    sources = [s for s in settings.enabled_sources if (source_id is None or s.id == source_id)]
    if source_id and not sources:
        result.errors.append(f"source {source_id!r} not found or disabled")
        return result

    for source in sources:
        result.sources_checked.append(source.id)
        repo.upsert_source(
            source_id=source.id,
            name=source.name,
            channel_url=source.channel_url,
            platform=source.platform,
            channel_id=source.channel_id,
            enabled=source.enabled,
            language=source.language,
            rights_status=source.rights_status,
            download_policy=source.download_policy,
            publication_policy=source.publication_policy,
        )

        try:
            entries = client.discover_channel(source.channel_url, max_entries=max_entries)
        except (YtDlpError, OSError) as exc:
            logger.error("[DISCOVER] source=%s error=%s", source.id, exc)
            result.errors.append(f"{source.id}: {exc}")
            continue

        for entry in entries:
            try:
                record = build_media_record(source, entry)
            except Exception as exc:  # noqa: BLE001 - a bad entry must not kill the run
                logger.warning("[DISCOVER] source=%s skipped entry: %s", source.id, exc)
                continue

            if repo.media_exists(record["source_id"], record["external_id"]):
                result.duplicates.append(record["external_id"])
                continue

            if dry_run:
                logger.info(
                    "[DISCOVER] dry-run new=%s title=%r",
                    record["external_id"],
                    record["title"],
                )
                result.discovered.append(record["external_id"])
                continue

            try:
                repo.insert_media(**record)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "[DISCOVER] insert failed video=%s: %s", record["external_id"], exc
                )
                result.errors.append(f"{record['external_id']}: {exc}")
                continue

            logger.info(
                tag("DISCOVER", "new=%s title=%r source=%s"),
                record["external_id"],
                record["title"],
                source.id,
            )
            result.discovered.append(record["external_id"])

    return result


def fingerprint(record: dict) -> str:
    """Stable fingerprint for a media record (used for cross-checking)."""
    canonical = f"{record.get('source_id')}|{record.get('external_id')}|{record.get('title')}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
