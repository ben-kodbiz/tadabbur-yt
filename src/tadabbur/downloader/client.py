"""yt-dlp subprocess adapter.

Isolates all raw ``yt-dlp`` invocation behind a single client so the rest of
the application never builds subprocess commands directly.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from tadabbur.config.models import Settings
from tadabbur.logging import stage_logger

logger = stage_logger("ytdlp")


class YtDlpError(Exception):
    """Raised when yt-dlp fails to produce a usable result."""

    def __init__(self, message: str, *, exit_code: int | None = None) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass
class YtDlpResult:
    """Result of a yt-dlp invocation."""

    command: list[str] = field(default_factory=list)
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    elapsed: float = 0.0
    ytdlp_version: str | None = None

    @property
    def success(self) -> bool:
        return self.exit_code == 0

    @property
    def text(self) -> str:
        return (self.stdout or "").strip()


def _bool(v: bool) -> str:
    return "true" if v else "false"


class YtDlpClient:
    """Safe wrapper around the ``yt-dlp`` binary."""

    def __init__(self, settings: Settings, *, binary: str | None = None) -> None:
        self.settings = settings
        self.binary = binary or shutil.which("yt-dlp") or "yt-dlp"
        self._version: str | None = None

    # ------------------------------------------------------------- lifecycle
    def version(self) -> str:
        if self._version is None:
            result = self.run(["--version"])
            self._version = result.text
        return self._version

    def available(self) -> bool:
        return shutil.which(self.binary) is not None

    # --------------------------------------------------------------- helpers
    def _base_args(self) -> list[str]:
        args = [
            self.binary,
            "--no-warnings",
            "--no-color",
            "--sleep-interval",
            str(self.settings.backoff.base_delay),
            "--max-sleep-interval",
            str(self.settings.backoff.max_delay),
            "--socket-timeout",
            str(self.settings.download.socket_timeout),
        ]
        if self.settings.proxy.enabled and self.settings.proxy.url:
            args += ["--proxy", self.settings.proxy.url]
        rate = self.settings.download.limit_rate
        if rate:
            args += ["--limit-rate", rate]
        return args

    def _common_download_args(self) -> list[str]:
        d = self.settings.download
        return [
            "--retries",
            str(d.retries),
            "--fragment-retries",
            str(d.fragment_retries),
            "--concurrent-fragments",
            str(d.concurrent_fragments),
            "--socket-timeout",
            str(d.socket_timeout),
        ]

    def run(self, args: list[str], *, timeout: int | None = None) -> YtDlpResult:
        """Execute yt-dlp with the given arguments (full argv provided)."""
        if not self.available():
            raise YtDlpError("yt-dlp binary not found on PATH")

        cmd = list(args)
        started = time.monotonic()
        logger.debug("yt-dlp argv: %s", cmd)

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout or 300,
            check=False,
        )
        result = YtDlpResult(
            command=cmd,
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            elapsed=time.monotonic() - started,
        )
        if result.exit_code != 0:
            logger.warning(
                "yt-dlp exited %s in %.1fs: %s",
                result.exit_code,
                result.elapsed,
                result.stderr.strip()[-500:],
            )
        return result

    # ------------------------------------------------------------- discovery
    def discover_channel(self, channel_url: str, *, max_entries: int = 50) -> list[dict]:
        """Return flat playlist metadata for a channel without downloading."""
        args = self._base_args() + [
            "--flat-playlist",
            "--dump-single-json",
            "--playlist-end",
            str(max_entries),
            channel_url,
        ]
        result = self.run(args)
        if not result.success:
            raise YtDlpError(
                f"channel discovery failed: {result.stderr.strip()[:400]}",
                exit_code=result.exit_code,
            )
        return self._parse_playlist_json(result.stdout)

    def inspect(self, url: str) -> dict:
        """Fetch full metadata for a single video without downloading media."""
        args = self._base_args() + ["--skip-download", "--dump-single-json", url]
        result = self.run(args)
        if not result.success:
            raise YtDlpError(
                f"video inspect failed: {result.stderr.strip()[:400]}",
                exit_code=result.exit_code,
            )
        data = self._parse_single_json(result.stdout)
        if not data:
            raise YtDlpError("video inspect returned no metadata")
        return data

    # ------------------------------------------------------------ downloads
    def download_video(
        self,
        url: str,
        output_template: str,
        *,
        proxy: str | None = None,
    ) -> YtDlpResult:
        d = self.settings.download
        args = self._base_args() + [
            "--no-part",
            "--merge-output-format",
            d.merge_output_format,
            "--format",
            d.format,
            "--output",
            output_template,
        ]
        if d.keep_video:
            args += ["--write-thumbnail"]
        if d.write_subs or d.write_auto_subs:
            if d.write_subs:
                args.append("--write-subs")
            if d.write_auto_subs:
                args.append("--write-auto-subs")
            args += ["--sub-langs", d.sub_langs]
        if proxy:
            args += ["--proxy", proxy]
        args += self._common_download_args()
        args.append(url)
        return self.run(args)

    def download_audio(
        self,
        url: str,
        output_template: str,
        *,
        proxy: str | None = None,
    ) -> YtDlpResult:
        d = self.settings.download
        args = self._base_args() + [
            "--no-part",
            "--extract-audio",
            "--audio-format",
            d.audio_format,
            "--audio-quality",
            str(d.audio_quality),
            "--format",
            "bestaudio",
            "--output",
            output_template,
        ]
        if proxy:
            args += ["--proxy", proxy]
        args += self._common_download_args()
        args.append(url)
        return self.run(args)

    # --------------------------------------------------------------- parsing
    @staticmethod
    def _parse_playlist_json(raw: str) -> list[dict]:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise YtDlpError(f"could not parse yt-dlp playlist JSON: {exc}") from exc
        entries = data.get("entries") or []
        return [e for e in entries if e and e.get("id")]

    @staticmethod
    def _parse_single_json(raw: str) -> dict | None:
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise YtDlpError(f"could not parse yt-dlp single JSON: {exc}") from exc
