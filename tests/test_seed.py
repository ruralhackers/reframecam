"""Station seed loader tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from app import db, seed


def test_seed_creates_three_stations(seeded_stations: list[str]) -> None:
    assert sorted(seeded_stations) == [
        "bosque-comestible",
        "casa-do-pobo",
        "ies-ponte-caldelas",
    ]


def test_seed_rows_have_expected_columns(seeded_stations: list[str]) -> None:
    conn = db.connect()
    try:
        rows = {
            row["slug"]: row
            for row in conn.execute("SELECT * FROM station")
        }
        locations = {
            row["slug"]: row for row in conn.execute("SELECT * FROM location")
        }
    finally:
        conn.close()

    bc = rows["bosque-comestible"]
    assert bc["name_es"] == "Bosque Comestible"
    assert bc["name_en"] == "Anceu Food Forest"
    assert bc["location_slug"] == "anceu"
    assert bc["status"] == "active"
    assert bc["latitude"] is not None and bc["longitude"] is not None
    assert bc["story_es"].startswith("El bosque comestible")
    assert bc["story_en"].startswith("The Anceu Food Forest")
    # Seeded stations carry a contact name; the email is left blank for privacy.
    assert bc["contact_name"]
    assert bc["contact_email"] is None

    assert locations["anceu"]["name"] == "Anceu, Galicia"
    assert locations["anceu"]["country"] == "ES"


def test_seed_is_idempotent(seeded_stations: list[str], data_root: Path) -> None:
    seed.run()
    seed.run()
    conn = db.connect()
    try:
        n = conn.execute("SELECT COUNT(*) AS n FROM station").fetchone()["n"]
    finally:
        conn.close()

    assert n == 3


def test_seed_upserts_edited_copy(seeded_stations: list[str], data_root: Path) -> None:
    target = data_root / seed.SEED_FILENAME
    text = target.read_text()
    edited = text.replace("Bosque Comestible", "Bosque Comestible (edit)")
    target.write_text(edited)

    seed.run()

    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT name_es FROM station WHERE slug = ?",
            ("bosque-comestible",),
        ).fetchone()
    finally:
        conn.close()

    assert row["name_es"] == "Bosque Comestible (edit)"


def test_seed_creates_filesystem_layout(seeded_stations: list[str], data_root: Path) -> None:
    for slug in seeded_stations:
        for kind in ("viewer", "thumb"):
            assert (data_root / "photos" / slug / kind).is_dir()


def test_seed_rejects_missing_required_field(data_root: Path) -> None:
    target = data_root / seed.SEED_FILENAME
    target.write_text(
        '[[locations]]\n'
        'slug = "l"\n'
        'name = "L"\n'
        '\n'
        '[[stations]]\n'
        'slug = "x"\n'
        'name_es = "X"\n'
        # missing name_en, location, stories
    )
    db.init()
    with pytest.raises(ValueError, match="missing required field"):
        seed.run()


def test_seed_rejects_duplicate_slug(data_root: Path) -> None:
    target = data_root / seed.SEED_FILENAME
    target.write_text(
        """
[[locations]]
slug = "l"
name = "L"

[[stations]]
slug = "x"
name_es = "X"
name_en = "X"
location = "l"
story_es = "."
story_en = "."

[[stations]]
slug = "x"
name_es = "Y"
name_en = "Y"
location = "l"
story_es = "."
story_en = "."
"""
    )
    db.init()
    with pytest.raises(ValueError, match="duplicate station slug"):
        seed.run()


def test_seed_rejects_unknown_location(data_root: Path) -> None:
    target = data_root / seed.SEED_FILENAME
    target.write_text(
        """
[[locations]]
slug = "l"
name = "L"

[[stations]]
slug = "x"
name_es = "X"
name_en = "X"
location = "nonexistent"
story_es = "."
story_en = "."
"""
    )
    db.init()
    with pytest.raises(ValueError, match="unknown location"):
        seed.run()
