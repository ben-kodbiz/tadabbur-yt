"""Shared placeholder for service modules implemented in later stages."""

from tadabbur.config.models import Settings


def _not_implemented(stage: str, settings: Settings) -> str:
    """Return a consistent message when a stage is not yet implemented."""
    return f"[{stage}] not implemented yet (Tadabbur pipeline stage not built)"
