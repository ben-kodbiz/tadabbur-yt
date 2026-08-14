"""CLI for the Tadabbur pipeline."""

from __future__ import annotations

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
) -> None:
    """Download queued media and extract audio."""
    from tadabbur.services.download import run_download

    settings = _settings(config)
    console.print(run_download(settings, video_id=video_id, limit=limit))


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
) -> None:
    """Export publishable media to web JSON files."""
    from tadabbur.services.export import run_export_service

    settings = _settings(config)
    console.print(run_export_service(settings))


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


if __name__ == "__main__":
    app()
