"""Upload pipeline Phase 9: youtube upload integration (fake client)."""

from pathlib import Path

import pytest

from tadabbur.uploader.config import UploadPipelineSettings
from tadabbur.uploader.database import open_database
from tadabbur.uploader.models import MediaState
from tadabbur.uploader.repository import UploaderRepository
from tadabbur.uploader.youtube import YouTubeClient, backoff_delay, upload_item


class FakeYouTube(YouTubeClient):
    def __init__(self, fail=False, error="boom"):
        self.fail = fail
        self.error = error

    def configured(self):
        return True

    def upload(self, video_path, meta, **kw):
        if self.fail:
            from tadabbur.uploader.youtube import UploadOutcome
            from tadabbur.uploader.models import FailureCategory

            return UploadOutcome(False, error=self.error,
                                 category=FailureCategory.UPLOAD_ERROR)
        from tadabbur.uploader.youtube import UploadOutcome

        return UploadOutcome(True, platform_video_id="ytNEW1234567",
                             platform_url="https://youtu.be/ytNEW1234567")


@pytest.fixture
def ready_item(tmp_path: Path):
    up = UploadPipelineSettings(base_dir=tmp_path)
    repo = UploaderRepository(open_database(tmp_path / "pipeline.db"))
    src_id = repo.upsert_source(source_key="s1", name="Chan 1",
                                channel_url="https://example.com/@c")
    mid = repo.insert_media_item(
        source_id=src_id, platform="youtube", original_media_id="vidAAAAAAAA1",
        original_url="https://youtu.be/vidAAAAAAAA1",
        original_title="Tafsir Al-Fatihah", uploader_name="Ustaz Test",
        rights_status="creative_commons",
        permission_reference="CC-LINK-1",
    )
    assert mid is not None
    mid = int(mid)
    for s in ("RIGHTS_REVIEW", "DOWNLOAD_PENDING", "DOWNLOADING", "DOWNLOADED",
              "AUDIO_PROCESSING", "AUDIO_READY", "VIDEO_RENDERING", "VALIDATION",
              "READY_FOR_UPLOAD"):
        assert repo.transition(mid, s)
    # fake rendered mp4 + metadata inputs on disk
    mp4 = tmp_path / "vid.mp4"
    mp4.write_bytes(b"\x00" * 2048)
    repo.upsert_file(media_item_id=mid, file_type="youtube_mp4", path=mp4,
                     extension="mp4", size_bytes=2048)
    return up, repo, mid


def test_upload_success_records_platform_id(ready_item):
    up, repo, mid = ready_item
    outcome = upload_item(repo, up, FakeYouTube(), mid)

    assert outcome.ok and outcome.platform_video_id == "ytNEW1234567"

    row = repo._conn.execute(
        "SELECT * FROM uploads WHERE media_item_id = ?", (mid,)
    ).fetchone()
    assert row["upload_status"] == "uploaded"
    assert row["platform_video_id"] == "ytNEW1234567"  # §30 verification
    assert repo.get_media_item(mid)["state"] == MediaState.UPLOADED


def test_upload_failure_keeps_item_unuploaded(ready_item):
    up, repo, mid = ready_item
    outcome = upload_item(repo, up, FakeYouTube(fail=True, error="quota"), mid)
    assert not outcome.ok

    row = repo._conn.execute(
        "SELECT * FROM uploads WHERE media_item_id = ?", (mid,)
    ).fetchone()
    assert row["upload_status"] == "failed"
    assert row["platform_video_id"] is None  # NEVER marked uploaded without id
    assert row["error_message"] == "quota"


def test_unconfigured_client_reports_auth_error(ready_item, monkeypatch):
    import os as _os

    monkeypatch.delenv("YOUTUBE_CLIENT_SECRETS", raising=False)
    monkeypatch.delenv("YOUTUBE_TOKEN_JSON", raising=False)
    up, repo, mid = ready_item
    client = YouTubeClient()
    assert not client.configured()
    outcome = upload_item(repo, up, client, mid)
    assert not outcome.ok and outcome.category == "AUTH_ERROR"


def test_retry_schedule_matches_spec():
    """§19: immediate, 5min, 30min, 2h then manual review."""
    assert backoff_delay(0, [0, 300, 1800, 7200]) < 60
    d1 = backoff_delay(1, [0, 300, 1800, 7200])
    assert 300 <= d1 <= 330 + 1
    d3 = backoff_delay(3, [0, 300, 1800, 7200])
    assert 7200 <= d3 <= 7920 + 1
    assert backoff_delay(4, [0, 300, 1800, 7200]) is None  # -> manual review
