"""Stage 0: configuration loading tests."""

from __future__ import annotations

import textwrap

import pytest

from tadabbur.config import ConfigError, load_settings
from tadabbur.config.models import Settings

SAMPLE_CONFIG = textwrap.dedent(
    """\
    log_level: INFO
    sources:
      - id: ustaz_example
        name: "Ustaz Example"
        platform: youtube
        channel_url: "https://www.youtube.com/@ustaz-example"
        enabled: true
        rules:
          include: [tadabbur, tafsir]
          exclude: [shorts]
    download:
      audio_format: m4a
    proxy:
      enabled: true
      url: "http://proxy.example:8080"
    """
)


@pytest.fixture()
def config_file(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(SAMPLE_CONFIG, encoding="utf-8")
    return path


def test_default_settings_apply_defaults(tmp_path):
    settings = load_settings(config_file=tmp_path / "missing.yaml", project_dir=tmp_path)
    assert isinstance(settings, Settings)
    assert settings.sources == []
    assert settings.download.audio_format == "m4a"
    assert settings.classification.default_category == "other"
    assert settings.storage.database_path.name == "tadabbur.sqlite"


def test_load_yaml_config(config_file, tmp_path):
    settings = load_settings(config_file=config_file, project_dir=tmp_path)
    assert len(settings.sources) == 1
    source = settings.sources[0]
    assert source.id == "ustaz_example"
    assert source.name == "Ustaz Example"
    assert source.enabled is True
    assert source.rules.include == ["tadabbur", "tafsir"]
    assert source.rules.exclude == ["shorts"]
    assert settings.proxy.enabled is True
    assert settings.proxy.url == "http://proxy.example:8080"


def test_enabled_sources_filters_disabled(config_file, tmp_path):
    settings = load_settings(config_file=config_file, project_dir=tmp_path)
    assert [s.id for s in settings.enabled_sources] == ["ustaz_example"]


def test_env_overrides(config_file, tmp_path):
    env = {
        "TADABBUR_LOG_LEVEL": "DEBUG",
        "TADABBUR_PROXY_ENABLED": "false",
        "TADABBUR_SCHEDULER_DRY_RUN": "true",
    }
    settings = load_settings(config_file=config_file, project_dir=tmp_path, env=env)
    assert settings.log_level == "DEBUG"
    assert settings.proxy.enabled is False
    assert settings.scheduler.dry_run is True


def test_proxy_enabled_requires_url(tmp_path):
    bad = textwrap.dedent(
        """\
        proxy:
          enabled: true
          url: ""
        """
    )
    path = tmp_path / "bad.yaml"
    path.write_text(bad, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(config_file=path, project_dir=tmp_path)


def test_invalid_yaml_raises_config_error(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("sources: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(config_file=path, project_dir=tmp_path)
