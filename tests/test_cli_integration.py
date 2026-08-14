"""CLI integration tests using the full command stack."""

from __future__ import annotations

import json
import os
from pathlib import Path

from typer.testing import CliRunner

from tadabbur.cli import app

runner = CliRunner()


def _write_config(tmp_path):
    import yaml

    cfg = {
        "storage": {"base_dir": str(tmp_path / "data")},
        "sources": [],
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return str(path)


def test_cli_status_empty(tmp_path):
    cfg = _write_config(tmp_path)
    result = runner.invoke(app, ["--config", cfg, "status"])
    assert result.exit_code == 0
    assert "TOTAL: 0" in result.output


def test_cli_inspect_missing(tmp_path):
    cfg = _write_config(tmp_path)
    result = runner.invoke(app, ["--config", cfg, "inspect", "abc123"])
    assert result.exit_code == 0
    assert "not found" in result.output


def test_cli_failed_empty(tmp_path):
    cfg = _write_config(tmp_path)
    result = runner.invoke(app, ["--config", cfg, "failed"])
    assert result.exit_code == 0
    assert "count=0" in result.output


def test_cli_classify_empty(tmp_path):
    cfg = _write_config(tmp_path)
    result = runner.invoke(app, ["--config", cfg, "classify"])
    assert result.exit_code == 0
    assert "processed=0" in result.output


def test_cli_export_empty(tmp_path):
    cfg = _write_config(tmp_path)
    result = runner.invoke(app, ["--config", cfg, "export"])
    assert result.exit_code == 0
    assert "items=0" in result.output


def test_cli_retry_empty(tmp_path):
    cfg = _write_config(tmp_path)
    result = runner.invoke(app, ["--config", cfg, "retry"])
    assert result.exit_code == 0
    assert "requeued=0" in result.output


def test_cli_config_before_subcommand_uses_config_dir(tmp_path):
    """--config before the subcommand must control storage resolution."""
    import os

    cfg = _write_config(tmp_path)
    result = runner.invoke(app, ["--config", cfg, "export"])
    assert result.exit_code == 0
    # relative base_dir "data" must resolve next to the config, not the CWD
    exports = tmp_path / "data" / "exports" / "lectures.json"
    assert exports.exists()
    assert not (Path(os.getcwd()) / "data" / "exports" / "lectures.json").exists()
