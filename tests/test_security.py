"""Security / privacy regressions.

Locks in the hardening added after the pre-launch security review:

- decompression-bomb rejection in the upload decoder (§7.3 / abuse)
- the same-origin guard that blocks forged cross-site POSTs (CSRF defence)
- per-IP rate limiting on the abuse-prone surfaces
- the email-format check rejecting header-injection newlines
- the privacy guarantee that served photos carry no EXIF (incl. GPS)
"""

from __future__ import annotations

import dataclasses
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import config, main as app_main, storage, validation
from app.main import _EMAIL_RE, app


client = TestClient(app, follow_redirects=False)


def _multipart(body: bytes, filename: str = "photo.jpg", content_type: str = "image/jpeg"):
    return {"file": (filename, io.BytesIO(body), content_type)}


# ---------------------------------------------------------------------------
# Decompression bomb (§7.3)
# ---------------------------------------------------------------------------


def test_decode_rejects_decompression_bomb_hard_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Lower the ceiling so an ordinary 100×100 image (10 000 px) trips the
    # hard DecompressionBombError (fires past 2× the limit) without us having
    # to synthesise a genuine gigapixel file.
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10)
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), (120, 120, 120)).save(buf, format="JPEG")

    with pytest.raises(validation.ValidationFailure) as exc:
        validation.decode_to_image(buf.getvalue())

    assert exc.value.code == validation.ERR_TOO_LARGE


def test_decode_rejects_decompression_bomb_warning_band(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 10 000 px sits between the limit (8 000) and 2× — Pillow only *warns*
    # there; we promote that warning to a rejection too.
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 8_000)
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), (120, 120, 120)).save(buf, format="JPEG")

    with pytest.raises(validation.ValidationFailure) as exc:
        validation.decode_to_image(buf.getvalue())

    assert exc.value.code == validation.ERR_TOO_LARGE


# ---------------------------------------------------------------------------
# Same-origin guard (CSRF defence)
# ---------------------------------------------------------------------------


def test_cross_origin_post_is_blocked() -> None:
    resp = client.post(
        "/api/upload",
        data={"station_slug": "casa-do-pobo"},
        files=_multipart(b"irrelevant"),
        headers={"X-Client-Token": "tok", "Origin": "http://evil.example"},
    )

    assert resp.status_code == 403


def test_same_origin_post_is_allowed_through() -> None:
    # TestClient's host is "testserver"; a matching Origin must not be blocked.
    # (The upload itself fails downstream — the point is it isn't a 403.)
    resp = client.post(
        "/api/upload",
        data={"station_slug": "casa-do-pobo"},
        files=_multipart(b"irrelevant"),
        headers={"X-Client-Token": "tok", "Origin": "http://testserver"},
    )

    assert resp.status_code != 403


def test_cross_origin_get_is_allowed() -> None:
    # Safe methods are never blocked, regardless of Origin.
    resp = client.get("/en/", headers={"Origin": "http://evil.example"})

    assert resp.status_code != 403


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


def test_rate_limit_returns_429_over_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Re-enable limiting (the conftest baseline turns it off) and dial the
    # admin bucket down to 2/window so a third request trips it.
    monkeypatch.setattr(
        config,
        "settings",
        dataclasses.replace(config.settings, rate_limit_enabled=True),
    )
    monkeypatch.setattr(app_main, "_RATE_LIMITS", {"admin": (2, 60)})
    app_main._rate_buckets.clear()

    # Admin isn't configured, so the route 404s — but the limiter counts the
    # request before the route runs, which is exactly the brute-force surface.
    first = client.get("/admin/whatever/")
    second = client.get("/admin/whatever/")
    third = client.get("/admin/whatever/")

    assert first.status_code != 429
    assert second.status_code != 429
    assert third.status_code == 429
    assert third.headers.get("Retry-After") == "60"


# ---------------------------------------------------------------------------
# Email-format / header-injection guard
# ---------------------------------------------------------------------------


def test_email_regex_accepts_plain_address() -> None:
    assert _EMAIL_RE.match("visitor@example.com")


@pytest.mark.parametrize(
    "value",
    [
        "visitor@example.com\nBcc: attacker@evil.com",  # header injection
        "visitor@example.com\n",  # trailing newline (the \A…\Z anchors catch it)
        "visitor@example.com\r\nSubject: x",
        "two parts@example.com",
    ],
)
def test_email_regex_rejects_injection_and_whitespace(value: str) -> None:
    assert _EMAIL_RE.match(value) is None


# ---------------------------------------------------------------------------
# EXIF / GPS stripping (privacy, §7.7)
# ---------------------------------------------------------------------------


def _jpeg_with_exif(make_jpeg) -> bytes:
    """A real, decodable JPEG carrying camera-make + GPS EXIF."""
    image = Image.open(io.BytesIO(make_jpeg(seed_value=314)))
    image.load()
    exif = image.getexif()
    exif[271] = "ReFrameTestCam"  # Make
    exif[272] = "Model-X"  # Model
    gps = exif.get_ifd(0x8825)
    gps[1] = "N"
    gps[2] = (42.0, 0.0, 0.0)  # latitude d/m/s as rationals
    gps[3] = "W"
    gps[4] = (8.0, 0.0, 0.0)  # longitude d/m/s as rationals
    buf = io.BytesIO()
    image.save(buf, format="JPEG", exif=exif.tobytes(), quality=90)

    return buf.getvalue()


def test_served_photo_has_no_exif_or_gps(
    seeded_stations: list[str], make_jpeg, db_conn
) -> None:
    source = _jpeg_with_exif(make_jpeg)
    # Sanity: the source really does carry the EXIF we expect to be stripped.
    src_exif = Image.open(io.BytesIO(source)).getexif()
    assert src_exif[271] == "ReFrameTestCam"
    assert dict(src_exif.get_ifd(0x8825))  # GPS IFD present

    # skip_match bypasses the feature matcher (no reference set needed) — the
    # encode path that strips EXIF is identical either way.
    result = validation.process_upload(
        conn=db_conn,
        station_slug="casa-do-pobo",
        client_token="tok-exif-strip",
        file_bytes=source,
        skip_match=True,
    )

    viewer_path = storage.local_photo_path("casa-do-pobo", result.filename, "viewer")
    out_exif = Image.open(viewer_path).getexif()

    assert 271 not in out_exif  # camera make gone
    assert 272 not in out_exif  # model gone
    assert not dict(out_exif.get_ifd(0x8825))  # no GPS coordinates survived
