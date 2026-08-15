"""Deterministic extraction of surah + ayah range from titles/descriptions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from tadabbur.metadata.surahs import Surah, find_surah

# "Ayat 1-10", "ayat 10-15", "Ayat 255"
_AYAT_RANGE = re.compile(
    r"ayat\s*[:,\-]?\s*(\d{1,4})\s*[-–]\s*(\d{1,4})", re.IGNORECASE
)
_AYAT_SINGLE = re.compile(r"ayat\s*[:,\-]?\s*(\d{1,4})\b", re.IGNORECASE)
# "1-10", "1 : 10" (bare range, must not be preceded by ayat already matched)
_BARE_RANGE = re.compile(r"(?<!ayat)\b(\d{1,3})\s*[-–]\s*(\d{1,3})\b", re.IGNORECASE)
# "255" as a standalone ayah number
_BARE_SINGLE = re.compile(r"(?<!ayat)\b(\d{1,3})\b")

# Words that signal we are talking about the Quran itself, required before a
# surah-only mention is treated as a reference (avoids matching person names).
_QURAN_CONTEXT = re.compile(
    r"\b(surah|surat|sura|ayat|quran|qur'an|quranic|al-quran|alquran|tafsir|"
    r"tadabbur|recitation|bacaan|ruqyah|teraweh|tarawih|tadarus|tilawah)\b",
    re.IGNORECASE,
)


@dataclass
class QuranReference:
    """Parsed Quran reference. None fields mean 'not found / uncertain'."""

    surah: Surah | None = None
    surah_number: int | None = None
    surah_name: str | None = None
    ayah_start: int | None = None
    ayah_end: int | None = None

    @property
    def has_surah(self) -> bool:
        return self.surah is not None

    @property
    def is_valid(self) -> bool:
        """Valid when we have a surah and a sane ayah range (start <= end)."""
        if not self.has_surah:
            return False
        if self.ayah_start is None and self.ayah_end is None:
            return True  # surah only is acceptable
        start = self.ayah_start or 0
        end = self.ayah_end if self.ayah_end is not None else start
        return 1 <= start <= end

    def as_dict(self) -> dict:
        return {
            "surah_number": self.surah_number,
            "surah_name": self.surah_name,
            "ayah_start": self.ayah_start,
            "ayah_end": self.ayah_end,
        }


def _strip_dates(text: str) -> str:
    """Remove date prefixes like '16-06-2026' or '(4K) 05-03-2026' that
    otherwise get misread as ayah ranges (16-6)."""
    t = re.sub(
        r"^\s*(?:\(\s*\d{1,4}\s*[kKpP]?[pP]?\s*\)\s*)?"
        r"\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\s*[:|\-]?\s*",
        "",
        text,
    )
    # Strip session markers ("Siri Ke-57", "Sesi 2", "Part 1") so the session
    # number is not misread as an ayah number.
    t = re.sub(
        r"\b(siri|sesi|episod|episode|part|jilid|bhg\.?|bahagian)\b"
        r"(?:\s+(?:ke|ke-|no\.?|no)\s*|\s*[:#]?\s*|\s*[-#]\s*)\d+\b",
        " ",
        t,
        flags=re.IGNORECASE,
    )
    return t


def extract_quran_reference(text: str | None) -> QuranReference:
    """Parse a surah/ayah reference from a title or description."""
    if not text:
        return QuranReference()

    text = _strip_dates(text)
    surah = find_surah(text)
    ref = QuranReference()

    # A surah mention alone (no ayat) is only accepted with quran context,
    # so a person named "Muhammad" or "Hud" does not create a reference.
    if surah and _QURAN_CONTEXT.search(text):
        ref.surah = surah
        ref.surah_number = surah.number
        ref.surah_name = surah.transliteration

    # Prefer explicit "Ayat X-Y" / "Ayat X"
    ayah_start = ayah_end = None
    m = _AYAT_RANGE.search(text)
    if m:
        ayah_start, ayah_end = int(m.group(1)), int(m.group(2))
    else:
        m = _AYAT_SINGLE.search(text)
        if m:
            ayah_start = ayah_end = int(m.group(1))

    # Only use a bare range/single when a surah is present, to avoid guessing.
    if ayah_start is None and surah:
        m = _BARE_RANGE.search(text)
        if m:
            ayah_start, ayah_end = int(m.group(1)), int(m.group(2))
        else:
            m = _BARE_SINGLE.search(text)
            if m:
                ayah_start = ayah_end = int(m.group(1))

    # Guard against out-of-range ayah numbers (max 286 in Al-Baqarah).
    if ayah_start is not None and surah:
        max_ayah = _max_ayah_for(surah.number)
        if ayah_start > max_ayah or (ayah_end and ayah_end > max_ayah):
            return QuranReference(surah=surah, surah_number=surah.number,
                                  surah_name=surah.transliteration)

    ref.ayah_start = ayah_start
    ref.ayah_end = ayah_end
    return ref


def _max_ayah_for(surah_number: int) -> int:
    """Approximate maximum ayah count per surah (authoritative for known long ones)."""
    known = {
        2: 286, 3: 200, 4: 176, 5: 120, 6: 165, 7: 206, 8: 75, 9: 129, 10: 109,
        11: 123, 12: 111, 13: 43, 14: 52, 15: 99, 16: 128, 17: 111, 18: 110,
        19: 98, 20: 135, 21: 112, 22: 78, 23: 118, 24: 64, 25: 77, 26: 227,
        27: 93, 28: 88, 29: 69, 30: 60, 31: 34, 32: 30, 33: 73, 34: 54, 35: 45,
        36: 83, 37: 182, 38: 88, 39: 75, 40: 85, 41: 54, 42: 53, 43: 89, 44: 59,
        45: 37, 46: 35, 47: 38, 48: 29, 49: 18, 50: 45, 51: 60, 52: 49, 53: 62,
        54: 55, 55: 78, 56: 96, 57: 29, 58: 22, 59: 24, 60: 13, 61: 14, 62: 11,
        63: 11, 64: 18, 65: 12, 66: 12, 67: 30, 68: 52, 69: 52, 70: 44, 71: 28,
        72: 28, 73: 20, 74: 56, 75: 40, 76: 31, 77: 50, 78: 40, 79: 46, 80: 42,
        81: 29, 82: 19, 83: 36, 84: 25, 85: 22, 86: 17, 87: 19, 88: 26, 89: 30,
        90: 20, 91: 15, 92: 21, 93: 11, 94: 8, 95: 8, 96: 19, 97: 5, 98: 8,
        99: 8, 100: 11, 101: 11, 102: 8, 103: 3, 104: 9, 105: 5, 106: 4, 107: 7,
        108: 3, 109: 6, 110: 3, 111: 5, 112: 4, 113: 5, 114: 6,
    }
    return known.get(surah_number, 286)


def build_quran_tags(ref: QuranReference) -> list[str]:
    """Convert a parsed reference into controlled tags (e.g. ``surah-al-kahfi``)."""
    if not ref.has_surah:
        return []
    tags = [f"surah-{ref.surah.canonical}"]
    if ref.ayah_start is not None and ref.ayah_end is not None:
        tags.append(f"ayah-{ref.ayah_start}-{ref.ayah_end}")
    elif ref.ayah_start is not None:
        tags.append(f"ayah-{ref.ayah_start}")
    return tags
