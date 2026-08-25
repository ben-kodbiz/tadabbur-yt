"""SQLite schema and migrations for the upload pipeline (pipeline.db)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 2

MIGRATIONS: dict[int, list[str]] = {
    1: [
        "ALTER TABLE media_items ADD COLUMN original_sha256 TEXT",
        """
        CREATE TABLE IF NOT EXISTS media_events (
            id INTEGER PRIMARY KEY,
            media_item_id INTEGER NOT NULL REFERENCES media_items(id),
            event_type TEXT NOT NULL,
            old_state TEXT,
            new_state TEXT,
            message TEXT,
            error_category TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_media_events_media ON media_events(media_item_id)",
        """
        CREATE TABLE IF NOT EXISTS upload_attempts (
            id INTEGER PRIMARY KEY,
            media_item_id INTEGER NOT NULL REFERENCES media_items(id),
            attempt_no INTEGER NOT NULL DEFAULT 1,
            started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            finished_at TEXT,
            status TEXT NOT NULL DEFAULT 'running',
            error_category TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_upload_attempts_media ON upload_attempts(media_item_id)",
    ],
}

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY,
    source_key TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    platform TEXT NOT NULL DEFAULT 'youtube',
    channel_url TEXT,
    attribution_text TEXT,
    default_rights_status TEXT NOT NULL DEFAULT 'manual_review_required',
    enabled INTEGER DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS media_items (
    id INTEGER PRIMARY KEY,

    source_id INTEGER NOT NULL REFERENCES sources(id),

    platform TEXT NOT NULL,
    original_media_id TEXT NOT NULL,

    original_url TEXT NOT NULL,
    original_title TEXT,

    uploader_name TEXT,
    published_at TEXT,

    duration_seconds REAL,

    rights_status TEXT NOT NULL DEFAULT 'manual_review_required',
    original_sha256 TEXT,
    rights_reviewed_at TEXT,
    rights_notes TEXT,
    permission_reference TEXT,

    state TEXT NOT NULL DEFAULT 'DISCOVERED',

    upload_status TEXT NOT NULL DEFAULT 'not_queued',

    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

    UNIQUE(platform, original_media_id)
);

CREATE INDEX IF NOT EXISTS idx_media_items_state ON media_items(state);
CREATE INDEX IF NOT EXISTS idx_media_items_upload_status ON media_items(upload_status);

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,

    media_item_id INTEGER NOT NULL REFERENCES media_items(id),

    file_type TEXT NOT NULL,

    path TEXT NOT NULL,

    extension TEXT,
    size_bytes INTEGER,

    sha256 TEXT,

    codec TEXT,
    bitrate INTEGER,
    duration_seconds REAL,

    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

    UNIQUE(media_item_id, file_type)
);

CREATE TABLE IF NOT EXISTS processing_jobs (
    id INTEGER PRIMARY KEY,

    media_item_id INTEGER NOT NULL REFERENCES media_items(id),

    job_type TEXT NOT NULL,

    status TEXT NOT NULL DEFAULT 'pending',

    attempts INTEGER DEFAULT 0,

    started_at TEXT,
    completed_at TEXT,

    error_category TEXT,
    error_message TEXT,

    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_jobs_media ON processing_jobs(media_item_id);
CREATE INDEX IF NOT EXISTS idx_jobs_type_status ON processing_jobs(job_type, status);

CREATE TABLE IF NOT EXISTS uploads (
    id INTEGER PRIMARY KEY,

    media_item_id INTEGER NOT NULL REFERENCES media_items(id),

    platform TEXT NOT NULL DEFAULT 'youtube',

    upload_status TEXT NOT NULL DEFAULT 'not_queued',

    platform_video_id TEXT,
    platform_url TEXT,

    title_used TEXT,

    uploaded_at TEXT,

    attempt_count INTEGER DEFAULT 0,

    error_message TEXT,

    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(media_item_id, platform)
);

CREATE TABLE IF NOT EXISTS media_events (
    id INTEGER PRIMARY KEY,
    media_item_id INTEGER NOT NULL REFERENCES media_items(id),
    event_type TEXT NOT NULL,
    old_state TEXT,
    new_state TEXT,
    message TEXT,
    error_category TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_media_events_media ON media_events(media_item_id);

CREATE TABLE IF NOT EXISTS upload_attempts (
    id INTEGER PRIMARY KEY,
    media_item_id INTEGER NOT NULL REFERENCES media_items(id),
    attempt_no INTEGER NOT NULL DEFAULT 1,
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    error_category TEXT
);

CREATE INDEX IF NOT EXISTS idx_upload_attempts_media ON upload_attempts(media_item_id);
"""


def connect(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    """Create/upgrade the pipeline schema."""
    conn.executescript(SCHEMA_SQL)
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    current = row["version"] if row else 0

    if current == 0:
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
    elif current < SCHEMA_VERSION:
        for v in range(current, SCHEMA_VERSION):
            for stmt in MIGRATIONS.get(v, []):
                conn.execute(stmt)
        conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))
    conn.commit()


def open_database(db_path: Path | str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    migrate(conn)
    return conn
