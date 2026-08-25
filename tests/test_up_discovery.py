"""Upload pipeline Phases 2-3: discovery and rights gate."""

from pathlib import Path

import pytest

from tadabbur.uploader.database import open_database
from tadabbur.uploader.discovery import discover_from_channel, sync_sources
from tadabbur.uploader.models import MediaState, UploadRightsStatus
from tadabbur.uploader.repository import UploaderRepository


class FakeClient:
    def __init__(self, entries=None, error=None):
        self._entries = entries or []
        self._error = error

    def available(self):
        return True

    def discover_channel(self, channel_url, max_entries=50):
        if self._error:
            raise self._error
        return self._entries[:max_entries]


@pytest.fixture
def repo(tmp_path: Path) -> UploaderRepository:
    return UploaderRepository(open_database(tmp_path / "pipeline.db"))


def _entry(vid, title="Tafsir Al-Fatihah"):
    return {
        "id": vid,
        "title": title,
        "upload_date": "20260801",
        "duration": 3600,
        "uploader": "Ustaz Test",
        "webpage_url": f"https://www.youtube.com/watch?v={vid}",
    }


def test_sync_sources_defaults_to_manual_review(repo):
    from tadabbur.config.models import Settings, Source, SourceRules

    settings = Settings(sources=[
        Source(id="chan1", name="Chan 1", channel_url="https://example.com/@c1",
               rules=SourceRules()),
    ])
    n = sync_sources(settings, repo)
    assert n == 1
    row = repo.get_source("chan1")
    assert row["default_rights_status"] == UploadRightsStatus.MANUAL_REVIEW_REQUIRED


def test_discovery_registers_new_items_with_identity(repo):
    repo.upsert_source(source_key="s1", name="S1", channel_url="https://example.com")
    client = FakeClient([_entry("vidAAAAAAAA1"), _entry("vidAAAAAAAA2")])

    from tadabbur.config.models import Settings

    res = discover_from_channel(Settings(), repo, client)
    assert len(res.discovered) == 2
    assert len(res.duplicates) == 0

    item = repo.find_media_item("youtube", "vidAAAAAAAA1")
    assert item is not None
    assert item["state"] == MediaState.DISCOVERED
    assert item["rights_status"] == UploadRightsStatus.MANUAL_REVIEW_REQUIRED


def test_discovery_dedup_on_second_run(repo):
    repo.upsert_source(source_key="s1", name="S1", channel_url="https://example.com")
    from tadabbur.config.models import Settings

    client = FakeClient([_entry("vidBBBBBBBB1")])
    discover_from_channel(Settings(), repo, client)
    res2 = discover_from_channel(Settings(), repo, client)
    assert res2.discovered == []
    assert len(res2.duplicates) == 1


def test_discovery_url_duplicate_check(repo):
    """Level-2: same URL under a different platform id is still a duplicate."""
    repo.upsert_source(source_key="s1", name="S1", channel_url="https://example.com")
    e = _entry("vidCCCCCCCC1")
    repo.insert_media_item(
        source_id=1, platform="youtube", original_media_id="OTHERID12345",
        original_url=e["webpage_url"], original_title="same video other id",
    )
    from tadabbur.config.models import Settings

    res = discover_from_channel(Settings(), repo, FakeClient([e]))
    assert res.discovered == [] and len(res.duplicates) == 1


def test_rights_gate_full_flow(repo):
    """discover -> review approve -> DOWNLOAD_PENDING; block path stays out."""
    repo.upsert_source(source_key="s1", name="S1", channel_url="https://example.com")
    from tadabbur.config.models import Settings

    vid = "vidDDDDDDDD1"
    discover_from_channel(Settings(), repo, FakeClient([_entry(vid)]))
    item = repo.find_media_item("youtube", vid)

    # Approve with evidence.
    assert repo.transition(item["id"], MediaState.RIGHTS_REVIEW)
    assert repo.transition(item["id"], MediaState.DOWNLOAD_PENDING)
    repo.review_rights(
        item["id"],
        rights_status=UploadRightsStatus.PERMISSION_CONFIRMED,
        notes="Written permission received",
        permission_reference="REF-1",
    )
    row = repo.get_media_item(item["id"])
    assert row["state"] == MediaState.DOWNLOAD_PENDING
    assert row["rights_status"] == UploadRightsStatus.PERMISSION_CONFIRMED


def test_blocked_item_never_reaches_queue(repo):
    repo.upsert_source(source_key="s1", name="S1", channel_url="https://example.com")
    from tadabbur.config.models import Settings

    vid = "vidEEEEEEEE1"
    discover_from_channel(Settings(), repo, FakeClient([_entry(vid)]))
    item = repo.find_media_item("youtube", vid)

    repo.transition(item["id"], MediaState.RIGHTS_REVIEW)
    repo.transition(item["id"], MediaState.BLOCKED)
    repo.review_rights(item["id"], rights_status=UploadRightsStatus.UPLOAD_NOT_AUTHORIZED,
                       notes="operator decided no")

    # Force it forward is impossible through the machine:
    assert repo.transition(item["id"], MediaState.DOWNLOAD_PENDING) is False
