"""Configuration for the upload pipeline (upload_yt_pipeline.md §23, §24, §29, §34)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

VisualMode = Literal["static", "waveform"]


class AudioProfile(BaseModel):
    """Archive audio derivative profile (speech-focused)."""

    model_config = ConfigDict(extra="forbid")

    codec: Literal["opus"] = "opus"
    bitrate_kbps: int = 48
    channels: int = 1
    sample_rate: int = 48000

    @property
    def label(self) -> str:
        return f"opus-{self.bitrate_kbps}k-mono"


DEFAULT_AUDIO_PROFILES: dict[str, AudioProfile] = {
    "speech_compact": AudioProfile(bitrate_kbps=32),
    "speech_balanced": AudioProfile(bitrate_kbps=48),
    "speech_high": AudioProfile(bitrate_kbps=64),
}


class RenderProfile(BaseModel):
    """YouTube-compatible video output profile."""

    model_config = ConfigDict(extra="forbid")

    width: int = 1280
    height: int = 720
    fps: int = 24
    video_codec: Literal["libx264"] = "libx264"
    audio_codec: Literal["aac"] = "aac"
    audio_bitrate_kbps: int = 64
    visual_mode: VisualMode = "static"

    @property
    def crf(self) -> int:
        # Mostly static imagery -> CRF-based encoding is efficient.
        return 23


DEFAULT_RENDER_PROFILES: dict[str, RenderProfile] = {
    "youtube_720p_static": RenderProfile(visual_mode="static"),
    "youtube_720p_waveform": RenderProfile(visual_mode="waveform"),
}


class UploadSafetyConfig(BaseModel):
    """Hard limits preventing accidental mass uploads (§34)."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    require_manual_enable: bool = True
    max_uploads_per_run: int = Field(default=3, ge=1)
    max_uploads_per_day: int = Field(default=5, ge=1)
    dry_run_default: bool = True


class UploaderStorageConfig(BaseModel):
    """Storage policies (§29)."""

    model_config = ConfigDict(extra="forbid")

    keep_originals: bool = True
    keep_processed_audio: bool = True
    keep_youtube_mp4_after_upload: bool = True
    delete_temp_after_success: bool = True
    verify_sha256: bool = True


class RetrySchedule(BaseModel):
    """Application-level retry delays in seconds (§19)."""

    model_config = ConfigDict(extra="forbid")

    delays_seconds: list[int] = Field(default_factory=lambda: [0, 300, 1800, 7200])
    #: After exhausting the schedule the item goes to manual review.


class UploadPipelineSettings(BaseModel):
    """Top-level settings for the upload pipeline sub-system."""

    model_config = ConfigDict(extra="forbid")

    base_dir: Path = Path("data")
    database_path: Path | None = None

    default_audio_profile: str = "speech_balanced"
    default_render_profile: str = "youtube_720p_static"
    audio_profiles: dict[str, AudioProfile] = Field(
        default_factory=lambda: dict(DEFAULT_AUDIO_PROFILES)
    )
    render_profiles: dict[str, RenderProfile] = Field(
        default_factory=lambda: dict(DEFAULT_RENDER_PROFILES)
    )

    storage: UploaderStorageConfig = Field(default_factory=UploaderStorageConfig)
    upload: UploadSafetyConfig = Field(default_factory=UploadSafetyConfig)
    retry: RetrySchedule = Field(default_factory=RetrySchedule)

    def resolve_database_path(self, project_dir: Path) -> Path:
        if self.database_path is not None:
            p = self.database_path
            return p if p.is_absolute() else project_dir / p
        return project_dir / self.base_dir / "pipeline.db"

    def resolve_incoming(self, project_dir: Path) -> Path:
        return project_dir / self.base_dir / "incoming" / "originals"

    def resolve_workspace(self, project_dir: Path) -> Path:
        return project_dir / self.base_dir / "workspace"

    def resolve_archive_audio(self, project_dir: Path) -> Path:
        return project_dir / self.base_dir / "archive" / "processed_audio"

    def resolve_archive_video(self, project_dir: Path) -> Path:
        return project_dir / self.base_dir / "archive" / "uploaded"

    def get_audio_profile(self, name: str | None = None) -> AudioProfile:
        key = name or self.default_audio_profile
        if key not in self.audio_profiles:
            raise KeyError(f"unknown audio profile {key!r}")
        return self.audio_profiles[key]

    def get_render_profile(self, name: str | None = None) -> RenderProfile:
        key = name or self.default_render_profile
        if key not in self.render_profiles:
            raise KeyError(f"unknown render profile {key!r}")
        return self.render_profiles[key]
