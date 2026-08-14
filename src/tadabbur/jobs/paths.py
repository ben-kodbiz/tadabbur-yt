"""Deterministic archival path layout.

Layout: data/media/<speaker>/<year>/<month>/<source-id>/<VIDEO_ID>/
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from tadabbur.config.models import Settings

_SAFE = re.compile(r"[^a-z0-9._-]+", re.IGNORECASE)


def slugify(value: str | None) -> str:
    """Produce a safe directory segment from an arbitrary string."""
    if not value:
        return "unknown"
    slug = _SAFE.sub("-", value.strip().lower())
    return slug.strip("-") or "unknown"


def _year_month(published_at: str | None) -> tuple[str, str]:
    if published_at:
        try:
            dt = datetime.fromisoformat(published_at)
            return dt.strftime("%Y"), dt.strftime("%m")
        except ValueError:
            pass
    return "unknown", "unknown"


def media_directory(
    settings: Settings,
    *,
    speaker: str | None,
    source_id: str,
    video_id: str,
    published_at: str | None = None,
) -> Path:
    """Return the archival directory for a media item, creating nothing."""
    base = settings.storage.resolved_media_dir
    if not base.is_absolute():
        base = settings.project_dir / base
    year, month = _year_month(published_at)
    return base / slugify(speaker) / year / month / slugify(source_id) / video_id


def output_template(
    settings: Settings,
    *,
    speaker: str | None,
    source_id: str,
    video_id: str,
    published_at: str | None = None,
) -> str:
    """yt-dlp ``--output`` template that resolves into the archival layout."""
    directory = media_directory(
        settings, speaker=speaker, source_id=source_id, video_id=video_id,
        published_at=published_at,
    )
    return str(directory / "%(title)s [%(id)s].%(ext)s")
