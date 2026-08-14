"""Service entry point (implemented in a later stage)."""

from tadabbur.config.models import Settings


def run_discovery(settings: Settings, *args, **kwargs) -> str:
    raise NotImplementedError("tadabbur discovery service not implemented yet")
