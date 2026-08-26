"""yt-dlp subprocess adapter.

Isolates all raw ``yt-dlp`` invocation behind a single client so the rest of
the application never builds subprocess commands directly.
"""

from __future__ import annotations

import json
import re
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

    @property
    def transfer_rate(self) -> str | None:
        """Best-effort download rate from yt-dlp progress lines (e.g. '3.6MiB/s')."""
        match = re.search(
            r"(\d+(?:\.\d+)?\s*(?:[KMGT]?i?B)/s)", self.stderr or ""
        )
        return match.group(1) if match else None


def _bool(v: bool) -> str:
    return "true" if v else "false"


def get_effective_proxy(proxy_config, override_proxy: str | None = None) -> str | None:
    """Single decision point for the effective proxy.

    Priority: per-operation override > configured (enabled) proxy > none.
    Guarantees at most one ``--proxy`` argument per yt-dlp invocation.
    """
    if override_proxy:
        return override_proxy
    if proxy_config.enabled and proxy_config.url:
        return proxy_config.url
    return None


class YtDlpClient:
    """Safe wrapper around the ``yt-dlp`` binary."""

    def __init__(self, settings: Settings, *, binary: str | None = None) -> None:
        self.settings = settings
        self.binary = binary or shutil.which("yt-dlp") or "yt-dlp"
        self._version: str | None = None

    # ------------------------------------------------------------- lifecycle
    def version(self) -> str:
        if self._version is None:
            result = self.run([self.binary, "--version"])
            self._version = result.text
        return self._version

    def available(self) -> bool:
        return shutil.which(self.binary) is not None

    # --------------------------------------------------------------- helpers
    def _base_args(self, *, proxy: str | None = None) -> list[str]:
        args = [
            self.binary,
            "--no-warnings",
            "--no-color",
            "--sleep-interval",
            str(self.settings.download.sleep_interval),
            "--max-sleep-interval",
            str(self.settings.download.max_sleep_interval),
            "--socket-timeout",
            str(self.settings.download.socket_timeout),
        ]
        args += self._proxy_args(proxy)
        rate = self.settings.download.limit_rate
        if rate:
            args += ["--limit-rate", rate]
        return args

    def _proxy_args(self, override: str | None = None) -> list[str]:
        """Exactly one effective ``--proxy`` per invocation.

        Priority: per-operation override > configured proxy > none.
        All proxy decisions are centralized here.
        """
        effective = get_effective_proxy(self.settings.proxy, override)
        return ["--proxy", effective] if effective else []

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
        ] + self._part_args()

    def _part_args(self) -> list[str]:
        """Part-file behaviour, decided in exactly one place.

        ``download.resume = true``  -> allow .part files so yt-dlp can resume.
        ``download.resume = false`` -> --no-part (restart downloads from zero).
        """
        if not self.settings.download.resume:
            return ["--no-part"]
        return []

    def _run_download(self, args: list[str]) -> YtDlpResult:
        """Execute a media download with the configured time budget."""
        return self.run(args, timeout=self.settings.download.download_timeout)

    def run(self, args: list[str], *, timeout: int | None = None) -> YtDlpResult:
        """Execute yt-dlp with the given arguments (full argv provided)."""
        if not self.available():
            raise YtDlpError("yt-dlp binary not found on PATH")

        cmd = list(args)
        started = time.monotonic()
        logger.debug("yt-dlp argv: %s", cmd)

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout or 300,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            logger.warning("yt-dlp timed out after %ss", timeout or 300)
            raise YtDlpError(
                f"yt-dlp timed out after {timeout or 300} seconds"
            ) from exc
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
        args = self._base_args(proxy=proxy) + [
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
        args += self._common_download_args()
        args.append(url)
        return self._run_download(args)

    def download_audio(
        self,
        url: str,
        output_template: str,
        *,
        proxy: str | None = None,
    ) -> YtDlpResult:
        d = self.settings.download
        args = self._base_args(proxy=proxy) + [
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
        args += self._common_download_args()
        args.append(url)
        return self._run_download(args)

    def download_lowest(
        self,
        url: str,
        output_template: str,
        *,
        proxy: str | None = None,
    ) -> YtDlpResult:
        """Download the smallest audio source for audio-only extraction.

        Prefers an already-encapsulated m4a/AAC stream (format ``140``) so no
        re-encode is needed; falls back to ``bestaudio``. FFmpeg is only used
        to correct the container if required (fast).
        """
        args = self._base_args(proxy=proxy) + [
            "--newline",
            "--progress",
            "--format",
            "140/bestaudio",
            "--output",
            output_template,
        ]
        args += self._common_download_args()
        args.append(url)
        return self._run_download(args)

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
