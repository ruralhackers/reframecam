"""Persistent key/value settings.

A small wrapper over the `setting` table for runtime-toggleable settings that
the admin can flip without a restart. Distinct from `app.config.Settings` —
that's deploy-time configuration (env vars, site.toml); this is operational
state the operator changes from the admin UI.

Values are stored as TEXT — callers convert to/from the type they need. The
table is created by `app.db.init()`; callers pass a connection in.
"""

from __future__ import annotations

import sqlite3


UPLOAD_NOTIFICATIONS_KEY = "upload_notifications_enabled"


def get(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute(
        "SELECT value FROM setting WHERE key = ?", (key,)
    ).fetchone()
    if row is None:
        return default

    return row["value"]


def set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO setting (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def upload_notifications_enabled(conn: sqlite3.Connection) -> bool:
    """Defaults to False — operators opt in from the admin Settings page."""
    return get(conn, UPLOAD_NOTIFICATIONS_KEY, "false").lower() == "true"


def set_upload_notifications_enabled(conn: sqlite3.Connection, enabled: bool) -> None:
    set(conn, UPLOAD_NOTIFICATIONS_KEY, "true" if enabled else "false")
