"""Service entry point (implemented in a later stage)."""

from tadabbur.config.models import Settings


def run_validation(settings: Settings, *args, **kwargs) -> str:
    raise NotImplementedError("tadabbur validation service not implemented yet")
