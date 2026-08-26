"""CLI for the Tadabbur pipeline."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from tadabbur import __version__
from tadabbur.config import load_settings
from tadabbur.logging import setup_logging

app = typer.Typer(
    name="tadabbur",
    help="Local-first Tadabbur media ingestion and cataloguing pipeline.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)
console = Console()

_VERBOSE = False
_GLOBAL_CONFIG: Optional[str] = None


def _settings(config: Optional[str]) -> object:
    return load_settings(config_file=config or _GLOBAL_CONFIG)


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"tadabbur {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config file."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
    version: bool = typer.Option(
        False,
        "--version",
        help="Show version and exit.",
        is_eager=True,
        callback=_version_callback,
    ),
) -> None:
    """Shared CLI options."""
    global _VERBOSE, _GLOBAL_CONFIG
    _VERBOSE = verbose
    if config:
        _GLOBAL_CONFIG = config


@app.command("discover")
def discover(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config file."),
    source: Optional[str] = typer.Option(None, "--source", help="Limit to a single source id."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Log discovered items without writing to DB."),
) -> None:
    """Discover new media metadata from configured sources."""
    from tadabbur.services.discovery import run_discovery

    settings = _settings(config)
    result = run_discovery(settings, source_id=source, dry_run=dry_run)
    console.print(result)


@app.command("classify")
def classify(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config file."),
) -> None:
    """Classify newly discovered media using deterministic rules."""
    from tadabbur.services.classification import run_classification

    settings = _settings(config)
    console.print(run_classification(settings))


@app.command("download")
def download(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config file."),
    video_id: Optional[str] = typer.Option(None, "--video", help="Download a specific video id."),
    limit: int = typer.Option(1, "--limit", help="Maximum items to process."),
    export: Optional[bool] = typer.Option(
        None, "--export/--no-export",
        help="Refresh the web display JSON afterwards (overrides download.auto_export).",
    ),
) -> None:
    """Download queued media and extract audio."""
    from tadabbur.services.download import run_download

    settings = _settings(config)
    console.print(run_download(settings, video_id=video_id, limit=limit))

    do_export = settings.download.auto_export if export is None else export
    if not video_id and do_export:
        try:
            from tadabbur.database import Repository, open_database
            from tadabbur.exporters import export_web_data

            db_path = settings.storage.database_path
            if not db_path.is_absolute():
                db_path = settings.project_dir / db_path
            conn = open_database(db_path)
            try:
                result = export_web_data(settings, Repository(conn), mode="library")
                console.print(f"[EXPORT] refreshed web display: {result.count} items")
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001 - display refresh must never break downloads
            logging.getLogger("tadabbur").warning(
                "[EXPORT] auto-refresh failed (downloads unaffected): %s", exc
            )


@app.command("process")
def process(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config file."),
    video_id: str = typer.Option(..., "--video", help="Video id to process."),
) -> None:
    """Process a single video end-to-end (download -> audio -> tag -> validate)."""
    from tadabbur.services.pipeline import run_process

    settings = _settings(config)
    console.print(run_process(settings, video_id=video_id))


@app.command("validate")
def validate(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config file."),
    video_id: Optional[str] = typer.Option(None, "--video", help="Validate a specific video id."),
) -> None:
    """Validate processed media before publication."""
    from tadabbur.services.validation import run_validation

    settings = _settings(config)
    console.print(run_validation(settings, video_id=video_id))


@app.command("publish")
def publish(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config file."),
    publisher: str = typer.Option("internet_archive", "--publisher", help="Publisher backend."),
    video_id: Optional[str] = typer.Option(None, "--video", help="Publish a specific video id."),
) -> None:
    """Publish ready media to a configured publisher."""
    from tadabbur.services.publish import run_publish

    settings = _settings(config)
    console.print(run_publish(settings, publisher=publisher, video_id=video_id))


@app.command("export")
def export(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config file."),
    mode: str = typer.Option("publish", "--mode", help="'publish' or 'library'."),
) -> None:
    """Export media to web JSON files (publish or internal library)."""
    from tadabbur.services.export import run_export_service

    settings = _settings(config)
    console.print(run_export_service(settings, mode=mode))


@app.command("serve")
def serve(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config file."),
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
    mode: str = typer.Option("library", "--mode", help="'publish' or 'library'."),
) -> None:
    """Serve the web display locally (simple HTTP server)."""
    from tadabbur.services.serve import run_serve

    settings = _settings(config)
    run_serve(settings, host=host, port=port, mode=mode)


@app.command("worker")
def worker(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config file."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Run without performing real work."),
    once: bool = typer.Option(False, "--once", help="Run a single pass and exit."),
) -> None:
    """Run the persistent worker loop over the processing queue."""
    from tadabbur.services.worker import run_worker

    settings = _settings(config)
    run_worker(settings, dry_run=dry_run, once=once)


@app.command("status")
def status(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config file."),
) -> None:
    """Show a summary of the pipeline state."""
    from tadabbur.services.status import run_status

    settings = _settings(config)
    console.print(run_status(settings))


@app.command("retry")
def retry(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config file."),
    failed: bool = typer.Option(False, "--failed", help="Retry all failed items."),
    video_id: Optional[str] = typer.Option(None, "--video", help="Retry a specific video id."),
) -> None:
    """Retry failed or interrupted jobs."""
    from tadabbur.services.retry import run_retry

    settings = _settings(config)
    console.print(run_retry(settings, failed=failed, video_id=video_id))


@app.command("failed")
def failed(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config file."),
) -> None:
    """List failed media items."""
    from tadabbur.services.status import list_failed

    settings = _settings(config)
    console.print(list_failed(settings))


@app.command("inspect")
def inspect(
    video_id: str = typer.Argument(..., help="Video id to inspect."),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config file."),
) -> None:
    """Show the full record for a video id."""
    from tadabbur.services.status import inspect_media

    settings = _settings(config)
    console.print(inspect_media(settings, video_id=video_id))


@app.command("diagnose")
def diagnose(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config file."),
) -> None:
    """Run operational health checks (environment, database, tools, proxy)."""
    from tadabbur.services.diagnose import run_diagnostics

    settings = _settings(config)
    report = run_diagnostics(settings)
    console.print(str(report))
    raise typer.Exit(code=1 if report.has_failure else 0)


if __name__ == "__main__":
    app()
