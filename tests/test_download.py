"""Stage 7: download manager tests using a mocked YtDlpClient."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tadabbur.config import load_settings
from tadabbur.database import Repository, open_database
from tadabbur.downloader import YtDlpError
from tadabbur.downloader.circuit_breaker import CircuitBreaker
from tadabbur.downloader.manager import run_download
from tadabbur.jobs.paths import media_directory


class FakeResult:
    def __init__(self, exit_code=0, stdout="", stderr=""):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


class FakeClient:
    """Stand-in for YtDlpClient that writes fake files to disk."""

    def __init__(self, settings, *, fail_video=False, fail_audio=False):
        self.settings = settings
        self.fail_video = fail_video
        self.fail_audio = fail_audio
        self.audio_written = []

    def available(self):
        return True

    def version(self):
        return "2025.01.01"

    def inspect(self, url):
        return {
            "id": "videoone1234",
            "webpage_url": url,
            "title": "Tadabbur Surah Al-Kahfi Ayat 1-10",
            "description": None,
            "channel": "Channel One",
            "upload_date": "20260801",
            "duration": 3600,
        }

    def download_video(self, url, output_template):
        if self.fail_video:
            return FakeResult(exit_code=1, stderr="download failed")
        return FakeResult(exit_code=0)

    def download_audio(self, url, output_template):
        if self.fail_audio:
            return FakeResult(exit_code=1, stderr="audio failed")
        # Mimic yt-dlp output naming: "<title> [id].m4a"
        import re

        base = re.sub(r"%\([^)]+\)", "", output_template).replace(".%(ext)s", "")
        title_slug = "Tadabbur Surah Al-Kahfi Ayat 1-10 [videoone1234]"
        audio_path = Path(output_template).parent / f"{title_slug}.m4a"
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        audio_path.write_bytes(b"0" * 100_000)
        self.audio_written.append(audio_path)
        return FakeResult(exit_code=0)


@pytest.fixture()
def settings(tmp_path):
    s = load_settings(config_file=tmp_path / "nope.yaml", project_dir=tmp_path)
    s.storage.base_dir = tmp_path / "data"
    return s


@pytest.fixture()
def repo(settings):
    conn = open_database(settings.storage.database_path)
    yield Repository(conn)
    conn.close()


def _seed_queued(repo, *, external_id="videoone1234"):
    repo.upsert_source(
        source_id="ustaz", name="Ustaz", channel_url="https://youtube.com/@x"
    )
    mid = repo.insert_media(
        source_id="ustaz",
        external_id=external_id,
        url=f"https://www.youtube.com/watch?v={external_id}",
        title="Tadabbur Surah Al-Kahfi Ayat 1-10",
        uploader="Channel One",
        published_at="2026-08-01",
        status="QUEUED",
    )
    return mid


def test_download_success(settings, repo):
    mid = _seed_queued(repo)
    client = FakeClient(settings)
    outcomes = run_download(settings, repo, client=client, sleep=lambda _: None)

    assert len(outcomes) == 1
    o = outcomes[0]
    assert o.status == "PROCESSED"
    row = repo.get_media(mid)
    assert row["status"] == "PROCESSED"

    audio_file = repo.get_media_file(mid, "audio")
    assert audio_file is not None
    assert Path(audio_file["path"]).exists()
    meta = repo.get_media_file(mid, "metadata")
    assert meta is not None


def test_download_video_failure_retries_then_fails(settings, repo):
    mid = _seed_queued(repo)
    client = FakeClient(settings, fail_video=True)
    outcomes = run_download(
        settings, repo, client=client,
        sleep=lambda _: None,
        circuit_breaker=CircuitBreaker(settings.circuit_breaker),
    )
    o = outcomes[0]
    assert o.status == "FAILED"
    assert repo.get_media(mid)["status"] == "FAILED"


def test_download_audio_failure(settings, repo):
    mid = _seed_queued(repo)
    client = FakeClient(settings, fail_audio=True)
    outcomes = run_download(settings, repo, client=client, sleep=lambda _: None)
    assert outcomes[0].status == "FAILED"
    assert repo.get_media(mid)["status"] == "FAILED"


def test_download_specific_video(settings, repo):
    mid = _seed_queued(repo)
    client = FakeClient(settings)
    outcomes = run_download(
        settings, repo, client=client, video_id="videoone1234", sleep=lambda _: None
    )
    assert len(outcomes) == 1
    assert outcomes[0].video_id == "videoone1234"


def test_download_only_queued(settings, repo):
    repo.upsert_source(source_id="s1", name="A", channel_url="https://youtube.com/@a")
    repo.insert_media(
        source_id="s1", external_id="notqueued", url="https://youtu.be/notqueued",
        title="T", status="DISCOVERED",
    )
    client = FakeClient(settings)
    outcomes = run_download(settings, repo, client=client, sleep=lambda _: None)
    assert outcomes == []


def test_media_directory_layout(settings):
    d = media_directory(
        settings,
        speaker="Channel One",
        source_id="ustaz",
        video_id="videoone1234",
        published_at="2026-08-01",
    )
    assert str(d).endswith(
        "/data/media/channel-one/2026/08/ustaz/videoone1234"
    )
