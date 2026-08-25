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


@app.command("discover")
def discover_cmd(
    config: Optional[str] = typer.Option(None, "--config", "-c"),
    tadabbur_config: Optional[str] = typer.Option(
        None, "--ingest-config", help="Ingestion config providing channel sources."
    ),
    max_entries: int = typer.Option(50, help="Max entries per channel scan."),
) -> None:
    """Register sources and scan channels for new media metadata."""
    from tadabbur.config import load_settings as load_ingest_settings
    from tadabbur.downloader.client import YtDlpClient
    from tadabbur.uploader.discovery import discover_from_channel, sync_sources

    settings, project_dir = _settings(config)
    ingest = load_ingest_settings(config_file=tadabbur_config)
    repo = _repo(settings, project_dir)

    n_sources = sync_sources(ingest, repo)
    result = discover_from_channel(ingest, repo, YtDlpClient(ingest), max_entries=max_entries)
    result.sources_checked = list(dict.fromkeys([str(n_sources)] + result.sources_checked))
    console.print(str(result))


@app.command("review")
def review_cmd(
    action: str = typer.Argument(..., help="list | approve | block | archive-only"),
    item_id: Optional[int] = typer.Argument(None, help="Media item id."),
    status: Optional[str] = typer.Option(
        None, "--status", help="Approved rights status to record."
    ),
    notes: Optional[str] = typer.Option(None, help="Evidence notes."),
    reference: Optional[str] = typer.Option(None, "--ref", help="Permission reference."),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
) -> None:
    """Rights review gate: list pending items or record a decision."""
    from tadabbur.uploader.models import APPROVED_FOR_UPLOAD, MediaState
    from tadabbur.uploader.models import UploadRightsStatus as RS

    settings, project_dir = _settings(config)
    repo = _repo(settings, project_dir)

    if action == "list":
        rows = repo.list_media_by_state(MediaState.DISCOVERED, MediaState.RIGHTS_REVIEW)
        table = Table(title=f"Pending rights review ({len(rows)})")
        for col in ("ID", "Title", "Source URL", "Status"):
            table.add_column(col)
        for r in rows:
            table.add_row(str(r["id"]), (r["original_title"] or "")[:40],
                          r["original_url"][:45], r["rights_status"])
        console.print(table)
        return

    if item_id is None:
        raise typer.BadParameter(f"item id required for {action!r}")

    mapping = {
        "approve": None,  # requires --status
        "block": RS.UPLOAD_NOT_AUTHORIZED,
        "archive-only": RS.UPLOAD_NOT_AUTHORIZED,
    }
    if action not in mapping:
        raise typer.BadParameter(f"unknown action {action!r}")

    if action == "approve":
        if status not in APPROVED_FOR_UPLOAD:
            raise typer.BadParameter(
                f"--status must be one of: {', '.join(sorted(APPROVED_FOR_UPLOAD))}"
            )
        chosen = status
        new_state = MediaState.DOWNLOAD_PENDING
    else:
        chosen = mapping[action]
        new_state = MediaState.BLOCKED if action == "block" else MediaState.ARCHIVED

    # DISCOVERED must pass through RIGHTS_REVIEW first.
    row = repo.get_media_item(item_id)
    if row is None:
        raise typer.BadParameter(f"item {item_id} not found")
    if row["state"] == MediaState.DISCOVERED:
        repo.transition(item_id, MediaState.RIGHTS_REVIEW)
    if not repo.transition(item_id, new_state):
        raise typer.BadParameter(
            f"invalid transition {row['state']} -> {new_state}"
        )
    repo.review_rights(item_id, rights_status=chosen, notes=notes, permission_reference=reference)
    console.print(f"[UP-REVIEW] item={item_id} -> {chosen} state={new_state}")


if __name__ == "__main__":
    app()
