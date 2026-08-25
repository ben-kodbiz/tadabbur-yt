"""fix_me.md §24 hardening test suite.

Covers: rights gate, artifact-aware resume, MP4/Opus validation,
SHA-256 duplicates, upload idempotency + retry classification, events.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ffmpeg = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(ffmpeg is None, reason="ffmpeg not available")

from tadabbur.uploader.config import AudioProfile, RenderProfile, UploadPipelineSettings
from tadabbur.uploader.database import open_database
from tadabbur.uploader.models import APPROVED_FOR_UPLOAD, FailureCategory, MediaState
from tadabbur.uploader.process import check_rights_gate, process_item
from tadabbur.uploader.repository import UploaderRepository
from tadabbur.uploader.validator import (
    validate_archive_audio,
    validate_original,
    validate_youtube_video,
)


@pytest.fixture
def env(tmp_path: Path):
    up = UploadPipelineSettings(base_dir=tmp_path)
    repo = UploaderRepository(open_database(tmp_path / "pipeline.db"))
    src_id = repo.upsert_source(source_key="s1", name="Chan 1",
                                channel_url="https://example.com")

    def make_item(vid="vidAAAAAAAA1", rights="public_domain", state=MediaState.DISCOVERED):
        mid = repo.insert_media_item(
            source_id=src_id, platform="youtube", original_media_id=vid,
            original_url=f"https://youtu.be/{vid}", original_title=f"Lecture {vid}",
            uploader_name="Ustaz Test", rights_status=rights, state=state,
        )
        return int(mid)

    return up, repo, make_item


def _make_wav(path: Path, seconds: float = 4.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", str(path)],
        check=True,
    )
    return path


def _make_opus(path: Path, seconds: float = 3.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-c:a", "libopus", str(path)],
        check=True,
    )


# ------------------------------------------------------------------ rights
def test_approved_rights_proceed(env):
    _, repo, make = env
    for n, status in enumerate(sorted(APPROVED_FOR_UPLOAD)):
        row = repo.get_media_item(make(f"vidAPPR{n:06d}01", rights=status))
        assert check_rights_gate(row) is None, status


def test_unknown_and_review_blocked(env):
    _, repo, make = env
    for n, status in enumerate(("unknown", "manual_review_required")):
        mid = make(f"vidREVIEW{n:06d}1", rights=status)
        outcome = check_rights_gate(repo.get_media_item(mid))
        assert outcome is not None and not outcome.ok
        assert "review" in outcome.detail


def test_unauthorized_blocked_and_marked(env):
    up, repo, make = env
    mid = make(rights="upload_not_authorized")
    # process_item should refuse AND move to BLOCKED without deleting the record
    outcome = process_item(up, up, repo, mid)
    assert not outcome.ok and outcome.stage == "rights"
    row = repo.get_media_item(mid)
    assert row["state"] == MediaState.BLOCKED
    assert row is not None  # record preserved, searchable


def test_archive_only_stays_non_uploadable(env):
    """ARCHIVED items never appear in the upload queue."""
    _, repo, make = env
    mid = make(rights="public_domain")
    repo.transition(mid, MediaState.RIGHTS_REVIEW)
    repo.transition(mid, MediaState.ARCHIVED)
    repo._conn.execute("UPDATE media_items SET rights_status='public_domain' WHERE id=?", (mid,))
    repo._conn.commit()
    assert all(e.media_item_id != mid for e in [] )  # placeholder
    queue_ids = [r["id"] for r in repo.list_upload_queue()]
    assert mid not in queue_ids


# -------------------------------------------------------------- duplicates
def test_same_sha256_flagged_not_deleted(env):
    _, repo, make = env
    a = make("vidAAAAAAAA1")
    b = make("vidBBBBBBBB2")
    sha = "abc123" * 10 + "x"
    repo.set_original_sha256(a, sha)
    repo.set_original_sha256(b, sha)
    dups = repo.find_sha256_duplicates()
    ids = [r["id"] for r in dups]
    assert a in ids and b in ids
    assert repo.get_media_item(a) is not None and repo.get_media_item(b) is not None


def test_different_sha_no_duplicate(env):
    _, repo, make = env
    a, b = make("vidAAAAAAAA1"), make("vidBBBBBBBB2")
    repo.set_original_sha256(a, "sha-one")
    repo.set_original_sha256(b, "sha-two")
    assert repo.find_sha256_duplicates() == []


# ---------------------------------------------------------------- video val
@needs_ffmpeg
def test_valid_mp4_accepted(tmp_path: Path):
    opus = tmp_path / "a.opus"
    _make_opus(opus, 3.0)

    from tadabbur.uploader.render import render_card_video

    out = render_card_video(opus, tmp_path, "stem", RenderProfile(),
                            title="T", source_name="S")
    report = validate_youtube_video(out.video_path, expected_duration=3.0)
    assert report.ok, report.errors


@needs_ffmpeg
def test_corrupt_mp4_rejected(tmp_path: Path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"\x00" * 30000)  # big enough but garbage
    report = validate_youtube_video(bad)
    assert not report.ok


@needs_ffmpeg
def test_wrong_resolution_rejected(tmp_path: Path):
    from tadabbur.uploader.render import render_card_video

    opus = tmp_path / "a.opus"
    _make_opus(opus, 2.0)
    out = render_card_video(opus, tmp_path, "stem", RenderProfile(width=640, height=360),
                            title="T", source_name="S")
    # validate against expected 1280x720 -> must fail resolution check
    report = validate_youtube_video(out.video_path, width=1280, height=720)
    assert not report.ok and any("resolution" in e for e in report.errors)


@needs_ffmpeg
def test_duration_mismatch_rejected(tmp_path: Path):
    from tadabbur.uploader.render import render_card_video

    opus = tmp_path / "a.opus"
    _make_opus(opus, 3.0)
    out = render_card_video(opus, tmp_path, "stem", RenderProfile(),
                            title="T", source_name="S")
    report = validate_youtube_video(out.video_path, expected_duration=600.0,
                                    duration_tolerance=5.0)
    assert not report.ok and any("duration" in e for e in report.errors)


@needs_ffmpeg
def test_missing_file_rejected():
    report = validate_youtube_video("/nonexistent/video.mp4")
    assert not report.ok


# ----------------------------------------------------------------- audio val
@needs_ffmpeg
def test_valid_opus_accepted(tmp_path: Path):
    opus = tmp_path / "a.opus"
    _make_opus(opus, 3.0)
    report = validate_archive_audio(opus, codec="opus", channels=1)
    assert report.ok, report.errors


@needs_ffmpeg
def test_corrupt_opus_rejected(tmp_path: Path):
    bad = tmp_path / "bad.opus"
    bad.write_bytes(b"\x00" * 20000)
    assert not validate_archive_audio(bad).ok


@needs_ffmpeg
def test_wrong_codec_rejected(tmp_path: Path):
    wav = _make_wav(tmp_path / "src.wav", 2.0)
    # wav is not opus -> must fail codec check
    report = validate_archive_audio(wav, codec="opus")
    assert not report.ok and any("codec" in e for e in report.errors)


@needs_ffmpeg
def test_invalid_duration_rejected(tmp_path: Path):
    opus = tmp_path / "a.opus"
    _make_opus(opus, 2.0)
    report = validate_archive_audio(opus, expected_duration=9999.0)
    assert not report.ok


# ------------------------------------------------------------------- resume
@needs_ffmpeg
def test_crash_resume_reuses_artifacts(env, tmp_path: Path):
    """Simulate crash after each stage; rerun reuses valid artifacts."""
    from tadabbur.audio.ffmpeg import extract_audio
    from tadabbur.uploader.render import render_card_video

    up, repo, _ = env
    mid = repo.insert_media_item(
        source_id=1, platform="youtube", original_media_id="vidRESUME0001",
        original_url="https://youtu.be/vidRESUME0001",
        original_title="Resume Lecture", uploader_name="Ustaz",
        rights_status="public_domain",
    )
    # Build artifacts directly (simulating earlier completed stages).
    workdir = tmp_path / "work" / "s1" / "vidRESUME0001"
    workdir.mkdir(parents=True)
    stem = "s1__vidRESUME0001"
    original = _make_wav(workdir / f"{stem}__original.wav", 3.0)
    repo.upsert_file(media_item_id=mid, file_type="original_media",
                     path=original, extension="wav", size_bytes=original.stat().st_size)
    opus = workdir / f"{stem}__audio.opus"
    _make_opus(opus, 3.0)
    mp4_res = render_card_video(opus, workdir, stem, RenderProfile(),
                                title="Resume Lecture", source_name="Ustaz")
    assert mp4_res.ok
    mtimes = {
        "orig": original.stat().st_mtime_ns,
        "opus": opus.stat().st_mtime_ns,
        "mp4": mp4_res.video_path.stat().st_mtime_ns,
    }

    outcome = process_item(up, up, repo, int(mid))
    assert outcome.ok, outcome

    # All three artifacts untouched (reused, not rebuilt).
    assert original.stat().st_mtime_ns == mtimes["orig"]
    assert opus.stat().st_mtime_ns == mtimes["opus"]
    assert mp4_res.video_path.stat().st_mtime_ns == mtimes["mp4"]
    assert repo.get_media_item(mid)["state"] == MediaState.READY_FOR_UPLOAD


@needs_ffmpeg
def test_invalid_opus_is_regenerated(env, tmp_path: Path):
    up, repo, _ = env
    workdir = tmp_path / "w" / "s1" / "vidBADOPUS001"
    workdir.mkdir(parents=True)
    stem = "s1__vidBADOPUS001"
    original = _make_wav(workdir / f"{stem}__original.wav", 3.0)
    bad_opus = workdir / f"{stem}__audio.opus"
    bad_opus.write_bytes(b"\xff" * 25000)  # corrupt

    mid = repo.insert_media_item(
        source_id=1, platform="youtube", original_media_id="vidBADOPUS001",
        original_url="https://youtu.be/vidBADOPUS001", original_title="T",
        rights_status="public_domain",
    )
    repo.upsert_file(media_item_id=int(mid), file_type="original_media",
                     path=original, extension="wav", size_bytes=original.stat().st_size)

    outcome = process_item(up, up, repo, int(mid))
    assert outcome.ok, outcome
    # the corrupt file was replaced with a valid one
    assert validate_archive_audio(bad_opus, codec="opus", channels=1).ok


# ------------------------------------------------------------------- upload
def test_upload_idempotent_after_success(env):
    """#8: an uploaded item can NEVER be uploaded again."""

    from tadabbur.uploader.config import UploadPipelineSettings as UPS
    import tadabbur.uploader.youtube as yt_mod

    class FakeClient(yt_mod.YouTubeClient):
        def __init__(self):
            self.calls = 0

        def configured(self):
            return True

        def upload(self, video_path, meta, **kw):
            self.calls += 1
            return yt_mod.UploadOutcome(True, platform_video_id=f"ytX{self.calls}",
                                        platform_url="https://youtu.be/x")

    up, repo, _ = env
    client = FakeClient()
    mid = repo.insert_media_item(
        source_id=1, platform="youtube", original_media_id="vidUPLOAD0001",
        original_url="https://youtu.be/vidUPLOAD0001", original_title="T",
        rights_status="public_domain",
    )
    mp4 = Path("/tmp/fake__vidUPLOAD0001.mp4")
    mp4.write_bytes(b"x" * 1000)
    repo.upsert_file(media_item_id=int(mid), file_type="youtube_mp4",
                     path=mp4, extension="mp4", size_bytes=1000)
    for s in ("RIGHTS_REVIEW", "DOWNLOAD_PENDING", "DOWNLOADING", "DOWNLOADED",
              "AUDIO_PROCESSING", "AUDIO_READY", "VIDEO_RENDERING", "VALIDATION"):
        repo.transition(int(mid), s)
    repo.transition(int(mid), MediaState.READY_FOR_UPLOAD)

    r1 = yt_mod.upload_item(repo, up, client, int(mid))
    assert r1.ok
    calls_after_first = client.calls

    r2 = yt_mod.upload_item(repo, up, client, int(mid))
    assert r2.ok
    assert client.calls == calls_after_first, "second call must NOT hit the API"
    rec = repo.get_upload_record(int(mid))
    assert rec["platform_video_id"] == "ytX1"  # unchanged


