"""Location and station seed loader.

Reads `{data_root}/stations.toml` and upserts each `[[locations]]` and
`[[stations]]` entry. Idempotent — re-running picks up edited copy without
duplicating rows. The seed file is a bootstrap / fork convenience; once a
deployment is live, locations and stations are managed through the admin UI.

CLI: `python -m app.seed`. Implicitly calls `db.init()` first so a fresh
checkout boots with one command. The on-disk layout per §7.3 is created or
verified on every run.
"""

from __future__ import annotations

import sqlite3
import sys
import tomllib
from pathlib import Path
from typing import Any

from app import config, countries, db, storage


SEED_FILENAME = "stations.toml"

VALID_STATUSES: frozenset[str] = frozenset({"draft", "active", "archived"})

LOCATION_REQUIRED_FIELDS: tuple[str, ...] = ("slug", "name")

STATION_REQUIRED_FIELDS: tuple[str, ...] = (
    "slug",
    "name_es",
    "name_en",
    "location",
    "story_es",
    "story_en",
)


def seed_path() -> Path:
    return config.settings.data_root / SEED_FILENAME


def _clean_locations(raw: list[Any], target: Path) -> list[dict[str, Any]]:
    seen: set[str] = set()
    cleaned: list[dict[str, Any]] = []
    for entry in raw:
        for field in LOCATION_REQUIRED_FIELDS:
            if field not in entry or entry[field] in (None, ""):
                raise ValueError(
                    f"{target}: location entry missing required field {field!r}"
                )
        slug = entry["slug"]
        if slug in seen:
            raise ValueError(f"{target}: duplicate location slug {slug!r}")
        seen.add(slug)
        cleaned.append(
            {
                "slug": slug,
                "name": entry["name"].strip(),
                "country": countries.normalise_country(entry.get("country")),
            }
        )

    return cleaned


def _clean_stations(
    raw: list[Any], location_slugs: set[str], target: Path
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    cleaned: list[dict[str, Any]] = []
    for entry in raw:
        for field in STATION_REQUIRED_FIELDS:
            if field not in entry or entry[field] in (None, ""):
                raise ValueError(
                    f"{target}: station entry missing required field {field!r}"
                )

        slug = entry["slug"]
        if slug in seen:
            raise ValueError(f"{target}: duplicate station slug {slug!r}")
        seen.add(slug)

        location_slug = entry["location"]
        if location_slug not in location_slugs:
            raise ValueError(
                f"{target}: station {slug!r} references unknown location "
                f"{location_slug!r}"
            )

        status = (entry.get("status") or "active").strip() or "active"
        if status not in VALID_STATUSES:
            raise ValueError(
                f"{target}: station {slug!r} has invalid status {status!r}"
            )

        cleaned.append(
            {
                "slug": slug,
                "name_es": entry["name_es"].strip(),
                "name_en": entry["name_en"].strip(),
                "location_slug": location_slug,
                "story_es": entry["story_es"].strip(),
                "story_en": entry["story_en"].strip(),
                "latitude": entry.get("latitude"),
                "longitude": entry.get("longitude"),
                "contact_name": (entry.get("contact_name") or "").strip() or None,
                "contact_email": (entry.get("contact_email") or "").strip() or None,
                "status": status,
            }
        )

    return cleaned


def load_seed_config(path: Path | None = None) -> dict[str, list[dict[str, Any]]]:
    """Read and validate the seed TOML.

    Returns `{"locations": [...], "stations": [...]}`. Each station's
    `location_slug` is checked against the declared locations.
    """
    target = path or seed_path()
    if not target.is_file():
        raise FileNotFoundError(f"seed config not found at {target}")

    with target.open("rb") as fh:
        raw = tomllib.load(fh)

    raw_locations = raw.get("locations")
    if not isinstance(raw_locations, list) or not raw_locations:
        raise ValueError(f"{target}: expected a non-empty [[locations]] array")

    raw_stations = raw.get("stations")
    if not isinstance(raw_stations, list) or not raw_stations:
        raise ValueError(f"{target}: expected a non-empty [[stations]] array")

    locations = _clean_locations(raw_locations, target)
    stations = _clean_stations(
        raw_stations, {loc["slug"] for loc in locations}, target
    )

    return {"locations": locations, "stations": stations}


LOCATION_UPSERT_SQL = """
INSERT INTO location (slug, name, country)
VALUES (:slug, :name, :country)
ON CONFLICT(slug) DO UPDATE SET
    name    = excluded.name,
    country = excluded.country
"""


STATION_UPSERT_SQL = """
INSERT INTO station (
    slug, name_es, name_en, location_slug,
    story_es, story_en,
    latitude, longitude,
    contact_name, contact_email,
    status
) VALUES (
    :slug, :name_es, :name_en, :location_slug,
    :story_es, :story_en,
    :latitude, :longitude,
    :contact_name, :contact_email,
    :status
)
ON CONFLICT(slug) DO UPDATE SET
    name_es           = excluded.name_es,
    name_en           = excluded.name_en,
    location_slug     = excluded.location_slug,
    story_es          = excluded.story_es,
    story_en          = excluded.story_en,
    latitude          = excluded.latitude,
    longitude         = excluded.longitude,
    contact_name      = excluded.contact_name,
    contact_email     = excluded.contact_email,
    status            = excluded.status
"""


def apply(
    conn: sqlite3.Connection, seed_config: dict[str, list[dict[str, Any]]]
) -> None:
    """Upsert locations then stations. Caller owns the connection."""
    conn.execute("BEGIN")
    try:
        for location in seed_config["locations"]:
            conn.execute(LOCATION_UPSERT_SQL, location)
        for station in seed_config["stations"]:
            conn.execute(STATION_UPSERT_SQL, station)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def run(seed_file: Path | None = None) -> list[str]:
    """End-to-end: init schema, load config, ensure layout, apply seeds.

    Returns the list of station slugs applied. Safe to re-run.
    """
    db.init()
    seed_config = load_seed_config(seed_file)
    slugs = [s["slug"] for s in seed_config["stations"]]
    storage.ensure_storage_layout(slugs)

    conn = db.connect()
    try:
        apply(conn, seed_config)
    finally:
        conn.close()

    return slugs


def _cli(argv: list[str]) -> int:
    if argv:
        print("usage: python -m app.seed", file=sys.stderr)
        return 2
    slugs = run()
    print(f"Seeded {len(slugs)} station(s): {', '.join(slugs)}")
    print(f"DB:   {db.db_path()}")
    print(f"Data: {config.settings.data_root}")

    return 0


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
