"""Stage runner: drive one item through download -> audio -> render -> ready."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tadabbur.config.models import Settings
from tadabbur.downloader.client import YtDlpClient
from tadabbur.logging import stage_logger
from tadabbur.uploader.audio_processing import process_audio, record_audio
from tadabbur.uploader.config import UploadPipelineSettings
from tadabbur.uploader.download import download_item
from tadabbur.uploader.models import MediaState
from tadabbur.uploader.render import record_video, render_card_video
from tadabbur.uploader.repository import UploaderRepository

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


def process_item(
    ingest_settings: Settings,
    up_settings: UploadPipelineSettings,
    repo: UploaderRepository,
    media_item_id: int,
    *,
    client: YtDlpClient | None = None,
) -> ProcessOutcome:
    """Run all processing stages for one item. Resumable: completed stages
    are detected by their artifacts and skipped."""
    row = repo.get_media_item(media_item_id)
    if row is None:
        return ProcessOutcome(False, stage="lookup", detail="item not found")
    src = repo.get_source_by_id(row["source_id"])
    source_key = src["source_key"] if src else "unknown-source"
    media_id = row["original_media_id"]

    # ---- locate / fetch original ------------------------------------------
    original = repo.get_file(media_item_id, "original_media")
    have_original = original is not None and Path(original["path"]).exists()

    if not have_original:
        if not _advance(repo, media_item_id, MediaState.DOWNLOADING):
            return ProcessOutcome(False, stage="state", detail="cannot enter DOWNLOADING")
        dl = download_item(ingest_settings, up_settings, repo,
                           client or YtDlpClient(ingest_settings), media_item_id)
        if not dl.ok:
            return ProcessOutcome(False, stage="download", detail=dl.error or "")

    original = repo.get_file(media_item_id, "original_media")
    if original is None or not Path(original["path"]).exists():
        return ProcessOutcome(False, stage="download", detail="no original on record")
    original_path = Path(original["path"])

    # Walk to DOWNLOADED (imported items start at DOWNLOAD_PENDING).
    state_now = repo.get_media_item(media_item_id)["state"]
    if state_now == MediaState.DOWNLOAD_PENDING:
        if not _advance(repo, media_item_id, MediaState.DOWNLOADING):
            return ProcessOutcome(False, stage="state", detail="cannot enter DOWNLOADING")
    if repo.get_media_item(media_item_id)["state"] == MediaState.DOWNLOADING:
        if not _advance(repo, media_item_id, MediaState.DOWNLOADED):
            return ProcessOutcome(False, stage="state", detail="cannot mark DOWNLOADED")

    if not _advance(repo, media_item_id, MediaState.AUDIO_PROCESSING):
        return ProcessOutcome(False, stage="state", detail="cannot enter AUDIO_PROCESSING")

    # ---- archive audio derivative -----------------------------------------
    stem = f"{source_key}__{media_id}"
    out_dir = original_path.parent
    audio_res = process_audio(original_path, out_dir, stem,
                              up_settings.get_audio_profile())
    if not audio_res.ok:
        return ProcessOutcome(False, stage="audio", detail=audio_res.error or "")
    import hashlib

    checksum = hashlib.sha256(audio_res.audio_path.read_bytes()).hexdigest()
    record_audio(repo, media_item_id, audio_res, checksum)

    # ---- youtube mp4 --------------------------------------------------------
    if not _advance(repo, media_item_id, MediaState.AUDIO_READY):
        return ProcessOutcome(False, stage="state", detail="cannot enter AUDIO_READY")
    if not _advance(repo, media_item_id, MediaState.VIDEO_RENDERING):
        return ProcessOutcome(False, stage="state", detail="cannot enter VIDEO_RENDERING")

    render_res = render_card_video(
        audio_res.audio_path, out_dir, stem,
        up_settings.get_render_profile(),
        title=row["original_title"] or media_id,
        source_name=row["uploader_name"] or (src["name"] if src else "") or "unknown",
    )
    if not render_res.ok or render_res.video_path is None:
        return ProcessOutcome(False, stage="render", detail=render_res.error or "")
    record_video(repo, media_item_id, render_res.video_path)

    # ---- validation gate ----------------------------------------------------
    if not _advance(repo, media_item_id, MediaState.VALIDATION):
        return ProcessOutcome(False, stage="state", detail="cannot enter VALIDATION")
    if not _advance(repo, media_item_id, MediaState.READY_FOR_UPLOAD):
        return ProcessOutcome(False, stage="state", detail="cannot become READY_FOR_UPLOAD")

    return ProcessOutcome(True, stage="ready",
                          detail=f"video={render_res.video_path.name}")
