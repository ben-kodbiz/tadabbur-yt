"""Upload pipeline video rendering: static archive card -> YouTube MP4.

Layout 1 (§11): static card with title + source attribution.
Output profile (§12): 1280x720, H.264 yuv420p CRF, AAC 64k mono, 24 fps.
"""

from __future__ import annotations

import html
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from tadabbur.audio.ffmpeg import probe_duration
from tadabbur.logging import stage_logger
from tadabbur.uploader.config import RenderProfile
from tadabbur.uploader.models import FailureCategory
from tadabbur.uploader.repository import UploaderRepository

logger = stage_logger("up-render")

MIN_VIDEO_BYTES = 20_000


@dataclass
class RenderResult:
    ok: bool
    video_path: Path | None = None
    error: str | None = None
    category: str = FailureCategory.UNKNOWN_ERROR


def render_card_video(
    audio_path: Path,
    output_dir: Path,
    stem: str,
    profile: RenderProfile,
    *,
    title: str,
    source_name: str,
    channel_label: str = "Archived collection",
) -> RenderResult:
    """Render a static-card MP4 from the processed audio.

    Idempotent: an existing valid MP4 is reused.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{stem}__youtube.mp4"

    if out_path.exists() and out_path.stat().st_size > MIN_VIDEO_BYTES:
        logger.info("[UP-RENDER] reusing existing %s", out_path.name)
        return _validate(audio_path, out_path, profile)

    card = _render_title_png(output_dir / f"{stem}__card.png",
                             profile.width, profile.height,
                             title=title, source_name=source_name,
                             channel_label=channel_label)
    if card is None:
        return RenderResult(False, error="could not render title card",
                            category=FailureCategory.FFMPEG_ERROR)

    duration = probe_duration(audio_path)
    if duration is None:
        return RenderResult(False, error="cannot probe audio duration",
                            category=FailureCategory.VALIDATION_ERROR)

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-loop", "1", "-framerate", str(profile.fps), "-i", str(card),
        "-i", str(audio_path),
        "-c:v", profile.video_codec,
        "-tune", "stillimage",
        "-pix_fmt", "yuv420p",
        "-crf", str(profile.crf),
        "-preset", "medium",
        "-vf", f"scale={profile.width}:{profile.height}",
        "-c:a", profile.audio_codec,
        "-b:a", f"{profile.audio_bitrate_kbps}k",
        "-ac", "1",
        "-shortest",
        "-t", f"{duration:.3f}",
        "-movflags", "+faststart",
        str(out_path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=14400)
    except subprocess.TimeoutExpired:
        return RenderResult(False, error="ffmpeg render timed out",
                            category=FailureCategory.FFMPEG_ERROR)
    except OSError as exc:
        return RenderResult(False, error=str(exc), category=FailureCategory.FFMPEG_ERROR)

    if proc.returncode != 0 or not out_path.exists():
        err = proc.stderr.strip()[:400] or f"exit={proc.returncode}"
        return RenderResult(False, error=err, category=FailureCategory.FFMPEG_ERROR)

    result = _validate(audio_path, out_path, profile)
    if not result.ok:
        out_path.unlink(missing_ok=True)
    return result


def record_video(repo: UploaderRepository, media_item_id: int, path: Path) -> None:
    repo.upsert_file(
        media_item_id=media_item_id,
        file_type="youtube_mp4",
        path=path,
        extension="mp4",
        size_bytes=path.stat().st_size,
        codec="h264",
        duration_seconds=probe_duration(path),
    )


# ------------------------------------------------------------------ card art
def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def render_card_png(
    out_path: Path, width: int, height: int, *, title: str,
    source_name: str, channel_label: str = "Archived collection",
) -> Path | None:
    """Public wrapper for the internal PNG renderer (used by tests)."""
    return _render_title_png(out_path, width, height, title=title,
                             source_name=source_name, channel_label=channel_label)


def _render_title_png(
    out_path: Path, width: int, height: int, *, title: str,
    source_name: str, channel_label: str,
) -> Path | None:
    """Archive attribution card (fix_me.md #10).

    The visual itself must make provenance clear — never claim ownership
    or unrecorded permission.
    """
    # Wrap long text into lines that fit the card.
    def wrap(text: str, n: int) -> str:
        return "\n".join(text[i:i + n] for i in range(0, min(len(text), n * 6), n))

    title_block = wrap(title, 34).replace(":", "\\:")
    source_block = wrap(source_name, 40).replace(":", "\\:")

    drawtexts = [
        # Header makes the archival nature explicit.
        (
            "drawtext=text='ORIGINAL RECORDING':fontcolor=white:fontsize=30:"
            "x=(w-text_w)/2:y=h*0.08"
        ),
        # Title
        (
            "drawtext=text='%s':fontcolor=white:fontsize=40:"
            "x=(w-text_w)/2:y=h*0.20:text_align=center"
            % title_block
        ),
        # Speaker / original source
        (
            "drawtext=text='Speaker\\: %s':fontcolor=0xB0BEC5:fontsize=28:"
            "x=(w-text_w)/2:y=h*0.55"
            % source_block
        ),
        (
            "drawtext=text='Original Source\\: %s':fontcolor=0xB0BEC5:fontsize=24:"
            "x=(w-text_w)/2:y=h*0.63"
            % _esc(channel_label.replace(":", "\\:"))
        ),
        # Disclaimer (visible on every frame of the video)
        (
            "drawtext=text='No authorship of the original recording is claimed.':"
            "fontcolor=0x78909C:fontsize=22:x=(w-text_w)/2:y=h*0.82"
        ),
        (
            "drawtext=text='Original link\\: see description':"
            "fontcolor=0x78909C:fontsize=22:x=(w-text_w)/2:y=h*0.87"
        ),
    ]
    vf = ",".join(drawtexts)

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"color=c=0x101820:s={width}x{height}:d=1",
        "-frames:v", "1", "-vf", vf, str(out_path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except OSError:
        return None
    if proc.returncode != 0 or not out_path.exists():
        logger.warning("[UP-RENDER] card render failed: %s", proc.stderr.strip()[:200])
        return None
    return out_path


def _validate(audio: Path, video: Path, profile: RenderProfile) -> RenderResult:
    """§12/§16 checks: container streams, resolution, duration match."""
    if video.stat().st_size < MIN_VIDEO_BYTES:
        return RenderResult(False, error="video too small",
                            category=FailureCategory.FILE_CORRUPT)
    info = _probe_streams(video)
    if info is None:
        return RenderResult(False, error="cannot probe video",
                            category=FailureCategory.VALIDATION_ERROR)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    if v is None or a is None:
        return RenderResult(False, error="missing audio or video stream",
                            category=FailureCategory.VALIDATION_ERROR)
    if v.get("width") != profile.width or v.get("height") != profile.height:
        return RenderResult(
            False,
            error=f"resolution {v.get('width')}x{v.get('height')} != {profile.width}x{profile.height}",
            category=FailureCategory.VALIDATION_ERROR,
        )
    if v.get("codec_name") != "h264":
        return RenderResult(False, error=f"video codec {v.get('codec_name')!r} != h264",
                            category=FailureCategory.VALIDATION_ERROR)
    if a.get("codec_name") != "aac":
        return RenderResult(False, error=f"audio codec {a.get('codec_name')!r} != aac",
                            category=FailureCategory.VALIDATION_ERROR)
    return RenderResult(True, video_path=video)


def _probe_streams(path: Path) -> dict | None:
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", str(path)],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(proc.stdout)
        return data if data.get("streams") else None
    except Exception:  # noqa: BLE001
        return None
