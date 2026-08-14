"""Publisher plugin interface.

Publishing is deliberately separated from ingestion. The core pipeline depends
only on this interface, never on a concrete publisher.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass
class PublishResult:
    success: bool
    external_url: str | None = None
    error: str | None = None
    detail: str | None = None


class Publisher(abc.ABC):
    """Interface every publisher must implement."""

    name: str = "base"

    @abc.abstractmethod
    def publish(self, media_row, repo) -> PublishResult:
        """Publish a single media item.

        ``media_row`` is a sqlite row for ``media``; ``repo`` gives read access
        to files/classification/tags. Must raise or return ``success=False`` on
        failure without breaking the core pipeline.
        """
        raise NotImplementedError
