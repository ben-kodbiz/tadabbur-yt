"""SQLite connection management."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from tadabbur.database.schema import SCHEMA_SQL, SCHEMA_VERSION


class DatabaseError(Exception):
    """Raised for database-level failures."""


def connect(db_path: Path | str) -> sqlite3.Connection:
    """Open a SQLite connection configured for the pipeline."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    """Apply schema if not present; record the schema version."""
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'")
    if cur.fetchone() is None:
        conn.executescript(SCHEMA_SQL)
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        conn.commit()
        return

    row = conn.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()
    if row is None:
        conn.executescript(SCHEMA_SQL)
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        conn.commit()
        return

    current = row["version"]
    if current < SCHEMA_VERSION:
        _apply_migrations(conn, current, SCHEMA_VERSION)


def _apply_migrations(conn: sqlite3.Connection, from_version: int, to_version: int) -> None:
    """Apply incremental migrations from ``from_version`` up to ``to_version``."""
    from tadabbur.database.schema import MIGRATIONS

    # Collapse any duplicated schema_version rows into the single highest one.
    conn.execute(
        "DELETE FROM schema_version WHERE rowid NOT IN "
        "(SELECT MAX(rowid) FROM schema_version)"
    )

    for version in range(from_version, to_version):
        statements = MIGRATIONS.get(version)
        if not statements:
            raise DatabaseError(
                f"no migration defined for schema version {version} -> {version + 1}"
            )
        for statement in statements:
            conn.execute(statement)
        conn.execute(
            "UPDATE schema_version SET version = ? WHERE rowid = "
            "(SELECT MIN(rowid) FROM schema_version)",
            (version + 1,),
        )
        if conn.total_changes == 0:
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version + 1,))
    conn.commit()

def open_database(db_path: Path | str) -> sqlite3.Connection:
    """Open a connection and ensure the schema is applied."""
    conn = connect(db_path)
    migrate(conn)
    return conn
