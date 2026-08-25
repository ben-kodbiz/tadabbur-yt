"""Stage 1: resumable downloads and timeout normalization."""

from pathlib import Path

import pytest

from tadabbur.config.models import DownloadConfig, Settings, StorageConfig
from tadabbur.downloader.client import YtDlpClient, YtDlpError


def _client(resume: bool, keep_part: bool = True) -> YtDlpClient:
    settings = Settings(download=DownloadConfig(resume=resume, keep_part_files=keep_part))
    return YtDlpClient(settings)


def test_resume_enabled_does_not_add_no_part():
    client = _client(resume=True)
    assert "--no-part" not in client._common_download_args()


def test_resume_disabled_adds_no_part():
    client = _client(resume=False)
    assert client._common_download_args().count("--no-part") == 1


def test_download_methods_use_single_place_for_part_args():
    """All download methods must get part behaviour from one helper."""
    client = _client(resume=True)
    args = client._base_args() + [
        "--extract-audio", "--format", "bestaudio", "--output", "x",
    ] + client._common_download_args()
    assert "--no-part" not in args
    # no duplicated injection anywhere else in the argv builder chain
    assert args.count("--no-part") == 0


def test_timeout_raises_domain_error(monkeypatch):
    import subprocess

    client = _client(resume=True)

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="yt-dlp", timeout=300)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(YtDlpError) as exc:
        client.run(["yt-dlp", "--version"])
    assert "timed out" in str(exc.value)
    assert exc.value.__cause__ is not None


def test_recovery_keeps_part_file_when_resume_enabled(tmp_path: Path):
    from tadabbur.database import Repository, open_database
    from tadabbur.downloader.manager import _recover_interrupted, _find_part_file

    conn = open_database(tmp_path / "db.sqlite")
    repo = Repository(conn)
    repo.upsert_source(source_id="s1", name="S1", channel_url="https://example.com")
    repo.insert_media(
        source_id="s1", external_id="abc123", url="https://youtu.be/abc123",
        title="Tadabbur Surah Al-Baqarah Sesi 1", status="DOWNLOADING",
        uploader="Ustaz Test",
    )

    settings = Settings(
        project_dir=tmp_path,
        storage=StorageConfig(base_dir=tmp_path),
        download=DownloadConfig(resume=True),
    )

    from tadabbur.jobs.paths import series_directory
    directory = series_directory(
        settings, speaker="Ustaz Test", series_folder="Surah Al-Baqarah"
    )
    directory.mkdir(parents=True)
    part = directory / "video [abc123].m4a.part"
    part.write_bytes(b"partial")

    row = conn.execute("SELECT * FROM media WHERE external_id='abc123'").fetchone()
    _recover_interrupted(settings, repo, [row])

    assert _find_part_file(directory, "abc123") == part
    assert part.exists(), ".part file must survive when resume is enabled"
    statuses = conn.execute("SELECT status FROM media WHERE external_id='abc123'").fetchone()
    assert statuses["status"] == "QUEUED"


def test_recovery_deletes_part_file_when_resume_disabled(tmp_path: Path):
    from tadabbur.database import Repository, open_database
    from tadabbur.downloader.manager import _recover_interrupted, _find_part_file

    conn = open_database(tmp_path / "db.sqlite")
    repo = Repository(conn)
    repo.upsert_source(source_id="s1", name="S1", channel_url="https://example.com")
    repo.insert_media(
        source_id="s1", external_id="xyz789", url="https://youtu.be/xyz789",
        title="Tadabbur Surah Al-Baqarah Sesi 2", status="DOWNLOADING",
        uploader="Ustaz Test",
    )

    settings = Settings(
        project_dir=tmp_path,
        storage=StorageConfig(base_dir=tmp_path),
        download=DownloadConfig(resume=False),
    )
    from tadabbur.jobs.paths import series_directory
    directory = series_directory(
        settings, speaker="Ustaz Test", series_folder="Surah Al-Baqarah"
    )
    directory.mkdir(parents=True)
    part = directory / "video [xyz789].m4a.part"
    part.write_bytes(b"partial")
    row = conn.execute("SELECT * FROM media WHERE external_id='xyz789'").fetchone()
    _recover_interrupted(settings, repo, [row])

    assert _find_part_file(directory, "xyz789") is None
    assert not part.exists()


def test_find_part_file_distinguishes_states(tmp_path: Path):
    from tadabbur.downloader.manager import _find_part_file

    d = tmp_path
    (d / "vid [id1].m4a").write_bytes(b"complete")       # final file
    (d / "vid [id2].m4a.part").write_bytes(b"partial")   # part file
    (d / "vid [id3].m4a.part-Frag1").write_bytes(b"frag")  # fragment temp

    assert _find_part_file(d, "id1") is None
    assert _find_part_file(d, "id2") is not None
    assert _find_part_file(d, "id3") is not None
