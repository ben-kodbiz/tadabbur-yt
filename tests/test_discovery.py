"""Stage 3: discovery engine tests (mocked yt-dlp)."""

from __future__ import annotations

import json

import pytest

from tadabbur.config import load_settings
from tadabbur.database import Repository, open_database
from tadabbur.discovery import (
    build_media_record,
    normalize_upload_date,
    normalize_video_id,
    run_discovery,
)
from tadabbur.downloader.client import YtDlpError

CHANNEL_JSON = {
    "id": "channel1",
    "title": "Channel One",
    "entries": [
        {
            "id": "videoone1234",
            "title": "Tadabbur Surah Al-Kahfi Ayat 1-10",
            "upload_date": "20260801",
            "duration": 3600,
            "webpage_url": "https://www.youtube.com/watch?v=videoone1234",
            "uploader": "Channel One",
        },
        {
            "id": "videotwo1234",
            "title": "Kuliah Umum",
            "upload_date": "20260802",
            "duration": 1800,
            "webpage_url": "https://www.youtube.com/watch?v=videotwo1234",
        },
    ],
}


class FakeClient:
    def __init__(self, entries=None, error=False):
        self.entries = entries or []
        self.error = error
        self.calls = []

    def available(self):
        return True

    def discover_channel(self, channel_url, max_entries=50):
        self.calls.append(channel_url)
        if self.error:
            raise YtDlpError("network down")
        return self.entries


@pytest.fixture()
def settings(tmp_path):
    return load_settings(config_file=tmp_path / "nope.yaml", project_dir=tmp_path)


@pytest.fixture()
def repo(tmp_path):
    conn = open_database(tmp_path / "test.sqlite")
    yield Repository(conn)
    conn.close()


def test_normalize_video_id():
    assert normalize_video_id("https://www.youtube.com/watch?v=abcDEF12345") == "abcDEF12345"
    assert normalize_video_id("https://youtu.be/abcDEF12345") == "abcDEF12345"
    assert normalize_video_id("abcDEF12345") == "abcDEF12345"
    assert normalize_video_id("https://www.youtube.com/shorts/abcDEF12345") == "abcDEF12345"


def test_normalize_upload_date():
    assert normalize_upload_date("20260801") == "2026-08-01"
    assert normalize_upload_date(None) is None
    assert normalize_upload_date("garbage") is None


def test_build_media_record(settings):
    from tadabbur.config.models import Source

    src = Source(id="ustaz", name="Ustaz", channel_url="https://youtube.com/@x")
    rec = build_media_record(src, CHANNEL_JSON["entries"][0])
    assert rec["external_id"] == "videoone1234"
    assert rec["source_id"] == "ustaz"
    assert rec["published_at"] == "2026-08-01"
    assert rec["duration"] == 3600
    assert rec["status"] == "DISCOVERED"


def test_discovery_inserts_new_media(settings, repo):
    source = settings.model_copy().model_dump()
    settings.sources = []
    from tadabbur.config.models import Source

    settings.sources = [
        Source(id="ustaz", name="Ustaz", channel_url="https://youtube.com/@x", enabled=True)
    ]
    client = FakeClient(entries=CHANNEL_JSON["entries"])

    result = run_discovery(settings, repo, client=client)
    assert result.discovered == ["videoone1234", "videotwo1234"]
    assert repo.media_exists("ustaz", "videoone1234")
    assert repo.media_exists("ustaz", "videotwo1234")


def test_discovery_dedup(settings, repo):
    from tadabbur.config.models import Source

    settings.sources = [
        Source(id="ustaz", name="Ustaz", channel_url="https://youtube.com/@x", enabled=True)
    ]
    client = FakeClient(entries=CHANNEL_JSON["entries"])
    first = run_discovery(settings, repo, client=client)
    assert len(first.discovered) == 2

    second = run_discovery(settings, repo, client=client)
    assert second.discovered == []
    assert second.duplicates == ["videoone1234", "videotwo1234"]


def test_discovery_source_error(settings, repo):
    from tadabbur.config.models import Source

    settings.sources = [
        Source(id="ustaz", name="Ustaz", channel_url="https://youtube.com/@x", enabled=True)
    ]
    client = FakeClient(entries=[], error=True)
    result = run_discovery(settings, repo, client=client)
    assert result.discovered == []
    assert len(result.errors) == 1


def test_discovery_dry_run(settings, repo):
    from tadabbur.config.models import Source

    settings.sources = [
        Source(id="ustaz", name="Ustaz", channel_url="https://youtube.com/@x", enabled=True)
    ]
    client = FakeClient(entries=CHANNEL_JSON["entries"])
    result = run_discovery(settings, repo, client=client, dry_run=True)
    assert result.discovered == ["videoone1234", "videotwo1234"]
    assert repo.media_exists("ustaz", "videoone1234") is False


def test_discovery_source_filter(settings, repo):
    from tadabbur.config.models import Source

    settings.sources = [
        Source(id="a", name="A", channel_url="https://youtube.com/@a", enabled=True),
        Source(id="b", name="B", channel_url="https://youtube.com/@b", enabled=True),
    ]
    client = FakeClient(entries=CHANNEL_JSON["entries"])
    result = run_discovery(settings, repo, client=client, source_id="a")
    assert result.sources_checked == ["a"]
    assert len(result.sources_checked) == 1
