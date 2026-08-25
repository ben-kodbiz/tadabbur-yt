"""Upload pipeline Phase 7: metadata generation."""

from pathlib import Path

from tadabbur.uploader.metadata import (
    build_description,
    build_metadata_record,
    build_title,
    write_metadata_json,
)


def test_title_format_matches_spec():
    t = build_title("Tafsir Surah Al-Fatihah", "Ustaz Test")
    assert t == "[Archive] Tafsir Surah Al-Fatihah — Ustaz Test"


def test_title_truncated_to_yt_limit():
    long = "A" * 300
    t = build_title(long, "Speaker")
    assert len(t) <= 100
    assert t.startswith("[Archive] ")
    assert "Speaker" in t


def test_description_contains_provenance_and_no_false_permission():
    d = build_description(
        original_title="Kuliah Maghrib",
        source_name="Maulana Asri",
        source_url="https://example.com/@chan",
        original_url="https://youtube.com/watch?v=vidAAAAAAAA1",
        rights_status="permission_confirmed",
    )
    assert "Original title:" in d and "Kuliah Maghrib" in d
    assert "Original speaker/channel:" in d and "Maulana Asri" in d
    assert "https://youtube.com/watch?v=vidAAAAAAAA1" in d
    assert "does not claim authorship" in d
    assert "Rights status:\npermission_confirmed" in d


def test_never_claims_permission_without_evidence():
    """Core policy: no 'used with permission' unless actually recorded."""
    d = build_description(
        original_title="T", source_name="S", source_url=None,
        original_url="u", rights_status="manual_review_required",
    )
    assert "used with permission" not in d.lower()


def test_permission_reference_included_when_recorded():
    d = build_description(
        original_title="T", source_name="S", source_url=None,
        original_url="u", rights_status="license_confirmed",
        extra_permission_text="Permission reference: MAIL-2026-001",
    )
    assert "MAIL-2026-001" in d


def test_full_record_bundle(tmp_path: Path):
    meta = build_metadata_record(
        original_title="Tadabbur Surah Yasin",
        speaker="Ustaz Qarni",
        source_name="PROmediaTAJDID",
        source_url="https://youtube.com/@promedia",
        original_url="https://youtube.com/watch?v=vidZZZZZZZZ1",
        rights_status="creative_commons",
        permission_note="CC-BY license link",
    )
    assert meta.title == "[Archive] Tadabbur Surah Yasin — Ustaz Qarni"
    assert "creative_commons" in meta.description
    assert "CC-BY license link" in meta.description
    assert meta.privacy == "unlisted"

    path = write_metadata_json(tmp_path, "stem__x", meta)
    data = __import__("json").loads(path.read_text())
    assert data["categoryId"] == "27"
