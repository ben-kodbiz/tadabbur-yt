"""Configuration loading with YAML file + environment variable support."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from tadabbur.config.models import Settings
from tadabbur.logging import stage_logger

logger = stage_logger("config")

ENV_PREFIX = "TADABBUR_"
DEFAULT_CONFIG_NAME = "config.yaml"
CONFIG_DIR_NAME = "config"


class ConfigError(Exception):
    """Raised when configuration cannot be loaded."""


def _find_project_dir() -> Path:
    """Locate the project root by walking up to find ``config/`` or ``pyproject.toml``."""
    candidates = ["pyproject.toml", CONFIG_DIR_NAME, "src/tadabbur"]
    cwd = Path.cwd()
    for parent in (cwd, *cwd.parents):
        if any((parent / c).exists() for c in candidates):
            return parent
    return cwd


def load_settings(
    config_file: Path | str | None = None,
    *,
    project_dir: Path | str | None = None,
    env: dict[str, str] | None = None,
) -> Settings:
    """Load settings from a YAML file merged with environment overrides.

    Resolution order (lowest to highest priority):
    1. Defaults from the data models.
    2. YAML file (``config/config.yaml`` by default).
    3. ``TADABBUR_*`` environment variables.

    ``TADABBUR_CONFIG`` overrides the default config file path.
    """
    env = dict(os.environ) if env is None else dict(env)
    base = Path(project_dir) if project_dir else _find_project_dir()

    config_path = config_file
    if config_path is None:
        config_path = env.get(f"{ENV_PREFIX}CONFIG")
    if config_path is None:
        config_path = base / CONFIG_DIR_NAME / DEFAULT_CONFIG_NAME
    config_path = Path(config_path)

    # When an explicit config file is supplied, treat its directory as the
    # project root so relative storage/log paths stay next to the config.
    if project_dir is None and config_file is not None:
        base = config_path.resolve().parent

    data: dict[str, Any] = {}
    if config_path.exists():
        data = _read_yaml(config_path)
    else:
        logger.debug("Config file not found, using defaults: %s", config_path)

    _apply_env_overrides(data, env)

    try:
        settings = Settings.model_validate(data)
    except ValidationError as exc:  # pragma: no cover - exercised via tests
        raise ConfigError(f"Invalid configuration: {exc}") from exc

    settings.project_dir = base
    return settings


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Cannot parse config file {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"Config file {path} must contain a mapping at top level")
    return data


def _apply_env_overrides(data: dict[str, Any], env: dict[str, str]) -> None:
    """Apply ``TADABBUR_*`` env vars onto the raw config dict.

    Supported variables:

    - ``TADABBUR_LOG_LEVEL``
    - ``TADABBUR_PROXY_URL`` / ``TADABBUR_PROXY_ENABLED``
    - ``TADABBUR_BASE_DIR``
    - ``TADABBUR_ARCHIVE_FILE``
    - ``TADABBUR_SCHEDULER_ENABLED``
    - ``TADABBUR_SCHEDULER_DRY_RUN``
    """
    if val := env.get(f"{ENV_PREFIX}LOG_LEVEL"):
        data["log_level"] = val
    if val := env.get(f"{ENV_PREFIX}PROXY_ENABLED"):
        data.setdefault("proxy", {})["enabled"] = _as_bool(val)
    if val := env.get(f"{ENV_PREFIX}PROXY_URL"):
        data.setdefault("proxy", {})["url"] = val
    if val := env.get(f"{ENV_PREFIX}BASE_DIR"):
        data.setdefault("storage", {})["base_dir"] = val
    if val := env.get(f"{ENV_PREFIX}ARCHIVE_FILE"):
        data.setdefault("archive", {})["archive_file"] = val
    if val := env.get(f"{ENV_PREFIX}SCHEDULER_ENABLED"):
        data.setdefault("scheduler", {})["enabled"] = _as_bool(val)
    if val := env.get(f"{ENV_PREFIX}SCHEDULER_DRY_RUN"):
        data.setdefault("scheduler", {})["dry_run"] = _as_bool(val)


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


__all__ = ["ConfigError", "load_settings"]
