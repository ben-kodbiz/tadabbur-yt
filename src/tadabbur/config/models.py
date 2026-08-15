"""Configuration data models for the Tadabbur pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RightsStatus = Literal[
    "unknown",
    "open_license",
    "permission_obtained",
    "source_permitted",
    "restricted",
    "do_not_publish",
]


class SourceRules(BaseModel):
    """Classification rules applied to a single source."""

    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)


class Source(BaseModel):
    """A configured content source (e.g. a YouTube channel)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1)
    platform: Literal["youtube"] = "youtube"
    channel_url: str
    channel_id: str | None = None
    enabled: bool = True
    language: str = "ms"
    rules: SourceRules = Field(default_factory=SourceRules)
    rights_status: RightsStatus = "unknown"
    download_policy: bool = True
    publication_policy: bool = False

    @field_validator("channel_url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("channel_url must be an absolute http(s) URL")
        return v


class DownloadConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: str = "bestvideo+bestaudio/best"
    merge_output_format: str = "mp4"
    audio_format: str = "m4a"
    audio_quality: int = 5
    write_subs: bool = False
    write_auto_subs: bool = False
    sub_langs: str = "en.*"
    keep_video: bool = True
    max_filesize_mb: int | None = None
    retries: int = 3
    fragment_retries: int = 3
    concurrent_fragments: int = 4
    timeout: int = 30
    socket_timeout: int = 30
    limit_rate: str | None = None
    audio_only: bool = False


class ProxyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    url: str = ""
    health_check: bool = True
    health_check_timeout: int = 10

    @model_validator(mode="after")
    def _validate_proxy(self) -> "ProxyConfig":
        if self.enabled and not self.url:
            raise ValueError("proxy.enabled requires proxy.url")
        if self.url and not self.url.startswith(("http://", "https://", "socks5://", "socks5h://")):
            raise ValueError("proxy.url has an unsupported scheme")
        return self


class BackoffConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_delay: float = 10.0
    max_delay: float = 600.0
    max_attempts: int = 5
    jitter: float = 0.1
    multiplier: float = 2.0

    @field_validator("base_delay", "max_delay", "jitter", "multiplier")
    @classmethod
    def _non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("must be >= 0")
        return v

    @field_validator("max_attempts")
    @classmethod
    def _positive_attempts(cls, v: int) -> int:
        if v < 1:
            raise ValueError("max_attempts must be >= 1")
        return v

    @model_validator(mode="after")
    def _order(self) -> "BackoffConfig":
        if self.base_delay > self.max_delay:
            raise ValueError("base_delay must be <= max_delay")
        return self


class CircuitBreakerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    failure_threshold: int = 5
    cooldown_seconds: int = 900
    half_open_attempts: int = 1

    @field_validator("failure_threshold", "cooldown_seconds", "half_open_attempts")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("must be >= 1")
        return v


class ClassificationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_category: str = "other"
    confidence_threshold: float = 0.6
    qwen_enabled: bool = False
    qwen_model: str = "Qwen/Qwen2.5-3B-Instruct"
    qwen_conf_threshold: float = 0.7
    manual_review_on_low_confidence: bool = True


class StorageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_dir: Path = Field(default_factory=lambda: Path("data"))
    media_dir: Path | None = None
    database_dir: Path | None = None
    exports_dir: Path | None = None

    @property
    def resolved_media_dir(self) -> Path:
        return self.media_dir or (self.base_dir / "media")

    @property
    def resolved_database_dir(self) -> Path:
        return self.database_dir or (self.base_dir / "database")

    @property
    def resolved_exports_dir(self) -> Path:
        return self.exports_dir or (self.base_dir / "exports")

    @property
    def database_path(self) -> Path:
        return self.resolved_database_dir / "tadabbur.sqlite"


class ArchiveConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    archive_file: Path | None = None
    keep_source_video: bool = True
    keep_subtitles: bool = True
    keep_thumbnail: bool = True


class SchedulerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    discovery_time: str = "07:00"
    worker_interval_minutes: int = 60
    dry_run: bool = False


class Settings(BaseModel):
    """Top-level application settings loaded from YAML + env overrides."""

    model_config = ConfigDict(extra="forbid")

    project_dir: Path = Field(default_factory=Path.cwd)
    log_level: str = "INFO"
    sources: list[Source] = Field(default_factory=list)
    download: DownloadConfig = Field(default_factory=DownloadConfig)
    proxy: ProxyConfig = Field(default_factory=ProxyConfig)
    backoff: BackoffConfig = Field(default_factory=BackoffConfig)
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    classification: ClassificationConfig = Field(default_factory=ClassificationConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    archive: ArchiveConfig = Field(default_factory=ArchiveConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)

    @property
    def enabled_sources(self) -> list[Source]:
        return [s for s in self.sources if s.enabled]

    def resolve_path(self, p: Path) -> Path:
        if p.is_absolute():
            return p
        return self.project_dir / p
