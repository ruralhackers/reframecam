"""View-model builders for the public templates.

Keeps the Jinja templates "dumb": all DB lookups, language-specific name
selection, photo-URL resolution and date formatting happen here, and
templates just render the resulting dicts.

Naming follows the templates that consume each model — `landing_view`,
`station_view` — so the call site reads naturally.
"""

from __future__ import annotations

import datetime as dt
import math
import sqlite3
from typing import Any

from app import config, countries, photos, storage
from app.strings import MONTH_ABBR, MONTH_NAMES, month_name, t


# ---------------------------------------------------------------------------
# Per-language URL helpers
# ---------------------------------------------------------------------------
#
# A station lives at `/{lang}/{location-slug}/{station-slug}` — the location
# nests the station. URLs are always language-prefixed (English default,
# Spanish optional). Slugs are language-agnostic.


def station_path(lang: str, location_slug: str, station_slug: str) -> str:
    return f"/{lang}/{location_slug}/{station_slug}"


# Standalone pages get localised path segments — `/en/locations` vs
# `/es/lugares` — so each language reads naturally. The Spanish slugs are
# stand-ins pending Rural Hackers sign-off (see the build plan's sign-off
# list); changing one means editing the dict here and the route literals in
# `main.py` that mirror it. The /about page is gone — its content collapsed
# into the homepage About section in the "abundant brooks" redesign.
LOCATIONS_SEGMENT: dict[str, str] = {"en": "locations", "es": "lugares"}
HOST_SEGMENT: dict[str, str] = {"en": "host", "es": "acoger"}


def locations_path(lang: str) -> str:
    return f"/{lang}/{LOCATIONS_SEGMENT.get(lang, LOCATIONS_SEGMENT['en'])}"


def host_path(lang: str) -> str:
    return f"/{lang}/{HOST_SEGMENT.get(lang, HOST_SEGMENT['en'])}"


# Homepage "locations" section: a fixed, editorially-ordered list of station
# slugs. The cards render in this order; slugs missing from the DB or not in
# the `active` status are skipped, so a fresh fork without these slugs gets
# the empty-state copy. A fork that wants different homepage cards edits this
# tuple.
HOMEPAGE_FEATURED_SLUGS: tuple[str, ...] = (
    "casa-do-pobo",
    "ies-ponte-caldelas",
    "bosque-comestible",
)


# Interest checkboxes on the submission form. Keys are the stable checkbox
# `value`s (mapped to email labels in `app.email.INTEREST_LABELS`); the form
# template renders each with `t('host.interest.<key>', lang)`.
SUBMISSION_INTERESTS: tuple[str, ...] = (
    "have_location",
    "can_install",
    "can_print",
    "want_guidance",
    "just_curious",
)


# ---------------------------------------------------------------------------
# Meta / OG context (§9.8, §10.4)
# ---------------------------------------------------------------------------


# Default OG image bundled with the build — used on the landing page and on
# stations that have no photos yet. Stations with at least one active photo
# emit the most recent viewer-size frame instead. Dimensions match the file
# at `static/branding/og-default.jpg` (a fork's swap point).
DEFAULT_OG_IMAGE_PATH = "/static/branding/og-default.jpg"
DEFAULT_OG_IMAGE_WIDTH = 1200
DEFAULT_OG_IMAGE_HEIGHT = 630


def _absolute_url(base: str, path: str) -> str:
    """Join a request base URL (e.g. `https://reframe.example/`) with `path`.

    Open Graph scrapers expect absolute URLs for `og:image` and `og:url`.
    Path may be already-absolute (returned unchanged) or root-relative.
    """
    if path.startswith(("http://", "https://")):
        return path

    return base.rstrip("/") + path


# ---------------------------------------------------------------------------
# Station fetchers
# ---------------------------------------------------------------------------


# Every station read joins its location so the view models can surface the
# place line (`location.name`) and country without a second query.
_STATION_SELECT = """
    SELECT station.*,
           location.name    AS location_name,
           location.country AS location_country
    FROM station
    LEFT JOIN location ON location.slug = station.location_slug
"""


