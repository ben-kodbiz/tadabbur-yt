"""Read-only tracking dashboard export."""

import json
from pathlib import Path

from tadabbur.uploader.config import UploadPipelineSettings
from tadabbur.uploader.database import open_database
from tadabbur.uploader.export_dashboard import export_dashboard
from tadabbur.uploader.models import MediaState
from tadabbur.uploader.repository import UploaderRepository


def _seed(tmp_path: Path) -> UploaderRepository:
    repo = UploaderRepository(open_database(tmp_path / "pipeline.db"))
    src_id = repo.upsert_source(source_key="s1", name="Chan 1",
                                channel_url="https://example.com")
    # uploaded item
    a = repo.insert_media_item(
        source_id=src_id, platform="youtube", original_media_id="vidAAAAAAAA1",
        original_url="https://youtu.be/vidAAAAAAAA1", original_title="Lecture A",
        uploader_name="Ustaz Test", rights_status="creative_commons",
    )
    repo.mark_uploaded(int(a), platform_video_id="ytAAA1111111",
                       platform_url="https://youtu.be/ytAAA1111111",
                       title_used="[Archive] Lecture A — Ustaz Test")
    # pending review item
    b = repo.insert_media_item(
        source_id=src_id, platform="youtube", original_media_id="vidBBBBBBBB2",
        original_url="https://youtu.be/vidBBBBBBBB2", original_title="Lecture B",
        rights_status="manual_review_required",
    )
    assert a and b
    return repo


def test_export_creates_static_site(tmp_path: Path):
    up = UploadPipelineSettings(base_dir=tmp_path)
    repo = _seed(tmp_path)

    out = export_dashboard(tmp_path, up, repo)
    for f in ("index.html", "style.css", "app.js", "data.json"):
        assert (out / f).exists(), f

    data = json.loads((out / "data.json").read_text())
    assert len(data["items"]) == 2

    by_id = {i["media_id"]: i for i in data["items"]}
    a = by_id["vidAAAAAAAA1"]
    assert a["uploaded"] is True
    assert a["platform_video_id"] == "ytAAA1111111"
    assert a["title"] == "[Archive] Lecture A — Ustaz Test"
    assert a["upload_authorized"] is True

    b = by_id["vidBBBBBBBB2"]
    assert b["uploaded"] is False
    assert b["upload_authorized"] is False


def test_export_is_read_only_and_regenerable(tmp_path: Path):
    up = UploadPipelineSettings(base_dir=tmp_path)
    repo = _seed(tmp_path)
    out1 = export_dashboard(tmp_path, up, repo)
    mtime = (out1 / "data.json").stat().st_mtime_ns
    out2 = export_dashboard(tmp_path, up, repo)
    assert out1 == out2
    # regeneration overwrites cleanly (no duplicates)
    data = json.loads((out2 / "data.json").read_text())
    assert len(data["items"]) == 2
