"""Stage 8: FFmpeg audio extraction tests."""

from __future__ import annotations

import pytest

from tadabbur.audio import extract_audio, probe_duration

pytestmark = pytest.mark.skipif(
    __import__("tadabbur.audio", fromlist=["available"]).available() is False,
    reason="ffmpeg/ffprobe not available",
)


@pytest.fixture()
def sample_video(tmp_path):
    """Generate a tiny valid mp4 with tone audio via ffmpeg."""
    src = tmp_path / "sample.mp4"
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=1",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=64x64:d=1",
        "-shortest",
        str(src),
    ]
    import subprocess

    subprocess.run(cmd, capture_output=True, check=False)
    return src


def test_extract_audio_creates_m4a(tmp_path, sample_video):
    out = tmp_path / "out.m4a"
    result = extract_audio(sample_video, out)
    assert result.success
    assert out.exists()
    assert out.stat().st_size > 1000
    assert result.duration is not None


def test_extract_audio_idempotent(tmp_path, sample_video):
    out = tmp_path / "out.m4a"
    first = extract_audio(sample_video, out)
    assert first.replaced is True
    second = extract_audio(sample_video, out)
    assert second.replaced is False  # reused existing file


def test_probe_duration(tmp_path, sample_video):
    assert probe_duration(sample_video) is not None
    assert probe_duration(tmp_path / "missing.mp4") is None
