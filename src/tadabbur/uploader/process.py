"""Stage runner: drive one item through download -> audio -> render -> ready.

fix_me.md hardening:
- rights gate BEFORE any processing (#3)
- artifact-aware resume: validate before skip, rebuild when invalid (#4)
- independent MP4 validation gates READY_FOR_UPLOAD (#5/#6)
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from tadabbur.config.models import Settings
from tadabbur.downloader.client import YtDlpClient
from tadabbur.logging import stage_logger
from tadabbur.uploader.audio_processing import process_audio, record_audio
from tadabbur.uploader.config import UploadPipelineSettings
from tadabbur.uploader.download import download_item
from tadabbur.uploader.models import APPROVED_FOR_UPLOAD, MediaState
from tadabbur.uploader.render import record_video, render_card_video
from tadabbur.uploader.repository import UploaderRepository
from tadabbur.uploader.validator import (
    validate_archive_audio,
    validate_original,
    validate_youtube_video,
)

logger = stage_logger("up-process")


@dataclass
class ProcessOutcome:
    ok: bool
    stage: str = ""
    detail: str = ""

    def __str__(self) -> str:
        status = "OK" if self.ok else f"FAIL at {self.stage}"
        return f"[UP-PROCESS] item stage={self.stage} {status} {self.detail}".rstrip()


def _advance(repo: UploaderRepository, mid: int, new_state: str) -> bool:
    if not repo.transition(mid, new_state):
        logger.error("[UP-PROCESS] item=%s invalid transition to %s", mid, new_state)
        return False
    return True


def check_rights_gate(row) -> ProcessOutcome | None:
    """#3: gate automatic processing on explicit publishing authorization."""
    status = row["rights_status"]
    if status in APPROVED_FOR_UPLOAD:
        return None
    if status == "upload_not_authorized":
        return ProcessOutcome(False, stage="rights",
                              detail="upload_not_authorized — item blocked from processing")
    # unknown / manual_review_required
    return ProcessOutcome(
        False, stage="rights",
        detail=f"rights_status={status} requires review before processing "
               f"(use: upipeline review approve {row['id']} --status ...)",
    )


def block_unauthorized(repo: UploaderRepository, media_item_id: int) -> bool:
    """Move an unauthorized item to BLOCKED via RIGHTS_REVIEW. Never deletes."""
    row = repo.get_media_item(media_item_id)
    if row is None:
        return False
    if row["state"] == MediaState.DISCOVERED:
        repo.transition(media_item_id, MediaState.RIGHTS_REVIEW)
    if repo.get_media_item(media_item_id)["state"] == MediaState.RIGHTS_REVIEW:
        return repo.transition(media_item_id, MediaState.BLOCKED)
    return False


