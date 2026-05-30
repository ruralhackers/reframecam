"""SQLite schema, connection helper, and migration entry point.

Schema: a `location` table (the place a set of stations sits in), a `station`
table keyed by slug and referencing its location, a `photo` table with the
columns the upload pipeline and admin fill in, and the two indexes the
recent-references query (§7.4) leans on.

The DB file lives at `{settings.data_root}/reframe.db`. `init()` is idempotent
so re-running it is safe.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from app import config, countries


DB_FILENAME = "reframe.db"


SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS location (
        slug                  TEXT PRIMARY KEY,
        name                  TEXT NOT NULL,
        country               TEXT NOT NULL DEFAULT 'ES',
        created_at            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS station (
        slug                  TEXT PRIMARY KEY,
        name_es               TEXT NOT NULL,
        name_en               TEXT NOT NULL,
        location_slug         TEXT REFERENCES location(slug),
        story_es              TEXT NOT NULL,
        story_en              TEXT NOT NULL,
        latitude              REAL,
        longitude             REAL,
        contact_name          TEXT,
        contact_email         TEXT,
        status                TEXT NOT NULL DEFAULT 'active',
        created_at            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS photo (
        id                    INTEGER PRIMARY KEY AUTOINCREMENT,
        station_slug          TEXT NOT NULL REFERENCES station(slug),
        captured_at           DATETIME NOT NULL,
        uploaded_at           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        client_token          TEXT UNIQUE NOT NULL,
        filename              TEXT NOT NULL,
        viewer_path           TEXT NOT NULL,
        thumb_path            TEXT NOT NULL,
        width                 INTEGER NOT NULL,
        height                INTEGER NOT NULL,
        removed_at            DATETIME,
        removal_reason        TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS photo_station_captured ON photo (station_slug, captured_at)",
    "CREATE INDEX IF NOT EXISTS photo_active           ON photo (station_slug, removed_at, captured_at)",
    """
    CREATE TABLE IF NOT EXISTS setting (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
)


def db_path() -> Path:
    """Return the absolute path to the SQLite file for the current settings."""
    return config.settings.data_root / DB_FILENAME


def connect() -> sqlite3.Connection:
    """Open a connection to the configured SQLite database.

    Ensures the parent directory exists, switches on foreign-key enforcement
    (off by default in SQLite) and uses `Row` for dict-like row access. The
    caller is responsible for closing the connection.
    """
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        path,
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        isolation_level=None,  # autocommit; explicit transactions where needed
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    return conn


# Idempotent column additions for tables created by an earlier schema
# revision. SQLite's CREATE TABLE IF NOT EXISTS is a no-op when the table
# exists, so a column added later needs an explicit ALTER. Each entry is
# (table, column_def); duplicate-column errors are swallowed so re-running on
# a fully-migrated DB is a no-op. On a fresh DB the column already exists from
# SCHEMA_STATEMENTS, so every ALTER here is a swallowed no-op there too.
COLUMN_ADDITIONS: tuple[tuple[str, str], ...] = (
    ("station", "location_slug TEXT REFERENCES location(slug)"),
    ("station", "latitude REAL"),
    ("station", "longitude REAL"),
    ("station", "contact_name TEXT"),
    ("station", "contact_email TEXT"),
    ("station", "status TEXT NOT NULL DEFAULT 'active'"),
)

# Idempotent column drops, applied after the additions. Each entry is
# (table, column); "no such column" is swallowed so re-running is a no-op.
# DROP COLUMN needs SQLite >= 3.35 (bundled with Python 3.11).
COLUMN_DROPS: tuple[tuple[str, str], ...] = (
    ("station", "drone_video_url"),
    ("station", "drone_video_thumb"),
    ("station", "place_name"),
    ("station", "placeholder_image"),
    ("station", "recording_since"),
    ("station", "is_featured"),
    ("photo", "original_path"),
)


def init(conn: sqlite3.Connection | None = None) -> None:
    """Apply the schema. Idempotent.

    Accepts an optional connection so tests can drive a temp DB without
    touching settings; otherwise opens its own.
    """
    own = conn is None
    if own:
        conn = connect()
    try:
        for statement in SCHEMA_STATEMENTS:
            conn.execute(statement)
        for table, column_def in COLUMN_ADDITIONS:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise
        for table, column in COLUMN_DROPS:
            try:
                conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
            except sqlite3.OperationalError as exc:
                if "no such column" not in str(exc).lower():
                    raise
        _migrate_country_codes(conn)
    finally:
        if own:
            conn.close()


def _migrate_country_codes(conn: sqlite3.Connection) -> None:
    """Convert any legacy free-text `location.country` values to ISO codes.

    Idempotent — a row already holding a known ISO code is left alone. Rows
    with unrecognised values stay as-is; the display layer falls back to the
    raw string so a fork's pre-existing data still renders something.
    """
    rows = conn.execute("SELECT slug, country FROM location").fetchall()
    for row in rows:
        new_value = countries.migrate_legacy_value(row["country"])
        if new_value is not None and new_value != row["country"]:
            conn.execute(
                "UPDATE location SET country = ? WHERE slug = ?",
                (new_value, row["slug"]),
            )


def _cli(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] != "init":
        print("usage: python -m app.db init", file=sys.stderr)
        return 2
    init()
    print(f"DB initialised at {db_path()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
