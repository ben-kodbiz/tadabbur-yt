"""Stage 6: state machine tests."""

from __future__ import annotations

import pytest

from tadabbur.jobs.state_machine import (
    InvalidTransitionError,
    assert_transition,
    describe,
    is_valid_transition,
)
from tadabbur.status import (
    AUDIO_PROCESSING,
    DISCOVERED,
    DOWNLOADED,
    DOWNLOADING,
    FAILED,
    PROCESSED,
    QUEUED,
    READY_TO_PUBLISH,
    TAGGED,
    VALIDATED,
)


def test_valid_transitions():
    assert is_valid_transition(DISCOVERED, QUEUED)
    assert is_valid_transition(QUEUED, DOWNLOADING)
    assert is_valid_transition(DOWNLOADING, DOWNLOADED)
    assert is_valid_transition(DOWNLOADED, AUDIO_PROCESSING)
    assert is_valid_transition(AUDIO_PROCESSING, PROCESSED)
    assert is_valid_transition(PROCESSED, TAGGED)
    assert is_valid_transition(TAGGED, VALIDATED)
    assert is_valid_transition(VALIDATED, READY_TO_PUBLISH)


def test_invalid_transitions():
    assert not is_valid_transition(QUEUED, DISCOVERED)
    assert not is_valid_transition(DISCOVERED, PROCESSED)
    assert not is_valid_transition(PROCESSED, DISCOVERED)


def test_failure_transitions():
    assert is_valid_transition(DOWNLOADING, FAILED)
    assert is_valid_transition(AUDIO_PROCESSING, FAILED)
    assert is_valid_transition(DOWNLOADED, FAILED)


def test_assert_transition_raises():
    with pytest.raises(InvalidTransitionError):
        assert_transition(QUEUED, DISCOVERED)
    assert_transition(DISCOVERED, QUEUED)  # does not raise


def test_describe_covers_all_states():
    trans = describe()
    assert set(trans.keys()) == {
        "DISCOVERED", "CLASSIFIED", "REJECTED", "QUEUED", "DOWNLOADING",
        "DOWNLOADED", "AUDIO_PROCESSING", "PROCESSED", "TAGGED", "VALIDATED",
        "READY_TO_PUBLISH", "PUBLISHED", "FAILED", "MANUAL_REVIEW",
    }
    assert DOWNLOADING in trans["QUEUED"]
