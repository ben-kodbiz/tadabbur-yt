"""Stage 6: incremental source sync state."""

from pathlib import Path

from tadabbur.config.models import Settings
from tadabbur.database import Repository, open_database
from tadabbur.discovery.engine import run_discovery


class FakeClient:
    def __init__(self, entries):
        self._entries = entries

    def available(self):
        return True

    def version(self):
        return "test"

    def discover_channel(self, channel_url, max_entries=50):
        return self._entries[:max_entries]


def _source_settings(tmp_path: Path):
    from tadabbur.config.models import Source, SourceRules, StorageConfig

    return Settings(
        project_dir=tmp_path,
        storage=StorageConfig(base_dir=tmp_path),
        sources=[
            Source(
                id="s1",
                name="S1",
                channel_url="https://example.com/@chan",
                rules=SourceRules(include=["tadabbur"]),
            )
        ],
    )


def _entries(vids):
    return [
        {
            "id": v,
            "title": f"Tadabbur Surah Al-Kahfi Sesi {v}",
            "upload_date": "20260801",
            "duration": 3600,
            "webpage_url": f"https://www.youtube.com/watch?v={v}",
        }
        for v in vids
    ]


def test_sync_state_recorded_on_success(tmp_path: Path):
    conn = open_database(tmp_path / "db.sqlite")
    repo = Repository(conn)
    settings = _source_settings(tmp_path)

    run_discovery(settings, repo, client=FakeClient(_entries(["vidAAAAAAA1"])))

    state = repo.get_source_sync_state("s1")
    assert state is not None
    assert state["last_error"] is None
    assert state["consecutive_failures"] == 0
    assert state["last_seen_video_id"] == "vidAAAAAAA1"


def test_sync_state_records_failure(tmp_path: Path):
    from tadabbur.downloader.client import YtDlpError

    class FailingClient(FakeClient):
        def discover_channel(self, channel_url, max_entries=50):
            raise YtDlpError("channel discovery failed: boom")

    conn = open_database(tmp_path / "db.sqlite")
    repo = Repository(conn)
    settings = _source_settings(tmp_path)

    run_discovery(settings, repo, client=FailingClient([]))

    state = repo.get_source_sync_state("s1")
    assert state is not None
    assert state["consecutive_failures"] == 1
    assert "boom" in state["last_error"]


def test_known_history_stops_scan_early(tmp_path: Path):
    """After 5 consecutive known ids the scan stops (efficiency over time)."""

    class CountingClient(FakeClient):
        calls = 0
        served = 0

        def discover_channel(self, channel_url, max_entries=50):
            CountingClient.calls += 1
            entries = self._entries[:max_entries]
            CountingClient.served = len(entries)
            return entries

    vids = [f"new{i:07d}xxx" for i in range(3)] + [f"old{i:07d}xxx" for i in range(10)]
    conn = open_database(tmp_path / "db.sqlite")
    repo = Repository(conn)
    settings = _source_settings(tmp_path)

    # First pass: ingest everything.
    run_discovery(settings, repo, client=FakeClient(_entries(vids)), max_entries=100)
    total = conn.execute("SELECT COUNT(*) c FROM media").fetchone()["c"]
    assert total == 13

    # Second pass with a fresh client serving the same list: early stop.
    counting = CountingClient(_entries(vids))
    result = run_discovery(settings, repo, client=counting, max_entries=100)
    assert result.discovered == []
    assert len(result.duplicates) < 13  # stopped before scanning the whole tail
