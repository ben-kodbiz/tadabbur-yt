"""Stage 0: package / CLI smoke tests."""

from __future__ import annotations

from typer.testing import CliRunner

from tadabbur import __version__
from tadabbur.cli import app

runner = CliRunner()


def test_version_string():
    assert isinstance(__version__, str)
    assert len(__version__.split(".")) == 3


def test_cli_no_args_prints_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "discover" in result.output
    assert "classify" in result.output
    assert "worker" in result.output


def test_cli_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output
