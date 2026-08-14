"""Service that tags processed media and records the tagging step."""

from __future__ import annotations

from tadabbur.config.models import Settings
from tadabbur.database import Repository
from tadabbur.logging import stage_logger, tag
from tadabbur.status import PROCESSED, TAGGED
from tadabbur.tagging import generate_tags

logger = stage_logger("tag")


def run_tagging(settings: Settings, repo: Repository) -> str:
    """Tag all media in PROCESSED state, then mark them TAGGED."""
    lines: list[str] = []
    rows = repo.list_media_by_status(PROCESSED)

    for row in rows:
        classification = repo.get_effective_classification(row["id"])
        category = classification["category"] if classification else "other"

        tags = generate_tags(
            title=row["title"],
            category=category,
            source_id=row["source_id"],
        )
        repo.attach_tags(row["id"], tags, source="rules")
        repo.transition_media(row["id"], TAGGED)
        lines.append(f"{row['external_id']} -> TAGGED tags={','.join(tags) or '(none)'}")
        logger.info(
            "[TAG] video=%s category=%s tags=%s",
            row["external_id"], category, ",".join(tags),
        )

    summary = "[TAG] processed=%d" % len(rows)
    return "\n".join([summary, *lines])
