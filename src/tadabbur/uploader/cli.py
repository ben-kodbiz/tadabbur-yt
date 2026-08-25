"""CLI for the upload pipeline (separate `upipeline` entry point)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from tadabbur.uploader.config import UploadPipelineSettings
from tadabbur.uploader.database import open_database
from tadabbur.uploader.repository import UploaderRepository

app = typer.Typer(help="Upload pipeline: archived audio -> YouTube.")
console = Console()

CONFIG_ENV = "UPLOAD_PIPELINE_CONFIG"


def _settings(config: Optional[str]) -> tuple[UploadPipelineSettings, Path]:
    """Load settings; project dir is the CWD (or config file's parent)."""
    import os

    path = config or os.environ.get(CONFIG_ENV)
    if path:
        cfg_file = Path(path)
        data = __import__("yaml").safe_load(cfg_file.read_text()) if cfg_file.exists() else {}
        settings = UploadPipelineSettings(**(data or {}))
        return settings, cfg_file.parent
    return UploadPipelineSettings(), Path.cwd()


def _repo(settings: UploadPipelineSettings, project_dir: Path) -> UploaderRepository:
    conn = open_database(settings.resolve_database_path(project_dir))
    return UploaderRepository(conn)


@app.command("init")
def init_cmd(
    config: Optional[str] = typer.Option(None, "--config", "-c"),
) -> None:
    """Create the pipeline database."""
    settings, project_dir = _settings(config)
    db_path = settings.resolve_database_path(project_dir)
    open_database(db_path)
    console.print(f"[UP] database ready: {db_path}")


@app.command("status")
def status_cmd(
    config: Optional[str] = typer.Option(None, "--config", "-c"),
) -> None:
    """Show a summary of media states and the upload queue."""
    settings, project_dir = _settings(config)
    repo = _repo(settings, project_dir)

    table = Table(title="Upload pipeline status")
    table.add_column("State")
    table.add_column("Items", justify="right")
    for state, n in repo.summary().items():
        table.add_row(state, str(n))
    console.print(table)

    queue = repo.list_upload_queue()
    console.print(f"[UP] upload-eligible now: {len(queue)}")


if __name__ == "__main__":
    app()
