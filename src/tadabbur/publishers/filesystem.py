"""Filesystem publisher: exports approved media to a directory (test/sandbox backend).

Useful as a reference implementation and for dry-run / staging publication.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from tadabbur.publishers.base import PublishResult, Publisher


class FilesystemPublisher(Publisher):
    """Copies the canonical audio + metadata.json into a publish directory."""

    name = "filesystem"

    def __init__(self, publish_dir: Path) -> None:
        self.publish_dir = Path(publish_dir)

    def publish(self, media_row, repo) -> PublishResult:
        audio = repo.get_media_file(int(media_row["id"]), "audio")
        if audio is None:
            return PublishResult(success=False, error="no audio file recorded")

        src = Path(audio["path"])
        if not src.exists():
            return PublishResult(success=False, error=f"audio missing on disk: {src}")

        target_dir = self.publish_dir / media_row["external_id"]
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / src.name
        shutil.copy2(src, target)

        meta = repo.get_media_file(int(media_row["id"]), "metadata")
        if meta is not None and Path(meta["path"]).exists():
            shutil.copy2(meta["path"], target_dir / "metadata.json")

        return PublishResult(
            success=True,
            external_url=str(target),
            detail=f"copied {src.name} to {target_dir}",
        )
