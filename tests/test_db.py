"""Schema and migration tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app import db


def test_init_creates_tables_and_indexes(data_root: Path) -> None:
    db.init()
    conn = db.connect()
    try:
        names = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','index')"
            )
        }
    finally:
        conn.close()

    assert {
        "location",
        "station",
        "photo",
        "setting",
        "photo_station_captured",
        "photo_active",
    } <= names


def test_drone_and_place_columns_dropped(data_root: Path) -> None:
    db.init()
    conn = db.connect()
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(station)")}
    finally:
        conn.close()

    assert {"location_slug", "latitude", "longitude", "status"} <= cols
    assert "drone_video_url" not in cols
    assert "drone_video_thumb" not in cols
    assert "place_name" not in cols
    assert "is_featured" not in cols


def test_init_is_idempotent(data_root: Path) -> None:
    db.init()
    db.init()
    db.init()  # third pass for confidence


def test_foreign_key_enforcement(data_root: Path) -> None:
    db.init()
    conn = db.connect()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO photo (
                    station_slug, captured_at, client_token, filename,
                    viewer_path, thumb_path, width, height
                ) VALUES (
                    'nonexistent-station', '2026-04-01 09:00:00', 't', 'x.jpg',
                    'b', 'c', 1200, 900
                )
                """
            )
    finally:
        conn.close()


def test_country_codes_migrate_from_legacy_names(data_root: Path) -> None:
    """A row stored with the pre-migration free-text name flips to an ISO code."""
    db.init()
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO location (slug, name, country) VALUES (?, ?, ?)",
            ("legacy", "Legacy", "Spain"),
        )
        conn.execute(
            "INSERT INTO location (slug, name, country) VALUES (?, ?, ?)",
            ("already-coded", "Already Coded", "PT"),
        )
        conn.execute(
            "INSERT INTO location (slug, name, country) VALUES (?, ?, ?)",
            ("unknown", "Unknown", "Atlantis"),
        )
    finally:
        conn.close()

    # Re-running init() picks up the legacy row + leaves the others alone.
    db.init()
    conn = db.connect()
    try:
        rows = {
            r["slug"]: r["country"]
            for r in conn.execute("SELECT slug, country FROM location")
        }
    finally:
        conn.close()

    assert rows["legacy"] == "ES"
    assert rows["already-coded"] == "PT"
    assert rows["unknown"] == "Atlantis"


def test_client_token_unique(data_root: Path) -> None:
    db.init()
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO station (slug, name_es, name_en, "
            "story_es, story_en) "
            "VALUES ('s', 'S', 'S', '.', '.')"
        )
        conn.execute(
            """
            INSERT INTO photo (
                station_slug, captured_at, client_token, filename,
                viewer_path, thumb_path, width, height
            ) VALUES ('s', '2026-04-01 09:00:00', 'dup', 'a.jpg',
                      'b', 'c', 1200, 900)
            """
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO photo (
                    station_slug, captured_at, client_token, filename,
                    viewer_path, thumb_path, width, height
                ) VALUES ('s', '2026-04-01 10:00:00', 'dup', 'b.jpg',
                          'b', 'c', 1200, 900)
                """
            )
    finally:
        conn.close()
