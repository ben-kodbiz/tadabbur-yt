"""Classification service entry point."""

from __future__ import annotations

from tadabbur.classifier import Classification, accepts, classify_metadata
from tadabbur.config.models import Settings, Source
from tadabbur.config.models import SourceRules
from tadabbur.database import Repository, open_database
from tadabbur.logging import stage_logger
from tadabbur.status import MANUAL_REVIEW, QUEUED, REJECTED

logger = stage_logger("classify")


def _source_from_row(row, settings: Settings | None = None) -> Source | None:
    """Convert a sources sqlite row into a config Source model.

    When ``settings`` is provided, the per-source classification rules from
    the YAML config are merged in (the DB stores only scalar source fields).
    """
    if row is None:
        return None
    source = Source(
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
    if settings is not None:
        configured = next((s for s in settings.sources if s.id == row["id"]), None)
        if configured is not None:
            source.rules = configured.rules
    return source


def run_classification(settings: Settings, *, video_id: str | None = None) -> str:
    """Classify DISCOVERED media (optionally a single video), persist result."""
    db_path = settings.storage.database_path
    if not db_path.is_absolute():
        db_path = settings.project_dir / db_path
    conn = open_database(db_path)
    try:
        return classify(repository=Repository(conn), settings=settings, video_id=video_id)
    finally:
        conn.close()


def classify(
    repository: Repository,
    settings: Settings,
    *,
    video_id: str | None = None,
) -> str:
    """Engine: classify DISCOVERED media in the given repository.

    When ``video_id`` is given only that video is classified; batch
    behaviour is unchanged when it is None.
    """
    repo = repository
    lines: list[str] = []
    media_rows = repo.list_media_by_status("DISCOVERED", video_id=video_id)
    threshold = settings.classification.confidence_threshold

    for row in media_rows:
        source = _source_from_row(repo.get_source(row["source_id"]), settings)
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
