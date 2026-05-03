"""SMTP send for operator-facing notifications.

Two functions:

- `send_submission` — community location submission form (v2).
- `send_upload_notification` — per-upload moderation email with the
  thumbnail attached inline so the operator can scan it at a glance.

Both are called from FastAPI `BackgroundTasks` so a slow SMTP server never
blocks the user-facing response; failures are logged, never surfaced.
"""

from __future__ import annotations

import datetime as dt
import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path

from app import config


_log = logging.getLogger("reframe.submissions")
_uploads_log = logging.getLogger("reframe.uploads_notifications")


# Stable interest keys (the checkbox `value`s) mapped to a fixed English
# label for the notification email — so the email reads the same regardless
# of which language the visitor filled the form in.
INTEREST_LABELS: dict[str, str] = {
    "have_location": "Has a specific location in mind",
    "can_install": "Can install the holder themselves",
    "can_print": "Happy to 3D print the holder from the open-source model",
    "want_guidance": "Would like guidance from Rural Hackers",
    "just_curious": "Just interested in learning more",
}


def _build_message(
    *, email: str, location: str, interests: list[str], notes: str
) -> EmailMessage:
    smtp = config.settings.smtp

    lines = [
        "New ReFrame location submission.",
        "",
        f"Email:          {email}",
        f"Rough location: {location}",
        "",
        "Interests:",
    ]
    selected = [INTEREST_LABELS.get(key, key) for key in interests]
    if selected:
        lines += [f"  - {label}" for label in selected]
    else:
        lines.append("  (none selected)")
    lines += ["", "Notes:", notes.strip() or "(none)"]

    message = EmailMessage()
    message["Subject"] = "ReFrame — new location submission"
    message["From"] = smtp.from_address or smtp.username
    message["To"] = smtp.recipient
    # Reply-To is the submitter so Rural Hackers can answer with one click.
    message["Reply-To"] = email
    message.set_content("\n".join(lines))

    return message


def send_submission(
    *, email: str, location: str, interests: list[str], notes: str
) -> None:
    """Send one submission email. Swallows and logs every failure.

    A no-op (with a warning) when SMTP isn't configured — a fork that leaves
    the `SMTP_*` env vars unset still gets a working form, it just doesn't
    deliver mail.
    """
    smtp = config.settings.smtp
    if not smtp.configured:
        _log.warning(
            "submission received but SMTP is not configured; dropped: %s", email
        )
        return

    message = _build_message(
        email=email, location=location, interests=interests, notes=notes
    )

    try:
        with smtplib.SMTP(smtp.host, smtp.port, timeout=20) as server:
            if smtp.use_tls:
                server.starttls()
            if smtp.username:
                server.login(smtp.username, smtp.password)
            server.send_message(message)
    except Exception:  # noqa: BLE001 — never let a send failure escape
        _log.exception("submission email send failed for %s", email)
        return

    _log.info("submission email sent for %s", email)


# ---------------------------------------------------------------------------
# Upload notification
# ---------------------------------------------------------------------------


def _format_captured_at(captured_at: dt.datetime) -> str:
    """`28 May 2026 09:14 UTC` — operator-facing, English-only."""
    return (
        f"{captured_at.day} {captured_at.strftime('%b %Y %H:%M')} UTC"
    )


def _build_upload_message(
    *,
    station_name: str,
    station_slug: str,
    captured_at: dt.datetime,
    viewer_url: str,
    thumb_bytes: bytes,
) -> EmailMessage:
    smtp = config.settings.smtp
    when = _format_captured_at(captured_at)

    text_body = (
        f"New photo uploaded on {station_name}.\n"
        f"\n"
        f"Station: {station_name} ({station_slug})\n"
        f"Uploaded: {when}\n"
        f"View full size: {viewer_url}\n"
    )

    html_body = (
        "<!doctype html>"
        "<html><body style=\"font-family:system-ui,-apple-system,sans-serif;"
        "color:#1a2620;margin:0;padding:24px;\">"
        f"<p style=\"margin:0 0 16px;font-size:15px;\">"
        f"New photo on <strong>{station_name}</strong>."
        f"</p>"
        f"<p style=\"margin:0 0 16px;\">"
        f"<img src=\"cid:thumb\" alt=\"Uploaded thumbnail\" "
        f"style=\"max-width:100%;height:auto;border-radius:4px;\" />"
        f"</p>"
        f"<table style=\"font-size:14px;line-height:1.5;border-collapse:collapse;\">"
        f"<tr><td style=\"padding-right:12px;color:#5a6660;\">Station</td>"
        f"<td>{station_name} <span style=\"color:#5a6660;\">({station_slug})</span></td></tr>"
        f"<tr><td style=\"padding-right:12px;color:#5a6660;\">Uploaded</td>"
        f"<td>{when}</td></tr>"
        f"<tr><td style=\"padding-right:12px;color:#5a6660;\">Full size</td>"
        f"<td><a href=\"{viewer_url}\">{viewer_url}</a></td></tr>"
        f"</table>"
        f"</body></html>"
    )

    message = EmailMessage()
    message["Subject"] = f"ReFrame — new photo: {station_name}"
    message["From"] = smtp.from_address or smtp.username
    message["To"] = smtp.recipient
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    html_part = message.get_payload()[-1]
    html_part.add_related(
        thumb_bytes, maintype="image", subtype="jpeg", cid="<thumb>"
    )

    return message


def send_upload_notification(
    *,
    station_name: str,
    station_slug: str,
    captured_at: dt.datetime,
    viewer_url: str,
    thumb_path: Path,
) -> None:
    """Email the configured recipient with the new photo's thumbnail inline.

    Swallows and logs every failure — the upload itself already succeeded
    and the visitor should never see a notification glitch. A no-op (with a
    warning) when SMTP isn't configured.
    """
    smtp = config.settings.smtp
    if not smtp.configured:
        _uploads_log.warning(
            "upload notification skipped: SMTP not configured (station=%s)",
            station_slug,
        )
        return

    try:
        thumb_bytes = thumb_path.read_bytes()
    except OSError:
        _uploads_log.exception(
            "upload notification: failed to read thumbnail at %s", thumb_path
        )
        return

    message = _build_upload_message(
        station_name=station_name,
        station_slug=station_slug,
        captured_at=captured_at,
        viewer_url=viewer_url,
        thumb_bytes=thumb_bytes,
    )

    try:
        with smtplib.SMTP(smtp.host, smtp.port, timeout=20) as server:
            if smtp.use_tls:
                server.starttls()
            if smtp.username:
                server.login(smtp.username, smtp.password)
            server.send_message(message)
    except Exception:  # noqa: BLE001 — never let a send failure escape
        _uploads_log.exception(
            "upload notification send failed (station=%s)", station_slug
        )
        return

    _uploads_log.info(
        "upload notification sent (station=%s)", station_slug
    )
