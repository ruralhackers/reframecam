"""Phase 5 — server-side upload pipeline (§7.3).

Two layers of coverage:

- Unit tests for the pipeline's pure functions: EXIF orientation bake,
  captured_at resolution against the §7.2 sane window, derivative resize,
  filename construction.
- Integration tests through `POST /api/upload`: success path persists a
  photo + writes derivatives; each server-side failure code surfaces
  correctly; idempotent re-submit returns the prior response without
  re-processing; soft-deleting a photo drops it from the active reference
  set on the next upload.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import io
import logging
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import config, storage, validation
from app.main import app


client = TestClient(app)


# ---------------------------------------------------------------------------
# captured_at resolution (§7.2)
# ---------------------------------------------------------------------------


def _image_with_exif_datetime(value: str) -> Image.Image:
    """Build an in-memory image carrying a DateTimeOriginal EXIF tag."""
    base = Image.new("RGB", (100, 100), (180, 180, 180))
    exif = base.getexif()
    exif[validation._EXIF_DATETIME_ORIGINAL] = value
    buf = io.BytesIO()
    base.save(buf, format="JPEG", exif=exif.tobytes(), quality=80)
    buf.seek(0)
    image = Image.open(buf)
    image.load()

    return image


def test_captured_at_uses_exif_when_in_window() -> None:
    image = _image_with_exif_datetime("2026:03:12 09:14:00")
    now = dt.datetime(2026, 5, 4, 12, 0, 0, tzinfo=dt.timezone.utc)

    resolved = validation.resolve_captured_at(image, now=now)

    assert resolved == dt.datetime(2026, 3, 12, 9, 14, 0)


def test_captured_at_falls_back_when_pre_2020() -> None:
    image = _image_with_exif_datetime("1999:01:01 12:00:00")
    now = dt.datetime(2026, 5, 4, 12, 0, 0, tzinfo=dt.timezone.utc)

    resolved = validation.resolve_captured_at(image, now=now)

    assert resolved == dt.datetime(2026, 5, 4, 12, 0, 0)


def test_captured_at_falls_back_when_far_future() -> None:
    # Two days in the future — outside the §7.2 +1-day tolerance.
    image = _image_with_exif_datetime("2030:01:01 00:00:00")
    now = dt.datetime(2026, 5, 4, 12, 0, 0, tzinfo=dt.timezone.utc)

    resolved = validation.resolve_captured_at(image, now=now)

    assert resolved == dt.datetime(2026, 5, 4, 12, 0, 0)


def test_captured_at_falls_back_when_no_exif() -> None:
    image = Image.new("RGB", (100, 100), (160, 160, 160))
    now = dt.datetime(2026, 5, 4, 12, 0, 0, tzinfo=dt.timezone.utc)

    resolved = validation.resolve_captured_at(image, now=now)

    assert resolved == dt.datetime(2026, 5, 4, 12, 0, 0)


# ---------------------------------------------------------------------------
# EXIF orientation
# ---------------------------------------------------------------------------


def test_apply_exif_orientation_bakes_rotation() -> None:
    # 200×100 wide image rotated to landscape via EXIF orientation 6 should
    # come out 100×200 portrait once baked.
    base = Image.new("RGB", (200, 100), (200, 100, 50))
    exif = base.getexif()
    exif[274] = 6  # Orientation: rotate 270° CW
    buf = io.BytesIO()
    base.save(buf, format="JPEG", exif=exif.tobytes(), quality=80)
    buf.seek(0)
    image = Image.open(buf)
    image.load()

    rotated = validation.apply_exif_orientation(image)

    assert rotated.size == (100, 200)


# ---------------------------------------------------------------------------
# Derivatives
# ---------------------------------------------------------------------------


def test_make_derivative_caps_long_edge() -> None:
    image = Image.new("RGB", (3000, 2000), (128, 128, 128))

    viewer = validation.make_derivative(image, validation.VIEWER_LONG_EDGE)
    thumb = validation.make_derivative(image, validation.THUMB_LONG_EDGE)

    assert max(viewer.size) == validation.VIEWER_LONG_EDGE
    assert max(thumb.size) == validation.THUMB_LONG_EDGE


def test_make_derivative_passthrough_when_already_small() -> None:
    image = Image.new("RGB", (300, 200), (128, 128, 128))

    out = validation.make_derivative(image, validation.VIEWER_LONG_EDGE)

    assert out.size == (300, 200)


# ---------------------------------------------------------------------------
# Filename construction
# ---------------------------------------------------------------------------


def test_build_filename_shape() -> None:
    captured = dt.datetime(2026, 3, 12, 9, 14, 0)

    name = validation.build_filename(captured)

    # YYYY-MM-DD_HHHH.jpg with 4 hex chars and a .jpg extension.
    assert name.startswith("2026-03-12_")
    assert name.endswith(".jpg")
    suffix = name[len("2026-03-12_"):-len(".jpg")]
    assert len(suffix) == 4
    assert all(c in "0123456789abcdef" for c in suffix)


def test_reserve_filename_retries_on_collision(
    seeded_stations: list[str], monkeypatch: pytest.MonkeyPatch, data_root: Path
) -> None:
    """If `build_filename` returns a name whose file exists, retry."""
    captured = dt.datetime(2026, 3, 12, 9, 14, 0)

    # Pre-place a file at the first name `build_filename` will produce.
    sequence = iter(["2026-03-12_aaaa.jpg", "2026-03-12_bbbb.jpg"])
    monkeypatch.setattr(validation, "build_filename", lambda _: next(sequence))

    storage._local_photo_path("casa-do-pobo", "2026-03-12_aaaa.jpg", "viewer").parent.mkdir(
        parents=True, exist_ok=True
    )
    storage._local_photo_path("casa-do-pobo", "2026-03-12_aaaa.jpg", "viewer").write_bytes(b"x")

    name = validation.reserve_filename(captured, "casa-do-pobo")

    assert name == "2026-03-12_bbbb.jpg"


# ---------------------------------------------------------------------------
# Borderline-match logging (§7.3)
# ---------------------------------------------------------------------------


def test_log_borderline_emits_only_in_band(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="reframe.validation.borderline")

    # Below threshold = nothing.
    validation.log_borderline(
        photo_id=1, station_slug="casa-do-pobo", match_count=10, threshold=15
    )
    # Inside band — should log.
    validation.log_borderline(
        photo_id=2, station_slug="casa-do-pobo", match_count=20, threshold=15
    )
    # Far above band — silent.
    validation.log_borderline(
        photo_id=3, station_slug="casa-do-pobo", match_count=200, threshold=15
    )

    messages = [r.getMessage() for r in caplog.records]
    assert any("photo_id=2" in m and "match_count=20" in m for m in messages)
    assert not any("photo_id=1" in m for m in messages)
    assert not any("photo_id=3" in m for m in messages)


def test_log_borderline_writes_to_file_when_configured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "logs" / "borderline.log"
    new_settings = dataclasses.replace(
        config.settings, borderline_log_path=str(target)
    )
    monkeypatch.setattr(config, "settings", new_settings)

    validation.log_borderline(
        photo_id=42, station_slug="casa-do-pobo", match_count=18, threshold=15
    )

    assert target.read_text(encoding="utf-8").strip().startswith("BORDERLINE photo_id=42")


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_lookup_by_client_token_finds_existing(
    seeded_stations: list[str], db_conn: sqlite3.Connection, insert_photo
) -> None:
    insert_photo(
        "casa-do-pobo",
        "2026-04-01 09:00:00",
        client_token="my-unique-token",
        filename="2026-04-01_dead.jpg",
    )

    row = validation.lookup_by_client_token(db_conn, "my-unique-token")

    assert row is not None
    assert row["filename"] == "2026-04-01_dead.jpg"


def test_lookup_by_client_token_misses(
    seeded_stations: list[str], db_conn: sqlite3.Connection
) -> None:
    assert validation.lookup_by_client_token(db_conn, "no-such-token") is None


# ---------------------------------------------------------------------------
# Integration through POST /api/upload
# ---------------------------------------------------------------------------


def _multipart(body: bytes, filename: str = "photo.jpg", content_type: str = "image/jpeg"):
    return {"file": (filename, io.BytesIO(body), content_type)}


def test_upload_known_good_persists_and_returns_success(
    seeded_stations: list[str], make_jpeg, seed_reference_jpeg, db_conn: sqlite3.Connection
) -> None:
    seed_reference_jpeg("casa-do-pobo", seed_value=42)
    photo = make_jpeg(seed_value=42)

    resp = client.post(
        "/api/upload",
        data={"station_slug": "casa-do-pobo"},
        files=_multipart(photo),
        headers={"X-Client-Token": "tok-known-good-1"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["captured_at"].endswith("Z")
    # The photo row exists and both derivative files have been written.
    cur = db_conn.execute(
        "SELECT * FROM photo WHERE client_token = ?", ("tok-known-good-1",)
    )
    row = cur.fetchone()
    assert row is not None
    assert row["station_slug"] == "casa-do-pobo"
    for kind in ("viewer", "thumb"):
        assert storage.local_photo_path("casa-do-pobo", row["filename"], kind).is_file()


def test_upload_off_station_returns_doesnt_match(
    seeded_stations: list[str],
    make_jpeg,
    seed_reference_jpeg,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Synthetic test patterns produce far more incidental ORB matches
    # between unrelated images than real outdoor photos do (50–60 vs the
    # real-world ~5). Bump the match threshold for this test so a
    # different-seed pair reliably falls below it; this exercises the
    # rejection path independent of the production threshold value.
    monkeypatch.setattr(
        config,
        "settings",
        dataclasses.replace(config.settings, feature_match_min_matches=400),
    )

    seed_reference_jpeg("casa-do-pobo", seed_value=100)
    off_station = make_jpeg(seed_value=999)

    resp = client.post(
        "/api/upload",
        data={"station_slug": "casa-do-pobo"},
        files=_multipart(off_station),
        headers={"X-Client-Token": "tok-off-station"},
    )

    assert resp.status_code == 200
    assert resp.json() == {"ok": False, "error": "doesnt_match"}


def test_upload_blurry_returns_too_blurry(
    seeded_stations: list[str], seed_reference_jpeg
) -> None:
    seed_reference_jpeg("casa-do-pobo", seed_value=7)

    # A perfectly flat image has Laplacian variance 0 — well below the 100
    # blur threshold and simulates a deliberately-blurred submission.
    flat = Image.new("RGB", (1600, 1200), (180, 180, 180))
    buf = io.BytesIO()
    flat.save(buf, format="JPEG", quality=90)

    resp = client.post(
        "/api/upload",
        data={"station_slug": "casa-do-pobo"},
        files=_multipart(buf.getvalue()),
        headers={"X-Client-Token": "tok-blurry"},
    )

    assert resp.status_code == 200
    assert resp.json() == {"ok": False, "error": "too_blurry"}


def test_upload_wrong_file_type_returns_wrong_file_type(
    seeded_stations: list[str], seed_reference_jpeg
) -> None:
    seed_reference_jpeg("casa-do-pobo", seed_value=11)

    resp = client.post(
        "/api/upload",
        data={"station_slug": "casa-do-pobo"},
        files=_multipart(b"this is not an image"),
        headers={"X-Client-Token": "tok-not-image"},
    )

    assert resp.status_code == 200
    assert resp.json() == {"ok": False, "error": "wrong_file_type"}


def test_upload_heic_is_transcoded_and_passes(
    seeded_stations: list[str], make_jpeg, seed_reference_jpeg, db_conn: sqlite3.Connection
) -> None:
    """A HEIF/HEIC payload is transcoded by pillow-heif and validated normally."""
    import pillow_heif

    pillow_heif.register_heif_opener()

    seed_reference_jpeg("casa-do-pobo", seed_value=55)

    # Build a HEIF payload from the same pattern as the seed so the
    # transcode + matcher both succeed.
    src_bytes = make_jpeg(seed_value=55)
    src = Image.open(io.BytesIO(src_bytes))
    src.load()
    heif_buf = io.BytesIO()
    src.save(heif_buf, format="HEIF")

    resp = client.post(
        "/api/upload",
        data={"station_slug": "casa-do-pobo"},
        files=_multipart(heif_buf.getvalue(), filename="photo.heic", content_type="image/heic"),
        headers={"X-Client-Token": "tok-heic"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    # Stored derivative is a JPEG regardless of the .heic upload extension.
    assert body["filename"].endswith(".jpg")


def test_upload_idempotent_replay_returns_prior_response(
    seeded_stations: list[str], make_jpeg, seed_reference_jpeg, db_conn: sqlite3.Connection
) -> None:
    seed_reference_jpeg("casa-do-pobo", seed_value=200)
    photo = make_jpeg(seed_value=200)
    headers = {"X-Client-Token": "tok-idempotent"}

    first = client.post(
        "/api/upload",
        data={"station_slug": "casa-do-pobo"},
        files=_multipart(photo),
        headers=headers,
    )
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["ok"] is True

    # Replay — exactly the same client token. Phase 4's client reuses the
    # token across retries so this stands in for a network/server retry.
    second = client.post(
        "/api/upload",
        data={"station_slug": "casa-do-pobo"},
        files=_multipart(photo),
        headers=headers,
    )
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["ok"] is True
    assert second_body["id"] == first_body["id"]
    assert second_body["filename"] == first_body["filename"]

    # Crucially: only one row was inserted.
    cur = db_conn.execute(
        "SELECT COUNT(*) AS n FROM photo WHERE client_token = ?", ("tok-idempotent",)
    )
    assert int(cur.fetchone()["n"]) == 1


def test_upload_unknown_station_is_404(
    seeded_stations: list[str], make_jpeg
) -> None:
    resp = client.post(
        "/api/upload",
        data={"station_slug": "no-such-station"},
        files=_multipart(make_jpeg()),
        headers={"X-Client-Token": "tok-bad-station"},
    )

    assert resp.status_code == 404


def test_upload_missing_client_token_is_server_error(
    seeded_stations: list[str], make_jpeg
) -> None:
    resp = client.post(
        "/api/upload",
        data={"station_slug": "casa-do-pobo"},
        files=_multipart(make_jpeg()),
    )

    assert resp.status_code == 500
    assert resp.json() == {"ok": False, "error": "server_error"}


def test_upload_with_no_reference_set_fails_closed(
    seeded_stations: list[str], make_jpeg
) -> None:
    """A station with neither seeds nor active photos rejects all uploads.

    An empty reference set is an unconfigured-station condition, not a
    visitor error — it surfaces as `not_ready` rather than blaming the photo
    with `doesnt_match`.
    """
    resp = client.post(
        "/api/upload",
        data={"station_slug": "casa-do-pobo"},
        files=_multipart(make_jpeg()),
        headers={"X-Client-Token": "tok-no-refs"},
    )

    assert resp.status_code == 200
    assert resp.json() == {"ok": False, "error": "not_ready"}


def test_process_upload_skip_match_bypasses_feature_check(
    seeded_stations: list[str],
    make_jpeg,
    db_conn: sqlite3.Connection,
) -> None:
    # No active reference set (no photos for this station). A normal
    # upload would fail-closed with not_ready; skip_match=True
    # bootstraps the station.
    body = make_jpeg(seed_value=11)
    result = validation.process_upload(
        conn=db_conn,
        station_slug="casa-do-pobo",
        client_token="admin-bootstrap-1",
        file_bytes=body,
        skip_match=True,
    )
    assert result.photo_id is not None

    row = db_conn.execute(
        "SELECT viewer_path FROM photo WHERE id = ?", (result.photo_id,)
    ).fetchone()
    assert row["viewer_path"].startswith("photos/casa-do-pobo/viewer/")


def test_soft_deleted_photo_drops_from_active_reference_set(
    seeded_stations: list[str],
    make_jpeg,
    seed_reference_jpeg,
    db_conn: sqlite3.Connection,
) -> None:
    """An admin takedown removes a photo from the matcher's reference set.

    Plant an admin seed photo (matches against itself), upload a matching
    community photo, then soft-delete BOTH. With no photos left, the next
    upload has nothing to match against.
    """
    seed_reference_jpeg("casa-do-pobo", seed_value=300)

    photo_a = make_jpeg(seed_value=301)
    first = client.post(
        "/api/upload",
        data={"station_slug": "casa-do-pobo"},
        files=_multipart(photo_a),
        headers={"X-Client-Token": "tok-a"},
    )
    assert first.status_code == 200 and first.json()["ok"] is True

    # Soft-delete every photo for the station — leaves an empty active set.
    db_conn.execute(
        "UPDATE photo SET removed_at = CURRENT_TIMESTAMP "
        "WHERE station_slug = ?",
        ("casa-do-pobo",),
    )

    # A second matching photo now has nothing to match against.
    photo_b = make_jpeg(seed_value=301, width=1601, height=1201)
    second = client.post(
        "/api/upload",
        data={"station_slug": "casa-do-pobo"},
        files=_multipart(photo_b),
        headers={"X-Client-Token": "tok-b"},
    )
    assert second.status_code == 200
    assert second.json() == {"ok": False, "error": "not_ready"}


# ---------------------------------------------------------------------------
# Size / resolution rejections carry their own codes (not wrong_file_type)
# ---------------------------------------------------------------------------


def test_check_resolution_raises_too_small() -> None:
    """A valid-but-tiny image is `too_small`, not `wrong_file_type`."""
    small = Image.new("RGB", (400, 300), (180, 180, 180))
    with pytest.raises(validation.ValidationFailure) as exc:
        validation.check_resolution(small, min_long_edge=800)

    assert exc.value.code == validation.ERR_TOO_SMALL


def test_process_upload_oversized_raises_too_large(
    seeded_stations: list[str],
    make_jpeg,
    db_conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An over-cap payload is `too_large`, not `wrong_file_type`."""
    monkeypatch.setattr(validation, "MAX_UPLOAD_BYTES", 16)

    with pytest.raises(validation.ValidationFailure) as exc:
        validation.process_upload(
            conn=db_conn,
            station_slug="casa-do-pobo",
            client_token="tok-too-large",
            file_bytes=make_jpeg(),
            skip_match=True,
        )

    assert exc.value.code == validation.ERR_TOO_LARGE


