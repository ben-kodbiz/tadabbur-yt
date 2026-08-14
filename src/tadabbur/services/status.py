"""Service entry point (implemented in a later stage)."""

from tadabbur.config.models import Settings


def run_status(settings: Settings, *args, **kwargs) -> str:
    raise NotImplementedError("tadabbur status service not implemented yet")
