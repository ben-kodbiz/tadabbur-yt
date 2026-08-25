"""Upload pipeline Phase 4: download stage (resume, provenance, checksums)."""

import hashlib
import json
from pathlib import Path

import pytest

from tadabbur.config.models import Settings, StorageConfig
from tadabbur.downloader.client import YtDlpError
from tadabbur.uploader.config import UploadPipelineSettings
from tadabbur.uploader.database import open_database
from tadabbur.uploader.download import (
    advance_after_download,
    download_item,
    file_stem,
    item_directory,
)
from tadabbur.uploader.models import MediaState
from tadabbur.uploader.repository import UploaderRepository


class FakeYtDlp:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = 0

    def available(self):
        return True

    def inspect(self, url):
        return {
            "id": "vidAAAAAAAA1",
            "webpage_url": url,
            "title": "Tafsir Surah Al-Fatihah",
            "channel": "Ustaz Test",
            "upload_date": "20260801",
            "duration": 3600,
        }

    def download_lowest(self, url, tpl):
        self.calls += 1
        if self.fail:
            from tadabbur.downloader.client import YtDlpResult

            return YtDlpResult(exit_code=1, stderr="ERROR: Sign in to confirm you're not a bot")
        out = tpl.replace("%(ext)s", "m4a")
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        payload = b"fake-audio-bytes" * 1000
        Path(out).write_bytes(payload)
        from tadabbur.downloader.client import YtDlpResult

        return YtDlpResult(exit_code=0)


@pytest.fixture
def env(tmp_path: Path):
    ingest = Settings(project_dir=tmp_path, storage=StorageConfig(base_dir=tmp_path))
    up = UploadPipelineSettings(base_dir=tmp_path)
    repo = UploaderRepository(open_database(tmp_path / "pipeline.db"))
    src_id = repo.upsert_source(source_key="maulana-asri", name="Maulana",
                                channel_url="https://example.com")
    mid = repo.insert_media_item(
        source_id=src_id, platform="youtube",
        original_media_id="vidAAAAAAAA1",
        original_url="https://www.youtube.com/watch?v=vidAAAAAAAA1",
        original_title="Tafsir Surah Al-Fatihah",
        rights_status="permission_confirmed",
        state=MediaState.DOWNLOAD_PENDING,
    )
    assert mid is not None
    return ingest, up, repo, int(mid)


def test_file_naming_uses_identity(env):
    ingest, up, repo, mid = env
    d = item_directory(ingest, up, source_key="maulana-asri", media_id="vidAAAAAAAA1")
    assert str(d).endswith("maulana-asri/vidAAAAAAAA1")
    stem = file_stem("maulana-asri", "vidAAAAAAAA1", "Tafsir Surah Al-Fatihah")
    assert stem == "maulana-asri__vidAAAAAAAA1__tafsir-surah-al-fatihah"


def test_download_creates_provenance_and_checksum(env):
    ingest, up, repo, mid = env
    result = download_item(ingest, up, repo, FakeYtDlp(), mid)
    assert result.ok and result.original_path is not None

    directory = result.original_path.parent
    # identity-based name
    assert "__original." in result.original_path.name
    # source.json preserved
    meta = json.loads((directory / "source.json").read_text())
    assert meta["id"] == "vidAAAAAAAA1"
    assert meta["title"] == "Tafsir Surah Al-Fatihah"
    # checksum matches content
    expected = hashlib.sha256(result.original_path.read_bytes()).hexdigest()
    assert result.checksum == expected
    assert (directory / "checksum.sha256").read_text().startswith(expected)

    # DB record
    f = repo.get_file(mid, "original_media")
    assert f is not None and f["sha256"] == expected


def test_download_never_redownloads_complete_files(env):
    ingest, up, repo, mid = env
    client = FakeYtDlp()
    r1 = download_item(ingest, up, repo, client, mid)
    r2 = download_item(ingest, up, repo, client, mid)
    assert r1.ok and r2.ok
    assert client.calls == 1, "existing valid original must be reused"


def test_checksum_duplicate_detection_level3(env):
    ingest, up, repo, mid = env
    result = download_item(ingest, up, repo, FakeYtDlp(), mid)
    dup = repo.checksum_exists(result.checksum)
    assert dup is not None and int(dup["media_item_id"]) == mid


def test_download_failure_records_auth_category(env):
    ingest, up, repo, mid = env
    result = download_item(ingest, up, repo, FakeYtDlp(fail=True), mid)
    assert not result.ok
    assert result.category == "AUTH_ERROR"
    assert "Sign in" in (result.error or "")
    # no partial file recorded in DB
    assert repo.get_file(mid, "original_media") is None


def test_state_transitions_around_download(env):
    ingest, up, repo, mid = env
    repo.transition(mid, MediaState.DOWNLOADING)
    ok = advance_after_download(repo, mid, True)
    assert ok and repo.get_media_item(mid)["state"] == MediaState.DOWNLOADED

    # retry path for a second failing item
    repo.transition(mid, MediaState.AUDIO_PROCESSING)  # invalid; use fresh flow below
    # (machine: DOWNLOADED -> AUDIO_PROCESSING is valid, so state moved on)


def test_retry_state_roundtrip(env):
    ingest, up, repo, mid2_src = env
    src_id = repo.upsert_source(source_key="s9", name="S9")
    mid = repo.insert_media_item(
        source_id=src_id, platform="youtube",
        original_media_id="vidBBBBBBBB2",
        original_url="https://youtu.be/vidBBBBBBBB2",
        rights_status="public_domain",
        state=MediaState.DOWNLOAD_PENDING,
    )
    assert mid is not None
    repo.transition(int(mid), MediaState.DOWNLOADING)
    assert advance_after_download(repo, int(mid), False) is True
    assert repo.get_media_item(int(mid))["state"] == MediaState.DOWNLOAD_RETRY
