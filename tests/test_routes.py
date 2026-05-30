"""Phase 2 — landing and station route rendering.

Asserts the public read paths cover both languages, render the chrome
correctly, and switch between the empty-state cold-start (§5.6 / §9.4)
and the with-photos state.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app, follow_redirects=False)


# ---------------------------------------------------------------------------
# Landing
# ---------------------------------------------------------------------------


def test_landing_es_renders_marketing_sections(
    seeded_stations: list[str],
) -> None:
    resp = client.get("/es/")

    assert resp.status_code == 200
    body = resp.text
    assert '<html lang="es">' in body
    # 1 — hero: badge + tagline.
    assert "EST. GALICIA 2024" in body
    assert "Regeneración rural a través del ojo de la comunidad." in body
    # 2 — intro section: "¿Qué es ReFrame?" plain-language explainer.
    assert "EL PROYECTO" in body
    assert "¿Qué es ReFrame?" in body
    assert ">Rural Hackers</a> de Anceu, Galicia" in body
    assert 'href="https://ruralhackers.com"' in body
    # 3 — about section: label + heading (no /about link in the nav anymore).
    assert "RAÍCES COMUNES" in body
    assert "Donde el patrimonio humano se encuentra con el renacer natural." in body
    # 4 — quote + attribution.
    assert "Llegar al lugar de partida y conocerlo por primera vez" in body
    assert "T.S. Eliot" in body
    # 5 — locations section: label + heading + "see all" CTA + featured cards.
    assert "LA RED" in body
    assert "Nuestro primer capítulo" in body
    assert "VER TODOS LOS LUGARES" in body
    assert "Bosque Comestible" in body
    assert "Casa do Pobo de Anceu" in body
    assert "IES Ponte Caldelas" in body
    assert 'href="/es/lugares"' in body
    # 6 — setup section.
    assert "LA SEMILLA" in body
    assert "Lleva ReFrame a tu comunidad." in body
    # Submissions enabled → "Host a location" button links to the localised form.
    assert 'href="/es/acoger"' in body
    # No /about anywhere — the /about page was removed.
    assert 'href="/es/sobre"' not in body
    assert 'href="/en/about"' not in body
    # Nav links.
    assert ">Lugares</a>" in body


def test_landing_en_renders_marketing_sections(
    seeded_stations: list[str],
) -> None:
    resp = client.get("/en/")

    assert resp.status_code == 200
    body = resp.text
    assert '<html lang="en">' in body
    assert "EST. GALICIA 2024" in body
    assert "Rural regeneration through the lens of community." in body
    assert "THE PROJECT" in body
    assert "What is ReFrame?" in body
    assert ">Rural Hackers</a> of Anceu, Galicia" in body
    assert 'href="https://ruralhackers.com"' in body
    assert "SHARED ROOTS" in body
    assert "Where human heritage meets natural regrowth." in body
    assert "To arrive where we started and know the place for the first time" in body
    assert "THE NETWORK" in body
    assert "Our First Chapter" in body
    assert "EXPLORE ALL LOCATIONS" in body
    assert "Anceu Food Forest" in body
    assert 'href="/en/locations"' in body
    assert "THE SEED" in body
    assert "Bring ReFrame to your community." in body
    assert 'href="/en/host"' in body
    # No /about anywhere.
    assert 'href="/en/about"' not in body
    assert ">Locations</a>" in body


def test_landing_empty_locations_shows_empty_state(
    seeded_stations: list[str],
    db_conn: sqlite3.Connection,
) -> None:
    # Archive every station — the hardcoded homepage slugs drop out of
    # `fetch_public_stations` (active-only) and the cards collapse to the
    # empty-state copy a fresh fork would see.
    db_conn.execute("UPDATE station SET status = 'archived'")

    body = client.get("/en/").text
    assert "No locations yet. Check back soon." in body
    assert "home-locations__cards" not in body


def test_landing_cards_render_in_hardcoded_order(
    seeded_stations: list[str],
) -> None:
    # `HOMEPAGE_FEATURED_SLUGS` is `(casa-do-pobo, ies-ponte-caldelas,
    # bosque-comestible)`; the cards must appear in that order regardless of
    # the slug-alphabetical SQL ordering.
    body = client.get("/en/").text
    casa = body.index("Casa do Pobo de Anceu")
    ies = body.index("IES Ponte Caldelas")
    bosque = body.index("Anceu Food Forest")
    assert casa < ies < bosque


def test_landing_no_photo_renders_no_thumb(
    seeded_stations: list[str],
) -> None:
    body = client.get("/es/").text
    # Featured cards with no photos render no <img> — the home-location-card
    # partial gates on has_photos.
    assert "home-location-card__image" not in body


def test_landing_with_photo_uses_thumb_url(
    seeded_stations: list[str],
    insert_photo: Callable[..., int],
) -> None:
    insert_photo(
        "casa-do-pobo",
        "2026-04-10 09:00:00",
        filename="recent.jpg",
    )

    resp = client.get("/es/")
    body = resp.text
    assert "/photos/casa-do-pobo/thumb/recent.jpg" in body


# ---------------------------------------------------------------------------
# Station page — both languages
# ---------------------------------------------------------------------------


def test_station_es_path_renders_full_page(seeded_stations: list[str]) -> None:
    resp = client.get("/es/anceu/bosque-comestible")

    assert resp.status_code == 200
    body = resp.text
    assert '<html lang="es">' in body
    assert "Bosque Comestible" in body
    # Story body (loaded from stations.toml stand-in copy).
    assert "bosque comestible de Anceu" in body
    # Empty state — no uploads, no references either (test fixture). The
    # stats line renders the localised "no photos yet" message.
    assert "Sin fotos todavía." in body
    # Estaciones cercanas — siblings within the configured radius (50 km
    # default). Anceu and Ponte Caldelas seed coords are ~1 km apart, so
    # both appear regardless of location.
    assert "Estaciones cercanas" in body
    assert "Casa do Pobo de Anceu" in body
    assert "IES Ponte Caldelas" in body
    # No references and no uploads → empty mode (caption shown in place of
    # the controls), no payload.
    assert "viewer--empty" in body
    assert "Aún no hay fotos" in body
    assert "data-viewer-payload" not in body
    # Upload anchor (Spanish).
    assert 'id="subir"' in body


def test_station_en_path_renders_full_page(seeded_stations: list[str]) -> None:
    resp = client.get("/en/anceu/bosque-comestible")

    assert resp.status_code == 200
    body = resp.text
    assert '<html lang="en">' in body
    assert "Anceu Food Forest" in body
    assert "Anceu Food Forest is a landscape-regeneration project" in body
    assert "No photos yet." in body
    assert "Nearby stations" in body
    # Upload anchor (English).
    assert 'id="upload"' in body


def test_station_404_for_unknown_slug(seeded_stations: list[str]) -> None:
    resp = client.get("/es/anceu/no-such-station")
    assert resp.status_code == 404


def test_station_404_for_wrong_location_segment(
    seeded_stations: list[str],
) -> None:
    # `bosque-comestible` lives under `anceu`; a URL naming any other
    # location for it 404s so each station has exactly one canonical URL.
    assert client.get("/es/ponte-caldelas/bosque-comestible").status_code == 404
    assert client.get("/es/wrong/bosque-comestible").status_code == 404


def test_station_404_for_disabled_language(seeded_stations: list[str]) -> None:
    # `fr` is not an enabled language.
    assert client.get("/fr/anceu/bosque-comestible").status_code == 404


def test_station_language_toggle_is_path_equivalent(
    seeded_stations: list[str],
) -> None:
    body_es = client.get("/es/anceu/casa-do-pobo").text
    body_en = client.get("/en/anceu/casa-do-pobo").text
    # Each page's language toggle points at the path-equivalent URL in the other language.
    assert 'href="/en/anceu/casa-do-pobo"' in body_es
    assert 'href="/es/anceu/casa-do-pobo"' in body_en


# ---------------------------------------------------------------------------
# Station page — with photos
# ---------------------------------------------------------------------------


def test_station_hero_uses_most_recent_active_photo(
    seeded_stations: list[str],
    insert_photo: Callable[..., int],
) -> None:
    insert_photo("bosque-comestible", "2026-01-01 10:00:00", filename="old.jpg")
    insert_photo("bosque-comestible", "2026-04-01 10:00:00", filename="new.jpg")

    body = client.get("/es/anceu/bosque-comestible").text
    # The hero IS the viewer when photos exist; the viewer's <img src> is the
    # most-recent viewer-size derivative. (`old.jpg` appears as the older
    # frame inside the viewer's JSON payload — see test_station_viewer_*.)
    assert 'src="/photos/bosque-comestible/viewer/new.jpg"' in body
    # Empty-state stats line is gone (we have photos now).
    assert "Sin fotos todavía." not in body
    # Viewer renders (1+ photos state).
    assert 'data-viewer-payload' in body


def test_station_stats_line_uses_first_photo_date(
    seeded_stations: list[str],
    insert_photo: Callable[..., int],
) -> None:
    # Stats line "since {Month} {Year}" is derived from the oldest active
    # photo's captured_at, not from a stored field.
    insert_photo("ies-ponte-caldelas", "2024-09-15 10:00:00")
    insert_photo("ies-ponte-caldelas", "2026-04-01 10:00:00")
    body_es = client.get("/es/ponte-caldelas/ies-ponte-caldelas").text
    body_en = client.get("/en/ponte-caldelas/ies-ponte-caldelas").text
    assert "2 contribuciones desde septiembre de 2024." in body_es
    assert "2 contributions since September 2024." in body_en


def test_station_others_within_radius(
    seeded_stations: list[str],
) -> None:
    body = client.get("/es/anceu/bosque-comestible").text
    # Current station never appears as one of its own nearby cards.
    assert body.count('href="/es/anceu/bosque-comestible"') == 0
    # Both seeded siblings are ~1 km away — well within 50 km.
    assert 'href="/es/anceu/casa-do-pobo"' in body
    assert 'href="/es/ponte-caldelas/ies-ponte-caldelas"' in body


def test_station_others_excludes_out_of_radius(
    seeded_stations: list[str],
    db_conn: sqlite3.Connection,
) -> None:
    # Push one sibling off to the equator. Default radius is 50 km, so it
    # falls out of the list while the in-radius sibling stays.
    db_conn.execute(
        "UPDATE station SET latitude = 0, longitude = 0 "
        "WHERE slug = 'ies-ponte-caldelas'"
    )

    body = client.get("/es/anceu/bosque-comestible").text
    assert 'href="/es/anceu/casa-do-pobo"' in body
    assert 'href="/es/ponte-caldelas/ies-ponte-caldelas"' not in body


def test_station_others_hidden_when_current_has_no_coords(
    seeded_stations: list[str],
    db_conn: sqlite3.Connection,
) -> None:
    # No coordinates → can't compute distance → section hides entirely.
    db_conn.execute(
        "UPDATE station SET latitude = NULL, longitude = NULL "
        "WHERE slug = 'bosque-comestible'"
    )

    body = client.get("/es/anceu/bosque-comestible").text
    assert "Estaciones cercanas" not in body
    assert 'id="otros"' not in body
    assert "station-others" not in body


def test_station_others_hidden_when_no_neighbours_in_radius(
    seeded_stations: list[str],
    db_conn: sqlite3.Connection,
) -> None:
    # Move both siblings far away. Default 50 km radius leaves none.
    db_conn.execute(
        "UPDATE station SET latitude = 0, longitude = 0 "
        "WHERE slug IN ('casa-do-pobo', 'ies-ponte-caldelas')"
    )

    body = client.get("/es/anceu/bosque-comestible").text
    assert "Estaciones cercanas" not in body
    assert 'id="otros"' not in body


def test_station_others_ordered_by_distance(
    seeded_stations: list[str],
    db_conn: sqlite3.Connection,
) -> None:
    # Pin coords so distance ordering is deterministic regardless of seed
    # numerics. Current at (42, -8); near at (42.01, -8) ~1 km; far at
    # (42.3, -8) ~33 km — both within 50 km but in a clear order.
    db_conn.execute(
        "UPDATE station SET latitude = 42.0, longitude = -8.0 "
        "WHERE slug = 'bosque-comestible'"
    )
    db_conn.execute(
        "UPDATE station SET latitude = 42.01, longitude = -8.0 "
        "WHERE slug = 'casa-do-pobo'"
    )
    db_conn.execute(
        "UPDATE station SET latitude = 42.3, longitude = -8.0 "
        "WHERE slug = 'ies-ponte-caldelas'"
    )

    body = client.get("/es/anceu/bosque-comestible").text
    near_pos = body.find('href="/es/anceu/casa-do-pobo"')
    far_pos = body.find('href="/es/ponte-caldelas/ies-ponte-caldelas"')
    assert near_pos != -1 and far_pos != -1
    assert near_pos < far_pos


# ---------------------------------------------------------------------------
# Station page — "abundant brooks" redesign
# ---------------------------------------------------------------------------


def test_station_hero_meta_line(seeded_stations: list[str]) -> None:
    # Mono-caps line under the H1 — uppercase place + country, bullet-joined.
    # Country name is localised: 'ESPAÑA' on /es/, 'SPAIN' on /en/.
    es_body = client.get("/es/anceu/casa-do-pobo").text
    assert 'class="station-hero__meta"' in es_body
    assert "ANCEU" in es_body and "ESPAÑA" in es_body
    assert " • " in es_body

    en_body = client.get("/en/anceu/casa-do-pobo").text
    assert "ANCEU" in en_body and "SPAIN" in en_body


def test_station_others_use_home_location_card(
    seeded_stations: list[str],
) -> None:
    body = client.get("/es/anceu/bosque-comestible").text
    # "Otras estaciones" now uses the same partial as /locations.
    assert "home-location-card" in body
    # Legacy partial is gone.
    assert "location-card__thumb" not in body


# ---------------------------------------------------------------------------
# Page titles (§9.8)
# ---------------------------------------------------------------------------


def test_landing_title(seeded_stations: list[str]) -> None:
    body = client.get("/es/").text
    assert "<title>ReFrame · Regeneración rural a través del ojo de la comunidad</title>" in body


def test_station_title_template(seeded_stations: list[str]) -> None:
    body = client.get("/en/anceu/casa-do-pobo").text
    assert "<title>Casa do Pobo de Anceu · ReFrame</title>" in body
