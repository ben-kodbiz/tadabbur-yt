"""Worker and graceful shutdown tests."""

from __future__ import annotations

import threading
import time

from tadabbur.config import load_settings
from tadabbur.database import Repository, open_database
from tadabbur.services.worker import _shutdown_event, run_single_pass


def test_single_pass_dry_run(tmp_path):
    settings = load_settings(config_file=tmp_path / "nope.yaml", project_dir=tmp_path)
    conn = open_database(settings.storage.database_path)
    try:
        repo = Repository(conn)
        # Should complete without errors even with no sources/network.
        run_single_pass(settings, repo, dry_run=True)
    finally:
        conn.close()


def test_shutdown_event_set_and_clear():
    _shutdown_event.clear()
    assert not _shutdown_event.is_set()
    _shutdown_event.set()
    assert _shutdown_event.is_set()
    _shutdown_event.clear()
    assert not _shutdown_event.is_set()


def test_signal_handlers_installed(tmp_path):
    import signal

    settings = load_settings(config_file=tmp_path / "nope.yaml", project_dir=tmp_path)
    from tadabbur.services.worker import install_signal_handlers

    install_signal_handlers()
    old = signal.getsignal(signal.SIGTERM)
    # installed handler is callable (not SIG_DFL)
    assert callable(old)
