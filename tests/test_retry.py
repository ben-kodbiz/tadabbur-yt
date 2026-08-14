"""Stage 7: retry, backoff, circuit breaker, download manager tests."""

from __future__ import annotations

import random
import time

import pytest

from tadabbur.config import load_settings
from tadabbur.config.models import BackoffConfig, CircuitBreakerConfig
from tadabbur.database import Repository, open_database
from tadabbur.downloader import (
    CircuitBreaker,
    CircuitState,
    RetryExhaustedError,
    backoff_delay,
    retry,
)


@pytest.fixture()
def backoff_cfg():
    return BackoffConfig(base_delay=1.0, max_delay=10.0, max_attempts=3, jitter=0.0)


def test_backoff_delay_grows_exponentially():
    cfg = BackoffConfig(base_delay=10.0, max_delay=600.0, max_attempts=5, jitter=0.0)
    assert backoff_delay(1, cfg) == pytest.approx(10.0)
    assert backoff_delay(2, cfg) == pytest.approx(20.0)
    assert backoff_delay(3, cfg) == pytest.approx(40.0)


def test_backoff_caps_at_max_delay():
    cfg = BackoffConfig(base_delay=100.0, max_delay=150.0, max_attempts=5, jitter=0.0)
    assert backoff_delay(5, cfg) == pytest.approx(150.0)


def test_retry_succeeds_after_failures(backoff_cfg):
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("boom")
        return "ok"

    sleeps = []
    result = retry(flaky, backoff_cfg, sleep=sleeps.append)
    assert result == "ok"
    assert calls["n"] == 3
    assert len(sleeps) == 2


def test_retry_exhausted(backoff_cfg):
    def always_fail():
        raise ValueError("no")

    with pytest.raises(RetryExhaustedError):
        retry(always_fail, backoff_cfg, sleep=lambda _: None)


def test_retry_respects_should_retry(backoff_cfg):
    def boom():
        raise KeyError("non-retryable")

    with pytest.raises(KeyError):
        retry(
            boom,
            backoff_cfg,
            should_retry=lambda exc: isinstance(exc, ValueError),
            sleep=lambda _: None,
        )


# ---------------------------------------------------------------- circuit breaker
@pytest.fixture()
def cb_cfg():
    return CircuitBreakerConfig(
        failure_threshold=3, cooldown_seconds=60, half_open_attempts=1
    )


def test_circuit_breaker_normal(cb_cfg):
    cb = CircuitBreaker(cb_cfg)
    assert cb.allow_request() is True
    cb.record_success()
    assert cb.state is CircuitState.NORMAL


def test_circuit_breaker_trips(cb_cfg):
    cb = CircuitBreaker(cb_cfg)
    for _ in range(3):
        cb.record_failure()
    assert cb.state is CircuitState.COOLDOWN
    assert cb.is_open is True


def test_circuit_breaker_cooldown_expiry(cb_cfg):
    cb = CircuitBreaker(cb_cfg)
    cb.trip()
    cb.cooldown_until = time.monotonic() - 1  # expire immediately
    assert cb.allow_request() is True
    assert cb.state is CircuitState.HALF_OPEN


def test_circuit_breaker_half_open_failure_reopens(cb_cfg):
    cb = CircuitBreaker(cb_cfg)
    cb.state = CircuitState.HALF_OPEN
    cb.record_failure()
    assert cb.state is CircuitState.COOLDOWN


def test_circuit_breaker_half_open_success_closes(cb_cfg):
    cb = CircuitBreaker(cb_cfg)
    cb.state = CircuitState.HALF_OPEN
    cb.record_success()
    assert cb.state is CircuitState.NORMAL


def test_circuit_breaker_disabled(cb_cfg):
    cb_cfg.enabled = False
    cb = CircuitBreaker(cb_cfg)
    for _ in range(10):
        cb.record_failure()
    assert cb.allow_request() is True
