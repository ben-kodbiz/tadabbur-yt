"""Audio subsystem."""

from tadabbur.audio.ffmpeg import (
    ExtractResult,
    FfmpegError,
    available,
    extract_audio,
    normalize_audio,
    probe_duration,
)

__all__ = [
    "ExtractResult",
    "FfmpegError",
    "available",
    "extract_audio",
    "normalize_audio",
    "probe_duration",
]
