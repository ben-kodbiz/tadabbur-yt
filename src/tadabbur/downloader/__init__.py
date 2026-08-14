"""Downloader subsystem."""

from tadabbur.downloader.circuit_breaker import CircuitBreaker, CircuitState
from tadabbur.downloader.client import YtDlpClient, YtDlpError, YtDlpResult
from tadabbur.downloader.manager import DownloadOutcome, run_download
from tadabbur.downloader.retry import RetryExhaustedError, backoff_delay, retry
from tadabbur.downloader.validator import FileValidation, validate_audio_file, validate_file

__all__ = [
    "CircuitBreaker",
    "CircuitState",
    "DownloadOutcome",
    "FileValidation",
    "RetryExhaustedError",
    "YtDlpClient",
    "YtDlpError",
    "YtDlpResult",
    "backoff_delay",
    "retry",
    "run_download",
    "validate_audio_file",
    "validate_file",
]
