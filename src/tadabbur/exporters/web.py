"""Web data export: generate static JSON consumed by the web frontend.

SQLite -> JSON files (lectures.json, speakers.json, surahs.json,
categories.json, tags.json). The frontend never touches the ingestion DB.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from tadabbur.config.models import Settings
from tadabbur.database import Repository
from tadabbur.logging import stage_logger

logger = stage_logger("export")


@dataclass
class ExportResult:
    files: dict[str, Path]  # name -> path
    count: int

    def __str__(self) -> str:
        return "[EXPORT] items=%d files=%s" % (self.count, ",".join(self.files))


def _safe_text(value) -> str | None:
    if value is None:
        return None
    return str(value)


def export_web_data(
    settings: Settings,
    repo: Repository,
    *,
    export_dir: Path | None = None,
    mode: str = "publish",
) -> ExportResult:
    """Export media as JSON for the web application.

    ``mode="publish"`` exports only content that may be published publicly.
    ``mode="library"`` exports everything that has been downloaded (audio on
    disk) for internal reference, regardless of publication policy.
    """
    out_dir = export_dir or settings.storage.resolved_exports_dir
    if not out_dir.is_absolute():
        out_dir = settings.project_dir / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    if mode == "library":
        rows = repo._conn.execute(
            """
            SELECT m.*, s.name AS speaker_name, s.platform AS source_platform
            FROM media m
            JOIN sources s ON s.id = m.source_id
            WHERE m.status IN ('PROCESSED', 'FAILED', 'READY_TO_PUBLISH', 'PUBLISHED')
            ORDER BY m.published_at DESC
            """
        ).fetchall()
    else:
        # Only content that is publishable appears in the public web export.
        rows = repo._conn.execute(
            """
            SELECT m.*, s.name AS speaker_name, s.platform AS source_platform
            FROM media m
            JOIN sources s ON s.id = m.source_id
            WHERE m.publication_policy = 1
              AND m.rights_status IN ('open_license', 'permission_obtained', 'source_permitted')
              AND m.status IN ('READY_TO_PUBLISH', 'PUBLISHED')
            ORDER BY m.published_at DESC
            """
        ).fetchall()

    speakers: dict[str, dict] = {}
    surahs: dict[int, dict] = {}
    categories: dict[str, int] = {}
    tags: dict[str, int] = {}
    lectures: list[dict] = []

    for row in rows:
        media_id = int(row["id"])
        classification = repo.get_effective_classification(media_id)
        tag_rows = repo.tags_for_media(media_id)
        audio = repo.get_media_file(media_id, "audio")

        category = classification["category"] if classification else "other"
        categories[category] = categories.get(category, 0) + 1
        for t in tag_rows:
            tags[t["name"]] = tags.get(t["name"], 0) + 1

        speaker_id = row["source_id"]
        if speaker_id not in speakers:
            speakers[speaker_id] = {
                "id": speaker_id,
                "name": row["speaker_name"],
                "platform": row["source_platform"],
                "channel_url": (lambda r: repo.get_source(r)["channel_url"] if r else None)(row["source_id"]),
            }

        ref = {
            "surah_number": None,
            "surah_name": None,
            "ayah_start": None,
            "ayah_end": None,
        }
        # Re-derive quran reference from stored tags for robustness.
        for t in tag_rows:
            name = t["name"]
            if name.startswith("surah-"):
                ref["surah_name"] = name.removeprefix("surah-")
            elif name.startswith("ayah-"):
                parts = name.removeprefix("ayah-").split("-")
                if parts:
                    ref["ayah_start"] = int(parts[0])
                    ref["ayah_end"] = int(parts[-1])

        media_root = settings.storage.resolved_media_dir
        if not media_root.is_absolute():
            media_root = settings.project_dir / media_root
        audio_url = None
        if audio:
            try:
                rel = Path(audio["path"]).resolve().relative_to(media_root.resolve())
                audio_url = f"/media/{rel}"
            except ValueError:
                audio_url = f"/media/{Path(audio['path']).name}"

        lectures.append(
            {
                "id": row["external_id"],
                "title": row["title"],
                "description": _safe_text(row["description"]),
                "speaker": speaker_id,
                "category": category,
                "tags": [t["name"] for t in tag_rows],
                "surah": ref["surah_name"],
                "surah_number": ref["surah_number"],
                "ayah_start": ref["ayah_start"],
                "ayah_end": ref["ayah_end"],
                "published_at": _safe_text(row["published_at"]),
                "duration": row["duration"],
                "source_url": row["url"],
                "audio_path": audio["path"] if audio else None,
                "audio_url": audio_url,
                "rights_status": row["rights_status"],
                "status": row["status"],
                "error": row["error_message"],
            }
        )

    _write_json(out_dir, "lectures.json", lectures)
    _write_json(out_dir, "speakers.json", list(speakers.values()))
    _write_json(out_dir, "surahs.json", sorted(
        ({"name": k, "count": v} for k, v in surahs.items()),
        key=lambda x: str(x["name"]),
    ))
    _write_json(out_dir, "categories.json", [{"name": k, "count": v} for k, v in sorted(categories.items())])
    _write_json(out_dir, "tags.json", [{"name": k, "count": v} for k, v in sorted(tags.items())])

    return ExportResult(
        files={
            "lectures.json": out_dir / "lectures.json",
            "speakers.json": out_dir / "speakers.json",
            "surahs.json": out_dir / "surahs.json",
            "categories.json": out_dir / "categories.json",
            "tags.json": out_dir / "tags.json",
        },
        count=len(lectures),
    )


def _write_json(directory: Path, name: str, data: list) -> None:
    path = directory / name
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("[EXPORT] wrote %s (%d entries)", path, len(data))
