"""Data-access layer for the Tadabbur SQLite database."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from tadabbur.status import (
    ATTEMPT_FAILED,
    ATTEMPT_SUCCESS,
    JOB_FAILED,
    JOB_INTERRUPTED,
    JOB_PENDING,
    JOB_RUNNING,
    JOB_SUCCESS,
)
def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class Repository:
    """Thin, explicit data-access layer over the SQLite schema."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------ sources
    def upsert_source(
        self,
        *,
        source_id: str,
        name: str,
        channel_url: str,
        platform: str = "youtube",
        channel_id: str | None = None,
        enabled: bool = True,
        language: str = "ms",
        rights_status: str = "unknown",
        download_policy: bool = True,
        publication_policy: bool = False,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO sources
                (id, name, platform, channel_url, channel_id, enabled, language,
                 rights_status, download_policy, publication_policy)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                channel_url = excluded.channel_url,
                channel_id = excluded.channel_id,
                enabled = excluded.enabled,
                language = excluded.language,
                rights_status = excluded.rights_status,
                download_policy = excluded.download_policy,
                publication_policy = excluded.publication_policy,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
            """,
            (source_id, name, platform, channel_url, channel_id,
             int(enabled), language, rights_status, int(download_policy), int(publication_policy)),
        )
        self._conn.commit()

    def get_source(self, source_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM sources WHERE id = ?", (source_id,)
        ).fetchone()

    def list_sources(self, enabled_only: bool = False) -> list[sqlite3.Row]:
        sql = "SELECT * FROM sources"
        if enabled_only:
            sql += " WHERE enabled = 1"
        return self._conn.execute(sql).fetchall()

    # ------------------------------------------------------------------- media
    def insert_media(
        self,
        *,
        source_id: str,
        external_id: str,
        url: str,
        title: str,
        description: str | None = None,
        uploader: str | None = None,
        channel: str | None = None,
        published_at: str | None = None,
        duration: int | None = None,
        thumbnail_url: str | None = None,
        status: str = "DISCOVERED",
        rights_status: str = "unknown",
        publication_policy: bool = False,
        series_key: str | None = None,
        session_number: int | None = None,
    ) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO media
                (source_id, external_id, url, title, description, uploader, channel,
                 published_at, duration, thumbnail_url, series_key, session_number,
                 status, rights_status, publication_policy)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (source_id, external_id, url, title, description, uploader, channel,
             published_at, duration, thumbnail_url, series_key, session_number,
             status, rights_status, int(publication_policy)),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def media_exists(self, source_id: str, external_id: str) -> bool:
        row = self._conn.execute(
            "SELECT id FROM media WHERE source_id = ? AND external_id = ?",
            (source_id, external_id),
        ).fetchone()
        return row is not None

    def get_media(self, media_id: int) -> sqlite3.Row | None:
        return self._conn.execute("SELECT * FROM media WHERE id = ?", (media_id,)).fetchone()

    def get_media_by_external(self, source_id: str, external_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM media WHERE source_id = ? AND external_id = ?",
            (source_id, external_id),
        ).fetchone()

    def get_media_by_external_id(self, external_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM media WHERE external_id = ?", (external_id,)
        ).fetchone()

    def list_media_by_status(
        self,
        status: str,
        limit: int | None = None,
        *,
        video_id: str | None = None,
    ) -> list[sqlite3.Row]:
        """List media by status, optionally scoped to a single external id.

        Filtering happens at the query level so single-video operations never
        load (or touch) unrelated rows.
        """
        sql = "SELECT * FROM media WHERE status = ?"
        args: list[Any] = [status]
        if video_id is not None:
            sql += " AND external_id = ?"
            args.append(video_id)
        sql += " ORDER BY created_at ASC"
        if limit is not None:
            sql += " LIMIT ?"
            args.append(limit)
        return self._conn.execute(sql, args).fetchall()

    def set_media_status(self, media_id: int, status: str, error_message: str | None = None) -> None:
        self._conn.execute(
            "UPDATE media SET status = ?, error_message = ?, updated_at = ? WHERE id = ?",
            (status, error_message, _now(), media_id),
        )
        self._conn.commit()

    def transition_media(
        self, media_id: int, to_status: str, *, error_message: str | None = None
    ) -> None:
        """Validate a state transition, apply it, and record it in the history log."""
        row = self.get_media(media_id)
        if row is None:
            raise ValueError(f"no media row with id {media_id}")
        from_status = row["status"]
        self._conn.execute(
            """
            INSERT INTO state_transitions (media_id, from_status, to_status)
            VALUES (?, ?, ?)
            """,
            (media_id, from_status, to_status),
        )
        self.set_media_status(media_id, to_status, error_message)

    def set_media_classifier(
        self, media_id: int, model: str, version: str, qwen_used: bool
    ) -> None:
        self._conn.execute(
            "UPDATE media SET classifier_model = ?, classifier_version = ?, "
            "qwen_used = ?, updated_at = ? WHERE id = ?",
            (model, version, int(qwen_used), _now(), media_id),
        )
        self._conn.commit()

    def enrich_media(
        self,
        media_id: int,
        *,
        title: str | None = None,
        description: str | None = None,
        uploader: str | None = None,
        channel: str | None = None,
        published_at: str | None = None,
        duration: int | None = None,
        thumbnail_url: str | None = None,
    ) -> None:
        """Update authoritative source fields from an inspect call."""
        self._conn.execute(
            """
            UPDATE media SET
                title = COALESCE(?, title),
                description = COALESCE(?, description),
                uploader = COALESCE(?, uploader),
                channel = COALESCE(?, channel),
                published_at = COALESCE(?, published_at),
                duration = COALESCE(?, duration),
                thumbnail_url = COALESCE(?, thumbnail_url),
                updated_at = ?
            WHERE id = ?
            """,
            (title, description, uploader, channel, published_at,
             duration, thumbnail_url, _now(), media_id),
        )
        self._conn.commit()

    def list_failed(self) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM media WHERE status = 'FAILED' ORDER BY updated_at DESC"
        ).fetchall()

    # ------------------------------------------------------------ media files
    def upsert_media_file(
        self,
        *,
        media_id: int,
        kind: str,
        path: str,
        size_bytes: int | None = None,
        sha256: str | None = None,
        mime_type: str | None = None,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO media_files (media_id, kind, path, size_bytes, sha256, mime_type)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(media_id, kind) DO UPDATE SET
                path = excluded.path,
                size_bytes = excluded.size_bytes,
                sha256 = excluded.sha256,
                mime_type = excluded.mime_type,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
            """,
            (media_id, kind, path, size_bytes, sha256, mime_type),
        )
        self._conn.commit()

    def get_media_file(self, media_id: int, kind: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM media_files WHERE media_id = ? AND kind = ?",
            (media_id, kind),
        ).fetchone()

    def list_media_files(self, media_id: int) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM media_files WHERE media_id = ? ORDER BY kind", (media_id,)
        ).fetchall()

    # -------------------------------------------------------- classifications
    def save_classification(
        self,
        *,
        media_id: int,
        category: str,
        confidence: float,
        method: str,
        matched_rules: list[str] | None = None,
        model: str | None = None,
    ) -> None:
        rules_json = json.dumps(matched_rules) if matched_rules else None
        self._conn.execute(
            """
            INSERT INTO classifications (media_id, category, confidence, method, matched_rules, model)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(media_id, method) DO UPDATE SET
                category = excluded.category,
                confidence = excluded.confidence,
                matched_rules = excluded.matched_rules,
                model = excluded.model
            """,
            (media_id, category, confidence, method, rules_json, model),
        )
        self._conn.commit()

    def get_classification(self, media_id: int, method: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM classifications WHERE media_id = ? AND method = ?",
            (media_id, method),
        ).fetchone()

    def get_effective_classification(self, media_id: int) -> sqlite3.Row | None:
        row = self._conn.execute(
            """
            SELECT * FROM classifications WHERE media_id = ?
            ORDER BY CASE method WHEN 'rules' THEN 0 WHEN 'qwen' THEN 1 ELSE 2 END,
                     confidence DESC
            """,
            (media_id,),
        ).fetchone()
        return row

    # ------------------------------------------------------------------- tags
    def ensure_tag(self, name: str) -> int:
        self._conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
        row = self._conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
        return int(row["id"])

    def attach_tag(self, media_id: int, tag: str, source: str = "rules") -> None:
        tag_id = self.ensure_tag(tag)
        self._conn.execute(
            "INSERT OR IGNORE INTO media_tags (media_id, tag_id, source) VALUES (?, ?, ?)",
            (media_id, tag_id, source),
        )
        self._conn.commit()

    def attach_tags(self, media_id: int, tags: list[str], source: str = "rules") -> None:
        for tag in tags:
            self.attach_tag(media_id, tag, source=source)

    def tags_for_media(self, media_id: int) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT t.name, mt.source FROM media_tags mt "
            "JOIN tags t ON t.id = mt.tag_id WHERE mt.media_id = ? ORDER BY t.name",
            (media_id,),
        ).fetchall()

    def list_tags(self) -> list[sqlite3.Row]:
        return self._conn.execute("SELECT * FROM tags ORDER BY name").fetchall()

    # --------------------------------------------------------- processing jobs
    def create_job(self, media_id: int, job_type: str, max_attempts: int = 5) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO processing_jobs (media_id, job_type, status, max_attempts)
            VALUES (?, ?, ?, ?)
            """,
            (media_id, job_type, JOB_PENDING, max_attempts),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def claim_pending_jobs(self, job_type: str | None = None, limit: int = 10) -> list[sqlite3.Row]:
        """Atomically mark pending jobs as running and return them."""
        sql = "SELECT id FROM processing_jobs WHERE status = ?"
        args: list[Any] = [JOB_PENDING]
        if job_type:
            sql += " AND job_type = ?"
            args.append(job_type)
        sql += " ORDER BY created_at ASC LIMIT ?"
        args.append(limit)
        rows = self._conn.execute(sql, args).fetchall()
        ids = [r["id"] for r in rows]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            self._conn.execute(
                f"UPDATE processing_jobs SET status = ?, started_at = ?, updated_at = ? "
                f"WHERE id IN ({placeholders})",
                (JOB_RUNNING, _now(), _now(), *ids),
            )
            self._conn.commit()
        return self._conn.execute(
            f"SELECT * FROM processing_jobs WHERE id IN ({','.join('?' for _ in ids)})"
            if ids else "SELECT * FROM processing_jobs WHERE 0",
            ids,
        ).fetchall()

    def get_pending_job_for_media(self, media_id: int, job_type: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM processing_jobs WHERE media_id = ? AND job_type = ? "
            "AND status IN ('pending','running','failed','interrupted') ORDER BY id DESC LIMIT 1",
            (media_id, job_type),
        ).fetchone()

    def mark_job_success(self, job_id: int) -> None:
        self._conn.execute(
            "UPDATE processing_jobs SET status = ?, finished_at = ?, updated_at = ? WHERE id = ?",
            (JOB_SUCCESS, _now(), _now(), job_id),
        )
        self._conn.commit()

    def mark_job_failure(self, job_id: int, error: str) -> None:
        self._conn.execute(
            "UPDATE processing_jobs SET status = ?, finished_at = ?, error = ?, "
            "updated_at = ? WHERE id = ?",
            (JOB_FAILED, _now(), error, _now(), job_id),
        )
        self._conn.commit()

    def mark_job_interrupted(self, job_id: int, error: str) -> None:
        self._conn.execute(
            "UPDATE processing_jobs SET status = ?, finished_at = ?, error = ?, "
            "updated_at = ? WHERE id = ?",
            (JOB_INTERRUPTED, _now(), error, _now(), job_id),
        )
        self._conn.commit()

    def increment_job_attempt(self, job_id: int) -> None:
        self._conn.execute(
            "UPDATE processing_jobs SET attempt = attempt + 1, updated_at = ? WHERE id = ?",
            (_now(), job_id),
        )
        self._conn.commit()

    def retry_job(self, job_id: int) -> None:
        self._conn.execute(
            "UPDATE processing_jobs SET status = ?, error = NULL, updated_at = ? WHERE id = ?",
            (JOB_PENDING, _now(), job_id),
        )
        self._conn.commit()

    def list_running_jobs(self) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM processing_jobs WHERE status = ?", (JOB_RUNNING,)
        ).fetchall()

    def find_interrupted_jobs(self) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM processing_jobs WHERE status IN (?, ?)",
            (JOB_INTERRUPTED, JOB_FAILED),
        ).fetchall()

    # ------------------------------------------------------ download attempts
    def record_download_attempt(
        self,
        *,
        media_id: int,
        attempt: int,
        status: str,
        exit_code: int | None = None,
        ytdlp_version: str | None = None,
        error: str | None = None,
        output_file: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO download_attempts
                (media_id, attempt, status, exit_code, ytdlp_version, error,
                 output_file, started_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (media_id, attempt, status, exit_code, ytdlp_version, error,
             output_file, started_at, finished_at),
        )
        self._conn.commit()

    def count_media_failures(self, media_id: int) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM download_attempts WHERE media_id = ? AND status = ?",
            (media_id, ATTEMPT_FAILED),
        ).fetchone()
        return int(row["c"])

    def clear_download_attempts(self, media_id: int) -> None:
        """Reset the attempt budget when an operator requeues a failed item.

        Without this, items that exhausted max_attempts can never retry:
        count_media_failures() keeps exceeding the limit forever.
        """
        self._conn.execute(
            "DELETE FROM download_attempts WHERE media_id = ?", (media_id,)
        )
        self._conn.commit()

    # ------------------------------------------------------------ publish jobs
    def create_publish_job(self, media_id: int, publisher: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO publish_jobs (media_id, publisher) VALUES (?, ?)",
            (media_id, publisher),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def claim_pending_publish_jobs(self, limit: int = 10) -> list[sqlite3.Row]:
        sql = "SELECT id FROM publish_jobs WHERE status = 'pending' ORDER BY created_at ASC LIMIT ?"
        rows = self._conn.execute(sql, (limit,)).fetchall()
        ids = [r["id"] for r in rows]
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        self._conn.execute(
            f"UPDATE publish_jobs SET status = 'running', started_at = ?, updated_at = ? "
            f"WHERE id IN ({placeholders})",
            (_now(), _now(), *ids),
        )
        self._conn.commit()
        return self._conn.execute(
            f"SELECT * FROM publish_jobs WHERE id IN ({placeholders})", ids
        ).fetchall()

    def mark_publish_success(self, job_id: int, external_url: str | None = None) -> None:
        self._conn.execute(
            "UPDATE publish_jobs SET status = 'success', external_url = ?, finished_at = ?, "
            "updated_at = ? WHERE id = ?",
            (external_url, _now(), _now(), job_id),
        )
        self._conn.commit()

    def mark_publish_failure(self, job_id: int, error: str) -> None:
        self._conn.execute(
            "UPDATE publish_jobs SET status = 'failed', error = ?, finished_at = ?, "
            "updated_at = ? WHERE id = ?",
            (error, _now(), _now(), job_id),
        )
        self._conn.commit()

    def reset_interrupted(self) -> int:
        """Reset jobs stuck in 'running' to 'pending' (crash recovery)."""
        cur = self._conn.execute(
            "UPDATE processing_jobs SET status = ?, updated_at = ? WHERE status = ?",
            (JOB_PENDING, _now(), JOB_RUNNING),
        )
        self._conn.commit()
        return cur.rowcount

    # ------------------------------------------------------- circuit state
    def load_circuit_state(self, name: str = "download") -> dict | None:
        """Load persisted circuit-breaker state (survives restarts)."""
        row = self._conn.execute(
            "SELECT * FROM circuit_state WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            return None
        return {
            "state": row["state"],
            "failure_count": row["failure_count"],
            "cooldown_until": row["cooldown_until"],
        }

    def save_circuit_state(
        self,
        name: str,
        state: str,
        failure_count: int,
        cooldown_until: float | None,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO circuit_state (name, state, failure_count, cooldown_until, updated_at)
            VALUES (?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            ON CONFLICT(name) DO UPDATE SET
                state = excluded.state,
                failure_count = excluded.failure_count,
                cooldown_until = excluded.cooldown_until,
                updated_at = excluded.updated_at
            """,
            (name, state, failure_count, cooldown_until),
        )
        self._conn.commit()

    # --------------------------------------------------- source sync state
    def get_source_sync_state(self, source_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM source_sync_state WHERE source_id = ?", (source_id,)
        ).fetchone()
        if row is None:
            return None
        return {
            "source_id": row["source_id"],
            "last_success_at": row["last_success_at"],
            "last_seen_video_id": row["last_seen_video_id"],
            "last_error": row["last_error"],
            "consecutive_failures": row["consecutive_failures"],
        }

    def record_source_success(self, source_id: str, last_seen_video_id: str | None) -> None:
        self._conn.execute(
            """
            INSERT INTO source_sync_state
                (source_id, last_success_at, last_seen_video_id, last_error,
                 consecutive_failures, updated_at)
            VALUES (?, strftime('%Y-%m-%dT%H:%M:%fZ','now'), ?, NULL, 0,
                    strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            ON CONFLICT(source_id) DO UPDATE SET
                last_success_at = excluded.last_success_at,
                last_seen_video_id = excluded.last_seen_video_id,
                last_error = NULL,
                consecutive_failures = 0,
                updated_at = excluded.updated_at
            """,
            (source_id, last_seen_video_id),
        )
        self._conn.commit()

    def record_source_failure(self, source_id: str, error: str) -> None:
        self._conn.execute(
            """
            INSERT INTO source_sync_state
                (source_id, last_error, consecutive_failures, updated_at)
            VALUES (?, ?, 1, strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            ON CONFLICT(source_id) DO UPDATE SET
                last_error = excluded.last_error,
                consecutive_failures = consecutive_failures + 1,
                updated_at = excluded.updated_at
            """,
            (source_id, error),
        )
        self._conn.commit()
