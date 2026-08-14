"""Metadata preservation: writes archival metadata.json per media item.

Preserves only authoritative source fields from yt-dlp plus classification,
tags, and rights. Never lets model-generated values overwrite source metadata.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from tadabbur.database import Repository
from tadabbur.logging import stage_logger
from tadabbur.metadata.quran_ref import extract_quran_reference

logger = stage_logger("metadata")


@dataclass
class MetadataResult:
    media_id: int
    path: Path
    written: bool = False

    def __str__(self) -> str:
        status = "written" if self.written else "reused"
        return f"[METADATA] media_id={self.media_id} {status} path={self.path}"


def build_metadata(
    repo: Repository,
    *,
    media_id: int,
) -> dict:
    """Assemble the archival metadata payload for a media item."""
    row = repo.get_media(media_id)
    if row is None:
        raise ValueError(f"no media row {media_id}")

    source = repo.get_source(row["source_id"])
    classification = repo.get_effective_classification(media_id)
    tags = [t["name"] for t in repo.tags_for_media(media_id)]
    files = [
        {"kind": f["kind"], "path": f["path"], "size_bytes": f["size_bytes"]}
        for f in repo.list_media_files(media_id)
    ]
    ref = extract_quran_reference(row["title"])

    return {
        "media": {
            "id": row["id"],
            "external_id": row["external_id"],
            "url": row["url"],
            "title": row["title"],
            "description": row["description"],
            "uploader": row["uploader"],
            "channel": row["channel"],
            "published_at": row["published_at"],
            "duration": row["duration"],
            "status": row["status"],
        },
        "source": {
            "source_id": source["id"] if source else row["source_id"],
            "name": source["name"] if source else None,
            "platform": source["platform"] if source else "youtube",
            "channel_url": source["channel_url"] if source else None,
        },
        "rights": {
            "status": row["rights_status"],
            "publication_policy": bool(row["publication_policy"]),
        },
        "classification": (
            {
                "category": classification["category"],
                "confidence": classification["confidence"],
                "method": classification["method"],
                "model": classification["model"],
            }
            if classification
            else None
        ),
        "quran_reference": ref.as_dict(),
        "tags": tags,
        "files": files,
        "classifier": {
            "model": row["classifier_model"],
            "version": row["classifier_version"],
            "qwen_used": bool(row["qwen_used"]),
        },
    }


def write_metadata(
    repo: Repository,
    *,
    media_id: int,
    directory: Path,
) -> MetadataResult:
    """Write metadata.json idempotently (skip if present and current)."""
    row = repo.get_media(media_id)
    if row is None:
        raise ValueError(f"no media row {media_id}")

    payload = build_metadata(repo, media_id=media_id)
    meta_path = directory / "metadata.json"
    if meta_path.exists():
        logger.debug("[METADATA] media_id=%s reused existing metadata.json", media_id)
        return MetadataResult(media_id=media_id, path=meta_path, written=False)

    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info("[METADATA] media_id=%s wrote metadata.json", media_id)
    return MetadataResult(media_id=media_id, path=meta_path, written=True)
