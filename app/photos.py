"""Photo query helpers used by the station page (Phase 2/3) and the
validation pipeline (Phase 5).

These wrap the read paths the spec leans on:

- §5.5 / §5.6  — recent photos in reverse-chronological order for the viewer
                 and for the cold-start state machine.
- §5.4         — most recent photo as the reference image (None when the
                 station has no active photos — the cold-start empty state).
- §7.4         — sliding-window reference set: seeds + the 5 most recent
                 active photos, used by the OpenCV feature matcher.

Functions accept an open `sqlite3.Connection` so callers (request handlers,
tests, CLI) control transaction boundaries and so tests can drive a temp DB.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app import storage


def recent_active(
    conn: sqlite3.Connection, station_slug: str, limit: int = 20
) -> list[sqlite3.Row]:
    """Return the most recent active (non-removed) photos for a station."""
    cur = conn.execute(
        """
        SELECT *
        FROM photo
        WHERE station_slug = ? AND removed_at IS NULL
        ORDER BY captured_at DESC
        LIMIT ?
        """,
        (station_slug, limit),
    )

    return cur.fetchall()


def all_active_chronological(
    conn: sqlite3.Connection, station_slug: str
) -> list[sqlite3.Row]:
    """All active photos for a station, oldest → newest by `captured_at`.

    Used by the timelapse viewer (§5.5): the playhead steps from oldest to
    newest, the scrubber places ticks at real-time offsets, and the date
    overlay reads `captured_at`. Ordering by id as a tie-breaker keeps the
    sequence deterministic when two photos share a timestamp.
    """
    cur = conn.execute(
        """
        SELECT *
        FROM photo
        WHERE station_slug = ? AND removed_at IS NULL
        ORDER BY captured_at ASC, id ASC
        """,
        (station_slug,),
    )

    return cur.fetchall()


def most_recent(conn: sqlite3.Connection, station_slug: str) -> sqlite3.Row | None:
    """Return the single most recent active photo, or None if there are none."""
    cur = conn.execute(
        """
        SELECT *
        FROM photo
        WHERE station_slug = ? AND removed_at IS NULL
        ORDER BY captured_at DESC
        LIMIT 1
        """,
        (station_slug,),
    )

    return cur.fetchone()


def count_active(conn: sqlite3.Connection, station_slug: str) -> int:
    cur = conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM photo
        WHERE station_slug = ? AND removed_at IS NULL
        """,
        (station_slug,),
    )

    return int(cur.fetchone()["n"])


def admin_list(
    conn: sqlite3.Connection, *, limit: int, offset: int
) -> list[sqlite3.Row]:
    """Active photos across all stations, most recent first.

    Powers the §7.5 admin list — joins each photo to its station so the
    template can render the station's display name without a second query.
    Soft-deleted photos are excluded; the admin only sees photos still in
    the public timelapse.
    """
    cur = conn.execute(
        """
        SELECT photo.*, station.name_es AS station_name_es,
               station.name_en AS station_name_en
        FROM photo
        JOIN station ON station.slug = photo.station_slug
        WHERE photo.removed_at IS NULL
        ORDER BY photo.captured_at DESC, photo.id DESC
        LIMIT ? OFFSET ?
        """,
        (limit, offset),
    )

    return cur.fetchall()


def count_active_all_stations(conn: sqlite3.Connection) -> int:
    cur = conn.execute(
        "SELECT COUNT(*) AS n FROM photo WHERE removed_at IS NULL"
    )

    return int(cur.fetchone()["n"])


REFERENCE_RECENT_LIMIT = 5


def active_reference_set(conn: sqlite3.Connection, station_slug: str) -> list[Path]:
    """Active reference set — the most-recent N active photo viewer frames.

    Returns filesystem paths the validator can hand straight to OpenCV.
    With references unified into the `photo` table, the admin's seed
    upload is just the chronologically-first row; recent uploads are the
    most-recent rows. Bounded at `REFERENCE_RECENT_LIMIT`.
    """
    paths: list[Path] = []
    recents = recent_active(conn, station_slug, limit=REFERENCE_RECENT_LIMIT)
    for row in recents:
        paths.append(
            storage.local_photo_path(station_slug, row["filename"], "viewer")
        )

    return paths
