"""Phase 6 — admin takedown surface (§7.5, §9.7).

Coverage: auth gating, slug resolution, photo list rendering, soft-delete
flow + side effects on public views and the active reference set, pagination,
and the boot-time 30-day file cleanup.
"""

from __future__ import annotations

import base64
import dataclasses
import datetime as dt
import io
import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config, main as app_main, photos, storage
from app.main import app


client = TestClient(app, follow_redirects=False)


ADMIN_SLUG = "secret-slug-uuid"
ADMIN_PASSWORD = "letmein"


@pytest.fixture
def admin_settings(monkeypatch: pytest.MonkeyPatch, data_root: Path) -> None:
    """Set admin slug + password on the live `config.settings` singleton.

    Builds on the `data_root` override so tests pick up both. Note: the
    `data_root` fixture has already replaced settings once; we replace again
    to layer on the admin fields.
    """
    new_settings = dataclasses.replace(
        config.settings,
        admin_slug=ADMIN_SLUG,
        admin_password=ADMIN_PASSWORD,
    )
    monkeypatch.setattr(config, "settings", new_settings)


def _basic_auth_header(password: str = ADMIN_PASSWORD) -> dict[str, str]:
    raw = base64.b64encode(f"admin:{password}".encode("utf-8")).decode("ascii")

    return {"Authorization": f"Basic {raw}"}


# ---------------------------------------------------------------------------
# Auth + slug gating
# ---------------------------------------------------------------------------


def test_admin_requires_auth(seeded_stations, admin_settings):
    resp = client.get(f"/admin/{ADMIN_SLUG}/")

    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"].startswith("Basic")


def test_admin_wrong_password_unauthorized(seeded_stations, admin_settings):
    resp = client.get(
        f"/admin/{ADMIN_SLUG}/",
        headers=_basic_auth_header("nope"),
    )

    assert resp.status_code == 401


def test_admin_wrong_slug_returns_404_even_with_auth(seeded_stations, admin_settings):
    resp = client.get(
        "/admin/wrong-slug/",
        headers=_basic_auth_header(),
    )

    assert resp.status_code == 404


def test_admin_unset_config_is_404(seeded_stations, monkeypatch):
    """Empty admin_slug/password → the surface is unavailable (no leak)."""
    new = dataclasses.replace(
        config.settings, admin_slug="", admin_password=""
    )
    monkeypatch.setattr(config, "settings", new)
    resp = client.get(f"/admin/{ADMIN_SLUG}/", headers=_basic_auth_header())

    assert resp.status_code == 404


@pytest.mark.parametrize(
    "header",
    [
        "Bearer sometoken",  # non-Basic scheme
        "Basic ",  # empty credential blob
        "Basic !!!not-base64!!!",  # undecodable base64 → ValueError
        "Basic " + base64.b64encode(b"\xff\xfe").decode("ascii"),  # not utf-8
        "Basic " + base64.b64encode(b"letmein").decode("ascii"),  # no colon → empty pw
        "garbage",  # not even a scheme
    ],
)
def test_admin_malformed_auth_header_is_unauthorized(
    seeded_stations, admin_settings, header
):
    """Every non-Basic / malformed / undecodable header → 401 + challenge.

    Exercises the parsing branches in `_require_admin_auth` (missing/odd
    scheme, base64 `ValueError`, `UnicodeDecodeError`, missing colon).
    """
    resp = client.get(
        f"/admin/{ADMIN_SLUG}/", headers={"Authorization": header}
    )

    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"].startswith("Basic")


# ---------------------------------------------------------------------------
# List rendering
# ---------------------------------------------------------------------------


def test_admin_root_redirects_to_locations(seeded_stations, admin_settings):
    resp = client.get(f"/admin/{ADMIN_SLUG}/", headers=_basic_auth_header())

    assert resp.status_code == 303
    assert resp.headers["location"] == f"/admin/{ADMIN_SLUG}/locations"


def test_admin_list_renders_chrome_in_spanish(
    seeded_stations, admin_settings, insert_photo
):
    insert_photo("casa-do-pobo", "2026-03-12 09:14:00")
    resp = client.get(f"/admin/{ADMIN_SLUG}/photos", headers=_basic_auth_header())

    assert resp.status_code == 200
    body = resp.text
    # Page title in the new admin shell is just "Fotos".
    assert "<h1 class=\"admin-page-title\">" in body
    assert ">Fotos<" in body
    # The remove button is icon-only; its accessible label carries "Quitar".
    assert 'aria-label="Quitar"' in body
    assert '<html lang="es">' in body
    # No language toggle on admin chrome.
    assert "language-toggle" not in body


def test_admin_list_renders_remove_confirm_dialog(
    seeded_stations, admin_settings, insert_photo
):
    insert_photo("casa-do-pobo", "2026-03-12 09:14:00")
    resp = client.get(f"/admin/{ADMIN_SLUG}/photos", headers=_basic_auth_header())

    assert resp.status_code == 200
    body = resp.text
    # The removal reason lives in the shared confirmation dialog now, not
    # inline beside the button.
    assert 'id="admin-remove-confirm"' in body
    assert "data-confirm-reason" in body
    assert "Sí, quitar" in body
    assert "Cancelar" in body
    # The old inline reason input is gone.
    assert "admin-photo-card__reason-input" not in body
    # The per-card form is wired to the dialog, not the old native-confirm hook.
    assert "data-remove-form" in body
    assert "data-admin-confirm" not in body


