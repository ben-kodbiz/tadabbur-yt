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


def test_source_include_rules_used_in_service(tmp_path):
    """Channel-specific include/exclude rules from config must apply."""
    import yaml

    from tadabbur.config import load_settings
    from tadabbur.database import Repository, open_database
    from tadabbur.services.classification import classify
    from tadabbur.status import QUEUED, REJECTED

    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "storage": {"base_dir": str(tmp_path / "data")},
                "sources": [
                    {
                        "id": "ustaz",
                        "name": "Ustaz",
                        "channel_url": "https://youtube.com/@x",
                        "enabled": True,
                        "rules": {"include": ["kuliah", "siri"], "exclude": ["cuaca"]},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    settings = load_settings(config_file=cfg)
    conn = open_database(settings.storage.database_path)
    repo = Repository(conn)
    repo.upsert_source(source_id="ustaz", name="Ustaz", channel_url="https://youtube.com/@x")

    repo.insert_media(
        source_id="ustaz", external_id="v1", url="https://youtu.be/v1",
        title="SIRI 3: KULIAH TAFSIR", status="DISCOVERED",
    )
    repo.insert_media(
        source_id="ustaz", external_id="v2", url="https://youtu.be/v2",
        title="Tadabbur Al-Kahfi", status="DISCOVERED",
    )
    repo.insert_media(
        source_id="ustaz", external_id="v3", url="https://youtu.be/v3",
        title="Ramalan cuaca hari ini", status="DISCOVERED",
    )

    classify(repo, settings)

    by_id = {r["external_id"]: r["status"] for r in
             repo._conn.execute("SELECT * FROM media").fetchall()}
    # v1 matches configured include keywords -> accepted
    assert by_id["v1"] == QUEUED
    # v3 matches configured exclude keyword -> rejected
    assert by_id["v3"] == REJECTED
    # v2 matches only global keyword (tadabbur) -> accepted
    assert by_id["v2"] == QUEUED
    conn.close()
