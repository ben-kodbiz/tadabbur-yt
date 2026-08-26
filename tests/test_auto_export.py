"""Auto-export after download runs (opt-in, never breaks downloads)."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from tadabbur.cli import app


def test_auto_export_defaults_off():
    from tadabbur.config.models import DownloadConfig

    assert DownloadConfig().auto_export is False


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    """Isolated project: config + empty DB + stubbed downloader."""
    from tadabbur.config.models import DownloadConfig, Settings, StorageConfig

    settings = Settings(
        project_dir=tmp_path,
        storage=StorageConfig(base_dir=tmp_path),
        download=DownloadConfig(audio_only=True),
    )
    conn_path = settings.storage.database_path
    from tadabbur.database import Repository, open_database

    conn = open_database(conn_path)
    repo = Repository(conn)
    repo.upsert_source(source_id="s1", name="S1", channel_url="https://example.com")
    repo.insert_media(
        source_id="s1", external_id="vidAUTO00001", url="https://youtu.be/vidAUTO00001",
        title="Tadabbur Surah Al-Kahfi Sesi 1", status="QUEUED",
        uploader="Ustaz Test",
    )
    conn.close()

    class FakeClient:
        def available(self):
            return True

        def version(self):
            return "test"

        def inspect(self, url):
            return {"id": "vidAUTO00001", "webpage_url": url,
                    "title": "Tadabbur Surah Al-Kahfi Sesi 1",
                    "uploader": "Ustaz Test", "upload_date": "20260801",
                    "duration": 60}

        def download_lowest(self, url, tpl):
            out = tpl.replace("%(title)s [%(id)s]", "x").replace("%(ext)s", "m4a")
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_bytes(b"a" * 20000)
            from tadabbur.downloader.client import YtDlpResult

            return YtDlpResult(exit_code=0)

    import tadabbur.services.download as dl_mod

    monkeypatch.setattr(
        dl_mod, "engine_run_download",
        lambda settings, repo, video_id=None, limit=1:
            __import__("tadabbur.downloader.manager", fromlist=["run_download"]).run_download(
                settings, repo, FakeClient(), video_id=video_id, limit=limit),
    )
    return tmp_path, settings


def _config_file(tmp_path: Path, auto_export: bool) -> Path:
    cfg = tmp_path / "conf.yaml"
    cfg.write_text(f"""
download:
  audio_only: true
  resume: true
  auto_export: {str(auto_export).lower()}
""")
    return cfg


def test_download_with_auto_export_flag_refreshes_display(env):
    tmp_path, _ = env
    cfg = _config_file(tmp_path, False)  # config off...
    runner = CliRunner()
    result = runner.invoke(app, [
        "download", "--config", str(cfg), "--limit", "5", "--export",
    ], catch_exceptions=False)
    assert result.exit_code == 0
    data_file = tmp_path / "data" / "exports" / "lectures.json"
    assert data_file.exists(), "--export must refresh web display"


def test_download_without_export_leaves_exports_absent(env):
    tmp_path, _ = env
    cfg = _config_file(tmp_path, False)
    runner = CliRunner()
    result = runner.invoke(app, [
        "download", "--config", str(cfg), "--limit", "5", "--no-export",
    ], catch_exceptions=False)
    assert result.exit_code == 0
    assert not (tmp_path / "data" / "exports" / "lectures.json").exists()


def test_config_auto_export_true_triggers(env):
    tmp_path, _ = env
    cfg = _config_file(tmp_path, True)
    runner = CliRunner()
    result = runner.invoke(app, [
        "download", "--config", str(cfg), "--limit", "5",
    ], catch_exceptions=False)
    assert result.exit_code == 0
    assert (tmp_path / "data" / "exports" / "lectures.json").exists()


def test_broken_export_never_fails_download(env, monkeypatch):
    tmp_path, _ = env
    cfg = _config_file(tmp_path, True)

    import tadabbur.exporters.web as web_mod

    def boom(*a, **kw):
        raise RuntimeError("export exploded")

    monkeypatch.setattr(web_mod, "export_web_data", boom)

    runner = CliRunner()
    result = runner.invoke(app, [
        "download", "--config", str(cfg), "--limit", "5",
    ], catch_exceptions=True)
    # download still succeeded despite export crash
    assert "PROCESSED" in result.output or result.exit_code == 0