def test_admin_list_shows_photos_reverse_chronological(
    seeded_stations, admin_settings, insert_photo
):
    insert_photo("casa-do-pobo", "2026-03-10 08:00:00")
    insert_photo("ies-ponte-caldelas", "2026-03-12 11:08:00")
    insert_photo("bosque-comestible", "2026-03-11 18:42:00")

    resp = client.get(f"/admin/{ADMIN_SLUG}/photos", headers=_basic_auth_header())
    assert resp.status_code == 200
    body = resp.text

    i_caldelas = body.find("IES Ponte Caldelas")
    i_bosque = body.find("Bosque Comestible")
    i_casa = body.find("Casa do Pobo")
    assert i_caldelas != -1 and i_bosque != -1 and i_casa != -1
    # Reverse chronological: caldelas (12) → bosque (11) → casa (10).
    assert i_caldelas < i_bosque < i_casa
    # Date format dd/mm/yyyy HH:MM (§9.6).
    assert "12/03/2026 11:08" in body
    assert "11/03/2026 18:42" in body
    assert "10/03/2026 08:00" in body


def test_admin_list_excludes_soft_deleted(
    seeded_stations, admin_settings, insert_photo
):
    insert_photo("casa-do-pobo", "2026-03-10 08:00:00")
    insert_photo(
        "casa-do-pobo",
        "2026-03-11 09:00:00",
        removed_at="2026-03-12 10:00:00",
    )

    resp = client.get(f"/admin/{ADMIN_SLUG}/photos", headers=_basic_auth_header())
    assert resp.status_code == 200
    body = resp.text
    assert "10/03/2026 08:00" in body
    assert "11/03/2026 09:00" not in body


def test_admin_empty_state(seeded_stations, admin_settings):
    resp = client.get(f"/admin/{ADMIN_SLUG}/photos", headers=_basic_auth_header())
    assert resp.status_code == 200
    assert "Aún no hay fotos." in resp.text


# ---------------------------------------------------------------------------
# Quitar (soft-delete) flow
# ---------------------------------------------------------------------------


def test_admin_quitar_soft_deletes_and_redirects(
    seeded_stations, admin_settings, insert_photo, db_conn
):
    photo_id = insert_photo("casa-do-pobo", "2026-03-10 08:00:00")
    resp = client.post(
        f"/admin/{ADMIN_SLUG}/photo/{photo_id}/remove",
        headers=_basic_auth_header(),
        data={"removal_reason": "ofensiva"},
    )

    assert resp.status_code == 303
    assert resp.headers["location"].startswith(f"/admin/{ADMIN_SLUG}/photos")

    row = db_conn.execute(
        "SELECT removed_at, removal_reason, viewer_path, thumb_path "
        "FROM photo WHERE id = ?",
        (photo_id,),
    ).fetchone()
    assert row["removed_at"] is not None
    assert row["removal_reason"] == "ofensiva"
    # Path columns blanked immediately (the files are gone too — admin
    # takedown is now a hard delete).
    assert row["viewer_path"] == ""
    assert row["thumb_path"] == ""


def test_admin_photo_upload_skips_feature_match(
    seeded_stations, admin_settings, make_jpeg, db_conn
):
    # Bootstrap case: no existing photos, no reference set. The admin
    # upload bypasses feature-match and lands as the station's first row.
    body = make_jpeg(seed_value=1)
    resp = client.post(
        f"/admin/{ADMIN_SLUG}/stations/casa-do-pobo/photos",
        headers=_basic_auth_header(),
        files={"photo": ("seed.jpg", io.BytesIO(body), "image/jpeg")},
    )

    assert resp.status_code == 303
    assert resp.headers["location"].endswith("/casa-do-pobo")

    row = db_conn.execute(
        "SELECT client_token, viewer_path, thumb_path FROM photo "
        "WHERE station_slug = ?",
        ("casa-do-pobo",),
    ).fetchone()
    assert row is not None
    assert row["client_token"].startswith("admin-")
    # Derivative files exist on disk.
    assert storage.local_photo_path(
        "casa-do-pobo", row["viewer_path"].rsplit("/", 1)[-1], "viewer"
    ).is_file()


def test_admin_quitar_hard_deletes_files(
    seeded_stations, admin_settings, insert_photo, db_conn
):
    # Plant the two derivative files so we can verify they vanish.
    storage.save_photo("casa-do-pobo", "del.jpg", b"viewer-bytes", "viewer")
    storage.save_photo("casa-do-pobo", "del.jpg", b"thumb-bytes", "thumb")
    photo_id = insert_photo(
        "casa-do-pobo", "2026-03-10 08:00:00", filename="del.jpg"
    )
    assert storage.local_photo_path("casa-do-pobo", "del.jpg", "viewer").is_file()
    assert storage.local_photo_path("casa-do-pobo", "del.jpg", "thumb").is_file()

    client.post(
        f"/admin/{ADMIN_SLUG}/photo/{photo_id}/remove",
        headers=_basic_auth_header(),
    )

    # Files are removed at takedown time, not 30 days later.
    assert not storage.local_photo_path("casa-do-pobo", "del.jpg", "viewer").is_file()
    assert not storage.local_photo_path("casa-do-pobo", "del.jpg", "thumb").is_file()


def test_admin_quitar_disappears_from_station_page(
    seeded_stations, admin_settings, insert_photo
):
    photo_id = insert_photo("casa-do-pobo", "2026-03-10 08:00:00")
    # Pre-soft-delete: viewer block present (the date overlay shows the date).
    pre = client.get("/es/anceu/casa-do-pobo")
    assert "10/03/2026" in pre.text

    client.post(
        f"/admin/{ADMIN_SLUG}/photo/{photo_id}/remove",
        headers=_basic_auth_header(),
    )

    post = client.get("/es/anceu/casa-do-pobo")
    assert post.status_code == 200
    # Back to cold-start: viewer no longer carries the photo's payload; the
    # date overlay for that photo is gone.
    assert "data-viewer-payload" not in post.text
    assert "10/03/2026" not in post.text


def test_admin_quitar_drops_from_active_reference_set(
    seeded_stations, admin_settings, insert_photo, db_conn
):
    photo_id = insert_photo("casa-do-pobo", "2026-03-10 08:00:00")

    pre = photos.active_reference_set(db_conn, "casa-do-pobo")
    pre_names = {p.name for p in pre}
    assert any(name.endswith(".jpg") for name in pre_names)
    pre_count = len(pre)

    client.post(
        f"/admin/{ADMIN_SLUG}/photo/{photo_id}/remove",
        headers=_basic_auth_header(),
    )

    post = photos.active_reference_set(db_conn, "casa-do-pobo")
    assert len(post) == pre_count - 1


