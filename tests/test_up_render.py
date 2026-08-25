"""Upload pipeline Phase 6: video rendering tests (real ffmpeg, synthetic audio)."""

import shutil
import subprocess
from pathlib import Path

import pytest

ffmpeg = shutil.which("ffmpeg")
pytestmark = pytest.mark.skipif(ffmpeg is None, reason="ffmpeg not available")


def _make_opus(path: Path, seconds: float = 5.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-c:a", "libopus", str(path)],
        check=True,
    )
    return path


@pytest.fixture
def audio(tmp_path: Path) -> Path:
    return _make_opus(tmp_path / "in" / "stem__audio.opus")


def test_render_static_card_video(audio, tmp_path: Path):
    from tadabbur.uploader.config import RenderProfile
    from tadabbur.uploader.render import render_card_video

    result = render_card_video(
        audio, tmp_path / "out", "stem",
        RenderProfile(),
        title="Tafsir Surah Al-Fatihah",
        source_name="Ustaz Test",
    )
    assert result.ok, result.error
    assert result.video_path.name == "stem__youtube.mp4"


def test_render_is_idempotent(audio, tmp_path: Path):
    from tadabbur.uploader.config import RenderProfile
    from tadabbur.uploader.render import render_card_video

    kwargs = dict(title="T", source_name="S")
    r1 = render_card_video(audio, tmp_path / "out", "stem2", RenderProfile(), **kwargs)
    mtime = r1.video_path.stat().st_mtime_ns
    r2 = render_card_video(audio, tmp_path / "out", "stem2", RenderProfile(), **kwargs)
    assert r2.ok and r2.video_path.stat().st_mtime_ns == mtime


def test_output_profile_matches_youtube_spec(audio, tmp_path: Path):
    """§12: 1280x720 h264 yuv420p + aac mono."""
    import json as jsonlib

    from tadabbur.uploader.config import RenderProfile
    from tadabbur.uploader.render import render_card_video

    result = render_card_video(
        audio, tmp_path / "out", "stem3", RenderProfile(),
        title="Tafsir", source_name="Chan",
    )
    assert result.ok
    proc = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams",
         str(result.video_path)],
        capture_output=True, text=True, check=True,
    )
    streams = jsonlib.loads(proc.stdout)["streams"]
    v = next(s for s in streams if s["codec_type"] == "video")
    a = next(s for s in streams if s["codec_type"] == "audio")
    assert (v["width"], v["height"]) == (1280, 720)
    assert v["codec_name"] == "h264" and v["pix_fmt"] == "yuv420p"
    assert a["codec_name"] == "aac"


def test_title_card_png_rendered(tmp_path: Path):
    from tadabbur.uploader.render import render_card_png

    out = tmp_path / "card.png"
    card = render_card_png(out, 1280, 720, title="Tafsir Al-Kahfi",
                           source_name="Maulana Asri")
    assert card is not None and card.exists()
    assert card.stat().st_size > 1000
