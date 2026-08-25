"""Stage 5: circuit breaker state persists across restarts."""

from pathlib import Path

from tadabbur.config.models import CircuitBreakerConfig
from tadabbur.database import Repository, open_database
from tadabbur.downloader.circuit_breaker import CircuitBreaker, CircuitState


def _repo(tmp_path: Path) -> Repository:
    return Repository(open_database(tmp_path / "db.sqlite"))


def test_state_survives_repository_reopen(tmp_path: Path):
    repo = _repo(tmp_path)
    cfg = CircuitBreakerConfig(failure_threshold=2, cooldown_seconds=900)

    breaker = CircuitBreaker(cfg, repository=repo)
    breaker.record_failure()
    breaker.record_failure()  # trips (threshold=2)
    assert breaker.state is CircuitState.COOLDOWN

    # Simulate restart: fresh breaker, same DB.
    reloaded = CircuitBreaker(cfg, repository=_repo(tmp_path))
    assert reloaded.state is CircuitState.COOLDOWN
    assert not reloaded.allow_request(), "cooldown must block immediately after restart"


def test_expired_cooldown_enters_recovery_after_restart(tmp_path: Path):
    repo = _repo(tmp_path)
    cfg = CircuitBreakerConfig(failure_threshold=1, cooldown_seconds=1)

    breaker = CircuitBreaker(cfg, repository=repo)
    breaker.record_failure()  # trips

    import time
    time.sleep(1.05)  # let the 1s cooldown expire

    # Restart after cooldown has expired.
    reloaded = CircuitBreaker(CircuitBreakerConfig(failure_threshold=1), repository=_repo(tmp_path))
    assert reloaded.state is CircuitState.HALF_OPEN
    assert reloaded.allow_request()


def test_success_closes_circuit_and_persists(tmp_path: Path):
    cfg = CircuitBreakerConfig(failure_threshold=1, cooldown_seconds=1)
    repo = _repo(tmp_path)

    breaker = CircuitBreaker(cfg, repository=repo)
    breaker.record_failure()
    import time
    time.sleep(1.05)  # expire the 1s cooldown
    assert breaker.allow_request()  # half-open test request
    breaker.record_success()

    reloaded = CircuitBreaker(cfg, repository=_repo(tmp_path))
    assert reloaded.state is CircuitState.NORMAL
    assert reloaded.failures == 0


def test_in_memory_breaker_unchanged():
    """Without a repository the breaker stays in-memory (backward compat)."""
    breaker = CircuitBreaker(CircuitBreakerConfig(failure_threshold=1))
    breaker.record_failure()
    assert breaker.is_open
    # nothing persisted anywhere; no exception raised


def test_migration_from_v2_database(tmp_path: Path):
    """A fresh database is migrated to the current schema with new tables."""
    conn = open_database(tmp_path / "db.sqlite")
    version = conn.execute("SELECT version FROM schema_version").fetchone()["version"]
    assert version >= 3
    conn.execute("SELECT * FROM circuit_state")  # table exists
