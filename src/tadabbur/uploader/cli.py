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


@app.command("queue")
def queue_cmd(
    config: Optional[str] = typer.Option(None, "--config", "-c"),
) -> None:
    """List items ready and eligible for upload (§18)."""
    from tadabbur.uploader.queue import build_queue_plan

    settings, project_dir = _settings(config)
    repo = _repo(settings, project_dir)
    plan = build_queue_plan(settings, repo)

    table = Table(title=f"Upload queue ({len(plan.entries)} eligible)")
    for col in ("ID", "Rights", "Title"):
        table.add_column(col)
    for e in plan.entries:
        table.add_row(str(e.media_item_id), e.rights_status, e.title[:50])
    console.print(table)

    if plan.rejected:
        console.print("[red]Rejected:[/red]")
        for i, reason in plan.rejected:
            console.print(f"  {i}: {reason}")


@app.command("upload")
def upload_cmd(
    action: str = typer.Argument(..., help="run | item"),
    item_id: Optional[int] = typer.Argument(None, help="Item id (for `item`)."),
    limit: int = typer.Option(3, help="Max uploads this run."),
    dry_run: bool = typer.Option(None, "--dry-run/--no-dry-run"),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
) -> None:
    """Upload queued items to YouTube (safety-limited, dry-run default)."""
    from tadabbur.uploader.models import MediaState
    from tadabbur.uploader.queue import check_daily_limit, build_queue_plan
    from tadabbur.uploader.youtube import YouTubeClient, upload_item

    settings, project_dir = _settings(config)
    safety = settings.upload
    do_dry_run = safety.dry_run_default if dry_run is None else dry_run

    if not safety.enabled and not do_dry_run:
        console.print(
            "[UP-UPLOAD] blocked: upload.enabled=false in config "
            "(require_manual_enable). Set enabled=true after review."
        )
        raise typer.Exit(code=2)

    repo = _repo(settings, project_dir)
    plan = build_queue_plan(settings, repo, limit=limit)

    if action == "item":
        if item_id is None or all(e.media_item_id != item_id for e in plan.entries):
            console.print(f"[UP-UPLOAD] item={item_id} not eligible")
            raise typer.Exit(code=1)

    if do_dry_run:
        console.print(f"[UP-UPLOAD] DRY RUN — would upload {len(plan.entries)} item(s):")
        for e in plan.entries:
            console.print(f"  {e.media_item_id}: {e.title[:60]}")
        return

    try:
        check_daily_limit(settings, repo)
    except Exception as exc:
        console.print(f"[UP-UPLOAD] blocked: {exc}")
        raise typer.Exit(code=2) from exc

    client = YouTubeClient()
    targets = [e.media_item_id for e in plan.entries]
    if action == "item" and item_id is not None:
        targets = [item_id]

    uploaded = 0
    for mid in targets:
        outcome = upload_item(repo, settings, client, mid)
        if outcome.ok:
            uploaded += 1
            console.print(f"[UP-UPLOAD] item={mid} -> {outcome.platform_url}")
        else:
            console.print(
                f"[UP-UPLOAD] item={mid} failed ({outcome.category}): "
                f"{(outcome.error or '')[:120]}"
            )
            if outcome.category == "AUTH_ERROR":
                break
    console.print(f"[UP-UPLOAD] done: {uploaded} uploaded")


@app.command("dashboard")
def dashboard_cmd(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8767),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
) -> None:
    """Local review dashboard (rights approval, queue overview)."""
    from tadabbur.config import load_settings as load_ingest
    from tadabbur.uploader.dashboard import serve_dashboard

    up_settings, _project_dir = _settings(config)
    ingest_settings = load_ingest()  # path resolution for the shared project
    serve_dashboard(ingest_settings, up_settings, host=host, port=port)


