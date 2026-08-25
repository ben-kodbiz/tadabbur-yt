"""Authorized YouTube upload mechanism (§9/§30/§31).

Uses the YouTube Data API v3 via ``google-api-python-client`` (optional
dependency). The client is pluggable so tests can inject fakes.

Safety: uploads only happen for DB-queued approved items, within limits,
and an item is marked uploaded ONLY after the platform video id exists.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

from tadabbur.logging import stage_logger
from tadabbur.uploader.config import UploadPipelineSettings
from tadabbur.uploader.metadata import UploadMetadata
from tadabbur.uploader.models import FailureCategory, MediaState
from tadabbur.uploader.repository import UploaderRepository

logger = stage_logger("up-youtube")

CLIENT_SECRETS_ENV = "YOUTUBE_CLIENT_SECRETS"
TOKEN_ENV = "YOUTUBE_TOKEN_JSON"

#: Error categories that are safe to retry automatically (fix_me.md #9).
RETRYABLE_CATEGORIES = frozenset({
    FailureCategory.NETWORK_ERROR,
    "TIMEOUT",
    "SERVER_ERROR",
})

#: Categories that require intervention / scheduled-later retry.
NON_RETRYABLE_CATEGORIES = frozenset({
    "AUTH_ERROR", "QUOTA_ERROR", "INVALID_REQUEST", "FILE_ERROR",
})


class YouTubeUploadError(Exception):
    def __init__(self, message: str, *, category: str = FailureCategory.UPLOAD_ERROR,
                 retryable: bool = True) -> None:
        super().__init__(message)
        self.category = category
        self.retryable = retryable


def classify_upload_error(message: str, http_status: int | None = None) -> str:
    """#9: structured upload failure classification."""
    m = (message or "").lower()
    if http_status == 401 or "invalid credentials" in m or "unauthorized" in m \
            or "auth" in m and "error" in m:
        return "AUTH_ERROR"
    if "quotaexceeded" in m or "uploadlimitexceeded" in m \
            or (http_status == 403 and ("quota" in m or "limit" in m)):
        return "QUOTA_ERROR"
    if http_status == 403:
        return "AUTH_ERROR"
    if http_status == 400 or "invalid" in m:
        return "INVALID_REQUEST"
    if "timed out" in m or "timeout" in m:
        return "TIMEOUT"
    if http_status is not None and http_status >= 500:
        return "SERVER_ERROR"
    if "connection" in m or "network" in m or "unreachable" in m:
        return FailureCategory.NETWORK_ERROR
    if "no such file" in m or "file" in m and ("missing" in m or "corrupt" in m):
        return "FILE_ERROR"
    return "UNKNOWN_ERROR"


@dataclass
class UploadOutcome:
    ok: bool
    platform_video_id: str | None = None
    platform_url: str | None = None
    error: str | None = None
    category: str = FailureCategory.UNKNOWN_ERROR


class YouTubeClient:
    """Thin wrapper around the YouTube Data API resumable upload."""

    def __init__(self) -> None:
        import os

        self._secrets_path = os.environ.get(CLIENT_SECRETS_ENV)
        self._token_json = os.environ.get(TOKEN_ENV)

    def configured(self) -> bool:
        return bool(self._secrets_path and self._token_json)

    def upload(
        self,
        video_path: Path,
        meta: UploadMetadata,
        *,
        chunk_size: int = 8 * 1024 * 1024,
    ) -> UploadOutcome:
        """Resumable upload; returns the new platform video id on success."""
        if not self.configured():
            return UploadOutcome(
                False,
                error="YouTube API not configured: set YOUTUBE_CLIENT_SECRETS "
                      "and YOUTUBE_TOKEN_JSON",
                category=FailureCategory.AUTH_ERROR,
            )
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            from googleapiclient.errors import HttpError
            from googleapiclient.http import MediaFileUpload
        except ImportError as exc:
            return UploadOutcome(
                False,
                error=f"google api libraries not installed ({exc}); "
                      "pip install google-api-python-client google-auth-oauthlib",
                category=FailureCategory.AUTH_ERROR,
            )

        creds = Credentials.from_authorized_user_info(json.loads(self._token_json))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)

        body = {
            "snippet": {
                "title": meta.title,
                "description": meta.description,
                "tags": meta.tags,
                "categoryId": meta.category_id,
            },
            "status": {
                "privacyStatus": meta.privacy,
                "selfDeclaredMadeForKids": False,
            },
        }
        media = MediaFileUpload(str(video_path), mimetype="video/mp4",
                                chunksize=chunk_size, resumable=True)

        request = youtube.videos().insert(
            part="snippet,status", body=body, media_body=media
        )
        try:
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    logger.debug("[UP-YOUTUBE] progress %.0f%%",
                                 status.progress() * 100)
        except HttpError as exc:
            transient = exc.resp.status in {403, 429, 500, 503}
            return UploadOutcome(
                False,
                error=str(exc)[:500],
                category=FailureCategory.NETWORK_ERROR if transient
                else FailureCategory.UPLOAD_ERROR,
            )

        vid = response.get("id")
        if not vid:
            return UploadOutcome(False, error=f"no video id in response: {response}",
                                 category=FailureCategory.UPLOAD_ERROR)
        return UploadOutcome(True, platform_video_id=vid,
                             platform_url=f"https://youtu.be/{vid}")


