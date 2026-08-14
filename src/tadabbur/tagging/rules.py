"""Deterministic tagging with a controlled vocabulary.

Tags are generated from rules only in this stage. Model-generated tags must be
validated against this vocabulary before entering the database.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from tadabbur.metadata.quran_ref import extract_quran_reference

# Controlled tag vocabulary (canonical tags).
CONTROLLED_TAGS = frozenset(
    {
        "quran",
        "tadabbur",
        "tafsir",
        "sabar",
        "syukur",
        "taqwa",
        "iman",
        "akhirat",
        "doa",
        "akhlak",
        "keluarga",
        "tazkirah",
        "malam-jumaat",
        "remaja",
        "wanita",
        "bicara",
    }
)

# Topic keywords mapped to canonical controlled tags.
_TOPIC_KEYWORDS = {
    "sabar": ("sabar", "kesabaran", "bersabar", "sabran"),
    "syukur": ("syukur", "bersyukur", "gratitude"),
    "taqwa": ("taqwa", "ketakwaan", "takwa"),
    "iman": ("iman", "keimanan", "aqidah", "kufur"),
    "akhirat": ("akhirat", "kematian", "qiamat", "kiamat", "syurga", "neraka", "hisab"),
    "doa": ("doa", "berdoa", "dua"),
    "akhlak": ("akhlak", "adab", "etika", "moral"),
    "keluarga": ("keluarga", "rumah tangga", "suami", "isteri", "anak", "ibubapa", "ibu bapa"),
    "malam-jumaat": ("malam jumaat", "malam jumuah", "malam jumaat"),
    "remaja": ("remaja", "belia", "youth"),
    "wanita": ("wanita", "muslimah", "perempuan"),
}


@dataclass
class TagResult:
    tags: list[str] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)  # tag -> source

    def __str__(self) -> str:
        return f"[TAG] tags={','.join(self.tags) or '(none)'}"


def _normalize(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    no_diacritics = "".join(c for c in nfkd if not unicodedata.combining(c))
    return no_diacritics.lower()


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def generate_tags(*, title: str, category: str, source_id: str | None = None) -> list[str]:
    """Generate deterministic tags from rules."""
    tags: list[str] = []
    blob = _normalize(f"{title} {category}")

    if category in {"tadabbur", "tafsir", "quran"}:
        tags.append("quran")
    if category == "tadabbur":
        tags.append("tadabbur")
    elif category == "tafsir":
        tags.append("tafsir")

    ref = extract_quran_reference(title)
    if ref.has_surah:
        tags.append(f"surah-{ref.surah.canonical}")
        if ref.ayah_start is not None and ref.ayah_end is not None:
            tags.append(f"ayah-{ref.ayah_start}-{ref.ayah_end}")

    for tag, keywords in _TOPIC_KEYWORDS.items():
        if any(k in blob for k in keywords):
            tags.append(tag)

    if source_id:
        tags.append(f"source-{_slugify(source_id)}")

    # Deduplicate while preserving order.
    seen: set[str] = set()
    ordered: list[str] = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            ordered.append(t)
    return ordered


def validate_tags(candidates: list[str]) -> tuple[list[str], list[str]]:
    """Filter candidate tags against the controlled vocabulary.

    Returns ``(valid, rejected)``. Tags in the controlled set pass; tags that
    match the structured patterns (``surah-*``, ``ayah-*``, ``source-*``,
    ``language-*``) also pass since they are deterministically generated.
    """
    valid: list[str] = []
    rejected: list[str] = []
    structured = re.compile(
        r"^(surah-[a-z0-9-]+|ayah-[0-9]+(-[0-9]+)?|source-[a-z0-9-]+|language-[a-z0-9-]+)$"
    )
    for tag in candidates:
        t = tag.strip().lower()
        if t in CONTROLLED_TAGS or structured.match(t):
            valid.append(t)
        else:
            rejected.append(t)
    return valid, rejected
