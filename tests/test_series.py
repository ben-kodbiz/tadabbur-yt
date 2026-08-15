"""Series/session detection tests."""

from __future__ import annotations

from tadabbur.metadata.series import SeriesInfo, series_info


def test_surah_series_grouping():
    a = series_info("05-03-2026 Ustaz Ahmad Hasyimi : Tadabbur Surah Al-An'am Siri Ke-35")
    b = series_info("19-05-2026 Ustaz Ahmad Hasyimi : Tadabbur Surah Al-An'am Siri Ke-55")
    c = series_info("12-11-2025 Ustaz Ahmad Hasyimi : Tadabbur Surah Al-An'am Siri Pertama")
    assert a.folder == b.folder == c.folder == "Surah Al-An'am"
    assert (a.session_number, b.session_number, c.session_number) == (35, 55, 1)
    assert all(s.is_series for s in (a, b, c))


def test_surah_series_other_surah():
    si = series_info("Ustaz Ahmad Hasyimi : Tadabbur Surah Ali-Imran Siri Ke-14")
    assert si.folder == "Surah Ali 'Imran"
    assert si.session_number == 14
    assert si.is_series


def test_single_video_gets_own_folder():
    si = series_info("24-07-2026 Ustaz Radhi Abu Bakar: Tadabbur Ayat Qursi")
    assert si.folder == "Tadabbur Ayat Qursi"
    assert si.session_number is None
    assert not si.is_series


def test_tafsir_juzuk_not_session():
    si = series_info("21-01-2026 Ustaz Fadzil : Tafsir Juzuk 28 | Surah At-Tahrim")
    assert si.folder == "Tafsir Juzuk 28 | Surah At-Tahrim"
    assert si.session_number is None


def test_mukhtasar_series_keeps_title_folder():
    si = series_info("(4K) 25-11-2024 Ustaz Qarni Edrus : Mukhtasar As-Soghir Fi Sirah Al-Basyir")
    assert si.folder == "Mukhtasar As-Soghir Fi Sirah Al-Basyir"
    assert si.session_number is None


def test_date_and_ustaz_stripped():
    si = series_info("05-03-2026 Ustaz Ahmad Hasyimi : Tadabbur Surah Al-An'am Siri Ke-35")
    assert si.short_title == "Tadabbur Surah Al-An'am"


def test_series_info_dataclass():
    si = series_info("Tadabbur Surah Al-Mulk")
    assert isinstance(si, SeriesInfo)
    assert si.folder == "Tadabbur Surah Al-Mulk"
    assert si.short_title == "Tadabbur Surah Al-Mulk"
