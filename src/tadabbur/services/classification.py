"""Service entry point (implemented in a later stage)."""

from tadabbur.config.models import Settings


def run_classification(settings: Settings, *args, **kwargs) -> str:
    raise NotImplementedError("tadabbur classification service not implemented yet")
