"""Upload pipeline Phase 5: audio processing tests (synthetic audio, real ffmpeg)."""

import shutil
import subprocess
from pathlib import Path

import pytest

ffmpeg = shutil.which("ffmpeg")
pytestmark = pytest.mark.skipif(ffmpeg is None, reason="ffmpeg not available")


def _make_wav(path: Path, seconds: float = 3.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         str(path)],
        check=True,
    )
    return path


@pytest.fixture
def original(tmp_path: Path) -> Path:
    return _make_wav(tmp_path / "orig" / "maulana-asri__vidAAAAAAAA1__original.wav")


def test_process_audio_produces_opus_derivative(original, tmp_path: Path):
    from tadabbur.uploader.audio_processing import process_audio
    from tadabbur.uploader.config import AudioProfile

    out_dir = tmp_path / "out"
    result = process_audio(original, out_dir, "maulana-asri__vidAAAAAAAA1",
                           AudioProfile(bitrate_kbps=48))
    assert result.ok, result.error
    assert result.audio_path.name.endswith("__audio.opus")
    assert result.audio_path.exists()


def test_duration_validation_passes_for_matching_lengths(original, tmp_path: Path):
    from tadabbur.uploader.audio_processing import process_audio
    from tadabbur.uploader.config import AudioProfile

    result = process_audio(original, tmp_path / "out", "stem1", AudioProfile())
    assert result.ok


def test_codec_matches_profile(original, tmp_path: Path):
    from tadabbur.uploader.audio_processing import _audio_codec, process_audio
    from tadabbur.uploader.config import AudioProfile

    result = process_audio(original, tmp_path / "out", "stem2", AudioProfile())
    assert result.ok
    assert _audio_codec(result.audio_path) == "opus"


def test_idempotent_reuse(original, tmp_path: Path):
    from tadabbur.uploader.audio_processing import process_audio
    from tadabbur.uploader.config import AudioProfile

    out_dir = tmp_path / "out"
    r1 = process_audio(original, out_dir, "stem3", AudioProfile())
    mtime = r1.audio_path.stat().st_mtime_ns
    r2 = process_audio(original, out_dir, "stem3", AudioProfile())
    assert r2.ok and r2.audio_path == r1.audio_path
    assert r2.audio_path.stat().st_mtime_ns == mtime  # untouched


def test_manifest_written(original, tmp_path: Path):
    from tadabbur.uploader.audio_processing import write_processing_manifest
    from tadabbur.uploader.config import AudioProfile

    import json

    path = write_processing_manifest(
        tmp_path, "stem4", profile=AudioProfile(bitrate_kbps=32),
        files={"original": "x.wav", "archive_audio": "x.opus"},
    )
    data = json.loads(path.read_text())
    assert data["processing"]["archive_bitrate_kbps"] == 32
    assert data["files"]["archive_audio"] == "x.opus"
