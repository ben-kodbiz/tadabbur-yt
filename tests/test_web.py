"""Web display: library export + serve handler tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tadabbur.config import load_settings
from tadabbur.database import Repository, open_database
from tadabbur.exporters import export_web_data
from tadabbur.services.serve import TadabburHandler, _make_handler
from tadabbur.status import PROCESSED, READY_TO_PUBLISH


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


def _seed_processed(repo, tmp_path, *, external_id="abc11111111", policy=False, rights="permission_obtained"):
    repo.upsert_source(source_id="ustaz", name="Ustaz", channel_url="https://youtube.com/@x")
    mid = repo.insert_media(
        source_id="ustaz", external_id=external_id,
        url=f"https://www.youtube.com/watch?v={external_id}",
        title="Tadabbur Surah Al-Kahfi Ayat 1-10", uploader="Channel One",
        published_at="2026-08-01", duration=3600, status=PROCESSED,
        publication_policy=policy, rights_status=rights,
    )
    repo.save_classification(media_id=mid, category="tadabbur", confidence=0.95, method="rules")
    repo.attach_tags(mid, ["quran", "tadabbur", "surah-al-kahf"])
    audio = tmp_path / "media" / external_id / "audio.m4a"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"0" * 100_000)
    repo.upsert_media_file(media_id=mid, kind="audio", path=str(audio), size_bytes=100_000)
    return mid


def test_library_export_includes_non_publishable(settings, repo, tmp_path):
    mid = _seed_processed(repo, tmp_path, policy=False)
    result = export_web_data(settings, repo, mode="library")
    assert result.count == 1
    lectures = json.loads(result.files["lectures.json"].read_text(encoding="utf-8"))
    assert lectures[0]["id"] == "abc11111111"
    assert lectures[0]["audio_url"].startswith("/media/")
    assert lectures[0]["audio_path"] is not None


def test_publish_export_excludes_non_publishable(settings, repo, tmp_path):
    _seed_processed(repo, tmp_path, policy=False)
    result = export_web_data(settings, repo, mode="publish")
    assert result.count == 0


def test_library_export_includes_publishable(settings, repo, tmp_path):
    _seed_processed(repo, tmp_path, policy=True)
    result = export_web_data(settings, repo, mode="publish")
    assert result.count == 0  # PROCESSED is not publishable status yet

    # advance to READY_TO_PUBLISH
    mid = repo.get_media_by_external_id("abc11111111")["id"]
    repo.transition_media(mid, READY_TO_PUBLISH)
    result = export_web_data(settings, repo, mode="publish")
    assert result.count == 1


def test_serve_handler_serves_index(settings, repo, tmp_path):
    from http import HTTPStatus

    handler = _make_handler(
        media_root=tmp_path / "media", data_dir=tmp_path / "exports", web_dir=Path(__file__).parent.parent / "src" / "tadabbur" / "web"
    )
    assert issubclass(handler, TadabburHandler)
