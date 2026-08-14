"""Stage 12 + 13: validation and rights/publication policy tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from tadabbur.config import load_settings
from tadabbur.database import Repository, open_database
from tadabbur.status import READY_TO_PUBLISH, TAGGED
from tadabbur.validator import validate_media


@pytest.fixture()
def settings(tmp_path):
    return load_settings(config_file=tmp_path / "nope.yaml", project_dir=tmp_path)


@pytest.fixture()
def repo(tmp_path):
    conn = open_database(tmp_path / "test.sqlite")
    yield Repository(conn)
    conn.close()


def _seed_ready_candidate(repo, tmp_path, *, rights="permission_obtained", policy=True):
    repo.upsert_source(source_id="ustaz", name="Ustaz", channel_url="https://youtube.com/@x")
    mid = repo.insert_media(
        source_id="ustaz",
        external_id="videoone1234",
        url="https://www.youtube.com/watch?v=videoone1234",
        title="Tadabbur Surah Al-Kahfi Ayat 1-10",
        uploader="Channel One",
        published_at="2026-08-01",
        duration=3600,
        status=TAGGED,
        rights_status=rights,
        publication_policy=policy,
    )
    repo.save_classification(
        media_id=mid, category="tadabbur", confidence=0.95, method="rules"
    )
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"0" * 100_000)
    repo.upsert_media_file(media_id=mid, kind="audio", path=str(audio), size_bytes=100_000)
    meta = tmp_path / "metadata.json"
    meta.write_text("{}", encoding="utf-8")
    repo.upsert_media_file(media_id=mid, kind="metadata", path=str(meta))
    return mid


def test_validation_passes(settings, repo, tmp_path):
    mid = _seed_ready_candidate(repo, tmp_path)
    row = repo.get_media(mid)
    report = validate_media(settings, repo, row)
    assert report.valid
    assert report.checks["audio_file_exists"]
    assert report.checks["rights_known"]
    assert report.checks["publication_policy_ok"]


def test_validation_fails_without_audio(settings, repo, tmp_path):
    mid = _seed_ready_candidate(repo, tmp_path)
    row = repo.get_media(mid)
    # delete audio row
    repo._conn.execute("DELETE FROM media_files WHERE media_id=? AND kind='audio'", (mid,))
    repo._conn.commit()
    report = validate_media(settings, repo, repo.get_media(mid))
    assert not report.valid
    assert any("audio" in e for e in report.errors)


def test_validation_fails_when_policy_disabled(settings, repo, tmp_path):
    mid = _seed_ready_candidate(repo, tmp_path, policy=False)
    report = validate_media(settings, repo, repo.get_media(mid))
    assert not report.valid
    assert any("publication_policy" in e for e in report.errors)


def test_validation_fails_when_rights_restricted(settings, repo, tmp_path):
    mid = _seed_ready_candidate(repo, tmp_path, rights="do_not_publish")
    report = validate_media(settings, repo, repo.get_media(mid))
    assert not report.valid
    assert any("rights" in e for e in report.errors)


def test_validation_fails_without_classification(settings, repo, tmp_path):
    mid = _seed_ready_candidate(repo, tmp_path)
    repo._conn.execute("DELETE FROM classifications WHERE media_id=?", (mid,))
    repo._conn.commit()
    report = validate_media(settings, repo, repo.get_media(mid))
    assert not report.valid
    assert any("classification" in e for e in report.errors)


def test_run_validation_advances_to_ready(settings, repo, tmp_path):
    from tadabbur.validator import run_validation

    mid = _seed_ready_candidate(repo, tmp_path)
    output = run_validation(settings, repo)
    row = repo.get_media(mid)
    assert row["status"] == READY_TO_PUBLISH
    assert "PASS" in output


def test_run_validation_failed_goes_failed(settings, repo, tmp_path):
    from tadabbur.status import FAILED
    from tadabbur.validator import run_validation

    mid = _seed_ready_candidate(repo, tmp_path, policy=False)
    run_validation(settings, repo)
    assert repo.get_media(mid)["status"] == FAILED
