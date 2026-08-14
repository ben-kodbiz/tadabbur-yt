"""Service entry point (implemented in a later stage)."""

from tadabbur.config.models import Settings


def run_pipeline(settings: Settings, *args, **kwargs) -> str:
    raise NotImplementedError("tadabbur pipeline service not implemented yet")
