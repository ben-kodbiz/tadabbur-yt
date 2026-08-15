"""Failure recovery integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from tadabbur.config import load_settings
from tadabbur.database import Repository, open_database
from tadabbur.discovery import run_discovery
from tadabbur.downloader import run_download
from tadabbur.downloader.circuit_breaker import CircuitBreaker
from tadabbur.status import FAILED, PROCESSED, QUEUED
from tadabbur.services.retry import run_retry


class FlakyClient:
    """Succeeds only on the Nth audio attempt, mimicking transient failures."""

    def __init__(self, settings, succeed_on_attempt=2):
        self.settings = settings
        self.succeed_on_attempt = succeed_on_attempt
        self.attempts = 0

    def available(self):
        return True

    def version(self):
        return "2026.01.01"

    def discover_channel(self, channel_url, max_entries=50):
        return [
            {"id": "abc11111111", "title": "Tadabbur Surah Al-Kahfi Ayat 1-10",
             "upload_date": "20260801", "duration": 3600,
             "webpage_url": "https://www.youtube.com/watch?v=abc11111111"},
        ]

    def inspect(self, url):
        return {"id": "abc11111111", "webpage_url": url, "title": "T",
                "channel": "C", "upload_date": "20260801", "duration": 3600}

    def download_video(self, url, output_template):
        return type("R", (), {"exit_code": 0, "stderr": ""})()

    def download_audio(self, url, output_template):
        self.attempts += 1
        if self.attempts < self.succeed_on_attempt:
            return type("R", (), {"exit_code": 1, "stderr": "transient network error"})()
        audio = Path(output_template).parent / "title [abc11111111].m4a"
        audio.parent.mkdir(parents=True, exist_ok=True)
        audio.write_bytes(b"0" * 500_000)
        return type("R", (), {"exit_code": 0, "stderr": ""})()


@pytest.fixture()
def settings(tmp_path):
    from tadabbur.config.models import Source

    s = load_settings(config_file=tmp_path / "nope.yaml", project_dir=tmp_path)
    s.storage.base_dir = tmp_path / "data"
    s.sources.append(
        Source(id="ustaz", name="Ustaz", channel_url="https://youtube.com/@x",
               enabled=True, rights_status="permission_obtained", publication_policy=True)
    )
    s.backoff.max_attempts = 3
    return s


@pytest.fixture()
def repo(settings):
    conn = open_database(settings.storage.database_path)
    yield Repository(conn)
    conn.close()


def test_transient_failure_recovers(settings, repo):
    disc = run_discovery(
        settings, repo, client=FlakyClient(settings),
    )
    assert disc.discovered == ["abc11111111"]

    from tadabbur.services.classification import classify

    classify(repo, settings)
    assert repo.get_media_by_external_id("abc11111111")["status"] == QUEUED

    client = FlakyClient(settings)
    breaker = CircuitBreaker(settings.circuit_breaker)
    outcomes = run_download(settings, repo, client=client, circuit_breaker=breaker, sleep=lambda _: None)
    assert outcomes[0].status == PROCESSED
    assert client.attempts >= 2  # first attempt failed, second succeeded


def test_persistent_failure_marks_failed_then_retry(settings, repo):
    run_discovery(settings, repo, client=FlakyClient(settings))
    from tadabbur.services.classification import classify

    classify(repo, settings)

    client = FlakyClient(settings, succeed_on_attempt=999)  # always fails
    breaker = CircuitBreaker(settings.circuit_breaker)
    outcomes = run_download(settings, repo, client=client, circuit_breaker=breaker, sleep=lambda _: None)
    assert outcomes[0].status == FAILED
    assert repo.get_media_by_external_id("abc11111111")["status"] == FAILED

    # manual retry re-queues it
    out = run_retry(settings, failed=True)
    assert "requeued=1" in out
    assert repo.get_media_by_external_id("abc11111111")["status"] == QUEUED


def test_circuit_breaker_blocks_after_failures(settings, repo):
    breaker = CircuitBreaker(settings.circuit_breaker)
    breaker.config.failure_threshold = 2
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.allow_request() is False  # open during cooldown


def test_interrupted_download_recovers_and_retries(settings, repo):
    """A crash mid-download leaves media in DOWNLOADING; it must be retried."""
    from tadabbur.services.classification import classify

    run_discovery(settings, repo, client=FlakyClient(settings))
    classify(repo, settings)
    assert repo.get_media_by_external_id("abc11111111")["status"] == QUEUED

    # Simulate a crash: item was in DOWNLOADING when the process died.
    repo.transition_media(
        repo.get_media_by_external_id("abc11111111")["id"], "DOWNLOADING"
    )
    assert repo.get_media_by_external_id("abc11111111")["status"] == "DOWNLOADING"

    # A fresh run must recover it and finish.
    client = FlakyClient(settings)
    breaker = CircuitBreaker(settings.circuit_breaker)
    outcomes = run_download(settings, repo, client=client, circuit_breaker=breaker, sleep=lambda _: None)
    assert outcomes[0].status == PROCESSED
    assert repo.get_media_by_external_id("abc11111111")["status"] == PROCESSED


def test_interrupted_audio_processing_with_existing_audio_recovered(settings, repo):
    """AUDIO_PROCESSING with an existing valid audio file is advanced, not redone."""
    from tadabbur.services.classification import classify

    run_discovery(settings, repo, client=FlakyClient(settings))
    classify(repo, settings)
    mid = repo.get_media_by_external_id("abc11111111")["id"]

    # Complete the download so an audio file exists.
    run_download(settings, repo, client=FlakyClient(settings), sleep=lambda _: None)
    assert repo.get_media(mid)["status"] == PROCESSED

    # Simulate a crash that left the media in AUDIO_PROCESSING but audio valid.
    repo.transition_media(mid, "AUDIO_PROCESSING")
    outcomes = run_download(settings, repo, client=FlakyClient(settings), sleep=lambda _: None)
    # no re-download performed; recovered directly
    assert outcomes == []
    assert repo.get_media(mid)["status"] == PROCESSED
