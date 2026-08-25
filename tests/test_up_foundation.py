"""Upload pipeline Phase 1: foundation (db, config, state machine, CLI)."""

from pathlib import Path

import pytest

from tadabbur.uploader.config import (
    DEFAULT_AUDIO_PROFILES,
    DEFAULT_RENDER_PROFILES,
    UploadPipelineSettings,
)
from tadabbur.uploader.database import open_database
from tadabbur.uploader.models import (
    APPROVED_FOR_UPLOAD,
    MediaState,
    UploadRightsStatus,
    can_transition,
)
from tadabbur.uploader.repository import UploaderRepository


@pytest.fixture
def repo(tmp_path: Path) -> UploaderRepository:
    conn = open_database(tmp_path / "pipeline.db")
    return UploaderRepository(conn)


# ------------------------------------------------------------------ schema
def test_database_creates_schema(tmp_path: Path):
    conn = open_database(tmp_path / "pipeline.db")
    version = conn.execute("SELECT version FROM schema_version").fetchone()["version"]
    assert version >= 1
    for table in ("sources", "media_items", "files", "processing_jobs", "uploads"):
        conn.execute(f"SELECT * FROM {table}")


def test_migration_is_idempotent(tmp_path: Path):
    open_database(tmp_path / "pipeline.db")
    conn = open_database(tmp_path / "pipeline.db")  # reopen must not fail
    assert conn is not None


# ------------------------------------------------------------- rights policy
def test_attribution_is_not_permission():
    """Core policy boundary: only explicit statuses are uploadable."""
    for s in ("unknown", "manual_review_required", "upload_not_authorized"):
        assert s not in APPROVED_FOR_UPLOAD


# ------------------------------------------------------------ state machine
def test_state_machine_happy_path():
    steps = [
        (MediaState.DISCOVERED, MediaState.RIGHTS_REVIEW),
        (MediaState.RIGHTS_REVIEW, MediaState.DOWNLOAD_PENDING),
        (MediaState.DOWNLOAD_PENDING, MediaState.DOWNLOADING),
        (MediaState.DOWNLOADING, MediaState.DOWNLOADED),
        (MediaState.DOWNLOADED, MediaState.AUDIO_PROCESSING),
        (MediaState.AUDIO_PROCESSING, MediaState.AUDIO_READY),
        (MediaState.AUDIO_READY, MediaState.VIDEO_RENDERING),
        (MediaState.VIDEO_RENDERING, MediaState.VALIDATION),
        (MediaState.VALIDATION, MediaState.READY_FOR_UPLOAD),
        (MediaState.READY_FOR_UPLOAD, MediaState.UPLOAD_QUEUED),
        (MediaState.UPLOAD_QUEUED, MediaState.UPLOADING),
        (MediaState.UPLOADING, MediaState.UPLOADED),
    ]
    for cur, new in steps:
        assert can_transition(cur, new), f"{cur} -> {new} must be valid"


def test_discovered_cannot_skip_rights_gate():
    assert not can_transition(MediaState.DISCOVERED, MediaState.DOWNLOAD_PENDING)
    assert not can_transition(MediaState.DISCOVERED, MediaState.UPLOADED)


def test_retry_paths_exist():
    assert can_transition(MediaState.DOWNLOADING, MediaState.DOWNLOAD_RETRY)
    assert can_transition(MediaState.DOWNLOAD_RETRY, MediaState.DOWNLOAD_PENDING)
    assert can_transition(MediaState.VALIDATION, MediaState.PROCESSING_RETRY)
    assert can_transition(MediaState.PROCESSING_RETRY, MediaState.AUDIO_PROCESSING)


def test_archive_only_and_blocked_states():
    assert can_transition(MediaState.RIGHTS_REVIEW, MediaState.ARCHIVED)
    assert can_transition(MediaState.RIGHTS_REVIEW, MediaState.BLOCKED)


# -------------------------------------------------------------- repository
def _item(repo: UploaderRepository, **kw) -> int:
    src = repo.upsert_source(
        source_key="test-src", name="Test", channel_url="https://example.com"
    )
    defaults = dict(
        source_id=src,
        platform="youtube",
        original_media_id="vid12345678",
        original_url="https://youtube.com/watch?v=vid12345678",
        original_title="Tafsir Al-Fatihah",
    )
    defaults.update(kw)
    mid = repo.insert_media_item(**defaults)
    assert mid is not None
    return mid


def test_platform_plus_media_id_is_identity(repo: UploaderRepository):
    src = repo.upsert_source(source_key="ident", name="Ident")
    first = repo.insert_media_item(
        source_id=src, platform="youtube",
        original_media_id="abc12345678", original_url="u1",
    )
    dup = repo.insert_media_item(
        source_id=src, platform="youtube",
        original_media_id="abc12345678", original_url="u2-different-url",
    )
    assert first is not None
    assert dup is None, "UNIQUE(platform, original_media_id) must block duplicates"


