"""v2 — standalone marketing pages (/locations, /host).

Covers the localised path segments, the canonical-URL 404 for a mismatched
segment, and the submission form.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app, follow_redirects=False)


# The SMTP fake (`FakeSMTP`) and the `configure_smtp` fixture live in
# `conftest.py` so `test_email` can share them.


# ---------------------------------------------------------------------------
# /about — removed in the "abundant brooks" redesign (content collapsed into
# the homepage About section). The route should 404 in both languages.
# ---------------------------------------------------------------------------


def test_about_routes_are_gone(seeded_stations: list[str]) -> None:
    assert client.get("/en/about").status_code == 404
    assert client.get("/es/sobre").status_code == 404


# ---------------------------------------------------------------------------
# /locations
# ---------------------------------------------------------------------------


def test_locations_en_renders_map_and_grouped_list(
    seeded_stations: list[str],
) -> None:
    resp = client.get("/en/locations")

    assert resp.status_code == 200
    body = resp.text
    assert '<html lang="en">' in body
    assert "Locations" in body
    # The grouped list: country → place → station. Country is the localised
    # display name resolved from the ISO code in `location.country`.
    assert "Spain" in body
    assert "Anceu, Galicia" in body
    assert "Ponte Caldelas, Galicia" in body
    # Per-location subgroup headings render as the `.section-label` primitive
    # so each country's stations are grouped under their place name.
    assert (
        '<span class="section-label__text">Anceu, Galicia</span>' in body
    )
    assert (
        '<span class="section-label__text">Ponte Caldelas, Galicia</span>'
        in body
    )
    assert 'href="/en/anceu/bosque-comestible"' in body
    # The map container + the inline marker payload (seed stations have
    # coordinates), plus the self-hosted Leaflet assets.
    assert 'id="locations-map"' in body
    assert "data-locations-payload" in body
    assert "/static/vendor/leaflet/leaflet.js" in body


def test_locations_es_uses_localised_segment(
    seeded_stations: list[str],
) -> None:
    assert client.get("/es/lugares").status_code == 200
    body = client.get("/es/lugares").text
    assert '<html lang="es">' in body
    assert "Lugares" in body
    # Country names render in the user's language; the column stores 'ES'.
    assert "España" in body


def test_locations_wrong_segment_for_language_404s(
    seeded_stations: list[str],
) -> None:
    assert client.get("/es/locations").status_code == 404
    assert client.get("/en/lugares").status_code == 404


def test_locations_map_omitted_when_no_coordinates(
    seeded_stations: list[str],
    db_conn: sqlite3.Connection,
) -> None:
    db_conn.execute("UPDATE station SET latitude = NULL, longitude = NULL")

    body = client.get("/en/locations").text
    # No coordinates → no map, but the grouped list still renders.
    assert 'id="locations-map"' not in body
    assert "data-locations-payload" not in body
    assert 'href="/en/anceu/bosque-comestible"' in body


def test_locations_empty_when_no_active_stations(
    seeded_stations: list[str],
    db_conn: sqlite3.Connection,
) -> None:
    db_conn.execute("UPDATE station SET status = 'archived'")

    body = client.get("/en/locations").text
    assert "No locations yet. Check back soon." in body
    assert 'id="locations-map"' not in body


def test_leaflet_assets_served(seeded_stations: list[str]) -> None:
    js = client.get("/static/vendor/leaflet/leaflet.js")
    css = client.get("/static/vendor/leaflet/leaflet.css")
    icon = client.get("/static/vendor/leaflet/images/marker-icon.png")
    assert js.status_code == 200
    assert css.status_code == 200
    assert "text/css" in css.headers["content-type"]
    assert icon.status_code == 200


# ---------------------------------------------------------------------------
# /host — community submission form
# ---------------------------------------------------------------------------


def test_host_form_renders(seeded_stations: list[str]) -> None:
    # site.toml ships submissions enabled, so the form is reachable.
    resp = client.get("/es/acoger")

    assert resp.status_code == 200
    body = resp.text
    assert "Acoger un lugar" in body
    # The honeypot field is present in the markup.
    assert 'name="website"' in body
    # All five interest checkboxes render.
    assert 'value="have_location"' in body
    assert 'value="just_curious"' in body


def test_host_confirmation_renders(
    seeded_stations: list[str], configure_smtp
) -> None:
    sent = configure_smtp()

    resp = client.post(
        "/en/host",
        data={"email": "me@example.com", "location": "Catalonia, Spain"},
    )

    assert resp.status_code == 200
    body = resp.text
    # Confirmation copy is shown.
    assert "Thanks." in body and "in touch." in body
    # The "BACK TO HOME" CTA is the new back-link text (all-caps to match
    # the `.btn-outline` design-system convention).
    assert "BACK TO HOME" in body
    assert len(sent) == 1


def test_host_wrong_segment_for_language_404s(
    seeded_stations: list[str],
) -> None:
    assert client.get("/es/host").status_code == 404
    assert client.get("/en/acoger").status_code == 404


def test_host_404_when_submissions_disabled(
    seeded_stations: list[str], set_submissions: Callable[[bool], None]
) -> None:
    set_submissions(False)

    assert client.get("/en/host").status_code == 404
    assert (
        client.post(
            "/en/host", data={"email": "a@b.co", "location": "x"}
        ).status_code
        == 404
    )


def test_host_surfaces_hidden_when_submissions_disabled(
    seeded_stations: list[str], set_submissions: Callable[[bool], None]
) -> None:
    # Enabled (suite baseline) → the nav CTA and the homepage setup section show.
    enabled = client.get("/en/").text
    assert 'site-nav__link--cta' in enabled
    assert 'home-setup' in enabled

    # Disabled → neither the nav link nor the setup section (which pitches
    # hosting) may render a route the visitor can't actually use.
    set_submissions(False)
    body = client.get("/en/").text
    assert 'site-nav__link--cta' not in body
    assert 'href="/en/host"' not in body
    assert 'home-setup' not in body
    assert 'id="setup"' not in body


def test_host_valid_submission_sends_email(
    seeded_stations: list[str], configure_smtp
) -> None:
    sent = configure_smtp()

    resp = client.post(
        "/en/host",
        data={
            "email": "me@example.com",
            "location": "Catalonia, Spain",
            "interests": ["have_location", "can_print"],
            "notes": "Happy to help.",
        },
    )

    assert resp.status_code == 200
    assert "Thanks." in resp.text and "in touch." in resp.text
    # The background task ran and the email went to the configured recipient.
    assert len(sent) == 1
    assert sent[0]["To"] == "hola@ruralhackers.test"
    assert sent[0]["Reply-To"] == "me@example.com"
    body = sent[0].get_content()
    assert "Catalonia, Spain" in body


def test_host_honeypot_drops_silently(
    seeded_stations: list[str], configure_smtp
) -> None:
    sent = configure_smtp()

    resp = client.post(
        "/en/host",
        data={
            "email": "bot@spam.test",
            "location": "Spamville",
            "website": "http://spam.example",
        },
    )

    # The bot sees the same confirmation a person would — but nothing sends.
    assert resp.status_code == 200
    assert "Thanks." in resp.text and "in touch." in resp.text
    assert sent == []


def test_host_missing_required_fields_shows_error(
    seeded_stations: list[str], configure_smtp
) -> None:
    sent = configure_smtp()

    resp = client.post("/en/host", data={"email": "", "location": ""})

    assert resp.status_code == 200
    body = resp.text
    assert "Please add your email and a rough location" in body
    # The form is shown again (not the confirmation) and nothing was sent.
    assert 'name="email"' in body
    assert sent == []


@pytest.mark.parametrize(
    "bad_email", ["x", "foo@bar", "@bar.com", "no-at-symbol.com", "spaces in@email.com"]
)
def test_host_invalid_email_shows_format_error(
    seeded_stations: list[str],
    configure_smtp,
    bad_email: str,
) -> None:
    sent = configure_smtp()

    resp = client.post(
        "/en/host", data={"email": bad_email, "location": "Barcelona"}
    )

    assert resp.status_code == 200
    body = resp.text
    assert "doesn&#39;t look like a valid email" in body
    # The form re-renders (not the confirmation) and nothing was sent.
    assert 'name="email"' in body
    # The submitted email is preserved so the user can correct it.
    assert f'value="{bad_email}"' in body
    assert sent == []
