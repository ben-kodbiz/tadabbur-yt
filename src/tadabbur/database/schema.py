"""SQLite schema for the Tadabbur pipeline."""

from __future__ import annotations

SCHEMA_VERSION = 1

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    id                   TEXT PRIMARY KEY,
    name                 TEXT NOT NULL,
    platform             TEXT NOT NULL DEFAULT 'youtube',
    channel_url          TEXT NOT NULL,
    channel_id           TEXT,
    enabled              INTEGER NOT NULL DEFAULT 1,
    language             TEXT NOT NULL DEFAULT 'ms',
    rights_status        TEXT NOT NULL DEFAULT 'unknown',
    download_policy      INTEGER NOT NULL DEFAULT 1,
    publication_policy   INTEGER NOT NULL DEFAULT 0,
    created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS media (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id            TEXT NOT NULL REFERENCES sources(id),
    external_id          TEXT NOT NULL,
    url                  TEXT NOT NULL,
    title                TEXT NOT NULL,
    description          TEXT,
    uploader             TEXT,
    channel              TEXT,
    published_at         TEXT,
    duration             INTEGER,
    thumbnail_url        TEXT,
    status               TEXT NOT NULL DEFAULT 'DISCOVERED',
    rights_status        TEXT NOT NULL DEFAULT 'unknown',
    publication_policy   INTEGER NOT NULL DEFAULT 0,
    classifier_model     TEXT,
    classifier_version   TEXT,
    qwen_used            INTEGER NOT NULL DEFAULT 0,
    error_message        TEXT,
    created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (source_id, external_id)
);

CREATE TABLE IF NOT EXISTS media_files (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    media_id             INTEGER NOT NULL REFERENCES media(id),
    kind                 TEXT NOT NULL,
    path                 TEXT NOT NULL,
    size_bytes           INTEGER,
    sha256               TEXT,
    mime_type            TEXT,
    created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (media_id, kind)
);

CREATE TABLE IF NOT EXISTS classifications (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    media_id             INTEGER NOT NULL REFERENCES media(id),
    category             TEXT NOT NULL,
    confidence           REAL,
    method               TEXT NOT NULL DEFAULT 'rules',
    matched_rules        TEXT,
    model                TEXT,
    created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (media_id, method)
);

CREATE TABLE IF NOT EXISTS tags (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    name                 TEXT NOT NULL UNIQUE,
    created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS media_tags (
    media_id             INTEGER NOT NULL REFERENCES media(id),
    tag_id               INTEGER NOT NULL REFERENCES tags(id),
    source               TEXT NOT NULL DEFAULT 'rules',
    created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY (media_id, tag_id)
);

CREATE TABLE IF NOT EXISTS processing_jobs (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    media_id             INTEGER NOT NULL REFERENCES media(id),
    job_type             TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'pending',
    attempt              INTEGER NOT NULL DEFAULT 0,
    max_attempts         INTEGER NOT NULL DEFAULT 5,
    started_at           TEXT,
    finished_at          TEXT,
    error                TEXT,
    created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS download_attempts (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    media_id             INTEGER NOT NULL REFERENCES media(id),
    attempt              INTEGER NOT NULL,
    status               TEXT NOT NULL,
    started_at           TEXT,
    finished_at          TEXT,
    exit_code            INTEGER,
    ytdlp_version        TEXT,
    error                TEXT,
    output_file          TEXT,
    created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS publish_jobs (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    media_id             INTEGER NOT NULL REFERENCES media(id),
    publisher            TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'pending',
    attempt              INTEGER NOT NULL DEFAULT 0,
    external_url         TEXT,
    started_at           TEXT,
    finished_at          TEXT,
    error                TEXT,
    created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_media_status ON media(status);
CREATE INDEX IF NOT EXISTS idx_media_source_external ON media(source_id, external_id);
CREATE INDEX IF NOT EXISTS idx_jobs_media ON processing_jobs(media_id);
CREATE INDEX IF NOT EXISTS idx_jobs_type_status ON processing_jobs(job_type, status);
CREATE INDEX IF NOT EXISTS idx_download_attempts_media ON download_attempts(media_id);
CREATE INDEX IF NOT EXISTS idx_publish_media ON publish_jobs(media_id);
"""
