"""Logging infrastructure for the Tadabbur pipeline."""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_STAGE_TAGS = {
    "DISCOVER": "[DISCOVER]",
    "CLASSIFY": "[CLASSIFY]",
    "DOWNLOAD": "[DOWNLOAD]",
    "AUDIO": "[AUDIO]",
    "TAG": "[TAG]",
    "VALIDATE": "[VALIDATE]",
    "PUBLISH": "[PUBLISH]",
    "ERROR": "[ERROR]",
}

DEFAULT_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def redact(value: str) -> str:
    """Best-effort redaction of credentials from a string."""
    import re

    patterns = [
        (re.compile(r"(https?://)([^:@/\s]+):([^@/\s]+)@"), r"\1***:***@"),
        (re.compile(r"(password|passwd|token|secret|api[_-]?key)\s*[=:]\s*\S+", re.I), r"\1=***"),
    ]
    out = value
    for pattern, replacement in patterns:
        out = pattern.sub(replacement, out)
    return out


class RedactingFilter(logging.Filter):
    """Redacts credentials before a record is emitted."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(str(record.msg))
        if record.args:
            record.args = tuple(redact(str(a)) if isinstance(a, str) else a for a in record.args)
        return True


def _level_from_env(default: str = "INFO") -> int:
    return getattr(logging, os.getenv("TADABBUR_LOG_LEVEL", default).upper(), logging.INFO)


def setup_logging(
    log_dir: Path | str | None = None,
    *,
    level: int | None = None,
    console: bool = True,
    file: bool = True,
) -> logging.Logger:
    """Configure root logger with console and rotating file handlers.

    Redaction is applied to every handler. Logs written to ``log_dir`` (default
    ``logs/`` relative to the working directory) are rotated at 5 MB, 3 backups.
    """
    root = logging.getLogger()
    root.setLevel(level if level is not None else _level_from_env())
    root.handlers.clear()

    formatter = logging.Formatter(DEFAULT_FORMAT)
    redactor = RedactingFilter()

    if console:
        ch = logging.StreamHandler(sys.stderr)
        ch.setFormatter(formatter)
        ch.addFilter(redactor)
        root.addHandler(ch)

    if file:
        directory = Path(log_dir or "logs")
        directory.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(
            directory / "tadabbur.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        fh.setFormatter(formatter)
        fh.addFilter(redactor)
        root.addHandler(fh)

    return root


def stage_logger(name: str) -> logging.Logger:
    """Return a logger preconfigured for the package namespace."""
    return logging.getLogger(f"tadabbur.{name}")


def tag(stage: str, message: str) -> str:
    """Prefix a message with the canonical stage tag for observability."""
    tag_prefix = _STAGE_TAGS.get(stage.upper(), f"[{stage.upper()}]")
    return f"{tag_prefix} {message}"


__all__ = [
    "RedactingFilter",
    "redact",
    "setup_logging",
    "stage_logger",
    "tag",
]
