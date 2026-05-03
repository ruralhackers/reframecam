"""Phase 7 — launch readiness.

Covers the public-surface additions from `docs/prompts/phase-7.md`:

- Meta and Open Graph tags on landing + station pages (§9.8).
- Favicon and apple-touch-icon links in the document head.
- `robots.txt` and `sitemap.xml` shape and coverage.
- Themed 404 / 500 pages (§10.4) — bilingual based on the URL path.
- Apache-style request access logging.
- Lang-aware error-page rendering for unknown routes and known-bad slugs.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app, follow_redirects=False)


# ---------------------------------------------------------------------------
# Meta / OG tags (§9.8)
# ---------------------------------------------------------------------------


def test_landing_emits_meta_description_and_og(
    seeded_stations: list[str],
) -> None:
    resp = client.get("/es/")
    assert resp.status_code == 200
    body = resp.text

    assert (
        '<meta name="description" content="Regeneración rural a través del ojo de la comunidad." />'
    ) in body
    assert '<meta property="og:site_name" content="ReFrame" />' in body
    assert '<meta property="og:type" content="website" />' in body
    assert '<meta property="og:locale" content="es_ES" />' in body
    assert (
        '<meta property="og:title" content="ReFrame · Regeneración rural a través del ojo de la comunidad" />'
    ) in body
    # OG URL is absolute (TestClient base is http://testserver/).
    assert (
        '<meta property="og:url" content="http://testserver/es/" />'
    ) in body
    assert (
        '<meta property="og:image" content="http://testserver/static/branding/og-default.jpg" />'
    ) in body
    assert '<meta property="og:image:width" content="1200" />' in body
    assert '<meta property="og:image:height" content="630" />' in body
    assert '<meta name="twitter:card" content="summary_large_image" />' in body
    assert '<link rel="canonical" href="http://testserver/es/" />' in body


def test_landing_en_emits_english_meta(seeded_stations: list[str]) -> None:
    resp = client.get("/en/")
    assert resp.status_code == 200
    body = resp.text

    assert "Rural regeneration through the lens of community." in body
    assert '<meta property="og:locale" content="en_GB" />' in body
    assert "ReFrame · Rural regeneration through the lens of community" in body


def test_station_meta_uses_template_with_name(
    seeded_stations: list[str],
) -> None:
    resp = client.get("/es/anceu/casa-do-pobo")
    assert resp.status_code == 200
    body = resp.text

    # Description templated with the station's localised name (§9.8).
    assert (
        "Mira cómo cambia Casa do Pobo de Anceu a lo largo del tiempo, foto a foto."
    ) in body
    # og:type bumps to article on station pages.
    assert '<meta property="og:type" content="article" />' in body
    assert (
        '<meta property="og:url" content="http://testserver/es/anceu/casa-do-pobo" />'
    ) in body


def test_station_with_photo_uses_viewer_image_for_og(
    seeded_stations: list[str], insert_photo: Callable[..., int]
) -> None:
    insert_photo("casa-do-pobo", "2025-01-15T10:00:00")
    resp = client.get("/es/anceu/casa-do-pobo")
    assert resp.status_code == 200
    body = resp.text

    # Most recent viewer-size frame is the OG image (§9.8 OG row).
    assert "casa-do-pobo/viewer/2025-01-15" in body
    assert '<meta property="og:image:width" content="1200" />' in body
    assert '<meta property="og:image:height" content="675" />' in body


# ---------------------------------------------------------------------------
# Favicon set (§10.4)
# ---------------------------------------------------------------------------


def test_base_emits_favicon_links(seeded_stations: list[str]) -> None:
    resp = client.get("/es/")
    body = resp.text

    assert (
        '<link rel="icon" type="image/svg+xml" href="/static/branding/favicon.svg" />'
    ) in body
    assert (
        '<link rel="icon" type="image/png" sizes="32x32" href="/static/branding/favicon-32.png" />'
    ) in body
    assert (
        '<link rel="apple-touch-icon" sizes="180x180" '
        'href="/static/branding/apple-touch-icon.png" />'
    ) in body
    assert '<link rel="alternate icon" href="/static/branding/favicon.ico" />' in body


def test_favicon_assets_serve_with_correct_content_type(
    seeded_stations: list[str],
) -> None:
    resp = client.get("/static/branding/favicon.svg")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/svg+xml")

    resp = client.get("/static/branding/favicon-32.png")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/png")

    resp = client.get("/static/branding/favicon.ico")
    assert resp.status_code == 200

    resp = client.get("/static/branding/apple-touch-icon.png")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/png")

    resp = client.get("/static/branding/og-default.jpg")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/jpeg")


# ---------------------------------------------------------------------------
# robots.txt and sitemap.xml (§10.4)
# ---------------------------------------------------------------------------


def test_robots_txt_disallows_admin_and_points_at_sitemap(
    seeded_stations: list[str],
) -> None:
    resp = client.get("/robots.txt")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    body = resp.text

    assert "User-agent: *" in body
    assert "Allow: /" in body
    assert "Disallow: /admin/" in body
    assert "Disallow: /api/" in body
    assert "Sitemap: http://testserver/sitemap.xml" in body


def test_sitemap_lists_all_eight_public_urls(seeded_stations: list[str]) -> None:
    resp = client.get("/sitemap.xml")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/xml")
    body = resp.text

    expected_urls = [
        "http://testserver/es/",
        "http://testserver/en/",
        "http://testserver/es/anceu/bosque-comestible",
        "http://testserver/en/anceu/bosque-comestible",
        "http://testserver/es/anceu/casa-do-pobo",
        "http://testserver/en/anceu/casa-do-pobo",
        "http://testserver/es/ponte-caldelas/ies-ponte-caldelas",
        "http://testserver/en/ponte-caldelas/ies-ponte-caldelas",
    ]
    for url in expected_urls:
        assert f"<loc>{url}</loc>" in body
    # hreflang alternates link the bilingual pair on each <url>.
    assert (
        'xhtml:link rel="alternate" hreflang="es" '
        'href="http://testserver/es/anceu/casa-do-pobo"'
    ) in body
    assert (
        'xhtml:link rel="alternate" hreflang="en" '
        'href="http://testserver/en/anceu/casa-do-pobo"'
    ) in body


# ---------------------------------------------------------------------------
# Themed 404 / 500 (§10.4)
# ---------------------------------------------------------------------------


def test_unknown_path_renders_themed_404_in_spanish(
    seeded_stations: list[str],
) -> None:
    resp = client.get("/es/this-does-not-exist")
    assert resp.status_code == 404
    body = resp.text

    assert '<html lang="es">' in body
    assert "Página no encontrada · ReFrame" in body
    assert "No encontramos esta página." in body
    # Section label + oversized status code from the abundant brooks treatment.
    assert "PÁGINA NO ENCONTRADA" in body
    assert 'class="error__code"' in body
    # CTA back to the lang-correct landing.
    assert 'href="/es/"' in body
    # No OG image meta on error pages — they shouldn't appear in link previews.
    assert '<meta property="og:image"' not in body


def test_unknown_path_renders_themed_404_in_english(
    seeded_stations: list[str],
) -> None:
    resp = client.get("/en/missing")
    assert resp.status_code == 404
    body = resp.text

    assert '<html lang="en">' in body
    # Apostrophes are HTML-entity-escaped by Jinja's autoescape ("couldn&#39;t").
    assert "couldn" in body and "find that page" in body
    assert 'href="/en/"' in body
    assert "Page not found" in body
    assert "PAGE NOT FOUND" in body
    assert 'class="error__code"' in body


def test_unknown_station_slug_renders_themed_404(
    seeded_stations: list[str],
) -> None:
    # The station handler raises HTTPException(404) explicitly when the slug
    # is unknown. Exception handler should route to the themed page.
    resp = client.get("/es/anceu/no-such-station")
    assert resp.status_code == 404
    body = resp.text

    assert '<html lang="es">' in body
    assert "No encontramos esta página." in body


def test_root_unknown_path_uses_default_language(
    seeded_stations: list[str],
) -> None:
    # A multi-segment path that doesn't match any route — neither the
    # `/{lang}/` landing nor any station handler — falls back to the default
    # language (English). Single-segment paths trigger FastAPI's trailing-
    # slash redirect into `/{lang}/`; multi-segment ones don't.
    resp = client.get("/no/lang/prefix/here")
    assert resp.status_code == 404
    body = resp.text

    assert '<html lang="en">' in body


def test_unhandled_exception_renders_themed_500(
    seeded_stations: list[str], monkeypatch
) -> None:
    # Force the landing handler to crash by monkeypatching the view-builder.
    from app import views

    def _boom(*_args, **_kwargs):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(views, "landing_view", _boom)
    # TestClient propagates server errors by default; flip raise_server_exceptions
    # off so we see the themed 500 response.
    crash_client = TestClient(app, raise_server_exceptions=False)
    resp = crash_client.get("/es/")

    assert resp.status_code == 500
    body = resp.text
    assert "Algo no fue bien." in body
    assert '<html lang="es">' in body


# ---------------------------------------------------------------------------
# Access log middleware (§10.4)
# ---------------------------------------------------------------------------


def test_request_emits_apache_combined_log_line(
    seeded_stations: list[str], caplog
) -> None:
    caplog.set_level(logging.INFO, logger="reframe.access")
    client.get("/es/")

    matching = [r for r in caplog.records if r.name == "reframe.access"]
    assert matching, "expected at least one reframe.access log record"
    msg = matching[-1].getMessage()
    # Apache combined: '<ip> - - [<time>] "GET <path> HTTP/1.1" <status> <bytes> "<ref>" "<ua>" <ms>ms'
    assert '"GET /es/ HTTP/1.1" 200' in msg
    assert msg.endswith("ms") or msg.endswith("ms\n")


# ---------------------------------------------------------------------------
# Image dimension attributes (§8.2 — required on every image)
# ---------------------------------------------------------------------------


def test_hero_and_cards_carry_explicit_width_height(
    seeded_stations: list[str],
    insert_photo: Callable[..., int],
) -> None:
    # When the station has photos, the hero IS the viewer (so its <img> uses
    # the .viewer__image class). When others have photos, the home-location
    # -card renders an <img>. Insert into both so both assertions have
    # something concrete to check.
    insert_photo("casa-do-pobo", "2026-04-01 10:00:00")
    insert_photo("bosque-comestible", "2026-04-01 10:00:00")

    resp = client.get("/es/anceu/casa-do-pobo")
    body = resp.text

    # Viewer image (acting as the hero) carries explicit dimensions.
    assert 'class="viewer__image"' in body
    assert 'width="1200"' in body and 'height="675"' in body
    # Cross-station cards use the home_location_card partial post-redesign.
    assert 'class="home-location-card__image"' in body
    assert 'width="400"' in body and 'height="300"' in body
