"""Tagging service entry point."""

from __future__ import annotations

from tadabbur.config.models import Settings
from tadabbur.database import Repository, open_database
from tadabbur.logging import stage_logger
from tadabbur.status import PROCESSED, TAGGED
from tadabbur.tagging import generate_tags

logger = stage_logger("tag")


def run_tagging(settings: Settings, *, video_id: str | None = None) -> str:
    db_path = settings.storage.database_path
    if not db_path.is_absolute():
        db_path = settings.project_dir / db_path
    conn = open_database(db_path)
    try:
        return tag(repository=Repository(conn), video_id=video_id)
    finally:
        conn.close()


def tag(repository: Repository, *, video_id: str | None = None) -> str:
    """Engine: tag media in PROCESSED state.

    When ``video_id`` is given only that video is tagged; batch behaviour
    is unchanged when it is None.
    """
    repo = repository
    lines: list[str] = []
    rows = repo.list_media_by_status(PROCESSED, video_id=video_id)

    for row in rows:
        classification = repo.get_effective_classification(int(row["id"]))
        category = classification["category"] if classification else "other"

        tags = generate_tags(
            title=row["title"],
            category=category,
            source_id=row["source_id"],
        )
        repo.attach_tags(int(row["id"]), tags, source="rules")
        repo.transition_media(int(row["id"]), TAGGED)
        lines.append(f"{row['external_id']} -> TAGGED tags={','.join(tags) or '(none)'}")
        logger.info("[TAG] video=%s category=%s tags=%s", row["external_id"], category, tags)

    return "[TAG] processed=%d\n%s" % (len(rows), "\n".join(lines))
