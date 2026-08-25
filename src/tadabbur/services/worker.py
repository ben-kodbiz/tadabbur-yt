"""Persistent worker loop with graceful shutdown.

Processes the pipeline one stage at a time:
discover -> classify -> download -> tag -> validate -> publish -> export.
Handles SIGINT/SIGTERM without corrupting state.
"""

from __future__ import annotations

import signal
import threading
import time

from tadabbur.config.models import Settings
from tadabbur.database import Repository, open_database
from tadabbur.downloader import run_download
from tadabbur.downloader.circuit_breaker import CircuitBreaker
from tadabbur.exporters import export_web_data
from tadabbur.logging import setup_logging, stage_logger, tag as log_tag
from tadabbur.services.classification import classify
from tadabbur.services.lock import WorkerLock
from tadabbur.services.publish import publish
from tadabbur.services.tagging import tag as tag_stage
from tadabbur.validator import run_validation

logger = stage_logger("worker")

_shutdown_event = threading.Event()


def install_signal_handlers() -> None:
    """Install graceful shutdown handlers for SIGINT/SIGTERM."""
    def _handler(signum, frame):  # noqa: ARG001
        logger.info("[WORKER] received signal %d, shutting down gracefully", signum)
        _shutdown_event.set()

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)


def run_worker(
    settings: Settings,
    *,
    dry_run: bool = False,
    once: bool = False,
) -> str:
    """Run the worker loop. Returns when shutdown is requested or once=True."""
    setup_logging()
    install_signal_handlers()
    breaker = CircuitBreaker(settings.circuit_breaker)
    _shutdown_event.clear()

    db_path = settings.storage.database_path
    if not db_path.is_absolute():
        db_path = settings.project_dir / db_path

    # Single-instance protection: never overlap with another worker.
    lock = WorkerLock(settings.resolve_path(settings.storage.base_dir) / "worker.lock")
    if not lock.acquire():
        logger.warning("[WORKER] another worker is active, exiting safely")
        return "[WORKER] another worker is active, exiting safely"

    conn = open_database(db_path)
    repo = Repository(conn)
    try:
        passes = 0
        while not _shutdown_event.is_set():
            passes += 1
            try:
                run_single_pass(settings, repo, dry_run=dry_run, breaker=breaker)
            except Exception as exc:  # noqa: BLE001 - keep worker alive
                logger.error("[WORKER] pass %d failed: %s", passes, exc)
                if once:
                    return f"[WORKER] pass failed: {exc}"
            if once:
                return f"[WORKER] completed {passes} pass(es)"
            time.sleep(settings.scheduler.worker_interval_minutes * 60)

        logger.info("[WORKER] shutdown requested")
        return "[WORKER] shutdown requested"
    finally:
        conn.close()
        lock.release()


def run_single_pass(
    settings: Settings,
    repo: Repository,
    *,
    dry_run: bool = False,
    breaker: CircuitBreaker | None = None,
) -> None:
    """Run one full pipeline pass (stages are individually resumable)."""
    logger.info(log_tag("WORKER", "starting pipeline pass"))

    if dry_run:
        logger.info("[WORKER] dry-run: no real work performed")
        return

    # 1. discover
    from tadabbur.discovery import run_discovery

    disc = run_discovery(settings, repo)
    logger.info(
        "[WORKER] discover done: new=%d errors=%d",
        len(disc.discovered), len(disc.errors),
    )

    # 2. classify
    classify(repo, settings)

    # 3. download + audio
    run_download(settings, repo, circuit_breaker=breaker)

    # 4. tag
    tag_stage(repo)

    # 5. validate
    run_validation(settings, repo)

    # 6. publish
    publish(repo, settings, publisher_name="internet_archive")

    # 7. export web data
    try:
        export_web_data(settings, repo)
    except Exception as exc:  # noqa: BLE001 - export must not kill the pipeline
        logger.warning("[WORKER] web export failed: %s", exc)

    logger.info(log_tag("WORKER", "pipeline pass complete"))
