"""Domain constants for the upload pipeline (upload_yt_pipeline.md §2, §15, §31)."""

from __future__ import annotations

from enum import StrEnum


class UploadRightsStatus(StrEnum):
    """Rights statuses for the upload pipeline.

    NOTE: attribution alone is NOT permission. Only explicitly approved
    statuses may enter the automatic upload queue.
    """

    UNKNOWN = "unknown"
    PERMISSION_CONFIRMED = "permission_confirmed"
    LICENSE_CONFIRMED = "license_confirmed"
    PUBLIC_DOMAIN = "public_domain"
    CREATIVE_COMMONS = "creative_commons"
    OWNED_BY_OPERATOR = "owned_by_operator"
    UPLOAD_NOT_AUTHORIZED = "upload_not_authorized"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"


#: Statuses that may enter the automatic YouTube upload queue.
APPROVED_FOR_UPLOAD: frozenset[str] = frozenset(
    {
        UploadRightsStatus.PERMISSION_CONFIRMED,
        UploadRightsStatus.LICENSE_CONFIRMED,
        UploadRightsStatus.PUBLIC_DOMAIN,
        UploadRightsStatus.CREATIVE_COMMONS,
        UploadRightsStatus.OWNED_BY_OPERATOR,
    }
)

#: Everything else stays here until an operator decides.
REVIEW_STATUSES: frozenset[str] = frozenset(
    {
        UploadRightsStatus.UNKNOWN,
        UploadRightsStatus.MANUAL_REVIEW_REQUIRED,
    }
)


class MediaDiscoveryStatus(StrEnum):
    DISCOVERED = "discovered"


class JobType(StrEnum):
    DOWNLOAD = "download"
    EXTRACT_AUDIO = "extract_audio"
    NORMALIZE = "normalize"
    COMPRESS = "compress"
    RENDER_VIDEO = "render_video"
    VALIDATE = "validate"
    GENERATE_METADATA = "generate_metadata"
    UPLOAD = "upload"


UPLOAD_JOB_TYPES: frozenset[str] = frozenset(t.value for t in JobType)


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRY = "retry"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


class UploadStatus(StrEnum):
    NOT_QUEUED = "not_queued"
    PENDING_REVIEW = "pending_review"
    QUEUED = "queued"
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    FAILED = "failed"
    RETRY = "retry"
    SKIPPED = "skipped"
    BLOCKED = "blocked"

    #: Statuses allowed to transition into the upload queue.
    UPLOADABLE = "uploadable"  # marker only; see APPROVED_FOR_UPLOAD


UPLOAD_STATUSES: frozenset[str] = frozenset(s.value for s in UploadStatus)


class FailureCategory(StrEnum):
    NETWORK_ERROR = "NETWORK_ERROR"
    AUTH_ERROR = "AUTH_ERROR"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    DOWNLOAD_ERROR = "DOWNLOAD_ERROR"
    FILE_CORRUPT = "FILE_CORRUPT"
    DISK_FULL = "DISK_FULL"
    FFMPEG_ERROR = "FFMPEG_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    METADATA_ERROR = "METADATA_ERROR"
    UPLOAD_ERROR = "UPLOAD_ERROR"
    RIGHTS_BLOCKED = "RIGHTS_BLOCKED"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


# ---------------------------------------------------------------- state machine
class MediaState(StrEnum):
    """Controlled media-item states (upload_yt_pipeline.md §16)."""

    DISCOVERED = "DISCOVERED"
    RIGHTS_REVIEW = "RIGHTS_REVIEW"
    BLOCKED = "BLOCKED"
    ARCHIVED = "ARCHIVED"  # archive-only
    DOWNLOAD_PENDING = "DOWNLOAD_PENDING"
    DOWNLOADING = "DOWNLOADING"
    DOWNLOAD_RETRY = "DOWNLOAD_RETRY"
    DOWNLOADED = "DOWNLOADED"
    AUDIO_PROCESSING = "AUDIO_PROCESSING"
    AUDIO_READY = "AUDIO_READY"
    VIDEO_RENDERING = "VIDEO_RENDERING"
    VALIDATION = "VALIDATION"
    PROCESSING_RETRY = "PROCESSING_RETRY"
    READY_FOR_UPLOAD = "READY_FOR_UPLOAD"
    UPLOAD_REVIEW = "UPLOAD_REVIEW"
    UPLOAD_QUEUED = "UPLOAD_QUEUED"
    UPLOADING = "UPLOADING"
    UPLOAD_RETRY = "UPLOAD_RETRY"
    UPLOADED = "UPLOADED"


#: Valid transitions of the media state machine.
MEDIA_TRANSITIONS: dict[str, set[str]] = {
    MediaState.DISCOVERED: {MediaState.RIGHTS_REVIEW},
    MediaState.RIGHTS_REVIEW: {
        MediaState.DOWNLOAD_PENDING,
        MediaState.ARCHIVED,
        MediaState.BLOCKED,
    },
    MediaState.BLOCKED: {MediaState.RIGHTS_REVIEW},
    MediaState.ARCHIVED: {MediaState.RIGHTS_REVIEW},
    MediaState.DOWNLOAD_PENDING: {MediaState.DOWNLOADING},
    MediaState.DOWNLOADING: {MediaState.DOWNLOADED, MediaState.DOWNLOAD_RETRY},
    MediaState.DOWNLOAD_RETRY: {MediaState.DOWNLOAD_PENDING},
    MediaState.DOWNLOADED: {MediaState.AUDIO_PROCESSING},
    MediaState.AUDIO_PROCESSING: {MediaState.AUDIO_READY, MediaState.PROCESSING_RETRY},
    MediaState.AUDIO_READY: {MediaState.VIDEO_RENDERING},
    MediaState.VIDEO_RENDERING: {MediaState.VALIDATION, MediaState.PROCESSING_RETRY},
    MediaState.VALIDATION: {MediaState.READY_FOR_UPLOAD, MediaState.PROCESSING_RETRY},
    MediaState.PROCESSING_RETRY: {MediaState.DOWNLOAD_PENDING, MediaState.AUDIO_PROCESSING, MediaState.VIDEO_RENDERING},
    MediaState.READY_FOR_UPLOAD: {MediaState.UPLOAD_QUEUED, MediaState.UPLOAD_REVIEW},
    MediaState.UPLOAD_REVIEW: {MediaState.UPLOAD_QUEUED, MediaState.BLOCKED},
    MediaState.UPLOAD_QUEUED: {MediaState.UPLOADING},
    MediaState.UPLOADING: {MediaState.UPLOADED, MediaState.UPLOAD_RETRY},
    MediaState.UPLOAD_RETRY: {MediaState.UPLOAD_QUEUED, MediaState.UPLOAD_REVIEW},
}


def can_transition(current: str, new: str) -> bool:
    return new in MEDIA_TRANSITIONS.get(current, set())
