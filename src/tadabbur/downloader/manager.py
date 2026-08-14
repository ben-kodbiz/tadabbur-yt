"""Download manager: orchestrates the download pipeline for queued media."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from tadabbur.config.models import Settings
from tadabbur.database import Repository
from tadabbur.downloader.circuit_breaker import CircuitBreaker
from tadabbur.downloader.client import YtDlpClient, YtDlpError
from tadabbur.downloader.retry import RetryExhaustedError, retry
from tadabbur.downloader.validator import validate_audio_file, validate_file
from tadabbur.jobs.paths import media_directory, output_template
from tadabbur.logging import stage_logger, tag
from tadabbur.status import (
    AUDIO_PROCESSING,
    DOWNLOADED,
    DOWNLOADING,
    FAILED,
    PROCESSED,
)

logger = stage_logger("download")

# File kinds recorded in media_files.
KIND_VIDEO = "video"
KIND_AUDIO = "audio"
KIND_METADATA = "metadata"
KIND_THUMBNAIL = "thumbnail"
KIND_SUBTITLES = "subtitles"


@dataclass
class DownloadOutcome:
    media_id: int
    video_id: str
    status: str
    error: str | None = None
    video_path: Path | None = None
    audio_path: Path | None = None
    attempts: int = 0

    def __str__(self) -> str:
        return (
            f"[DOWNLOAD] video={self.video_id} status={self.status} "
            f"attempts={self.attempts}"
            + (f" error={self.error}" if self.error else "")
        )


def _is_retryable(exc: Exception) -> bool:
    return isinstance(exc, (YtDlpError, RetryExhaustedError, OSError, TimeoutError))


def _safe_slug(text: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", text.lower()).strip("-") or "video"


def run_download(
    settings: Settings,
    repo: Repository,
    client: YtDlpClient | None = None,
    *,
    video_id: str | None = None,
    limit: int = 1,
    circuit_breaker: CircuitBreaker | None = None,
    sleep=None,
) -> list[DownloadOutcome]:
    """Process queued media items (or a specific video) through the download stage."""
    client = client or YtDlpClient(settings)
    breaker = circuit_breaker or CircuitBreaker(settings.circuit_breaker)

    queued = (
        [repo.get_media_by_external_id(video_id)]
        if video_id
        else repo.list_media_by_status("QUEUED", limit=limit)
    )
    queued = [m for m in queued if m is not None and m["status"] == "QUEUED"]

    outcomes: list[DownloadOutcome] = []
    for row in queued:
        outcomes.append(
            _download_one(settings, repo, client, breaker, row, sleep=sleep)
        )
    return outcomes


def _download_one(
    settings: Settings,
    repo: Repository,
    client: YtDlpClient,
    breaker: CircuitBreaker,
    row,
    *,
    sleep=None,
) -> DownloadOutcome:
    media_id = int(row["id"])
    vid = row["external_id"]
    url = row["url"]
    source = repo.get_source(row["source_id"])

    # Broken-circuit guard: do not even attempt.
    if not breaker.allow_request():
        msg = "circuit breaker open (cooldown)"
        logger.warning("[DOWNLOAD] video=%s %s", vid, msg)
        repo.transition_media(media_id, FAILED, error_message=msg)
        return DownloadOutcome(media_id, vid, FAILED, error=msg)

    repo.transition_media(media_id, DOWNLOADING)
    logger.info(tag("DOWNLOAD", "video=%s attempt started"), vid)

    max_attempts = settings.backoff.max_attempts
    attempt = 0
    last_error: str | None = None

    # Build a per-item attempt counter from the download_attempts table.
    attempt = repo.count_media_failures(media_id) + 1

    while attempt <= max_attempts:
        started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        result = None
        error: str | None = None
        try:
            result = _perform_download(settings, repo, client, row, source, media_id, vid, url)
            breaker.record_success()
            repo.record_download_attempt(
                media_id=media_id,
                attempt=attempt,
                status="success",
                exit_code=0,
                ytdlp_version=client.version(),
                started_at=started,
            )
            logger.info("[DOWNLOAD] video=%s success", vid)
            return DownloadOutcome(
                media_id, vid, result.final_status,
                video_path=result.video_path,
                audio_path=result.audio_path, attempts=attempt,
            )
        except (YtDlpError, OSError, TimeoutError) as exc:
            error = str(exc)
            breaker.record_failure()
            repo.record_download_attempt(
                media_id=media_id,
                attempt=attempt,
                status="failed",
                ytdlp_version=client.version() if client.available() else None,
                error=error,
                started_at=started,
            )
            last_error = error
            logger.warning("[DOWNLOAD] video=%s attempt=%d failed: %s", vid, attempt, error)
            if attempt >= max_attempts:
                break
            delay = _compute_backoff(settings, attempt)
            if sleep is not None:
                sleep(delay)
            else:
                _real_sleep(delay)
            attempt += 1
        except Exception as exc:  # noqa: BLE001 - unexpected
            last_error = str(exc)
            logger.exception("[DOWNLOAD] video=%s unexpected error", vid)
            break

    repo.transition_media(media_id, FAILED, error_message=last_error)
    return DownloadOutcome(media_id, vid, FAILED, error=last_error, attempts=attempt)


@dataclass
class _DownloadArtifacts:
    video_path: Path | None = None
    audio_path: Path | None = None
    final_status: str = PROCESSED


def _perform_download(
    settings: Settings,
    repo: Repository,
    client: YtDlpClient,
    row,
    source,
    media_id: int,
    vid: str,
    url: str,
) -> _DownloadArtifacts:
    directory = media_directory(
        settings,
        speaker=row["uploader"] or row["channel"],
        source_id=row["source_id"],
        video_id=vid,
        published_at=row["published_at"],
    )
    directory.mkdir(parents=True, exist_ok=True)

    tpl = output_template(
        settings,
        speaker=row["uploader"] or row["channel"],
        source_id=row["source_id"],
        video_id=vid,
        published_at=row["published_at"],
    )

    # 1. Metadata-first inspect (never hallucinated source data).
    try:
        info = client.inspect(url)
    except YtDlpError as exc:
        raise exc

    meta_path = directory / "metadata.json"
    meta_path.write_text(
        json.dumps(_normalized_metadata(info), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    repo.upsert_media_file(media_id=media_id, kind=KIND_METADATA, path=str(meta_path))

    # 2. Download video (keeps original source video when configured).
    video_result = None
    video_file: Path | None = None
    if settings.download.keep_video or True:
        video_result = client.download_video(url, tpl)
        if video_result.exit_code != 0:
            raise YtDlpError(f"video download failed: {video_result.stderr.strip()[:400]}")
        video_file = _find_downloaded_file(directory, vid)
        if video_file is not None:
            v = validate_file(video_file, min_size=1000)
            if v.valid:
                repo.upsert_media_file(
                    media_id=media_id, kind=KIND_VIDEO, path=str(video_file),
                    size_bytes=v.size_bytes, mime_type=v.mime_type,
                )
            else:
                logger.warning("[DOWNLOAD] video=%s invalid file: %s", vid, v.errors)

    # 3. Extract audio via yt-dlp's native extraction (FFmpeg).
    repo.transition_media(media_id, AUDIO_PROCESSING)
    audio_result = client.download_audio(url, tpl)
    if audio_result.exit_code != 0:
        raise YtDlpError(f"audio extraction failed: {audio_result.stderr.strip()[:400]}")
    audio_file = _find_audio_file(directory, vid, settings.download.audio_format)
    if audio_file is None:
        raise YtDlpError(f"audio file not found in {directory}")
    av = validate_audio_file(audio_file)
    if not av.valid:
        raise YtDlpError(f"audio validation failed: {av.errors}")

    repo.upsert_media_file(
        media_id=media_id, kind=KIND_AUDIO, path=str(audio_file),
        size_bytes=av.size_bytes, mime_type=av.mime_type,
    )

    # 4. Thumbnail / subtitles handling.
    _record_optional_files(repo, media_id, directory, vid)

    repo.transition_media(media_id, PROCESSED)
    return _DownloadArtifacts(video_path=video_file, audio_path=audio_file)


def _normalized_metadata(info: dict) -> dict:
    """Select the authoritative source fields only (no model-generated values)."""
    return {
        "id": info.get("id"),
        "url": info.get("webpage_url"),
        "title": info.get("title"),
        "description": info.get("description"),
        "channel": info.get("channel"),
        "channel_id": info.get("channel_id"),
        "uploader": info.get("uploader"),
        "upload_date": info.get("upload_date"),
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "uploader_id": info.get("uploader_id"),
        "view_count": info.get("view_count"),
        "like_count": info.get("like_count"),
        "categories": info.get("categories"),
    }


def _find_downloaded_file(directory: Path, vid: str) -> Path | None:
    for p in directory.iterdir():
        if vid in p.name and p.suffix.lower() in {".mp4", ".mkv", ".webm"}:
            return p
    return None


def _find_audio_file(directory: Path, vid: str, audio_format: str) -> Path | None:
    suffix = f".{audio_format.lower()}"
    for p in directory.iterdir():
        if vid in p.name and p.suffix.lower() == suffix:
            return p
    # fallback: any audio file in the directory
    for p in directory.iterdir():
        if vid in p.name and p.suffix.lower() in {".m4a", ".mp3", ".opus", ".aac"}:
            return p
    return None


def _record_optional_files(repo: Repository, media_id: int, directory: Path, vid: str) -> None:
    for p in directory.iterdir():
        if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"} and p.name not in {
            _safe_slug("thumb")
        }:
            repo.upsert_media_file(media_id=media_id, kind=KIND_THUMBNAIL, path=str(p))
        elif p.suffix.lower() in {".vtt", ".srt", ".ttml"}:
            repo.upsert_media_file(media_id=media_id, kind=KIND_SUBTITLES, path=str(p))


def _compute_backoff(settings: Settings, attempt: int) -> float:
    base = settings.backoff.base_delay
    mult = settings.backoff.multiplier
    import random

    delay = min(base * (mult ** (attempt - 1)), settings.backoff.max_delay)
    jitter = delay * settings.backoff.jitter
    return max(0.0, delay + random.uniform(-jitter, jitter))


def _real_sleep(seconds: float) -> None:
    import time

    time.sleep(seconds)