def test_admin_quitar_already_removed_is_idempotent(
    seeded_stations, admin_settings, insert_photo, db_conn
):
    photo_id = insert_photo(
        "casa-do-pobo",
        "2026-03-10 08:00:00",
        removed_at="2026-03-12 10:00:00",
    )
    resp = client.post(
        f"/admin/{ADMIN_SLUG}/photo/{photo_id}/remove",
        headers=_basic_auth_header(),
    )
    assert resp.status_code == 303

    row = db_conn.execute(
        "SELECT removed_at FROM photo WHERE id = ?", (photo_id,)
    ).fetchone()
    # The original removed_at timestamp is preserved (we only update where
    # removed_at IS NULL).
    assert str(row["removed_at"]).startswith("2026-03-12 10:00:00")


def test_admin_quitar_last_photo_demotes_active_station_to_draft(
    seeded_stations, admin_settings, insert_photo, db_conn
):
    # casa-do-pobo is seeded active. Give it a single photo, then remove it:
    # with no active photos left the station no longer satisfies the
    # active-status gate, so it drops back to draft.
    db_conn.execute(
        "UPDATE station SET status = 'active' WHERE slug = ?", ("casa-do-pobo",)
    )
    photo_id = insert_photo("casa-do-pobo", "2026-03-10 08:00:00")

    resp = client.post(
        f"/admin/{ADMIN_SLUG}/photo/{photo_id}/remove",
        headers=_basic_auth_header(),
    )

    # Redirect carries the demotion toast.
    assert resp.status_code == 303
    assert "notice=removed_draft" in resp.headers["location"]
    status = db_conn.execute(
        "SELECT status FROM station WHERE slug = ?", ("casa-do-pobo",)
    ).fetchone()["status"]
    assert status == "draft"


def test_admin_quitar_keeps_station_active_when_photos_remain(
    seeded_stations, admin_settings, insert_photo, db_conn
):
    # Two photos: removing one leaves the station with an active photo, so it
    # stays active.
    db_conn.execute(
        "UPDATE station SET status = 'active' WHERE slug = ?", ("casa-do-pobo",)
    )
    keep_id = insert_photo("casa-do-pobo", "2026-03-09 08:00:00")
    drop_id = insert_photo("casa-do-pobo", "2026-03-10 08:00:00")

    resp = client.post(
        f"/admin/{ADMIN_SLUG}/photo/{drop_id}/remove",
        headers=_basic_auth_header(),
    )

    # Plain delete toast — no demotion.
    assert "notice=removed" in resp.headers["location"]
    assert "notice=removed_draft" not in resp.headers["location"]
    status = db_conn.execute(
        "SELECT status FROM station WHERE slug = ?", ("casa-do-pobo",)
    ).fetchone()["status"]
    assert status == "active"
    assert keep_id  # the survivor is untouched


def test_admin_quitar_last_photo_makes_location_inactive(
    seeded_stations, admin_settings, insert_photo, db_conn
):
    # ponte-caldelas' only station is ies-ponte-caldelas. Draining its last
    # photo demotes the station to draft, which — since a location's
    # active-ness is derived from its active stations — drops the location
    # into the admin's Inactivos group.
    db_conn.execute(
        "UPDATE station SET status = 'active' WHERE slug = ?",
        ("ies-ponte-caldelas",),
    )
    photo_id = insert_photo("ies-ponte-caldelas", "2026-03-10 08:00:00")

    client.post(
        f"/admin/{ADMIN_SLUG}/photo/{photo_id}/remove",
        headers=_basic_auth_header(),
    )

    body = client.get(
        f"/admin/{ADMIN_SLUG}/locations", headers=_basic_auth_header()
    ).text
    inactivos = body[body.index("Inactivos"):]
    assert "ponte-caldelas" in inactivos


def test_photos_tab_renders_removed_toast(seeded_stations, admin_settings):
    body = client.get(
        f"/admin/{ADMIN_SLUG}/photos?notice=removed", headers=_basic_auth_header()
    ).text
    assert "data-admin-toast" in body
    assert "Foto eliminada." in body


def test_photos_tab_renders_removed_draft_toast(seeded_stations, admin_settings):
    body = client.get(
        f"/admin/{ADMIN_SLUG}/photos?notice=removed_draft",
        headers=_basic_auth_header(),
    ).text
    assert "data-admin-toast" in body
    assert "pasó a borrador" in body


def test_station_view_renders_removed_toast(seeded_stations, admin_settings):
    body = client.get(
        f"/admin/{ADMIN_SLUG}/stations/casa-do-pobo?notice=removed",
        headers=_basic_auth_header(),
    ).text
    assert "data-admin-toast" in body
    assert "Foto eliminada." in body
    # Must not collide with the photo-upload-failure ("photo_<code>") notice.
    assert "No se pudo añadir la foto" not in body


def test_station_view_remove_form_carries_redirect_back(
    seeded_stations, admin_settings, insert_photo
):
    insert_photo("casa-do-pobo", "2026-03-10 08:00:00")
    body = client.get(
        f"/admin/{ADMIN_SLUG}/stations/casa-do-pobo", headers=_basic_auth_header()
    ).text
    # The station view's remove form returns the admin to the station page,
    # where the toast then renders.
    assert (
        f'value="/admin/{ADMIN_SLUG}/stations/casa-do-pobo"' in body
    )


