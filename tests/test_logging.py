"""Stage 0: logging tests."""

from __future__ import annotations

import logging

from tadabbur.logging import redact, setup_logging, tag


def test_redact_url_credentials():
    assert redact("http://user:pass@host/path") == "http://***:***@host/path"


def test_redact_password_key():
    assert "secret" not in redact("password=supersecret")


def test_tag_stage_prefix():
    assert tag("DOWNLOAD", "done") == "[DOWNLOAD] done"


def test_setup_logging_writes_file(tmp_path):
    logger = setup_logging(log_dir=tmp_path, console=False, file=True)
    assert logger.level == logging.INFO
    logger.info("hello")
    log_file = tmp_path / "tadabbur.log"
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "hello" in content
