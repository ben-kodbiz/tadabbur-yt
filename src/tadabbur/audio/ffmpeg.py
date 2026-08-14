"""Controlled FFmpeg wrapper for audio extraction and normalization.

Canonical listening format is M4A/AAC. Extraction is idempotent: if the target
file already exists and passes validation, no transcoding is performed.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from tadabbur.downloader.validator import validate_audio_file
from tadabbur.logging import stage_logger

logger = stage_logger("audio")

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"


class FfmpegError(Exception):
    """Raised when an FFmpeg operation fails."""


@dataclass
class ExtractResult:
    output: Path
    replaced: bool = False
    duration: float | None = None

    @property
    def success(self) -> bool:
        return self.output.exists()


def available() -> bool:
    return shutil.which(FFMPEG) is not None and shutil.which(FFPROBE) is not None


def probe_duration(path: Path | str) -> float | None:
    """Return media duration in seconds using ffprobe, or None on failure."""
    cmd = [
        FFPROBE,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            return None
        return float(proc.stdout.strip())
    except (ValueError, subprocess.TimeoutExpired, OSError):
        return None


def extract_audio(
    source: Path | str,
    output: Path | str,
    *,
    audio_format: str = "m4a",
    quality: int = 5,
    normalize: bool = False,
    force: bool = False,
) -> ExtractResult:
    """Extract/normalize audio from ``source`` to ``output`` (M4A/AAC).

    Idempotent: if ``output`` already exists, is non-empty, and can be probed,
    it is reused (``replaced=False``) instead of transcoding again.
    """
    src = Path(source)
    out = Path(output)

    if not src.exists():
        raise FfmpegError(f"source does not exist: {src}")

    if not force and out.exists():
        duration = probe_duration(out)
        if out.stat().st_size > 0 and duration not in (None, 0.0):
            logger.info("[AUDIO] existing valid audio reused path=%s", out)
            return ExtractResult(output=out, replaced=False, duration=duration)

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f"{out.stem}.tmp{out.suffix}")

    cmd = [
        FFMPEG,
        "-y",
        "-i",
        str(src),
        "-vn",
        "-acodec",
        "aac",
        "-b:a",
        f"{quality * 32}k",
        "-movflags",
        "+faststart",
    ]
    if normalize:
        cmd += ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"]
    cmd.append(str(tmp))

    logger.debug("[AUDIO] ffmpeg argv: %s", cmd)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600, check=False)
    if proc.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise FfmpegError(
            f"ffmpeg failed (exit {proc.returncode}): {proc.stderr.strip()[-500:]}"
        )
    if not tmp.exists():
        tmp.unlink(missing_ok=True)
        raise FfmpegError("ffmpeg produced no output file")

    tmp.replace(out)
    duration = probe_duration(out)
    logger.info("[AUDIO] extracted path=%s duration=%s", out, duration)
    return ExtractResult(output=out, replaced=True, duration=duration)


def normalize_audio(
    source: Path | str,
    output: Path | str,
    *,
    audio_format: str = "m4a",
) -> ExtractResult:
    """Re-encode audio with loudness normalization (idempotent)."""
    return extract_audio(
        source, output, audio_format=audio_format, normalize=True, force=True
    )