def fetch_all_stations(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Every station, any status — for the admin surface."""
    cur = conn.execute(f"{_STATION_SELECT} ORDER BY station.name_en COLLATE NOCASE")

    return cur.fetchall()


def fetch_public_stations(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Active stations only — for public listings, carousels, and the sitemap.

    Draft and archived stations still render at their own URL ("render but
    unlisted") but never appear in a listing.
    """
    cur = conn.execute(
        f"{_STATION_SELECT} WHERE station.status = 'active' ORDER BY station.slug"
    )

    return cur.fetchall()


def fetch_station(conn: sqlite3.Connection, slug: str) -> sqlite3.Row | None:
    cur = conn.execute(f"{_STATION_SELECT} WHERE station.slug = ?", (slug,))

    return cur.fetchone()


def fetch_all_locations(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    cur = conn.execute("SELECT * FROM location ORDER BY name COLLATE NOCASE")

    return cur.fetchall()


def fetch_location(conn: sqlite3.Connection, slug: str) -> sqlite3.Row | None:
    cur = conn.execute("SELECT * FROM location WHERE slug = ?", (slug,))

    return cur.fetchone()


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def _station_display_name(row: sqlite3.Row, lang: str) -> str:
    return row["name_en"] if lang == "en" else row["name_es"]


def _station_story(row: sqlite3.Row, lang: str) -> str:
    return row["story_en"] if lang == "en" else row["story_es"]


def _station_place(row: sqlite3.Row) -> str:
    """The place line beneath the station name — its location's name.

    Place names are not translated (spec §2.3), so this is language-agnostic.
    Falls back to an empty string for a station with no location attached.
    """
    keys = row.keys()
    if "location_name" in keys and row["location_name"]:
        return row["location_name"]

    return ""


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in km between two coordinates."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _stats(
    conn: sqlite3.Connection, row: sqlite3.Row, lang: str, has_photos: bool
) -> dict[str, Any]:
    """Stats line model.

    Returns the formatted `text` plus the structured pieces (`template`,
    `count`, `month`, `year`) so the upload JS can rebuild the text in
    place after a successful community upload — incrementing the count
    without a page refresh.
    """
    if not has_photos:
        return {"text": t("station.stats.empty", lang)}

    slug = row["slug"]
    chronological = photos.all_active_chronological(conn, slug)
    first = _captured_at(chronological[0]["captured_at"])
    count = photos.count_active(conn, slug)
    template = t("station.stats.with_photos", lang)
    month = month_name(lang, first.month)
    year = first.year
    text = template.format(count=count, month=month, year=year)

    return {
        "text": text,
        "template": template,
        "count": count,
        "month": month,
        "year": year,
    }


# ---------------------------------------------------------------------------
# Timelapse viewer (§5.5, §5.6)
# ---------------------------------------------------------------------------
#
# Modes: `empty` when the station has neither references nor uploads (a
# defensive case — active stations always have ≥1 reference); `single` when
# there's exactly one frame (the reference alone, or one upload with no
# reference); `full` when there are ≥2 frames. The latest reference photo
# is permanently frame[0] of the timelapse so cold-start stations still
# show a real photo. The view-model is shaped so the template renders dumb
# HTML and the JS reads a single `<script type=
# "application/json">` blob to wire up controls.

def _captured_at(value: object) -> dt.datetime:
    """Coerce the DB value for `photo.captured_at` to a `datetime`.

    With `PARSE_DECLTYPES` enabled (see `app/db.connect`), DATETIME columns
    round-trip as `datetime.datetime` already. The `isinstance(value, str)`
    branch covers fixture rows inserted with raw ISO strings.
    """
    if isinstance(value, dt.datetime):
        return value
    if isinstance(value, dt.date):
        return dt.datetime(value.year, value.month, value.day)

    return dt.datetime.fromisoformat(str(value))


def _frame_date_overlay(captured: dt.datetime) -> str:
    """Format the always-visible overlay (numeric, both languages, §5.5.6)."""
    return f"{captured.day:02d}/{captured.month:02d}/{captured.year:04d}"


def _frame_sr_label(captured: dt.datetime, lang: str) -> str:
    """Longform date for the screen-reader-only aria-live text (§9.4)."""
    return t("viewer.sr.date_template", lang).format(
        day=captured.day,
        month=month_name(lang, captured.month),
        year=captured.year,
    )


def _viewer_frames(
    rows: list[sqlite3.Row], slug: str, lang: str
) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        captured = _captured_at(row["captured_at"])
        frames.append(
            {
                "index": index,
                "captured_at": captured.isoformat(),
                "viewer_url": storage.photo_url(slug, row["filename"], "viewer"),
                "thumb_url": storage.photo_url(slug, row["filename"], "thumb"),
                "date_overlay": _frame_date_overlay(captured),
                "sr_label": _frame_sr_label(captured, lang),
            }
        )

    return frames


def _viewer_view(
    conn: sqlite3.Connection, row: sqlite3.Row, lang: str
) -> dict[str, Any]:
    """Build the viewer model. Always returns a dict; `mode` distinguishes
    `empty` / `single` / `full`. With references unified into the photo
    table, frames are just all active photos chronologically — the
    admin's seed upload is naturally frame[0]."""
    slug = row["slug"]
    rows = photos.all_active_chronological(conn, slug)

    frame_of_total = t("viewer.frame_of_total", lang)
    aria = {
        "aria_region": t("viewer.aria.region", lang),
        "aria_play": t("viewer.aria.play", lang),
        "aria_pause": t("viewer.aria.pause", lang),
        "aria_prev": t("viewer.aria.prev", lang),
        "aria_next": t("viewer.aria.next", lang),
        "aria_speed": t("viewer.aria.speed", lang),
        "aria_scrubber": t("viewer.aria.scrubber", lang),
    }

    frames = _viewer_frames(rows, slug, lang)

    if not frames:
        return {
            "mode": "empty",
            "frames": [],
            "empty_caption": t("viewer.empty_caption", lang),
            "frame_of_total_template": frame_of_total,
            "payload": None,
            **aria,
        }

    mode = "single" if len(frames) == 1 else "full"
    month_abbr_list = list(MONTH_ABBR.get(lang) or MONTH_ABBR["es"])

    return {
        "mode": mode,
        "frames": frames,
        # Template string with {n} / {total}; the JS interpolates it on each
        # frame change so the announcement stays in sync without a round-trip.
        "frame_of_total_template": frame_of_total,
        # Subset of the model serialised inline as JSON for `viewer.js`.
        # Keeping this as a separate dict keeps the template-side `|tojson`
        # call narrow — only what the JS module actually needs.
        "payload": {
            "mode": mode,
            "frames": frames,
            "monthAbbr": month_abbr_list,
            "frameOfTotalTemplate": frame_of_total,
        },
        **aria,
    }


# ---------------------------------------------------------------------------
# Upload section (§6, §9.5)
# ---------------------------------------------------------------------------
#
# Bilingual anchor id matches the §3.4 QR target. The view model is small —
# the partial composes shells for all six §6.2 states, and the JS module
# transitions between them. Microcopy is resolved here so the template stays
# string-free.

# Failure codes the server returns (§6.5). `network` is generated client-side
# when the XHR errors or stalls; the others come back from the server.
_UPLOAD_FAILURE_CODES: tuple[str, ...] = (
    "wrong_file_type",
    "network",
    "doesnt_match",
    "too_blurry",
    "server_error",
    "too_large",
    "too_small",
    "not_ready",
)


def _upload_view(slug: str, lang: str) -> dict[str, Any]:
    anchor_id = "subir" if lang == "es" else "upload"

    failure_microcopy: dict[str, dict[str, str]] = {}
    for code in _UPLOAD_FAILURE_CODES:
        if code == "server_error":
            entry: dict[str, str] = {
                "body_prefix": t("upload.failure.server_error.body_prefix", lang),
                "body_link": t("upload.failure.server_error.body_link", lang),
                "body_suffix": t("upload.failure.server_error.body_suffix", lang),
                "cta": t(f"upload.failure.{code}.cta", lang),
            }
        else:
            entry = {
                "body": t(f"upload.failure.{code}.body", lang),
                "cta": t(f"upload.failure.{code}.cta", lang),
            }
        failure_microcopy[code] = entry

    # Subset serialised inline as JSON for `static/js/upload.js`. Endpoint URL
    # is fixed on the server side (§6.6) — passing it through the payload
    # keeps the JS module free of route knowledge.
    payload = {
        "endpoint": "/api/upload",
        "stationSlug": slug,
        "lang": lang,
        "uploadingStatusTemplate": t("upload.uploading.status", lang),
        "uploadingPaused": t("upload.uploading.paused", lang),
        "validatingStatus": t("upload.validating.status", lang),
        "validatingSub": t("upload.validating.sub", lang),
        "successHeading": t("upload.success.heading", lang),
        "successBody": t("upload.success.body", lang),
        "viewCta": t("upload.success.view_cta", lang),
        "failures": failure_microcopy,
        "monthNames": list(MONTH_NAMES.get(lang) or MONTH_NAMES["es"]),
        "dateTemplate": "{day} de {month} de {year}" if lang == "es" else "{day} {month} {year}",
        # Hard limit before we even attempt to read the file (§6.4).
        "maxSizeBytes": 30 * 1024 * 1024,
        "maxLongEdge": 2400,
        "jpegQuality": 0.85,
        # Stalled-for-30s = network failure (§6.6).
        "stallTimeoutMs": 30_000,
        # After the bytes are uploaded we wait on the server's validation
        # response. If it never arrives (a server-side hang), abort and surface
        # a network failure rather than spinning on "Checking…" forever.
        "responseTimeoutMs": 60_000,
    }

    return {
        "anchor_id": anchor_id,
        "section_heading": t("upload.section.heading", lang),
        "section_body": t("upload.section.body", lang),
        "section_aria": t("upload.aria.section", lang),
        "picker_cta": t("upload.picker.cta", lang),
        "picker_cta_camera": t("upload.picker.cta_camera", lang),
        "picker_ack": t("upload.picker.ack", lang),
        "picker_ack_link": t("upload.picker.ack_link", lang),
        "picker_ack_close": t("upload.picker.ack_close", lang),
        "picker_panel_body": t("upload.picker.panel_body", lang),
        "preview_heading": t("upload.preview.heading", lang),
        "preview_confirm": t("upload.preview.confirm", lang),
        "preview_change": t("upload.preview.change", lang),
        "preview_no_preview": t("upload.preview.no_preview", lang),
        "validating_status": t("upload.validating.status", lang),
        "validating_sub": t("upload.validating.sub", lang),
        "progress_aria": t("upload.aria.progress", lang),
        "spinner_aria": t("upload.aria.spinner", lang),
        "failures": failure_microcopy,
        "payload": payload,
    }


# ---------------------------------------------------------------------------
# Location-card view (used on landing + Nearby stations)
# ---------------------------------------------------------------------------


def location_card_view(
    conn: sqlite3.Connection, row: sqlite3.Row, lang: str
) -> dict[str, Any]:
    """Build the dict the `home_location_card.html` partial expects.

    Empty-state handling: when a station has no active photos `thumb_url`
    is None and `has_photos` stays False, so the partial hides the <img>
    on a truly photo-less station.
    """
    most = photos.most_recent(conn, row["slug"])
    has_photos = most is not None
    if has_photos:
        thumb_url = storage.photo_url(row["slug"], most["filename"], "thumb")
    else:
        thumb_url = None

    return {
        "slug": row["slug"],
        "name": _station_display_name(row, lang),
        "place": _station_place(row),
        "href": station_path(lang, row["location_slug"], row["slug"]),
        "thumb_url": thumb_url,
        "has_photos": has_photos,
    }


# ---------------------------------------------------------------------------
# Landing
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Admin (§7.5, §9.7) — Spanish-only
# ---------------------------------------------------------------------------

ADMIN_PAGE_SIZE = 20


def _admin_datetime(value: object) -> str:
    """Format `captured_at` for the §9.6 admin row: `dd/mm/yyyy HH:MM` (24h)."""
    captured = _captured_at(value)

    return (
        f"{captured.day:02d}/{captured.month:02d}/{captured.year:04d} "
        f"{captured.hour:02d}:{captured.minute:02d}"
    )


def admin_photos_view(
    conn: sqlite3.Connection, *, page: int, admin_slug: str
) -> dict[str, Any]:
    """Build the model for the admin photo list (§7.5).

    Spanish-only — Rural Hackers' internal language. Pagination is fixed at
    `ADMIN_PAGE_SIZE` rows per page (§7.5: "twenty most recent fit on a screen").
    """
    lang = "es"
    page = max(1, page)
    offset = (page - 1) * ADMIN_PAGE_SIZE

    total = photos.count_active_all_stations(conn)
    rows = photos.admin_list(conn, limit=ADMIN_PAGE_SIZE, offset=offset)

    photo_rows = []
    for row in rows:
        photo_rows.append(
            {
                "id": int(row["id"]),
                "station_slug": row["station_slug"],
                "station_name": row["station_name_es"],
                "thumb_url": storage.photo_url(
                    row["station_slug"], row["filename"], "thumb"
                ),
                "viewer_url": storage.photo_url(
                    row["station_slug"], row["filename"], "viewer"
                ),
                "viewer_width": int(row["width"]),
                "viewer_height": int(row["height"]),
                "captured_at": _admin_datetime(row["captured_at"]),
                "remove_action": f"/admin/{admin_slug}/photo/{int(row['id'])}/remove",
            }
        )

    has_prev = page > 1
    has_next = (offset + len(photo_rows)) < total
    base = f"/admin/{admin_slug}/"
    prev_href = f"{base}?page={page - 1}" if has_prev else None
    next_href = f"{base}?page={page + 1}" if has_next else None

    return {
        "lang": lang,
        "page_title": t("admin.page.title", lang),
        "heading": t("admin.heading", lang),
        "columns": {
            "photo": t("admin.column.photo", lang),
            "place": t("admin.column.place", lang),
            "date": t("admin.column.date", lang),
            "action": t("admin.column.action", lang),
        },
        "thumb_alt": t("admin.thumb_alt", lang),
        "remove_label": t("admin.action.remove", lang),
        "confirm_message": t("admin.confirm.message", lang),
        "confirm_confirm": t("admin.confirm.confirm", lang),
        "confirm_cancel": t("admin.confirm.cancel", lang),
        "removal_reason_label": t("admin.removal_reason.label", lang),
        "empty": t("admin.empty", lang),
        "pagination": {
            "prev_label": t("admin.pagination.previous", lang),
            "next_label": t("admin.pagination.next", lang),
            "prev_href": prev_href,
            "next_href": next_href,
        },
        "photos": photo_rows,
        "page": page,
        "total": total,
    }


# Station lifecycle. A station can only go `active` once it has at least
# one photo — the admin's seed upload (which doubles as the hero's initial
# frame and the validator's feature-match anchor).
STATION_STATUSES: tuple[str, ...] = ("draft", "active", "archived")

# Spanish display labels for the Spanish-only admin. Singular form (one
# estación) for the per-row badge; the stations index groups under plural
# headers built in `admin_stations_view`.
STATION_STATUS_LABELS: dict[str, str] = {
    "draft": "Borrador",
    "active": "Activa",
    "archived": "Archivada",
}


def station_readiness(conn: sqlite3.Connection, slug: str) -> dict[str, Any]:
    """Whether a station is allowed to be `status = 'active'`.

    Needs ≥1 active photo. References are uniform with regular uploads
    (the admin seeds via the admin photo form; subsequent rows are
    community uploads).
    """
    photo_count = photos.count_active(conn, slug)
    missing: list[str] = []
    if photo_count < 1:
        missing.append("photos")

    return {
        "photo_count": photo_count,
        "ready": not missing,
        "missing": missing,
    }


def admin_locations_view(
    conn: sqlite3.Connection, *, admin_slug: str
) -> dict[str, Any]:
    """Model for the admin locations list.

    Location state is *implicit*: a location is "active" if it has ≥1 active
    station, else "inactive". Locations are grouped under Activos / Inactivos
    (empty groups omitted). A location with no stations at all is deletable
    (hard delete); every other location can only be edited.
    """
    rows = fetch_all_locations(conn)
    counts = {
        r["location_slug"]: r["n"]
        for r in conn.execute(
            "SELECT location_slug, COUNT(*) AS n FROM station GROUP BY location_slug"
        )
    }
    active_counts = {
        r["location_slug"]: r["n"]
        for r in conn.execute(
            "SELECT location_slug, COUNT(*) AS n FROM station "
            "WHERE status = 'active' GROUP BY location_slug"
        )
    }

    active: list[dict[str, Any]] = []
    inactive: list[dict[str, Any]] = []
    for r in rows:
        station_count = counts.get(r["slug"], 0)
        is_active = active_counts.get(r["slug"], 0) >= 1
        loc = {
            "slug": r["slug"],
            "name": r["name"],
            "country": r["country"],
            "country_label": countries.country_name(r["country"], "es"),
            "station_count": station_count,
            "is_active": is_active,
            "can_delete": station_count == 0,
            "edit_href": f"/admin/{admin_slug}/locations/{r['slug']}",
            "delete_href": f"/admin/{admin_slug}/locations/{r['slug']}/delete",
        }
        (active if is_active else inactive).append(loc)

    groups = [
        {"key": key, "label": label, "locations": bucket}
        for key, label, bucket in (
            ("active", "Activos", active),
            ("inactive", "Inactivos", inactive),
        )
        if bucket
    ]

    return {"admin_slug": admin_slug, "groups": groups}


# Group headers for the stations index — plural, in fixed lifecycle order.
_STATION_GROUP_LABELS: tuple[tuple[str, str], ...] = (
    ("draft", "Borradores"),
    ("active", "Activas"),
    ("archived", "Archivadas"),
)


def admin_stations_view(
    conn: sqlite3.Connection, *, admin_slug: str
) -> dict[str, Any]:
    """Model for the admin stations list — every station, grouped by status.

    Groups are emitted in `draft → active → archived` order; empty groups are
    omitted so the page only shows headers that have stations under them.
    """
    rows = fetch_all_stations(conn)
    by_status: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_status.setdefault(r["status"], []).append(_admin_station_row(r, admin_slug))

    groups = [
        {"status": status, "label": label, "stations": by_status[status]}
        for status, label in _STATION_GROUP_LABELS
        if by_status.get(status)
    ]

    return {"admin_slug": admin_slug, "groups": groups}


def admin_stations_for_location(
    conn: sqlite3.Connection, *, admin_slug: str, location_slug: str
) -> list[dict[str, Any]]:
    """Admin-shaped station rows filtered to one location.

    Each edit link carries `?from_location=` so the station form knows to send
    the admin back here (rather than the global Stations list) on save / back.
    """
    cur = conn.execute(
        f"{_STATION_SELECT} WHERE station.location_slug = ? ORDER BY station.slug",
        (location_slug,),
    )

    rows = [_admin_station_row(r, admin_slug) for r in cur.fetchall()]
    for row in rows:
        row["edit_href"] += f"?from_location={location_slug}"

    return rows


def _admin_station_row(row: sqlite3.Row, admin_slug: str) -> dict[str, Any]:
    return {
        "slug": row["slug"],
        "name": row["name_en"] or row["name_es"],
        "location_name": _station_place(row) or "—",
        "status": row["status"],
        "status_label": STATION_STATUS_LABELS.get(row["status"], row["status"]),
        "edit_href": f"/admin/{admin_slug}/stations/{row['slug']}",
    }


def admin_station_form_view(
    conn: sqlite3.Connection,
    *,
    admin_slug: str,
    row: sqlite3.Row | None,
    preselected_location_slug: str | None = None,
) -> dict[str, Any]:
    """Model for the create / edit station form.

    `row` is None for the create form, a station row for edit. Carries the
    location options, the current seed references, and the readiness check
    that gates the `active` status. `preselected_location_slug` lets the
    "Añadir estación a este lugar" affordance on the location detail page
    pre-select the location in the dropdown; ignored on the edit form (the
    station's own `location_slug` already wins).
    """
    locations = [
        {"slug": loc["slug"], "name": loc["name"]}
        for loc in fetch_all_locations(conn)
    ]
    is_edit = row is not None
    slug = row["slug"] if is_edit else ""
    readiness = station_readiness(conn, slug) if is_edit else None
    station_photos: list[dict[str, Any]] = []
    if is_edit:
        station_name = row["name_es"] or row["name_en"] or slug
        for r in photos.recent_active(conn, slug, limit=50):
            captured = _captured_at(r["captured_at"])
            station_photos.append({
                "id": int(r["id"]),
                "filename": r["filename"],
                "thumb_url": storage.photo_url(slug, r["filename"], "thumb"),
                "viewer_url": storage.photo_url(slug, r["filename"], "viewer"),
                "viewer_width": int(r["width"]),
                "viewer_height": int(r["height"]),
                "station_name": station_name,
                "captured_at": captured.strftime("%d/%m/%Y %H:%M"),
            })

    known_location_slugs = {loc["slug"] for loc in locations}
    selected_location = (
        preselected_location_slug
        if preselected_location_slug in known_location_slugs
        else None
    )

    return {
        "admin_slug": admin_slug,
        "is_edit": is_edit,
        "locations": locations,
        "selected_location": selected_location,
        "statuses": [
            {"value": st, "label": STATION_STATUS_LABELS.get(st, st)}
            for st in STATION_STATUSES
        ],
        "readiness": readiness,
        "photos": station_photos,
        "station": dict(row) if is_edit else None,
    }


def landing_view(conn: sqlite3.Connection, lang: str) -> dict[str, Any]:
    """Model for the marketing landing page.

    The locations section shows a fixed, editorially-ordered set of stations
    (`HOMEPAGE_FEATURED_SLUGS`). Missing or non-active slugs are skipped, so a
    fresh fork without these slugs gets the empty-state copy.
    """
    by_slug = {r["slug"]: r for r in fetch_public_stations(conn)}
    featured = [
        location_card_view(conn, by_slug[s], lang)
        for s in HOMEPAGE_FEATURED_SLUGS
        if s in by_slug
    ]

    return {
        "featured": featured,
        "locations_href": locations_path(lang),
        "host_href": host_path(lang),
    }


def locations_view(conn: sqlite3.Connection, lang: str) -> dict[str, Any]:
    """Model for the `/locations` page — a map payload plus grouped cards.

    Only active stations appear (draft / archived are render-but-unlisted).
    `markers` carries the subset that has both coordinates set; `countries`
    groups stations as homepage-style card dicts (via `location_card_view`)
    by country → place, each level sorted alphabetically.
    """
    rows = fetch_public_stations(conn)

    by_country: dict[str, dict[str, list[dict[str, Any]]]] = {}
    markers: list[dict[str, Any]] = []
    for row in rows:
        country = countries.country_name(row["location_country"], lang) or "—"
        place = _station_place(row) or "—"
        card = location_card_view(conn, row, lang)
        by_country.setdefault(country, {}).setdefault(place, []).append(card)

        lat, lng = row["latitude"], row["longitude"]
        if lat is not None and lng is not None:
            markers.append(
                {
                    "name": card["name"],
                    "href": card["href"],
                    "place": place,
                    "lat": float(lat),
                    "lng": float(lng),
                }
            )

    country_groups: list[dict[str, Any]] = []
    for country in sorted(by_country):
        places = [
            {
                "name": place,
                "cards": sorted(
                    by_country[country][place], key=lambda c: c["name"]
                ),
            }
            for place in sorted(by_country[country])
        ]
        country_groups.append({"country": country, "locations": places})

    return {
        "countries": country_groups,
        "markers": markers,
        "has_markers": bool(markers),
        "host_href": host_path(lang),
    }


def landing_meta(lang: str, base_url: str) -> dict[str, Any]:
    """Meta / OG context for the landing page (`/{lang}/`)."""
    return {
        "page_title": t("landing.title", lang),
        "meta_description": t("meta.description.landing", lang),
        "canonical_url": _absolute_url(base_url, f"/{lang}/"),
        "og_title": t("landing.title", lang),
        "og_image_url": _absolute_url(base_url, DEFAULT_OG_IMAGE_PATH),
        "og_image_width": DEFAULT_OG_IMAGE_WIDTH,
        "og_image_height": DEFAULT_OG_IMAGE_HEIGHT,
        "og_image_alt": t("meta.description.landing", lang),
        "og_type": "website",
    }


def locations_meta(lang: str, base_url: str) -> dict[str, Any]:
    """Meta / OG context for the `/locations` page."""
    return {
        "page_title": t("locations.title", lang),
        "meta_description": t("locations.meta_description", lang),
        "canonical_url": _absolute_url(base_url, locations_path(lang)),
        "og_title": t("locations.title", lang),
        "og_image_url": _absolute_url(base_url, DEFAULT_OG_IMAGE_PATH),
        "og_image_width": DEFAULT_OG_IMAGE_WIDTH,
        "og_image_height": DEFAULT_OG_IMAGE_HEIGHT,
        "og_image_alt": t("locations.meta_description", lang),
        "og_type": "website",
    }


def host_meta(lang: str, base_url: str) -> dict[str, Any]:
    """Meta / OG context for the `/host` submission form."""
    return {
        "page_title": t("host.title", lang),
        "meta_description": t("host.meta_description", lang),
        "canonical_url": _absolute_url(base_url, host_path(lang)),
        "og_title": t("host.title", lang),
        "og_image_url": _absolute_url(base_url, DEFAULT_OG_IMAGE_PATH),
        "og_image_width": DEFAULT_OG_IMAGE_WIDTH,
        "og_image_height": DEFAULT_OG_IMAGE_HEIGHT,
        "og_image_alt": t("host.meta_description", lang),
        "og_type": "website",
    }


def station_meta(
    station_model: dict[str, Any], lang: str, base_url: str
) -> dict[str, Any]:
    """Meta / OG context for a station page (`/{lang}/<segment>/<slug>`).

    `og:image` is the latest viewer-size frame when the station has photos
    (per §9.8); otherwise we fall back to the bundled default OG image so
    cold-start stations still produce a sensible link preview.
    """
    name = station_model["name"]
    description = t("meta.description.station_template", lang).format(name=name)
    if station_model["has_photos"] and station_model["hero_url"]:
        # Viewer derivatives are 1200px on the long edge with 16:9 framing
        # (§5.5.3 / §8.2). 1200×675 falls just inside OG's preferred ratio
        # (1200×630) — close enough that scrapers don't complain.
        og_image = _absolute_url(base_url, station_model["hero_url"])
        og_width, og_height = 1200, 675
    else:
        og_image = _absolute_url(base_url, DEFAULT_OG_IMAGE_PATH)
        og_width, og_height = DEFAULT_OG_IMAGE_WIDTH, DEFAULT_OG_IMAGE_HEIGHT

    return {
        "page_title": station_model["title"],
        "meta_description": description,
        "canonical_url": _absolute_url(
            base_url,
            station_path(
                lang, station_model["location_slug"], station_model["slug"]
            ),
        ),
        "og_title": station_model["title"],
        "og_image_url": og_image,
        "og_image_width": og_width,
        "og_image_height": og_height,
        "og_image_alt": description,
        "og_type": "article",
    }


# ---------------------------------------------------------------------------
# Station page
# ---------------------------------------------------------------------------


def station_view(
    conn: sqlite3.Connection, row: sqlite3.Row, lang: str
) -> dict[str, Any]:
    """Build the full station-page model: hero, story, stats, reference,
    viewer, upload, and "Nearby stations"."""
    most = photos.most_recent(conn, row["slug"])
    has_photos = most is not None

    if has_photos:
        hero_url = storage.photo_url(row["slug"], most["filename"], "viewer")
    else:
        hero_url = None

    name = _station_display_name(row, lang)
    place = _station_place(row)
    country_code = row["location_country"] if "location_country" in row.keys() else ""
    country = countries.country_name(country_code, lang)

    # Mono-caps line under the H1, e.g. "ANCEU, GALICIA • SPAIN". Place names
    # don't translate (spec §2.3); the country name does — `country_name`
    # resolves the ISO code to the localised label.
    parts = [p for p in (place, country) if p]
    hero_meta = " • ".join(p.upper() for p in parts)

    lat, lng = row["latitude"], row["longitude"]
    if lat is not None and lng is not None:
        map_marker = {
            "name": name,
            "href": station_path(lang, row["location_slug"], row["slug"]),
            "place": place or "",
            "lat": float(lat),
            "lng": float(lng),
        }
    else:
        map_marker = None

    others: list[dict[str, Any]] = []
    if lat is not None and lng is not None:
        radius_km = config.settings.nearby_radius_km
        candidates: list[tuple[float, sqlite3.Row]] = []
        for other in fetch_public_stations(conn):
            if other["slug"] == row["slug"]:
                continue
            olat, olng = other["latitude"], other["longitude"]
            if olat is None or olng is None:
                continue
            distance = _haversine_km(
                float(lat), float(lng), float(olat), float(olng)
            )
            if distance <= radius_km:
                candidates.append((distance, other))
        candidates.sort(key=lambda pair: pair[0])
        others = [location_card_view(conn, other, lang) for _, other in candidates]

    others_heading = t("nearby.heading", lang) if others else ""

    return {
        "slug": row["slug"],
        "location_slug": row["location_slug"],
        "name": name,
        "place": place,
        "story": _station_story(row, lang),
        "hero_url": hero_url,
        "has_photos": has_photos,
        "hero_meta": hero_meta,
        "stats": _stats(conn, row, lang, has_photos),
        "title": t("station.title_template", lang).format(name=name),
        "viewer": _viewer_view(conn, row, lang),
        "upload": _upload_view(row["slug"], lang),
        "others": others,
        "others_heading": others_heading,
        "map_marker": map_marker,
    }
