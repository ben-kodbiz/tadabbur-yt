"""Media state machine: validates and records persisted transitions."""

from __future__ import annotations

from tadabbur.status import (
    AUDIO_PROCESSING,
    CLASSIFIED,
    DISCOVERED,
    DOWNLOADED,
    DOWNLOADING,
    FAILED,
    MANUAL_REVIEW,
    PROCESSED,
    PUBLISHED,
    QUEUED,
    READY_TO_PUBLISH,
    REJECTED,
    TAGGED,
    VALIDATED,
)

# Valid transitions per state. Transitions not listed here are forbidden.
_TRANSITIONS: dict[str, frozenset[str]] = {
    DISCOVERED: frozenset({CLASSIFIED, QUEUED, REJECTED, FAILED, MANUAL_REVIEW}),
    CLASSIFIED: frozenset({QUEUED, REJECTED, FAILED, MANUAL_REVIEW}),
    QUEUED: frozenset({DOWNLOADING, FAILED, REJECTED, MANUAL_REVIEW}),
    DOWNLOADING: frozenset({DOWNLOADED, FAILED, AUDIO_PROCESSING}),
    DOWNLOADED: frozenset({AUDIO_PROCESSING, FAILED, PROCESSED}),
    AUDIO_PROCESSING: frozenset({PROCESSED, FAILED, DOWNLOADED}),
    PROCESSED: frozenset({TAGGED, FAILED}),
    TAGGED: frozenset({VALIDATED, FAILED}),
    VALIDATED: frozenset({READY_TO_PUBLISH, FAILED, TAGGED}),
    READY_TO_PUBLISH: frozenset({PUBLISHED, FAILED}),
    REJECTED: frozenset({CLASSIFIED, QUEUED}),
    MANUAL_REVIEW: frozenset({CLASSIFIED, QUEUED, REJECTED}),
    FAILED: frozenset({QUEUED, DISCOVERED, DOWNLOADING, AUDIO_PROCESSING}),
    PUBLISHED: frozenset(),
}


class InvalidTransitionError(Exception):
    """Raised when a media state transition is not allowed."""


def is_valid_transition(current: str, target: str) -> bool:
    """Check whether ``current -> target`` is a permitted transition."""
    allowed = _TRANSITIONS.get(current)
    if allowed is None:
        return False
    return target in allowed


def assert_transition(current: str, target: str) -> None:
    """Raise :class:`InvalidTransitionError` when the transition is invalid."""
    if not is_valid_transition(current, target):
        raise InvalidTransitionError(
            f"invalid transition: {current} -> {target}"
        )


def describe() -> dict[str, list[str]]:
    return {k: sorted(v) for k, v in _TRANSITIONS.items()}
