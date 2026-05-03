"""Phase 4 — upload section view-model, template render, and stub endpoint.

Pure-server coverage. The client-side state machine is tested by manual click-
through (see CLAUDE.md / the §6 definition-of-done). The smaller deterministic
slice we cover here:

- view-model shape (anchor id per language, failure-microcopy completeness,
  payload constants visible to upload.js)
- station-page renders the upload section (heading, hidden-state shells,
  inline JSON payload)
- POST /api/upload returns the success shape, echoes the X-Client-Token
  header, and produces each §6.5 server-driven failure code via the
  `?test_failure=` parameter
- POST /api/upload rejects unknown failure codes
"""

from __future__ import annotations

import io

from fastapi.testclient import TestClient

from app import views
from app.main import app


client = TestClient(app, follow_redirects=False)


# ---------------------------------------------------------------------------
# View-model
# ---------------------------------------------------------------------------


def test_upload_view_anchor_id_per_language() -> None:
    es = views._upload_view("casa-do-pobo", "es")
    en = views._upload_view("casa-do-pobo", "en")

    assert es["anchor_id"] == "subir"
    assert en["anchor_id"] == "upload"


def test_upload_view_section_heading_localised() -> None:
    assert views._upload_view("casa-do-pobo", "es")["section_heading"] == "Subir una foto"
    assert views._upload_view("casa-do-pobo", "en")["section_heading"] == "Upload a photo"


def test_upload_view_failures_cover_all_codes() -> None:
    model = views._upload_view("casa-do-pobo", "es")

    expected = {
        "wrong_file_type",
        "network",
        "doesnt_match",
        "too_blurry",
        "server_error",
        "too_large",
        "too_small",
        "not_ready",
    }
    assert set(model["failures"]) == expected
    # server_error carries an inline link split across prefix/link/suffix so
    # the JS can build a real <a> rather than render raw markdown.
    se = model["failures"]["server_error"]
    assert "body_prefix" in se and "body_link" in se and "body_suffix" in se
    assert se["body_link"] == "escríbenos"
    # Plain failures carry a single body string + cta.
    blurry = model["failures"]["too_blurry"]
    assert blurry["body"].startswith("La foto se ve borrosa")
    assert blurry["cta"] == "Elegir otra"


def test_upload_view_payload_carries_constants_for_js() -> None:
    payload = views._upload_view("ies-ponte-caldelas", "en")["payload"]

    assert payload["endpoint"] == "/api/upload"
    assert payload["stationSlug"] == "ies-ponte-caldelas"
    assert payload["lang"] == "en"
    assert payload["maxSizeBytes"] == 30 * 1024 * 1024
    assert payload["maxLongEdge"] == 2400
    assert payload["jpegQuality"] == 0.85
    assert payload["stallTimeoutMs"] == 30_000
    assert "{percent}" in payload["uploadingStatusTemplate"]
    assert payload["uploadingPaused"] == "Paused — waiting for connection"
    assert payload["validatingStatus"] == "Checking photo…"
    assert payload["validatingSub"] == "Comparing with the reference photos…"
    # Success microcopy + CTA replace the old "refresh the page" hint.
    assert payload["successHeading"] == "Photo added to the timelapse"
    assert payload["successBody"] == "Your photo joins the others in the timelapse above."
    assert payload["viewCta"] == "View in timelapse"
    assert "refreshHint" not in payload
    # The success-state date renders client-side, so the JS needs the month
    # names + a language-appropriate template.
    assert len(payload["monthNames"]) == 12
    assert "{day}" in payload["dateTemplate"] and "{year}" in payload["dateTemplate"]


# ---------------------------------------------------------------------------
# Station page renders the upload section (§6.1)
# ---------------------------------------------------------------------------


