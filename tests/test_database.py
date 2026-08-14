"""Stage 2: database schema and repository tests."""

from __future__ import annotations

import sqlite3

import pytest

from tadabbur.database import Repository, open_database


@pytest.fixture()
def repo(tmp_path):
    conn = open_database(tmp_path / "test.sqlite")
    yield Repository(conn)
    conn.close()


def test_migrate_creates_tables(tmp_path):
    conn = open_database(tmp_path / "test.sqlite")
    tables = {
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    for expected in [
        "sources",
        "media",
        "media_files",
        "classifications",
        "tags",
        "media_tags",
        "processing_jobs",
        "download_attempts",
        "publish_jobs",
        "schema_version",
    ]:
        assert expected in tables
    conn.close()


def test_source_upsert_and_get(repo):
    repo.upsert_source(source_id="s1", name="Channel A", channel_url="https://youtube.com/@a")
    row = repo.get_source("s1")
    assert row["name"] == "Channel A"
    assert row["enabled"] == 1

    repo.upsert_source(
        source_id="s1", name="Channel A2", channel_url="https://youtube.com/@a", enabled=False
    )
    row = repo.get_source("s1")
    assert row["name"] == "Channel A2"
    assert row["enabled"] == 0


def test_media_unique_per_source(repo):
    repo.upsert_source(source_id="s1", name="A", channel_url="https://youtube.com/@a")
    repo.upsert_source(source_id="s2", name="B", channel_url="https://youtube.com/@b")

    m1 = repo.insert_media(source_id="s1", external_id="abc123", url="https://youtu.be/abc123", title="T1")
    m2 = repo.insert_media(source_id="s2", external_id="abc123", url="https://youtu.be/abc123", title="T1")
    assert m1 != m2

    with pytest.raises(sqlite3.IntegrityError):
        repo.insert_media(
            source_id="s1", external_id="abc123", url="https://youtu.be/abc123", title="dup"
        )


def test_media_exists_and_duplicate_check(repo):
    repo.upsert_source(source_id="s1", name="A", channel_url="https://youtube.com/@a")
    assert repo.media_exists("s1", "xyz") is False
    repo.insert_media(source_id="s1", external_id="xyz", url="https://youtu.be/xyz", title="T")
    assert repo.media_exists("s1", "xyz") is True


def test_status_transitions(repo):
    repo.upsert_source(source_id="s1", name="A", channel_url="https://youtube.com/@a")
    mid = repo.insert_media(
        source_id="s1", external_id="v1", url="https://youtu.be/v1", title="T", status="DISCOVERED"
    )
    repo.set_media_status(mid, "QUEUED")
    row = repo.get_media(mid)
    assert row["status"] == "QUEUED"
    assert repo.list_media_by_status("QUEUED")[0]["id"] == mid


def test_media_files(repo):
    repo.upsert_source(source_id="s1", name="A", channel_url="https://youtube.com/@a")
    mid = repo.insert_media(source_id="s1", external_id="v1", url="https://youtu.be/v1", title="T")
    repo.upsert_media_file(media_id=mid, kind="audio", path="/tmp/a.m4a", size_bytes=100)
    row = repo.get_media_file(mid, "audio")
    assert row["path"] == "/tmp/a.m4a"
    assert row["size_bytes"] == 100


def test_classification_and_tags(repo):
    repo.upsert_source(source_id="s1", name="A", channel_url="https://youtube.com/@a")
    mid = repo.insert_media(source_id="s1", external_id="v1", url="https://youtu.be/v1", title="T")

    repo.save_classification(
        media_id=mid, category="tadabbur", confidence=0.9, method="rules",
        matched_rules=["keyword:tadabbur"],
    )
    eff = repo.get_effective_classification(mid)
    assert eff["category"] == "tadabbur"
    assert eff["matched_rules"] == '["keyword:tadabbur"]'

    repo.attach_tags(mid, ["quran", "tadabbur"])
    names = {r["name"] for r in repo.tags_for_media(mid)}
    assert names == {"quran", "tadabbur"}
    assert len(repo.list_tags()) == 2


def test_jobs_lifecycle(repo):
    repo.upsert_source(source_id="s1", name="A", channel_url="https://youtube.com/@a")
    mid = repo.insert_media(source_id="s1", external_id="v1", url="https://youtu.be/v1", title="T")

    job_id = repo.create_job(mid, "download")
    claimed = repo.claim_pending_jobs()
    assert len(claimed) == 1
    assert claimed[0]["status"] == "running"
    repo.mark_job_success(job_id)
    assert repo.get_media(mid)["status"] == "DISCOVERED"


def test_job_failure_and_interrupted(repo):
    repo.upsert_source(source_id="s1", name="A", channel_url="https://youtube.com/@a")
    mid = repo.insert_media(source_id="s1", external_id="v1", url="https://youtu.be/v1", title="T")
    job_id = repo.create_job(mid, "audio")
    repo.increment_job_attempt(job_id)
    repo.mark_job_failure(job_id, "boom")
    repo.retry_job(job_id)
    assert repo.get_media(mid)["status"] == "DISCOVERED"
    row = repo.get_pending_job_for_media(mid, "audio")
    assert row["status"] == "pending"


def test_download_attempts(repo):
    repo.upsert_source(source_id="s1", name="A", channel_url="https://youtube.com/@a")
    mid = repo.insert_media(source_id="s1", external_id="v1", url="https://youtu.be/v1", title="T")
    repo.record_download_attempt(media_id=mid, attempt=1, status="failed", exit_code=1, error="e")
    repo.record_download_attempt(media_id=mid, attempt=2, status="failed", exit_code=1, error="e")
    assert repo.count_media_failures(mid) == 2


def test_publish_jobs(repo):
    repo.upsert_source(source_id="s1", name="A", channel_url="https://youtube.com/@a")
    mid = repo.insert_media(source_id="s1", external_id="v1", url="https://youtu.be/v1", title="T")
    job_id = repo.create_publish_job(mid, "internet_archive")
    claimed = repo.claim_pending_publish_jobs()
    assert len(claimed) == 1
    repo.mark_publish_success(job_id, "https://archive.org/details/xyz")
    row = repo._conn.execute("SELECT * FROM publish_jobs WHERE id = ?", (job_id,)).fetchone()
    assert row["status"] == "success"


def test_reset_interrupted_jobs(repo):
    repo.upsert_source(source_id="s1", name="A", channel_url="https://youtube.com/@a")
    mid = repo.insert_media(source_id="s1", external_id="v1", url="https://youtu.be/v1", title="T")
    job_id = repo.create_job(mid, "download")
    repo.claim_pending_jobs()
    assert repo.reset_interrupted() == 1
    row = repo._conn.execute("SELECT * FROM processing_jobs WHERE id = ?", (job_id,)).fetchone()
    assert row["status"] == "pending"
