"""Stage 14 + 15: publisher and web export tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tadabbur.config import load_settings
from tadabbur.database import Repository, open_database
from tadabbur.exporters import export_web_data
from tadabbur.publishers import FilesystemPublisher, InternetArchivePublisher
from tadabbur.services.publish import publish as publish_engine
from tadabbur.status import PUBLISHED, READY_TO_PUBLISH


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


def _seed_ready(repo, tmp_path, *, external_id="videoone1234", policy=True):
    repo.upsert_source(source_id="ustaz", name="Ustaz", channel_url="https://youtube.com/@x")
    mid = repo.insert_media(
        source_id="ustaz",
        external_id=external_id,
        url=f"https://www.youtube.com/watch?v={external_id}",
        title="Tadabbur Surah Al-Kahfi Ayat 1-10",
        uploader="Channel One",
        published_at="2026-08-01",
        duration=3600,
        status=READY_TO_PUBLISH,
        rights_status="permission_obtained",
        publication_policy=policy,
    )
    repo.save_classification(media_id=mid, category="tadabbur", confidence=0.95, method="rules")
    repo.attach_tags(mid, ["quran", "tadabbur", "surah-al-kahf", "ayah-1-10"])
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"0" * 100_000)
    repo.upsert_media_file(media_id=mid, kind="audio", path=str(audio), size_bytes=100_000)
    meta = tmp_path / "metadata.json"
    meta.write_text("{}", encoding="utf-8")
    repo.upsert_media_file(media_id=mid, kind="metadata", path=str(meta))
    return mid


# ---------------------------------------------------------------- filesystem publisher
def test_filesystem_publisher(settings, repo, tmp_path):
    mid = _seed_ready(repo, tmp_path)
    pub_dir = tmp_path / "published"
    publisher = FilesystemPublisher(pub_dir)
    result = publisher.publish(repo.get_media(mid), repo)
    assert result.success
    target = pub_dir / "videoone1234" / "audio.m4a"
    assert target.exists()


def test_filesystem_publisher_missing_audio(settings, repo, tmp_path):
    mid = _seed_ready(repo, tmp_path)
    repo._conn.execute("DELETE FROM media_files WHERE media_id=? AND kind='audio'", (mid,))
    repo._conn.commit()
    publisher = FilesystemPublisher(tmp_path / "pub")
    result = publisher.publish(repo.get_media(mid), repo)
    assert result.success is False


# ---------------------------------------------------------------- internet archive
def test_internet_archive_requires_library(settings, repo, tmp_path):
    mid = _seed_ready(repo, tmp_path)
    publisher = InternetArchivePublisher()
    result = publisher.publish(repo.get_media(mid), repo)
    # Either the library is absent (graceful error) or present (would hit network).
    assert result.success is False


# ---------------------------------------------------------------- publish service
def test_publish_service_success(settings, repo, tmp_path):
    mid = _seed_ready(repo, tmp_path)
    output = publish_engine(repo, settings, publisher_name="filesystem")
    row = repo.get_media(mid)
    assert row["status"] == PUBLISHED
    job = repo._conn.execute(
        "SELECT * FROM publish_jobs WHERE media_id=?", (mid,)
    ).fetchone()
    assert job["status"] == "success"
    assert "PUBLISHED" in output


def test_publish_service_ignores_unknown_publisher(settings, repo, tmp_path):
    _seed_ready(repo, tmp_path)
    with pytest.raises(ValueError):
        publish_engine(repo, settings, publisher_name="nope")


def test_publish_not_ready(settings, repo, tmp_path):
    mid = _seed_ready(repo, tmp_path)
    repo.transition_media(mid, READY_TO_PUBLISH)
    # set media to DISCOVERED to ensure it's skipped
    repo.set_media_status(mid, "DISCOVERED")
    output = publish_engine(repo, settings, publisher_name="filesystem", video_id="videoone1234")
    assert "not found or not ready" in output


# ---------------------------------------------------------------- web export
def test_export_web_data(settings, repo, tmp_path):
    mid = _seed_ready(repo, tmp_path)
    result = export_web_data(settings, repo)
    assert result.count == 1

    lectures = json.loads((result.files["lectures.json"]).read_text(encoding="utf-8"))
    assert lectures[0]["id"] == "videoone1234"
    # speaker falls back to source name when the title has no ustaz prefix
    assert lectures[0]["speaker"] == "speaker-Ustaz"
    assert lectures[0]["category"] == "tadabbur"
    assert "surah-al-kahf" in lectures[0]["tags"]
    assert lectures[0]["surah"] == "al-kahf"

    speakers = json.loads((result.files["speakers.json"]).read_text(encoding="utf-8"))
    assert any(s["id"] == "speaker-Ustaz" for s in speakers)


def test_export_excludes_non_publishable(settings, repo, tmp_path):
    _seed_ready(repo, tmp_path, external_id="restricted1", policy=False)
    result = export_web_data(settings, repo)
    assert result.count == 0
