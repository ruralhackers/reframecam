"""Smoke tests.

Confirms the app imports cleanly, the root redirect honours Accept-Language
with English as the default, and both language routes render the chrome.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.strings import STRINGS


client = TestClient(app, follow_redirects=False)


def test_app_imports() -> None:
    assert app.title == "ReFrame"


def test_root_default_redirects_to_en() -> None:
    resp = client.get("/")
    assert resp.status_code == 302
    assert resp.headers["location"] == "/en/"


def test_root_redirects_to_en_for_english_speaker() -> None:
    resp = client.get("/", headers={"accept-language": "en-GB,en;q=0.9"})
    assert resp.status_code == 302
    assert resp.headers["location"] == "/en/"


def test_root_redirects_to_es_for_spanish_speaker() -> None:
    resp = client.get("/", headers={"accept-language": "es-ES,es;q=0.9,en;q=0.5"})
    assert resp.status_code == 302
    assert resp.headers["location"] == "/es/"


def test_root_falls_back_to_en_for_unsupported_language() -> None:
    resp = client.get("/", headers={"accept-language": "fr-FR,fr;q=0.9"})
    assert resp.status_code == 302
    assert resp.headers["location"] == "/en/"


def test_root_first_enabled_tag_wins_regardless_of_quality() -> None:
    # Negotiation is "loose": the first *enabled* tag in document order wins,
    # even when a later tag carries a higher q-value (see `_pick_lang_from_accept`).
    resp = client.get(
        "/", headers={"accept-language": "fr-FR;q=0.9, es;q=0.1, en;q=0.8"}
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == "/es/"


def test_root_malformed_accept_language_falls_back_to_default() -> None:
    # A header with no recognisable enabled primary tag → default language.
    resp = client.get("/", headers={"accept-language": ";;;, zh-CN, *"})
    assert resp.status_code == 302
    assert resp.headers["location"] == "/en/"


@pytest.mark.parametrize("lang,other", [("es", "en"), ("en", "es")])
def test_landing_renders_chrome(lang: str, other: str) -> None:
    """Both language landings render base.html chrome end-to-end.

    Marketing-content assertions live in `test_routes`; this is the lightweight
    chrome / language-toggle integration check across both languages.
    """
    resp = client.get(f"/{lang}/")

    assert resp.status_code == 200
    body = resp.text
    assert f'<html lang="{lang}">' in body
    assert STRINGS[lang]["header.skip_to_main"] in body
    assert config.site.attribution(lang) in body
    # The inactive language appears as a toggle link to the other language root.
    assert f'href="/{other}/"' in body


def test_unknown_language_redirects_to_default() -> None:
    resp = client.get("/fr/")
    assert resp.status_code == 302
    assert resp.headers["location"] == "/en/"