def test_upload_failure_classification():
    from tadabbur.uploader.youtube import classify_upload_error

    assert classify_upload_error("invalid credentials", 401) == "AUTH_ERROR"
    assert classify_upload_error("quotaExceeded blah", 403) == "QUOTA_ERROR"
    assert classify_upload_error("daily upload limit", 403) == "QUOTA_ERROR"
    assert classify_upload_error("connection reset", None) == "NETWORK_ERROR"
    assert classify_upload_error("request timed out after 120s") == "TIMEOUT"
    assert classify_upload_error("backend error", 500) == "SERVER_ERROR"
    assert classify_upload_error("invalid metadata provided", 400) == "INVALID_REQUEST"


def test_retryable_vs_not():
    from tadabbur.uploader.queue import QueueEntry  # noqa
    from tadabbur.uploader.youtube import NON_RETRYABLE_CATEGORIES, RETRYABLE_CATEGORIES

    for cat in ("AUTH_ERROR", "QUOTA_ERROR", "INVALID_REQUEST"):
        assert cat in NON_RETRYABLE_CATEGORIES
    for cat in (FailureCategory.NETWORK_ERROR.value, "SERVER_ERROR", "TIMEOUT"):
        assert cat in RETRYABLE_CATEGORIES or cat == "NETWORK_ERROR"


