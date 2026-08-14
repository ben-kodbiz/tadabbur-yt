"""Metadata subsystem."""

from tadabbur.metadata.quran_ref import (
    QuranReference,
    build_quran_tags,
    extract_quran_reference,
)
from tadabbur.metadata.surahs import Surah, find_surah, get_surah_by_number

__all__ = [
    "QuranReference",
    "Surah",
    "build_quran_tags",
    "extract_quran_reference",
    "find_surah",
    "get_surah_by_number",
]
