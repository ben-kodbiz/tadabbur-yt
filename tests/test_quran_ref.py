"""Stage 5: Quran/Surah metadata extraction tests."""

from __future__ import annotations

import pytest

from tadabbur.metadata import (
    build_quran_tags,
    extract_quran_reference,
    find_surah,
    get_surah_by_number,
)


def test_surah_dictionary_complete():
    assert get_surah_by_number(1) is not None
    assert get_surah_by_number(114) is not None
    assert get_surah_by_number(18).transliteration == "Al-Kahf"


def test_find_surah_aliases():
    assert find_surah("Tadabbur Surah Al-Kahfi Ayat 1-10").number == 18
    assert find_surah("Tafsir Al-Baqarah 255").number == 2
    assert find_surah("Surah Yasin").number == 36
    assert find_surah("Al Kahfi ayat 10-15").number == 18


def test_extract_ayah_range():
    ref = extract_quran_reference("Tadabbur Surah Al-Kahfi Ayat 1-10")
    assert ref.surah_number == 18
    assert ref.ayah_start == 1
    assert ref.ayah_end == 10
    assert ref.is_valid


def test_extract_single_ayah():
    ref = extract_quran_reference("Tadabbur Al-Baqarah 255")
    assert ref.surah_number == 2
    assert ref.ayah_start == 255
    assert ref.ayah_end == 255


def test_extract_malay_format():
    ref = extract_quran_reference("Al Kahfi ayat 10-15")
    assert ref.surah_number == 18
    assert ref.ayah_start == 10
    assert ref.ayah_end == 15


def test_no_ayah_surah_only():
    ref = extract_quran_reference("Surah Yasin")
    assert ref.surah_number == 36
    assert ref.ayah_start is None
    assert ref.is_valid


def test_uncertain_returns_null():
    ref = extract_quran_reference("Kuliah Umum Sabtu")
    assert ref.surah_number is None
    assert ref.ayah_start is None
    assert ref.is_valid is False


def test_no_invention_of_missing_info():
    ref = extract_quran_reference("Ceramah 10 malam terakhir")
    assert ref.surah_number is None


def test_out_of_range_ayah_rejected():
    ref = extract_quran_reference("Tadabbur Al-Baqarah Ayat 500")
    assert ref.ayah_start is None


def test_build_quran_tags():
    ref = extract_quran_reference("Tadabbur Surah Al-Kahfi Ayat 1-10")
    tags = build_quran_tags(ref)
    assert "surah-al-kahf" in tags
    assert "ayah-1-10" in tags
