"""Upload pipeline Phase 10: dashboard rendering and actions."""

from pathlib import Path

import pytest

from tadabbur.uploader.database import open_database
from tadabbur.uploader.dashboard import make_handler, render_overview, render_review
from tadabbur.uploader.models import MediaState
from tadabbur.uploader.repository import UploaderRepository


@pytest.fixture
def repo(tmp_path: Path) -> UploaderRepository:
    repo = UploaderRepository(open_database(tmp_path / "pipeline.db"))
    src_id = repo.upsert_source(source_key="s1", name="S1")
    repo.insert_media_item(
        source_id=src_id, platform="youtube", original_media_id="vidAAAAAAAA1",
        original_url="https://youtu.be/vidAAAAAAAA1",
        original_title="Tafsir Al-Fatihah <script>alert(1)</script>",
    )
    return repo


def test_review_page_lists_pending_and_escapes_html(repo):
    page = render_review(repo)
    assert "Rights Review" in page
    assert "Tafsir Al-Fatihah" in page
    assert "<script>" not in page  # XSS escaped
    assert "approve" in page and "block" in page


def test_overview_page_shows_states(repo):
    page = render_overview(repo)
    assert "Overview" in page
    assert "DISCOVERED" in page


def _post(handler_class, path, form):
    """Drive the handler's do_POST directly (no sockets)."""
    import io

    body = "&".join(f"{k}={v}" for k, v in form.items()).encode()
    handler = handler_class.__new__(handler_class)
    handler.path = path
    handler.headers = {"Content-Length": str(len(body))}
    handler.rfile = io.BytesIO(body)
    out = io.BytesIO()

    def send_response(code):
        pass

    def send_header(*a):
        pass

    def end_headers():
        pass

    def write(data):
        out.write(data)

    handler.send_response = send_response
    handler.send_header = send_header
    handler.end_headers = end_headers
    handler.wfile = out

    handler.do_POST()
    return out.getvalue().decode()


class _FakeSettings:
    def __init__(self, project_dir):
        self.project_dir = project_dir


def test_dashboard_approve_action_transitions_item(repo, tmp_path: Path):
    from tadabbur.uploader.config import UploadPipelineSettings

    up = UploadPipelineSettings(database_path=tmp_path / "pipeline.db")
    fake = _FakeSettings(tmp_path)
    fake.project_dir = tmp_path
    handler = make_handler(fake, up)

    item = repo.list_media_by_state(MediaState.DISCOVERED)[0]
    page = _post(handler, "/review", {"id": str(item["id"]), "action": "approve"})

    assert "permission_confirmed" in page or "DOWNLOAD_PENDING" in page
    row = repo.get_media_item(int(item["id"]))
    assert row["state"] == MediaState.DOWNLOAD_PENDING
    assert row["rights_status"] == "permission_confirmed"


def test_dashboard_block_action_blocks_item(repo, tmp_path: Path):
    from tadabbur.uploader.config import UploadPipelineSettings

    up = UploadPipelineSettings(database_path=tmp_path / "pipeline.db")
    fake = _FakeSettings(tmp_path)
    fake.project_dir = tmp_path
    handler = make_handler(fake, up)

    item = repo.list_media_by_state(MediaState.DISCOVERED)[0]
    _post(handler, "/review", {"id": str(item["id"]), "action": "block"})

    row = repo.get_media_item(int(item["id"]))
    assert row["state"] == MediaState.BLOCKED
    assert row["rights_status"] == "upload_not_authorized"