def test_station_renders_upload_section_es(seeded_stations: list[str]) -> None:
    body = client.get("/es/anceu/casa-do-pobo").text

    # Always-visible heading + anchor id (§6.1, §3.4).
    assert 'id="subir"' in body
    assert "Subir una foto" in body
    # Two picker CTAs: gallery (primary) + camera (secondary).
    assert "Hacer una foto" in body
    assert 'id="upload-file-input"' in body
    assert 'id="upload-camera-input"' in body
    assert 'capture="environment"' in body
    # Acknowledgement line.
    assert "Al subir, aceptas que la foto sea pública." in body
    # Acknowledgement-panel placeholder copy is present (hidden by default).
    assert "Saber más" in body
    assert "publica de forma anónima" in body
    # State shells are present, hidden until JS shows them.
    assert "data-upload-state-preview" in body
    assert "data-upload-state-uploading" in body
    assert "data-upload-state-success" in body
    assert "data-upload-state-failure" in body
    # Validating overlay carries the prominent status + sub-line.
    assert "Comprobando foto…" in body
    assert "Comparando con las fotos de referencia…" in body
    # Success state has the view-in-timelapse CTA button (no refresh hint).
    assert "data-upload-success-view" in body
    assert "data-upload-success-body" in body
    assert "Recarga la página" not in body
    # Inline JSON payload that upload.js consumes.
    assert "data-upload-payload" in body
    assert '"endpoint": "/api/upload"' in body or '"endpoint":"/api/upload"' in body


def test_station_renders_upload_section_en(seeded_stations: list[str]) -> None:
    body = client.get("/en/anceu/casa-do-pobo").text

    assert 'id="upload"' in body
    assert "Upload a photo" in body
    assert "Take a photo" in body
    assert 'capture="environment"' in body
    assert "By uploading, you agree the photo will be public." in body
    assert "Learn more" in body


def test_station_no_upload_slot_stub_remains(seeded_stations: list[str]) -> None:
    body = client.get("/es/anceu/casa-do-pobo").text

    # Phase 2's slot stub is gone; the real section has replaced it.
    assert "Upload section — Phase 4" not in body


# ---------------------------------------------------------------------------
# /api/upload stub
# ---------------------------------------------------------------------------


def _multipart(filename: str = "photo.jpg", body: bytes = b"\xff\xd8\xff stub \xff\xd9"):
    return {"file": (filename, io.BytesIO(body), "image/jpeg")}


