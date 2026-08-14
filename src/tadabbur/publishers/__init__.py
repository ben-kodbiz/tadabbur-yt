"""Publishers subsystem."""

from tadabbur.publishers.base import PublishResult, Publisher
from tadabbur.publishers.filesystem import FilesystemPublisher
from tadabbur.publishers.internet_archive import InternetArchivePublisher

__all__ = [
    "FilesystemPublisher",
    "InternetArchivePublisher",
    "PublishResult",
    "Publisher",
]
