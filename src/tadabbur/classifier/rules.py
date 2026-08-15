"""Deterministic Tadabbur classifier (rules first, no LLM).

Input: title, description, channel, source config.
Output: category, confidence, matched_rules.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from tadabbur.config.models import Source
from tadabbur.metadata.quran_ref import extract_quran_reference

CATEGORIES = ("tadabbur", "tafsir", "quran", "fiqh", "sirah", "other")

# Global include/exclude keyword lists (configurable per source via source.rules).
_DEFAULT_INCLUDE = (
    "tadabbur",
    "tadabburlah",
    "tafsir",
    "quran",
    "ayat",
    "surah",
    "recitation",
    "tajwid",
    "qur'an",
    "quranic",
    "fiqh",
    "sirah",
    "sirah nabawiyyah",
    "sirah nabawiah",
)
_DEFAULT_EXCLUDE = (
    "shorts",
    "promo",
    "announcement",
    "trailer",
    "behind the scenes",
    "live stream",
    "live streaming",
    "giveaway",
    "coming soon",
)


@dataclass
class Classification:
    category: str = "other"
    confidence: float = 0.0
    matched_rules: list[str] = field(default_factory=list)
    ambiguous: bool = True

    @property
    def is_accepted(self) -> bool:
        # Only Fiqh / sirah / tadabbur / tafsir are downloaded.
        # Quran recitation ("Bacaan ...") is detected as category "quran" and
        # rejected (not lecture content).
        return self.category in {"tadabbur", "tafsir", "fiqh", "sirah"}


def _normalize(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    no_diacritics = "".join(c for c in nfkd if not unicodedata.combining(c))
    return no_diacritics.lower().strip()


def _contains_any(text: str, keywords) -> list[str]:
    return [k for k in keywords if k.lower() in text]


def _has_word(text: str, word: str) -> bool:
    return bool(re.search(rf"\b{re.escape(word)}\b", text, re.IGNORECASE))


def classify_metadata(
    *,
    title: str,
    description: str | None = None,
    source: Source | None = None,
) -> Classification:
    """Classify media using deterministic rules.

    Priority:
    1. Source include/exclude rules (strongest signal).
    2. Global keyword rules.
    3. Quran reference presence (surah/ayat in title).
    4. Fall back to configured default category.
    """
    description = description or ""
    blob = _normalize(f"{title} {description}")

    matched: list[str] = []
    excluded: list[str] = []

    include = list(_DEFAULT_INCLUDE)
    exclude = list(_DEFAULT_EXCLUDE)
    if source is not None:
        include.extend(source.rules.include)
        exclude.extend(source.rules.exclude)

    matched.extend(f"include:{k}" for k in _contains_any(blob, include))
    excluded.extend(f"exclude:{k}" for k in _contains_any(blob, exclude))

    # Exclusions win over inclusions.
    if excluded:
        return Classification(
            category="other",
            confidence=0.9,
            matched_rules=excluded,
            ambiguous=False,
        )

    if not matched:
        # Fall back to Quran-reference detection.
        ref = extract_quran_reference(title)
        if ref.has_surah:
            return Classification(
                category="quran",
                confidence=0.7,
                matched_rules=["quran-reference"],
                ambiguous=True,
            )
        return Classification(
            category="other",
            confidence=0.3,
            matched_rules=[],
            ambiguous=True,
        )

    # Score category from keywords.
    blob_lower = blob
    category = "other"
    confidence = 0.5
    ambiguous = False

    if any(_has_word(blob_lower, k) or k in blob_lower for k in ("tadabbur", "tadabburlah")):
        category = "tadabbur"
        confidence = 0.95
    elif any(k in blob_lower for k in ("tafsir",)):
        category = "tafsir"
        confidence = 0.9
    elif any(k in blob_lower for k in ("fiqh",)):
        category = "fiqh"
        confidence = 0.9
    elif any(k in blob_lower for k in ("sirah", "sirah nabawiyyah", "sirah nabawiah")):
        category = "sirah"
        confidence = 0.9
    elif any(k in blob_lower for k in ("quran", "qur'an", "quranic", "surah", "ayat")):
        category = "quran"
        confidence = 0.8

    return Classification(
        category=category,
        confidence=confidence,
        matched_rules=matched,
        ambiguous=ambiguous,
    )


def accepts(classification: Classification, *, threshold: float = 0.6) -> bool:
    """Decide whether a classification is confident enough to accept."""
    if not classification.is_accepted:
        return False
    return classification.confidence >= threshold
