"""Single-instance protection for the pipeline worker.

Uses an advisory ``flock`` on a lock file so the OS releases the lock even
after a crash (no stale-lock cleanup needed). A second worker exits safely
instead of duplicating downloads or racing state transitions.
"""

from __future__ import annotations

from pathlib import Path

from tadabbur.logging import stage_logger

logger = stage_logger("worker-lock")

try:  # POSIX
    import fcntl  # noqa: F401

    _HAVE_FCNTL = True
except ImportError:  # pragma: no cover - non-POSIX
    _HAVE_FCNTL = False


class WorkerLock:
    """Advisory file lock ensuring at most one active worker."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._fd = None

    def acquire(self) -> bool:
        """Try to acquire the lock without blocking. True if acquired."""
        if not _HAVE_FCNTL:  # pragma: no cover - non-POSIX fallback
            logger.warning("fcntl unavailable; single-instance check skipped")
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = self.path.open("w")
        try:
            fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fd.close()
            return False
        fd.write(str(__import__("os").getpid()))
        fd.flush()
        self._fd = fd
        logger.info("[WORKER-LOCK] acquired %s", self.path)
        return True

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            import os

            fcntl.flock(self._fd.fileno(), fcntl.LOCK_UN)
        finally:
            self._fd.close()
            self._fd = None
            logger.info("[WORKER-LOCK] released %s", self.path)

    def __enter__(self) -> "WorkerLock":
        if not self.acquire():
            raise RuntimeError(f"another worker holds {self.path}")
        return self

    def __exit__(self, *exc_info) -> None:
        self.release()
