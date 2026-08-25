"""Operational health diagnostics: `tadabbur diagnose`.

Conservative checks only — a WARN does not mean the pipeline is broken.
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
from dataclasses import dataclass, field

from tadabbur.config.models import Settings
from tadabbur.database import open_database
from tadabbur.logging import stage_logger
from tadabbur.downloader.client import get_effective_proxy

logger = stage_logger("diagnose")


@dataclass
class DiagnosticsReport:
    checks: list[tuple[str, str, str]] = field(default_factory=list)  # (status, name, detail)

    def ok(self, name: str, detail: str = "") -> None:
        self.checks.append(("OK", name, detail))

    def warn(self, name: str, detail: str = "") -> None:
        self.checks.append(("WARN", name, detail))

    def fail(self, name: str, detail: str = "") -> None:
        self.checks.append(("FAIL", name, detail))

    @property
    def has_failure(self) -> bool:
        return any(status == "FAIL" for status, _, _ in self.checks)

    def __str__(self) -> str:
        lines = ["[DIAGNOSE]"]
        for status, name, detail in self.checks:
            line = f"  [{status}] {name}"
            if detail:
                line += f": {detail}"
            lines.append(line)
        return "\n".join(lines)


def run_diagnostics(settings: Settings) -> DiagnosticsReport:
    report = DiagnosticsReport()

    # Python environment
    report.ok("python", sys.version.split()[0])

    # Configuration validity is implied by reaching this point (pydantic),
    # but verify proxy consistency explicitly.
    if settings.proxy.enabled and not settings.proxy.url:
        report.fail("proxy config", "proxy.enabled is true but proxy.url is empty")
    else:
        report.ok("config")

    # Database reachable + schema current
    try:
        db_path = settings.storage.database_path
        if not db_path.is_absolute():
            db_path = settings.project_dir / db_path
        conn = open_database(db_path)
        version = conn.execute("SELECT version FROM schema_version").fetchone()["version"]
        n_media = conn.execute("SELECT COUNT(*) c FROM media").fetchone()["c"]
        interrupted = conn.execute(
            "SELECT COUNT(*) c FROM media WHERE status IN ('DOWNLOADING','AUDIO_PROCESSING')"
        ).fetchone()["c"]
        conn.close()
        report.ok("database", f"schema v{version}, {n_media} media items")
        if interrupted:
            report.warn("interrupted jobs", f"{interrupted} item(s) mid-download; recovered on next run")
        else:
            report.ok("interrupted jobs", "none")
    except sqlite3.Error as exc:
        report.fail("database", str(exc))

    # yt-dlp available
    ytdlp = shutil.which("yt-dlp")
    if ytdlp:
        report.ok("yt-dlp", ytdlp)
    else:
        report.fail("yt-dlp", "not found on PATH")

    # FFmpeg available
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        report.ok("ffmpeg", ffmpeg)
    else:
        report.warn("ffmpeg", "not found; audio conversion will fail if needed")

    # Output directory writable
    try:
        media_dir = settings.storage.resolved_media_dir
        if not media_dir.is_absolute():
            media_dir = settings.project_dir / media_dir
        media_dir.mkdir(parents=True, exist_ok=True)
        probe = media_dir / ".write-probe"
        probe.write_text("ok")
        probe.unlink()
        report.ok("media dir writable", str(media_dir))
    except OSError as exc:
        report.fail("media dir writable", str(exc))

    # Proxy reachable (warn only — never blocks)
    proxy_url = get_effective_proxy(settings.proxy)
    if proxy_url:
        try:
            import urllib.error
            import urllib.request

            try:
                with urllib.request.urlopen(
                    proxy_url, timeout=settings.proxy.health_check_timeout
                ) as resp:
                    report.warn("proxy", f"{proxy_url} responded HTTP {resp.status}")
            except urllib.error.HTTPError as resp_err:
                # Any HTTP response proves the proxy is reachable.
                report.ok("proxy", f"{proxy_url} reachable (HTTP {resp_err.code})")
        except Exception as exc:  # noqa: BLE001 - diagnostic only
            report.warn("proxy", f"{proxy_url} unreachable ({exc.__class__.__name__})")
    else:
        report.ok("proxy", "disabled")

    # Circuit breaker state
    try:
        repo_repo = None
        db_path = settings.storage.database_path
        if not db_path.is_absolute():
            db_path = settings.project_dir / db_path
        conn2 = open_database(db_path)
        from tadabbur.database import Repository
        from tadabbur.downloader.circuit_breaker import CircuitState

        repo_repo = Repository(conn2)
        saved = repo_repo.load_circuit_state("download")
        conn2.close()
        if saved and saved["state"] == CircuitState.COOLDOWN.value:
            report.warn("circuit breaker", "open (cooldown); downloads paused until expiry")
        else:
            report.ok("circuit breaker", saved["state"] if saved else "normal")
    except Exception as exc:  # noqa: BLE001
        report.warn("circuit breaker", str(exc))

    return report
