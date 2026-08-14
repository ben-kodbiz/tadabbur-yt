"""Bounded retry with exponential backoff and jitter.

Conservative failure handling per the architecture: never retry indefinitely,
and always delay between attempts to avoid hammering the source service.
"""

from __future__ import annotations

import random
import time
from typing import Any, Callable

from tadabbur.config.models import BackoffConfig


def backoff_delay(
    attempt: int,
    config: BackoffConfig,
    *,
    rng: random.Random | None = None,
) -> float:
    """Compute the delay (seconds) before retry number ``attempt`` (1-based).

    delay = min(max_delay, base_delay * multiplier^(attempt-1)) +/- jitter
    """
    rng = rng or random
    raw = config.base_delay * (config.multiplier ** (attempt - 1))
    raw = min(raw, config.max_delay)
    jitter_amt = raw * config.jitter
    return max(0.0, raw + rng.uniform(-jitter_amt, jitter_amt))


class RetryExhaustedError(Exception):
    """Raised when all attempts have been consumed."""


def retry(
    fn: Callable[[], Any],
    config: BackoffConfig,
    *,
    should_retry: Callable[[Exception], bool] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    rng: random.Random | None = None,
) -> Any:
    """Call ``fn`` with bounded retries and exponential backoff + jitter.

    ``should_retry`` decides whether a raised exception is retryable
    (default: retry everything).
    """
    attempt = 0
    last_error: Exception | None = None

    while attempt < config.max_attempts:
        attempt += 1
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if should_retry is not None and not should_retry(exc):
                raise
            if attempt >= config.max_attempts:
                break
            delay = backoff_delay(attempt, config, rng=rng)
            sleep(delay)

    raise RetryExhaustedError(f"exhausted {config.max_attempts} attempts") from last_error
