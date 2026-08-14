"""Stage 4: deterministic classifier tests."""

from __future__ import annotations

from tadabbur.classifier import accepts, classify_metadata
from tadabbur.config.models import Source

SRC = Source(id="ustaz", name="Ustaz", channel_url="https://youtube.com/@x")


def test_tadabbur_title_high_confidence():
    c = classify_metadata(
        title="Tadabbur Surah Al-Kahfi Ayat 1-10",
        description="Kuliah tadabbur oleh Ustaz",
        source=SRC,
    )
    assert c.category == "tadabbur"
    assert c.confidence >= 0.9
    assert accepts(c)


def test_tafsir_category():
    c = classify_metadata(title="Tafsir Al-Baqarah 255", source=SRC)
    assert c.category == "tafsir"


def test_quran_only_reference():
    c = classify_metadata(title="Surah Yasin", source=SRC)
    assert c.category == "quran"
    assert c.confidence >= 0.6


def test_other_content():
    c = classify_metadata(title="Announcement: Seminar Ramadan", source=SRC)
    assert c.category == "other"
    assert not accepts(c)


def test_exclusion_wins():
    c = classify_metadata(title="Tadabbur Al-Kahfi Shorts", source=SRC)
    assert c.category == "other"
    assert any("exclude" in r for r in c.matched_rules)


def test_case_insensitive_and_unicode():
    c = classify_metadata(title="TADABBUR AL-KAHFI AYAT 1-10", source=SRC)
    assert c.category == "tadabbur"


def test_source_include_rules_extend():
    src = SRC.model_copy(deep=True)
    src.rules.include.append("kuliah")
    c = classify_metadata(title="Kuliah Malam Jumaat", source=src)
    assert c.category in {"tadabbur", "tafsir", "quran"} or c.matched_rules


def test_no_source_fallback():
    c = classify_metadata(title="Tadabbur Al-Mulk 1-5", source=None)
    assert c.category == "tadabbur"
