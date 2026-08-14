"""Service entry point (implemented in a later stage)."""

from tadabbur.config.models import Settings


def run_download(settings: Settings, *args, **kwargs) -> str:
    raise NotImplementedError("tadabbur download service not implemented yet")
