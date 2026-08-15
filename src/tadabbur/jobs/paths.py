"""Deterministic archival path layout.

Layout (human-friendly, organised by ustaz then series):

    data/media/<ustaz>/
        <series-or-title>/          # e.g. "Surah Al-An'am" (one folder per series)
            01 - <title>.m4a
            02 - <title>.m4a
        <single-video-title>/
            audio.m4a

Determined by :func:`tadabbur.metadata.series.series_info`.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from tadabbur.config.models import Settings

_SAFE = re.compile(r"[^a-z0-9._-]+", re.IGNORECASE)
_DATE_PATTERN = re.compile(r"^(\d{4})(\d{2})(\d{2})$")


def normalize_upload_date(raw: str | None) -> str | None:
    """Convert yt-dlp ``upload_date`` (YYYYMMDD) to ISO date (YYYY-MM-DD)."""
    if not raw:
        return None
    m = _DATE_PATTERN.match(raw.strip())
    if not m:
        return None
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"


def slugify(value: str | None) -> str:
    """Produce a safe directory segment from an arbitrary string."""
    if not value:
        return "unknown"
    slug = _SAFE.sub("-", value.strip().lower())
    return slug.strip("-") or "unknown"


def media_root(settings: Settings) -> Path:
    base = settings.storage.resolved_media_dir
    if not base.is_absolute():
        base = settings.project_dir / base
    return base


def series_directory(
    settings: Settings,
    *,
    speaker: str | None,
    series_folder: str,
) -> Path:
    """Return the directory for a series/single video under an ustaz folder."""
    base = media_root(settings)
    return base / slugify(speaker) / slugify(series_folder)


def media_directory(
    settings: Settings,
    *,
    speaker: str | None,
    source_id: str,
    video_id: str,
    published_at: str | None = None,
    series_folder: str | None = None,
) -> Path:
    """Return the archival directory for a media item.

    ``series_folder`` overrides the per-video folder (used for series grouping).
    """
    folder = series_folder or f"{video_id}-{source_id}"
    return series_directory(settings, speaker=speaker, series_folder=folder)


def output_template(
    settings: Settings,
    *,
    speaker: str | None,
    source_id: str,
    video_id: str,
    published_at: str | None = None,
    series_folder: str | None = None,
) -> str:
    """yt-dlp ``--output`` template that resolves into the archival layout."""
    directory = media_directory(
        settings, speaker=speaker, source_id=source_id, video_id=video_id,
        published_at=published_at, series_folder=series_folder,
    )
    return str(directory / "%(title)s [%(id)s].%(ext)s")
