"""Independent artifact validation for the upload pipeline (fix_me.md #5).

Validation success — not render success — gates READY_FOR_UPLOAD.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from tadabbur.logging import stage_logger

logger = stage_logger("up-validate")

MIN_VIDEO_BYTES = 20_000
MIN_AUDIO_BYTES = 10_000
DEFAULT_DURATION_TOLERANCE = 5.0


@dataclass
class ArtifactReport:
    ok: bool
    errors: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return "VALID" if self.ok else f"INVALID: {'; '.join(self.errors)}"


def _probe(path: Path) -> dict | None:
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", "-show_format", str(path)],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(proc.stdout)
        return data if data.get("streams") else None
    except Exception:  # noqa: BLE001 - probe failure means invalid
        return None


def _duration_of(info: dict) -> float | None:
    fmt = info.get("format") or {}
    raw = fmt.get("duration")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    for s in info.get("streams", []):
        if s.get("duration"):
            try:
                return float(s["duration"])
            except ValueError:
                continue
    return None


def validate_youtube_video(
    path: Path | str,
    *,
    expected_duration: float | None = None,
    width: int = 1280,
    height: int = 720,
    duration_tolerance: float = DEFAULT_DURATION_TOLERANCE,
) -> ArtifactReport:
    """Full MP4 gate: container, streams, codecs, resolution, size, duration."""
    p = Path(path)
    errors: list[str] = []

    if not p.exists():
        return ArtifactReport(False, ["file missing"])
    if p.stat().st_size < MIN_VIDEO_BYTES:
        return ArtifactReport(False, [f"file too small ({p.stat().st_size} bytes)"])
    if p.suffix.lower() != ".mp4":
        errors.append(f"container {p.suffix!r} != .mp4")

    info = _probe(p)
    if info is None:
        return ArtifactReport(False, errors + ["ffprobe could not read file"])

    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    if video is None:
        errors.append("missing video stream")
    else:
        if video.get("codec_name") != "h264":
            errors.append(f"video codec {video.get('codec_name')!r} != h264")
        if video.get("width") != width or video.get("height") != height:
            errors.append(
                f"resolution {video.get('width')}x{video.get('height')} != {width}x{height}"
            )
        if video.get("pix_fmt") != "yuv420p":
            errors.append(f"pixel format {video.get('pix_fmt')!r} != yuv420p")

    if audio is None:
        errors.append("missing audio stream")
    elif audio.get("codec_name") != "aac":
        errors.append(f"audio codec {audio.get('codec_name')!r} != aac")

    duration = _duration_of(info)
    if duration is None or duration <= 0:
        errors.append("invalid or zero duration")
    elif expected_duration is not None and abs(expected_duration - duration) > duration_tolerance:
        errors.append(
            f"duration drift {duration:.1f}s vs source {expected_duration:.1f}s "
            f"(tolerance {duration_tolerance:.1f}s)"
        )

    return ArtifactReport(not errors, errors)


def validate_archive_audio(
    path: Path | str,
    *,
    expected_duration: float | None = None,
    codec: str = "opus",
    channels: int | None = 1,
    sample_rate: int | None = None,
    duration_tolerance: float = DEFAULT_DURATION_TOLERANCE,
) -> ArtifactReport:
    """Opus derivative gate: size, codec, channels, rate, duration."""
    p = Path(path)
    errors: list[str] = []

    if not p.exists():
        return ArtifactReport(False, ["file missing"])
    if p.stat().st_size < MIN_AUDIO_BYTES:
        return ArtifactReport(False, [f"file too small ({p.stat().st_size} bytes)"])

    info = _probe(p)
    if info is None:
        return ArtifactReport(False, ["ffprobe could not read file"])

    audio = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), None)
    if audio is None:
        return ArtifactReport(False, ["missing audio stream"])

    if audio.get("codec_name") != codec:
        errors.append(f"codec {audio.get('codec_name')!r} != {codec!r}")
    if channels is not None and int(audio.get("channels") or 0) != channels:
        errors.append(f"channels {audio.get('channels')} != {channels}")
    if sample_rate is not None and int(audio.get("sample_rate") or 0) != sample_rate:
        errors.append(f"sample rate {audio.get('sample_rate')} != {sample_rate}")

    duration = _duration_of(info)
    if duration is None or duration <= 0:
        errors.append("invalid or zero duration")
    elif expected_duration is not None and abs(expected_duration - duration) > duration_tolerance:
        errors.append(
            f"duration drift {duration:.1f}s vs source {expected_duration:.1f}s"
        )

    return ArtifactReport(not errors, errors)


def validate_original(path: Path | str) -> ArtifactReport:
    """Original media gate: exists, non-trivial, decodable, has audio."""
    p = Path(path)
    if not p.exists():
        return ArtifactReport(False, ["file missing"])
    if p.stat().st_size < 1_000:
        return ArtifactReport(False, [f"file too small ({p.stat().st_size} bytes)"])
    info = _probe(p)
    if info is None:
        return ArtifactReport(False, ["ffprobe could not read file"])
    if not any(s.get("codec_type") == "audio" for s in info.get("streams", [])):
        return ArtifactReport(False, ["no audio stream in original"])
    return ArtifactReport(True)
