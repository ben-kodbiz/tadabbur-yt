"""Classification service entry point."""

from __future__ import annotations

from tadabbur.classifier import Classification, accepts, classify_metadata
from tadabbur.config.models import Settings, Source
from tadabbur.config.models import SourceRules
from tadabbur.database import Repository, open_database
from tadabbur.logging import stage_logger
from tadabbur.status import MANUAL_REVIEW, QUEUED, REJECTED

logger = stage_logger("classify")


def _source_from_row(row) -> Source | None:
    """Convert a sources sqlite row into a config Source model (rules incl.)."""
    if row is None:
        return None
    rules_row = None
    # Rules live in config, not the DB; build an empty Source so default
    # keyword rules apply.
    return Source(
        id=row["id"],
        name=row["name"],
        platform=row["platform"],
        channel_url=row["channel_url"],
        channel_id=row["channel_id"],
        enabled=bool(row["enabled"]),
        language=row["language"],
        rights_status=row["rights_status"],
        download_policy=bool(row["download_policy"]),
        publication_policy=bool(row["publication_policy"]),
    )


def run_classification(settings: Settings) -> str:
    """Classify all DISCOVERED media, persist classification, set status."""
    db_path = settings.storage.database_path
    if not db_path.is_absolute():
        db_path = settings.project_dir / db_path
    conn = open_database(db_path)
    try:
        return classify(repository=Repository(conn), settings=settings)
    finally:
        conn.close()


def classify(repository: Repository, settings: Settings) -> str:
    """Engine: classify all DISCOVERED media in the given repository."""
    repo = repository
    lines: list[str] = []
    media_rows = repo.list_media_by_status("DISCOVERED")
    threshold = settings.classification.confidence_threshold

    for row in media_rows:
        source = _source_from_row(repo.get_source(row["source_id"]))
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
            repo.transition_media(int(row["id"]), REJECTED)
            lines.append(f"{row['external_id']} -> REJECTED ({classification.category})")
            logger.info(
                "[CLASSIFY] video=%s rejected category=%s conf=%.2f",
                row["external_id"], classification.category, classification.confidence,
            )
            continue

        if accepts(classification, threshold=threshold):
            repo.transition_media(int(row["id"]), QUEUED)
            lines.append(f"{row['external_id']} -> QUEUED ({classification.category})")
            logger.info(
                "[CLASSIFY] video=%s queued category=%s conf=%.2f",
                row["external_id"], classification.category, classification.confidence,
            )
        else:
            repo.transition_media(int(row["id"]), MANUAL_REVIEW)
            lines.append(f"{row['external_id']} -> MANUAL_REVIEW")
            logger.info(
                "[CLASSIFY] video=%s manual_review category=%s conf=%.2f",
                row["external_id"], classification.category, classification.confidence,
            )

    return "[CLASSIFY] processed=%d\n%s" % (len(media_rows), "\n".join(lines))
