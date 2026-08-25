"""Upload pipeline Phase 8: upload queue safety and validation."""

from pathlib import Path

import pytest

from tadabbur.uploader.config import UploadPipelineSettings
from tadabbur.uploader.database import open_database
from tadabbur.uploader.models import MediaState
from tadabbur.uploader.queue import (
    DailyLimitReached,
    build_queue_plan,
    check_daily_limit,
    mark_upload_failed,
    record_upload_attempt,
)
from tadabbur.uploader.repository import UploaderRepository


@pytest.fixture
def env(tmp_path: Path):
    up = UploadPipelineSettings(base_dir=tmp_path)
    repo = UploaderRepository(open_database(tmp_path / "pipeline.db"))
    src_id = repo.upsert_source(source_key="s1", name="S1")
    return up, repo, int(src_id)


def _approved_item(repo: UploaderRepository, src_id: int, vid: str,
                   *, with_mp4: bool = True) -> int:
    mid = repo.insert_media_item(
        source_id=src_id, platform="youtube", original_media_id=vid,
        original_url=f"https://youtu.be/{vid}",
        original_title=f"Lecture {vid}",
        rights_status="public_domain",
    )
    assert mid is not None
    for s in ("RIGHTS_REVIEW", "DOWNLOAD_PENDING", "DOWNLOADING", "DOWNLOADED",
              "AUDIO_PROCESSING", "AUDIO_READY", "VIDEO_RENDERING", "VALIDATION"):
        assert repo.transition(int(mid), s), f"transition to {s}"
    assert repo.transition(int(mid), MediaState.READY_FOR_UPLOAD)
    if with_mp4:
        mp4 = Path(f"/tmp/fake__{vid}__youtube.mp4")
        mp4.write_bytes(b"x" * 1000)  # tiny but existing
        repo.upsert_file(media_item_id=int(mid), file_type="youtube_mp4",
                         path=mp4, extension="mp4", size_bytes=1000)
    return int(mid)


def test_queue_requires_rendered_mp4(env):
    up, repo, src = env
    no_mp4 = _approved_item(repo, src, "vidAAAAAAAA1", with_mp4=False)
    plan = build_queue_plan(up, repo)
    assert plan.entries == []
    assert any(i == no_mp4 and ("no rendered" in r or "no archive" in r or "original missing" in r) for i, r in plan.rejected)


def test_queue_requires_approved_rights(env):
    up, repo, src = env
    # unreviewed item pushed (via SQL setup) into READY state must be rejected
    mid = repo.insert_media_item(
        source_id=src, platform="youtube", original_media_id="vidBBBBBBBB2",
        original_url="https://youtu.be/vidBBBBBBBB2",
        original_title="Unreviewed", rights_status="manual_review_required",
    )
    repo._conn.execute("UPDATE media_items SET state='READY_FOR_UPLOAD' WHERE id=?", (mid,))
    repo._conn.commit()
    mp4 = Path("/tmp/fake__vidBBBBBBBB2__youtube.mp4")
    mp4.write_bytes(b"x")
    repo.upsert_file(media_item_id=int(mid), file_type="youtube_mp4",
                     path=mp4, extension="mp4")

    plan = build_queue_plan(up, repo)
    # Defense in depth: the queue query itself excludes unapproved rights.
    assert all(i != mid for i, _ in plan.entries)
    assert all(i != mid for i, _ in plan.rejected)


def test_queue_honors_per_run_limit(env):
    up, repo, src = env
    up.upload.max_uploads_per_run = 2
    for i in range(5):
        _approved_item(repo, src, f"vid{i:09d}")
    plan = build_queue_plan(up, repo)
    assert len(plan.entries) <= 2


def test_daily_limit_blocks_uploads(env):
    up, repo, src = env
    item = _approved_item(repo, src, "vidCCCCCCCC3")

    up.upload.max_uploads_per_day = 1
    check_daily_limit(up, repo)  # nothing uploaded yet -> fine
    record_upload_attempt(repo, item, error=None)

    with pytest.raises(DailyLimitReached):
        check_daily_limit(up, repo)


def test_failed_upload_recorded_with_error(env):
    up, repo, src = env
    item = _approved_item(repo, src, "vidDDDDDDDD4")
    record_upload_attempt(repo, item, error="quotaExceeded")
    mark_upload_failed(repo, item, "UPLOAD_ERROR", "quotaExceeded")

    row = repo._conn.execute(
        "SELECT * FROM uploads WHERE media_item_id = ?", (item,)
    ).fetchone()
    assert row["upload_status"] == "failed"
    assert row["attempt_count"] == 1
    assert row["error_message"] == "quotaExceeded"
    assert row["platform_video_id"] is None  # never marked uploaded


def test_success_records_platform_video_id(env):
    from tadabbur.uploader.queue import QueueEntry

    up, repo, src = env
    item = _approved_item(repo, src, "vidEEEEEEEE5")
    record_upload_attempt(repo, item, error=None)
    repo.mark_uploaded(item, platform_video_id="ytABC1234567",
                       platform_url="https://youtu.be/ytABC1234567",
                       title_used="[Archive] Lecture vidEEEEEEEE5")
    row = repo._conn.execute(
        "SELECT * FROM uploads WHERE media_item_id = ?", (item,)
    ).fetchone()
    assert row["upload_status"] == "uploaded"
    assert row["platform_video_id"] == "ytABC1234567"
