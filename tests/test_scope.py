"""Stage 3: single-video pipeline scope must not touch unrelated videos."""

from pathlib import Path

import pytest

from tadabbur.config.models import Settings, StorageConfig
from tadabbur.database import Repository, open_database
from tadabbur.services.classification import classify
from tadabbur.services.tagging import tag


def _repo_with_videos(tmp_path: Path, vids: list[str]) -> Repository:
    conn = open_database(tmp_path / "db.sqlite")
    repo = Repository(conn)
    repo.upsert_source(source_id="s1", name="S1", channel_url="https://example.com")
    for v in vids:
        repo.insert_media(
            source_id="s1", external_id=v, url=f"https://youtu.be/{v}",
            title=f"Tadabbur Surah Al-Kahfi Sesi {v}", status="DISCOVERED",
            uploader="Ustaz Test",
        )
    return repo


def _settings(tmp_path: Path) -> Settings:
    return Settings(project_dir=tmp_path, storage=StorageConfig(base_dir=tmp_path))


def test_classify_single_video_leaves_others(tmp_path: Path):
    repo = _repo_with_videos(tmp_path, ["aaa", "bbb"])
    classify(repo, _settings(tmp_path), video_id="aaa")

    statuses = {
        r["external_id"]: r["status"]
        for r in repo._conn.execute("SELECT external_id, status FROM media")
    }
    assert statuses["aaa"] == "QUEUED"      # classified
    assert statuses["bbb"] == "DISCOVERED"  # untouched


def test_classify_batch_processes_all(tmp_path: Path):
    repo = _repo_with_videos(tmp_path, ["aaa", "bbb"])
    classify(repo, _settings(tmp_path))

    statuses = {
        r["external_id"]: r["status"]
        for r in repo._conn.execute("SELECT external_id, status FROM media")
    }
    assert statuses == {"aaa": "QUEUED", "bbb": "QUEUED"}


def test_classify_unknown_video_is_noop(tmp_path: Path):
    repo = _repo_with_videos(tmp_path, ["aaa"])
    result = classify(repo, _settings(tmp_path), video_id="zzz")
    assert "processed=0" in result
    row = repo._conn.execute("SELECT status FROM media WHERE external_id='aaa'").fetchone()
    assert row["status"] == "DISCOVERED"


def test_tag_single_video_leaves_others(tmp_path: Path):
    conn = open_database(tmp_path / "db.sqlite")
    repo = Repository(conn)
    repo.upsert_source(source_id="s1", name="S1", channel_url="https://example.com")
    for v in ["aaa", "bbb"]:
        repo.insert_media(
            source_id="s1", external_id=v, url=f"https://youtu.be/{v}",
            title=f"Tadabbur Surah Al-Kahfi Sesi {v}", status="PROCESSED",
            uploader="Ustaz Test",
        )
    tag(repo, video_id="aaa")

    statuses = {
        r["external_id"]: r["status"]
        for r in conn.execute("SELECT external_id, status FROM media")
    }
    assert statuses["aaa"] == "TAGGED"
    assert statuses["bbb"] == "PROCESSED"