def test_upload_low_resolution_returns_too_small(
    seeded_stations: list[str], make_jpeg
) -> None:
    """Integration: the resolution check (step 8a) runs before the matcher, so
    a tiny image surfaces `too_small` regardless of the reference set."""
    resp = client.post(
        "/api/upload",
        data={"station_slug": "casa-do-pobo"},
        files=_multipart(make_jpeg(width=400, height=300)),
        headers={"X-Client-Token": "tok-low-res"},
    )

    assert resp.status_code == 200
    assert resp.json() == {"ok": False, "error": "too_small"}


# ---------------------------------------------------------------------------
# Persistence faults: no orphaned files; post-save steps are non-fatal
# ---------------------------------------------------------------------------


class _InsertFailingConn:
    """Delegates everything to a real connection but fails any INSERT."""

    def __init__(self, real: sqlite3.Connection) -> None:
        self._real = real

    def execute(self, sql, *args, **kwargs):
        if str(sql).lstrip().upper().startswith("INSERT"):
            raise sqlite3.OperationalError("disk I/O error")
        return self._real.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_upload_insert_failure_cleans_up_derivatives(
    seeded_stations: list[str], make_jpeg, db_conn: sqlite3.Connection
) -> None:
    """A non-race INSERT failure must not orphan the viewer/thumb files."""
    viewer_dir = storage.local_photo_path("casa-do-pobo", "x.jpg", "viewer").parent
    thumb_dir = storage.local_photo_path("casa-do-pobo", "x.jpg", "thumb").parent

    with pytest.raises(sqlite3.OperationalError):
        validation.process_upload(
            conn=_InsertFailingConn(db_conn),
            station_slug="casa-do-pobo",
            client_token="tok-insert-fail",
            file_bytes=make_jpeg(),
            skip_match=True,
        )

    assert list(viewer_dir.glob("*.jpg")) == []
    assert list(thumb_dir.glob("*.jpg")) == []


def test_borderline_log_failure_does_not_fail_upload(
    seeded_stations: list[str],
    make_jpeg,
    db_conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The photo is committed before borderline logging; a log-write fault is
    swallowed rather than turning a saved photo into a server_error."""

    def _boom(**_kwargs):
        raise RuntimeError("borderline log path unwritable")

    monkeypatch.setattr(validation, "log_borderline", _boom)

    result = validation.process_upload(
        conn=db_conn,
        station_slug="casa-do-pobo",
        client_token="tok-borderline-fail",
        file_bytes=make_jpeg(),
        skip_match=True,
    )

    assert result.photo_id is not None
    row = db_conn.execute(
        "SELECT 1 FROM photo WHERE id = ?", (result.photo_id,)
    ).fetchone()
    assert row is not None
