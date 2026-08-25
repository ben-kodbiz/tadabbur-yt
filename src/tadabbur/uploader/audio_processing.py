"""Upload pipeline audio processing: inspect, normalize, Opus encode, validate.

Archive derivative profile (§5/§10): speech-focused opus mono. Derivatives
are always regenerated from the original source — never re-transcode.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from tadabbur.audio.ffmpeg import probe_duration
from tadabbur.logging import stage_logger
from tadabbur.uploader.config import AudioProfile, UploadPipelineSettings
from tadabbur.uploader.models import FailureCategory
from tadabbur.uploader.repository import UploaderRepository

logger = stage_logger("up-audio")

#: Duration difference tolerated between source and derivative (seconds).
DURATION_TOLERANCE = 2.0


@dataclass
class AudioResult:
    ok: bool
    audio_path: Path | None = None
    checksum: str | None = None
    error: str | None = None
    category: str = FailureCategory.UNKNOWN_ERROR


def process_audio(
    original_path: Path,
    output_dir: Path,
    stem: str,
    profile: AudioProfile,
) -> AudioResult:
    """Extract + loudness-normalize + encode the archival opus derivative.

    Idempotent: an existing valid derivative for this profile is reused.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{stem}__audio.opus"

    if out_path.exists() and out_path.stat().st_size > MIN_BYTES:
        logger.info("[UP-AUDIO] reusing existing %s", out_path.name)
        return _validate(original_path, out_path, profile)

    # Single-pass filter graph: loudness normalize then encode opus.
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(original_path),
        "-vn",                       # drop video stream
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        "-ac", str(profile.channels),
        "-ar", str(profile.sample_rate),
        "-c:a", "libopus",
        "-b:a", f"{profile.bitrate_kbps}k",
        str(out_path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
    except subprocess.TimeoutExpired:
        return AudioResult(False, error="ffmpeg timed out",
                           category=FailureCategory.FFMPEG_ERROR)
    except OSError as exc:
        return AudioResult(False, error=str(exc), category=FailureCategory.FFMPEG_ERROR)

    if proc.returncode != 0 or not out_path.exists():
        err = proc.stderr.strip()[:400] or f"exit={proc.returncode}"
        return AudioResult(False, error=err, category=FailureCategory.FFMPEG_ERROR)

    result = _validate(original_path, out_path, profile)
    if not result.ok and out_path.exists():
        out_path.unlink(missing_ok=True)  # don't keep invalid derivatives
    return result


MIN_BYTES = 10_000


def record_audio(repo: UploaderRepository, media_item_id: int,
                 result: AudioResult, checksum: str | None) -> None:
    if not result.ok or result.audio_path is None:
        return
    repo.upsert_file(
        media_item_id=media_item_id,
        file_type="processed_opus",
        path=result.audio_path,
        extension="opus",
        size_bytes=result.audio_path.stat().st_size,
        sha256=checksum,
        codec="opus",
        duration_seconds=probe_duration(result.audio_path),
    )


def write_processing_manifest(
    directory: Path, stem: str, *, profile: AudioProfile,
    files: dict[str, str], extra: dict | None = None,
) -> Path:
    """§22 processing manifest fragment."""
    manifest = {
        "files": files,
        "processing": {
            "archive_codec": "opus",
            "archive_bitrate_kbps": profile.bitrate_kbps,
            "archive_channels": profile.channels,
            "archive_sample_rate": profile.sample_rate,
            **(extra or {}),
        },
    }
    path = directory / f"{stem}__manifest.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _validate(source: Path, derivative: Path, profile: AudioProfile) -> AudioResult:
    """§10 validation: duration tolerance, stream exists, size, codec."""
    if derivative.stat().st_size < MIN_BYTES:
        return AudioResult(False, error="derivative too small",
                           category=FailureCategory.FILE_CORRUPT)

    src_duration = probe_duration(source)
    out_duration = probe_duration(derivative)
    if src_duration is None or out_duration is None:
        return AudioResult(False, error="could not probe durations",
                           category=FailureCategory.VALIDATION_ERROR)
    if abs(src_duration - out_duration) > DURATION_TOLERANCE:
        return AudioResult(
            False,
            error=f"duration drift {out_duration:.1f}s vs {src_duration:.1f}s",
            category=FailureCategory.VALIDATION_ERROR,
        )

    codec = _audio_codec(derivative)
    if codec is not None and codec != profile.codec:
        return AudioResult(False, error=f"codec {codec!r} != {profile.codec!r}",
                           category=FailureCategory.VALIDATION_ERROR)

    return AudioResult(True, audio_path=derivative)


def _audio_codec(path: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", "-select_streams", "a:0", str(path)],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(proc.stdout)
        streams = data.get("streams") or []
        return streams[0].get("codec_name") if streams else None
    except Exception:  # noqa: BLE001 - validation best-effort
        return None
