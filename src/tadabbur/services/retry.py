"""Service entry point (implemented in a later stage)."""

from tadabbur.config.models import Settings


def run_retry(settings: Settings, *args, **kwargs) -> str:
    raise NotImplementedError("tadabbur retry service not implemented yet")
