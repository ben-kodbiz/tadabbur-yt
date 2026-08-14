"""Validator: gates media before it can become READY_TO_PUBLISH."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from tadabbur.config.models import Settings
from tadabbur.database import Repository
from tadabbur.logging import stage_logger

logger = stage_logger("validator")

MIN_AUDIO_SIZE = 10_000

# rights statuses that forbid publication
BLOCKED_RIGHTS = frozenset({"restricted", "do_not_publish"})


@dataclass
class ValidationReport:
    media_id: int
    video_id: str
    checks: dict[str, bool] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors

    def __str__(self) -> str:
        status = "PASS" if self.valid else "FAIL"
        lines = [f"[VALIDATE] video={self.video_id} {status}"]
        for check, ok in self.checks.items():
            lines.append(f"[VALIDATE]   {check}: {'ok' if ok else 'FAIL'}")
        for err in self.errors:
            lines.append(f"[VALIDATE]   error: {err}")
        return "\n".join(lines)


def _row_has(row, key: str) -> bool:
    return row is not None and row[key] is not None and row[key] != ""


def validate_media(settings: Settings, repo: Repository, row) -> ValidationReport:
    """Run all pre-publication checks against a media row."""
    report = ValidationReport(media_id=int(row["id"]), video_id=row["external_id"])
    media_id = int(row["id"])

    # 1. source exists
    source = repo.get_source(row["source_id"])
    report.checks["source_exists"] = source is not None
    if source is None:
        report.errors.append("source missing")

    # 2. title exists
    ok = _row_has(row, "title")
    report.checks["title_exists"] = ok
    if not ok:
        report.errors.append("title missing")

    # 3. classification exists
    classification = repo.get_effective_classification(media_id)
    report.checks["classification_exists"] = classification is not None
    if classification is None:
        report.errors.append("classification missing")
    else:
        if classification["category"] == "other":
            report.errors.append("classification is 'other'")

    # 4. audio file exists + valid
    audio = repo.get_media_file(media_id, "audio")
    report.checks["audio_file_exists"] = audio is not None
    audio_path: Path | None = None
    if audio is None:
        report.errors.append("audio file missing")
    else:
        audio_path = Path(audio["path"])
        report.checks["audio_on_disk"] = audio_path.exists()
        if not audio_path.exists():
            report.errors.append(f"audio file not on disk: {audio_path}")

        size_ok = audio["size_bytes"] is not None and audio["size_bytes"] >= MIN_AUDIO_SIZE
        if audio["size_bytes"] is None:
            try:
                audio["size_bytes"] = audio_path.stat().st_size if audio_path.exists() else 0
            except OSError:
                pass
            size_ok = audio["size_bytes"] >= MIN_AUDIO_SIZE
        report.checks["audio_size_ok"] = size_ok
        if not size_ok:
            report.errors.append("audio file too small")

    # 5. metadata exists on disk
    meta = repo.get_media_file(media_id, "metadata")
    report.checks["metadata_exists"] = meta is not None and Path(meta["path"]).exists()
    if not report.checks["metadata_exists"]:
        report.errors.append("metadata.json missing")

    # 6. duration sensible
    report.checks["duration_sensible"] = True
    if row["duration"] is not None:
        if not (30 <= int(row["duration"]) <= 4 * 3600):
            report.checks["duration_sensible"] = False
            report.errors.append(f"duration out of range: {row['duration']}")

    # 7. rights allowed (publishable only when policy permits)
    rights = row["rights_status"] or "unknown"
    policy = bool(row["publication_policy"])
    report.checks["rights_known"] = rights in {"open_license", "permission_obtained", "source_permitted"}
    report.checks["publication_policy_ok"] = policy
    if rights in BLOCKED_RIGHTS:
        report.errors.append(f"rights forbid publication: {rights}")
    if not policy:
        report.errors.append("publication_policy is disabled")

    # 8. no duplicate (source_id, external_id unique is enforced by schema)
    report.checks["duplicate_check"] = True

    return report


def run_validation(settings: Settings, repo: Repository, *, video_id: str | None = None) -> str:
    """Validate TAGGED media (or a specific video) and advance to READY_TO_PUBLISH."""
    from tadabbur.status import FAILED, READY_TO_PUBLISH, TAGGED

    if video_id:
        row = repo.get_media_by_external_id(video_id)
        rows = [row] if row else []
        if not rows:
            return f"[VALIDATE] video={video_id} not found"
    else:
        rows = repo.list_media_by_status(TAGGED)

    lines: list[str] = []
    for row in rows:
        report = validate_media(settings, repo, row)
        lines.append(str(report))
        if report.valid:
            repo.transition_media(int(row["id"]), READY_TO_PUBLISH)
            logger.info("[VALIDATE] video=%s -> READY_TO_PUBLISH", row["external_id"])
        else:
            repo.transition_media(int(row["id"]), FAILED, error_message="; ".join(report.errors))
            logger.warning("[VALIDATE] video=%s failed: %s", row["external_id"], report.errors)

    summary = "[VALIDATE] checked=%d" % len(rows)
    return "\n".join([summary, *lines])
