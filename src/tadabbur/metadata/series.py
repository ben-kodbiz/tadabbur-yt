"""Series / session detection for organizing downloaded media.

Given a video title, determine:
- the series folder name (e.g. "Surah Al-An'am" for a multi-session series,
  or the cleaned single-video title),
- the session number (e.g. 35 for "Siri Ke-35", 1 for "Siri Pertama"),
- a clean short title for file naming.

Rule of thumb: a title containing a surah name *plus* a session marker is part
of a surah-based series -> folder named after the surah. Otherwise a title with
a session marker is part of a named series -> folder = title minus session.
Otherwise the title is a single video -> folder = the cleaned title.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from tadabbur.metadata.surahs import find_surah

# Session markers (Malay/English episode labels). Handles "Siri Ke-35",
# "Sesi 2", "Part 1", "Episod 3", "Jilid 2", "Siri Ke 12", etc.
_SESSION_RE = re.compile(
    r"\b(siri|sesi|episod|episode|part|jilid|bhg\.?|bahagian)\b"
    r"(?:\s+(?:ke|ke-|no\.?|no)\s*|\s*[:#]?\s*|\s*[-#]\s*)"
    r"(\d+)\b",
    re.IGNORECASE,
)
_SESSION_WORD_RE = re.compile(
    r"\b(siri|sesi|episod|episode|part|jilid|bahagian)\b\s*([A-Za-z]+)\b",
    re.IGNORECASE,
)

# Malay ordinal words -> number (for "Siri Pertama", "Siri Kedua", ...).
_ORDINALS = {
    "pertama": 1,
    "kedua": 2,
    "ketiga": 3,
    "keempat": 4,
    "kelima": 5,
    "keenam": 6,
    "ketujuh": 7,
    "kelapan": 8,
    "kesembilan": 9,
    "kesepuluh": 10,
    "kesebelas": 11,
    "keduabelas": 12,
}

# Prefixes stripped from the folder name (date, quality tag, ustaz intro).
_DATE_PREFIX_RE = re.compile(
    r"^\s*(?:\(\d{1,4}[kKpP]\)\s*)?\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\s*[:|\-]?\s*"
)
_QUALITY_RE = re.compile(r"^\(\s*\d{1,4}\s*[kKpP]?[pP]?\s*\)\s*")
_USTAZ_PREFIX_RE = re.compile(
    r"^(?:ustaz|ust\.?|ustz|dr\.?|dato'?|datuk|prof\.?|syeikh|sheikh|ustadz)"
    r"[^:|\u2013-]*[:|\u2013-]\s*",
    re.IGNORECASE,
)
_TRAIL_SEP_RE = re.compile(r"[\s:|\u2013-]+$")


@dataclass
class SeriesInfo:
    """Deterministic series/session info for one video title."""

    folder: str            # folder name under <ustaz>/
    session_number: int | None  # 1-based within series, or None for single
    session_label: str | None   # e.g. "Siri Ke-35" (for the filename), or None
    short_title: str       # cleaned title without date/ustaz/session markers
    is_series: bool


def _normalize(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    no_diacritics = "".join(c for c in nfkd if not unicodedata.combining(c))
    return no_diacritics


def _clean_title(title: str) -> str:
    t = _normalize(title or "")
    t = _DATE_PREFIX_RE.sub("", t)
    t = _QUALITY_RE.sub("", t)
    t = _USTAZ_PREFIX_RE.sub("", t)
    t = _TRAIL_SEP_RE.sub("", t).strip()
    return t


def _extract_session(title: str) -> tuple[int | None, str | None]:
    """Return (number, label) for a session marker, or (None, None)."""
    m = _SESSION_RE.search(title)
    if m:
        return int(m.group(2)), m.group(0).strip()
    m = _SESSION_WORD_RE.search(title)
    if m:
        word = m.group(2).lower()
        if word in _ORDINALS:
            return _ORDINALS[word], m.group(0).strip()
    return None, None


def _strip_session(title: str) -> str:
    """Remove the session marker + number from a title."""
    t = re.sub(
        r"\b(siri|sesi|episod|episode|part|jilid|bhg\.?|bahagian)\b"
        r"(?:\s+(?:ke|ke-|no\.?|no)\s*|\s*[:#]?\s*|\s*[-#]\s*)\d+\b",
        " ",
        title,
        flags=re.IGNORECASE,
    )
    t = _SESSION_WORD_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return _TRAIL_SEP_RE.sub("", t).strip()


def series_info(title: str) -> SeriesInfo:
    """Compute series folder + session info for a video title."""
    cleaned = _clean_title(title)
    if not cleaned:
        cleaned = title or "untitled"

    number, label = _extract_session(title)
    is_series = number is not None

    base = _strip_session(cleaned)
    base = re.sub(r"\s+", " ", base).strip(" :|\u2013-") or cleaned

    if is_series:
        surah = find_surah(base)
        if surah is not None:
            # surah-based series: folder named after the surah
            folder = f"Surah {surah.transliteration}"
        else:
            folder = base
    else:
        # single video: folder = cleaned title
        folder = cleaned

    short = base if is_series else cleaned
    return SeriesInfo(
        folder=folder,
        session_number=number,
        session_label=label,
        short_title=short,
        is_series=is_series,
    )
