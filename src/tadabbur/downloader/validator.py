"""Validation of downloaded media files."""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass, field
from pathlib import Path

from tadabbur.logging import stage_logger

logger = stage_logger("validator")

MIN_AUDIO_SIZE_BYTES = 10_000


@dataclass
class FileValidation:
    path: Path
    exists: bool = False
    size_bytes: int = 0
    mime_type: str | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return self.exists and not self.errors

    def as_dict(self) -> dict:
        return {
            "path": str(self.path),
            "exists": self.exists,
            "size_bytes": self.size_bytes,
            "mime_type": self.mime_type,
            "errors": self.errors,
        }


def _detect_mime(path: Path) -> str | None:
    try:
        kind, _ = mimetypes.guess_type(str(path))
        return kind
    except Exception:  # noqa: BLE001
        return None


def validate_file(
    path: Path | str,
    *,
    min_size: int = MIN_AUDIO_SIZE_BYTES,
    check_mime: bool = False,
) -> FileValidation:
    """Validate that a downloaded file exists and has a sane size."""
    p = Path(path)
    result = FileValidation(path=p)
    if not p.exists():
        result.errors.append("file does not exist")
        return result

    result.exists = True
    result.size_bytes = p.stat().st_size
    result.mime_type = _detect_mime(p)

    if p.stat().st_size < min_size:
        result.errors.append(
            f"file too small ({p.stat().st_size} bytes < {min_size} bytes)"
        )
    if check_mime and result.mime_type and not result.mime_type.startswith(("audio/", "video/")):
        result.errors.append(f"unexpected mime type: {result.mime_type}")

    return result


def validate_audio_file(path: Path | str, *, min_size: int = MIN_AUDIO_SIZE_BYTES) -> FileValidation:
    """Validate an extracted audio file."""
    result = validate_file(path, min_size=min_size, check_mime=True)
    if result.valid:
        logger.info("[VALIDATE] audio valid path=%s size=%d", path, result.size_bytes)
    else:
        logger.warning("[VALIDATE] audio invalid path=%s errors=%s", path, result.errors)
    return result
