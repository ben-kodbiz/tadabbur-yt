"""Circuit breaker for network/platform failure protection.

Prevents the application from hammering a failing service. States:
NORMAL -> COOLDOWN -> HALF_OPEN -> (NORMAL | COOLDOWN).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum

from tadabbur.config.models import CircuitBreakerConfig


class CircuitState(str, Enum):
    NORMAL = "normal"
    COOLDOWN = "cooldown"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    """Stateful circuit breaker persisted in memory for the process lifetime."""

    config: CircuitBreakerConfig

    def __post_init__(self) -> None:
        self.state = CircuitState.NORMAL
        self.failures = 0
        self.cooldown_until: float | None = None
        self.half_open_attempts_used = 0

    def allow_request(self) -> bool:
        """Whether a new request should be attempted right now."""
        if self.config.enabled is False:
            return True
        if self.state is CircuitState.COOLDOWN:
            if self.cooldown_until is not None and time.monotonic() >= self.cooldown_until:
                self.state = CircuitState.HALF_OPEN
                self.half_open_attempts_used = 0
                return True
            return False
        if self.state is CircuitState.HALF_OPEN:
            return self.half_open_attempts_used < self.config.half_open_attempts
        return True

    def record_success(self) -> None:
        """Reset failures after a successful call."""
        if self.config.enabled is False:
            return
        self.failures = 0
        if self.state in {CircuitState.HALF_OPEN, CircuitState.COOLDOWN}:
            self.state = CircuitState.NORMAL
            self.cooldown_until = None
        self.half_open_attempts_used = 0

    def record_failure(self) -> None:
        """Register a failure; trip the breaker when the threshold is reached."""
        if self.config.enabled is False:
            return
        self.failures += 1
        if self.state is CircuitState.HALF_OPEN:
            self.half_open_attempts_used += 1
        if self.failures >= self.config.failure_threshold or self.state is CircuitState.HALF_OPEN:
            self.trip()

    def trip(self) -> None:
        self.state = CircuitState.COOLDOWN
        self.cooldown_until = time.monotonic() + self.config.cooldown_seconds
        self.half_open_attempts_used = 0

    @property
    def is_open(self) -> bool:
        return self.state is CircuitState.COOLDOWN