@app.command("import")
def import_cmd(
    file: str = typer.Argument(..., help="Path to a local audio/video file."),
    source: str = typer.Option("local-samples", help="Source key."),
    media_id: Optional[str] = typer.Option(None, help="Original media id (default: file hash prefix)."),
    title: Optional[str] = typer.Option(None, help="Original title (default: filename)."),
    speaker: Optional[str] = typer.Option(None, help="Uploader/speaker name."),
    rights: str = typer.Option(
        "manual_review_required",
        help="Rights status to record (e.g. owned_by_operator for your own samples).",
    ),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
) -> None:
    """Register a local file as a pipeline item (offline testing / own content).

    The file is copied into incoming/originals/<source>/<id>/ with provenance,
    exactly as a downloaded item would be.
    """
    import hashlib
    import shutil

    from tadabbur.uploader.models import MediaState

    src_path = Path(file).expanduser().resolve()
    if not src_path.exists():
        raise typer.BadParameter(f"file not found: {src_path}")

    settings, project_dir = _settings(config)
    repo = _repo(settings, project_dir)

    if media_id is None:
        h = hashlib.sha256(src_path.read_bytes()).hexdigest()
        media_id = f"local_{h[:11]}"
    title = title or src_path.stem

    src_id = repo.upsert_source(
        source_key=source, name=source.replace("-", " ").title(),
        channel_url=None, attribution_text=f"Original source: {source}",
    )
    mid = repo.insert_media_item(
        source_id=src_id, platform="local", original_media_id=media_id,
        original_url=src_path.as_uri(), original_title=title,
        uploader_name=speaker, rights_status=rights,
        state=MediaState.DISCOVERED,
    )
    if mid is None:
        console.print(f"[UP-IMPORT] item already exists: {source}/{media_id}")
        raise typer.Exit(code=1)
    mid = int(mid)

    # Copy into the archival layout and record it like a downloaded original.
    directory = project_dir / settings.base_dir / "incoming" / "originals" / source / media_id
    directory.mkdir(parents=True, exist_ok=True)
    dest = directory / f"{source}__{media_id}__original{src_path.suffix}"
    shutil.copy2(src_path, dest)
    repo.upsert_file(media_item_id=mid, file_type="original_media", path=dest,
                     extension=dest.suffix.lstrip("."),
                     size_bytes=dest.stat().st_size)
    # Rights decision recorded explicitly (even for imports).
    if rights != "manual_review_required":
        repo.transition(mid, MediaState.RIGHTS_REVIEW)
        repo.transition(mid, MediaState.DOWNLOAD_PENDING)
        repo.review_rights(mid, rights_status=rights, notes="imported sample")

    console.print(f"[UP-IMPORT] item={mid} source={source}/{media_id} file={dest.name}")


@app.command("process")
def process_cmd(
    item_id: int = typer.Argument(..., help="Media item id."),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
) -> None:
    """Run download -> audio -> render -> validate for one approved item.

    Items imported from local files skip the network stage entirely.
    """
    from tadabbur.config.models import Settings as IngestSettings
    from tadabbur.uploader.process import process_item

    up_settings, project_dir = _settings(config)
    repo = _repo(up_settings, project_dir)
    ingest = IngestSettings(project_dir=project_dir)

    outcome = process_item(ingest, up_settings, repo, item_id)
    console.print(str(outcome))
    raise typer.Exit(code=0 if outcome.ok else 1)


@app.command("export-dashboard")
def export_dashboard_cmd(
    config: Optional[str] = typer.Option(None, "--config", "-c"),
) -> None:
    """Export a read-only static tracking dashboard from pipeline.db."""
    from tadabbur.uploader.export_dashboard import export_dashboard

    up_settings, project_dir = _settings(config)
    repo = _repo(up_settings, project_dir)
    out = export_dashboard(project_dir, up_settings, repo)
    console.print(f"[UP-DASH] dashboard written to {out}")
    console.print(f"  open: file://{out}/index.html")
    console.print(f"  or:   python -m http.server 8899 --directory {out}")


if __name__ == "__main__":
    app()