def process_item(
    ingest_settings: Settings,
    up_settings: UploadPipelineSettings,
    repo: UploaderRepository,
    media_item_id: int,
    *,
    client: YtDlpClient | None = None,
) -> ProcessOutcome:
    """Run all processing stages for one item.

    Resumable (artifact-aware): each stage validates its artifact first and
    only rebuilds when the artifact is missing or invalid.
    """
    row = repo.get_media_item(media_item_id)
    if row is None:
        return ProcessOutcome(False, stage="lookup", detail="item not found")

    # ---- P0-1: rights gate -------------------------------------------------
    gate = check_rights_gate(row)
    if gate is not None:
        if row["rights_status"] == "upload_not_authorized":
            block_unauthorized(repo, media_item_id)
            repo.record_event(media_item_id, "RIGHTS_BLOCKED",
                              message="blocked by rights gate during processing")
        return gate

    # Already processed? Verify artifacts still hold and report success.
    if row["state"] in {MediaState.READY_FOR_UPLOAD, MediaState.UPLOAD_QUEUED}:
        from tadabbur.uploader.validator import validate_youtube_video as _vyv

        mp4 = repo.get_file(media_item_id, "youtube_mp4")
        if mp4 and _vyv(Path(mp4["path"])).ok:
            return ProcessOutcome(True, stage="already_ready",
                                  detail="artifacts valid; nothing to do")

    src = repo.get_source_by_id(row["source_id"])
    source_key = src["source_key"] if src else "unknown-source"
    media_id = row["original_media_id"]

    # ---- locate / validate / fetch original --------------------------------
    original = repo.get_file(media_item_id, "original_media")
    original_path = Path(original["path"]) if original else None

    if original_path is not None and original_path.exists():
        report = validate_original(original_path)
        if not report.ok:
            logger.warning(
                "[UP-PROCESS] item=%s invalid original (%s); redownloading",
                media_item_id, report.errors,
            )
            try:
                original_path.unlink(missing_ok=True)
            except OSError:
                pass
            original_path = None

    if original_path is None:
        if not _advance(repo, media_item_id, MediaState.DOWNLOADING):
            return ProcessOutcome(False, stage="state", detail="cannot enter DOWNLOADING")
        repo.record_event(media_item_id, "DOWNLOAD_STARTED")
        dl = download_item(ingest_settings, up_settings, repo,
                           client or YtDlpClient(ingest_settings), media_item_id)
        if not dl.ok:
            repo.record_event(media_item_id, "DOWNLOAD_FAILED",
                              message=dl.error, error_category=dl.category)
            return ProcessOutcome(False, stage="download", detail=dl.error or "")
        repo.record_event(media_item_id, "DOWNLOAD_COMPLETED")

    original = repo.get_file(media_item_id, "original_media")
    if original is None or not Path(original["path"]).exists():
        return ProcessOutcome(False, stage="download", detail="no original on record")
    original_path = Path(original["path"])

    # Record the original checksum for duplicate detection (P1).
    checksum = hashlib.sha256(original_path.read_bytes()).hexdigest()
    if row["original_sha256"] != checksum:
        repo.set_original_sha256(media_item_id, checksum)

    # Walk to DOWNLOADED (items may start at DISCOVERED or DOWNLOAD_PENDING).
    state_now = repo.get_media_item(media_item_id)["state"]
    if state_now == MediaState.DISCOVERED:
        # Rights gate already passed above, so advancing through review is safe.
        if not _advance(repo, media_item_id, MediaState.RIGHTS_REVIEW):
            return ProcessOutcome(False, stage="state", detail="cannot enter RIGHTS_REVIEW")
        if not _advance(repo, media_item_id, MediaState.DOWNLOAD_PENDING):
            return ProcessOutcome(False, stage="state", detail="cannot enter DOWNLOAD_PENDING")
    if repo.get_media_item(media_item_id)["state"] == MediaState.DOWNLOAD_PENDING:
        if not _advance(repo, media_item_id, MediaState.DOWNLOADING):
            return ProcessOutcome(False, stage="state", detail="cannot enter DOWNLOADING")
    if repo.get_media_item(media_item_id)["state"] == MediaState.DOWNLOADING:
        if not _advance(repo, media_item_id, MediaState.DOWNLOADED):
            return ProcessOutcome(False, stage="state", detail="cannot mark DOWNLOADED")

    # ---- archive audio derivative (artifact-aware) -------------------------
    # Always record the processing stage transition, even when the artifact
    # is reused — the machine requires it and the audit stays truthful.
    if not _advance(repo, media_item_id, MediaState.AUDIO_PROCESSING):
        return ProcessOutcome(False, stage="state", detail="cannot enter AUDIO_PROCESSING")

    stem = f"{source_key}__{media_id}"
    out_dir = original_path.parent
    profile = up_settings.get_audio_profile()

    existing_opus = out_dir / f"{stem}__audio.opus"
    src_duration = _probe_duration(original_path)
    audio_res = None
    if existing_opus.exists():
        report = validate_archive_audio(
            existing_opus, expected_duration=src_duration,
            codec=profile.codec, channels=profile.channels,
            sample_rate=profile.sample_rate,
        )
        if report.ok:
            logger.info("[UP-PROCESS] item=%s reusing valid opus", media_item_id)
            repo.record_event(media_item_id, "AUDIO_REUSED",
                              message=existing_opus.name)
            audio_res = _reuse(existing_opus)
        else:
            logger.warning("[UP-PROCESS] item=%s invalid opus (%s); re-encoding",
                           media_item_id, report.errors)
            try:
                existing_opus.unlink(missing_ok=True)  # remove corrupt artifact
            except OSError:
                pass

    if audio_res is None:
        repo.record_event(media_item_id, "AUDIO_STARTED")
        audio_res = process_audio(original_path, out_dir, stem, profile)
        if not audio_res.ok:
            repo.record_event(media_item_id, "AUDIO_FAILED",
                              message=audio_res.error, error_category=audio_res.category)
            return ProcessOutcome(False, stage="audio", detail=audio_res.error or "")
        record_audio(repo, media_item_id, audio_res, None)
        repo.record_event(media_item_id, "AUDIO_COMPLETED")

    # ---- youtube mp4 (artifact-aware + attribution card) -------------------
    if not _advance(repo, media_item_id, MediaState.AUDIO_READY):
        return ProcessOutcome(False, stage="state", detail="cannot enter AUDIO_READY")
    if not _advance(repo, media_item_id, MediaState.VIDEO_RENDERING):
        return ProcessOutcome(False, stage="state", detail="cannot enter VIDEO_RENDERING")

    speaker = row["uploader_name"] or (src["name"] if src else "") or "unknown"
    render_profile = up_settings.get_render_profile()

    existing_mp4 = out_dir / f"{stem}__youtube.mp4"
    render_res = None
    if existing_mp4.exists():
        report = validate_youtube_video(
            existing_mp4, expected_duration=_probe_duration(audio_res.audio_path),
            width=render_profile.width, height=render_profile.height,
        )
        if report.ok:
            logger.info("[UP-PROCESS] item=%s reusing valid mp4", media_item_id)
            render_res = _reuse_mp4(existing_mp4)
        else:
            logger.warning("[UP-PROCESS] item=%s invalid mp4 (%s); re-rendering",
                           media_item_id, report.errors)
            try:
                existing_mp4.unlink(missing_ok=True)
            except OSError:
                pass

    if render_res is None:
        repo.record_event(media_item_id, "VIDEO_STARTED")
        render_res = render_card_video(
            audio_res.audio_path, out_dir, stem, render_profile,
            title=row["original_title"] or media_id,
            source_name=speaker,
        )
        if not render_res.ok or render_res.video_path is None:
            return ProcessOutcome(False, stage="render", detail=render_res.error or "")
        record_video(repo, media_item_id, render_res.video_path)
        repo.record_event(media_item_id, "VIDEO_COMPLETED")

    # ---- validation gate (#6): READY_FOR_UPLOAD only after success ---------
    if not _advance(repo, media_item_id, MediaState.VALIDATION):
        return ProcessOutcome(False, stage="state", detail="cannot enter VALIDATION")

    final = validate_youtube_video(
        render_res.video_path,
        expected_duration=_probe_duration(audio_res.audio_path),
        width=render_profile.width, height=render_profile.height,
    )
    if not final.ok:
        repo.record_event(media_item_id, "VALIDATION_FAILED",
                          message="; ".join(final.errors),
                          error_category="VALIDATION_ERROR")
        if not _advance(repo, media_item_id, MediaState.PROCESSING_RETRY):
            return ProcessOutcome(False, stage="validation", detail="; ".join(final.errors))
        return ProcessOutcome(False, stage="validation", detail="; ".join(final.errors))

    if not _advance(repo, media_item_id, MediaState.READY_FOR_UPLOAD):
        return ProcessOutcome(False, stage="state", detail="cannot become READY_FOR_UPLOAD")
    repo.record_event(media_item_id, "VALIDATION_PASSED", new_state="READY_FOR_UPLOAD")

    return ProcessOutcome(True, stage="ready",
                          detail=f"video={render_res.video_path.name}")


@dataclass
class _ReuseResult:
    ok: bool = True
    audio_path: Path | None = None
    video_path: Path | None = None


def _reuse(path: Path) -> _ReuseResult:
    return _ReuseResult(ok=True, audio_path=path)


def _reuse_mp4(path: Path) -> _ReuseResult:
    return _ReuseResult(ok=True, video_path=path)


def _probe_duration(path: Path) -> float | None:
    from tadabbur.audio.ffmpeg import probe_duration

    return probe_duration(path)