def upload_item(
    repo: UploaderRepository,
    up_settings: UploadPipelineSettings,
    client: YouTubeClient,
    media_item_id: int,
) -> UploadOutcome:
    """Queue-checked single-item upload with post-upload verification (§30).

    fix_me.md #8: idempotent — an item with a recorded platform_video_id is
    NEVER uploaded again. fix_me.md #7: every attempt is persisted.
    """
    from tadabbur.uploader.queue import mark_upload_failed, record_upload_attempt

    row = repo.get_media_item(media_item_id)
    if row is None:
        return UploadOutcome(False, error="item not found")

    # ---- idempotency gate (#8): already uploaded? do nothing ---------------
    if repo.already_uploaded(media_item_id):
        rec = repo.get_upload_record(media_item_id)
        logger.info("[UP-YOUTUBE] item=%s already uploaded as %s; skipping",
                    media_item_id, rec["platform_video_id"])
        repo.record_event(media_item_id, "UPLOAD_SKIPPED_ALREADY_DONE",
                          message=f"platform_video_id={rec['platform_video_id']}")
        return UploadOutcome(True,
                             platform_video_id=rec["platform_video_id"],
                             platform_url=rec["platform_url"])

    f = repo.get_file(media_item_id, "youtube_mp4")
    if f is None or not Path(f["path"]).exists():
        return UploadOutcome(False, error="no rendered mp4 on disk",
                             category=FailureCategory.FILE_CORRUPT)

    # Metadata bundle rebuilt from DB provenance (never invented).
    from tadabbur.uploader.metadata import build_metadata_record

    src = repo.get_source_by_id(row["source_id"])
    meta = build_metadata_record(
        original_title=row["original_title"] or row["original_media_id"],
        speaker=row["uploader_name"],
        source_name=src["name"] if src else "unknown",
        source_url=src["channel_url"] if src else None,
        original_url=row["original_url"],
        rights_status=row["rights_status"],
        permission_note=(
            row["permission_reference"] or
            (f"notes: {row['rights_notes']}" if row["rights_notes"] else None)
        ),
    )

    if row["state"] == MediaState.READY_FOR_UPLOAD:
        repo.transition(media_item_id, MediaState.UPLOAD_QUEUED)
    repo.transition(media_item_id, MediaState.UPLOADING)
    repo.record_event(media_item_id, "UPLOAD_STARTED")

    attempt_id = repo.start_upload_attempt(media_item_id)
    outcome = client.upload(Path(f["path"]), meta)

    if outcome.ok and outcome.platform_video_id:
        record_upload_attempt(repo, media_item_id, error=None)
        repo.finish_upload_attempt(attempt_id, ok=True)
        repo.mark_uploaded(
            media_item_id,
            platform_video_id=outcome.platform_video_id,
            platform_url=outcome.platform_url or "",
            title_used=meta.title,
        )
        repo.transition(media_item_id, MediaState.UPLOADED)
        repo.record_event(media_item_id, "UPLOAD_COMPLETED",
                          new_state="UPLOADED",
                          message=f"platform_video_id={outcome.platform_video_id}")

        # Optional storage cleanup — only after verified success + commit (#16).
        if not up_settings.storage.keep_youtube_mp4_after_upload:
            try:
                Path(f["path"]).unlink(missing_ok=True)
                logger.info("[UP-YOUTUBE] item=%s removed local mp4 after upload",
                            media_item_id)
            except OSError as exc:
                logger.warning("[UP-YOUTUBE] could not remove mp4: %s", exc)

        logger.info("[UP-YOUTUBE] item=%s uploaded as %s",
                    media_item_id, outcome.platform_video_id)
    else:
        category = classify_upload_error(outcome.error or "")
        retryable = category in RETRYABLE_CATEGORIES
        record_upload_attempt(repo, media_item_id, error=outcome.error)
        repo.finish_upload_attempt(attempt_id, ok=False, error_category=category)
        mark_upload_failed(repo, media_item_id, category,
                           outcome.error or "unknown upload failure")
        repo.record_event(media_item_id, "UPLOAD_FAILED",
                          message=(outcome.error or "")[:500],
                          error_category=category)
    return outcome


def backoff_delay(attempt: int, schedule: list[int]) -> float | None:
    """§19 retry schedule: [0, 300, 1800, 7200]; None => manual review."""
    if attempt < len(schedule):
        base = schedule[attempt]
        jitter = base * 0.1
        return base + random.uniform(0, jitter)
    return None
