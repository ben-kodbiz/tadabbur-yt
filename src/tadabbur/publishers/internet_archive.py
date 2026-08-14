"""Internet Archive publisher.

Uses the ``internetarchive`` library when installed (``pip install .[ia]``).
Persists publish state in SQLite and never fails the core pipeline: failures
leave the media in READY_TO_PUBLISH (or a pending publish job) for retry.
"""

from __future__ import annotations

from pathlib import Path

from tadabbur.publishers.base import PublishResult, Publisher


class InternetArchivePublisher(Publisher):
    """Uploads canonical audio to archive.org as a new item."""

    name = "internet_archive"

    def __init__(self, *, identifier_prefix: str = "tadabbur-", collection: str = "") -> None:
        self.identifier_prefix = identifier_prefix
        self.collection = collection
        self._ia = None

    @property
    def available(self) -> bool:
        if self._ia is None:
            try:
                import internetarchive  # noqa: F401

                self._ia = True
            except ImportError:
                self._ia = False
        return self._ia

    def publish(self, media_row, repo) -> PublishResult:
        if not self.available:
            return PublishResult(
                success=False,
                error="internetarchive library not installed (pip install '.[ia]')",
            )
        import internetarchive

        audio = repo.get_media_file(int(media_row["id"]), "audio")
        if audio is None:
            return PublishResult(success=False, error="no audio file recorded")
        audio_path = Path(audio["path"])
        if not audio_path.exists():
            return PublishResult(success=False, error=f"audio missing on disk: {audio_path}")

        identifier = f"{self.identifier_prefix}{media_row['external_id']}"
        metadata = self._build_metadata(repo, int(media_row["id"]))

        try:
            item = internetarchive.get_item(identifier)
            item.upload(
                {audio_path.name: str(audio_path)},
                metadata=metadata,
                access_key=__import__("os").environ.get("IA_ACCESS_KEY"),
                secret_key=__import__("os").environ.get("IA_SECRET_KEY"),
            )
        except Exception as exc:  # noqa: BLE001
            return PublishResult(
                success=False,
                error=f"archive.org upload failed: {exc}",
            )

        return PublishResult(
            success=True,
            external_url=f"https://archive.org/details/{identifier}",
            detail=f"uploaded {audio_path.name} to {identifier}",
        )

    @staticmethod
    def _build_metadata(repo, media_id: int) -> dict:
        row = repo.get_media(media_id)
        source = repo.get_source(row["source_id"])
        classification = repo.get_effective_classification(media_id)
        tags = [t["name"] for t in repo.tags_for_media(media_id)]

        creator = row["uploader"] or (source["name"] if source else None) or "Unknown"
        return {
            "title": row["title"],
            "description": row["description"] or "",
            "creator": creator,
            "collection": ("opensource_audio",),
            "date": (row["published_at"] or ""),
            "subject": ",".join(tags),
            "external-identifier": row["url"],
            "originalurl": row["url"],
            "category": classification["category"] if classification else "",
            "licenseurl": "",
        }
