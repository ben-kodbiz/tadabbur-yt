"""Repository for the upload pipeline database.

The database is the source of truth; folders are storage.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from tadabbur.uploader.models import (
    APPROVED_FOR_UPLOAD,
    MediaState,
    UploadRightsStatus,
    can_transition,
)


class UploaderRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # -------------------------------------------------------------- sources
    def upsert_source(
        self,
        *,
        source_key: str,
        name: str,
        platform: str = "youtube",
        channel_url: str | None = None,
        attribution_text: str | None = None,
        default_rights_status: str = UploadRightsStatus.MANUAL_REVIEW_REQUIRED,
        enabled: bool = True,
    ) -> int:
        self._conn.execute(
            """
            INSERT INTO sources (source_key, name, platform, channel_url,
                                 attribution_text, default_rights_status, enabled)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_key) DO UPDATE SET
                name = excluded.name,
                platform = excluded.platform,
                channel_url = excluded.channel_url,
                attribution_text = excluded.attribution_text,
                default_rights_status = excluded.default_rights_status,
                enabled = excluded.enabled
            """,
            (source_key, name, platform, channel_url, attribution_text,
             default_rights_status, int(enabled)),
        )
        self._conn.commit()
        row = self.get_source(source_key)
        assert row is not None
        return int(row["id"])

    def get_source(self, source_key: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM sources WHERE source_key = ?", (source_key,)
        ).fetchone()

    def get_source_by_id(self, source_id: int) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM sources WHERE id = ?", (source_id,)
        ).fetchone()

    def list_sources(self, *, enabled_only: bool = False) -> list[sqlite3.Row]:
        sql = "SELECT * FROM sources"
        if enabled_only:
            sql += " WHERE enabled = 1"
        return self._conn.execute(sql).fetchall()

    # ---------------------------------------------------------- media items
    def insert_media_item(
        self,
        *,
        source_id: int,
        platform: str,
        original_media_id: str,
        original_url: str,
        original_title: str | None = None,
        uploader_name: str | None = None,
        published_at: str | None = None,
        duration_seconds: float | None = None,
        rights_status: str = UploadRightsStatus.MANUAL_REVIEW_REQUIRED,
        state: str = MediaState.DISCOVERED,
    ) -> int | None:
        """Insert a new item. Returns None when it already exists (dedup)."""
        try:
            cur = self._conn.execute(
                """
                INSERT INTO media_items (source_id, platform, original_media_id,
                                         original_url, original_title, uploader_name,
                                         published_at, duration_seconds,
                                         rights_status, state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (source_id, platform, original_media_id, original_url, original_title,
                 uploader_name, published_at, duration_seconds, rights_status, state),
            )
            self._conn.commit()
            return int(cur.lastrowid)
        except sqlite3.IntegrityError:
            return None  # duplicate on UNIQUE(platform, original_media_id)

    def get_media_item(self, media_item_id: int) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM media_items WHERE id = ?", (media_item_id,)
        ).fetchone()

    def find_media_item(self, platform: str, original_media_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM media_items WHERE platform = ? AND original_media_id = ?",
            (platform, original_media_id),
        ).fetchone()

    def find_by_original_url(self, url: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM media_items WHERE original_url = ?", (url,)
        ).fetchone()

    def list_media_by_state(self, *states: str, limit: int | None = None) -> list[sqlite3.Row]:
        placeholders = ",".join("?" for _ in states)
        sql = f"SELECT * FROM media_items WHERE state IN ({placeholders}) ORDER BY id"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        return self._conn.execute(sql, states).fetchall()

    def list_upload_queue(self, limit: int | None = None) -> list[sqlite3.Row]:
        """Items eligible for upload: approved rights + READY_FOR_UPLOAD."""
        approved = ",".join("?" for _ in APPROVED_FOR_UPLOAD)
        sql = f"""
            SELECT * FROM media_items
            WHERE state = ? AND rights_status IN ({approved})
              AND upload_status IN ('not_queued', 'retry')
            ORDER BY id
        """
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        return self._conn.execute(sql, (MediaState.READY_FOR_UPLOAD, *APPROVED_FOR_UPLOAD)).fetchall()

    # ------------------------------------------------------ state machine
    def transition(self, media_item_id: int, new_state: str) -> bool:
        """Apply a validated state transition; returns False if invalid."""
        row = self.get_media_item(media_item_id)
        if row is None or not can_transition(row["state"], new_state):
            return False
        self._conn.execute(
            "UPDATE media_items SET state = ?, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
            (new_state, media_item_id),
        )
        self._conn.commit()
        return True

    def set_upload_status(self, media_item_id: int, status: str) -> None:
        self._conn.execute(
            "UPDATE media_items SET upload_status = ?, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
            (status, media_item_id),
        )
        self._conn.commit()

    # ------------------------------------------------------------- rights
    def review_rights(
        self,
        media_item_id: int,
        *,
        rights_status: str,
        notes: str | None = None,
        permission_reference: str | None = None,
    ) -> bool:
        """Record an explicit operator rights decision."""
        if rights_status not in UploadRightsStatus:
            raise ValueError(f"unknown rights status {rights_status!r}")
        row = self.get_media_item(media_item_id)
        if row is None:
            return False
        self._conn.execute(
            """
            UPDATE media_items SET
                rights_status = ?,
                rights_notes = COALESCE(?, rights_notes),
                permission_reference = COALESCE(?, permission_reference),
                rights_reviewed_at = strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
            WHERE id = ?
            """,
            (rights_status, notes, permission_reference, media_item_id),
        )
        self._conn.commit()
        return True

    # --------------------------------------------------------------- files
    def upsert_file(
        self,
        *,
        media_item_id: int,
        file_type: str,
        path: str | Path,
        extension: str | None = None,
        size_bytes: int | None = None,
        sha256: str | None = None,
        codec: str | None = None,
        bitrate: int | None = None,
        duration_seconds: float | None = None,
    ) -> int:
        self._conn.execute(
            """
            INSERT INTO files (media_item_id, file_type, path, extension,
                               size_bytes, sha256, codec, bitrate, duration_seconds)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(media_item_id, file_type) DO UPDATE SET
                path = excluded.path,
                extension = excluded.extension,
                size_bytes = excluded.size_bytes,
                sha256 = excluded.sha256,
                codec = excluded.codec,
                bitrate = excluded.bitrate,
                duration_seconds = excluded.duration_seconds
            """,
            (media_item_id, file_type, str(path), extension, size_bytes,
             sha256, codec, bitrate, duration_seconds),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT id FROM files WHERE media_item_id = ? AND file_type = ?",
            (media_item_id, file_type),
        ).fetchone()
        assert row is not None
        return int(row["id"])

    def get_file(self, media_item_id: int, file_type: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM files WHERE media_item_id = ? AND file_type = ?",
            (media_item_id, file_type),
        ).fetchone()

    def checksum_exists(self, sha256: str) -> sqlite3.Row | None:
        """Level-3 duplicate protection: same content already recorded."""
        return self._conn.execute(
            "SELECT * FROM files WHERE sha256 = ? LIMIT 1", (sha256,)
        ).fetchone()

    # --------------------------------------------------------------- jobs
    def create_job(self, media_item_id: int, job_type: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO processing_jobs (media_item_id, job_type, status) VALUES (?, ?, 'pending')",
            (media_item_id, job_type),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def claim_job(self, job_type: str) -> sqlite3.Row | None:
        """Atomically claim one pending/retry job (§33).

        The UPDATE...RETURNING pattern ensures only one worker wins.
        """
        cur = self._conn.execute(
            """
            UPDATE processing_jobs
            SET status = 'running',
                attempts = attempts + 1,
                started_at = strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
            WHERE id = (
                SELECT id FROM processing_jobs
                WHERE job_type = ? AND status IN ('pending', 'retry')
                ORDER BY id LIMIT 1
            )
            RETURNING *
            """,
            (job_type,),
        )
        row = cur.fetchone()
        self._conn.commit()
        return row

    def complete_job(self, job_id: int) -> None:
        self._conn.execute(
            "UPDATE processing_jobs SET status = 'completed', "
            "completed_at = strftime('%Y-%m-%dT%H:%M:%fZ','now'), error_message = NULL, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
            (job_id,),
        )
        self._conn.commit()

    def fail_job(self, job_id: int, category: str, message: str, *, retryable: bool = True) -> None:
        status = "retry" if retryable else "failed"
        self._conn.execute(
            "UPDATE processing_jobs SET status = ?, error_category = ?, error_message = ?, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
            (status, category, message[:2000], job_id),
        )
        self._conn.commit()

    def find_interrupted_jobs(self) -> list[sqlite3.Row]:
        """Jobs left RUNNING by a crash (resume support §20)."""
        return self._conn.execute(
            "SELECT * FROM processing_jobs WHERE status = 'running'"
        ).fetchall()

    # ------------------------------------------------------------- uploads
    def ensure_upload_record(self, media_item_id: int, platform: str = "youtube") -> int:
        self._conn.execute(
            """
            INSERT INTO uploads (media_item_id, platform, upload_status)
            VALUES (?, ?, 'not_queued')
            ON CONFLICT(media_item_id, platform) DO NOTHING
            """,
            (media_item_id, platform),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT id FROM uploads WHERE media_item_id = ? AND platform = ?",
            (media_item_id, platform),
        ).fetchone()
        assert row is not None
        return int(row["id"])

    def mark_uploaded(
        self,
        media_item_id: int,
        *,
        platform_video_id: str,
        platform_url: str,
        title_used: str,
        platform: str = "youtube",
    ) -> None:
        """An upload only counts once the platform video id is stored (§30)."""
        self.ensure_upload_record(media_item_id, platform)
        self._conn.execute(
            """
            UPDATE uploads SET
                upload_status = 'uploaded',
                platform_video_id = ?,
                platform_url = ?,
                title_used = ?,
                uploaded_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
            WHERE media_item_id = ? AND platform = ?
            """,
            (platform_video_id, platform_url, title_used, media_item_id, platform),
        )
        self.set_upload_status(media_item_id, "uploaded")

    # ------------------------------------------------------------ summary
    def summary(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT state, COUNT(*) n FROM media_items GROUP BY state ORDER BY state"
        ).fetchall()
        return {r["state"]: r["n"] for r in rows}
