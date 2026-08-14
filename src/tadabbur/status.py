"""Processing status constants and state machine definitions."""

from __future__ import annotations

DISCOVERED = "DISCOVERED"
CLASSIFIED = "CLASSIFIED"
REJECTED = "REJECTED"
QUEUED = "QUEUED"
DOWNLOADING = "DOWNLOADING"
DOWNLOADED = "DOWNLOADED"
AUDIO_PROCESSING = "AUDIO_PROCESSING"
PROCESSED = "PROCESSED"
TAGGED = "TAGGED"
VALIDATED = "VALIDATED"
READY_TO_PUBLISH = "READY_TO_PUBLISH"
PUBLISHED = "PUBLISHED"
FAILED = "FAILED"
MANUAL_REVIEW = "MANUAL_REVIEW"

MEDIA_STATUSES = frozenset(
    {
        DISCOVERED,
        CLASSIFIED,
        REJECTED,
        QUEUED,
        DOWNLOADING,
        DOWNLOADED,
        AUDIO_PROCESSING,
        PROCESSED,
        TAGGED,
        VALIDATED,
        READY_TO_PUBLISH,
        PUBLISHED,
        FAILED,
        MANUAL_REVIEW,
    }
)

# job statuses
JOB_PENDING = "pending"
JOB_RUNNING = "running"
JOB_SUCCESS = "success"
JOB_FAILED = "failed"
JOB_INTERRUPTED = "interrupted"

# download attempt statuses
ATTEMPT_SUCCESS = "success"
ATTEMPT_FAILED = "failed"

# publish job statuses
PUBLISH_PENDING = "pending"
PUBLISH_RUNNING = "running"
PUBLISH_SUCCESS = "success"
PUBLISH_FAILED = "failed"
PUBLISH_RETRY = "retry"

# canonical final-ready state
READY_STATES = frozenset({READY_TO_PUBLISH, PUBLISHED})

# states that can be resumed by a worker
RESUMABLE_JOB_STATUSES = frozenset({JOB_FAILED, JOB_INTERRUPTED})
