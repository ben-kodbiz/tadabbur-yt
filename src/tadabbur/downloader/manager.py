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
from tadabbur.downloader.diagnose import diagnose_error
from tadabbur.downloader.retry import RetryExhaustedError, retry
from tadabbur.downloader.validator import validate_audio_file, validate_file
from tadabbur.jobs.paths import media_directory, normalize_upload_date, output_template
from tadabbur.logging import stage_logger, tag
from tadabbur.status import (
    AUDIO_PROCESSING,
    DOWNLOADED,
    DOWNLOADING,
    FAILED,
    PROCESSED,
    QUEUED,
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
    """Process queued media items (or a specific video) through the download stage.

    Also recovers items interrupted mid-download (crash recovery): media left
    in DOWNLOADING/AUDIO_PROCESSING are validated; if a usable audio file
    exists they are advanced, otherwise they are reset to QUEUED and retried.
    """
    client = client or YtDlpClient(settings)
    breaker = circuit_breaker or CircuitBreaker(settings.circuit_breaker)

    if video_id:
        row = repo.get_media_by_external_id(video_id)
        candidates = [row] if row is not None else []
    else:
        candidates = repo.list_media_by_status("QUEUED", limit=limit)

    # --- recovery: interrupted downloads left in a transitional state ---
    candidates = _recover_interrupted(settings, repo, candidates)

    candidates = [m for m in candidates if m is not None and m["status"] == "QUEUED"]

    outcomes: list[DownloadOutcome] = []
    for row in candidates:
        outcomes.append(
            _download_one(settings, repo, client, breaker, row, sleep=sleep)
        )
    return outcomes


def _recover_interrupted(
    settings: Settings,
    repo: Repository,
    candidates: list,
) -> list:
    """Validate interrupted items; keep resumable ones, reset broken ones to QUEUED."""
    recovered: list = []
    rows = candidates if candidates else repo._conn.execute(
        "SELECT * FROM media WHERE status IN ('DOWNLOADING','AUDIO_PROCESSING')"
    ).fetchall()

    for row in rows:
        status = row["status"]
        if status == "QUEUED":
            recovered.append(row)
            continue

        audio = repo.get_media_file(int(row["id"]), "audio")
        audio_ok = audio is not None and Path(audio["path"]).exists()
        if status == "AUDIO_PROCESSING" and audio_ok:
            repo.transition_media(int(row["id"]), PROCESSED)
            logger.info(
                "[DOWNLOAD] video=%s recovered: audio already valid", row["external_id"]
            )
            continue  # fully recovered, nothing more to do
        if status == "DOWNLOADING" and audio_ok:
            repo.transition_media(int(row["id"]), PROCESSED)
            logger.info(
                "[DOWNLOAD] video=%s recovered: audio already valid", row["external_id"]
            )
            continue

        # Incomplete output: delete partial media files, reset to QUEUED.
        directory = media_directory(
            settings,
            speaker=row["uploader"] or row["channel"],
            source_id=row["source_id"],
            video_id=row["external_id"],
            published_at=row["published_at"],
        )
        _cleanup_partial_outputs(directory, row["external_id"])
        logger.warning(
            "[DOWNLOAD] video=%s interrupted in %s, resetting to QUEUED",
            row["external_id"], status,
        )
        repo.transition_media(int(row["id"]), QUEUED)
        recovered.append(repo.get_media(int(row["id"])))
    return recovered


def _cleanup_partial_outputs(directory: Path, video_id: str) -> None:
    """Delete partial/incomplete media files for a video id.

    Removes ``.part`` files and any media file smaller than a sanity threshold
    that cannot be a complete download (matches the architect's rule to delete
    incomplete output and retry).
    """
    if not directory.exists():
        return
    for p in directory.iterdir():
        if not p.is_file():
            continue
        name = p.name
        is_part = name.endswith(".part") or ".part." in name
        is_media = p.suffix.lower() in {".mp4", ".webm", ".mkv", ".m4a", ".mp3", ".opus"}
        is_small = is_media and p.stat().st_size < 1_000_000
        if is_part or (video_id in name and is_small):
            logger.info("[DOWNLOAD] removing incomplete file %s", p)
            try:
                p.unlink(missing_ok=True)
            except OSError as exc:  # pragma: no cover
                logger.warning("[DOWNLOAD] could not remove %s: %s", p, exc)


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
            diagnosis = diagnose_error(error)
            breaker.record_failure()
            repo.record_download_attempt(
                media_id=media_id,
                attempt=attempt,
                status="failed",
                ytdlp_version=client.version() if client.available() else None,
                error=diagnosis.summary,
                started_at=started,
            )
            last_error = diagnosis.summary
            logger.warning(
                "[DOWNLOAD] video=%s attempt=%d failed: %s%s",
                vid, attempt, diagnosis.summary,
                f" | hint: {diagnosis.hint}" if diagnosis.hint else "",
            )
            if not diagnosis.is_retryable:
                logger.warning(
                    "[DOWNLOAD] video=%s stopping (non-retryable): %s "
                    "(change proxy in config, then `tadabbur retry --failed`)",
                    vid, diagnosis.summary,
                )
                break
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
    # 1. Metadata-first inspect (never hallucinated source data).
    try:
        info = client.inspect(url)
    except YtDlpError as exc:
        raise exc

    # Enrich the media record with authoritative fields from inspect.
    repo.enrich_media(
        media_id,
        title=info.get("title"),
        description=info.get("description"),
        uploader=info.get("uploader") or info.get("channel"),
        channel=info.get("channel"),
        published_at=normalize_upload_date(info.get("upload_date")),
        duration=info.get("duration"),
        thumbnail_url=info.get("thumbnail"),
    )
    row = repo.get_media(media_id)
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

    meta_path = directory / "metadata.json"
    meta_path.write_text(
        json.dumps(_normalized_metadata(info), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    repo.upsert_media_file(media_id=media_id, kind=KIND_METADATA, path=str(meta_path))

    # 2. Obtain source media.
    #    audio_only: fetch the smallest source and convert to m4a via FFmpeg.
    #    otherwise:  keep the video as-is and extract audio with yt-dlp.
    if settings.download.audio_only:
        audio_file = _download_audio_only(settings, repo, client, directory, tpl, media_id, vid, url)
        video_file = None
    else:
        video_file = _download_video(settings, repo, client, directory, tpl, media_id, vid, url)
        audio_file = _download_audio(settings, repo, client, directory, tpl, media_id, vid, url)

    av = validate_audio_file(audio_file)
    if not av.valid:
        raise YtDlpError(f"audio validation failed: {av.errors}")
    repo.upsert_media_file(
        media_id=media_id, kind=KIND_AUDIO, path=str(audio_file),
        size_bytes=av.size_bytes, mime_type=av.mime_type,
    )
    if video_file is not None:
        v = validate_file(video_file, min_size=1000)
        if v.valid:
            repo.upsert_media_file(
                media_id=media_id, kind=KIND_VIDEO, path=str(video_file),
                size_bytes=v.size_bytes, mime_type=v.mime_type,
            )
        else:
            logger.warning("[DOWNLOAD] video=%s invalid video file: %s", vid, v.errors)
            video_file = None

    # 4. Thumbnail / subtitles handling.
    _record_optional_files(repo, media_id, directory, vid)

    repo.transition_media(media_id, PROCESSED)
    return _DownloadArtifacts(video_path=video_file, audio_path=audio_file)


def _download_video(settings, repo, client, directory, tpl, media_id, vid, url) -> Path | None:
    """Download + keep the source video (or reuse an existing valid one)."""
    keep_video = settings.download.keep_video and not settings.download.audio_only
    existing = _find_existing_valid(directory, vid, settings, video=True)
    if existing is not None:
        logger.info("[DOWNLOAD] video=%s reusing existing video %s", vid, existing.name)
        return existing
    if not keep_video:
        return None
    result = client.download_video(url, tpl)
    if result.exit_code != 0:
        raise YtDlpError(f"video download failed: {result.stderr.strip()[:400]}")
    return _find_downloaded_file(directory, vid)


def _download_audio(settings, repo, client, directory, tpl, media_id, vid, url) -> Path:
    """Extract audio with yt-dlp's native extraction (video kept)."""
    repo.transition_media(media_id, AUDIO_PROCESSING)
    existing = _find_existing_valid(directory, vid, settings, audio=True)
    if existing is not None:
        logger.info("[DOWNLOAD] video=%s reusing existing audio %s", vid, existing.name)
        return existing
    result = client.download_audio(url, tpl)
    if result.exit_code != 0:
        raise YtDlpError(f"audio extraction failed: {result.stderr.strip()[:400]}")
    audio_file = _find_audio_file(directory, vid, settings.download.audio_format)
    if audio_file is None:
        raise YtDlpError(f"audio file not found in {directory}")
    return audio_file


def _download_audio_only(settings, repo, client, directory, tpl, media_id, vid, url) -> Path:
    """Audio-only path: fetch the smallest source (prefer already-m4a/AAC),
    and only convert via FFmpeg when the source is not already canonical.

    Fast path: format 140 is a native m4a/AAC stream — used directly with no
    re-encode. Slow path (fallback bestaudio=opus/webm) is transcoded once.
    """
    from tadabbur.audio import extract_audio

    repo.transition_media(media_id, AUDIO_PROCESSING)

    canonical = directory / f"audio.{settings.download.audio_format}"
    if canonical.exists() and canonical.stat().st_size > 0:
        logger.info("[DOWNLOAD] video=%s reusing canonical audio %s", vid, canonical.name)
        return canonical

    result = client.download_lowest(url, tpl)
    if result.exit_code != 0:
        raise YtDlpError(f"source download failed: {result.stderr.strip()[:400]}")
    logger.info(
        "[DOWNLOAD] video=%s source downloaded in %.1fs rate=%s",
        vid, result.elapsed, result.transfer_rate or "?",
    )

    source = _find_source_file(directory, vid)
    if source is None:
        raise YtDlpError(f"downloaded source not found in {directory}")

    # Fast path: source is already m4a/AAC — keep it as the canonical audio.
    if source.suffix.lower() == f".{settings.download.audio_format}":
        logger.info(
            "[DOWNLOAD] video=%s source already m4a, no transcode needed", vid
        )
        if source != canonical:
            source.replace(canonical)
        return canonical

    # Slow path: transcode opus/webm/etc. to canonical M4A/AAC (idempotent).
    extracted = extract_audio(source, canonical, audio_format=settings.download.audio_format)
    if not extracted.success:
        raise YtDlpError(f"ffmpeg conversion failed for {source}")

    # Free space unless the operator asked to keep the source video.
    if not settings.download.keep_video:
        logger.info("[DOWNLOAD] video=%s removing source %s (audio-only)", vid, source.name)
        try:
            source.unlink(missing_ok=True)
        except OSError as exc:  # pragma: no cover
            logger.warning("[DOWNLOAD] could not remove source %s: %s", source, exc)

    return canonical


def _find_source_file(directory: Path, vid: str) -> Path | None:
    """Find the yt-dlp-downloaded source media file (smallest format)."""
    if not directory.exists():
        return None
    candidates = []
    for p in directory.iterdir():
        if not p.is_file() or vid not in p.name:
            continue
        if p.name.endswith(".part"):
            continue
        if p.suffix.lower() in {".mp4", ".webm", ".mkv", ".m4a", ".mp3", ".opus"}:
            candidates.append(p)
    if not candidates:
        return None
    # yt-dlp writes "<title> [id].<ext>"; pick the actual media file.
    return min(candidates, key=lambda p: p.stat().st_size)


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


def _find_existing_valid(
    directory: Path,
    vid: str,
    settings: Settings,
    *,
    video: bool = False,
    audio: bool = False,
) -> Path | None:
    """Return an already-downloaded valid file for this video, or None.

    Idempotency: avoids re-downloading (and avoids yt-dlp range-resume errors
    on complete files) when a valid output already exists on disk.
    """
    if not directory.exists():
        return None
    for p in sorted(directory.iterdir()):
        if not p.is_file() or vid not in p.name:
            continue
        if audio and p.suffix.lower() in {".m4a", ".mp3", ".opus", ".aac"}:
            return p
        if video and p.suffix.lower() in {".mp4", ".mkv", ".webm"}:
            # Confirm it is a real, sizable file rather than a stray partial.
            if p.stat().st_size >= 100_000:
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
