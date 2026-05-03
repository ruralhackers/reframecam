"""Phase 3 — timelapse viewer rendering.

Covers the three viewer states (empty / single / full), the JSON payload
`static/js/viewer.js` reads, and the §9.4 aria-label set. Also exercises a
small unit test for scrubber tick positioning so the date-offset geometry
stays correct.

The latest reference photo becomes frame[0] of the timelapse, so a station
with 1 reference + 0 uploads renders in single mode (reference-only) and
1 reference + 1 upload renders in full mode (2 frames, controls visible).
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
from collections.abc import Callable

from fastapi.testclient import TestClient

from app import views
from app.main import app


client = TestClient(app, follow_redirects=False)


def _payload(body: str) -> dict:
    """Extract and parse the viewer's inline JSON payload."""
    match = re.search(
        r'<script type="application/json" data-viewer-payload>(.*?)</script>',
        body,
        re.DOTALL,
    )
    assert match, "viewer JSON payload not found in body"

    return json.loads(match.group(1))


# ---------------------------------------------------------------------------
# Cold-start state coverage
# ---------------------------------------------------------------------------


def test_viewer_empty_for_zero_photos(seeded_stations: list[str]) -> None:
    body = client.get("/es/anceu/bosque-comestible").text
    # Empty viewer frame renders, but with no payload + no controls + no
    # step buttons. The empty-state caption sits where the indicator would.
    assert "viewer--empty" in body
    assert "data-viewer-payload" not in body
    assert "viewer__controls" not in body
    assert "data-viewer-prev" not in body
    assert "data-viewer-next" not in body
    assert "Aún no hay fotos" in body


def test_viewer_single_for_one_photo(
    seeded_stations: list[str],
    insert_photo: Callable[..., int],
) -> None:
    insert_photo(
        "casa-do-pobo",
        "2026-04-10 09:00:00",
        filename="only.jpg",
    )

    body = client.get("/es/anceu/casa-do-pobo").text
    assert "data-viewer-payload" in body
    assert "viewer--single" in body
    # Controls DOM is always rendered when mode != empty so viewer.js can
    # reveal them on dynamic append; CSS hides them in single mode.
    assert "viewer__controls" in body
    assert "data-viewer-prev" in body
    assert "data-viewer-next" in body
    assert "data-viewer-play" in body
    assert "data-viewer-scrubber" in body
    # The SR-only live region still carries "Foto 1 de 1" for the one frame.
    assert "Foto 1 de 1" in body


def test_viewer_full_for_two_or_more_photos(
    seeded_stations: list[str],
    insert_photo: Callable[..., int],
) -> None:
    # Two uploads (and no references) — the second photo crosses the
    # frames.length >= 2 threshold so the viewer renders in full mode.
    insert_photo("casa-do-pobo", "2026-03-01 09:00:00", filename="a.jpg")
    insert_photo("casa-do-pobo", "2026-04-01 09:00:00", filename="b.jpg")

    body = client.get("/en/anceu/casa-do-pobo").text
    assert "viewer--full" in body
    assert "data-viewer-play" in body
    assert "data-viewer-scrubber" in body
    assert "data-viewer-speed" in body


def test_viewer_full_for_three_or_more_photos(
    seeded_stations: list[str],
    insert_photo: Callable[..., int],
) -> None:
    insert_photo("ies-ponte-caldelas", "2026-01-15 09:00:00", filename="a.jpg")
    insert_photo("ies-ponte-caldelas", "2026-02-15 09:00:00", filename="b.jpg")
    insert_photo("ies-ponte-caldelas", "2026-03-15 09:00:00", filename="c.jpg")

    body = client.get("/es/ponte-caldelas/ies-ponte-caldelas").text
    assert "viewer--full" in body
    assert "data-viewer-play" in body
    assert "data-viewer-scrubber" in body
    assert "data-viewer-speed" in body


