"""YouTube upload pipeline for archived third-party audio.

Self-contained sub-pipeline with its own database (``pipeline.db``), state
machine and CLI. The ingestion pipeline (tadabbur core) feeds it; the
uploader only publishes items whose rights status is explicitly approved.

Design principles (upload_yt_pipeline.md):
- source archive != right to publish
- the database is the source of truth; folders are storage
- platform + original_media_id is primary identity
"""

from tadabbur.uploader.models import (
    APPROVED_FOR_UPLOAD,
    UPLOAD_JOB_TYPES,
    UPLOAD_STATUSES,
    UploadRightsStatus,
)

__all__ = [
    "APPROVED_FOR_UPLOAD",
    "UPLOAD_JOB_TYPES",
    "UPLOAD_STATUSES",
    "UploadRightsStatus",
]