def test_upload_success_shape(
    seeded_stations: list[str], make_jpeg, seed_reference_jpeg
) -> None:
    seed_reference_jpeg("casa-do-pobo", seed_value=10)
    photo = make_jpeg(seed_value=10)
    resp = client.post(
        "/api/upload",
        data={"station_slug": "casa-do-pobo"},
        files=_multipart(body=photo),
        headers={"X-Client-Token": "deadbeef-aaaa-4bbb-8ccc-dddddddddddd"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    # Phase 5 honours the same shape; the client depends on it.
    assert "id" in data
    assert "captured_at" in data
    assert "filename" in data
    assert data["station_slug"] == "casa-do-pobo"
    assert data["viewer_url"].startswith("/photos/casa-do-pobo/viewer/")
    assert data["thumb_url"].startswith("/photos/casa-do-pobo/thumb/")


def test_upload_each_server_failure_code_via_test_param(
    seeded_stations: list[str],
) -> None:
    for code, expected_status in [
        ("wrong_file_type", 200),
        ("doesnt_match", 200),
        ("too_blurry", 200),
        ("too_large", 200),
        ("too_small", 200),
        ("not_ready", 200),
        ("server_error", 500),
    ]:
        resp = client.post(
            "/api/upload",
            data={"station_slug": "casa-do-pobo"},
            params={"test_failure": code},
            files=_multipart(),
            headers={"X-Client-Token": "tok"},
        )
        assert resp.status_code == expected_status, code
        body = resp.json()
        assert body == {"ok": False, "error": code}


def test_upload_unknown_test_failure_is_400(seeded_stations: list[str]) -> None:
    resp = client.post(
        "/api/upload",
        data={"station_slug": "casa-do-pobo"},
        params={"test_failure": "made-up"},
        files=_multipart(),
        headers={"X-Client-Token": "tok"},
    )

    assert resp.status_code == 400


def test_upload_reads_client_token_header(
    seeded_stations: list[str], make_jpeg, seed_reference_jpeg
) -> None:
    # The endpoint reads + persists the X-Client-Token header (Phase 5) — we
    # confirm it isn't rejected and that a successful upload comes back.
    seed_reference_jpeg("casa-do-pobo", seed_value=20)
    resp = client.post(
        "/api/upload",
        data={"station_slug": "casa-do-pobo"},
        files=_multipart(body=make_jpeg(seed_value=20)),
        headers={"X-Client-Token": "abc-token-123"},
    )

    assert resp.status_code == 200
    assert resp.json()["ok"] is True


# ---------------------------------------------------------------------------
# Section anchors used by the success-state smooth-scroll links (§6.7)
# ---------------------------------------------------------------------------


def test_station_with_photos_carries_viewer_and_otros_anchors(
    seeded_stations: list[str], insert_photo
) -> None:
    insert_photo("casa-do-pobo", "2026-04-01 09:00:00", filename="ph.jpg")

    body = client.get("/es/anceu/casa-do-pobo").text
    # Both anchor ids are needed by the success-state links to smooth-scroll.
    assert 'id="viewer"' in body
    assert 'id="otros"' in body


# ---------------------------------------------------------------------------
# Upload notification email — scheduled via BackgroundTasks (admin-toggleable)
# ---------------------------------------------------------------------------


def _enable_upload_notifications() -> None:
    from app import db, settings_store

    conn = db.connect()
    try:
        settings_store.set_upload_notifications_enabled(conn, True)
    finally:
        conn.close()


def test_upload_notification_scheduled_when_enabled(
    seeded_stations: list[str],
    make_jpeg,
    seed_reference_jpeg,
    monkeypatch,
) -> None:
    from app import main as app_main

    calls: list[dict] = []

    def _stub(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(app_main, "send_upload_notification", _stub)
    _enable_upload_notifications()
    seed_reference_jpeg("casa-do-pobo", seed_value=30)

    resp = client.post(
        "/api/upload",
        data={"station_slug": "casa-do-pobo"},
        files=_multipart(body=make_jpeg(seed_value=30)),
        headers={"X-Client-Token": "notify-tok-1"},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    assert len(calls) == 1
    call = calls[0]
    assert call["station_slug"] == "casa-do-pobo"
    # Station's `name_en` from the seed.
    assert call["station_name"]
    assert call["viewer_url"].endswith(resp.json()["viewer_url"])
    assert call["viewer_url"].startswith("http")
    assert call["thumb_path"].name == resp.json()["filename"]


def test_upload_notification_not_scheduled_when_disabled(
    seeded_stations: list[str],
    make_jpeg,
    seed_reference_jpeg,
    monkeypatch,
) -> None:
    from app import main as app_main

    calls: list[dict] = []
    monkeypatch.setattr(
        app_main, "send_upload_notification", lambda **kw: calls.append(kw)
    )
    # Toggle is off by default — don't enable.
    seed_reference_jpeg("casa-do-pobo", seed_value=31)

    resp = client.post(
        "/api/upload",
        data={"station_slug": "casa-do-pobo"},
        files=_multipart(body=make_jpeg(seed_value=31)),
        headers={"X-Client-Token": "notify-tok-2"},
    )
    assert resp.status_code == 200
    assert calls == []


def test_upload_notification_not_scheduled_on_idempotent_replay(
    seeded_stations: list[str],
    make_jpeg,
    seed_reference_jpeg,
    monkeypatch,
) -> None:
    from app import main as app_main

    calls: list[dict] = []
    monkeypatch.setattr(
        app_main, "send_upload_notification", lambda **kw: calls.append(kw)
    )
    _enable_upload_notifications()
    seed_reference_jpeg("casa-do-pobo", seed_value=32)
    photo = make_jpeg(seed_value=32)
    token = "notify-tok-3-replay"

    first = client.post(
        "/api/upload",
        data={"station_slug": "casa-do-pobo"},
        files=_multipart(body=photo),
        headers={"X-Client-Token": token},
    )
    assert first.status_code == 200
    assert len(calls) == 1

    # Same token, same body — should hit the idempotent replay branch and
    # NOT fire a second notification.
    second = client.post(
        "/api/upload",
        data={"station_slug": "casa-do-pobo"},
        files=_multipart(body=photo),
        headers={"X-Client-Token": token},
    )
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert len(calls) == 1
