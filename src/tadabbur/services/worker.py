"""Service entry point (implemented in a later stage)."""

from tadabbur.config.models import Settings


def run_worker(settings: Settings, *args, **kwargs) -> str:
    raise NotImplementedError("tadabbur worker service not implemented yet")
