"""Photo query helper tests."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

from app import photos


def test_recent_active_orders_by_captured_at_desc(
    db_conn: sqlite3.Connection,
    seeded_stations: list[str],
    insert_photo: Callable[..., int],
) -> None:
    insert_photo("bosque-comestible", "2026-04-01 09:00:00")
    insert_photo("bosque-comestible", "2026-04-03 09:00:00")
    insert_photo("bosque-comestible", "2026-04-02 09:00:00")

    rows = photos.recent_active(db_conn, "bosque-comestible")
    captured = [row["captured_at"] for row in rows]

    assert captured == [
        "2026-04-03 09:00:00",
        "2026-04-02 09:00:00",
        "2026-04-01 09:00:00",
    ]


def test_recent_active_excludes_removed(
    db_conn: sqlite3.Connection,
    seeded_stations: list[str],
    insert_photo: Callable[..., int],
) -> None:
    insert_photo("bosque-comestible", "2026-04-01 09:00:00")
    insert_photo("bosque-comestible", "2026-04-02 09:00:00", removed_at="2026-04-05 12:00:00")
    insert_photo("bosque-comestible", "2026-04-03 09:00:00")

    captured = [row["captured_at"] for row in photos.recent_active(db_conn, "bosque-comestible")]
    assert captured == ["2026-04-03 09:00:00", "2026-04-01 09:00:00"]


def test_recent_active_scopes_to_station(
    db_conn: sqlite3.Connection,
    seeded_stations: list[str],
    insert_photo: Callable[..., int],
) -> None:
    insert_photo("bosque-comestible", "2026-04-01 09:00:00")
    insert_photo("casa-do-pobo", "2026-04-02 09:00:00")

    bc = photos.recent_active(db_conn, "bosque-comestible")
    assert len(bc) == 1
    assert bc[0]["station_slug"] == "bosque-comestible"


def test_recent_active_honours_limit(
    db_conn: sqlite3.Connection,
    seeded_stations: list[str],
    insert_photo: Callable[..., int],
) -> None:
    for i in range(1, 11):
        insert_photo("bosque-comestible", f"2026-04-{i:02d} 09:00:00")

    rows = photos.recent_active(db_conn, "bosque-comestible", limit=3)
    assert len(rows) == 3


def test_most_recent_returns_latest(
    db_conn: sqlite3.Connection,
    seeded_stations: list[str],
    insert_photo: Callable[..., int],
) -> None:
    insert_photo("bosque-comestible", "2026-04-01 09:00:00")
    insert_photo("bosque-comestible", "2026-04-05 09:00:00")
    insert_photo("bosque-comestible", "2026-04-03 09:00:00")

    row = photos.most_recent(db_conn, "bosque-comestible")
    assert row is not None
    assert row["captured_at"] == "2026-04-05 09:00:00"


def test_most_recent_returns_none_when_empty(
    db_conn: sqlite3.Connection, seeded_stations: list[str]
) -> None:
    assert photos.most_recent(db_conn, "bosque-comestible") is None


def test_count_active_excludes_removed(
    db_conn: sqlite3.Connection,
    seeded_stations: list[str],
    insert_photo: Callable[..., int],
) -> None:
    insert_photo("bosque-comestible", "2026-04-01 09:00:00")
    insert_photo("bosque-comestible", "2026-04-02 09:00:00", removed_at="2026-04-05 12:00:00")
    insert_photo("bosque-comestible", "2026-04-03 09:00:00")

    assert photos.count_active(db_conn, "bosque-comestible") == 2


def test_active_reference_set_returns_recent_photo_paths(
    db_conn: sqlite3.Connection,
    seeded_stations: list[str],
    insert_photo: Callable[..., int],
) -> None:
    for i in range(1, 8):
        insert_photo("bosque-comestible", f"2026-04-{i:02d} 09:00:00")

    refs = photos.active_reference_set(db_conn, "bosque-comestible")

    # Up to 5 most-recent viewer paths.
    assert len(refs) == 5
    for path in refs:
        assert "/photos/bosque-comestible/viewer/" in str(path)


def test_active_reference_set_empty_when_no_photos(
    db_conn: sqlite3.Connection, seeded_stations: list[str]
) -> None:
    assert photos.active_reference_set(db_conn, "ies-ponte-caldelas") == []


def test_all_active_chronological_orders_oldest_first(
    db_conn: sqlite3.Connection,
    seeded_stations: list[str],
    insert_photo: Callable[..., int],
) -> None:
    insert_photo("bosque-comestible", "2026-04-03 09:00:00")
    insert_photo("bosque-comestible", "2026-04-01 09:00:00")
    insert_photo("bosque-comestible", "2026-04-02 09:00:00")

    captured = [
        row["captured_at"]
        for row in photos.all_active_chronological(db_conn, "bosque-comestible")
    ]
    # Viewer playback order: oldest → newest (opposite of `recent_active`).
    assert captured == [
        "2026-04-01 09:00:00",
        "2026-04-02 09:00:00",
        "2026-04-03 09:00:00",
    ]


def test_all_active_chronological_excludes_removed(
    db_conn: sqlite3.Connection,
    seeded_stations: list[str],
    insert_photo: Callable[..., int],
) -> None:
    insert_photo("bosque-comestible", "2026-04-01 09:00:00")
    insert_photo(
        "bosque-comestible", "2026-04-02 09:00:00", removed_at="2026-04-05 12:00:00"
    )

    rows = photos.all_active_chronological(db_conn, "bosque-comestible")
    assert [row["captured_at"] for row in rows] == ["2026-04-01 09:00:00"]


def test_count_active_all_stations_sums_and_excludes_removed(
    db_conn: sqlite3.Connection,
    seeded_stations: list[str],
    insert_photo: Callable[..., int],
) -> None:
    insert_photo("bosque-comestible", "2026-04-01 09:00:00")
    insert_photo("casa-do-pobo", "2026-04-02 09:00:00")
    insert_photo(
        "casa-do-pobo", "2026-04-03 09:00:00", removed_at="2026-04-05 12:00:00"
    )

    # Two active across two stations; the removed one is not counted.
    assert photos.count_active_all_stations(db_conn) == 2
