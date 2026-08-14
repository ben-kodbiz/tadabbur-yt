"""Service that runs classification over discovered media and persists results."""

from __future__ import annotations

from tadabbur.classifier import Classification, accepts, classify_metadata
from tadabbur.config.models import Settings
from tadabbur.database import Repository
from tadabbur.logging import stage_logger, tag
from tadabbur.status import (
    MANUAL_REVIEW,
    QUEUED,
    REJECTED,
)

logger = stage_logger("classify")


def run_classification(settings: Settings, repo: Repository) -> str:
    """Classify all DISCOVERED media, persist classification, set status."""
    lines: list[str] = []
    media_rows = repo.list_media_by_status("DISCOVERED")
    threshold = settings.classification.confidence_threshold

    for row in media_rows:
        source = repo.get_source(row["source_id"])
        classification = classify_metadata(
            title=row["title"],
            description=row["description"],
            source=source,
        )
        repo.save_classification(
            media_id=row["id"],
            category=classification.category,
            confidence=classification.confidence,
            method="rules",
            matched_rules=classification.matched_rules,
        )

        if not classification.is_accepted:
            repo.set_media_status(row["id"], REJECTED)
            lines.append(
                tag("CLASSIFY", "video=%s rejected category=%s conf=%.2f"),
            )
            logger.info(
                "[CLASSIFY] video=%s rejected category=%s conf=%.2f",
                row["external_id"],
                classification.category,
                classification.confidence,
            )
            continue

        if accepts(classification, threshold=threshold):
            repo.set_media_status(row["id"], QUEUED)
            lines.append(f"{row['external_id']} -> QUEUED ({classification.category})")
            logger.info(
                "[CLASSIFY] video=%s queued category=%s conf=%.2f",
                row["external_id"],
                classification.category,
                classification.confidence,
            )
        else:
            repo.set_media_status(row["id"], MANUAL_REVIEW)
            lines.append(f"{row['external_id']} -> MANUAL_REVIEW")
            logger.info(
                "[CLASSIFY] video=%s manual_review category=%s conf=%.2f",
                row["external_id"],
                classification.category,
                classification.confidence,
            )

    summary = (
        "[CLASSIFY] processed=%d" % len(media_rows)
    )
    return "\n".join([summary, *lines])
