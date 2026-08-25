"""Circuit breaker for network/platform failure protection.

Prevents the application from hammering a failing service. States:
NORMAL -> COOLDOWN -> HALF_OPEN -> (NORMAL | COOLDOWN).

When a repository is provided the state is persisted in SQLite so cooldown
survives process restarts; otherwise behaviour is in-memory only.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from tadabbur.config.models import CircuitBreakerConfig

BREAKER_NAME = "download"


class CircuitState(str, Enum):
    NORMAL = "normal"
    COOLDOWN = "cooldown"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    """Circuit breaker with optional SQLite persistence.

    Cooldown uses wall-clock time so a persisted ``cooldown_until`` remains
    meaningful across restarts.
    """

    config: CircuitBreakerConfig
    repository: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.state = CircuitState.NORMAL
        self.failures = 0
        self.cooldown_until: float | None = None
        self.half_open_attempts_used = 0
        if self.repository is not None:
            self._load()

    # ------------------------------------------------------------ persistence
    def _load(self) -> None:
        saved = self.repository.load_circuit_state(BREAKER_NAME)
        if not saved:
            return
        try:
            self.state = CircuitState(saved["state"])
        except ValueError:
            self.state = CircuitState.NORMAL
        self.failures = int(saved["failure_count"] or 0)
        self.cooldown_until = saved["cooldown_until"]
        if (
            self.state is CircuitState.COOLDOWN
            and self.cooldown_until is not None
            and time.time() >= self.cooldown_until
        ):
            # Cooldown expired while we were away -> recovery path.
            self.state = CircuitState.HALF_OPEN
            self.half_open_attempts_used = 0

    def _persist(self) -> None:
        if self.repository is None:
            return
        self.repository.save_circuit_state(
            BREAKER_NAME,
            self.state.value,
            self.failures,
            self.cooldown_until,
        )

    # ------------------------------------------------------------- decisions
    def allow_request(self) -> bool:
        """Whether a new request should be attempted right now."""
        if self.config.enabled is False:
            return True
        if self.state is CircuitState.COOLDOWN:
            if self.cooldown_until is not None and time.time() >= self.cooldown_until:
                self.state = CircuitState.HALF_OPEN
                self.half_open_attempts_used = 0
                self._persist()
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
        self._persist()

    def record_failure(self) -> None:
        """Register a failure; trip the breaker when the threshold is reached."""
        if self.config.enabled is False:
            return
        self.failures += 1
        if self.state is CircuitState.HALF_OPEN:
            self.half_open_attempts_used += 1
        if self.failures >= self.config.failure_threshold or self.state is CircuitState.HALF_OPEN:
            self.trip()
        else:
            self._persist()

    def trip(self) -> None:
        self.state = CircuitState.COOLDOWN
        self.cooldown_until = time.time() + self.config.cooldown_seconds
        self.half_open_attempts_used = 0
        self._persist()

    @property
    def is_open(self) -> bool:
        return self.state is CircuitState.COOLDOWN