def test_viewer_single_for_admin_seed_only(
    seeded_stations: list[str],
    seed_reference_jpeg,
    db_conn: sqlite3.Connection,
) -> None:
    # The admin's seed photo is a `photo` row (planted by the fixture).
    # 1 photo total → single mode.
    seed_reference_jpeg("casa-do-pobo", seed_value=42)

    body = client.get("/es/anceu/casa-do-pobo").text
    assert "viewer--single" in body
    assert "data-viewer-payload" in body
    # The hero <img> is served from /photos/ — references are unified with
    # uploads, no separate /references/ URL exists.
    assert "/photos/casa-do-pobo/viewer/" in body
    assert "/references/" not in body

    row = views.fetch_station(db_conn, "casa-do-pobo")
    assert row is not None
    model = views.station_view(db_conn, row, "es")
    frames = model["viewer"]["frames"]
    assert len(frames) == 1
    assert frames[0]["index"] == 0
    assert frames[0]["viewer_url"].startswith("/photos/casa-do-pobo/viewer/")


def test_viewer_full_for_admin_seed_plus_one_upload(
    seeded_stations: list[str],
    seed_reference_jpeg,
    insert_photo: Callable[..., int],
    db_conn: sqlite3.Connection,
) -> None:
    # 1 admin photo + 1 community upload → 2 frames, full mode, controls
    # visible.
    seed_reference_jpeg("casa-do-pobo", seed_value=7)
    insert_photo("casa-do-pobo", "2026-04-10 09:00:00", filename="up1.jpg")

    body = client.get("/es/anceu/casa-do-pobo").text
    assert "viewer--full" in body
    assert "data-viewer-scrubber" in body

    row = views.fetch_station(db_conn, "casa-do-pobo")
    assert row is not None
    model = views.station_view(db_conn, row, "es")
    frames = model["viewer"]["frames"]
    assert len(frames) == 2
    # Both frames are /photos/ URLs — references are unified with uploads.
    assert frames[0]["viewer_url"].startswith("/photos/casa-do-pobo/viewer/")
    assert frames[1]["viewer_url"].startswith("/photos/casa-do-pobo/viewer/")


# ---------------------------------------------------------------------------
# Inline JSON payload
# ---------------------------------------------------------------------------


def test_viewer_payload_orders_frames_oldest_to_newest(
    seeded_stations: list[str],
    insert_photo: Callable[..., int],
) -> None:
    insert_photo("ies-ponte-caldelas", "2026-03-01 09:00:00", filename="b.jpg")
    insert_photo("ies-ponte-caldelas", "2026-01-01 09:00:00", filename="a.jpg")
    insert_photo("ies-ponte-caldelas", "2026-05-01 09:00:00", filename="c.jpg")

    body = client.get("/es/ponte-caldelas/ies-ponte-caldelas").text
    payload = _payload(body)
    filenames = [
        f["viewer_url"].rsplit("/", 1)[-1] for f in payload["frames"]
    ]
    assert filenames == ["a.jpg", "b.jpg", "c.jpg"]


def test_viewer_payload_carries_date_overlay_and_sr_label(
    seeded_stations: list[str],
    insert_photo: Callable[..., int],
) -> None:
    insert_photo("ies-ponte-caldelas", "2026-03-12 09:00:00", filename="x.jpg")
    insert_photo("ies-ponte-caldelas", "2026-04-13 09:00:00", filename="y.jpg")
    insert_photo("ies-ponte-caldelas", "2026-05-14 09:00:00", filename="z.jpg")

    body_es = client.get("/es/ponte-caldelas/ies-ponte-caldelas").text
    payload_es = _payload(body_es)
    first_es = payload_es["frames"][0]
    assert first_es["date_overlay"] == "12/03/2026"
    assert first_es["sr_label"] == "Foto del 12 de marzo de 2026"

    body_en = client.get("/en/ponte-caldelas/ies-ponte-caldelas").text
    payload_en = _payload(body_en)
    first_en = payload_en["frames"][0]
    assert first_en["date_overlay"] == "12/03/2026"
    assert first_en["sr_label"] == "Photo from 12 March 2026"


def test_viewer_payload_includes_localised_month_abbr(
    seeded_stations: list[str],
    insert_photo: Callable[..., int],
) -> None:
    for d in ("2026-01-01", "2026-02-01", "2026-03-01"):
        insert_photo("ies-ponte-caldelas", f"{d} 09:00:00")

    payload_es = _payload(client.get("/es/ponte-caldelas/ies-ponte-caldelas").text)
    payload_en = _payload(client.get("/en/ponte-caldelas/ies-ponte-caldelas").text)
    assert payload_es["monthAbbr"][0] == "ene"
    assert payload_en["monthAbbr"][0] == "jan"
    # All twelve are present.
    assert len(payload_es["monthAbbr"]) == 12
    assert len(payload_en["monthAbbr"]) == 12