def test_admin_quitar_requires_auth(seeded_stations, admin_settings, insert_photo):
    photo_id = insert_photo("casa-do-pobo", "2026-03-10 08:00:00")
    resp = client.post(f"/admin/{ADMIN_SLUG}/photo/{photo_id}/remove")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def test_admin_paginates_at_twenty_per_page(
    seeded_stations, admin_settings, insert_photo
):
    # 25 photos → page 1 shows 20, page 2 shows 5. Distribute across days
    # so reverse-chronological ordering is unambiguous.
    for i in range(25):
        day = i + 1  # 1..25
        insert_photo(
            "casa-do-pobo",
            f"2026-03-{day:02d} 12:00:00",
        )

    page1 = client.get(f"/admin/{ADMIN_SLUG}/photos", headers=_basic_auth_header())
    assert page1.status_code == 200
    # 20 Quitar buttons on page 1 (icon-only; identified by accessible label).
    assert page1.text.count('aria-label="Quitar"') == 20
    assert "Siguientes →" in page1.text

    page2 = client.get(
        f"/admin/{ADMIN_SLUG}/photos?page=2", headers=_basic_auth_header()
    )
    assert page2.status_code == 200
    assert page2.text.count('aria-label="Quitar"') == 5
    assert "← Anteriores" in page2.text


# ---------------------------------------------------------------------------
# 30-day file cleanup
# ---------------------------------------------------------------------------


def test_cleanup_hard_deletes_files_after_30_days(
    seeded_stations, admin_settings, insert_photo, db_conn, data_root
):
    # Plant the two derivative files so we can verify they vanish.
    storage.save_photo("casa-do-pobo", "old.jpg", b"viewer-bytes", "viewer")
    storage.save_photo("casa-do-pobo", "old.jpg", b"thumb-bytes", "thumb")

    # Removed 31 days ago → should be cleaned.
    removed_at = (dt.datetime.utcnow() - dt.timedelta(days=31)).isoformat(sep=" ")
    photo_id = insert_photo(
        "casa-do-pobo",
        "2025-12-01 08:00:00",
        filename="old.jpg",
        removed_at=removed_at,
    )

    cleaned = app_main.cleanup_expired_removals()
    assert cleaned == 1

    # Files removed.
    assert not storage.local_photo_path("casa-do-pobo", "old.jpg", "viewer").is_file()
    assert not storage.local_photo_path("casa-do-pobo", "old.jpg", "thumb").is_file()

    # DB row remains, paths blanked.
    row = db_conn.execute(
        "SELECT removed_at, viewer_path, thumb_path "
        "FROM photo WHERE id = ?",
        (photo_id,),
    ).fetchone()
    assert row["removed_at"] is not None
    assert row["viewer_path"] == ""
    assert row["thumb_path"] == ""


def test_cleanup_skips_recently_removed(
    seeded_stations, admin_settings, insert_photo, db_conn, data_root
):
    storage.save_photo("casa-do-pobo", "fresh.jpg", b"x", "viewer")
    storage.save_photo("casa-do-pobo", "fresh.jpg", b"x", "thumb")

    removed_at = (dt.datetime.utcnow() - dt.timedelta(days=5)).isoformat(sep=" ")
    insert_photo(
        "casa-do-pobo",
        "2026-04-29 08:00:00",
        filename="fresh.jpg",
        removed_at=removed_at,
    )

    cleaned = app_main.cleanup_expired_removals()
    assert cleaned == 0
    assert storage.local_photo_path("casa-do-pobo", "fresh.jpg", "viewer").is_file()


def test_cleanup_skips_active_photos(
    seeded_stations, admin_settings, insert_photo, db_conn, data_root
):
    storage.save_photo("casa-do-pobo", "live.jpg", b"x", "viewer")
    insert_photo("casa-do-pobo", "2026-04-29 08:00:00", filename="live.jpg")

    cleaned = app_main.cleanup_expired_removals()
    assert cleaned == 0
    assert storage.local_photo_path("casa-do-pobo", "live.jpg", "viewer").is_file()


def test_cleanup_idempotent(seeded_stations, admin_settings, insert_photo, data_root):
    storage.save_photo("casa-do-pobo", "old.jpg", b"x", "viewer")
    storage.save_photo("casa-do-pobo", "old.jpg", b"x", "thumb")

    removed_at = (dt.datetime.utcnow() - dt.timedelta(days=45)).isoformat(sep=" ")
    insert_photo(
        "casa-do-pobo",
        "2025-12-01 08:00:00",
        filename="old.jpg",
        removed_at=removed_at,
    )

    first = app_main.cleanup_expired_removals()
    second = app_main.cleanup_expired_removals()
    assert first == 1
    assert second == 0


# ---------------------------------------------------------------------------
# v2 — admin Locations + Stations CRUD
# ---------------------------------------------------------------------------


def test_admin_sidebar_pages_render(
    admin_settings: None, seeded_stations: list[str]
) -> None:
    auth = _basic_auth_header()
    for path in ("photos", "locations", "stations", "settings"):
        url = f"/admin/{ADMIN_SLUG}/{path}"
        resp = client.get(url, headers=auth)
        assert resp.status_code == 200, url


def test_admin_create_location(
    admin_settings: None, seeded_stations: list[str], db_conn: sqlite3.Connection
) -> None:
    resp = client.post(
        f"/admin/{ADMIN_SLUG}/locations/new",
        headers=_basic_auth_header(),
        data={"location_slug": "vigo", "name": "Vigo", "country": "PT"},
    )
    assert resp.status_code == 303
    row = db_conn.execute(
        "SELECT name, country FROM location WHERE slug = ?", ("vigo",)
    ).fetchone()
    assert row is not None and row["name"] == "Vigo"
    # Country is stored as the ISO code submitted via the dropdown.
    assert row["country"] == "PT"
    # After creating, land on the new location's edit page (not the list) with
    # a "created" notice the edit page surfaces as a banner.
    assert (
        resp.headers["location"]
        == f"/admin/{ADMIN_SLUG}/locations/vigo?notice=created"
    )


