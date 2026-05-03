"""Direct coverage for the SMTP send functions in `app.email`.

`send_submission` is exercised end-to-end through the `/host` route in
`test_pages.py`; here we drive `send_upload_notification` (which is stubbed
out in `test_upload.py`, so its body never ran) and the shared
not-configured / send-failure paths directly. SMTP is faked via the
`configure_smtp` fixture in `conftest.py`.
"""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path

import pytest

from app import email as email_mod


CAPTURED_AT = dt.datetime(2026, 5, 28, 9, 14, 0)


def _write_thumb(tmp_path: Path) -> Path:
    """A tiny stand-in JPEG on disk — the send path only reads its bytes."""
    thumb = tmp_path / "thumb.jpg"
    thumb.write_bytes(b"\xff\xd8\xff fake-thumb \xff\xd9")

    return thumb


def test_upload_notification_sends_message_when_configured(
    configure_smtp, tmp_path: Path
) -> None:
    sent = configure_smtp()
    thumb = _write_thumb(tmp_path)

    email_mod.send_upload_notification(
        station_name="Bosque Comestible",
        station_slug="bosque-comestible",
        captured_at=CAPTURED_AT,
        viewer_url="https://reframe.test/photos/bosque-comestible/viewer/x.jpg",
        thumb_path=thumb,
    )

    assert len(sent) == 1
    message = sent[0]
    assert message["To"] == "hola@ruralhackers.test"
    assert message["From"] == "bot@reframe.test"
    assert "Bosque Comestible" in message["Subject"]


def test_upload_notification_attaches_thumbnail_inline(
    configure_smtp, tmp_path: Path
) -> None:
    sent = configure_smtp()
    thumb = _write_thumb(tmp_path)

    email_mod.send_upload_notification(
        station_name="Casa do Pobo",
        station_slug="casa-do-pobo",
        captured_at=CAPTURED_AT,
        viewer_url="https://reframe.test/v.jpg",
        thumb_path=thumb,
    )

    message = sent[0]
    # Plain-text + HTML alternative, and the HTML part carries the inline
    # thumbnail referenced by `cid:thumb`.
    image_parts = [
        part for part in message.walk() if part.get_content_maintype() == "image"
    ]
    assert len(image_parts) == 1
    assert image_parts[0].get_content_subtype() == "jpeg"
    html = message.get_body(preferencelist=("html",))
    assert html is not None
    assert "cid:thumb" in html.get_content()


def test_upload_notification_noop_when_smtp_not_configured(
    configure_smtp, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # No recipient → `SmtpConfig.configured` is False.
    sent = configure_smtp(recipient="")
    thumb = _write_thumb(tmp_path)

    with caplog.at_level(logging.WARNING, logger="reframe.uploads_notifications"):
        email_mod.send_upload_notification(
            station_name="IES Ponte Caldelas",
            station_slug="ies-ponte-caldelas",
            captured_at=CAPTURED_AT,
            viewer_url="https://reframe.test/v.jpg",
            thumb_path=thumb,
        )

    assert sent == []
    assert "SMTP not configured" in caplog.text


def test_upload_notification_swallows_missing_thumbnail(
    configure_smtp, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    sent = configure_smtp()
    missing = tmp_path / "does-not-exist.jpg"

    with caplog.at_level(logging.ERROR, logger="reframe.uploads_notifications"):
        email_mod.send_upload_notification(
            station_name="Bosque Comestible",
            station_slug="bosque-comestible",
            captured_at=CAPTURED_AT,
            viewer_url="https://reframe.test/v.jpg",
            thumb_path=missing,
        )

    # Read failure is logged and swallowed — nothing sent, no exception.
    assert sent == []
    assert "failed to read thumbnail" in caplog.text


def test_upload_notification_swallows_send_failure(
    configure_smtp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_smtp()
    thumb = _write_thumb(tmp_path)

    class _BoomSMTP:
        def __init__(self, *a, **k):
            raise OSError("connection refused")

    monkeypatch.setattr(email_mod.smtplib, "SMTP", _BoomSMTP)

    # Must not raise — the upload already succeeded; the visitor never sees this.
    email_mod.send_upload_notification(
        station_name="Casa do Pobo",
        station_slug="casa-do-pobo",
        captured_at=CAPTURED_AT,
        viewer_url="https://reframe.test/v.jpg",
        thumb_path=thumb,
    )


def test_submission_noop_when_smtp_not_configured(
    configure_smtp, caplog: pytest.LogCaptureFixture
) -> None:
    sent = configure_smtp(recipient="")

    with caplog.at_level(logging.WARNING, logger="reframe.submissions"):
        email_mod.send_submission(
            email="me@example.com",
            location="Galicia",
            interests=["have_location"],
            notes="hi",
        )

    assert sent == []
    assert "SMTP is not configured" in caplog.text
