"""Full v1 pipeline integration test with mocked network + filesystem.

Covers the complete flow without touching the internet:
discover -> classify -> download(+audio) -> tag -> validate -> publish -> export.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tadabbur.config import load_settings
from tadabbur.database import Repository, open_database
from tadabbur.discovery import run_discovery
from tadabbur.downloader import run_download
from tadabbur.exporters import export_web_data
from tadabbur.services.classification import classify
from tadabbur.services.publish import publish
from tadabbur.services.tagging import tag
from tadabbur.status import PUBLISHED, QUEUED, READY_TO_PUBLISH, REJECTED, TAGGED
from tadabbur.validator import run_validation


class FakeResult:
    def __init__(self, exit_code=0, stdout="", stderr=""):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


class FakeYtClient:
    """Mocks yt-dlp: discovery + inspect + download, writing fake files."""

    def __init__(self, settings):
        self.settings = settings
        self.entries = [
            {"id": "abc11111111", "title": "Tadabbur Surah Al-Kahfi Ayat 1-10",
             "upload_date": "20260801", "duration": 3600,
             "webpage_url": "https://www.youtube.com/watch?v=abc11111111"},
            {"id": "abc22222222", "title": "Ceramah Umum", "upload_date": "20260802",
             "duration": 1800,
             "webpage_url": "https://www.youtube.com/watch?v=abc22222222"},
        ]

    def available(self):
        return True

    def version(self):
        return "2026.01.01"

    def discover_channel(self, channel_url, max_entries=50):
        return self.entries

    def inspect(self, url):
        vid = url.split("=")[-1]
        return {"id": vid, "webpage_url": url, "title": "title", "description": None,
                "channel": "Channel One", "upload_date": "20260801", "duration": 3600}

    def download_video(self, url, output_template):
        return FakeResult(0)

    def download_audio(self, url, output_template):
        vid = url.split("=")[-1]
        # create a fake audio file in the archive directory
        import re

        base = re.sub(r"%\([^)]+\)", "", output_template).replace(".%(ext)s", "")
        audio = Path(output_template).parent / f"title [{vid}].m4a"
        audio.parent.mkdir(parents=True, exist_ok=True)
        audio.write_bytes(b"0" * 500_000)
        return FakeResult(0)


@pytest.fixture()
def settings(tmp_path):
    s = load_settings(config_file=tmp_path / "nope.yaml", project_dir=tmp_path)
    s.storage.base_dir = tmp_path / "data"
    return s


def _add_source(settings, **kw):
    """Register a source in the config so discovery can see it."""
    from tadabbur.config.models import Source

    defaults = dict(
        id="ustaz", name="Ustaz", channel_url="https://youtube.com/@x", enabled=True,
        rights_status="permission_obtained", publication_policy=True,
    )
    defaults.update(kw)
    settings.sources.append(Source(**defaults))


@pytest.fixture()
def repo(settings):
    conn = open_database(settings.storage.database_path)
    yield Repository(conn)
    conn.close()


def test_full_pipeline(tmp_path, settings, repo):
    # source allows publication
    _add_source(settings)
    client = FakeYtClient(settings)

    # 1. DISCOVER
    disc = run_discovery(settings, repo, client=client)
    assert disc.discovered == ["abc11111111", "abc22222222"]

    # 2. CLASSIFY
    classify(repo, settings)
    rows = {r["external_id"]: r["status"] for r in
            repo._conn.execute("SELECT * FROM media").fetchall()}
    assert rows["abc11111111"] == QUEUED   # tadabbur
    assert rows["abc22222222"] == REJECTED  # ceramah umum -> other

    # 3. DOWNLOAD (audio extraction happens here)
    outcomes = run_download(settings, repo, client=client, sleep=lambda _: None)
    assert len(outcomes) == 1
    assert outcomes[0].video_id == "abc11111111"
    row = repo.get_media_by_external_id("abc11111111")
    assert row["status"] == "PROCESSED"
    audio = repo.get_media_file(int(row["id"]), "audio")
    assert audio is not None and Path(audio["path"]).exists()

    # 4. TAG
    tag(repo)
    row = repo.get_media_by_external_id("abc11111111")
    assert row["status"] == TAGGED
    tag_names = {t["name"] for t in repo.tags_for_media(int(row["id"]))}
    assert "quran" in tag_names and "tadabbur" in tag_names
    assert "surah-al-kahf" in tag_names

    # 5. VALIDATE
    run_validation(settings, repo)
    row = repo.get_media_by_external_id("abc11111111")
    assert row["status"] == READY_TO_PUBLISH

    # 6. PUBLISH (filesystem backend to avoid network)
    publish(repo, settings, publisher_name="filesystem")
    row = repo.get_media_by_external_id("abc11111111")
    assert row["status"] == PUBLISHED

    # 7. EXPORT
    result = export_web_data(settings, repo)
    assert result.count == 1
    lectures = json.loads(result.files["lectures.json"].read_text(encoding="utf-8"))
    assert lectures[0]["id"] == "abc11111111"
    assert lectures[0]["category"] == "tadabbur"


def test_duplicate_discovery_is_idempotent(tmp_path, settings, repo):
    _add_source(settings)
    client = FakeYtClient(settings)
    first = run_discovery(settings, repo, client=client)
    second = run_discovery(settings, repo, client=client)
    assert len(first.discovered) == 2
    assert second.discovered == []
    assert len(second.duplicates) == 2
    assert repo._conn.execute("SELECT COUNT(*) c FROM media").fetchone()["c"] == 2