def test_admin_create_location_edit_page_shows_created_banner(
    admin_settings: None, seeded_stations: list[str]
) -> None:
    client.post(
        f"/admin/{ADMIN_SLUG}/locations/new",
        headers=_basic_auth_header(),
        data={"location_slug": "vigo", "name": "Vigo", "country": "PT"},
    )
    resp = client.get(
        f"/admin/{ADMIN_SLUG}/locations/vigo?notice=created",
        headers=_basic_auth_header(),
    )
    assert resp.status_code == 200
    assert "Lugar creado." in resp.text


def test_admin_update_location_redirects_with_saved_banner(
    admin_settings: None, seeded_stations: list[str], db_conn: sqlite3.Connection
) -> None:
    resp = client.post(
        f"/admin/{ADMIN_SLUG}/locations/anceu",
        headers=_basic_auth_header(),
        data={"name": "Anceu renombrado", "country": "ES"},
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/admin/{ADMIN_SLUG}/locations?notice=saved"
    name = db_conn.execute(
        "SELECT name FROM location WHERE slug = ?", ("anceu",)
    ).fetchone()["name"]
    assert name == "Anceu renombrado"
    # The list page renders the saved banner when the notice is present.
    listing = client.get(
        f"/admin/{ADMIN_SLUG}/locations?notice=saved", headers=_basic_auth_header()
    )
    assert "Lugar guardado." in listing.text


def test_admin_new_location_form_uses_crear_and_cancel(
    admin_settings: None, seeded_stations: list[str]
) -> None:
    resp = client.get(
        f"/admin/{ADMIN_SLUG}/locations/new", headers=_basic_auth_header()
    )
    body = resp.text
    # New form: "Crear" verb + a "Cancelar" link, and no back-arrow guard
    # (the back button is edit-only).
    assert ">Crear<" in body
    assert "Cancelar" in body
    assert "data-admin-back" not in body


def test_admin_edit_location_form_has_back_button(
    admin_settings: None, seeded_stations: list[str]
) -> None:
    resp = client.get(
        f"/admin/{ADMIN_SLUG}/locations/anceu", headers=_basic_auth_header()
    )
    body = resp.text
    # Edit form: back-arrow link (with the unsaved-changes guard hook) and a
    # header Save button; no inline "Cancelar".
    assert "data-admin-back" in body
    assert 'form="location-form"' in body


def test_admin_create_location_unknown_code_falls_back(
    admin_settings: None, seeded_stations: list[str], db_conn: sqlite3.Connection
) -> None:
    # A bogus code (e.g. a stale form submission) maps to the default
    # country rather than landing as-is in the column.
    resp = client.post(
        f"/admin/{ADMIN_SLUG}/locations/new",
        headers=_basic_auth_header(),
        data={"location_slug": "moon", "name": "Moon", "country": "ZZ"},
    )
    assert resp.status_code == 303
    row = db_conn.execute(
        "SELECT country FROM location WHERE slug = ?", ("moon",)
    ).fetchone()
    assert row is not None and row["country"] == "ES"


def test_admin_location_form_renders_dropdown(
    admin_settings: None, seeded_stations: list[str]
) -> None:
    # The country field is a <select> populated with translated names. The
    # admin chrome is Spanish-only, so the labels are the Spanish ones.
    resp = client.get(
        f"/admin/{ADMIN_SLUG}/locations/new", headers=_basic_auth_header()
    )
    assert resp.status_code == 200
    body = resp.text
    assert '<select name="country">' in body
    assert 'value="ES"' in body and "España" in body
    assert 'value="PT"' in body and "Portugal" in body
    # The current default country is preselected on the new-location form.
    assert 'value="ES" selected' in body


def test_admin_create_station_is_draft(
    admin_settings: None, seeded_stations: list[str], db_conn: sqlite3.Connection
) -> None:
    resp = client.post(
        f"/admin/{ADMIN_SLUG}/stations/new",
        headers=_basic_auth_header(),
        data={
            "station_slug": "new-spot",
            "name_en": "New Spot",
            "location_slug": "anceu",
            "story_en": "A new story.",
        },
    )
    assert resp.status_code == 303
    row = db_conn.execute(
        "SELECT status, name_es, name_en FROM station WHERE slug = ?", ("new-spot",)
    ).fetchone()
    assert row is not None
    # A fresh station has no seed references, so it must be a draft.
    assert row["status"] == "draft"
    # English doubles for Spanish when Spanish is left blank.
    assert row["name_es"] == "New Spot"
    # After creating, land on the new station's edit page with a "created" toast.
    assert (
        resp.headers["location"]
        == f"/admin/{ADMIN_SLUG}/stations/new-spot?notice=created"
    )


def test_admin_create_station_edit_page_shows_created_toast(
    admin_settings: None, seeded_stations: list[str]
) -> None:
    client.post(
        f"/admin/{ADMIN_SLUG}/stations/new",
        headers=_basic_auth_header(),
        data={
            "station_slug": "new-spot",
            "name_en": "New Spot",
            "location_slug": "anceu",
            "story_en": "A new story.",
        },
    )
    resp = client.get(
        f"/admin/{ADMIN_SLUG}/stations/new-spot?notice=created",
        headers=_basic_auth_header(),
    )
    assert resp.status_code == 200
    assert "Estación creada." in resp.text


def test_admin_update_station_redirects_to_list_with_saved_toast(
    admin_settings: None, seeded_stations: list[str]
) -> None:
    # A non-activating save (status stays draft) returns to the Stations list
    # with a "saved" toast.
    resp = client.post(
        f"/admin/{ADMIN_SLUG}/stations/casa-do-pobo",
        headers=_basic_auth_header(),
        data={
            "name_en": "Casa do Pobo de Anceu",
            "location_slug": "anceu",
            "story_en": "Story.",
            "status": "draft",
        },
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/admin/{ADMIN_SLUG}/stations?notice=saved"
    listing = client.get(
        f"/admin/{ADMIN_SLUG}/stations?notice=saved", headers=_basic_auth_header()
    )
    assert "Estación guardada." in listing.text


def test_admin_new_station_form_uses_crear_and_cancel(
    admin_settings: None, seeded_stations: list[str]
) -> None:
    body = client.get(
        f"/admin/{ADMIN_SLUG}/stations/new", headers=_basic_auth_header()
    ).text
    # New form: "Crear" verb + a "Cancelar" link, and no back-arrow guard.
    assert ">Crear<" in body
    assert "Cancelar" in body
    assert "data-admin-back" not in body


def test_admin_edit_station_form_has_back_button(
    admin_settings: None, seeded_stations: list[str]
) -> None:
    body = client.get(
        f"/admin/{ADMIN_SLUG}/stations/casa-do-pobo", headers=_basic_auth_header()
    ).text
    # Edit form: back-arrow link (with the unsaved-changes guard hook) and the
    # header Save button.
    assert "data-admin-back" in body
    assert 'form="station-form"' in body
    # The form carries the dirty-warn hook so navigating away after a change
    # (including the status select) prompts about unsaved changes.
    assert "data-admin-dirty-warn" in body


def test_admin_station_form_status_dropdown_uses_spanish_labels(
    admin_settings: None, seeded_stations: list[str]
) -> None:
    body = client.get(
        f"/admin/{ADMIN_SLUG}/stations/casa-do-pobo", headers=_basic_auth_header()
    ).text
    # The status <select> options carry capitalised Spanish labels keyed off
    # the raw status values.
    assert '<option value="draft"' in body
    assert ">Borrador<" in body
    assert ">Activa<" in body
    assert ">Archivada<" in body
    # The raw English keys never reach the UI as option text.
    assert ">draft<" not in body
    assert ">active<" not in body
    assert ">archived<" not in body


def test_admin_cannot_activate_station_without_readiness(
    admin_settings: None, seeded_stations: list[str], db_conn: sqlite3.Connection
) -> None:
    # casa-do-pobo has no seed references — not ready.
    resp = client.post(
        f"/admin/{ADMIN_SLUG}/stations/casa-do-pobo",
        headers=_basic_auth_header(),
        data={
            "name_en": "Casa do Pobo de Anceu",
            "location_slug": "anceu",
            "story_en": "Story.",
            "status": "active",
        },
    )
    assert resp.status_code == 303
    assert "notice=forced_draft" in resp.headers["location"]
    status = db_conn.execute(
        "SELECT status FROM station WHERE slug = ?", ("casa-do-pobo",)
    ).fetchone()["status"]
    assert status == "draft"


def test_admin_archive_station_hides_it_from_listings(
    admin_settings: None, seeded_stations: list[str], db_conn: sqlite3.Connection
) -> None:
    resp = client.post(
        f"/admin/{ADMIN_SLUG}/stations/casa-do-pobo/archive",
        headers=_basic_auth_header(),
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/admin/{ADMIN_SLUG}/stations?notice=archived"
    status = db_conn.execute(
        "SELECT status FROM station WHERE slug = ?", ("casa-do-pobo",)
    ).fetchone()["status"]
    assert status == "archived"
    # Archived: still reachable by URL, but absent from the landing listing.
    assert client.get("/es/anceu/casa-do-pobo").status_code == 200
    landing = client.get("/es/").text
    assert "/es/anceu/casa-do-pobo" not in landing


# ---------------------------------------------------------------------------
# Grouping + capitalised Spanish status labels + location delete
# ---------------------------------------------------------------------------


def test_stations_index_groups_by_status_with_spanish_labels(
    admin_settings: None, seeded_stations: list[str], db_conn: sqlite3.Connection
) -> None:
    # Seed starts all-active; nudge one into each other state so all three
    # groups render.
    db_conn.execute("UPDATE station SET status = 'draft' WHERE slug = ?", ("casa-do-pobo",))
    db_conn.execute(
        "UPDATE station SET status = 'archived' WHERE slug = ?", ("ies-ponte-caldelas",)
    )

    body = client.get(
        f"/admin/{ADMIN_SLUG}/stations", headers=_basic_auth_header()
    ).text

    # Group headers appear in lifecycle order: Borradores → Activas → Archivadas.
    assert body.index("Borradores") < body.index("Activas") < body.index("Archivadas")
    # Capitalised, title-case Spanish badges — never the raw lowercase value.
    assert ">Borrador<" in body
    assert ">Activa<" in body
    assert ">Archivada<" in body
    assert ">draft<" not in body and ">active<" not in body


def test_stations_index_omits_empty_status_groups(
    admin_settings: None, seeded_stations: list[str]
) -> None:
    # All seeded stations are active — only the Activas group should show.
    body = client.get(
        f"/admin/{ADMIN_SLUG}/stations", headers=_basic_auth_header()
    ).text
    assert "Activas" in body
    assert "Borradores" not in body
    assert "Archivadas" not in body


def test_locations_index_groups_active_inactive_and_offers_delete(
    admin_settings: None, seeded_stations: list[str], db_conn: sqlite3.Connection
) -> None:
    # An empty location (no stations) and a location whose only station is a
    # draft are both "inactive"; anceu (has active stations) is "active".
    db_conn.execute(
        "INSERT INTO location (slug, name, country) VALUES (?, ?, ?)",
        ("empty-place", "Lugar Vacío", "ES"),
    )

    body = client.get(
        f"/admin/{ADMIN_SLUG}/locations", headers=_basic_auth_header()
    ).text

    assert body.index("Activos") < body.index("Inactivos")
    # Empty location is deletable — its delete form is present.
    assert f"/admin/{ADMIN_SLUG}/locations/empty-place/delete" in body
    # A location with stations (anceu) gets no delete affordance.
    assert f"/admin/{ADMIN_SLUG}/locations/anceu/delete" not in body


def test_delete_empty_location_removes_it(
    admin_settings: None, seeded_stations: list[str], db_conn: sqlite3.Connection
) -> None:
    db_conn.execute(
        "INSERT INTO location (slug, name, country) VALUES (?, ?, ?)",
        ("empty-place", "Lugar Vacío", "ES"),
    )

    resp = client.post(
        f"/admin/{ADMIN_SLUG}/locations/empty-place/delete",
        headers=_basic_auth_header(),
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/admin/{ADMIN_SLUG}/locations?notice=deleted"
    assert (
        db_conn.execute(
            "SELECT 1 FROM location WHERE slug = ?", ("empty-place",)
        ).fetchone()
        is None
    )


def test_delete_location_with_stations_is_refused(
    admin_settings: None, seeded_stations: list[str], db_conn: sqlite3.Connection
) -> None:
    resp = client.post(
        f"/admin/{ADMIN_SLUG}/locations/anceu/delete",
        headers=_basic_auth_header(),
    )
    assert resp.status_code == 303
    assert "error=has_stations" in resp.headers["location"]
    # The location row survives.
    assert (
        db_conn.execute(
            "SELECT 1 FROM location WHERE slug = ?", ("anceu",)
        ).fetchone()
        is not None
    )


def test_delete_location_requires_auth(
    admin_settings: None, seeded_stations: list[str]
) -> None:
    assert (
        client.post(
            f"/admin/{ADMIN_SLUG}/locations/empty-place/delete"
        ).status_code
        == 401
    )


def test_station_archive_form_carries_confirmation_attributes(
    admin_settings: None, seeded_stations: list[str]
) -> None:
    body = client.get(
        f"/admin/{ADMIN_SLUG}/stations/casa-do-pobo", headers=_basic_auth_header()
    ).text
    # The archive form opts into the generic confirm dialog.
    assert "data-admin-confirm" in body
    assert 'data-confirm-title="¿Archivar esta estación?"' in body
    assert "no se elimina nada" in body.lower()
    # The shared dialog is included on the page.
    assert 'id="admin-action-confirm"' in body


# ---------------------------------------------------------------------------
# Station form returns to its origin (location detail vs Stations list)
# ---------------------------------------------------------------------------


def test_location_detail_station_links_carry_origin(
    admin_settings: None, seeded_stations: list[str]
) -> None:
    body = client.get(
        f"/admin/{ADMIN_SLUG}/locations/anceu", headers=_basic_auth_header()
    ).text
    # Each station edit link from the location page carries the origin marker.
    assert f"/admin/{ADMIN_SLUG}/stations/casa-do-pobo?from_location=anceu" in body


def test_edit_station_back_link_targets_origin_location(
    admin_settings: None, seeded_stations: list[str]
) -> None:
    body = client.get(
        f"/admin/{ADMIN_SLUG}/stations/casa-do-pobo?from_location=anceu",
        headers=_basic_auth_header(),
    ).text
    # Back link + hidden field both point at the originating location.
    assert f'href="/admin/{ADMIN_SLUG}/locations/anceu"' in body
    assert 'name="from_location" value="anceu"' in body


def test_edit_station_without_origin_targets_stations_list(
    admin_settings: None, seeded_stations: list[str]
) -> None:
    body = client.get(
        f"/admin/{ADMIN_SLUG}/stations/casa-do-pobo", headers=_basic_auth_header()
    ).text
    assert f'href="/admin/{ADMIN_SLUG}/stations"' in body
    assert "from_location" not in body


def test_save_station_with_origin_redirects_to_location(
    admin_settings: None, seeded_stations: list[str]
) -> None:
    resp = client.post(
        f"/admin/{ADMIN_SLUG}/stations/casa-do-pobo",
        headers=_basic_auth_header(),
        data={
            "name_en": "Casa do Pobo de Anceu",
            "location_slug": "anceu",
            "story_en": "Story.",
            "status": "draft",
            "from_location": "anceu",
        },
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/admin/{ADMIN_SLUG}/locations/anceu?notice=saved"


def test_save_station_without_origin_redirects_to_stations(
    admin_settings: None, seeded_stations: list[str]
) -> None:
    resp = client.post(
        f"/admin/{ADMIN_SLUG}/stations/casa-do-pobo",
        headers=_basic_auth_header(),
        data={
            "name_en": "Casa do Pobo de Anceu",
            "location_slug": "anceu",
            "story_en": "Story.",
            "status": "draft",
        },
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/admin/{ADMIN_SLUG}/stations?notice=saved"


def test_create_station_from_location_keeps_origin_on_edit_page(
    admin_settings: None, seeded_stations: list[str]
) -> None:
    resp = client.post(
        f"/admin/{ADMIN_SLUG}/stations/new",
        headers=_basic_auth_header(),
        data={
            "station_slug": "new-spot",
            "name_en": "New Spot",
            "location_slug": "anceu",
            "story_en": "Story.",
            "from_location": "anceu",
        },
    )
    assert resp.status_code == 303
    assert (
        resp.headers["location"]
        == f"/admin/{ADMIN_SLUG}/stations/new-spot?notice=created&from_location=anceu"
    )


def test_admin_crud_requires_auth(
    admin_settings: None, seeded_stations: list[str]
) -> None:
    assert client.get(f"/admin/{ADMIN_SLUG}/stations").status_code == 401
    assert (
        client.post(
            f"/admin/{ADMIN_SLUG}/locations/new",
            data={"location_slug": "x", "name": "X"},
        ).status_code
        == 401
    )


# ---------------------------------------------------------------------------
# Sidebar reorder + Locations drill-down
# ---------------------------------------------------------------------------


def test_admin_sidebar_order_is_locations_stations_photos_settings(
    admin_settings: None, seeded_stations: list[str]
) -> None:
    body = client.get(
        f"/admin/{ADMIN_SLUG}/locations", headers=_basic_auth_header()
    ).text
    nav_start = body.index("admin-sidebar__nav")
    # Hierarchy: locations contain stations contain photos. Anchor the
    # search to the nav block so we don't accidentally collide with the
    # same words appearing later in the page body.
    nav = body[nav_start:]
    assert (
        nav.index("Lugares")
        < nav.index("Estaciones")
        < nav.index("Fotos")
        < nav.index("Ajustes")
    )


def test_admin_sidebar_nav_links_carry_icons(
    admin_settings: None, seeded_stations: list[str]
) -> None:
    body = client.get(
        f"/admin/{ADMIN_SLUG}/locations", headers=_basic_auth_header()
    ).text
    # Anchor the search to the sidebar block so the page title in <title>
    # doesn't shadow the sidebar label we're looking for.
    nav = body[body.index("admin-sidebar__nav"):]
    # Each of the four nav labels sits inside a link that also contains an
    # inline SVG icon — the icon span comes before the label text.
    for label in ("Lugares", "Estaciones", "Fotos", "Ajustes"):
        i = nav.index(label)
        head = nav.rfind('<a class="admin-sidebar__link', 0, i)
        assert head != -1, label
        slice_ = nav[head:i]
        assert "<svg" in slice_, f"missing SVG for {label}"


def test_admin_location_detail_lists_only_its_stations(
    admin_settings: None, seeded_stations: list[str]
) -> None:
    auth = _basic_auth_header()
    anceu = client.get(
        f"/admin/{ADMIN_SLUG}/locations/anceu", headers=auth
    ).text
    assert "Estaciones en este lugar" in anceu
    assert "Casa do Pobo de Anceu" in anceu
    assert "Anceu Food Forest" in anceu
    # The station in ponte-caldelas must not surface on the anceu detail page.
    assert "IES Ponte Caldelas" not in anceu

    other = client.get(
        f"/admin/{ADMIN_SLUG}/locations/ponte-caldelas", headers=auth
    ).text
    assert "IES Ponte Caldelas" in other
    assert "Casa do Pobo de Anceu" not in other
    assert "Anceu Food Forest" not in other


def test_admin_location_detail_offers_scoped_add_station(
    admin_settings: None, seeded_stations: list[str]
) -> None:
    body = client.get(
        f"/admin/{ADMIN_SLUG}/locations/anceu", headers=_basic_auth_header()
    ).text
    assert (
        f'href="/admin/{ADMIN_SLUG}/stations/new?location=anceu"' in body
    )
    assert "Nueva estación" in body


def test_admin_station_new_preselects_location_from_query(
    admin_settings: None, seeded_stations: list[str]
) -> None:
    import re

    body = client.get(
        f"/admin/{ADMIN_SLUG}/stations/new?location=ponte-caldelas",
        headers=_basic_auth_header(),
    ).text
    assert re.search(r'value="ponte-caldelas"\s+selected', body)
    # An unknown location slug silently falls through — no crash, nothing selected.
    no_match = client.get(
        f"/admin/{ADMIN_SLUG}/stations/new?location=does-not-exist",
        headers=_basic_auth_header(),
    )
    assert no_match.status_code == 200
    assert "selected" not in no_match.text


# ---------------------------------------------------------------------------
# Settings — upload notifications toggle
# ---------------------------------------------------------------------------


def test_admin_settings_renders_toggle_unchecked_by_default(
    admin_settings: None, seeded_stations: list[str]
) -> None:
    resp = client.get(
        f"/admin/{ADMIN_SLUG}/settings", headers=_basic_auth_header()
    )

    assert resp.status_code == 200
    body = resp.text
    assert "Enviar un correo cuando se suba una foto nueva" in body
    assert 'name="enabled"' in body
    # Unchecked by default — the substring `checked` should not appear on the
    # checkbox input.
    assert "checked" not in body


def test_admin_settings_renders_operational_readonly(
    admin_settings: None, seeded_stations: list[str]
) -> None:
    resp = client.get(
        f"/admin/{ADMIN_SLUG}/settings", headers=_basic_auth_header()
    )

    assert resp.status_code == 200
    body = resp.text
    # The two operational env vars are surfaced read-only with their names.
    assert "SUBMISSIONS_ENABLED" in body
    assert "NEARBY_RADIUS_KM" in body
    assert "Formulario de propuestas" in body
    assert "Radio de cercanía" in body
    # The radius value is rendered with its unit.
    assert f"{config.settings.nearby_radius_km} km" in body


def test_admin_settings_submissions_state_reflects_config(
    monkeypatch: pytest.MonkeyPatch, admin_settings: None, seeded_stations: list[str]
) -> None:
    # Default config has submissions disabled → "Desactivado".
    body = client.get(
        f"/admin/{ADMIN_SLUG}/settings", headers=_basic_auth_header()
    ).text
    assert "Desactivado" in body

    # Flip the env-backed setting → "Activado".
    enabled = dataclasses.replace(config.settings, submissions_enabled=True)
    monkeypatch.setattr(config, "settings", enabled)
    body = client.get(
        f"/admin/{ADMIN_SLUG}/settings", headers=_basic_auth_header()
    ).text
    assert "Activado" in body


def test_admin_settings_upload_notifications_post_flips_state(
    admin_settings: None, seeded_stations: list[str]
) -> None:
    # Enable
    resp = client.post(
        f"/admin/{ADMIN_SLUG}/settings/upload-notifications",
        data={"enabled": "on"},
        headers=_basic_auth_header(),
    )
    assert resp.status_code == 303

    body = client.get(
        f"/admin/{ADMIN_SLUG}/settings", headers=_basic_auth_header()
    ).text
    assert "checked" in body

    # Disable (no `enabled` field at all — checkbox semantics)
    resp = client.post(
        f"/admin/{ADMIN_SLUG}/settings/upload-notifications",
        data={},
        headers=_basic_auth_header(),
    )
    assert resp.status_code == 303

    body = client.get(
        f"/admin/{ADMIN_SLUG}/settings", headers=_basic_auth_header()
    ).text
    assert "checked" not in body


def test_admin_settings_upload_notifications_post_requires_auth(
    admin_settings: None, seeded_stations: list[str]
) -> None:
    resp = client.post(
        f"/admin/{ADMIN_SLUG}/settings/upload-notifications",
        data={"enabled": "on"},
    )

    assert resp.status_code == 401