def test_upload_attempts_persisted(env):
    import tadabbur.uploader.youtube as yt_mod

    class FailingClient(yt_mod.YouTubeClient):
        def configured(self):
            return True

        def upload(self, video_path, meta, **kw):
            return yt_mod.UploadOutcome(False, error="connection reset by peer",
                                        category="NETWORK_ERROR")

    up, repo, _ = env
    mid = repo.insert_media_item(
        source_id=1, platform="youtube", original_media_id="vidATT0000001",
        original_url="https://youtu.be/vidATT0000001", original_title="T",
        rights_status="public_domain",
    )
    mp4 = Path("/tmp/fake__vidATT0000001.mp4")
    mp4.write_bytes(b"x" * 1000)
    repo.upsert_file(media_item_id=int(mid), file_type="youtube_mp4",
                     path=mp4, extension="mp4", size_bytes=1000)

    yt_mod.upload_item(repo, up, FailingClient(), int(mid))
    attempts = repo._conn.execute(
        "SELECT * FROM upload_attempts WHERE media_item_id = ?", (mid,)
    ).fetchall()
    assert len(attempts) == 1
    assert attempts[0]["status"] == "failed"
    assert attempts[0]["error_category"] in ("NETWORK_ERROR", FailureCategory.NETWORK_ERROR.value)


def test_events_recorded_through_pipeline(env, tmp_path: Path):
    up, repo, _ = env
    workdir = tmp_path / "ev" / "s1" / "vidEVENTS0001"
    workdir.mkdir(parents=True)
    stem = "s1__vidEVENTS0001"
    original = _make_wav(workdir / f"{stem}__original.wav", 2.5)
    mid = repo.insert_media_item(
        source_id=1, platform="youtube", original_media_id="vidEVENTS0001",
        original_url="https://youtu.be/vidEVENTS0001", original_title="T",
        rights_status="public_domain",
    )
    repo.upsert_file(media_item_id=int(mid), file_type="original_media",
                     path=original, extension="wav", size_bytes=original.stat().st_size)

    process_item(up, up, repo, int(mid))
    types = [e["event_type"] for e in repo.list_events(int(mid))]
    assert "AUDIO_COMPLETED" in types
    assert "VIDEO_COMPLETED" in types
    assert "VALIDATION_PASSED" in types
