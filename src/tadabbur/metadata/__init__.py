"""Metadata subsystem."""

from tadabbur.metadata.quran_ref import (
    QuranReference,
    build_quran_tags,
    extract_quran_reference,
)
from tadabbur.metadata.surahs import Surah, find_surah, get_surah_by_number
from tadabbur.metadata.preserve import MetadataResult, build_metadata, write_metadata
from tadabbur.metadata.series import SeriesInfo, series_info

__all__ = [
    "MetadataResult",
    "QuranReference",
    "SeriesInfo",
    "Surah",
    "build_metadata",
    "build_quran_tags",
    "extract_quran_reference",
    "find_surah",
    "get_surah_by_number",
    "series_info",
    "write_metadata",
]
