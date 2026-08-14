"""Tagging subsystem."""

from tadabbur.tagging.rules import (
    CONTROLLED_TAGS,
    TagResult,
    generate_tags,
    validate_tags,
)

__all__ = [
    "CONTROLLED_TAGS",
    "TagResult",
    "generate_tags",
    "validate_tags",
]