def test_url_duplicate_check_level2(repo: UploaderRepository):
    _item(repo)
    assert repo.find_by_original_url("https://youtube.com/watch?v=vid12345678") is not None
    assert repo.find_by_original_url("https://youtube.com/watch?v=other9999999") is None


def test_transition_enforces_machine(repo: UploaderRepository):
    mid = _item(repo)
    assert repo.transition(mid, MediaState.DOWNLOADING) is False  # skip gate
    assert repo.transition(mid, MediaState.RIGHTS_REVIEW) is True
    assert repo.transition(mid, MediaState.BLOCKED) is True


def test_review_rights_records_evidence(repo: UploaderRepository):
    mid = _item(repo)
    ok = repo.review_rights(
        mid,
        rights_status=UploadRightsStatus.PERMISSION_CONFIRMED,
        notes="Email from ustaz on 2026-08-20",
        permission_reference="MAIL-2026-001",
    )
    assert ok
    row = repo.get_media_item(mid)
    assert row["rights_status"] == "permission_confirmed"
    assert row["rights_reviewed_at"] is not None
    assert row["permission_reference"] == "MAIL-2026-001"


def test_review_rights_rejects_unknown_status(repo: UploaderRepository):
    import sqlite3

    mid = _item(repo)
    with pytest.raises(ValueError):
        repo.review_rights(mid, rights_status="i-made-this-up")


def test_upload_queue_requires_approved_rights(repo: UploaderRepository):
    blocked = _item(repo)  # default manual_review_required
    approved = repo.insert_media_item(
        source_id=_src(repo), platform="youtube",
        original_media_id="okl99999999",
        original_url="https://youtu.be/okl99999999",
        rights_status=UploadRightsStatus.CREATIVE_COMMONS,
    )
    assert approved is not None and blocked is not None
    # advance both to READY_FOR_UPLOAD directly via SQL (setup, not behaviour under test)
    conn = repo._conn
    conn.execute("UPDATE media_items SET state='READY_FOR_UPLOAD'")
    conn.commit()

    queue_ids = [r["id"] for r in repo.list_upload_queue()]
    assert approved in queue_ids
    assert blocked not in queue_ids, "unreviewed items must never enter upload queue"


def _src(repo: UploaderRepository) -> int:
    return repo.upsert_source(source_key="t2", name="T2")


def test_upload_requires_platform_video_id(repo: UploaderRepository):
    """§30: an item is uploaded only once the platform video id is stored."""
    mid = _item(repo)
    repo.mark_uploaded(
        mid, platform_video_id="ytXYZ78901",
        platform_url="https://youtu.be/ytXYZ78901",
        title_used="[Archive] Tafsir Al-Fatihah",
    )
    row = repo._conn.execute(
        "SELECT * FROM uploads WHERE media_item_id = ?", (mid,)
    ).fetchone()
    assert row["upload_status"] == "uploaded"
    assert row["platform_video_id"] == "ytXYZ78901"


def test_job_atomic_claim(repo: UploaderRepository):
    from tadabbur.uploader.models import JobType

    mid = _item(repo)
    job_id = repo.create_job(mid, JobType.DOWNLOAD)

    claimed = repo.claim_job(JobType.DOWNLOAD)
    assert claimed is not None and claimed["id"] == job_id
    assert claimed["status"] == "running"
    assert claimed["attempts"] == 1

    # Second claim attempt finds nothing (atomicity).
    assert repo.claim_job(JobType.DOWNLOAD) is None


def test_interrupted_jobs_detected_for_resume(repo: UploaderRepository):
    from tadabbur.uploader.models import JobType

    mid = _item(repo)
    repo.create_job(mid, JobType.RENDER_VIDEO)
    repo.claim_job(JobType.RENDER_VIDEO)  # left running (crash simulation)

    interrupted = repo.find_interrupted_jobs()
    assert len(interrupted) == 1
    assert interrupted[0]["job_type"] == JobType.RENDER_VIDEO


# ------------------------------------------------------------------ config
def test_default_profiles_match_spec():
    balanced = DEFAULT_AUDIO_PROFILES["speech_balanced"]
    assert balanced.codec == "opus" and balanced.bitrate_kbps == 48
    assert balanced.channels == 1 and balanced.sample_rate == 48000

    static = DEFAULT_RENDER_PROFILES["youtube_720p_static"]
    assert static.width == 1280 and static.height == 720 and static.fps == 24
    assert static.audio_bitrate_kbps == 64


def test_safety_defaults_are_conservative():
    settings = UploadPipelineSettings()
    assert settings.upload.enabled is False
    assert settings.upload.require_manual_enable is True
    assert settings.upload.dry_run_default is True
    assert settings.upload.max_uploads_per_run == 3


def test_file_naming_convention():
    """§21: identity-based names, never title-only."""
    from tadabbur.jobs.paths import slugify

    source_key, media_id = "maulana-asri", "abc123xyz"
    stem = f"{source_key}__{media_id}__{slugify('Tafsir Surah Al-Fatihah')}"
    assert stem == "maulana-asri__abc123xyz__tafsir-surah-al-fatihah"
