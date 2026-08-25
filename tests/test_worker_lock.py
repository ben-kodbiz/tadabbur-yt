"""Stage 4: worker single-instance lock behaviour."""

from pathlib import Path

from tadabbur.services.lock import WorkerLock


def test_first_worker_acquires_lock(tmp_path: Path):
    lock = WorkerLock(tmp_path / "worker.lock")
    assert lock.acquire() is True
    lock.release()


def test_second_worker_exits_safely(tmp_path: Path):
    first = WorkerLock(tmp_path / "worker.lock")
    second = WorkerLock(tmp_path / "worker.lock")
    assert first.acquire() is True
    try:
        assert second.acquire() is False, "second worker must not acquire"
    finally:
        first.release()


def test_lock_released_after_release(tmp_path: Path):
    first = WorkerLock(tmp_path / "worker.lock")
    second = WorkerLock(tmp_path / "worker.lock")
    assert first.acquire()
    first.release()
    assert second.acquire(), "lock must be acquirable after release"
    second.release()


def test_lock_released_on_process_death(tmp_path: Path):
    """Simulate crash: file descriptor closed by OS releases the flock."""
    import os

    lock_path = tmp_path / "worker.lock"
    first = WorkerLock(lock_path)
    assert first.acquire()

    # Simulate death of the holder by closing its fd behind its back.
    os.close(first._fd.fileno())
    first._fd = None

    second = WorkerLock(lock_path)
    assert second.acquire(), "OS must release flock after holder death"
    second.release()


def test_context_manager_releases(tmp_path: Path):
    lock_path = tmp_path / "worker.lock"
    with WorkerLock(lock_path):
        pass
    assert WorkerLock(lock_path).acquire()


def test_run_worker_second_instance_exits_cleanly(tmp_path: Path, monkeypatch):
    """run_worker with an externally held lock returns safely, no exception."""
    from tadabbur.config.models import Settings, StorageConfig
    from tadabbur.services.worker import run_worker

    settings = Settings(project_dir=tmp_path, storage=StorageConfig(base_dir=tmp_path))

    holder = WorkerLock(settings.resolve_path(settings.storage.base_dir) / "worker.lock")
    assert holder.acquire()
    try:
        result = run_worker(settings, once=True)
        assert "another worker is active" in result
    finally:
        holder.release()