# ---------------------------------------------------------------------------
# Aria-labels (spec §9.4)
# ---------------------------------------------------------------------------


def test_viewer_aria_labels_es(
    seeded_stations: list[str],
    insert_photo: Callable[..., int],
) -> None:
    for d in ("2026-01-01", "2026-02-01", "2026-03-01"):
        insert_photo("ies-ponte-caldelas", f"{d} 09:00:00")

    body = client.get("/es/ponte-caldelas/ies-ponte-caldelas").text
    assert 'aria-label="Reproducir"' in body
    assert 'aria-label="Foto anterior"' in body
    assert 'aria-label="Foto siguiente"' in body
    assert 'aria-label="Línea de tiempo"' in body
    assert 'aria-label="Velocidad"' in body


def test_viewer_aria_labels_en(
    seeded_stations: list[str],
    insert_photo: Callable[..., int],
) -> None:
    for d in ("2026-01-01", "2026-02-01", "2026-03-01"):
        insert_photo("ies-ponte-caldelas", f"{d} 09:00:00")

    body = client.get("/en/ponte-caldelas/ies-ponte-caldelas").text
    assert 'aria-label="Play"' in body
    assert 'aria-label="Previous photo"' in body
    assert 'aria-label="Next photo"' in body
    assert 'aria-label="Timeline"' in body
    assert 'aria-label="Speed"' in body


def test_viewer_live_region_seeded_with_latest_frame(
    seeded_stations: list[str],
    insert_photo: Callable[..., int],
) -> None:
    insert_photo("ies-ponte-caldelas", "2026-03-12 09:00:00")
    insert_photo("ies-ponte-caldelas", "2026-04-15 09:00:00")
    insert_photo("ies-ponte-caldelas", "2026-05-20 09:00:00")

    body = client.get("/es/ponte-caldelas/ies-ponte-caldelas").text
    # The live region opens with the latest frame's longform date.
    assert 'aria-live="polite"' in body
    assert "Foto del 20 de mayo de 2026" in body


# ---------------------------------------------------------------------------
# View-model unit tests (no HTTP layer)
# ---------------------------------------------------------------------------


def test_viewer_view_returns_empty_mode_for_zero_photos(
    seeded_stations: list[str], db_conn: sqlite3.Connection
) -> None:
    row = views.fetch_station(db_conn, "bosque-comestible")
    assert row is not None
    model = views.station_view(db_conn, row, "es")
    viewer = model["viewer"]
    assert viewer is not None
    assert viewer["mode"] == "empty"
    assert viewer["frames"] == []
    assert viewer["empty_caption"] == "Aún no hay fotos"
    assert viewer["payload"] is None


def test_viewer_frame_positions_match_real_time_offsets(
    seeded_stations: list[str],
    insert_photo: Callable[..., int],
    db_conn: sqlite3.Connection,
) -> None:
    """Scrubber geometry sanity check: frames at known timestamps land at the
    expected normalised offsets along the [first, last] range.

    The view-model exposes ISO timestamps; `viewer.js` computes
    (t - first) / (last - first) at render time. We replicate the math here
    to lock the data shape that the JS depends on.
    """
    insert_photo("ies-ponte-caldelas", "2026-01-01 00:00:00", filename="a.jpg")
    insert_photo("ies-ponte-caldelas", "2026-04-01 00:00:00", filename="b.jpg")
    insert_photo("ies-ponte-caldelas", "2026-07-01 00:00:00", filename="c.jpg")

    row = views.fetch_station(db_conn, "ies-ponte-caldelas")
    assert row is not None
    model = views.station_view(db_conn, row, "es")
    frames = model["viewer"]["frames"]
    times = [dt.datetime.fromisoformat(f["captured_at"]) for f in frames]
    span = (times[-1] - times[0]).total_seconds()
    offsets = [(t - times[0]).total_seconds() / span for t in times]
    # First and last anchor at 0 and 1; the April photo sits ~halfway.
    assert offsets[0] == 0.0
    assert offsets[-1] == 1.0
    assert 0.45 < offsets[1] < 0.55
