"""Stage 9 + 10: metadata preservation and deterministic tagging tests."""

from __future__ import annotations

import json

import pytest

from tadabbur.config import load_settings
from tadabbur.database import Repository, open_database
from tadabbur.metadata import build_metadata, write_metadata
from tadabbur.tagging import generate_tags, validate_tags


@pytest.fixture()
def repo(tmp_path):
    conn = open_database(tmp_path / "test.sqlite")
    yield Repository(conn)
    conn.close()


@pytest.fixture()
def media(repo):
    repo.upsert_source(source_id="ustaz", name="Ustaz", channel_url="https://youtube.com/@x")
    mid = repo.insert_media(
        source_id="ustaz",
        external_id="videoone1234",
        url="https://www.youtube.com/watch?v=videoone1234",
        title="Tadabbur Surah Al-Kahfi Ayat 1-10",
        uploader="Channel One",
        published_at="2026-08-01",
        duration=3600,
        status="PROCESSED",
    )
    repo.save_classification(
        media_id=mid, category="tadabbur", confidence=0.95, method="rules",
        matched_rules=["include:tadabbur"],
    )
    repo.attach_tags(mid, ["quran", "tadabbur"])
    repo.upsert_media_file(media_id=mid, kind="audio", path="/x/a.m4a", size_bytes=1000)
    return mid


def test_build_metadata_preserves_source_fields(repo, media):
    payload = build_metadata(repo, media_id=media)
    assert payload["media"]["title"] == "Tadabbur Surah Al-Kahfi Ayat 1-10"
    assert payload["media"]["external_id"] == "videoone1234"
    assert payload["source"]["source_id"] == "ustaz"
    assert payload["rights"]["status"] == "unknown"
    assert payload["classification"]["category"] == "tadabbur"
    assert payload["quran_reference"]["surah_number"] == 18
    assert "quran" in payload["tags"]
    assert payload["files"][0]["kind"] == "audio"


def test_write_metadata_idempotent(repo, media, tmp_path):
    directory = tmp_path / "meta"
    first = write_metadata(repo, media_id=media, directory=directory)
    assert first.written is True
    meta_path = directory / "metadata.json"
    assert meta_path.exists()

    data = json.loads(meta_path.read_text(encoding="utf-8"))
    assert data["media"]["external_id"] == "videoone1234"

    second = write_metadata(repo, media_id=media, directory=directory)
    assert second.written is False


# ------------------------------------------------------------------ tagging
def test_generate_tags_tadabbur():
    tags = generate_tags(title="Tadabbur Surah Al-Kahfi Ayat 1-10", category="tadabbur")
    assert "quran" in tags
    assert "tadabbur" in tags
    assert "surah-al-kahf" in tags
    assert "ayah-1-10" in tags


def test_generate_tags_topic():
    tags = generate_tags(title="Bersabar dan bersyukur dalam ujian", category="tadabbur")
    assert "sabar" in tags
    assert "syukur" in tags


def test_generate_tags_source():
    tags = generate_tags(title="Kuliah", category="other", source_id="ustaz_example")
    assert "source-ustaz-example" in tags


def test_generate_tags_no_duplicates():
    tags = generate_tags(title="Tadabbur Tadabbur Al-Mulk", category="tadabbur")
    assert len(tags) == len(set(tags))


def test_validate_tags_controlled():
    valid, rejected = validate_tags(["quran", "tadabbur", "sabar", "not-a-real-tag"])
    assert "quran" in valid
    assert "sabar" in valid
    assert rejected == ["not-a-real-tag"]


def test_validate_tags_structured_pass():
    valid, rejected = validate_tags(["surah-al-kahf", "ayah-1-10", "source-ustaz", "language-ms"])
    assert len(valid) == 4
    assert rejected == []
