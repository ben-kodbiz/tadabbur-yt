"""Stage 7: operational diagnostics."""

from pathlib import Path

from tadabbur.config.models import Settings, StorageConfig
from tadabbur.services.diagnose import run_diagnostics


def _settings(tmp_path: Path) -> Settings:
    return Settings(project_dir=tmp_path, storage=StorageConfig(base_dir=tmp_path))


def test_diagnostics_on_clean_project(tmp_path: Path):
    report = run_diagnostics(_settings(tmp_path))
    names = [name for _, name, _ in report.checks]
    assert "python" in names
    assert "database" in names
    assert "media dir writable" in names
    assert not report.has_failure


def test_diagnostics_warns_on_interrupted_jobs(tmp_path: Path):
    from tadabbur.database import Repository, open_database

    settings = _settings(tmp_path)
    conn = open_database(settings.storage.database_path)
    repo = Repository(conn)
    repo.upsert_source(source_id="s1", name="S1", channel_url="https://example.com")
    repo.insert_media(
        source_id="s1", external_id="abc12345678", url="https://youtu.be/abc12345678",
        title="Tadabbur Surah Al-Kahfi Sesi 1", status="DOWNLOADING",
        uploader="Ustaz Test",
    )
    conn.close()

    report = run_diagnostics(settings)
    interrupted = [c for c in report.checks if c[1] == "interrupted jobs"]
    assert interrupted and interrupted[0][0] == "WARN"


def test_diagnostics_fail_when_ytdlp_missing(tmp_path: Path, monkeypatch):
    import shutil

    monkeypatch.setattr(shutil, "which", lambda _: None)
    # binary lookup also used by shutil.which inside the service module
    from tadabbur.services import diagnose as diag_mod

    monkeypatch.setattr(diag_mod.shutil, "which", lambda _: None)
    report = run_diagnostics(_settings(tmp_path))
    assert report.has_failure
