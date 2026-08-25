"""Upload pipeline download stage: yt-dlp with resume, provenance, checksums.

Layout (upload_yt_pipeline.md §8, §21):
    incoming/originals/<source_key>/<original_media_id>/
        source.json
        <source_key>__<media_id>__original.<ext>
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from tadabbur.config.models import Settings
from tadabbur.downloader.client import YtDlpClient, YtDlpError
from tadabbur.logging import stage_logger
from tadabbur.uploader.config import UploadPipelineSettings
from tadabbur.uploader.models import FailureCategory, MediaState
from tadabbur.uploader.repository import UploaderRepository

logger = stage_logger("up-download")

MIN_FILE_BYTES = 1_000


def item_directory(
    settings: Settings,
    up: UploadPipelineSettings,
    *,
    source_key: str,
    media_id: str,
) -> Path:
    base = settings.resolve_path(up.resolve_incoming(settings.project_dir))
    return base / source_key / media_id


def file_stem(source_key: str, media_id: str, title: str | None = None) -> str:
    """§21 identity-based stem; slug suffix is convenience only."""
    from tadabbur.jobs.paths import slugify

    return f"{source_key}__{media_id}__{slugify(title or 'untitled')}"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class DownloadResult:
    ok: bool
    original_path: Path | None = None
    checksum: str | None = None
    error: str | None = None
    category: str = FailureCategory.UNKNOWN_ERROR


def download_item(
    ingest_settings: Settings,
    up_settings: UploadPipelineSettings,
    repo: UploaderRepository,
    client: YtDlpClient,
    media_item_id: int,
) -> DownloadResult:
    """Download one approved item into its identity-based directory.

    Idempotent: an existing valid original is reused (never re-downloaded).
    """
    row = repo.get_media_item(media_item_id)
    if row is None:
        return DownloadResult(False, error="item not found")
    src = repo.get_source_by_id(row["source_id"])
    source_key = src["source_key"] if src else "unknown-source"
    media_id = row["original_media_id"]

    directory = item_directory(
        ingest_settings, up_settings, source_key=source_key, media_id=media_id
    )
    directory.mkdir(parents=True, exist_ok=True)

    existing = _find_existing_original(directory)
    if existing is not None and existing.stat().st_size >= MIN_FILE_BYTES:
        logger.info("[UP-DOWNLOAD] item=%s reusing %s", media_item_id, existing.name)
        checksum = (
            sha256_of(existing) if up_settings.storage.verify_sha256 else None
        )
        _record_file(repo, media_item_id, existing, checksum)
        return DownloadResult(True, original_path=existing, checksum=checksum)

    # Provenance metadata first (§4/§14): even a failed download leaves evidence.
    try:
        info = client.inspect(row["original_url"])
    except YtDlpError as exc:
        return DownloadResult(False, error=str(exc),
                              category=FailureCategory.SOURCE_UNAVAILABLE)

    source_json = directory / "source.json"
    source_json.write_text(json.dumps(_normalized(info), indent=2, ensure_ascii=False),
                           encoding="utf-8")

    tpl = str(directory / f"{file_stem(source_key, media_id, info.get('title'))}__original.%(ext)s")
    result = client.download_lowest(row["original_url"], tpl)
    if not result.success:
        err = result.stderr.strip()[:400] if result.stderr else f"exit={result.exit_code}"
        category = FailureCategory.NETWORK_ERROR
        if "sign-in" in err.lower() or "confirm" in err.lower():
            category = FailureCategory.AUTH_ERROR
        return DownloadResult(False, error=err, category=category)

    original = _find_existing_original(directory)
    if original is None or original.stat().st_size < MIN_FILE_BYTES:
        return DownloadResult(False, error="download produced no valid file",
                              category=FailureCategory.FILE_CORRUPT)

    checksum = sha256_of(original)
    (directory / "checksum.sha256").write_text(f"{checksum}  {original.name}\n",
                                               encoding="utf-8")
    _record_file(repo, media_item_id, original, checksum)
    logger.info("[UP-DOWNLOAD] item=%s downloaded %s (%d bytes)",
                media_item_id, original.name, original.stat().st_size)
    return DownloadResult(True, original_path=original, checksum=checksum)


def _record_file(repo: UploaderRepository, media_item_id: int, path: Path, checksum: str | None) -> None:
    repo.upsert_file(
        media_item_id=media_item_id,
        file_type="original_media",
        path=path,
        extension=path.suffix.lstrip("."),
        size_bytes=path.stat().st_size,
        sha256=checksum,
    )


def _find_existing_original(directory: Path) -> Path | None:
    if not directory.exists():
        return None
    for p in sorted(directory.iterdir()):
        if p.is_file() and "__original." in p.name and ".part" not in p.name:
            return p
    return None


def _normalized(info: dict) -> dict:
    return {
        "id": info.get("id"),
        "url": info.get("webpage_url"),
        "title": info.get("title"),
        "channel": info.get("channel"),
        "uploader": info.get("uploader"),
        "upload_date": info.get("upload_date"),
        "duration": info.get("duration"),
        "license": info.get("license"),
        "view_count": info.get("view_count"),
    }


def advance_after_download(repo: UploaderRepository, media_item_id: int, ok: bool) -> bool:
    """State-machine bookkeeping after a download attempt.

    Callers must have moved the item into DOWNLOADING first.
    """
    if ok:
        return repo.transition(media_item_id, MediaState.DOWNLOADED)
    return repo.transition(media_item_id, MediaState.DOWNLOAD_RETRY)
