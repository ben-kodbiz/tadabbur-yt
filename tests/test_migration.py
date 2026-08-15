"""Series/session schema migration tests."""

from __future__ import annotations

import sqlite3

import pytest

from tadabbur.database.connection import open_database
from tadabbur.database.schema import SCHEMA_VERSION


def _create_v1_database(tmp_path) -> str:
    """Create a database with the old v1 schema (no series columns)."""
    db = tmp_path / "v1.sqlite"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE schema_version (version INTEGER NOT NULL);
        INSERT INTO schema_version (version) VALUES (1);
        CREATE TABLE media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            external_id TEXT NOT NULL,
            url TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'DISCOVERED',
            UNIQUE (source_id, external_id)
        );
        """
    )
    conn.commit()
    conn.close()
    return str(db)


def test_migrate_v1_to_v2_adds_series_columns(tmp_path):
    db = _create_v1_database(tmp_path)
    conn = open_database(db)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(media)").fetchall()}
    assert "series_key" in cols
    assert "session_number" in cols
    version = conn.execute("SELECT version FROM schema_version").fetchone()["version"]
    assert version == SCHEMA_VERSION
    conn.close()


def test_migrate_preserves_existing_rows(tmp_path):
    db = _create_v1_database(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO media (source_id, external_id, url, title) VALUES ('s1','v1','u','T')"
    )
    conn.commit()
    conn.close()

    conn = open_database(db)
    row = conn.execute("SELECT * FROM media").fetchone()
    assert row["external_id"] == "v1"
    assert row["series_key"] is None
    conn.close()
